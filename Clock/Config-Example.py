# -*- coding: utf-8 -*-
from PyQt5.QtGui import QColor

from GoogleMercatorProjection import LatLng  # NOQA

# LOCATION(S)
# Further radar configuration (zoom, marker location) can be
# completed under the RADAR section
primary_coordinates = 44.9764016, -93.2486732  # Change to your Lat/Lon

# Location for weather report
location = LatLng(primary_coordinates[0], primary_coordinates[1])
# Default radar location
radar_location = LatLng(primary_coordinates[0], primary_coordinates[1])

noaastream = 'http://www.urberg.net:8000/tim273/edina'
background = 'images/mesa.jpg'
squares1 = 'images/squares1-kevin.png.bak'
squares2 = 'images/squares2-kevin.png.bak'
icons = 'icons-lightblue'
textcolor = '#FFFFFF'
clockface = 'images/clockface3.png'
hourhand = 'images/hourhand.png'
minhand = 'images/minhand.png'
sechand = 'images/sechand.png'

# SlideShow
useslideshow = 1  # 1 to enable, 0 to disable
slide_time = 600  # in seconds, 3600 per hour
slide_bg_color = '#000'  # https://htmlcolorcodes.com/  black #000
slideshow_url = 'https://example.com/slideshow.txt' # must be plaintext formated, one image URL per line. Github works well for this

# Set to Digital Mode
digital = 1  # 1 = Digital Clock, 0 = Analog Clock
digitalcolor = '#FFFFFF' #Color of the text
digitalformat = '{0:%-I:%M%p}'  # Format of the digital clock face
digitalsize = 150 # Font Size of Clock
digitalformat2 = '{0:%-I:%M:%S %p}'  # Format of the digital time on second screen

# Mapbox map styles, need API key (mbapi in ApiKeys.py)
# If no Mapbox API is set, Google Maps are used
map_base = 'andrewhover/cm3f80lgn001o01qv6vvk1rtq'  # Custom dark Mapbox style for land and water only (bottom layer that goes below weather radar)
# map_overlay = 'bcurley/cj712r01c0bw62rm9isme3j8c'  # Custom Mapbox style for labels, roads, and borders only (top layer that goes above weather radar)
# map_base = 'mapbox/satellite-streets-v12'  # Uncomment for standard Mapbox Satellite Streets style, and comment/remove the custom style
# map_base = 'mapbox/streets-v12'  # Uncomment for standard Mapbox Streets style, and comment/remove the custom style
# map_base = 'mapbox/outdoors-v12'  # Uncomment for standard Mapbox Outdoors style, and comment/remove the custom style
# map_base = 'andrewhover/cm3f6hann001u01s13wl6hf7a'  # Uncomment for standard Mapbox Dark style, and comment/remove the custom style
# map_base = 'mapbox/cj5l80zrp29942rmtg0zctjto'  # Mapbox calls this map style 'Decimal'
map_overlay = 'andrewhover/cm3f7fhze001i01ry1o3m600s'  # Uncomment and leave blank if using standard Mapbox style, and comment/remove the custom style

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
dimcolor = QColor('#000000')
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

# Language specific wording
# OpenWeather Language code
#  (https://openweathermap.org/current#multi)
Language = 'EN'

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
LSet = ' | Set: '
LMoonPhase = ' | Moon: '
LInsideTemp = 'Inside Temp '
LRain = 'Rain: '
LSnow = 'Snow: '
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
    'zoom': 10,  # this is a maps zoom factor, bigger = smaller area
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
            'image': 'teardrop-dot',  # optional image from the markers folder
        },  # dangling comma is on purpose.
    )
}

radar2 = {
    'center': radar_location,
    'zoom': 8,
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
            'image': 'teardrop-dot',
        },
    )
}

radar3 = {
    'center': radar_location,
    'zoom': 5,
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
            'image': 'teardrop-dot',
        },
    )
}

radar4 = {
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
            'image': 'teardrop-dot',
        },
    )
}
