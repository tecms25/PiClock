# -*- coding: utf-8 -*-

import atexit
import datetime
import hashlib
import json
import locale
import math
import os
import platform
import random
import signal
import subprocess
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
from GoogleMercatorProjection import get_corners, get_point, get_tile_xy, LatLng
import ApiKeys


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

# How often a radar retries a base map or overlay that failed to download,
# until it succeeds. Covers booting before the network is up.
MAP_RETRY_MS = 10 * 60 * 1000


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


def _hhmm_to_minutes(value):
    hh, mm = value.split(':')
    return int(hh) * 60 + int(mm)


def get_brightness_percent(now):
    """Target 0-100 display brightness for `now`, per Config.day_start/
    night_start (24-hour HH:MM), with an optional linear fade over
    Config.brightness_transition_minutes at each transition."""
    if not Config.brightness_enabled:
        return 100

    day_start = _hhmm_to_minutes(Config.day_start)
    night_start = _hhmm_to_minutes(Config.night_start)
    now_min = now.hour * 60 + now.minute + now.second / 60.0
    trans = max(0.0, Config.brightness_transition_minutes)

    def minutes_since(start):
        d = now_min - start
        if d < 0:
            d += 24 * 60
        return d

    since_day = minutes_since(day_start)
    since_night = minutes_since(night_start)

    if trans > 0 and since_day < trans:
        return Config.night_brightness + (Config.day_brightness - Config.night_brightness) * (since_day / trans)
    if trans > 0 and since_night < trans:
        return Config.day_brightness + (Config.night_brightness - Config.day_brightness) * (since_night / trans)

    day_length = (night_start - day_start) % (24 * 60)
    if since_day < day_length:
        return Config.day_brightness
    return Config.night_brightness


def apply_brightness(percent):
    global last_brightness_percent
    percent = max(0.0, min(100.0, percent))
    if abs(percent - last_brightness_percent) < 0.5:
        return
    last_brightness_percent = percent
    alpha = int(round(255 * (1 - percent / 100.0)))
    brightness_overlay.setStyleSheet(
        '#brightness_overlay { background-color: rgba(0, 0, 0, %d); }' % alpha)


