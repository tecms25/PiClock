# -*- coding: utf-8 -*-
from PyQt6.QtGui import QColor

from GoogleMercatorProjection import LatLng  # NOQA

# LOCATION(S)
# Further radar configuration (zoom, marker location) can be
# completed under the RADAR section
primary_coordinates = 00.0000000, -00.0000000  # Change to your Lat/Lon

# Location for weather report
location = LatLng(primary_coordinates[0], primary_coordinates[1])
# Default radar location
radar_location = LatLng(primary_coordinates[0], primary_coordinates[1])

noaastream = 'https://radio.weatherusa.net/NWR/KEB98.mp3' # Change to local NOAA stream
background = 'images/mesa.jpg' # Only used if 'useslideshow' is set to 0 below
icons = 'icons-lightblue'
textcolor = '#FFFFFF'

cursor_idle_seconds = 3.0 # Seconds of no mouse movement before the cursor is hidden; 0 to disable

# Screen Brightness
# Dims the whole display like a night light using a software overlay, so it
# behaves the same on every OS/monitor without needing hardware backlight
# control. Percentages are 0 (black) to 100 (normal/full brightness).
brightness_enabled = 1  # 1 to enable time-based dimming, 0 to always use day_brightness
day_brightness = 100  # 0-100, brightness percentage during the day
night_brightness = 60  # 0-100, brightness percentage at night
day_start = '07:00'  # 24-hour clock (HH:MM) when day_brightness begins
night_start = '22:00'  # 24-hour clock (HH:MM) when night_brightness begins
brightness_transition_minutes = 30  # minutes to gradually fade between day/night brightness; 0 for an instant switch

# Keep the display awake at all times (best-effort; prevents the OS
# screensaver/sleep/DPMS from blanking the screen). Works on Windows, macOS,
# and Linux (X11 and most Wayland desktop environments).
prevent_screen_sleep = 1  # 1 to enable, 0 to disable

# Aircraft overhead
# Shows a bubble naming a plane passing overhead, in the same spot as the
# severe weather alert. If an alert is active the aircraft bubble stays out of
# the way until the alert has cleared.
# Data comes from airplanes.live, a volunteer-run ADS-B feed. No key needed,
# but it is someone else's bandwidth, so leave this off unless you want it.
flights_enabled = 0  # 1 to enable, 0 to disable
flight_poll_seconds = 30  # how often to look for aircraft
# How high in the sky a plane must be to count, in degrees above the horizon.
# This beats a plain distance: a jet at 35,000ft is genuinely overhead at 10nm
# but an invisible speck at 30nm. Lower this to catch more, raise it for only
# the ones nearly straight up. 30 is a handful at a time.
flight_min_elevation = 30
flight_search_radius_nm = 150  # how far out to ask for aircraft (max 250)

# Blue Iris camera alerts
# When Blue Iris trips an alert it calls PiClock over the LAN and the camera
# goes up on screen for a few seconds, then the clock comes back. Set this up
# in Blue Iris under Camera settings > Alerts > On alert > Web request, using:
#   http://<pi-address>:8127/alert?token=<blueiris_token>&cam=&CAM&memo=&MEMO
# Nothing is polled, so the popup is as quick as Blue Iris' own alert.
blueiris_enabled = 0  # 1 to enable, 0 to disable
blueiris_listen_port = 8127  # port PiClock listens on for Blue Iris
# Shared secret; must match the token= in the web request above. Leave blank to
# accept any request, which is only sensible on a trusted network.
blueiris_token = ''
blueiris_server = ''  # Blue Iris web server, e.g. 'http://192.168.1.10:81'
blueiris_user = ''  # a Blue Iris user allowed to view the cameras
blueiris_password = ''
# Only these cameras pop up, by Blue Iris short name. Empty list means any.
blueiris_cameras = []
# Only pop up when the alert memo mentions one of these. The ONVIF rules on
# Tapo cameras send text like 'People' or 'IsPet', so ['People'] shows a person
# at the door and ignores the cat. Empty list means any alert.
blueiris_triggers = []
blueiris_show_seconds = 60  # how long the camera stays on screen
# How many cameras may be on screen at once, 1 to 6. When more alert together
# the panel divides itself - one camera fills it, two sit side by side, then a
# 2x2 grid, then 2x3. Each keeps its own countdown and drops off on its own.
# Beyond this the oldest picture gives way to the newest alert.
blueiris_max_cameras = 6
# Width Blue Iris scales the stream to before sending it. Lower this if the
# clock stutters while a camera is up; the Pi decodes every frame.
blueiris_stream_width = 1080
# Accept the camera stream's certificate even when it fails validation, for a
# Blue Iris using a self-signed certificate or one whose name does not match
# the address here. This applies to the camera stream only - weather and radar
# go on checking certificates properly. Whatever gets waved through is named in
# the log, so leave this off unless the stream will not connect without it.
blueiris_ignore_ssl_errors = 0
# Sign in through the Blue Iris JSON interface instead of putting the user and
# password on the stream URL. Turn this on when "Use secure session keys and
# login page" is enabled on the Advanced page of Settings/Webserver in Blue
# Iris, because that setting makes Blue Iris refuse user/pw on a URL. Needs
# blueiris_user and blueiris_password set either way.
blueiris_use_session_login = 0
# Optional source address allow-list, e.g. ['192.168.1.10'] for the Blue Iris
# machine. Empty list accepts an alert from anywhere on the network.
blueiris_allow_from = []

