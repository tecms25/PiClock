# -*- coding: utf-8 -*-                 # NOQA

import datetime
import hashlib
import json
import locale
import math
import os
import platform
import random
import signal
import sys
import time
import traceback
import dateutil.parser
import pytz
import tzlocal
from subprocess import Popen
from urllib.parse import urlparse
from PyQt6 import QtGui, QtCore, QtNetwork, QtWidgets
from PyQt6.QtCore import QUrl
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QPainter, QImage, QFont
from PyQt6.QtGui import QPixmap, QBrush, QColor
from PyQt6.QtNetwork import QNetworkReply
from PyQt6.QtNetwork import QNetworkRequest
from tzfpy import get_tz

sys.dont_write_bytecode = True
from GoogleMercatorProjection import get_corners, get_point, get_tile_xy, LatLng  # NOQA
import ApiKeys  # NOQA


def _qt_message_handler(msg_type, context, message):
    # "QIODevice::read (QSslSocket): device not open" is harmless Qt
    # networking noise: it happens when a pooled keep-alive HTTPS connection
    # gets closed by the remote server between requests. Qt's own network
    # backend detects this and transparently reconnects, so it's silently
    # dropped here instead of spamming the console every few minutes.
    if 'device not open' in message:
        return
    sys.stderr.write(message + '\n')


QtCore.qInstallMessageHandler(_qt_message_handler)

# --- Short-lived disk cache for weather/radar API responses ---
# Repeatedly restarting the app (e.g. during development) would otherwise
# re-issue every weather/radar API call on every launch; this replays a
# recent-enough response from disk instead, independent of whatever caching
# headers (if any) a given API happens to send.
API_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api_cache')
os.makedirs(API_CACHE_DIR, exist_ok=True)


def api_cache_path(url):
    return os.path.join(API_CACHE_DIR, hashlib.sha1(url.encode('utf-8')).hexdigest() + '.cache')


def api_cache_read(url, max_age_seconds):
    """Return cached response bytes for url if a fresh-enough entry exists on disk, else None."""
    path = api_cache_path(url)
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return None
    if age > max_age_seconds:
        return None
    try:
        with open(path, 'rb') as f:
            return f.read()
    except OSError:
        return None


def api_cache_write(url, data):
    try:
        with open(api_cache_path(url), 'wb') as f:
            f.write(data)
    except OSError as e:
        print(f'WARNING: unable to write API cache for {url}: {e}')


# Ceiling well beyond any max_age used by an api_cache_read() call (the
# longest is Config.weather_refresh, typically 15 min); anything still
# fresh enough to ever be read is never this old, so the sweep only ever
# removes entries that have already aged out and can no longer be reused.
API_CACHE_SWEEP_MAX_AGE_SECONDS = 60 * 60
API_CACHE_SWEEP_INTERVAL_MS = 60 * 60 * 1000


def api_cache_cleanup():
    """Delete API_CACHE_DIR entries older than API_CACHE_SWEEP_MAX_AGE_SECONDS.

    Without this, api_cache/ grows forever: every distinct radar frame/tile
    URL gets its own file, RainViewer publishes a brand-new one every 10
    minutes, and nothing else ever removes old entries.
    """
    try:
        entries = os.listdir(API_CACHE_DIR)
    except OSError as e:
        print(f'WARNING: unable to list API cache dir for cleanup: {e}')
        return
    now = time.time()
    removed = 0
    for name in entries:
        path = os.path.join(API_CACHE_DIR, name)
        try:
            if now - os.path.getmtime(path) > API_CACHE_SWEEP_MAX_AGE_SECONDS:
                os.remove(path)
                removed += 1
        except OSError as e:
            print(f'WARNING: unable to remove stale API cache file {name}: {e}')
    if removed:
        print(f'INFO: API cache cleanup removed {removed} stale file(s)')


# --- Daily log rotation (at local midnight), keeping PyQtPiClock.1.log ... .7.log ---
class _DailyRotatingLineLogger:
    def __init__(self, log_path: str, keep: int = 7, tee_to=None):
        self.log_path = os.path.abspath(log_path)
        self.keep = keep
        self.tee_to = tee_to  # optional stream (e.g., original stdout)
        self._tz = tzlocal.get_localzone()
        self._buf = ""
        self._cur_date = datetime.datetime.now(tz=self._tz).date()
        self._fh = None
        self._open_for_today(rotate_on_open=True)

    def _open_for_today(self, rotate_on_open: bool):
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        if rotate_on_open and os.path.exists(self.log_path):
            self._rotate_files()
        self._fh = open(self.log_path, "a", encoding="utf-8", buffering=1)

    def _rotate_files(self):
        try:
            if self._fh:
                self._fh.flush()
                self._fh.close()
        except Exception:
            pass

        # shift .6 -> .7, ... .1 -> .2, current -> .1 (we always write to .1)
        for i in range(self.keep, 1, -1):
            src = self.log_path.replace(".1.log", f".{i - 1}.log")
            dst = self.log_path.replace(".1.log", f".{i}.log")
            try:
                if os.path.exists(dst):
                    os.remove(dst)
                if os.path.exists(src):
                    os.replace(src, dst)
            except OSError:
                pass

    def _maybe_rollover(self):
        today = datetime.datetime.now(tz=self._tz).date()
        if today != self._cur_date:
            self._cur_date = today
            self._rotate_files()
            self._open_for_today(rotate_on_open=False)

    def _timestamp_prefix(self) -> str:
        now = datetime.datetime.now(tz=self._tz)
        return now.strftime("%F %T.%f %Z (UTC%z) - ")

    def write(self, s: str):
        if not s:
            return
        self._maybe_rollover()
        self._buf += s

        while True:
            nl = self._buf.find("\n")
            if nl < 0:
                break
            line = self._buf[:nl]
            self._buf = self._buf[nl + 1:]

            out = self._timestamp_prefix() + line + "\n"
            try:
                self._fh.write(out)
            except Exception:
                pass

            if self.tee_to is not None:
                try:
                    self.tee_to.write(out)
                except Exception:
                    pass

    def flush(self):
        self._maybe_rollover()
        if self._buf:
            # flush partial line without forcing a newline
            try:
                out = self._timestamp_prefix() + self._buf
                self._fh.write(out)
            except Exception:
                pass
            if self.tee_to is not None:
                try:
                    self.tee_to.write(out)
                except Exception:
                    pass
            self._buf = ""
        try:
            if self._fh:
                self._fh.flush()
        except Exception:
            pass
        if self.tee_to is not None:
            try:
                self.tee_to.flush()
            except Exception:
                pass

    def close(self):
        try:
            self.flush()
        finally:
            try:
                if self._fh:
                    self._fh.close()
            except Exception:
                pass


def _setup_daily_log_if_enabled():
    if os.environ.get("PICLOCK_DAILY_LOG", "").strip() not in ("1", "true", "True", "yes", "YES"):
        return
    try:
        # Expect to be run from Clock/ (startup.sh does cd Clock)
        log_file = os.path.join(os.getcwd(), "PyQtPiClock.1.log")
        logger = _DailyRotatingLineLogger(log_file, keep=7, tee_to=None)
        sys.stdout = logger
        sys.stderr = logger
        import atexit
        atexit.register(logger.close)
    except Exception:
        # If anything goes wrong, fall back to normal stdout/stderr.
        pass


_setup_daily_log_if_enabled()


# --- end daily log rotation setup ---

class SunTimes:
    def __init__(self, lat, lng, tz):
        self.lat = lat
        self.lng = lng
        self.tz = tz

    def sunrise(self, when=None):
        if when is None:
            when = datetime.datetime.now(tz=tzlocal.get_localzone())
        # datetime at local coordinates
        when = when.astimezone(tz=self.tz)
        self.__preptime(when)
        self.__calc()
        # time part of sunrise at local coordinates
        sunrise_t = SunTimes.__timefromdecimalday(self.sunrise_t)
        # complete datetime of sunrise at local coordinates
        sunrise_dt = datetime.datetime.combine(when.date(), sunrise_t, when.tzinfo)
        # return datetime of sunrise in the designated system timezone
        return sunrise_dt.astimezone(tzlocal.get_localzone())

    def sunset(self, when=None):
        if when is None:
            when = datetime.datetime.now(tz=tzlocal.get_localzone())
        # datetime at local coordinates
        when = when.astimezone(tz=self.tz)
        self.__preptime(when)
        self.__calc()
        # time part of sunset at local coordinates
        sunset_t = SunTimes.__timefromdecimalday(self.sunset_t)
        # complete datetime of sunset at local coordinates
        sunset_dt = datetime.datetime.combine(when.date(), sunset_t, when.tzinfo)
        # return datetime of sunset in designated system timezone
        return sunset_dt.astimezone(tzlocal.get_localzone())

    @staticmethod
    def __timefromdecimalday(day):
        hours = 24.0 * day
        h = int(hours)
        minutes = (hours - h) * 60
        m = int(minutes)
        seconds = (minutes - m) * 60
        s = int(seconds)
        return datetime.time(hour=h, minute=m, second=s)

    def __preptime(self, when):
        # datetime days are numbered in the Gregorian calendar
        # while the calculations from NOAA are distributed as
        # OpenOffice spreadsheets with days numbered from
        # 1/1/1900. The difference are those numbers taken for
        # 18/12/2010
        self.day = when.toordinal() - (734124 - 40529)
        t = when.time()
        self.time = (t.hour + t.minute / 60.0 + t.second / 3600.0) / 24.0

        self.timezone = 0
        offset = when.utcoffset()
        if offset is not None:
            self.timezone = offset.seconds / 3600.0 + (offset.days * 24)

    def __calc(self):
        timezone = self.timezone  # in hours, east is positive
        longitude = self.lng  # in decimal degrees, east is positive
        latitude = self.lat  # in decimal degrees, north is positive

        time = self.time  # percentage past midnight, i.e. noon  is 0.5
        day = self.day  # daynumber 1=1/1/1900

        j_day = day + 2415018.5 + time - timezone / 24  # Julian day
        j_cent = (j_day - 2451545) / 36525  # Julian century

        m_anon = 357.52911 + j_cent * (35999.05029 - 0.0001537 * j_cent)
        m_long = 280.46646 + j_cent * (36000.76983 + j_cent * 0.0003032) % 360
        eccent = 0.016708634 - j_cent * (0.000042037 + 0.0001537 * j_cent)
        m_obliq = (23 + (26 + ((21.448 - j_cent * (46.815 + j_cent *
                                                   (0.00059 - j_cent * 0.001813)))) / 60) / 60)
        obliq = (m_obliq + 0.00256 *
                 math.cos(math.radians(125.04 - 1934.136 * j_cent)))
        vary = (math.tan(math.radians(obliq / 2)) *
                math.tan(math.radians(obliq / 2)))
        s_eqcent = (math.sin(math.radians(m_anon)) *
                    (1.914602 - j_cent * (0.004817 + 0.000014 * j_cent)) +
                    math.sin(math.radians(2 * m_anon))
                    * (0.019993 - 0.000101 * j_cent) +
                    math.sin(math.radians(3 * m_anon)) * 0.000289)
        s_truelong = m_long + s_eqcent
        s_applong = (s_truelong - 0.00569 - 0.00478 *
                     math.sin(math.radians(125.04 - 1934.136 * j_cent)))
        declination = (math.degrees(math.asin(math.sin(math.radians(obliq)) *
                                              math.sin(math.radians(s_applong)))))

        eqtime = (4 * math.degrees(vary * math.sin(2 * math.radians(m_long)) -
                                   2 * eccent * math.sin(math.radians(m_anon)) + 4 * eccent *
                                   vary * math.sin(math.radians(m_anon)) *
                                   math.cos(2 * math.radians(m_long)) - 0.5 * vary * vary *
                                   math.sin(4 * math.radians(m_long)) - 1.25 * eccent * eccent *
                                   math.sin(2 * math.radians(m_anon))))

        hourangle0 = (math.cos(math.radians(90.833)) /
                      (math.cos(math.radians(latitude)) *
                       math.cos(math.radians(declination))) -
                      math.tan(math.radians(latitude)) *
                      math.tan(math.radians(declination)))

        self.solarnoon_t = (720 - 4 * longitude - eqtime + timezone * 60) / 1440
        # sun never sets
        if hourangle0 > 1.0:
            self.sunrise_t = 0.0
            self.sunset_t = 1.0 - 1.0 / 86400.0
            return
        if hourangle0 < -1.0:
            self.sunrise_t = 0.0
            self.sunset_t = 0.0
            return

        hourangle = math.degrees(math.acos(hourangle0))

        self.sunrise_t = self.solarnoon_t - hourangle * 4 / 1440
        self.sunset_t = self.solarnoon_t + hourangle * 4 / 1440


# https://gist.github.com/miklb/ed145757971096565723
def moon_phase(dt=None):
    if dt is None:
        dt = datetime.datetime.now()
    diff = dt - datetime.datetime(2001, 1, 1)
    days = float(diff.days) + (float(diff.seconds) / 86400.0)
    lunations = 0.20439731 + float(days) * 0.03386319269
    return lunations % 1.0


def tick():
    global lastmin, lastday, lasttimestr
    global clockrect
    global datex, datex2, datey2, pdy
    global sun, daytime, sunrise, sunset
    global bottom

    now = datetime.datetime.now(tz=tzlocal.get_localzone())
    timestr = Config.digitalformat.format(now)
    if Config.digitalformat.find('%I') > -1:
        if timestr[0] == '0':
            timestr = timestr[1:99]
    if lasttimestr != timestr:
        clockface.setText(timestr.lower())
    lasttimestr = timestr

    dy = Config.digitalformat2.format(now)
    if Config.digitalformat2.find('%I') > -1:
        if dy[0] == '0':
            dy = dy[1:99]
    if dy != pdy:
        pdy = dy
        datey2.setText(dy)

    if now.minute != lastmin:
        lastmin = now.minute
        if sunrise <= now <= sunset:
            daytime = True
        else:
            daytime = False

    if now.day != lastday:
        lastday = now.day
        # date
        sup = 'th'
        if now.day == 1 or now.day == 21 or now.day == 31:
            sup = 'st'
        if now.day == 2 or now.day == 22:
            sup = 'nd'
        if now.day == 3 or now.day == 23:
            sup = 'rd'
        if Config.DateLocale != '':
            sup = ''
        ds = '{0:%A %B} {0.day}<sup>{1}</sup> {0.year}'.format(now, sup)
        ds2 = '{0:%a %b} {0.day}<sup>{1}</sup> {0.year}'.format(now, sup)
        datex.setText(ds)
        datex2.setText(ds2)
        dt = datetime.datetime.now(tz=tzlocal.get_localzone())
        sunrise = sun.sunrise(dt)
        sunset = sun.sunset(dt)
        bottomtext = ''
        bottomtext += (Config.LSunRise +
                       '{0:%-I:%M %p}'.format(sunrise) +
                       Config.LSet +
                       '{0:%-I:%M %p}'.format(sunset))
        bottomtext += (Config.LMoonPhase + phase(moon_phase()))
        bottom.setText(bottomtext)