def _macos_declare_user_active():
    Popen(['caffeinate', '-u', '-t', '5'],
          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def release_display_sleep():
    """Stop the keep-awake helpers started by prevent_display_sleep().

    Registered with atexit as well as being called from myquit(), because the
    helper is a child process: if PiClock ever exits without going through
    myquit() - an unhandled exception, or the window being closed - an
    unreleased helper would outlive it and keep the display awake for good.
    Safe to call more than once."""
    global sleep_inhibit_process, keepalive_timer
    if keepalive_timer is not None:
        keepalive_timer.stop()
        keepalive_timer = None
    if sleep_inhibit_process is not None:
        sleep_inhibit_process.terminate()
        sleep_inhibit_process = None


def prevent_display_sleep():
    """Best-effort: stop the OS from blanking/sleeping the display while the
    clock is running. Each platform uses its own native mechanism; failures
    are swallowed since not every desktop environment exposes one."""
    global sleep_inhibit_process, keepalive_timer
    if not Config.prevent_screen_sleep:
        return
    atexit.register(release_display_sleep)
    system = platform.system()
    try:
        if system == 'Windows':
            import ctypes
            ES_CONTINUOUS = 0x80000000
            ES_SYSTEM_REQUIRED = 0x00000001
            ES_DISPLAY_REQUIRED = 0x00000002
            ctypes.windll.kernel32.SetThreadExecutionState(
                ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED)
        elif system == 'Darwin':
            sleep_inhibit_process = Popen(['caffeinate', '-d', '-i'])
            # 'caffeinate -d -i' only stops true display/system sleep; macOS's
            # screensaver and lock-screen run off a separate HID-idle clock
            # that ignores it. Periodically declaring "user activity" (the
            # same signal IOPMAssertionDeclareUserActivity sends for a real
            # key press/mouse move) resets that clock too, so the screensaver
            # and lock never trigger.
            keepalive_timer = QtCore.QTimer()
            keepalive_timer.timeout.connect(_macos_declare_user_active)
            keepalive_timer.start(45 * 1000)
        elif system == 'Linux':
            # X11 desktops: disable the built-in screensaver/DPMS blanking.
            for args in (['xset', 's', 'off'], ['xset', 's', 'noblank'], ['xset', '-dpms']):
                try:
                    subprocess.run(args, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=5)
                except (OSError, subprocess.SubprocessError):
                    pass
            # systemd-logind idle/sleep inhibit; covers most desktop
            # environments on both X11 and Wayland (including Raspberry Pi OS).
            try:
                sleep_inhibit_process = Popen(
                    ['systemd-inhibit', '--what=idle:sleep',
                     '--who=PiClock', '--why=Always-on clock display',
                     'sleep', 'infinity'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                pass
    except Exception:
        print('WARNING:', traceback.format_exc())


def tick():
    global lastmin, lastday, lasttimestr
    global clockrect
    global datex, datex2, datey2, pdy
    global sun, daytime, sunrise, sunset
    global bottom

    now = datetime.datetime.now(tz=tzlocal.get_localzone())
    apply_brightness(get_brightness_percent(now))
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


def nm2miles(f):
    return f * 1.15078  # distance nautical miles to statute miles


def nm2km(f):
    return f * 1.852  # distance nautical miles to kilometers


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


# Tomorrow.io weather codes to display text. Overridden by Config.Ltm_code_map
# (for other languages) on the first getallwx() call.
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

        # Precipitation expected but too little to accumulate: probability only.
        if pop >= 1 and ptype > 0:
            if ptype == 1 and raccum < 0.10 and saccum < 0.10:
                s += Config.LRain + '%.0f' % pop + '%'
            elif ptype == 2 and saccum < 0.10 and raccum < 0.10:
                s += Config.LSnow + '%.0f' % pop + '%'

        # Enough to accumulate: probability plus the projected amount.
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

            if Config.metric:
                s += '%.0f' % tempf2tempc(f['values']['temperatureMax']) + '/' + \
                     '%.0f' % tempf2tempc(f['values']['temperatureMin']) + u'°C '
            else:
                s += '%.0f' % f['values']['temperatureMax'] + '/' + \
                     '%.0f' % f['values']['temperatureMin'] + u'°F '

            # Precipitation expected but too little to accumulate: probability only.
            if pop >= 1 and ptype > 0:
                if ptype == 1 and raccum < 0.10 and saccum < 0.10:
                    s += Config.LRain + '%.0f' % pop + '%'
                elif ptype == 2 and saccum < 0.10 and raccum < 0.10:
                    s += Config.LSnow + '%.0f' % pop + '%'

            # Enough to accumulate: probability plus the projected amount.
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
            # Fewer forecast intervals than slots; leave the remaining ones as-is.
            print('WARNING:', traceback.format_exc())


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

    ('GR', '', '+', 'Heavy Hail', 'thunderstorm', 14),
    ('GR', '', '', 'Hail', 'thunderstorm', 14),
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
    wdate.setText('{0:%H:%M %Z} {1}'.format(dt, Config.METAR))


def record_pressure_sample(value_inhg):
    # Keep a rolling 2-hour history of raw pressure readings (inHg) so
    # update_pressure_trend() has data to compare against later.
    global pressure_history
    now = time.time()
    pressure_history.append((now, value_inhg))
    cutoff = now - PRESSURE_TREND_WINDOW_SEC
    pressure_history[:] = [(t, v) for (t, v) in pressure_history if t >= cutoff]


def show_pressure():
    """Draw the pressure reading, with the trend arrow in its own label beside
    it.

    The arrow is deliberately not part of the pressure label. Inline, a larger
    glyph grows the line box, which pushes the reading down (the label is top
    aligned) and sideways (it is centre aligned). A separate label leaves the
    reading exactly where it was.
    """
    press.setText(pressure_label_text)
    if not pressure_trend_arrow:
        pressarrow.hide()
        return
    metrics = press.fontMetrics()
    text_w = metrics.horizontalAdvance(pressure_label_text)
    line_h = metrics.height()
    box_h = int(line_h * PRESSURE_ARROW_SCALE * 1.4)
    left = press.x() + press.width() // 2 + text_w // 2 + int(5 * xscale)
    pressarrow.setText(pressure_trend_arrow)
    pressarrow.setGeometry(left, press.y() + line_h // 2 - box_h // 2,
                           int(46 * xscale), box_h)
    pressarrow.show()


def set_pressure_label(pressure_str, value_inhg):
    """Record a new pressure sample (if any) and (re)render the pressure label
    using the current, possibly stale, trend arrow. The arrow itself is only
    recalculated by update_pressure_trend(), once an hour."""
    global pressure_label_text
    pressure_label_text = pressure_str
    if value_inhg is not None:
        record_pressure_sample(value_inhg)
    show_pressure()


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
            pressure_trend_arrow = u'↑'
        elif delta <= -PRESSURE_TREND_DEADBAND_INHG:
            pressure_trend_arrow = u'↓'
        # else: within the deadband, keep the previous arrow to avoid flicker
    show_pressure()


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


def _parse_alert_time(value):
    if not value:
        return None
    try:
        return dateutil.parser.parse(value).astimezone(tzlocal.get_localzone())
    except (ValueError, OverflowError):
        return None


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
        alerts.append({
            'event': props.get('event', 'Alert'),
            'headline': props.get('headline', ''),
            'description': props.get('description', '') or '',
            'instruction': props.get('instruction', '') or '',
            'area': props.get('areaDesc', ''),
            'severity': props.get('severity', ''),
            'certainty': props.get('certainty', ''),
            'urgency': props.get('urgency', ''),
            'sender': props.get('senderName', ''),
            'effective': _parse_alert_time(props.get('effective')),
            'expires': _parse_alert_time(props.get('expires')),
        })

    if alerts:
        print(f'INFO: {len(alerts)} active NOAA alert(s): ' + ', '.join(a['event'] for a in alerts))
    alertBubble.set_alerts(alerts)
    update_bubble_priority()


# --- Aircraft overhead (airplanes.live) --------------------------------------
# A community ADS-B feed, no API key needed. Only aircraft high enough in the
# sky to actually be worth looking up at are shown - see flight_elevation().
FLIGHT_API = 'https://api.airplanes.live/v2/point/%s/%s/%d'
FEET_PER_NM = 6076.12

# Callsign prefixes are ICAO airline codes. The feed's ownOp field is the
# registered owner, which is often a leasing trust rather than the airline
# flying it, so the callsign is the reliable signal. Unlisted codes just show
# the raw callsign.
ICAO_AIRLINES = {
    # North America
    'AAL': 'American', 'AAY': 'Allegiant', 'ACA': 'Air Canada', 'ASA': 'Alaska',
    'ASH': 'Mesa', 'AWI': 'Air Wisconsin', 'DAL': 'Delta', 'EDV': 'Endeavor',
    'ENY': 'Envoy', 'FFT': 'Frontier', 'GJS': 'GoJet', 'HAL': 'Hawaiian',
    'JBU': 'JetBlue', 'JIA': 'PSA', 'JZA': 'Jazz', 'KAP': 'Cape Air',
    'MXY': 'Breeze', 'NKS': 'Spirit', 'PDT': 'Piedmont', 'POE': 'Porter',
    'QXE': 'Horizon', 'ROU': 'Air Canada Rouge', 'RPA': 'Republic',
    'SCX': 'Sun Country', 'SKW': 'SkyWest', 'SWA': 'Southwest',
    'TSC': 'Air Transat', 'UAL': 'United', 'VOI': 'Volaris', 'WJA': 'WestJet',
    # Cargo
    'ABX': 'ABX Air', 'CKS': 'Kalitta', 'CLX': 'Cargolux', 'FDX': 'FedEx',
    'GEC': 'Lufthansa Cargo', 'GTI': 'Atlas Air', 'PAC': 'Polar Air',
    'UPS': 'UPS',
    # Business / fractional
    'EJA': 'NetJets', 'LXJ': 'Flexjet',
    # Europe
    'AUA': 'Austrian', 'AFR': 'Air France', 'BAW': 'British Airways',
    'BEL': 'Brussels', 'CFG': 'Condor', 'DLH': 'Lufthansa', 'EIN': 'Aer Lingus',
    'EZY': 'easyJet', 'FIN': 'Finnair', 'IBE': 'Iberia', 'ICE': 'Icelandair',
    'KLM': 'KLM', 'LOT': 'LOT', 'NAX': 'Norwegian', 'RYR': 'Ryanair',
    'SAS': 'SAS', 'SWR': 'Swiss', 'TAP': 'TAP', 'THY': 'Turkish',
    'VIR': 'Virgin Atlantic', 'VLG': 'Vueling', 'WZZ': 'Wizz Air',
    # Rest of world
    'AMX': 'Aeromexico', 'ANA': 'All Nippon', 'ANZ': 'Air New Zealand',
    'AVA': 'Avianca', 'CPA': 'Cathay Pacific', 'CMP': 'Copa', 'ETD': 'Etihad',
    'ETH': 'Ethiopian', 'JAL': 'Japan Airlines', 'KAL': 'Korean Air',
    'LAN': 'LATAM', 'QFA': 'Qantas', 'QTR': 'Qatar', 'SIA': 'Singapore',
    'UAE': 'Emirates', 'VOZ': 'Virgin Australia',
    # Other
    'CAP': 'Civil Air Patrol',
}


# Which way to look, drawn as an arrow. North is up, matching how you would
# hold a map. Keys are exactly what bearing() returns, so the arrow and the
# written compass point can never disagree.
COMPASS_ARROWS = {
    'N': '\u2191', 'NE': '\u2197', 'E': '\u2192', 'SE': '\u2198',
    'S': '\u2193', 'SW': '\u2199', 'W': '\u2190', 'NW': '\u2196',
}


def flight_elevation(alt_ft, dist_nm):
    """Degrees above the horizon an aircraft appears at.

    Distance alone is the wrong test: a jet at 35,000ft is genuinely overhead
    at 10nm but a speck at 30nm. The angle folds altitude and distance into
    the one number that matches what you would actually see.
    """
    ground_ft = dist_nm * FEET_PER_NM
    if ground_ft <= 0:
        return 90.0
    return math.degrees(math.atan2(alt_ft, ground_ft))


def get_flights():
    """Ask for aircraft near Config.location, if the feature is switched on."""
    global manager, flightReply
    if not Config.flights_enabled:
        return
    url = FLIGHT_API % (Config.location.lat, Config.location.lng,
                        Config.flight_search_radius_nm)
    req = QNetworkRequest(QUrl(url))
    req.setRawHeader(b'User-Agent', b'PiClock/1.0 (https://github.com/tecms25/PiClock)')
    flightReply = manager.get(req)
    flightReply.finished.connect(flights_finished)


def flights_finished():
    global flightReply

    flightReply.deleteLater()
    if flightReply.error() != QNetworkReply.NetworkError.NoError:
        print('ERROR: Response from airplanes.live: ' + flightReply.errorString())
        return
    try:
        data = json.loads(str(bytes(flightReply.readAll()), 'utf-8'))
    except ValueError:
        print('WARNING:', traceback.format_exc())
        print('WARNING: could not parse the airplanes.live response')
        return

    overhead = []
    for craft in data.get('ac') or []:
        alt = craft.get('alt_baro')
        dist = craft.get('dst')
        if alt is None or dist is None or alt == 'ground':
            continue  # on the ground, or not reporting altitude
        try:
            alt = float(alt)
            dist = float(dist)
        except (TypeError, ValueError):
            continue
        elevation = flight_elevation(alt, dist)
        if elevation < Config.flight_min_elevation:
            continue
        overhead.append({
            'icao': (craft.get('hex') or '').strip(),
            'callsign': (craft.get('flight') or '').strip(),
            'registration': (craft.get('r') or '').strip(),
            'kind': (craft.get('desc') or craft.get('t') or '').strip(),
            'altitude_ft': alt,
            'distance_nm': dist,
            'bearing_deg': craft.get('dir'),
            'speed_kt': craft.get('gs'),
            'elevation_deg': elevation,
        })

    # Highest in the sky first: that is the one most worth looking up at.
    overhead.sort(key=lambda c: c['elevation_deg'], reverse=True)
    if overhead:
        print('INFO: %d aircraft overhead: ' % len(overhead) +
              ', '.join((c['callsign'] or c['registration'] or '?') for c in overhead))
    flightBubble.set_items(overhead)
    update_bubble_priority()


def update_bubble_priority():
    """The alert bar owns that slot on the screen. Aircraft step aside until
    the severe weather alert has cleared."""
    if hasattr(Config, 'flights_enabled') and Config.flights_enabled:
        flightBubble.set_suppressed(bool(alertBubble.items))


def qtstart():
    global ctimer, wxtimer, temptimer, metadatatimer, cursortimer, alerttimer
    global apicachecleanuptimer, flighttimer
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

    # Only page 1's radars animate at startup; radar3/4 start when that page
    # is shown (see fixupframe()).
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

    # Aircraft passing overhead, if switched on
    if Config.flights_enabled:
        global flighttimer
        flighttimer = QtCore.QTimer()
        flighttimer.timeout.connect(get_flights)
        flighttimer.start(int(1000 * Config.flight_poll_seconds + random.uniform(200, 2000)))
        get_flights()

    if Config.useslideshow:
        objimage1.start(Config.slide_time)


# web_slideshow_playlist = 0: random images from this folder (repo-root-relative,
# resolved from this file's own location so it works regardless of cwd).
SLIDESHOW_LOCAL_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'Pictures', 'Slideshow'))
# web_slideshow_playlist = 1 and 2: downloaded images are cached here.
SLIDESHOW_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'slideshow_cache')
SLIDESHOW_PLAYLIST_REFRESH_SEC = 2 * 60 * 60  # re-check the web playlist for changes every 2 hours
SLIDESHOW_IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')