# Severe weather warning bubble, from api.weather.gov
noaa_alerts_enabled = 1  # 1 to show a warning bubble for active NOAA/NWS alerts, 0 to disable
alert_refresh = 10  # minutes between severe weather alert checks
# NWS severity levels that trigger the warning bubble; from least to most severe:
# 'Unknown', 'Minor', 'Moderate', 'Severe', 'Extreme'
alert_severities = ('Moderate', 'Severe', 'Extreme')

# SlideShow
useslideshow = 1  # 1 to enable, 0 to disable
slide_time = 300  # in seconds, 3600 per hour
slide_bg_color = '#000'  # https://htmlcolorcodes.com/  black #000
slide_transition_ms = 1000  # crossfade duration between images, in milliseconds; 0 for an instant hard cut
# Web Slideshow Playlist
# 0 = random images from the Pictures/Slideshow folder in this repo
# 1 = images listed (one URL per line) in slideshow_url below; the cache is
#     cleared and everything re-downloaded on every launch, then the list is
#     re-checked every 2 hours and only images new to the list are downloaded
# 2 = photos from a shared iCloud album (slideshow_icloud_album below); the
#     cache is kept between launches and only added/removed photos are synced,
#     re-checked every 2 hours
web_slideshow_playlist = 0
slideshow_url = 'https://example.com/slideshow.txt' # must be text file, one image url per line
# Shared iCloud album, used when web_slideshow_playlist = 2.
# In Photos, create an album, share it, turn on "Public Website", then copy the
# link here. Anything you add to that album from any Apple device shows up on
# the clock at the next refresh.
# NOTE: a public website album is readable by anyone who has the link, so don't
# put anything private in it.
slideshow_icloud_album = ''  # e.g. 'https://www.icloud.com/sharedalbum/#B0Xabc123'

# Digital clock
digitalcolor = '#FFFFFF' #Color of the text
digitalformat = '{0:%-I:%M%p}'  # Format of the digital clock face
digitalsize = 76 # Font Size of Clock ('photo' layout suits roughly 70-85)
digitalformat2 = '{0:%-I:%M:%S %p}'  # Format of the digital time on second screen

# Layout and text legibility
# 'classic' - the original arrangement: a large clock centered on the screen,
#             day/date across the top, sun rise/set along the bottom
# 'photo'   - inside temperature, clock, day/date and sun rise/set stacked
#             along the bottom with the time leading them, and the severe
#             weather alert up near the top. Leaves far more of the background
#             image visible.
layout = 'photo'
# Gradient panels drawn behind the text (left, right, top and bottom edges) so
# light text stays readable over a bright image without hiding it behind a
# solid block. 0-255; 0 turns them off. Applies to both layouts.
scrim_opacity = 205
datesize = 30  # Font size of the day/date
footersize = 20  # Font size of the sun rise/set and moon phase line

# Mapbox map styles, need API key (mbapi in ApiKeys.py)
# If no Mapbox API is set, Google Maps are used
map_base = ''  # blank uses Mapbox's default 'mapbox/satellite-streets-v12'; or your own custom style, see below
map_overlay = ''  # optional custom overlay style (labels/roads/borders only); blank disables the overlay

# For more Mapbox styles, see https://docs.mapbox.com/api/maps/styles/
# To create custom Mapbox styles, sign-in at https://studio.mapbox.com/
# Example: If static map URL is
# https://api.mapbox.com/styles/v1/mapbox/streets-v12/static/-80.2,25.8,10/600x400?access_token=YOUR-ACCESS-TOKEN
# use the portion between '/styles/v1/' and '/static/'
# Standard Mapbox maps will look like 'mapbox/streets-v12'
# User created Mapbox maps will look like 'user-name/map-identifier'