CURSOR_POLL_MS = 250
cursor_hidden = False
cursor_last_pos = None
cursor_idle_elapsed = 0.0


def cursor_idle_tick():
    """Hide the mouse cursor after a period of inactivity, show it again on movement.

    Polls the global cursor position instead of relying on a platform-specific
    tool, so it behaves the same on every OS.
    """
    global cursor_hidden, cursor_last_pos, cursor_idle_elapsed

    if Config.cursor_idle_seconds <= 0:
        return

    pos = QtGui.QCursor.pos()
    if pos != cursor_last_pos:
        cursor_last_pos = pos
        cursor_idle_elapsed = 0.0
        if cursor_hidden:
            QtWidgets.QApplication.restoreOverrideCursor()
            cursor_hidden = False
        return

    cursor_idle_elapsed += CURSOR_POLL_MS / 1000.0
    if cursor_idle_elapsed >= Config.cursor_idle_seconds and not cursor_hidden:
        QtWidgets.QApplication.setOverrideCursor(Qt.CursorShape.BlankCursor)
        cursor_hidden = True


def tempfinished():
    global tempreply, temp
    tempreply.deleteLater()
    if tempreply.error() != QNetworkReply.NetworkError.NoError:
        return
    tempstr = str(tempreply.readAll(), 'utf-8')
    try:
        tempdata = json.loads(tempstr)
    except ValueError:  # includes json.decoder.JSONDecodeError
        print('WARNING:', traceback.format_exc())
        print('WARNING: Response from localhost: ' + tempstr)
        print('WARNING: Moving on...')
        return  # ignore and try again on the next refresh

    if tempdata['temp'] == '':
        return
    if Config.metric:
        s = Config.LInsideTemp + '%.1f' % tempf2tempc(float(tempdata['temp'])) + u'°C'
        if tempdata['temps']:
            if len(tempdata['temps']) > 1:
                s = ''
                for tk in tempdata['temps']:
                    s += ' ' + tk + ': ' + '%.1f' % tempf2tempc(float(tempdata['temps'][tk])) + u'°C'
    else:
        s = Config.LInsideTemp + tempdata['temp'] + u'°F'
        if tempdata['temps']:
            if len(tempdata['temps']) > 1:
                s = ''
                for tk in tempdata['temps']:
                    s += ' ' + tk + ': ' + tempdata['temps'][tk] + u'°F'
    temp.setText(s)


def tempf2tempc(f):
    return (f - 32) / 1.8  # temperature degrees Fahrenheit to degrees Celsius


def mph2kph(f):
    return f * 1.609  # speed MPH to km/h


def mbar2inhg(f):
    return f / 33.864  # pressure millibars to inHg


def inhg2mbar(f):
    return f * 33.864  # pressure inHg to millibars


def inches2mm(f):
    return f * 25.4  # height inches to millimeters


def mm2inches(f):
    return f / 25.4  # height millimeters to inches


def phase(f):
    pp = Config.Lmoon1  # 'New Moon'
    if f > 0.9375:
        pp = Config.Lmoon1  # 'New Moon'
    elif f > 0.8125:
        pp = Config.Lmoon8  # 'Waning Crescent'
    elif f > 0.6875:
        pp = Config.Lmoon7  # 'Third Quarter'
    elif f > 0.5625:
        pp = Config.Lmoon6  # 'Waning Gibbous'
    elif f > 0.4375:
        pp = Config.Lmoon5  # 'Full Moon'
    elif f > 0.3125:
        pp = Config.Lmoon4  # 'Waxing Gibbous'
    elif f > 0.1875:
        pp = Config.Lmoon3  # 'First Quarter'
    elif f > 0.0625:
        pp = Config.Lmoon2  # 'Waxing Crescent'
    return pp


def bearing(f):
    wd = 'N'
    if f > 22.5:
        wd = 'NE'
    if f > 67.5:
        wd = 'E'
    if f > 112.5:
        wd = 'SE'
    if f > 157.5:
        wd = 'S'
    if f > 202.5:
        wd = 'SW'
    if f > 247.5:
        wd = 'W'
    if f > 292.5:
        wd = 'NW'
    if f > 337.5:
        wd = 'N'
    return wd


def gettemp():
    global tempreply
    host = 'localhost'
    if platform.uname()[1] == 'KW81':
        host = 'piclock.local'  # this is here just for testing
    r = QUrl('http://' + host + ':48213/temp')
    r = QNetworkRequest(r)
    tempreply = manager.get(r)
    tempreply.finished.connect(tempfinished)



def getmost(a):
    b = dict((i, a.count(i)) for i in a)  # list to key and counts
    # print('INFO:', 'getmost', b)
    c = sorted(b, key=b.get)  # sort by counts
    return c[-1]  # get last (most counted) item


tm_code_map = {
    0: 'Unknown',
    1000: 'Clear',
    1100: 'Mostly Clear',
    1101: 'Partly Cloudy',
    1102: 'Mostly Cloudy',
    1001: 'Cloudy',
    2000: 'Fog',
    2100: 'Light Fog',
    4000: 'Drizzle',
    4001: 'Rain',
    4200: 'Light Rain',
    4201: 'Heavy Rain',
    5000: 'Snow',
    5001: 'Flurries',
    5100: 'Light Snow',
    5101: 'Heavy Snow',
    6000: 'Freezing Drizzle',
    6001: 'Freezing Rain',
    6200: 'Light Freezing Rain',
    6201: 'Heavy Freezing Rain',
    7000: 'Ice Pellets',
    7101: 'Heavy Ice Pellets',
    7102: 'Light Ice Pellets',
    8000: 'Thunderstorm'
}

tm_code_icons = {
    0: 'Unknown',
    1000: 'clear-day',
    1100: 'partly-cloudy-day',
    1101: 'partly-cloudy-day',
    1102: 'partly-cloudy-day',
    1001: 'cloudy',
    2000: 'fog',
    2100: 'fog',
    4000: 'sleet',
    4001: 'rain',
    4200: 'rain',
    4201: 'rain',
    5000: 'snow',
    5001: 'snow',
    5100: 'snow',
    5101: 'snow',
    6000: 'sleet',
    6001: 'sleet',
    6200: 'sleet',
    6201: 'sleet',
    7000: 'sleet',
    7101: 'sleet',
    7102: 'sleet',
    8000: 'thunderstorm'
}


def wxfinished_tm_current(data=None):
    global wxreply
    global wxicon, temper, wxdesc, press, humidity
    global wind, feelslike, wdate
    global wxicon2, temper2, wxdesc2
    global daytime

    if data is None:
        wxreply.deleteLater()
        data = bytes(wxreply.readAll())
        api_cache_write(wxreply.url().toString(), data)
    wxstr = str(data, 'utf-8')

    try:
        wxdata = json.loads(wxstr)
    except ValueError:  # includes json.decoder.JSONDecodeError
        print('WARNING:', traceback.format_exc())
        print('WARNING: Response from api.tomorrow.io: ' + wxstr)
        print('WARNING: Moving on...')
        return  # ignore and try again on the next refresh

    if 'message' in wxdata:
        print('ERROR: Response from api.tomorrow.io: ' + str(wxdata['code']) + ' - ' + str(wxdata['type']) + ' - ' +
              str(wxdata['message']))
        return

    f = wxdata['data']['timelines'][0]['intervals'][0]
    dt = dateutil.parser.parse(f['startTime']).astimezone(tzlocal.get_localzone())
    icon = f['values']['weatherCode']
    icon = tm_code_icons[icon]
    if not daytime:
        icon = icon.replace('-day', '-night')
    wxiconpixmap = QtGui.QPixmap(Config.icons + '/' + icon + '.png')
    wxicon.setPixmap(wxiconpixmap.scaled(
        wxicon.width(), wxicon.height(), Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation))
    wxicon2.setPixmap(wxiconpixmap.scaled(
        wxicon.width(),
        wxicon.height(),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation))
    wxdesc.setText(tm_code_map[f['values']['weatherCode']])
    wxdesc2.setText(tm_code_map[f['values']['weatherCode']])

    if Config.wind_degrees:
        wd = str(f['values']['windDirection']) + u'°'
    else:
        wd = bearing(f['values']['windDirection'])

    if Config.metric:
        temper.setText('%.1f' % (tempf2tempc(f['values']['temperature'])) + u'°C')
        temper2.setText('%.1f' % (tempf2tempc(f['values']['temperature'])) + u'°C')
        wind.setText(Config.LWind + wd + ' ' +
                     '%.1f' % (mph2kph(f['values']['windSpeed'])) + 'km/h' +
                     Config.Lgusting +
                     '%.1f' % (mph2kph(f['values']['windGust'])) + 'km/h')
        feelslike.setText(Config.LFeelslike +
                          '%.1f' % (tempf2tempc(f['values']['temperatureApparent'])) + u'°C')
    else:
        temper.setText('%.1f' % (f['values']['temperature']) + u'°F')
        temper2.setText('%.1f' % (f['values']['temperature']) + u'°F')
        wind.setText(Config.LWind +
                     wd + ' ' +
                     '%.1f' % (f['values']['windSpeed']) + ' mph |' +
                     Config.Lgusting +
                     '%.1f' % (f['values']['windGust']) + ' mph')
        feelslike.setText(Config.LFeelslike +
                          '%.1f' % (f['values']['temperatureApparent']) + u'°F')

    press_inhg = f['values']['pressureSeaLevel']
    if Config.pressure_mbar:
        pressure_str = Config.LPressure + '%.1f' % inhg2mbar(press_inhg) + 'mbar'
    else:
        pressure_str = Config.LPressure + '%.2f' % press_inhg + ' inHg'
    # Sets the label text and feeds the raw reading into the pressure trend history.
    set_pressure_label(pressure_str, press_inhg)

    humidity.setText(Config.LHumidity + '%.0f%%' % (f['values']['humidity']))
    wdate.setText('Last Updated: {0:%-I:%M %p}'.format(dt))