# web_slideshow_playlist = 2: a shared iCloud album (Config.slideshow_icloud_album).
# Apple has no public Photos API, but an album shared with "Public Website"
# enabled is served by these two undocumented endpoints, with no Apple ID or
# credentials involved. Undocumented means Apple can change it without notice,
# so every failure here leaves whatever is already cached on screen.
ICLOUD_DEFAULT_HOST = 'https://p123-sharedstreams.icloud.com'
ICLOUD_ASSET_BATCH = 100  # photoGuids per webasseturls request
# Signed asset URLs expire after roughly an hour, so they are requested a batch
# at a time as the download queue drains rather than all up front.


def icloud_album_token(share_url):
    """Pull the album token out of a Photos share URL.

    Accepts the full link ('https://www.icloud.com/sharedalbum/#B0Xabc') or a
    bare token, and returns '' if there is nothing usable.
    """
    token = (share_url or '').strip()
    if '#' in token:
        token = token.split('#', 1)[1]
    token = token.strip().strip('/')
    if not token or not token.replace('-', '').replace('_', '').isalnum():
        return ''
    return token


def icloud_best_derivative(photo):
    """Largest available derivative for a photo, or None if it isn't a usable
    still image (shared albums can also hold videos)."""
    if str(photo.get('mediaAssetType', '')).lower() == 'video':
        return None
    best = None
    for derivative in (photo.get('derivatives') or {}).values():
        try:
            size = int(derivative.get('fileSize', 0))
        except (TypeError, ValueError):
            continue
        if not derivative.get('checksum') or size <= 0:
            continue
        if best is None or size > best[0]:
            best = (size, derivative)
    return best[1] if best else None


def icloud_photo_entries(webstream_data):
    """Flatten a webstream response into [{guid, checksum, cachename}], newest
    first so the most recent photos are downloaded and shown soonest."""
    photos = []
    for photo in webstream_data.get('photos') or []:
        derivative = icloud_best_derivative(photo)
        guid = photo.get('photoGuid')
        if not derivative or not guid:
            continue
        photos.append({
            'guid': guid,
            'checksum': derivative['checksum'],
            'sortkey': photo.get('dateCreated') or photo.get('batchDateCreated') or '',
            # Keyed on guid+checksum, which are stable, unlike the signed and
            # frequently rotating asset URLs.
            'cachename': 'icloud_%s.img' % hashlib.sha1(
                ('%s/%s' % (guid, derivative['checksum'])).encode('utf-8')).hexdigest(),
        })
    photos.sort(key=lambda p: p['sortkey'], reverse=True)
    return photos


# With more than one alert active, each stays up until its own ticker has run
# once, so a long headline is never cut off. The ticker reports when it has
# cleared the left edge rather than the delay being calculated up front, which
# keeps the swap in step with what is actually on screen.
ALERT_CYCLE_PAD_MS = 600  # beat between the text clearing and the next alert
ALERT_CYCLE_MAX_MS = 40000  # safety cap, so one huge headline can't stall the rest
FLIGHT_DWELL_MS = 6000  # how long each aircraft stays up when several are overhead
TICKER_PX_PER_TICK = 2  # ticker scroll speed
TICKER_TICK_MS = 30
TICKER_GAP_PX = 80  # blank gap after the text leaves before it re-enters