# Localization Variables
metric = 0  # 0 = English, 1 = Metric
radar_refresh = 10  # Radar refresh interval in minutes
weather_refresh = 15  # Current and Forecast WX refresh interval in minutes
wind_degrees = 0 # Wind in 360 degrees instead of cardinal 0 = cardinal, 1 = degrees
pressure_mbar = 0 # Override pressure units in millibars, mbar, instead of inches Mercury, inHg, (0 = inHg, 1 = mbar)

# gives all text additional attributes using PyQT attributes
# example: fontattr = 'font-weight: bold; '
fontattr = 'font-weight: bold;'

# These are to dim the radar images, if needed.
# see and try Config-Example-Bedside.py
dimcolor = QColor('#00000')
dimcolor.setAlpha(0)

# Optional Current conditions replaced with observations from a METAR station
# METAR is worldwide, provided mostly for pilots
# But data can be sparse outside US and Europe
# If you're close to an international airport, you should find something close
# Find the closest METAR station with the following URL
# https://www.aviationweather.gov/metar
# scroll/zoom the map to find your closest station
# or look up the ICAO code here:
# https://airportcodes.aero/name
METAR = ''

# The Python Locale for date/time (locale.setlocale)
#  '' for default Pi Setting
# Locales must be installed in your Pi. To check what is installed:
# locale -a
# to install locales
# sudo dpkg-reconfigure locales
DateLocale = ''

# Language specific wording
LPressure = 'Pressure: '
LHumidity = 'Humidity: '
LWind = 'Wind: '
Lgusting = ' Gusts: '
LFeelslike = 'Feels Like: '
LPrecip1hr = ' Precip 1hr: '
LToday = 'Today: '
LSunRise = 'Sun Rise: '
LSet = ' · Set: '
LMoonPhase = ' · Moon: '
LInsideTemp = 'Inside Temp '
LRain = '· Rain: '
LSnow = '· Snow: '
Lmoon1 = 'New Moon'
Lmoon2 = 'Waxing Crescent'
Lmoon3 = 'First Quarter'
Lmoon4 = 'Waxing Gibbous'
Lmoon5 = 'Full Moon'
Lmoon6 = 'Waning Gibbous'
Lmoon7 = 'Third Quarter'
Lmoon8 = 'Waning Crescent'

# Language specific terms for Tomorrow.io weather conditions
Ltm_code_map = {
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

# RADAR
# By default, radar_location entered will be the
# center and marker of all radar images.
# To update centers/markers, change radar sections
# below the desired lat/lon as:
# -FROM-
# radar_location,
# -TO-
# LatLng(44.9764016,-93.2486732),
radar1 = {
    'center': radar_location,  # the center of your radar block
    'zoom': 7,  # this is a maps zoom factor, bigger = smaller area
    'basemap': map_base,  # Mapbox style for standard map or custom map with land and water only
    'overlay': map_overlay,  # Mapbox style for labels, roads, and borders only
    'color': 4,  # rainviewer radar color scheme:
    # https://www.rainviewer.com/api/color-schemes.html
    'smooth': 1,  # rainviewer radar smoothing
    'snow': 1,  # rainviewer radar show snow as different color
    'markers': (  # google maps markers can be overlaid
        {
            'visible': 1,  # 0 = hide marker, 1 = show marker
            'location': radar_location,
            'color': 'red',
            'size': 'small',
            'image': 'teardrop-home',  # optional image from the markers folder
        },  # dangling comma is on purpose.
    )
}

radar2 = {
    'center': radar_location,
    'zoom': 4,
    'basemap': map_base,
    'overlay': map_overlay,
    'color': 4,
    'smooth': 1,
    'snow': 1,
    'markers': (
        {
            'visible': 1,
            'location': radar_location,
            'color': 'red',
            'size': 'small',
            'image': 'teardrop-home',
        },
    )
}

radar3 = {
    'center': radar_location,
    'zoom': 7,
    'basemap': map_base,
    'overlay': map_overlay,
    'color': 4,
    'smooth': 1,
    'snow': 1,
    'markers': (
        {
            'visible': 1,
            'location': radar_location,
            'color': 'red',
            'size': 'small',
            'image': 'teardrop-home',
        },
    )
}

radar4 = {
    'center': radar_location,
    'zoom': 4,
    'basemap': map_base,
    'overlay': map_overlay,
    'color': 4,
    'smooth': 1,
    'snow': 1,
    'markers': (
        {
            'visible': 1,
            'location': radar_location,
            'color': 'red',
            'size': 'small',
            'image': 'teardrop-home',
        },
    )
}