def wxfinished_tm_hourly(data=None):
    global wxreply2, forecast
    global daytime, attribution

    attribution.setText('')
    attribution2.setText('')

    if data is None:
        wxreply2.deleteLater()
        data = bytes(wxreply2.readAll())
        api_cache_write(wxreply2.url().toString(), data)
    wxstr2 = str(data, 'utf-8')

    try:
        wxdata2 = json.loads(wxstr2)
    except ValueError:  # includes json.decoder.JSONDecodeError
        print('WARNING:', traceback.format_exc())
        print('WARNING: Response from api.tomorrow.io: ' + wxstr2)
        print('WARNING: Moving on...')
        return  # ignore and try again on the next refresh

    if 'message' in wxdata2:
        print('ERROR: Response from api.tomorrow.io: ' + str(wxdata2['code']) + ' - ' + wxdata2['type'] + ' - ' +
              wxdata2['message'])
        return

    for i in range(0, 3):
        f = wxdata2['data']['timelines'][0]['intervals'][i * 3 + 2]
        fl = forecast[i]
        wicon = f['values']['weatherCode']
        wicon = tm_code_icons[wicon]

        dt = dateutil.parser.parse(f['startTime']).astimezone(tzlocal.get_localzone())
        if dt.day == datetime.datetime.now().day:
            fdaytime = daytime
        else:
            fsunrise = sun.sunrise(dt)
            fsunset = sun.sunset(dt)
            if fsunrise <= dt <= fsunset:
                fdaytime = True
            else:
                fdaytime = False

        if not fdaytime:
            wicon = wicon.replace('-day', '-night')
        icon = fl.findChild(QtWidgets.QLabel, 'icon')
        wxiconpixmap = QtGui.QPixmap(Config.icons + '/' + wicon + '.png')
        icon.setPixmap(wxiconpixmap.scaled(
            icon.width(),
            icon.height(),
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        wx = fl.findChild(QtWidgets.QLabel, 'wx')
        day = fl.findChild(QtWidgets.QLabel, 'day')
        day.setText('{0:%A %-I:%M %p} '.format(dt))
        s = ''
        pop = float(f['values']['precipitationProbability'])
        ptype = float(f['values']['precipitationType'])
        saccum = float(f['values']['snowAccumulationAvg'])
        raccum = float(f['values']['rainAccumulationAvg'])

        if Config.metric:
            s += '%.0f' % tempf2tempc(f['values']['temperature']) + u'°C '
        else:
            s += '%.0f' % (f['values']['temperature']) + u'°F '

        # If precipitationProbality is greater than 0% but no accumulation show rain or snow with probability percentage.
        # If no precip type or no precip forcated, show No Precipitation

        if pop >= 1 and ptype > 0:
            if ptype == 1 and raccum < 0.10 and saccum < 0.10:
                s += Config.LRain + '%.0f' % pop + '%'
            elif ptype == 2 and saccum < 0.10 and raccum < 0.10:
                s += Config.LSnow + '%.0f' % pop + '%'
#        if pop >=1 and ptype == 0:
#            s += 'No Precipitation'                
#        if pop == 0:
#            s += 'No Precipitation'

        # Logic to show rain or snow probability, followed by projected accumulations in forecast

        if Config.metric:
            if ptype == 2:
                if saccum >= 0.10:
                    s += Config.LSnow + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % inches2mm(saccum) + ' mm'
                else:
                    if raccum >= 0.10:
                        s += Config.LRain + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % inches2mm(raccum) + ' mm'
            else:
                if raccum >= 0.10:
                    s += Config.LRain + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % inches2mm(raccum) + ' mm'
                else:
                    if saccum >= 0.10:
                        s += Config.LSnow + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % inches2mm(saccum) + ' mm'
        else:
            if ptype == 2:
                if saccum >= 0.10:
                    s += Config.LSnow + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % saccum + ' in'
                else:
                    if raccum >= 0.10:
                        s += Config.LRain + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % raccum + ' in'
            else:
                if raccum >= 0.10:
                    s += Config.LRain + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % raccum + ' in'
                else:
                    if saccum >= 0.10:
                        s += Config.LSnow + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % saccum + ' in'

        wx.setStyleSheet('#wx { font-size: ' + str(int(17 * xscale * Config.fontmult)) + 'px; }')
        if pop >=1 and (saccum >= 0.10 or raccum >= 0.10):
            wx.setText(tm_code_map[f['values']['weatherCode']] + '\n' + s)
        else:
            wx.setText('\n' + tm_code_map[f['values']['weatherCode']] + '\n' + s)


def wxfinished_tm_daily(data=None):
    global wxreply3, forecast

    if data is None:
        wxreply3.deleteLater()
        data = bytes(wxreply3.readAll())
        api_cache_write(wxreply3.url().toString(), data)
    wxstr3 = str(data, 'utf-8')

    try:
        wxdata3 = json.loads(wxstr3)
    except ValueError:  # includes json.decoder.JSONDecodeError
        print('WARNING:', traceback.format_exc())
        print('WARNING: Response from api.tomorrow.io: ' + wxstr3)
        print('WARNING: Moving on...')
        return  # ignore and try again on the next refresh

    if 'message' in wxdata3:
        print('ERROR: Response from api.tomorrow.io: ' + str(wxdata3['code']) + ' - ' + wxdata3['type'] + ' - ' +
              wxdata3['message'])
        return

    dt = dateutil.parser.parse(wxdata3['data']['timelines'][0]['startTime']).astimezone(tzlocal.get_localzone())
    ioff = 0
    if datetime.datetime.now().day != dt.day:
        ioff += 1
    for i in range(3, 9):
        try:
            f = wxdata3['data']['timelines'][0]['intervals'][i - 3 + ioff]
            wicon = f['values']['weatherCode']
            wicon = tm_code_icons[wicon]
            fl = forecast[i]
            icon = fl.findChild(QtWidgets.QLabel, 'icon')
            wxiconpixmap = QtGui.QPixmap(Config.icons + '/' + wicon + '.png')
            icon.setPixmap(wxiconpixmap.scaled(
                icon.width(),
                icon.height(),
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation))
            wx = fl.findChild(QtWidgets.QLabel, 'wx')
            day = fl.findChild(QtWidgets.QLabel, 'day')
            day.setText('{0:%A %m/%d} '.format(dateutil.parser.parse(f['startTime'])
                                              .astimezone(tzlocal.get_localzone())))
            s = ''
            pop = float(f['values']['precipitationProbability'])
            ptype = float(f['values']['precipitationType'])
            saccum = float(f['values']['snowAccumulationAvg'])
            raccum = float(f['values']['rainAccumulationAvg'])
            wc = tm_code_icons[f['values']['weatherCode']]

            if '4000' in wc:
                ptype = 'rain'
            if '4001' in wc:
                ptype = 'rain'
            if '4200' in wc:
                ptype = 'rain'
            if '4201' in wc:
                ptype = 'rain'
            if '5000' in wc:
                ptype = 'snow'
            if '5001' in wc:
                ptype = 'snow'
            if '5100' in wc:
                ptype = 'snow'
            if '5101' in wc:
                ptype = 'snow'
            if '6000' in wc:
                ptype = 'rain'
            if '6001' in wc:
                ptype = 'rain'
            if '6200' in wc:
                ptype = 'rain'
            if '6201' in wc:
                ptype = 'rain'
            if '7000' in wc:
                ptype = 'snow'
            if '7101' in wc:
                ptype = 'snow'
            if '7102' in wc:
                ptype = 'snow'
            if '8000' in wc:
                ptype = 'rain'

            if Config.metric:
                s += '%.0f' % tempf2tempc(f['values']['temperatureMax']) + '/' + \
                     '%.0f' % tempf2tempc(f['values']['temperatureMin']) + u'°C '
            else:
                s += '%.0f' % f['values']['temperatureMax'] + '/' + \
                     '%.0f' % f['values']['temperatureMin'] + u'°F '

            # If precipitationProbality is greater than 0% but no accumulation show rain or snow with probability percentage.
            # If no precip type or no precip forcated, show No Precipitation

            if pop >= 1 and ptype > 0:
                if ptype == 1 and raccum < 0.10 and saccum < 0.10:
                    s += Config.LRain + '%.0f' % pop + '%'
                elif ptype == 2 and saccum < 0.10 and raccum < 0.10:
                    s += Config.LSnow + '%.0f' % pop + '%'

            # Logic to show rain or snow probability, followed by projected accumulations in forecast

            if Config.metric:
                if ptype == 2:
                    if saccum >= 0.10:
                        s += Config.LSnow + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % inches2mm(saccum) + ' mm'
                    else:
                        if raccum >= 0.10:
                            s += Config.LRain + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % inches2mm(raccum) + ' mm'
                else:
                    if raccum >= 0.10:
                        s += Config.LRain + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % inches2mm(raccum) + ' mm'
                    else:
                        if saccum >= 0.10:
                            s += Config.LSnow + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % inches2mm(saccum) + ' mm'
            else:
                if ptype == 2:
                    if saccum >= 0.10:
                        s += Config.LSnow + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % saccum + ' in'
                    else:
                        if raccum >= 0.10:
                            s += Config.LRain + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % raccum + ' in'
                else:
                    if raccum >= 0.10:
                        s += Config.LRain + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % raccum + ' in'
                    else:
                        if saccum >= 0.10:
                            s += Config.LSnow + '%.0f' % pop + '% ' + '\n' + 'Accumulation: ' + '%.2f' % saccum + ' in'


            wx.setStyleSheet('#wx { font-size: ' + str(int(17 * xscale * Config.fontmult)) + 'px; }')
            if pop >= 1 and (saccum >= 0.10 or raccum >= 0.10):
                wx.setText(tm_code_map[f['values']['weatherCode']] + '\n' + s)
            else:
                wx.setText('\n' + tm_code_map[f['values']['weatherCode']] + '\n' + s)
            
            

        except IndexError:
            print('WARNING:', traceback.format_exc())
            pass


metar_cond = [
    ('CLR', '', '', 'Clear', 'clear-day', 0),
    ('NSC', '', '', 'Clear', 'clear-day', 0),
    ('SKC', '', '', 'Clear', 'clear-day', 0),
    ('FEW', '', '', 'Few Clouds', 'partly-cloudy-day', 1),
    ('NCD', '', '', 'Clear', 'clear-day', 0),
    ('SCT', '', '', 'Scattered Clouds', 'partly-cloudy-day', 2),
    ('BKN', '', '', 'Mostly Cloudy', 'partly-cloudy-day', 3),
    ('OVC', '', '', 'Cloudy', 'cloudy', 4),

    ('///', '', '', '', 'cloudy', 0),
    ('UP', '', '', '', 'cloudy', 0),
    ('VV', '', '', '', 'cloudy', 0),
    ('//', '', '', '', 'cloudy', 0),

    ('DZ', '', '', 'Drizzle', 'rain', 10),

    ('RA', 'FZ', '+', 'Heavy Freezing Rain', 'sleet', 11),
    ('RA', 'FZ', '-', 'Light Freezing Rain', 'sleet', 11),
    ('RA', 'SH', '+', 'Heavy Rain Showers', 'sleet', 11),
    ('RA', 'SH', '-', 'Light Rain Showers', 'rain', 11),
    ('RA', 'BL', '+', 'Heavy Blowing Rain', 'rain', 11),
    ('RA', 'BL', '-', 'Light Blowing Rain', 'rain', 11),
    ('RA', 'FZ', '', 'Freezing Rain', 'sleet', 11),
    ('RA', 'SH', '', 'Rain Showers', 'rain', 11),
    ('RA', 'BL', '', 'Blowing Rain', 'rain', 11),
    ('RA', '', '+', 'Heavy Rain', 'rain', 11),
    ('RA', '', '-', 'Light Rain', 'rain', 11),
    ('RA', '', '', 'Rain', 'rain', 11),

    ('SN', 'FZ', '+', 'Heavy Freezing Snow', 'snow', 12),
    ('SN', 'FZ', '-', 'Light Freezing Snow', 'snow', 12),
    ('SN', 'SH', '+', 'Heavy Snow Showers', 'snow', 12),
    ('SN', 'SH', '-', 'Light Snow Showers', 'snow', 12),
    ('SN', 'BL', '+', 'Heavy Blowing Snow', 'snow', 12),
    ('SN', 'BL', '-', 'Light Blowing Snow', 'snow', 12),
    ('SN', 'FZ', '', 'Freezing Snow', 'snow', 12),
    ('SN', 'SH', '', 'Snow Showers', 'snow', 12),
    ('SN', 'BL', '', 'Blowing Snow', 'snow', 12),
    ('SN', '', '+', 'Heavy Snow', 'snow', 12),
    ('SN', '', '-', 'Light Snow', 'snow', 12),
    ('SN', '', '', 'Rain', 'snow', 12),

    ('SG', 'BL', '', 'Blowing Snow', 'snow', 12),
    ('SG', '', '', 'Snow', 'snow', 12),
    ('GS', 'BL', '', 'Blowing Snow Pellets', 'snow', 12),
    ('GS', '', '', 'Snow Pellets', 'snow', 12),

    ('IC', '', '', 'Ice Crystals', 'snow', 13),
    ('PL', '', '', 'Ice Pellets', 'snow', 13),

    ('GR', '', '+', 'Heavy Hail', 'thuderstorm', 14),
    ('GR', '', '', 'Hail', 'thuderstorm', 14),
]


def feels_like(f):
    t = f.temp.value('C')
    d = f.dewpt.value('C')
    h = (math.exp((17.625 * d) / (243.04 + d)) /
         math.exp((17.625 * t) / (243.04 + t)))
    t = f.temp.value('F')
    w = 0
    if f.wind_speed:
        w = f.wind_speed.value('MPH')
    if t > 80 and h >= 0.40:
        hi = (-42.379 + 2.04901523 * t + 10.14333127 * h - .22475541 * t * h -
              .00683783 * t * t - .05481717 * h * h + .00122874 * t * t * h +
              .00085282 * t * h * h - .00000199 * t * t * h * h)
        if h < 0.13:
            if 80.0 <= t <= 112.0:
                hi -= ((13 - h) / 4) * math.sqrt((17 - abs(t - 95)) / 17)
        if h > 0.85:
            if 80.0 <= t <= 112.0:
                hi += ((h - 85) / 10) * ((87 - t) / 5)
        return hi
    if t < 50 and w >= 3:
        wc = 35.74 + 0.6215 * t - 35.75 * \
             (w ** 0.16) + 0.4275 * t * (w ** 0.16)
        return wc
    return t


def wxfinished_metar(data=None):
    global metarreply
    global wxicon, temper, wxdesc, press, humidity
    global wind, feelslike, wdate
    global wxicon2, temper2, wxdesc2
    global daytime

    if data is None:
        metarreply.deleteLater()
        data = bytes(metarreply.readAll())
        if metarreply.error() != QNetworkReply.NetworkError.NoError:
            print('ERROR: Response from nws.noaa.gov: ' + str(data, 'utf-8'))
            return
        api_cache_write(metarreply.url().toString(), data)
    wxstr = str(data, 'utf-8')

    for wxline in wxstr.splitlines():
        if wxline.startswith(Config.METAR):
            wxstr = wxline
    print('INFO: wxmetar: ' + wxstr)
    f = Metar.Metar(wxstr, strict=False)
    dt = datetime.time(0, 0, 0, tzinfo=datetime.timezone.utc)
    if f.time:
        dt = f.time.replace(tzinfo=datetime.timezone.utc).astimezone(tzlocal.get_localzone())

    pri = -1
    weather = ''
    icon = ''
    if f.sky:
        for s in f.sky:
            for c in metar_cond:
                if s[0] == c[0]:
                    if c[5] > pri:
                        pri = c[5]
                        weather = c[3]
                        icon = c[4]
    if f.weather:
        for w in f.weather:
            for c in metar_cond:
                if w[2] == c[0]:
                    if c[1] > '':
                        if w[1] == c[1]:
                            if c[2] > '':
                                if w[0][0:1] == c[2]:
                                    if c[5] > pri:
                                        pri = c[5]
                                        weather = c[3]
                                        icon = c[4]
                    else:
                        if c[2] > '':
                            if w[0][0:1] == c[2]:
                                if c[5] > pri:
                                    pri = c[5]
                                    weather = c[3]
                                    icon = c[4]
                        else:
                            if c[5] > pri:
                                pri = c[5]
                                weather = c[3]
                                icon = c[4]

    if not daytime:
        icon = icon.replace('-day', '-night')

    wxiconpixmap = QtGui.QPixmap(Config.icons + '/' + icon + '.png')
    wxicon.setPixmap(wxiconpixmap.scaled(
        wxicon.width(), wxicon.height(), Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation))
    wxicon2.setPixmap(wxiconpixmap.scaled(
        wxicon.width(),
        wxicon.height(),
        Qt.AspectRatioMode.IgnoreAspectRatio,
        Qt.TransformationMode.SmoothTransformation))
    wxdesc.setText(weather)
    wxdesc2.setText(weather)

    temp_str = ''
    pressure_str = Config.LPressure
    humidity_str = Config.LHumidity
    wind_speed_str = Config.LWind
    wind_dir_str = ''
    feelslike_str = Config.LFeelslike

    if f.wind_dir:
        if Config.wind_degrees:
            wind_dir_str = str(f.wind_dir.value()) + u'°'
        else:
            wind_dir_str = f.wind_dir.compass()

    if Config.metric:
        if f.temp:
            temp_str = '%.1f' % f.temp.value('C')
        temp_str += u'°C'
        if f.wind_speed:
            wind_speed_str += wind_dir_str + ' ' + '%.1f' % f.wind_speed.value('KMH') + 'km/h'
            if f.wind_gust:
                wind_speed_str += Config.Lgusting + '%.1f' % f.wind_gust.value('KMH') + 'km/h'
        if f.temp and f.dewpt:
            feelslike_str += '%.1f' % tempf2tempc(feels_like(f)) + u'°C'
    else:
        if f.temp:
            temp_str = '%.1f' % f.temp.value('F')
        temp_str += u'°F'
        if f.wind_speed:
            wind_speed_str += wind_dir_str + ' ' + '%.1f' % f.wind_speed.value('MPH') + 'mph'
            if f.wind_gust:
                wind_speed_str += Config.Lgusting + '%.1f' % f.wind_gust.value('MPH') + 'mph'
        if f.temp and f.dewpt:
            feelslike_str += '%.1f' % feels_like(f) + u'°F'

    if f.press:
        if Config.pressure_mbar:
            pressure_str += '%.1f' % f.press.value('MB') + 'mbar'
        else:
            pressure_str += '%.2f' % f.press.value('IN') + 'inHg'

    if f.temp and f.dewpt:
        t = f.temp.value('C')
        d = f.dewpt.value('C')
        h = 100.0 * (math.exp((17.625 * d) / (243.04 + d)) /
                     math.exp((17.625 * t) / (243.04 + t)))
        humidity_str += '%.0f%%' % h

    temper.setText(temp_str)
    temper2.setText(temp_str)
    # Sets the label text and feeds the raw reading into the pressure trend history
    # (METAR reports occasionally omit pressure, hence the None fallback).
    set_pressure_label(pressure_str, f.press.value('IN') if f.press else None)
    humidity.setText(humidity_str)
    wind.setText(wind_speed_str)
    feelslike.setText(feelslike_str)
    wdate.setText('0:%H:%M %Z} {1}'.format(dt, Config.METAR))


def record_pressure_sample(value_inhg):
    # Keep a rolling 2-hour history of raw pressure readings (inHg) so
    # update_pressure_trend() has data to compare against later.
    global pressure_history
    now = time.time()
    pressure_history.append((now, value_inhg))
    cutoff = now - PRESSURE_TREND_WINDOW_SEC
    pressure_history[:] = [(t, v) for (t, v) in pressure_history if t >= cutoff]


def set_pressure_label(pressure_str, value_inhg):
    """Record a new pressure sample (if any) and (re)render the pressure label
    using the current, possibly stale, trend arrow. The arrow itself is only
    recalculated by update_pressure_trend(), once an hour."""
    global pressure_label_text
    pressure_label_text = pressure_str
    if value_inhg is not None:
        record_pressure_sample(value_inhg)
    press.setText(pressure_label_text + pressure_trend_arrow)


def update_pressure_trend():
    """Recompute the pressure trend arrow from the last 2 hours of samples.
    Called once an hour by pressuretrendtimer in qtstart()."""
    global pressure_trend_arrow
    now = time.time()
    window = [(t, v) for (t, v) in pressure_history if t >= now - PRESSURE_TREND_WINDOW_SEC]
    if len(window) >= 2:
        # Compare the oldest vs. newest sample still inside the 2-hour window
        # to decide which way pressure has been tracking.
        delta = window[-1][1] - window[0][1]
        if delta >= PRESSURE_TREND_DEADBAND_INHG:
            pressure_trend_arrow = u' ↑'
        elif delta <= -PRESSURE_TREND_DEADBAND_INHG:
            pressure_trend_arrow = u' ↓'
        # else: within the deadband, keep the previous arrow to avoid flicker
    press.setText(pressure_label_text + pressure_trend_arrow)


def getallwx():
    global hasMetar
    if hasMetar:
        try:
            getwx_metar()
        except AttributeError:
            pass

    try:
        ApiKeys.tmapi
        global tm_code_map
        try:
            tm_code_map = Config.Ltm_code_map
        except AttributeError:
            pass
        getwx_tm()
        return
    except AttributeError:
        pass


def getwx_tm():
    global wxreply
    global wxreply2
    global wxreply3
    global hasMetar

    max_age = Config.weather_refresh * 60

    if not hasMetar:
        # current conditions
        wxurl = 'https://api.tomorrow.io/v4/timelines?timesteps=current&apikey=' + ApiKeys.tmapi
        wxurl += '&location=' + str(Config.location.lat) + ',' + str(Config.location.lng)
        wxurl += '&units=imperial'
        wxurl += '&fields=temperature,weatherCode,temperatureApparent,humidity,'
        wxurl += 'windSpeed,windDirection,windGust,pressureSeaLevel,precipitationType'
        cached = api_cache_read(wxurl, max_age)
        if cached is not None:
            print('INFO: using cached Tomorrow.io current conditions')
            wxfinished_tm_current(cached)
        else:
            print('INFO: getting Tomorrow.io current conditions: ' + wxurl)
            r = QUrl(wxurl)
            r = QNetworkRequest(r)
            wxreply = manager.get(r)
            wxreply.finished.connect(wxfinished_tm_current)

    # hourly forecast
    wxurl2 = 'https://api.tomorrow.io/v4/timelines?timesteps=1h&apikey=' + ApiKeys.tmapi
    wxurl2 += '&location=' + str(Config.location.lat) + ',' + str(Config.location.lng)
    wxurl2 += '&units=imperial'
    wxurl2 += '&fields=temperature,precipitationIntensity,precipitationType,'
    wxurl2 += 'precipitationProbability,weatherCode,'
    wxurl2 += 'snowAccumulationAvg,rainAccumulationAvg'
    cached2 = api_cache_read(wxurl2, max_age)
    if cached2 is not None:
        print('INFO: using cached Tomorrow.io hourly forecast')
        wxfinished_tm_hourly(cached2)
    else:
        print('INFO: getting Tomorrow.io hourly forecast: ' + wxurl2)
        r2 = QUrl(wxurl2)
        r2 = QNetworkRequest(r2)
        wxreply2 = manager.get(r2)
        wxreply2.finished.connect(wxfinished_tm_hourly)

    # daily forecast
    wxurl3 = 'https://api.tomorrow.io/v4/timelines?timesteps=1d&apikey=' + ApiKeys.tmapi
    wxurl3 += '&location=' + str(Config.location.lat) + ',' + str(Config.location.lng)
    wxurl3 += '&units=imperial'
    wxurl3 += '&fields=temperature,precipitationIntensity,precipitationType,'
    wxurl3 += 'precipitationProbability,weatherCode,temperatureMax,temperatureMin,'
    wxurl3 += 'snowAccumulationAvg,rainAccumulationAvg'
    cached3 = api_cache_read(wxurl3, max_age)
    if cached3 is not None:
        print('INFO: using cached Tomorrow.io daily forecast')
        wxfinished_tm_daily(cached3)
    else:
        print('INFO: getting Tomorrow.io daily forecast: ' + wxurl3)
        r3 = QUrl(wxurl3)
        r3 = QNetworkRequest(r3)
        wxreply3 = manager.get(r3)
        wxreply3.finished.connect(wxfinished_tm_daily)


def getwx_metar():
    global metarreply
    metarurl = 'https://tgftp.nws.noaa.gov/data/observations/metar/stations/' + Config.METAR + '.TXT'
    cached = api_cache_read(metarurl, Config.weather_refresh * 60)
    if cached is not None:
        print('INFO: using cached METAR current conditions')
        wxfinished_metar(cached)
    else:
        print('INFO: getting METAR current conditions: ' + metarurl)
        r = QUrl(metarurl)
        r = QNetworkRequest(r)
        metarreply = manager.get(r)
        metarreply.finished.connect(wxfinished_metar)


def get_noaa_alerts():
    """Check api.weather.gov for active severe weather alerts for Config.location.
    Deliberately not disk-cached (unlike the other weather/radar calls): alerts
    are safety-relevant, so every check should reflect the current live state."""
    global manager, noaaAlertReply
    if not Config.noaa_alerts_enabled:
        return
    alerturl = 'https://api.weather.gov/alerts/active?point=' + \
               str(Config.location.lat) + ',' + str(Config.location.lng) + \
               '&severity=' + ','.join(Config.alert_severities)
    print('INFO: checking NOAA severe weather alerts: ' + alerturl)
    req = QNetworkRequest(QUrl(alerturl))
    req.setRawHeader(b'User-Agent', b'PiClock/1.0 (https://github.com/tecms25/PiClock)')
    req.setRawHeader(b'Accept', b'application/geo+json')
    noaaAlertReply = manager.get(req)
    noaaAlertReply.finished.connect(noaa_alerts_finished)


def noaa_alerts_finished():
    global noaaAlertReply, alertBubble

    noaaAlertReply.deleteLater()
    if noaaAlertReply.error() != QNetworkReply.NetworkError.NoError:
        print('ERROR: Response from api.weather.gov: ' + noaaAlertReply.errorString())
        return

    alertstr = str(bytes(noaaAlertReply.readAll()), 'utf-8')
    try:
        alertdata = json.loads(alertstr)
    except ValueError:  # includes json.decoder.JSONDecodeError
        print('WARNING:', traceback.format_exc())
        print('WARNING: Response from api.weather.gov: ' + alertstr)
        return

    alerts = []
    for feature in alertdata.get('features', []):
        props = feature.get('properties', {})
        expires = None
        if props.get('expires'):
            try:
                expires = dateutil.parser.parse(props['expires']).astimezone(tzlocal.get_localzone())
            except (ValueError, OverflowError):
                expires = None
        alerts.append({
            'event': props.get('event', 'Alert'),
            'headline': props.get('headline', ''),
            'expires': expires,
        })

    if alerts:
        print(f'INFO: {len(alerts)} active NOAA alert(s): ' + ', '.join(a['event'] for a in alerts))
    alertBubble.set_alerts(alerts)


def qtstart():
    global ctimer, wxtimer, temptimer, metadatatimer, cursortimer, alerttimer
    global apicachecleanuptimer
    global pressuretrendtimer
    global objradar1
    global objradar2
    global objradar3
    global objradar4
    global sun, daytime, sunrise, sunset
    global tzlatlng

    if Config.DateLocale != '':
        try:
            locale.setlocale(locale.LC_TIME, Config.DateLocale)
        except locale.Error:
            print('WARNING:', traceback.format_exc())
            pass

    dt = datetime.datetime.now(tz=tzlocal.get_localzone())
    tzlatlngstr = get_tz(Config.location.lng, Config.location.lat)
    if tzlatlngstr:
        tzlatlng = pytz.timezone(tzlatlngstr)
    else:
        tzlatlng = tzlocal.get_localzone()
        print(
            "WARNING: tzfpy.get_tz() returned None for lat/lng "
            f"({Config.location.lat}, {Config.location.lng}); "
            f"falling back to tzlocal.get_localzone() -> {tzlatlng}"
        )

    sun = SunTimes(Config.location.lat, Config.location.lng, tzlatlng)
    sunrise = sun.sunrise(dt)
    sunset = sun.sunset(dt)
    if sunrise <= dt <= sunset:
        daytime = True
    else:
        daytime = False

    getallwx()
    gettemp()

    # Start all radar objects
    radar_refresh_interval = Config.radar_refresh * 60
    objradar1.start(radar_refresh_interval)
    objradar2.start(radar_refresh_interval)
    objradar3.start(radar_refresh_interval)
    objradar4.start(radar_refresh_interval)

    # Sy wxstart calls for radar objects 1 and 2
    objradar1.wxstart()
    objradar2.wxstart()

    ctimer = QtCore.QTimer()
    ctimer.timeout.connect(tick)
    ctimer.start(1000)

    cursortimer = QtCore.QTimer()
    cursortimer.timeout.connect(cursor_idle_tick)
    cursortimer.start(CURSOR_POLL_MS)

    # Recompute the pressure up/down arrow once an hour, based on the last 2
    # hours of samples recorded by set_pressure_label() on each weather refresh.
    pressuretrendtimer = QtCore.QTimer()
    pressuretrendtimer.timeout.connect(update_pressure_trend)
    pressuretrendtimer.start(int(1000 * 60 * 60 + random.uniform(1000, 10000)))

    wxtimer = QtCore.QTimer()
    wxtimer.timeout.connect(getallwx)
    wxtimer.start(int(1000 * Config.weather_refresh * 60 + random.uniform(1000, 10000)))

    temptimer = QtCore.QTimer()
    temptimer.timeout.connect(gettemp)
    temptimer.start(int(1000 * 10 * 60 + random.uniform(1000, 10000)))


    # Fetch RainViewer metadata once at regular intervals (every 10 minutes)
    metadatatimer = QtCore.QTimer()
    metadatatimer.timeout.connect(get_rainviewer_metadata)
    metadatatimer.start(int(1000 * 600 + random.uniform(1000, 5000)))  # 10 minutes

    # Fetch metadata immediately on startup
    get_rainviewer_metadata()

    # Sweep stale API cache files on startup, then periodically thereafter
    apicachecleanuptimer = QtCore.QTimer()
    apicachecleanuptimer.timeout.connect(api_cache_cleanup)
    apicachecleanuptimer.start(API_CACHE_SWEEP_INTERVAL_MS)
    api_cache_cleanup()

    # Check for active NOAA/NWS severe weather alerts, then on a timer
    alerttimer = QtCore.QTimer()
    alerttimer.timeout.connect(get_noaa_alerts)
    alerttimer.start(int(1000 * 60 * Config.alert_refresh + random.uniform(1000, 5000)))
    get_noaa_alerts()

    if Config.useslideshow:
        objimage1.start(Config.slide_time)


# web_slideshow_playlist = 0: random images from this folder (repo-root-relative,
# resolved from this file's own location so it works regardless of cwd).
SLIDESHOW_LOCAL_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Pictures', 'Slideshow'))
# web_slideshow_playlist = 1: downloaded images from Config.slideshow_url are cached here.
SLIDESHOW_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'slideshow_cache')
SLIDESHOW_PLAYLIST_REFRESH_SEC = 2 * 60 * 60  # re-check the web playlist for changes every 2 hours
SLIDESHOW_IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')


ALERT_CYCLE_MS = 6000  # how long each alert shows before cycling to the next, when more than one is active


class AlertBubble(QtWidgets.QLabel):
    """Red, semi-transparent warning bubble for active NOAA/NWS severe weather
    alerts (see get_noaa_alerts()). Hidden when there are none; fades in/out
    as alerts appear or clear, and cycles through multiple active alerts."""

    def __init__(self, parent, rect):
        QtWidgets.QLabel.__init__(self, parent)
        self.setObjectName('alertBubble')
        self.setGeometry(rect)
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            '#alertBubble { background-color: rgba(190, 20, 20, 195); '
            'border-radius: ' + str(int(rect.height() / 2.4)) + 'px; '
            'color: #FFFFFF; font-family:"Open Sans"; font-weight: bold; '
            'font-size: ' + str(int(22 * xscale * Config.fontmult)) + 'px; ' +
            Config.fontattr + '}')

        self._opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)
        self.hide()

        self.alerts = []
        self.index = 0
        self._anim = None
        self._shown = False

        self.cycle_timer = QtCore.QTimer()
        self.cycle_timer.timeout.connect(self._cycle)
        self.cycle_timer.start(ALERT_CYCLE_MS)

    def set_alerts(self, alerts):
        self.alerts = alerts
        self.index = 0
        if alerts:
            self._show_current()
            if not self._shown:
                self._shown = True
                self._fade(1.0)
        else:
            if self._shown:
                self._shown = False
                self._fade(0.0)

    def _cycle(self):
        if len(self.alerts) > 1:
            self.index = (self.index + 1) % len(self.alerts)
            self._show_current()

    def _show_current(self):
        alert = self.alerts[self.index]
        text = alert['event'].upper()
        if alert.get('expires'):
            text += '\nuntil {0:%-I:%M %p}'.format(alert['expires'])
        self.setText(text)

    def _fade(self, target):
        if self._anim is not None:
            self._anim.stop()
            self._anim.deleteLater()
        if target > 0:
            self.show()
        anim = QtCore.QPropertyAnimation(self._opacity_effect, b'opacity', self)
        anim.setDuration(500)
        anim.setStartValue(self._opacity_effect.opacity())
        anim.setEndValue(target)
        if target == 0:
            anim.finished.connect(self.hide)
        self._anim = anim
        anim.start()