class _Ticker(QtWidgets.QWidget):
    """A single line of text that runs right-to-left like a news ticker.

    It always scrolls, entering from the right edge and looping once it has
    left on the left, so a short line behaves the same as a long one instead
    of sitting still and left-aligned.
    """

    # Emitted once per pass, the moment the text has cleared the left edge.
    finished = QtCore.pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._label = QtWidgets.QLabel(self)
        self._label.setStyleSheet('background: transparent;')
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._x = 0
        self._announced = False

        self._timer = QtCore.QTimer(self)
        self._timer.timeout.connect(self._advance)
        self._timer.start(TICKER_TICK_MS)

    def set_text(self, text, stylesheet):
        self._label.setStyleSheet('background: transparent; ' + stylesheet)
        self._label.setText(text)
        self._label.adjustSize()
        self._label.setFixedHeight(max(self.height(), self._label.sizeHint().height()))
        self._reset_offscreen()

    def _reset_offscreen(self):
        """Park the text just past the right edge, ready to scroll in."""
        self._x = self.width()
        self._announced = False
        self._label.move(self._x, 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._label.text():
            self._label.setFixedHeight(max(self.height(), self._label.sizeHint().height()))

    def _advance(self):
        if not self.isVisible() or not self._label.text():
            return
        self._x -= TICKER_PX_PER_TICK
        if self._x < -(self._label.width() + TICKER_GAP_PX):
            self._reset_offscreen()
            return
        self._label.move(self._x, 0)
        # Tail has passed the left edge: the line has been shown in full.
        if not self._announced and self._x + self._label.width() <= 0:
            self._announced = True
            self.finished.emit()


class _StaticLine(QtWidgets.QLabel):
    """Sub-line that simply sits there. Same set_text() interface as _Ticker,
    for bubbles whose text is short enough to read at a glance."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_text(self, text, stylesheet):
        self.setStyleSheet('background: transparent; ' + stylesheet)
        self.setText(text)


class _EventSink(QtWidgets.QFrame):
    """A plain QFrame that swallows mouse presses so taps inside it don't
    propagate up to (and dismiss) an ancestor overlay."""

    def mousePressEvent(self, event):
        pass


class InfoBubble(QtWidgets.QFrame):
    """Rounded translucent bar with a bold title line and a scrolling sub-line.

    Fades in when it has something to say and out when it does not, and rotates
    through its items one at a time, each staying up until its ticker has run
    once. Subclasses supply the colours and fill in format_item().
    """

    # Subclasses may make the sub-line static and set a fixed dwell instead of
    # letting the ticker's own run decide when to move on.
    SCROLL_SUBLINE = True
    DWELL_MS = None

    def __init__(self, parent, rect, name, background, ticker_color):
        QtWidgets.QFrame.__init__(self, parent)
        self.setObjectName(name)
        self.setGeometry(rect)
        self.setStyleSheet(
            '#%s { background-color: %s; border-radius: %dpx; }'
            % (name, background, int(rect.height() / 3.2)))

        pad_x = int(rect.width() * 0.05)
        title_style = (
            'color: #FFFFFF; font-family:"Open Sans"; font-weight: bold; '
            'font-size: ' + str(int(21 * xscale * Config.fontmult)) + 'px; ' + Config.fontattr)
        self._ticker_style = (
            'color: %s; font-family:"Open Sans"; ' % ticker_color +
            'font-size: ' + str(int(15 * xscale * Config.fontmult)) + 'px; ' + Config.fontattr)

        self.title_label = QtWidgets.QLabel(self)
        self.title_label.setGeometry(pad_x, int(rect.height() * 0.05),
                                      rect.width() - pad_x * 2, int(rect.height() * 0.55))
        self.title_label.setWordWrap(True)
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setStyleSheet('background: transparent; ' + title_style)
        self.title_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self.ticker = _Ticker(self) if self.SCROLL_SUBLINE else _StaticLine(self)
        self.ticker.setGeometry(pad_x, int(rect.height() * 0.62),
                                 rect.width() - pad_x * 2, int(rect.height() * 0.32))

        self._opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity_effect)
        self.hide()

        self.items = []
        self.index = 0
        self._anim = None
        self._shown = False
        self._suppressed = False

        # Driven by the ticker finishing rather than a fixed interval, so an
        # item is never swapped out mid-sentence or left replaying.
        self.cycle_timer = QtCore.QTimer()
        self.cycle_timer.setSingleShot(True)
        self.cycle_timer.timeout.connect(self._cycle)
        if self.SCROLL_SUBLINE:
            self.ticker.finished.connect(self._ticker_finished)

    # -- content -------------------------------------------------------------

    def format_item(self, item, position, total):
        """Return (title, ticker_text) for one item. Implemented per subclass."""
        raise NotImplementedError

    def item_key(self, item):
        """Stable identity for an item, so a refresh can carry on from where it
        was rather than jumping back to the start. None restarts the rotation."""
        return None

    def set_items(self, items):
        """Replace the list, disturbing what is on screen as little as possible.

        A refresh is not a reason to change what the viewer is reading. If the
        item on screen is still in the new list it keeps its place and its
        remaining time, and only its text is refreshed. If it has gone, the
        rotation carries on from the same position rather than snapping back
        to the start.
        """
        showing = None
        was_at = self.index
        if self.items and self.index < len(self.items):
            showing = self.item_key(self.items[self.index])

        self.items = items
        if not items:
            self.index = 0
            self.cycle_timer.stop()
            self._update_visibility()
            return

        still_here = None
        if showing is not None:
            for i, item in enumerate(items):
                if self.item_key(item) == showing:
                    still_here = i
                    break

        if still_here is not None:
            # Same item: update the wording in place and let its dwell run out
            # on the original schedule.
            self.index = still_here
            self._render()
            if not self.cycle_timer.isActive():
                self._arm_cycle()
        else:
            # It has gone. Carry on from where the rotation had reached.
            self.index = min(was_at, len(items) - 1)
            self.cycle_timer.stop()
            self._show_current()
        self._update_visibility()

    def set_suppressed(self, suppressed):
        """Hide despite having items, so a more important bubble can use the
        same spot."""
        suppressed = bool(suppressed)
        if suppressed != self._suppressed:
            self._suppressed = suppressed
            self._update_visibility()

    def _update_visibility(self):
        want = bool(self.items) and not self._suppressed
        if want != self._shown:
            self._shown = want
            self._fade(1.0 if want else 0.0)

    def _cycle(self):
        if len(self.items) > 1:
            self.index = (self.index + 1) % len(self.items)
            self._show_current()

    def _render(self):
        """Put the current item on screen without touching its dwell."""
        title, ticker_text = self.format_item(
            self.items[self.index], self.index + 1, len(self.items))
        self.title_label.setText(title)
        self.ticker.set_text(ticker_text, self._ticker_style)

    def _arm_cycle(self):
        if len(self.items) > 1:
            if self.DWELL_MS:
                self.cycle_timer.start(self.DWELL_MS)
            else:
                # Backstop only: normally _ticker_finished() gets there first.
                self.cycle_timer.start(ALERT_CYCLE_MAX_MS)

    def _show_current(self):
        self._render()
        self._arm_cycle()

    def _ticker_finished(self):
        """The line has run in full, so move on after a short beat. Restarting
        the timer here pre-empts the backstop armed in _show_current()."""
        if len(self.items) > 1:
            self.cycle_timer.start(ALERT_CYCLE_PAD_MS)

    # -- presentation --------------------------------------------------------

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


class AlertBubble(InfoBubble):
    """Red warning bar for active NOAA/NWS severe weather alerts (see
    get_noaa_alerts()). Tap it for the full alert text."""

    def __init__(self, parent, rect, detail_panel):
        InfoBubble.__init__(self, parent, rect, 'alertBubble',
                            'rgba(190, 20, 20, 195)', '#FFE2E2')
        self.detail_panel = detail_panel
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    @property
    def alerts(self):
        return self.items

    def set_alerts(self, alerts):
        self.set_items(alerts)

    def format_item(self, alert, position, total):
        title = alert['event'].upper()
        if alert.get('expires'):
            title += '  ·  until {0:%-I:%M %p}'.format(alert['expires'])
        if total > 1:
            title += '  ({0}/{1})'.format(position, total)
        bits = [b for b in (alert.get('area'), alert.get('headline')) if b]
        return title, '   •   '.join(bits)

    def mousePressEvent(self, event):
        if self.items:
            self.detail_panel.show_alert(self.items, self.index)


class FlightBubble(InfoBubble):
    """Bar naming an aircraft passing overhead, with how far away, which way to
    look, how high and how fast. Shares the alert bar's spot and gives way to
    it (see update_bubble_priority()).

    Deliberately quieter than the alert bar: the line is short enough to read
    at a glance so it does not scroll, and the background is lighter, since
    this is a curiosity rather than something demanding attention.
    """

    SCROLL_SUBLINE = False
    DWELL_MS = FLIGHT_DWELL_MS

    def __init__(self, parent, rect):
        InfoBubble.__init__(self, parent, rect, 'flightBubble',
                            'rgba(18, 46, 92, 120)', '#D8E6FF')

    def item_key(self, craft):
        """The ICAO24 address is the aircraft's permanent id, so the bubble can
        stay with the same plane as it moves between refreshes."""
        return craft.get('icao') or craft.get('callsign')

    def format_item(self, craft, position, total):
        callsign = craft['callsign'] or craft['registration'] or 'Aircraft'
        airline = ICAO_AIRLINES.get(callsign[:3].upper())
        title = '%s %s' % (airline, callsign[3:].strip()) if airline else callsign
        if total > 1:
            title += '  ({0}/{1})'.format(position, total)

        # Distance, altitude and speed follow Config.metric like the rest of
        # the clock; the feed itself reports nautical miles, feet and knots.
        if Config.metric:
            dist = '%.0f km' % nm2km(craft['distance_nm'])
            alt = '{:,.0f} m'.format(craft['altitude_ft'] * 0.3048)
            speed_unit, speed_conv = 'km/h', nm2km
        else:
            dist = '%.0f mi' % nm2miles(craft['distance_nm'])
            alt = '{:,.0f} ft'.format(craft['altitude_ft'])
            speed_unit, speed_conv = 'mph', nm2miles

        bits = []
        if craft['bearing_deg'] is not None:
            compass = bearing(float(craft['bearing_deg']))
            bits.append('%s to the %s %s'
                        % (dist, compass, COMPASS_ARROWS.get(compass, '')))
        else:
            bits.append('%s away' % dist)
        bits.append(alt)
        if craft['speed_kt'] is not None:
            try:
                bits.append('%.0f %s' % (speed_conv(float(craft['speed_kt'])), speed_unit))
            except (TypeError, ValueError):
                pass
        bits.append('%.0f%s up' % (craft['elevation_deg'], chr(176)))
        if craft['kind']:
            bits.append(craft['kind'].title())
        return title, '   •   '.join(bits)


class AlertDetailPanel(QtWidgets.QFrame):
    """Full-screen scrim with a centered card showing the complete text of a
    NOAA/NWS alert (opened by tapping an AlertBubble). Tapping the scrim, or
    the close button, dismisses it; prev/next browse other active alerts."""

    def __init__(self, parent, screen_width, screen_height):
        super().__init__(parent)
        self.setObjectName('alertDetailScrim')
        self.setGeometry(0, 0, screen_width, screen_height)
        self.setStyleSheet('#alertDetailScrim { background-color: rgba(0, 0, 0, 165); }')
        self.hide()

        card_w = int(screen_width * 0.62)
        card_h = int(screen_height * 0.72)
        card_x = int((screen_width - card_w) / 2)
        card_y = int((screen_height - card_h) / 2)
        pad = int(card_w * 0.045)

        self.card = _EventSink(self)
        self.card.setObjectName('alertDetailCard')
        self.card.setGeometry(card_x, card_y, card_w, card_h)
        self.card.setStyleSheet(
            '#alertDetailCard { background-color: rgba(32, 32, 32, 240); '
            'border: 2px solid rgba(190, 20, 20, 255); border-radius: ' +
            str(int(card_w * 0.02)) + 'px; }')

        self.title_label = QtWidgets.QLabel(self.card)
        self.title_label.setGeometry(pad, pad, card_w - pad * 2 - 60, int(card_h * 0.11))
        self.title_label.setWordWrap(True)
        self.title_label.setStyleSheet(
            'background: transparent; color: #FF6B6B; font-family:"Open Sans"; '
            'font-weight: bold; font-size: ' + str(int(26 * xscale)) + 'px;')

        self.close_button = QtWidgets.QPushButton('✕', self.card)
        self.close_button.setGeometry(card_w - pad - 46, pad, 46, 46)
        self.close_button.setStyleSheet(
            'QPushButton { background-color: rgba(255,255,255,30); color: #FFFFFF; '
            'border: none; border-radius: 23px; font-size: 18px; } '
            'QPushButton:pressed { background-color: rgba(255,255,255,70); }')
        self.close_button.clicked.connect(self.hide)

        meta_y = pad + int(card_h * 0.12)
        self.meta_label = QtWidgets.QLabel(self.card)
        self.meta_label.setGeometry(pad, meta_y, card_w - pad * 2, int(card_h * 0.14))
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet(
            'background: transparent; color: #CCCCCC; font-family:"Open Sans"; '
            'font-size: ' + str(int(15 * xscale)) + 'px;')

        nav_h = int(card_h * 0.08)
        body_y = meta_y + int(card_h * 0.15)
        body_h = card_h - body_y - nav_h - pad
        self.text_edit = QtWidgets.QTextEdit(self.card)
        self.text_edit.setGeometry(pad, body_y, card_w - pad * 2, body_h)
        self.text_edit.setReadOnly(True)
        self.text_edit.setStyleSheet(
            'QTextEdit { background-color: rgba(255,255,255,15); color: #FFFFFF; '
            'border: none; border-radius: 10px; padding: 10px; '
            'font-family:"Open Sans"; font-size: ' + str(int(15 * xscale)) + 'px; }')

        nav_y = card_h - pad - nav_h + int(nav_h * 0.1)
        self.nav_prev = QtWidgets.QPushButton('‹', self.card)
        self.nav_next = QtWidgets.QPushButton('›', self.card)
        self.nav_prev.setGeometry(pad, nav_y, 50, nav_h)
        self.nav_next.setGeometry(card_w - pad - 50, nav_y, 50, nav_h)
        for btn in (self.nav_prev, self.nav_next):
            btn.setStyleSheet(
                'QPushButton { background-color: rgba(255,255,255,25); color: #FFFFFF; '
                'border: none; border-radius: 8px; font-size: 22px; font-weight: bold; } '
                'QPushButton:pressed { background-color: rgba(255,255,255,65); }')
        self.nav_prev.clicked.connect(lambda: self._navigate(-1))
        self.nav_next.clicked.connect(lambda: self._navigate(1))

        self.page_label = QtWidgets.QLabel(self.card)
        self.page_label.setGeometry(pad + 60, nav_y, card_w - pad * 2 - 120, nav_h)
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setStyleSheet(
            'background: transparent; color: #999999; font-family:"Open Sans"; '
            'font-size: ' + str(int(13 * xscale)) + 'px;')

        self._alerts = []
        self._index = 0

    def show_alert(self, alerts, index):
        self._alerts = alerts
        self._index = index
        self._render()
        self.raise_()
        self.show()

    def _navigate(self, delta):
        if not self._alerts:
            return
        self._index = (self._index + delta) % len(self._alerts)
        self._render()

    def _render(self):
        alert = self._alerts[self._index]
        self.title_label.setText(alert['event'].upper())

        meta_bits = []
        if alert.get('area'):
            meta_bits.append(alert['area'])
        times = []
        if alert.get('effective'):
            times.append('Effective {0:%a %-I:%M %p}'.format(alert['effective']))
        if alert.get('expires'):
            times.append('Until {0:%a %-I:%M %p}'.format(alert['expires']))
        if times:
            meta_bits.append(' | '.join(times))
        badges = [b for b in (alert.get('severity'), alert.get('urgency'), alert.get('certainty')) if b]
        if badges:
            meta_bits.append(' · '.join(badges))
        self.meta_label.setText('\n'.join(meta_bits))

        body_parts = []
        if alert.get('headline'):
            body_parts.append(alert['headline'])
        if alert.get('description'):
            body_parts.append(alert['description'])
        if alert.get('instruction'):
            body_parts.append('WHAT TO DO:\n' + alert['instruction'])
        if alert.get('sender'):
            body_parts.append('Source: ' + alert['sender'])
        self.text_edit.setPlainText('\n\n'.join(body_parts))
        self.text_edit.verticalScrollBar().setValue(0)

        multi = len(self._alerts) > 1
        self.nav_prev.setVisible(multi)
        self.nav_next.setVisible(multi)
        self.page_label.setVisible(multi)
        if multi:
            self.page_label.setText('Alert {0} of {1}'.format(self._index + 1, len(self._alerts)))

    def mousePressEvent(self, event):
        # A tap that reaches here landed on the scrim itself, not the card
        # (whose own _EventSink swallows clicks) - dismiss.
        self.hide()


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

        # iCloud album state (web_slideshow_playlist = 2)
        self.icloud_host = ICLOUD_DEFAULT_HOST
        self.icloud_reply = None
        self.icloud_queue = []  # photos still needing an asset URL + download
        self._icloud_redirected = False

        os.makedirs(SLIDESHOW_LOCAL_DIR, exist_ok=True)
        os.makedirs(SLIDESHOW_CACHE_DIR, exist_ok=True)
        if Config.web_slideshow_playlist != 2:
            # URL-keyed cache entries can go stale silently, so mode 1 starts
            # clean each launch. iCloud entries are keyed on stable photo IDs,
            # so that cache is kept and only synced against the album.
            self._clear_cache_dir()

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

        if Config.web_slideshow_playlist == 2:
            # Show whatever survived from last run straight away, so a restart
            # (or a boot with no network yet) isn't a blank screen.
            self.load_cached_images()
            self.refresh_icloud_album()
            self.playlist_timer = QtCore.QTimer()
            self.playlist_timer.timeout.connect(self.refresh_icloud_album)
            self.playlist_timer.start(int(1000 * SLIDESHOW_PLAYLIST_REFRESH_SEC))
        elif Config.web_slideshow_playlist:
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
        # Read through QImageReader with autoTransform so EXIF orientation is
        # applied; QImage(path) ignores it, which lands portrait phone photos
        # on their side.
        reader = QtGui.QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            print(f"ERROR: Unable to load slideshow image: {path}: {reader.errorString()}")
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
            try:
                with open(dest, 'wb') as f:
                    f.write(bytes(reply.readAll()))
            except OSError as e:
                print(f"ERROR: Unable to save slideshow image {dest}: {e}")
                self._download_next_pending()
                return
            # Slot each new image in at random rather than appending: photos
            # are fetched in a deliberate order (newest first for iCloud), so
            # appending would play the whole album back in that same order.
            self.img_list.insert(random.randint(0, len(self.img_list)), dest)
            if len(self.img_list) == 1:
                self.switch_image()
        if self.pending_downloads:
            self._download_next_pending()
        else:
            # Batch drained; ask iCloud for the next set of asset URLs (no-op
            # in the other slideshow modes).
            self._icloud_request_asset_urls()

    # --- shared iCloud album (web_slideshow_playlist = 2) ---

    def load_cached_images(self):
        """Show images already in the cache from a previous run."""
        try:
            files = [os.path.join(SLIDESHOW_CACHE_DIR, f)
                     for f in os.listdir(SLIDESHOW_CACHE_DIR)]
        except OSError as e:
            print(f"ERROR: Unable to read {SLIDESHOW_CACHE_DIR}: {e}")
            return
        if not files:
            return
        random.shuffle(files)
        self.img_list = files
        self.count = 0
        print(f"SLIDESHOW: {len(files)} image(s) already cached")
        self.switch_image()

    def _icloud_post(self, path, payload, on_finished):
        global manager
        token = icloud_album_token(Config.slideshow_icloud_album)
        if not token:
            print('ERROR: slideshow_icloud_album is not a usable iCloud share link')
            return
        url = f'{self.icloud_host}/{token}/sharedstreams/{path}'
        request = QNetworkRequest(QUrl(url))
        request.setHeader(QNetworkRequest.KnownHeaders.ContentTypeHeader, 'application/json')
        self.icloud_reply = manager.post(request, json.dumps(payload).encode('utf-8'))
        self.icloud_reply.finished.connect(on_finished)

    def refresh_icloud_album(self):
        """Fetch the album's photo list (step 1 of 2)."""
        self._icloud_redirected = False
        print('SLIDESHOW: checking shared iCloud album')
        self._icloud_post('webstream', {'streamCtag': None}, self._webstream_finished)

    def _webstream_finished(self):
        reply = self.icloud_reply
        reply.deleteLater()

        # Apple answers from a per-album partition host and redirects if the
        # first guess was wrong. Qt won't follow this itself: it's a non-standard
        # 330 on a POST.
        redirect = bytes(reply.rawHeader(b'X-Apple-MMe-Host')).decode('utf-8', 'replace')
        if redirect and not self._icloud_redirected:
            self._icloud_redirected = True
            self.icloud_host = 'https://' + redirect
            print(f'SLIDESHOW: iCloud redirected to {redirect}')
            self._icloud_post('webstream', {'streamCtag': None}, self._webstream_finished)
            return

        if reply.error() != QNetworkReply.NetworkError.NoError:
            print(f'ERROR: shared iCloud album request failed: {reply.errorString()}')
            return
        try:
            data = json.loads(str(bytes(reply.readAll()), 'utf-8'))
        except ValueError:
            print('WARNING:', traceback.format_exc())
            print('WARNING: could not parse the shared iCloud album response')
            return

        photos = icloud_photo_entries(data)
        if not photos:
            print('WARNING: shared iCloud album returned no usable photos')
            return

        wanted = {p['cachename']: p for p in photos}
        for existing in os.listdir(SLIDESHOW_CACHE_DIR):
            if existing not in wanted:
                try:
                    os.remove(os.path.join(SLIDESHOW_CACHE_DIR, existing))
                except OSError:
                    pass

        cached, missing = [], []
        for photo in photos:
            dest = os.path.join(SLIDESHOW_CACHE_DIR, photo['cachename'])
            if os.path.exists(dest):
                cached.append(dest)
            else:
                photo['dest'] = dest
                missing.append(photo)

        random.shuffle(cached)
        self.img_list = cached
        self.count = 0
        if cached:
            self.switch_image()

        self.icloud_queue = missing
        print(f'SLIDESHOW: iCloud album has {len(photos)} photo(s); '
              f'{len(cached)} cached, {len(missing)} to download')
        self._icloud_request_asset_urls()

    def _icloud_request_asset_urls(self):
        """Swap the next batch of photo IDs for signed URLs (step 2 of 2)."""
        if not self.icloud_queue:
            return
        batch = self.icloud_queue[:ICLOUD_ASSET_BATCH]
        self._icloud_post('webasseturls',
                          {'photoGuids': [p['guid'] for p in batch]},
                          lambda: self._asseturls_finished(batch))

    def _asseturls_finished(self, batch):
        reply = self.icloud_reply
        reply.deleteLater()
        self.icloud_queue = self.icloud_queue[len(batch):]

        if reply.error() != QNetworkReply.NetworkError.NoError:
            print(f'ERROR: could not get iCloud asset URLs: {reply.errorString()}')
            return
        try:
            items = json.loads(str(bytes(reply.readAll()), 'utf-8')).get('items') or {}
        except ValueError:
            print('WARNING:', traceback.format_exc())
            print('WARNING: could not parse the iCloud asset URL response')
            return

        for photo in batch:
            item = items.get(photo['checksum'])
            if not item or not item.get('url_location') or not item.get('url_path'):
                continue
            self.pending_downloads.append(
                ('https://' + item['url_location'] + item['url_path'], photo['dest']))

        if self.pending_downloads:
            print(f"SLIDESHOW: downloading {len(self.pending_downloads)} new image(s) from iCloud")
            self._download_next_pending()
        else:
            self._icloud_request_asset_urls()

    def play_pause(self):
        self.pause = not self.pause

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
    """Fetch RainViewer metadata once globally, shared by all radar instances."""
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
    """Process the RainViewer metadata response."""
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

        self.wantoverlay = bool(usemapbox and radar.get('overlay'))
        if self.wantoverlay:
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

        # The base map and overlay are fetched once at startup. On a Pi that
        # boots before the network is up that single attempt fails and the
        # radar would sit on a blank background until the next restart, so
        # keep retrying until each one lands.
        self.basegood = False
        self.overlaygood = False
        self.maptimer = None

    def maps_pending(self):
        return (not self.basegood) or (self.wantoverlay and not self.overlaygood)

    def schedule_map_retry(self):
        """Run a retry timer while either map is still missing, and stop it
        once they have both arrived."""
        if not self.maps_pending():
            if self.maptimer is not None:
                self.maptimer.stop()
                self.maptimer = None
                print(f'INFO: {self.myname} maps loaded, no more retries needed')
            return
        if self.maptimer is None:
            self.maptimer = QtCore.QTimer()
            self.maptimer.timeout.connect(self.retry_maps)
            self.maptimer.start(MAP_RETRY_MS)

    def retry_maps(self):
        if not self.basegood:
            print(f'INFO: {self.myname} retrying base map')
            self.getbase()
        if self.wantoverlay and not self.overlaygood:
            print(f'INFO: {self.myname} retrying map overlay')
            self.getoverlay()

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
            if any(f['time'] == tt for f in self.frameImages):
                continue  # already have this frame
            print(f'INFO: {self.myname} fetching radar tiles for time {tt} '
                  f'({datetime.datetime.fromtimestamp(tt).astimezone(tzlocal.get_localzone())})')
            # Tiles arrive asynchronously, so stop after queueing one frame;
            # get_tilesreply() calls back here for the next one. A frame with
            # no data available returns False, so just try the next timestamp.
            if self.get_tiles(tt):
                break

    def get_tiles(self, t, i=0):
        """Build tile URLs from metadata and fetch them.

        Returns True if tiles were queued, False if no data exists for this time.
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
        """Find the metadata radar path closest to the requested timestamp.

        RainViewer publishes frames on a 10-minute grid, so an exact match is
        not guaranteed; anything within 5 minutes is accepted.
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
        """Process the radar tile response."""
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
        """Combine the fetched radar tiles into one image, plus a timestamp layer."""
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
                self.schedule_map_retry()
                return
            api_cache_write(self.basereply.url().toString(), data)
        basepixmap = QPixmap()
        if not basepixmap.loadFromData(data):
            print(f'ERROR: {self.myname} could not decode the base map image')
            self.schedule_map_retry()
            return
        self.basegood = True
        self.schedule_map_retry()
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
                self.schedule_map_retry()
                return
            api_cache_write(self.overlayreply.url().toString(), data)
        overlaypixmap = QPixmap()
        if not overlaypixmap.loadFromData(data):
            print(f'ERROR: {self.myname} could not decode the map overlay image')
            self.schedule_map_retry()
            return
        self.overlaygood = True
        self.schedule_map_retry()
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
        """Start the radar display, with an optional refresh interval override."""
        if interval > 0:
            self.interval = interval
        self.getbase()

        if self.wantoverlay:
            self.getoverlay()
        self.schedule_map_retry()

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.rtick)
        self.lastget = time.time() - self.interval + random.uniform(3, 10)

    def wxstart(self):
        print('INFO: wxstart for ' + self.myname)
        self.timer.start(self.TICK_MS)

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
        if self.maptimer is not None:
            self.maptimer.stop()
            self.maptimer = None


def realquit():
    QtWidgets.QApplication.exit(0)


def myquit(signum, frame):
    global objradar1, objradar2, objradar3, objradar4
    global ctimer, wxtimer, temptimer, cursortimer, alerttimer, flighttimer

    objradar1.stop()
    objradar2.stop()
    objradar3.stop()
    objradar4.stop()
    ctimer.stop()
    wxtimer.stop()
    temptimer.stop()
    cursortimer.stop()
    alerttimer.stop()
    if Config.flights_enabled and flighttimer is not None:
        flighttimer.stop()
    if Config.useslideshow:
        objimage1.stop()
    release_display_sleep()

    QtCore.QTimer.singleShot(30, realquit)


def fixupframe(frame, onoff):
    """Animate a page's radars only while that page is visible."""
    for child in frame.children():
        if isinstance(child, Radar):
            if onoff:
                child.wxstart()
            else:
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
            if event.key() == Qt.Key.Key_Escape:
                if alertDetailPanel.isVisible():
                    alertDetailPanel.hide()

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
    Config.brightness_enabled
except AttributeError:
    Config.brightness_enabled = 0
    Config.day_brightness = 100
    Config.night_brightness = 100
    Config.day_start = '07:00'
    Config.night_start = '22:00'
    Config.brightness_transition_minutes = 30