class SlideShow(QtWidgets.QLabel):
    def __init__(self, parent, rect, myname):
        self.myname = myname
        self.rect = rect
        QtWidgets.QLabel.__init__(self, parent)

        self.pause = False
        self.count = 0
        self.img_list = []  # local file paths, in display order
        self.img_inc = 1
        self.list_reply = None
        self.image_reply = None
        self.pending_downloads = []

        os.makedirs(SLIDESHOW_LOCAL_DIR, exist_ok=True)
        os.makedirs(SLIDESHOW_CACHE_DIR, exist_ok=True)
        self._clear_cache_dir()  # start every launch from a clean slate; nothing to redownload lingers forever

        self.setObjectName('slideShow')
        self.setGeometry(rect)
        self.setStyleSheet('#slideShow { background-color: ' +
                           Config.slide_bg_color + '; }')
        self.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignCenter)

        self.timer = None
        self.playlist_timer = None

        # Overlay label used to crossfade into the next image instead of a hard cut.
        self._fade_label = QtWidgets.QLabel(self)
        self._fade_label.setGeometry(0, 0, self.width(), self.height())
        self._fade_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignCenter)
        self._fade_label.setStyleSheet('background-color: transparent;')
        self._fade_opacity_effect = QtWidgets.QGraphicsOpacityEffect(self._fade_label)
        self._fade_opacity_effect.setOpacity(0.0)
        self._fade_label.setGraphicsEffect(self._fade_opacity_effect)
        self._fade_label.hide()
        self._fade_anim = None

    def start(self, interval):
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.switch_image)
        self.timer.start(int(1000 * interval + random.uniform(1, 10)))

        if Config.web_slideshow_playlist:
            self.refresh_playlist()  # downloads fresh on launch
            self.playlist_timer = QtCore.QTimer()
            self.playlist_timer.timeout.connect(self.refresh_playlist)
            self.playlist_timer.start(int(1000 * SLIDESHOW_PLAYLIST_REFRESH_SEC))
        else:
            self.scan_local_images()
            self.switch_image()

    def stop(self):
        try:
            self.timer.stop()
            self.timer = None
        except AttributeError:
            print('WARNING:', traceback.format_exc())
            pass
        if self.playlist_timer:
            self.playlist_timer.stop()
            self.playlist_timer = None

    def switch_image(self):
        if self.img_list and not self.pause:
            self.count = (self.count + self.img_inc) % len(self.img_list)
            self.display_image(self.img_list[self.count])

    def display_image(self, path):
        image = QtGui.QImage(path)
        if image.isNull():
            print(f"ERROR: Unable to load slideshow image: {path}")
            return
        pixmap = QtGui.QPixmap.fromImage(image).scaled(
            self.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation)

        if Config.slide_transition_ms <= 0:
            self.setPixmap(pixmap)
            return

        if self._fade_anim is not None:
            self._fade_anim.stop()
            self._finish_transition(self._fade_label.pixmap())

        self._fade_label.setGeometry(0, 0, self.width(), self.height())
        self._fade_label.setPixmap(pixmap)
        self._fade_opacity_effect.setOpacity(0.0)
        self._fade_label.show()
        self._fade_label.raise_()

        anim = QtCore.QPropertyAnimation(self._fade_opacity_effect, b'opacity', self)
        anim.setDuration(int(Config.slide_transition_ms))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.finished.connect(lambda: self._finish_transition(pixmap))
        self._fade_anim = anim
        anim.start()

    def _finish_transition(self, pixmap):
        self.setPixmap(pixmap)
        self._fade_label.hide()
        self._fade_anim = None

    @staticmethod
    def _clear_cache_dir():
        """Wipe SLIDESHOW_CACHE_DIR on launch so the cache can never build up
        across restarts; refresh_playlist() re-downloads whatever the current
        playlist needs."""
        for existing in os.listdir(SLIDESHOW_CACHE_DIR):
            try:
                os.remove(os.path.join(SLIDESHOW_CACHE_DIR, existing))
            except OSError as e:
                print(f"ERROR: Unable to remove cached slideshow image {existing}: {e}")

    def scan_local_images(self):
        """Populate img_list from SLIDESHOW_LOCAL_DIR (web_slideshow_playlist = 0)."""
        try:
            files = [
                os.path.join(SLIDESHOW_LOCAL_DIR, f)
                for f in os.listdir(SLIDESHOW_LOCAL_DIR)
                if os.path.splitext(f)[1].lower() in SLIDESHOW_IMAGE_EXTENSIONS
            ]
        except OSError as e:
            print(f"ERROR: Unable to read {SLIDESHOW_LOCAL_DIR}: {e}")
            files = []
        if not files:
            print(f"WARNING: No slideshow images found in {SLIDESHOW_LOCAL_DIR}")
        random.shuffle(files)
        self.img_list = files
        self.count = 0

    @staticmethod
    def cache_filename_for_url(url):
        """Stable, filesystem-safe cache filename derived from the URL, so the
        same URL always maps to the same cached file and re-downloads can be
        skipped when the playlist is unchanged."""
        ext = os.path.splitext(urlparse(url).path)[1].lower()
        if not ext or len(ext) > 5:
            ext = '.img'
        return hashlib.sha1(url.encode('utf-8')).hexdigest() + ext

    def refresh_playlist(self):
        """Fetch the playlist text file (web_slideshow_playlist = 1)."""
        global manager
        self.list_reply = manager.get(QNetworkRequest(QUrl(Config.slideshow_url)))
        self.list_reply.finished.connect(self.playlist_finished)

    def playlist_finished(self):
        reply = self.list_reply
        reply.deleteLater()
        if reply.error() != QNetworkReply.NetworkError.NoError:
            print(f"ERROR: Unable to fetch slideshow playlist: {reply.errorString()}")
            return

        content = str(reply.readAll(), 'utf-8')
        urls = [line.strip() for line in content.splitlines() if line.strip()]
        wanted = {self.cache_filename_for_url(url): url for url in urls}

        # Drop cached images that are no longer in the playlist.
        try:
            for existing in os.listdir(SLIDESHOW_CACHE_DIR):
                if existing not in wanted:
                    try:
                        os.remove(os.path.join(SLIDESHOW_CACHE_DIR, existing))
                    except OSError:
                        pass
        except OSError as e:
            print(f"ERROR: Unable to read {SLIDESHOW_CACHE_DIR}: {e}")

        def cache_path(fname):
            return os.path.join(SLIDESHOW_CACHE_DIR, fname)

        self.pending_downloads = [
            (url, cache_path(fname)) for fname, url in wanted.items()
            if not os.path.exists(cache_path(fname))
        ]

        cached = [cache_path(fname) for fname in wanted if os.path.exists(cache_path(fname))]
        random.shuffle(cached)
        self.img_list = cached
        self.count = 0
        if self.img_list:
            self.switch_image()

        if self.pending_downloads:
            print(f"SLIDESHOW: downloading {len(self.pending_downloads)} new image(s)")
            self._download_next_pending()
        else:
            print("SLIDESHOW: playlist unchanged, no new images to download")

    def _download_next_pending(self):
        global manager
        if not self.pending_downloads:
            return
        url, dest = self.pending_downloads[0]
        print(f"SLIDESHOW: downloading {url}")
        self.image_reply = manager.get(QNetworkRequest(QUrl(url)))
        self.image_reply.finished.connect(lambda: self._pending_download_finished(dest))

    def _pending_download_finished(self, dest):
        reply = self.image_reply
        reply.deleteLater()
        self.pending_downloads.pop(0)
        if reply.error() != QNetworkReply.NetworkError.NoError:
            print(f"ERROR: Unable to download {reply.url().toString()}: {reply.errorString()}")
        else:
            with open(dest, 'wb') as f:
                f.write(bytes(reply.readAll()))
            self.img_list.append(dest)
            if len(self.img_list) == 1:
                self.switch_image()
        self._download_next_pending()

    def play_pause(self):
        if not self.pause:
            self.pause = True
        else:
            self.pause = False

    def prev_next(self, direction):
        self.img_inc = direction
        self.timer.stop()
        self.switch_image()
        self.timer.start()