try:
    Config.prevent_screen_sleep
except AttributeError:
    Config.prevent_screen_sleep = 1

# Off unless a config asks for it, so existing installs are unchanged and
# nobody starts polling a third-party feed without opting in.
try:
    Config.flights_enabled
except AttributeError:
    Config.flights_enabled = 0

try:
    Config.flight_poll_seconds
except AttributeError:
    Config.flight_poll_seconds = 30

try:
    Config.flight_min_elevation
except AttributeError:
    Config.flight_min_elevation = 30  # degrees above the horizon

try:
    Config.flight_search_radius_nm
except AttributeError:
    Config.flight_search_radius_nm = 50

try:
    Config.web_slideshow_playlist
except AttributeError:
    # 0 = local images from Pictures/Slideshow, 1 = Config.slideshow_url,
    # 2 = Config.slideshow_icloud_album
    Config.web_slideshow_playlist = 0

try:
    Config.slideshow_icloud_album
except AttributeError:
    Config.slideshow_icloud_album = ''  # shared iCloud album link, used when web_slideshow_playlist = 2

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

# Layout defaults are the original ones, so an existing Config.py that predates
# these settings looks exactly as it did. Config-Example.py ships the newer
# 'photo' layout for fresh installs.
try:
    Config.layout
except AttributeError:
    Config.layout = 'classic'  # 'photo' puts the clock on top; see Config-Example.py

try:
    Config.scrim_opacity
except AttributeError:
    Config.scrim_opacity = 0  # 0-255 darkness of the gradients behind text; 0 disables them

try:
    Config.datesize
except AttributeError:
    Config.datesize = 50  # day/date font size

try:
    Config.footersize
except AttributeError:
    Config.footersize = 24  # sun rise/set and moon phase font size

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
last_brightness_percent = -1
flighttimer = None
sleep_inhibit_process = None
keepalive_timer = None

# Pressure trend tracking: samples are recorded every time fresh weather data
# arrives, but the displayed arrow only refreshes once an hour (see
# pressuretrendtimer in qtstart()), based on the change over the last 2 hours.
PRESSURE_TREND_WINDOW_SEC = 2 * 60 * 60
PRESSURE_TREND_DEADBAND_INHG = 0.02  # ~0.68 hPa; ignore noise below this over the window
# The arrow is drawn larger than the pressure text next to it, so which way
# the pressure is going reads at a glance from across the room.
PRESSURE_ARROW_SCALE = 1.7
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
signal.signal(signal.SIGTERM, myquit)


def add_text_shadow(widget):
    """Give a label a soft black drop shadow, so light text stays readable
    against a bright slideshow image. A widget holds only one graphics
    effect, so this replaces any previously set effect."""
    shadow = QtWidgets.QGraphicsDropShadowEffect(widget)
    shadow.setColor(QtGui.QColor(0, 0, 0))
    shadow.setBlurRadius(10)
    shadow.setOffset(2, 2)
    widget.setGraphicsEffect(shadow)


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

# Full-screen dimming overlay for the day/night brightness schedule; a direct
# child of w (rather than frame1/frame2) so it stays on top no matter which
# page is showing. Its alpha is updated from tick() via apply_brightness().
brightness_overlay = QtWidgets.QFrame(w)
brightness_overlay.setObjectName('brightness_overlay')
brightness_overlay.setGeometry(0, 0, width, height)
brightness_overlay.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
brightness_overlay.setStyleSheet('#brightness_overlay { background-color: rgba(0, 0, 0, 0); }')
brightness_overlay.raise_()

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
add_text_shadow(clockface)

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
                    str(int(Config.datesize * xscale * Config.fontmult)) +
                    'px; ' +
                    Config.fontattr +
                    '}')
datex.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
datex.setGeometry(0, mac_notch_inset, width, int(100 * yscale))

add_text_shadow(datex)


datex2 = QtWidgets.QLabel(frame2)
datex2.setObjectName('datex2')
datex2.setStyleSheet('#datex2 { font-family:"Open Sans"; color: ' +
                     Config.textcolor +
                     '; background-color: transparent; font-size: ' +
                     str(int(Config.datesize * xscale * Config.fontmult)) + 'px; ' +
                     Config.fontattr +
                     '}')
datex2.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
datex2.setGeometry(int(800 * xscale), int(760 * yscale), int(640 * xscale), 100)

add_text_shadow(datex2)


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

add_text_shadow(datey2)


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

add_text_shadow(wxdesc)


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

add_text_shadow(wxdesc2)

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

add_text_shadow(temper)


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

add_text_shadow(temper2)


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

add_text_shadow(feelslike)


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

add_text_shadow(humidity)


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

add_text_shadow(press)