# Global RainViewer metadata cache (shared by all Radar instances)
radarMetadataCache = {
    'data': {},
    'lastupdated': 0,
    'updateinterval': 600  # refresh every 10 minutes (same as tile intervals)
}
radarMetadataReply = None


def get_rainviewer_metadata():
    """Fetch RainViewer metadata once globally, shared by all radar instances"""
    global manager, radarMetadataCache, radarMetadataReply

    # Check if the cache is still fresh (updated within the last 10 minutes)
    if time.time() - radarMetadataCache['lastupdated'] < radarMetadataCache['updateinterval']:
        return

    metadataurl = 'https://api.rainviewer.com/public/weather-maps.json'
    cached = api_cache_read(metadataurl, radarMetadataCache['updateinterval'])
    if cached is not None:
        print('INFO: using cached RainViewer metadata')
        rainviewer_metadata_finished(cached)
    else:
        print('INFO: Fetching RainViewer metadata: ' + metadataurl)
        metadatareq = QNetworkRequest(QUrl(metadataurl))
        radarMetadataReply = manager.get(metadatareq)
        radarMetadataReply.finished.connect(rainviewer_metadata_finished)


def rainviewer_metadata_finished(data=None):
    """Process the RainViewer metadata response"""
    global radarMetadataCache, radarMetadataReply

    if data is None:
        radarMetadataReply.deleteLater()
        data = bytes(radarMetadataReply.readAll())
        if radarMetadataReply.error() != QNetworkReply.NetworkError.NoError:
            print('ERROR: Response from api.rainviewer.com: ' + str(data, 'utf-8'))
            return
        api_cache_write(radarMetadataReply.url().toString(), data)

    metadatastr = str(data, 'utf-8')
    try:
        radarMetadataCache['data'] = json.loads(metadatastr)
        radarMetadataCache['lastupdated'] = time.time()
    except ValueError:  # includes json.decoder.JSONDecodeError
        print('WARNING:', traceback.format_exc())
        print('WARNING: Response from api.rainviewer.com: ' + metadatastr)
        return