# The trend arrow lives in its own label so its larger glyph cannot disturb the
# pressure reading's position. show_pressure() places it on each update.
pressarrow = QtWidgets.QLabel(foreGround)
pressarrow.setObjectName('pressarrow')
pressarrow.setStyleSheet('#pressarrow { background-color: transparent; color: ' +
                         Config.textcolor +
                         '; font-size: ' +
                         str(int(17 * xscale * Config.fontmult * PRESSURE_ARROW_SCALE)) +
                         'px; ' +
                         Config.fontattr +
                         '}')
pressarrow.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
pressarrow.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
pressarrow.hide()
add_text_shadow(pressarrow)


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

add_text_shadow(wind)


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

add_text_shadow(wdate)


bottom = QtWidgets.QLabel(foreGround)
bottom.setObjectName('bottom')
bottom.setStyleSheet('#bottom { font-family:"Open Sans"; color: ' +
                     Config.textcolor +
                     '; background-color: transparent; font-size: ' +
                     str(int(Config.footersize * xscale * Config.fontmult)) +
                     'px; ' +
                     Config.fontattr +
                     '}')
bottom.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
bottom.setGeometry(0, int(height - 50 * yscale), width, int(50 * yscale))

add_text_shadow(bottom)

# Severe weather warning bubble: below the clock, clear of the inside
# temperature and the sunrise/set footer stacked underneath it. The bubble is
# raised above its siblings so the whole bar stays clickable, which means it
# would paint over anything it overlapped.
# The detail panel is a direct child of w (like brightness_overlay) so it sits
# on top of both frame1/frame2 and is reachable from either page.
alertDetailPanel = AlertDetailPanel(w, width, height)
# Narrow enough to clear the weather block on the left and the forecast column
# on the right; both start ~300 design units in from their edge.
ALERT_X = 0.22
ALERT_W = 0.56
alertrect = QtCore.QRect(
    int(width * ALERT_X),
    int(height - 176 * yscale),
    int(width * ALERT_W),
    int(height * 0.075))
alertBubble = AlertBubble(foreGround, alertrect, alertDetailPanel)
# Same slot as the alert bar; update_bubble_priority() keeps them from clashing.
flightBubble = FlightBubble(foreGround, alertrect)


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
# Full-width and usually empty (it only fills in when the optional temperature
# server is running), so without this it silently swallows every click along
# the bottom of the screen.
temp.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

add_text_shadow(temp)


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

    add_text_shadow(lab)

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

    add_text_shadow(wx)

    day = QtWidgets.QLabel(lab)
    day.setStyleSheet('#day { background-color: transparent; }')
    day.setGeometry(int(100 * xscale), int(75 * yscale), int(200 * xscale), int(25 * yscale))
    day.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignBottom)
    day.setObjectName('day')

    add_text_shadow(day)

    forecast.append(lab)

# The alert bar is the only clickable thing on this page, so it has to sit
# above the display-only labels created after it - otherwise they win
# hit-testing and only the part of the bar they don't cover responds to taps.
alertBubble.raise_()
flightBubble.raise_()


def add_scrim(x, y, w_, h_, gradient):
    """Gradient panel drawn under the text, fading out toward the middle of the
    screen. Keeps light text readable over a bright background without hiding
    that part of the image behind a solid block."""
    panel = QtWidgets.QFrame(foreGround)
    panel.setGeometry(int(x), int(y), int(w_), int(h_))
    panel.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    panel.setStyleSheet('background: ' + gradient + ';')
    panel.lower()  # behind every other foreGround child, above the background
    return panel


def add_scrims():
    """Darken the edges where text lives: the left weather block, the right
    forecast column, and a bottom band. The classic layout also gets a top
    band, for the day/date it runs across the top."""
    o = max(0, min(255, int(Config.scrim_opacity)))
    if o == 0:
        return
    add_scrim(0, 0, width * 0.32, height,
              'qlineargradient(x1:0, y1:0, x2:1, y2:0,'
              ' stop:0 rgba(0,0,0,%d), stop:0.65 rgba(0,0,0,%d), stop:1 rgba(0,0,0,0))'
              % (o, int(o * 0.59)))
    add_scrim(width * 0.70, 0, width * 0.30, height,
              'qlineargradient(x1:0, y1:0, x2:1, y2:0,'
              ' stop:0 rgba(0,0,0,0), stop:0.35 rgba(0,0,0,%d), stop:1 rgba(0,0,0,%d))'
              % (int(o * 0.59), o))
    # Only classic needs a top band, since it runs the day/date across the top.
    # In 'photo' the top holds only the alert (opaque on its own) and the side
    # columns, which the left/right scrims already cover.
    if Config.layout != 'photo':
        add_scrim(0, 0, width, height * 0.23,
                  'qlineargradient(x1:0, y1:0, x2:0, y2:1,'
                  ' stop:0 rgba(0,0,0,%d), stop:1 rgba(0,0,0,0))' % int(o * 0.95))
    # The 'photo' layout stacks time/date/sun-moon along the bottom, so its
    # gradient has to start higher than the classic footer alone needs.
    band_top = 0.68 if Config.layout == 'photo' else 0.76
    add_scrim(0, height * band_top, width, height * (1 - band_top),
              'qlineargradient(x1:0, y1:0, x2:0, y2:1,'
              ' stop:0 rgba(0,0,0,0), stop:0.45 rgba(0,0,0,%d), stop:1 rgba(0,0,0,%d))'
              % (int(o * 0.73), int(o * 0.98)))


# Band heights for the 'photo' layout, in the same 900-unit design space the
# rest of the layout uses (multiplied by yscale at build time). The bottom
# block stacks upward from the footer: sun/moon, day/date, clock, inside temp.
PHOTO_FOOTER_H = 44
PHOTO_DATE_H = 46
PHOTO_CLOCK_H = 100
PHOTO_TEMP_H = 40
PHOTO_GAP = 4
# Both bubbles sit near the very top edge, where the left weather block and
# right forecast column leave a clear run, so they take as little of the
# picture as possible. mac_notch_inset keeps them clear of a MacBook notch.
PHOTO_ALERT_TOP = 0.02
PHOTO_ALERT_H = 0.075


def apply_photo_layout():
    """Rearrange page 1 to keep the background image visible.

    The time, day/date and sun/moon line stack along the bottom with the clock
    as the largest of the three, the inside temperature sits above them, and
    the severe weather alert moves up out of the way. The classic layout
    centres a much larger clock instead.
    """
    footer_top = 900 - PHOTO_FOOTER_H
    date_top = footer_top - PHOTO_GAP - PHOTO_DATE_H
    clock_top = date_top - PHOTO_GAP - PHOTO_CLOCK_H
    temp_top = clock_top - PHOTO_GAP - PHOTO_TEMP_H

    clockface.setGeometry(0, int(clock_top * yscale), width, int(PHOTO_CLOCK_H * yscale))
    clockface.setAlignment(Qt.AlignmentFlag.AlignCenter)

    temp.setStyleSheet(temp.styleSheet().replace(
        'font-size: ' + str(int(30 * xscale * Config.fontmult)) + 'px',
        'font-size: ' + str(int(Config.footersize * xscale * Config.fontmult)) + 'px'))
    temp.setGeometry(0, int(temp_top * yscale), width, int(PHOTO_TEMP_H * yscale))
    temp.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

    # Centred vertically: the <sup> in the date makes the line taller than the
    # font size suggests, and AlignTop clips its descenders.
    datex.setGeometry(0, int(date_top * yscale), width, int(PHOTO_DATE_H * yscale))
    datex.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

    bottom.setGeometry(0, int(footer_top * yscale), width, int(PHOTO_FOOTER_H * yscale))
    bottom.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)

    # Both bubbles share this slot; update_bubble_priority() decides which of
    # them is on screen at any moment.
    for bubble in (alertBubble, flightBubble):
        bubble.setGeometry(int(width * ALERT_X),
                           mac_notch_inset + int(height * PHOTO_ALERT_TOP),
                           int(width * ALERT_W), int(height * PHOTO_ALERT_H))


add_scrims()
if Config.layout == 'photo':
    apply_photo_layout()

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

prevent_display_sleep()

sys.exit(app.exec())