class Radar(QtWidgets.QLabel):

    # Frame timing shared by every Radar instance, so playback is driven by
    # wall-clock time (see rtick()) instead of a per-instance counter. That
    # keeps all radars in lockstep, both on startup and while running, no
    # matter when each one's timer happened to start.
    TICK_MS = 200
    HOLD_TICKS = 10  # ticks spent holding on the newest frame before sweeping through history

    def __init__(self, parent, radar, rect, myname):
        self.myname = myname
        self.rect = rect
        self.anim = 10
        self.zoom = radar['zoom']
        self.point = radar['center']
        self.radar = radar
        self.baseurl = self.mapurl(radar, rect, overlayonly=False)
        print('INFO: map base url for ' + self.myname + ': ' + self.baseurl)

        if usemapbox:
            if 'overlay' in radar:
                if radar['overlay'] != '':
                    self.overlayurl = self.mapurl(radar, rect, overlayonly=True)
                    print('INFO: map overlay url for ' + self.myname + ': ' + self.overlayurl)

        QtWidgets.QLabel.__init__(self, parent)
        self.interval = Config.radar_refresh * 60
        self.lastwx = 0
        self.retries = 0
        self.corners = get_corners(self.point, self.zoom, rect.width(), rect.height())
        self.baseTime = 0
        self.cornerTiles = {
            'NW': get_tile_xy(LatLng(self.corners['N'],
                                     self.corners['W']), self.zoom),
            'NE': get_tile_xy(LatLng(self.corners['N'],
                                     self.corners['E']), self.zoom),
            'SE': get_tile_xy(LatLng(self.corners['S'],
                                     self.corners['E']), self.zoom),
            'SW': get_tile_xy(LatLng(self.corners['S'],
                                     self.corners['W']), self.zoom)
        }
        self.tiles = []
        self.tiletails = []
        self.totalWidth = 0
        self.totalHeight = 0
        self.tilesWidth = 0
        self.tilesHeight = 0

        # base map layer
        self.setObjectName('radar')
        self.setGeometry(rect)
        self.setStyleSheet('#radar { background-color: grey; }')
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # weather radar layer
        self.wwx = QtWidgets.QLabel(self)
        self.wwx.setObjectName('wx')
        self.wwx.setStyleSheet('#wx { background-color: transparent; }')
        self.wwx.setGeometry(0, 0, rect.width(), rect.height())

        # map overlay layer
        self.overlay = QtWidgets.QLabel(self)
        self.overlay.setObjectName('overlay')
        self.overlay.setStyleSheet('#overlay { background-color: transparent; }')
        self.overlay.setGeometry(0, 0, rect.width(), rect.height())

        # marker layer
        self.wmk = QtWidgets.QLabel(self)
        self.wmk.setObjectName('mk')
        self.wmk.setStyleSheet('#mk { background-color: transparent; }')
        self.wmk.setGeometry(0, 0, rect.width(), rect.height())

        # timestamp and attribution layer
        self.timestamp = QtWidgets.QLabel(self)
        self.timestamp.setObjectName('timestamp')
        self.timestamp.setStyleSheet('#timestamp { background-color: transparent; }')
        self.timestamp.setGeometry(0, 0, rect.width(), rect.height())

        for y in range(int(self.cornerTiles['NW']['Y']),
                       int(self.cornerTiles['SW']['Y']) + 1):
            self.totalHeight += 256
            self.tilesHeight += 1
            for x in range(int(self.cornerTiles['NW']['X']),
                           int(self.cornerTiles['NE']['X']) + 1):
                tile = {'X': x, 'Y': y}
                self.tiles.append(tile)
                if 'color' not in radar:
                    radar['color'] = 6
                if 'smooth' not in radar:
                    radar['smooth'] = 1
                if 'snow' not in radar:
                    radar['snow'] = 1
                tail = '256/%d/%d/%d/%d/%d_%d.png' % (self.zoom, x, y,
                                                       radar['color'],
                                                       radar['smooth'],
                                                       radar['snow'])
                if 'oldcolor' in radar:
                    tail = '256/%d/%d/%d.png?color=%d' % (self.zoom, x, y,
                                                           radar['color'])
                self.tiletails.append(tail)
        for x in range(int(self.cornerTiles['NW']['X']),
                       int(self.cornerTiles['NE']['X']) + 1):
            self.totalWidth += 256
            self.tilesWidth += 1
        self.frameImages = []
        self.frameIndex = 0
        self.lastget = 0

        self.getTime = 0
        self.getIndex = 0
        self.tileurls = []
        self.tileQimages = []
        self.tilereply = None
        self.basereply = None
        self.timer = None
        self.overlayreply = None

    def rtick(self):
        """Update radar display, synced to wall-clock time so every Radar
        instance shows the same point in the loop at the same moment."""
        now = time.time()
        if now > (self.lastget + self.interval):
            self.get(int(now))
            self.lastget = now
        if len(self.frameImages) < 1:
            return

        cycle_ticks = self.HOLD_TICKS + self.anim
        tick_in_cycle = int(now * 1000 / self.TICK_MS) % cycle_ticks
        if tick_in_cycle < self.HOLD_TICKS - 1:
            frame_index = self.anim  # holding on the newest frame
        else:
            frame_index = tick_in_cycle - (self.HOLD_TICKS - 1)

        t_now = int(now / 600) * 600
        target_time = t_now - (self.anim - frame_index) * 600

        for f in self.frameImages:
            if f['time'] == target_time:
                self.wwx.setPixmap(f['image'])
                self.timestamp.setPixmap(f['timestamp'])
                break
        # if the target frame hasn't been fetched yet, keep showing the last one

    def get(self, t=0):
        """Retrieve radar tiles for a specific time or the current base time."""
        t = int(t / 600) * 600
        if t > 0:
            if self.baseTime == t:
                return
        if t == 0:
            t = self.baseTime
        else:
            self.baseTime = t
        newf = []
        for f in self.frameImages:
            if f['time'] >= (t - self.anim * 600):
                newf.append(f)
        self.frameImages = newf
        firstt = t - self.anim * 600
        for tt in range(firstt, t + 1, 600):
#            print('INFO: ' + self.myname + '... get radar tiles for time ' + str(tt) +
#                  ' (' + str(datetime.datetime.fromtimestamp(tt).astimezone(tzlocal.get_localzone())) + ')')
            print(f'INFO: {self.myname} fetching radar tiles for time {tt} '
                  f'({datetime.datetime.fromtimestamp(tt).astimezone(tzlocal.get_localzone())})')
            gotit = False
            for f in self.frameImages:
                if f['time'] == tt:
                    gotit = True
            if not gotit:
#                self.get_tiles(tt)
#                break
                # Try to get tiles for this time, but continue to the next time if unavailable
                if self.get_tiles(tt):
                    break  # Successfully started fetching, stop loop to wait for async completion

    def get_tiles(self, t, i=0):
        """Build tile URLs from metadata and fetch them

        Returns True if tiles were successfully queued for fetching, False if unavailable
        """
        t = int(t / 600) * 600
        self.getTime = t
        self.getIndex = i

        if i == 0:
            self.tileurls = []
            self.tileQimages = []

            # Find the matching radar frame from metadata for this timestamp
            radarpath = self.find_radar_path_for_time(t)
            if not radarpath:
                print(f'WARNING: {self.myname} no radar data available for time {t}')
                return False  # No data available, caller should try the next timestamp

            host = radarMetadataCache['data'].get('host', 'https://tilecache.rainviewer.com')

            # Build the tile URLs using the frame path from API and our tile parameters
            for tt in self.tiletails:
                tileurl = host + radarpath + '/' + tt
                self.tileurls.append(tileurl)

        tileurl = self.tileurls[i]
        cached = api_cache_read(tileurl, Config.radar_refresh * 60)
        if cached is not None:
            print(f'INFO: {self.myname} {t} tile{self.getIndex} using cached {tileurl}')
            self.get_tilesreply(cached)
        else:
            print(f'INFO: {self.myname} {t} tile{self.getIndex} {tileurl}')
            tilereq = QNetworkRequest(QUrl(tileurl))
            self.tilereply = manager.get(tilereq)
            self.tilereply.finished.connect(self.get_tilesreply)
        return True  # Successfully queued for fetching

    def find_radar_path_for_time(self, timestamp):
        """Find the radar path from metadata that matches the requested timestamp

        Since the API provides 10-minute interval frames, find the closest available frame
        """
        if not radarMetadataCache['data'] or 'radar' not in radarMetadataCache['data']:
            return None

        past_frames = radarMetadataCache['data']['radar'].get('past', [])
        if not past_frames:
            return None

        # Look for the exact match or the closest frame
        closest_frame = None
        closest_diff = float('inf')

        for frame in past_frames:
            frame_time = frame.get('time')
            if frame_time is None:
                continue

            time_diff = abs(frame_time - timestamp)

            # Prefer an exact match or very close match (within 5 minutes of drift)
            if time_diff < closest_diff:
                closest_diff = time_diff
                closest_frame = frame

                # If we found an exact match, use it
                if time_diff == 0:
                    break

        if closest_frame and closest_diff <= 300:  # 5-minute tolerance
            path = closest_frame.get('path')
            if path:
                return path

        return None

    def get_tilesreply(self, data=None):
        """Process the radar tile response"""
        if data is None:
            self.tilereply.deleteLater()
            data = bytes(self.tilereply.readAll())
            if self.tilereply.error() != QNetworkReply.NetworkError.NoError:
                print(f'ERROR: Response from rainviewer.com: {str(data, "utf-8")}')
                return
            api_cache_write(self.tilereply.url().toString(), data)
        self.tileQimages.append(QImage())
        try:
            self.tileQimages[self.getIndex].loadFromData(data)
            self.getIndex += 1
        except IndexError:
            print('WARNING:', traceback.format_exc())
            pass
        if self.getIndex < len(self.tileurls):
            self.get_tiles(self.getTime, self.getIndex)
        else:
            self.combine_tiles()
            self.get()

    def combine_tiles(self):
        # create weather radar image
        """Combine the radar tiles into a single image"""
        ii = QImage(self.tilesWidth * 256, self.tilesHeight * 256, QImage.Format.Format_ARGB32)
        ii.fill(Qt.GlobalColor.transparent)
        painter = QPainter()
        painter.begin(ii)
        i = 0
        xo = self.cornerTiles['NW']['X']
        xo = int((int(xo) - xo) * 256)
        yo = self.cornerTiles['NW']['Y']
        yo = int((int(yo) - yo) * 256)
        for y in range(0, self.totalHeight, 256):
            for x in range(0, self.totalWidth, 256):
                try:
                    if self.tileQimages[i].format() == QImage.Format.Format_ARGB32:
                        painter.drawImage(x, y, self.tileQimages[i])
                    i += 1
                except IndexError:
                    print('WARNING:', traceback.format_exc())
                    pass
        painter.end()
        self.tileQimages = []
        ii2 = QPixmap(ii.copy(-xo, -yo, self.rect.width(), self.rect.height()))
        # finish weather radar image

        # create timestamp layer
        ii3 = ii.copy(-xo, -yo, self.rect.width(), self.rect.height())
        ii3.fill(Qt.GlobalColor.transparent)
        painter2 = QPainter()
        painter2.begin(ii3)
        timestamp = 'Radar Time: {0:%-I:%M %p}'.format(datetime.datetime.fromtimestamp(self.getTime))
        painter2.setPen(QColor(63, 63, 63, 255))
        painter2.setFont(QFont("Arial", pointSize=8, weight=75))
        painter2.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter2.drawText(3 - 1, 12 - 1, timestamp)
        painter2.drawText(3 + 2, 12 + 1, timestamp)
        painter2.setPen(QColor(255, 255, 255, 255))
        painter2.drawText(3, 12, timestamp)
        painter2.drawText(3 + 1, 12, timestamp)
        painter2.end()
        ts = QPixmap(ii3)
        # finish timestamp layer

        self.frameImages.append({'time': self.getTime, 'image': ii2, 'timestamp': ts})

    def mapurl(self, radar, rect, overlayonly):
        if usemapbox:
            if overlayonly:
                return self.mapboxoverlayurl(radar, rect)
            else:
                return self.mapboxbaseurl(radar, rect)
        else:
            return self.googlemapurl(radar, rect)

    @staticmethod
    def mapboxbaseurl(radar, rect):
        #  note we're using Google Maps zoom factor.
        #  Mapbox equivalent zoom is one less
        #  They seem to be using 512x512 tiles instead of 256x256
        basemap = 'mapbox/satellite-streets-v12'
        hide_attribution = ''
        if 'basemap' in radar:
            if radar['basemap'] != '':
                basemap = radar['basemap']
        if 'overlay' in radar:
            if radar['overlay'] != '':
                hide_attribution = '&attribution=false&logo=false'
        return 'https://api.mapbox.com/styles/v1/' + \
            basemap + \
            '/static/' + \
            str(radar['center'].lng) + ',' + \
            str(radar['center'].lat) + ',' + \
            str(radar['zoom'] - 1) + ',0,0/' + \
            str(rect.width()) + 'x' + str(rect.height()) + \
            '?access_token=' + ApiKeys.mbapi + \
            hide_attribution

    @staticmethod
    def mapboxoverlayurl(radar, rect):
        #  note we're using Google Maps zoom factor.
        #  Mapbox equivalent zoom is one less
        #  They seem to be using 512x512 tiles instead of 256x256
        overlay = ''
        if 'overlay' in radar:
            if radar['overlay'] != '':
                overlay = radar['overlay']
        return 'https://api.mapbox.com/styles/v1/' + \
            overlay + \
            '/static/' + \
            str(radar['center'].lng) + ',' + \
            str(radar['center'].lat) + ',' + \
            str(radar['zoom'] - 1) + ',0,0/' + \
            str(rect.width()) + 'x' + str(rect.height()) + \
            '?access_token=' + ApiKeys.mbapi

    @staticmethod
    def googlemapurl(radar, rect):
        urlp = []
        if len(ApiKeys.googleapi) > 0:
            urlp.append('key=' + ApiKeys.googleapi)
        urlp.append(
            'center=' + str(radar['center'].lat) +
            ',' + str(radar['center'].lng))
        zoom = radar['zoom']
        rsize = rect.size()
        if rsize.width() > 640 or rsize.height() > 640:
            rsize = QtCore.QSize(int(rsize.width() / 2), int(rsize.height() / 2))
            zoom -= 1
        urlp.append('zoom=' + str(zoom))
        urlp.append('size=' + str(rsize.width()) + 'x' + str(rsize.height()))
        urlp.append('maptype=hybrid')

        return 'http://maps.googleapis.com/maps/api/staticmap?' + \
            '&'.join(urlp)

    def basefinished(self, data=None):
        if data is None:
            self.basereply.deleteLater()
            data = bytes(self.basereply.readAll())
            if self.basereply.error() != QNetworkReply.NetworkError.NoError:
                basestr = str(data, 'utf-8')
                if usemapbox:
                    try:
                        basejson = json.loads(basestr)
                        print('ERROR: Response from api.mapbox.com: ' + basejson['message'])
                    except ValueError:  # includes json.decoder.JSONDecodeError
                        print('ERROR: Response from api.mapbox.com: ' + basestr)
                        pass
                else:
                    print('ERROR: Response from maps.googleapis.com: ' + basestr)
                return
            api_cache_write(self.basereply.url().toString(), data)
        basepixmap = QPixmap()
        basepixmap.loadFromData(data)
        if basepixmap.size() != self.rect.size():
            basepixmap = basepixmap.scaled(self.rect.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.setPixmap(basepixmap)

        # make marker pixmap
        mkpixmap = QPixmap(basepixmap.size())
        mkpixmap.fill(Qt.GlobalColor.transparent)
        br = QBrush(QColor(Config.dimcolor))
        painter = QPainter()
        painter.begin(mkpixmap)
        painter.fillRect(0, 0, mkpixmap.width(),
                         mkpixmap.height(), br)
        for marker in self.radar['markers']:
            if 'visible' not in marker or marker['visible'] == 1:
                pt = get_point(marker['location'], self.point, self.zoom,
                               self.rect.width(), self.rect.height())
                mk2 = QImage()
                mkfile = 'teardrop'
                if 'image' in marker:
                    mkfile = marker['image']
                if os.path.dirname(mkfile) == '':
                    mkfile = os.path.join('markers', mkfile)
                if os.path.splitext(mkfile)[1] == '':
                    mkfile += '.png'
                mk2.load(mkfile)
                if mk2.format() != QImage.Format.Format_ARGB32:
                    mk2 = mk2.convertToFormat(QImage.Format.Format_ARGB32)
                mkh = 80  # self.rect.height() / 5
                if 'size' in marker:
                    if marker['size'] == 'small':
                        mkh = 64
                    if marker['size'] == 'mid':
                        mkh = 70
                    if marker['size'] == 'tiny':
                        mkh = 40
                if 'color' in marker:
                    c = QColor(marker['color'])
                    (cr, cg, cb, ca) = c.getRgbF()
                    for x in range(0, mk2.width()):
                        for y in range(0, mk2.height()):
                            (r, g, b, a) = QColor.fromRgba(mk2.pixel(x, y)).getRgbF()
                            r = r * cr
                            g = g * cg
                            b = b * cb
                            mk2.setPixel(x, y, QColor.fromRgbF(r, g, b, a).rgba())
                mk2 = mk2.scaledToHeight(mkh, Qt.TransformationMode.SmoothTransformation)
                painter.drawImage(int(pt.x - mkh / 2), int(pt.y - mkh / 2), mk2)

        painter.end()

        self.wmk.setPixmap(mkpixmap)

    def overlayfinished(self, data=None):
        if data is None:
            self.overlayreply.deleteLater()
            data = bytes(self.overlayreply.readAll())
            if self.overlayreply.error() != QNetworkReply.NetworkError.NoError:
                overlaystr = str(data, 'utf-8')
                try:
                    overlayjson = json.loads(overlaystr)
                    print('ERROR: Response from api.mapbox.com: ' + overlayjson['message'])
                except ValueError:  # includes json.decoder.JSONDecodeError
                    print('ERROR: Response from api.mapbox.com: ' + overlaystr)
                    pass
                return
            api_cache_write(self.overlayreply.url().toString(), data)
        overlaypixmap = QPixmap()
        overlaypixmap.loadFromData(data)
        if overlaypixmap.size() != self.rect.size():
            overlaypixmap = overlaypixmap.scaled(
                self.rect.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation)
        self.overlay.setPixmap(overlaypixmap)

    def getbase(self):
        global manager
        cached = api_cache_read(self.baseurl, Config.radar_refresh * 60)
        if cached is not None:
            print(f'INFO: {self.myname} using cached base map')
            self.basefinished(cached)
        else:
            basereq = QNetworkRequest(QUrl(self.baseurl))
            self.basereply = manager.get(basereq)
            self.basereply.finished.connect(self.basefinished)

    def getoverlay(self):
        global manager
        cached = api_cache_read(self.overlayurl, Config.radar_refresh * 60)
        if cached is not None:
            print(f'INFO: {self.myname} using cached overlay map')
            self.overlayfinished(cached)
        else:
            overlayreq = QNetworkRequest(QUrl(self.overlayurl))
            self.overlayreply = manager.get(overlayreq)
            self.overlayreply.finished.connect(self.overlayfinished)

    def start(self, interval=0):
        """Start the radar display with an optional interval override"""
        if interval > 0:
            self.interval = interval
        self.getbase()

        if usemapbox:
            if 'overlay' in self.radar:
                if self.radar['overlay'] != '':
                    self.getoverlay()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.rtick)
        self.lastget = time.time() - self.interval + random.uniform(3, 10)

    def wxstart(self):
        print('INFO: wxstart for ' + self.myname)
        self.timer.start(200)

    def wxstop(self):
        print('INFO: wxstop for ' + self.myname)
        self.timer.stop()

    def stop(self):
        try:
            self.timer.stop()
            self.timer = None
        except AttributeError:
            print('WARNING:', traceback.format_exc())
            pass


def realquit():
    QtWidgets.QApplication.exit(0)


def myquit(signum, frame):
    global objradar1, objradar2, objradar3, objradar4
    global ctimer, wxtimer, temptimer, cursortimer, alerttimer

    objradar1.stop()
    objradar2.stop()
    objradar3.stop()
    objradar4.stop()
    ctimer.stop()
    wxtimer.stop()
    temptimer.stop()
    cursortimer.stop()
    alerttimer.stop()
    if Config.useslideshow:
        objimage1.stop()

    QtCore.QTimer.singleShot(30, realquit)


def fixupframe(frame, onoff):
    for child in frame.children():
        if isinstance(child, Radar):
            if onoff:
                # print('INFO: calling wxstart on radar on', frame.objectName())
                child.wxstart()
            else:
                # print('INFO: calling wxstop on radar on', frame.objectName())
                child.wxstop()


def nextframe(plusminus):
    global frames, framep
    frames[framep].setVisible(False)
    fixupframe(frames[framep], onoff=False)
    framep += plusminus
    if framep >= len(frames):
        framep = 0
    if framep < 0:
        framep = len(frames) - 1
    frames[framep].setVisible(True)
    fixupframe(frames[framep], onoff=True)


class MyMain(QtWidgets.QWidget):

    def keyPressEvent(self, event):
        global weatherplayer, lastkeytime
        if isinstance(event, QtGui.QKeyEvent):
            # print('INFO:', event.key(), format(event.key(), '08x'))
            if event.key() == Qt.Key.Key_F4:
                myquit(signal.SIGINT, None)
            if event.key() == Qt.Key.Key_F2:
                if time.time() > lastkeytime:
                    if weatherplayer is None:
                        weatherplayer = Popen(
                            ['mpg123', '-q', Config.noaastream])
                    else:
                        weatherplayer.kill()
                        weatherplayer = None
                lastkeytime = time.time() + 2
            if event.key() == Qt.Key.Key_Space:
                nextframe(1)
            if event.key() == Qt.Key.Key_Left:
                nextframe(-1)
            if event.key() == Qt.Key.Key_Right:
                nextframe(1)
            if event.key() == Qt.Key.Key_F6:  # Previous Image
                objimage1.prev_next(-1)
            if event.key() == Qt.Key.Key_F7:  # Next Image
                objimage1.prev_next(1)
            if event.key() == Qt.Key.Key_F8:  # Play/Pause
                objimage1.play_pause()
            if event.key() == Qt.Key.Key_F9:  # Foreground Toggle
                if foreGround.isVisible():
                    foreGround.hide()
                else:
                    foreGround.show()

    def mousePressEvent(self, event):
        if isinstance(event, QtGui.QMouseEvent):
            nextframe(1)


configname = 'Config'

if len(sys.argv) > 1:
    configname = sys.argv[1]

if not os.path.isfile(configname + '.py'):
    print('ERROR: Config file not found %s' % configname + '.py')
    exit(1)

Config = __import__(configname)

# define default values for new/optional config variables.

try:
    Config.metric
except AttributeError:
    Config.metric = 0

try:
    Config.weather_refresh
except AttributeError:
    Config.weather_refresh = 15  # minutes

try:
    Config.radar_refresh
except AttributeError:
    Config.radar_refresh = 10  # minutes

try:
    Config.fontattr
except AttributeError:
    Config.fontattr = ''

try:
    Config.dimcolor
except AttributeError:
    Config.dimcolor = QColor('#000000')
    Config.dimcolor.setAlpha(0)

try:
    Config.DateLocale
except AttributeError:
    Config.DateLocale = ''

try:
    Config.wind_degrees
except AttributeError:
    Config.wind_degrees = 0

try:
    Config.pressure_mbar
except AttributeError:
    Config.pressure_mbar = Config.metric

try:
    Config.fontmult
except AttributeError:
    Config.fontmult = 1.0

try:
    Config.cursor_idle_seconds
except AttributeError:
    Config.cursor_idle_seconds = 3.0  # seconds of no mouse movement before the cursor is hidden; 0 disables

try:
    Config.web_slideshow_playlist
except AttributeError:
    Config.web_slideshow_playlist = 0  # 0 = local images from Pictures/Slideshow, 1 = Config.slideshow_url

try:
    Config.slide_transition_ms
except AttributeError:
    Config.slide_transition_ms = 1000  # crossfade duration between slideshow images; 0 for an instant hard cut

try:
    Config.noaa_alerts_enabled
except AttributeError:
    Config.noaa_alerts_enabled = 1  # 1 to show a warning bubble for active NOAA/NWS alerts, 0 to disable

try:
    Config.alert_refresh
except AttributeError:
    Config.alert_refresh = 10  # minutes between NOAA severe weather alert checks

try:
    Config.alert_severities
except AttributeError:
    Config.alert_severities = ('Severe', 'Extreme')  # NWS severity levels that trigger the warning bubble
    # other possible values, from least to most severe: 'Unknown', 'Minor', 'Moderate', 'Severe', 'Extreme'

try:
    Config.LPressure
except AttributeError:
    Config.LPressure = 'Pressure '
    Config.LHumidity = 'Humidity '
    Config.LWind = 'Wind '
    Config.Lgusting = ' gust '
    Config.LFeelslike = 'Feels like '
    Config.LPrecip1hr = ' Precip 1hr:'
    Config.LToday = 'Today: '
    Config.LSunRise = 'Sun Rise: '
    Config.LSet = ' Set: '
    Config.LMoonPhase = ' Moon: '
    Config.LInsideTemp = 'Inside Temp '
    Config.LRain = ' Rain: '
    Config.LSnow = ' Snow: '

try:
    Config.Lmoon1
    Config.Lmoon2
    Config.Lmoon3
    Config.Lmoon4
    Config.Lmoon5
    Config.Lmoon6
    Config.Lmoon7
    Config.Lmoon8
except AttributeError:
    Config.Lmoon1 = 'New Moon'
    Config.Lmoon2 = 'Waxing Crescent'
    Config.Lmoon3 = 'First Quarter'
    Config.Lmoon4 = 'Waxing Gibbous'
    Config.Lmoon5 = 'Full Moon'
    Config.Lmoon6 = 'Waning Gibbous'
    Config.Lmoon7 = 'Third Quarter'
    Config.Lmoon8 = 'Waning Crescent'

try:
    Config.digitalformat2
except AttributeError:
    Config.digitalformat2 = '{0:%H:%M:%S}'

try:
    Config.useslideshow
except AttributeError:
    Config.useslideshow = 0

# Check if Mapbox API key is set, and use mapbox if so
usemapbox = 0
try:
    if ApiKeys.mbapi[:3].lower() == 'pk.':
        usemapbox = 1
except AttributeError:
    pass

hasMetar = False
try:
    if Config.METAR != '':
        hasMetar = True
        from metar import Metar
except AttributeError:
    pass

lastmin = -1
lastday = -1
pdy = ''
lasttimestr = ''
weatherplayer = None
lastkeytime = 0
lastapiget = time.time()

# Pressure trend tracking: samples are recorded every time fresh weather data
# arrives, but the displayed arrow only refreshes once an hour (see
# pressuretrendtimer in qtstart()), based on the change over the last 2 hours.
PRESSURE_TREND_WINDOW_SEC = 2 * 60 * 60
PRESSURE_TREND_DEADBAND_INHG = 0.02  # ~0.68 hPa; ignore noise below this over the window
pressure_history = []  # list of (unix_timestamp, pressure_inHg)
pressure_trend_arrow = ''
pressure_label_text = ''

app = QtWidgets.QApplication(sys.argv)
rec = app.primaryScreen().geometry()
height = rec.height()
width = rec.width()

# MacBooks with a camera notch (14"/16" MacBook Pro 2021+, some MacBook Air
# models) report a non-zero top safeAreaInsets for the built-in display; this
# is 0 on displays without a notch (external monitors, older MacBooks).
mac_appkit = None
mac_notch_inset = 0
if platform.system() == 'Darwin':
    try:
        import AppKit as mac_appkit
        mac_notch_inset = int(mac_appkit.NSScreen.mainScreen().safeAreaInsets().top)
    except ImportError:
        print('WARNING: pyobjc-framework-Cocoa not installed; menu bar will not auto-hide '
              'and top content will not avoid the MacBook notch. '
              'Install with: pip install pyobjc-framework-Cocoa')

signal.signal(signal.SIGINT, myquit)

w = MyMain()
w.setWindowTitle(os.path.basename(__file__))

w.setStyleSheet('QWidget { background-color: black;}')

xscale = float(width) / 1440.0
yscale = float(height) / 900.0

frames = []
framep = 0

frame1 = QtWidgets.QFrame(w)
frame1.setObjectName('frame1')
frame1.setGeometry(0, 0, width, height)
frame1.setStyleSheet('#frame1 { background-color: black; border-image: url(' +
                     Config.background + ') 0 0 0 0 stretch stretch;}')
frames.append(frame1)

if Config.useslideshow:
    imgRect = QtCore.QRect(0, 0, int(width), int(height))
    objimage1 = SlideShow(frame1, imgRect, 'image1')

frame2 = QtWidgets.QFrame(w)
frame2.setObjectName('frame2')
frame2.setGeometry(0, 0, width, height)
frame2.setStyleSheet('#frame2 { background-color: black; border-image: url(' +
                     Config.background + ') 0 0 0 0 stretch stretch;}')
frame2.setVisible(False)
frames.append(frame2)

foreGround = QtWidgets.QFrame(frame1)
foreGround.setObjectName('foreGround')
foreGround.setStyleSheet('#foreGround { background-color: transparent; }')
foreGround.setGeometry(0, 0, width, height)

clockface = QtWidgets.QLabel(foreGround)
clockface.setObjectName('clockface')
clockrect = QtCore.QRect(
    int(width / 2 - height * .4),
    int(height * .45 - height * .4),
    int(height * .8),
    int(height * .8))
clockface.setGeometry(clockrect)
dcolor = QColor(Config.digitalcolor).darker(0).name()
lcolor = QColor(Config.digitalcolor).lighter(120).name()
clockface.setStyleSheet(
    '#clockface { background-color: transparent; font-family:"Open Sans";' +
    ' font-weight: light; color: ' +
    lcolor +
    '; background-color: transparent; font-size: ' +
    str(int(Config.digitalsize * xscale)) +
    'px; ' +
    Config.fontattr +
    '}')
clockface.setAlignment(Qt.AlignmentFlag.AlignCenter)
clockface.setGeometry(clockrect)
glow = QtWidgets.QGraphicsDropShadowEffect()
glow.setOffset(0)
glow.setBlurRadius(50)
glow.setColor(QColor(dcolor))
clockface.setGraphicsEffect(glow)

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(clockface)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
clockface.setGraphicsEffect(shadow)



radar1rect = QtCore.QRect(int(3 * xscale), int(344 * yscale), int(300 * xscale), int(275 * yscale))
objradar1 = Radar(foreGround, Config.radar1, radar1rect, 'radar1')

radar2rect = QtCore.QRect(int(3 * xscale), int(622 * yscale), int(300 * xscale), int(275 * yscale))
objradar2 = Radar(foreGround, Config.radar2, radar2rect, 'radar2')

radar3rect = QtCore.QRect(int(13 * xscale), int(50 * yscale), int(700 * xscale), int(700 * yscale))
objradar3 = Radar(frame2, Config.radar3, radar3rect, 'radar3')

radar4rect = QtCore.QRect(int(726 * xscale), int(50 * yscale), int(700 * xscale), int(700 * yscale))
objradar4 = Radar(frame2, Config.radar4, radar4rect, 'radar4')

datex = QtWidgets.QLabel(foreGround)
datex.setObjectName('datex')
datex.setStyleSheet('#datex { font-family:"Open Sans"; color: ' +
                    Config.textcolor +
                    '; background-color: transparent; font-size: ' +
                    str(int(50 * xscale * Config.fontmult)) +
                    'px; ' +
                    Config.fontattr +
                    '}')
datex.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
datex.setGeometry(0, mac_notch_inset, width, int(100 * yscale))

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(datex)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
datex.setGraphicsEffect(shadow)


datex2 = QtWidgets.QLabel(frame2)
datex2.setObjectName('datex2')
datex2.setStyleSheet('#datex2 { font-family:"Open Sans"; color: ' +
                     Config.textcolor +
                     '; background-color: transparent; font-size: ' +
                     str(int(50 * xscale * Config.fontmult)) + 'px; ' +
                     Config.fontattr +
                     '}')
datex2.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
datex2.setGeometry(int(800 * xscale), int(760 * yscale), int(640 * xscale), 100)

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(datex2)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
datex2.setGraphicsEffect(shadow)


datey2 = QtWidgets.QLabel(frame2)
datey2.setObjectName('datey2')
datey2.setStyleSheet('#datey2 { font-family:"Open Sans"; color: ' +
                     Config.textcolor +
                     '; background-color: transparent; font-size: ' +
                     str(int(50 * xscale * Config.fontmult)) +
                     'px; ' +
                     Config.fontattr +
                     '}')
datey2.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
datey2.setGeometry(int(800 * xscale), int(820 * yscale), int(640 * xscale), 100)

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(datey2)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
datey2.setGraphicsEffect(shadow)


ypos = -10
wxicon = QtWidgets.QLabel(foreGround)
wxicon.setObjectName('wxicon')
wxicon.setStyleSheet('#wxicon { background-color: transparent; }')
wxicon.setGeometry(int(75 * xscale), int(ypos * yscale), int(150 * xscale), int(150 * yscale))

attribution = QtWidgets.QLabel(foreGround)
attribution.setObjectName('attribution')
attribution.setStyleSheet('#attribution { ' +
                          ' background-color: transparent; color: ' +
                          Config.textcolor +
                          '; font-size: ' +
                          str(int(12 * xscale)) +
                          'px; ' +
                          Config.fontattr +
                          '}')
attribution.setAlignment(Qt.AlignmentFlag.AlignTop)
attribution.setGeometry(int(6 * xscale), int(3 * yscale), int(130 * xscale), 100)

wxicon2 = QtWidgets.QLabel(frame2)
wxicon2.setObjectName('wxicon2')
wxicon2.setStyleSheet('#wxicon2 { background-color: transparent; }')
wxicon2.setGeometry(int(0 * xscale), int(750 * yscale), int(150 * xscale), int(150 * yscale))

attribution2 = QtWidgets.QLabel(frame2)
attribution2.setObjectName('attribution2')
attribution2.setStyleSheet('#attribution2 { ' +
                           'background-color: transparent; color: ' +
                           Config.textcolor +
                           '; font-size: ' +
                           str(int(12 * xscale * Config.fontmult)) +
                           'px; ' +
                           Config.fontattr +
                           '}')
attribution2.setAlignment(Qt.AlignmentFlag.AlignTop)
attribution2.setGeometry(int(6 * xscale), int(880 * yscale), int(130 * xscale), 100)

ypos += 140
wxdesc = QtWidgets.QLabel(foreGround)
wxdesc.setObjectName('wxdesc')
wxdesc.setStyleSheet('#wxdesc { background-color: transparent; color: ' +
                     Config.textcolor +
                     '; font-size: ' +
                     str(int(30 * xscale)) +
                     'px; ' +
                     Config.fontattr +
                     '}')
wxdesc.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
wxdesc.setGeometry(int(3 * xscale), int(ypos * yscale), int(300 * xscale), 100)

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(wxdesc)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
wxdesc.setGraphicsEffect(shadow)


wxdesc2 = QtWidgets.QLabel(frame2)
wxdesc2.setObjectName('wxdesc2')
wxdesc2.setStyleSheet('#wxdesc2 { background-color: transparent; color: ' +
                      Config.textcolor +
                      '; font-size: ' +
                      str(int(50 * xscale * Config.fontmult)) +
                      'px; ' +
                      Config.fontattr +
                      '}')
wxdesc2.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
wxdesc2.setGeometry(int(400 * xscale), int(800 * yscale), int(400 * xscale), 100)

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(wxdesc2)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
wxdesc2.setGraphicsEffect(shadow)

ypos += 33
temper = QtWidgets.QLabel(foreGround)
temper.setObjectName('temper')
temper.setStyleSheet('#temper { background-color: transparent; color: ' +
                     Config.textcolor +
                     '; font-size: ' +
                     str(int(50 * xscale * Config.fontmult)) +
                     'px; ' +
                     Config.fontattr +
                     '}')
temper.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
temper.setGeometry(int(3 * xscale), int(ypos * yscale), int(300 * xscale), int(100 * yscale))

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(temper)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
temper.setGraphicsEffect(shadow)


temper2 = QtWidgets.QLabel(frame2)
temper2.setObjectName('temper2')
temper2.setStyleSheet('#temper2 { background-color: transparent; color: ' +
                      Config.textcolor +
                      '; font-size: ' +
                      str(int(70 * xscale * Config.fontmult)) +
                      'px; ' +
                      Config.fontattr +
                      '}')
temper2.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
temper2.setGeometry(int(125 * xscale), int(780 * yscale), int(300 * xscale), 100)

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(temper2)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
temper2.setGraphicsEffect(shadow)


ypos += 61
feelslike = QtWidgets.QLabel(foreGround)
feelslike.setObjectName('feelslike')
feelslike.setStyleSheet('#feelslike { background-color: transparent; color: ' +
                        Config.textcolor +
                        '; font-size: ' +
                        str(int(26 * xscale * Config.fontmult)) +
                        'px; font-style: italic; ' +  # Add this line to make the font italic
                        Config.fontattr +
                        '}')
feelslike.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
feelslike.setGeometry(int(3 * xscale), int(ypos * yscale), int(300 * xscale), 100)

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(feelslike)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
feelslike.setGraphicsEffect(shadow)


ypos += 35
humidity = QtWidgets.QLabel(foreGround)
humidity.setObjectName('humidity')
humidity.setStyleSheet('#humidity { background-color: transparent; color: ' +
                       Config.textcolor +
                       '; font-size: ' +
                       str(int(17 * xscale * Config.fontmult)) +
                       'px; ' +
                       Config.fontattr +
                       '}')
humidity.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
humidity.setGeometry(int(3 * xscale), int(ypos * yscale), int(300 * xscale), 100)

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(humidity)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
humidity.setGraphicsEffect(shadow)


ypos += 22
press = QtWidgets.QLabel(foreGround)
press.setObjectName('press')
press.setStyleSheet('#press { background-color: transparent; color: ' +
                    Config.textcolor +
                    '; font-size: ' +
                    str(int(17 * xscale * Config.fontmult)) +
                    'px; ' +
                    Config.fontattr +
                    '}')
press.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
press.setGeometry(int(3 * xscale), int(ypos * yscale), int(300 * xscale), 100)

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(press)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
press.setGraphicsEffect(shadow)


ypos += 22
wind = QtWidgets.QLabel(foreGround)
wind.setObjectName('wind')
wind.setStyleSheet('#wind { background-color: transparent; color: ' +
                   Config.textcolor +
                   '; font-size: ' +
                   str(int(17 * xscale * Config.fontmult)) +
                   'px; ' +
                   Config.fontattr +
                   '}')
wind.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
wind.setGeometry(int(3 * xscale), int(ypos * yscale), int(300 * xscale), 100)

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(wind)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
wind.setGraphicsEffect(shadow)


ypos += 25
wdate = QtWidgets.QLabel(foreGround)
wdate.setObjectName('wdate')
wdate.setStyleSheet('#wdate { background-color: transparent; color: ' +
                    Config.textcolor +
                    '; font-size: ' +
                    str(int(11 * xscale * Config.fontmult)) +
                    'px; ' +
                    Config.fontattr +
                    '}')
wdate.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
wdate.setGeometry(int(3 * xscale), int(ypos * yscale), int(300 * xscale), 100)

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(wdate)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
wdate.setGraphicsEffect(shadow)


bottom = QtWidgets.QLabel(foreGround)
bottom.setObjectName('bottom')
bottom.setStyleSheet('#bottom { font-family:"Open Sans"; color: ' +
                     Config.textcolor +
                     '; background-color: transparent; font-size: ' +
                     str(int(24 * xscale * Config.fontmult)) +
                     'px; ' +
                     Config.fontattr +
                     '}')
bottom.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
bottom.setGeometry(0, int(height - 50 * yscale), width, int(50 * yscale))

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(bottom)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
bottom.setGraphicsEffect(shadow)

# Severe weather warning bubble: below the clock, above the sunrise/set footer.
alertrect = QtCore.QRect(
    int(width * 0.2),
    int(height * 0.855),
    int(width * 0.6),
    int(height * 0.075))
alertBubble = AlertBubble(foreGround, alertrect)


temp = QtWidgets.QLabel(foreGround)
temp.setObjectName('temp')
temp.setStyleSheet('#temp { font-family:"Open Sans"; color: ' +
                   Config.textcolor +
                   '; background-color: transparent; font-size: ' +
                   str(int(30 * xscale * Config.fontmult)) +
                   'px; ' +
                   Config.fontattr +
                   '}')
temp.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
temp.setGeometry(0, int(height - 100 * yscale), width, int(50 * yscale))

# Create a drop shadow effect
shadow = QtWidgets.QGraphicsDropShadowEffect(temp)
shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
shadow.setBlurRadius(10)                # Blur for smooth edges
shadow.setOffset(2, 2)                  # Offset for the shadow (x, y)

# Apply the shadow effect to the label
temp.setGraphicsEffect(shadow)


tzlatlng = pytz.utc
forecast = []

for i in range(0, 9):
    lab = QtWidgets.QLabel(foreGround)
    lab.setObjectName('forecast' + str(i))
    lab.setStyleSheet('QWidget { background-color: transparent; color: ' +
                      Config.textcolor +
                      '; font-size: ' +
                      str(int(17 * xscale * Config.fontmult)) +
                      'px; ' +
                      Config.fontattr +
                      '}')


    lab.setGeometry(int(1137 * xscale), int(i * 100 * yscale), int(300 * xscale), int(100 * yscale))

    # Apply shadow to the main label
    shadow = QtWidgets.QGraphicsDropShadowEffect(lab)
    shadow.setColor(QtGui.QColor(0, 0, 0))  # Black shadow
    shadow.setBlurRadius(10)                # Smooth edges
    shadow.setOffset(2, 2)                  # Shadow offset
    lab.setGraphicsEffect(shadow)

    icon = QtWidgets.QLabel(lab)
    icon.setStyleSheet('#icon { background-color: transparent; }')
    icon.setGeometry(0, 0, int(100 * xscale), int(100 * yscale))
    icon.setObjectName('icon')

    wx = QtWidgets.QLabel(lab)
    wx.setStyleSheet('#wx { background-color: transparent; }')
    wx.setGeometry(int(100 * xscale), int(5 * yscale), int(200 * xscale), int(120 * yscale))
    wx.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
    wx.setWordWrap(True)
    wx.setObjectName('wx')

    # Apply shadow to the weather description label
    shadow_wx = QtWidgets.QGraphicsDropShadowEffect(wx)
    shadow_wx.setColor(QtGui.QColor(0, 0, 0))
    shadow_wx.setBlurRadius(10)
    shadow_wx.setOffset(2, 2)
    wx.setGraphicsEffect(shadow_wx)

    day = QtWidgets.QLabel(lab)
    day.setStyleSheet('#day { background-color: transparent; }')
    day.setGeometry(int(100 * xscale), int(75 * yscale), int(200 * xscale), int(25 * yscale))
    day.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
    day.setObjectName('day')

    # Apply shadow to the day label
    shadow_day = QtWidgets.QGraphicsDropShadowEffect(day)
    shadow_day.setColor(QtGui.QColor(0, 0, 0))
    shadow_day.setBlurRadius(10)
    shadow_day.setOffset(2, 2)
    day.setGraphicsEffect(shadow_day)

    forecast.append(lab)


manager = QtNetwork.QNetworkAccessManager()

stimer = QtCore.QTimer()
stimer.singleShot(10, qtstart)

if platform.system() == 'Darwin':
    # On macOS, showFullScreen() reserves space for the menu bar: the window
    # ends up offset down by the menu bar height but still sized to the full
    # screen height, so that same amount gets clipped off the bottom. A
    # borderless window explicitly sized to the full screen avoids the clipping.
    # NoDropShadowWindowHint suppresses the native NSWindow drop shadow Cocoa
    # would otherwise still render around a frameless window, which shows up
    # as a thin border around the edges of the screen.
    w.setWindowFlags(w.windowFlags() |
                      Qt.WindowType.FramelessWindowHint |
                      Qt.WindowType.NoDropShadowWindowHint)
    w.setGeometry(rec)
    w.show()
    if mac_appkit is not None:
        mac_appkit.NSApplication.sharedApplication().setPresentationOptions_(
            mac_appkit.NSApplicationPresentationAutoHideMenuBar |
            mac_appkit.NSApplicationPresentationAutoHideDock
        )
else:
    # Comment out w.show() to prevent issues on Wayland based systems. Uncomment on RPi systems.
    # w.show()
    w.showFullScreen()

sys.exit(app.exec())
