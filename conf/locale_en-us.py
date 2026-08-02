# -*- coding: utf-8 -*-
"""Every word PiClock puts on screen, in one place.

Copy this file to locale_<code>.py, translate the values, and point `language`
in Config.py at the new code. Only the values on the right are translated - the
names on the left are what the code looks up, so leave those alone. The same
goes for dictionary keys: 'DAL' and 'few_clouds' are lookups, not text.

Console and log messages are deliberately not here. They are diagnostics for
whoever is reading a terminal, not part of the display.

Format placeholders:
  {0}, {1}     positional values - keep them, they may be reordered
  %s, %.0f     printf placeholders - keep them, and in the same order
  \\n           a line break in the middle of a label
Anything else is free text, including the spaces: a label ending in ': ' needs
that trailing space, and a unit starting with ' ' needs its leading one.

Sections
  1. Dates, times and the clock face      6. Severe weather alerts
  2. Units                                7. Aircraft overhead
  3. Compass                              8. Blue Iris cameras
  4. Weather                              9. Shared bits
  5. Sun and moon
"""

# =============================================================================
# 1. DATES, TIMES AND THE CLOCK FACE
# =============================================================================

# The Python locale used for date and time names (locale.setlocale).
# '' uses the Pi's own setting. Locales must be installed first - 'locale -a'
# lists what you have, 'sudo dpkg-reconfigure locales' adds more.
DateLocale = ''

# Python strftime formats. %-I is the hour with no leading zero (%#I on
# Windows), %p is AM/PM, and <sup></sup> makes the ordinal a superscript.
LDateFormat = '{0:%A %B} {0.day}<sup>{1}</sup> {0.year}'
LDateFormatShort = '{0:%a %b} {0.day}<sup>{1}</sup> {0.year}'

# The clock face itself. Colour and size stay in Config.py; this is the
# wording. For a 24-hour clock use '{0:%H:%M}'.
LClockFormat = '{0:%-I:%M%p}'
LClockFormatSeconds = '{0:%-I:%M:%S %p}'   # the second page's clock

LSunTimeFormat = '{0:%-I:%M %p}'           # sunrise and sunset in the footer
LHourlyFormat = '{0:%A %-I:%M %p} '        # heading on each hourly forecast
LDailyFormat = '{0:%A %m/%d} '             # heading on each daily forecast
LMetarObserved = '{0:%H:%M %Z} {1}'        # observation time, then the station
LRadarTime = 'Radar Time: {0:%-I:%M %p}'
LLastUpdated = 'Last Updated: {0:%-I:%M %p}'

# Ordinal suffix for a day number: 1st, 2nd, 3rd, 4th. LOrdinal maps the day
# of the month to its suffix; LOrdinalDefault covers every day not listed.
# Set every value to '' for a language that does not use ordinals - or set
# DateLocale, which drops them anyway.
LOrdinalDefault = 'th'
LOrdinal = {1: 'st', 2: 'nd', 3: 'rd', 21: 'st', 22: 'nd', 23: 'rd', 31: 'st'}


# =============================================================================
# 2. UNITS
# =============================================================================
# Shown next to a number, so keep any leading space that separates the two.

# Temperature
LDegC = '°C'
LDegF = '°F'
LDegreeSign = '°'                     # after a wind bearing in degrees

# Speed
Lkmh = ' km/h'
Lmph = ' mph'

# Pressure
Lmbar = 'mbar'
LinHg = ' inHg'
LinHgBare = 'inHg'                         # METAR pressure, no leading space

# Precipitation
Lmm = ' mm'
Lin = ' in'

# Distance and altitude, used by the aircraft bubble
Lkm = 'km'
Lmiles = 'mi'
Lmetres = 'm'
Lfeet = 'ft'

LPercent = '%'


# =============================================================================
# 3. COMPASS
# =============================================================================
# Bearings from north, going clockwise. Must stay 8 entries: the code picks one
# by angle, and the on-screen arrows are matched to these by position.
Lcompass = ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')


# =============================================================================
# 4. WEATHER
# =============================================================================

# --- labels on the current conditions block ----------------------------------
LPressure = 'Pressure: '
LHumidity = 'Humidity: '
LWind = 'Wind: '
Lgusting = ' Gusts: '
LFeelslike = 'Feels Like: '
LInsideTemp = 'Inside Temp '

# --- forecast ----------------------------------------------------------------
LRain = '· Rain: '
LSnow = '· Snow: '
LAccumulation = 'Accumulation: '

# --- condition names from Tomorrow.io ----------------------------------------
# Keyed by Tomorrow.io's own weather codes. Leave the numbers alone.
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

# --- condition names from a METAR station ------------------------------------
# Keyed by a fixed id, so the METAR decoding table in the script keeps working
# whatever language this file is in. Translate the values only.
Lmetar = {
    'clear':                 'Clear',
    'few_clouds':            'Few Clouds',
    'scattered_clouds':      'Scattered Clouds',
    'mostly_cloudy':         'Mostly Cloudy',
    'cloudy':                'Cloudy',
    'drizzle':               'Drizzle',
    'rain':                  'Rain',
    'light_rain':            'Light Rain',
    'heavy_rain':            'Heavy Rain',
    'freezing_rain':         'Freezing Rain',
    'light_freezing_rain':   'Light Freezing Rain',
    'heavy_freezing_rain':   'Heavy Freezing Rain',
    'rain_showers':          'Rain Showers',
    'light_rain_showers':    'Light Rain Showers',
    'heavy_rain_showers':    'Heavy Rain Showers',
    'blowing_rain':          'Blowing Rain',
    'light_blowing_rain':    'Light Blowing Rain',
    'heavy_blowing_rain':    'Heavy Blowing Rain',
    'snow':                  'Snow',
    'light_snow':            'Light Snow',
    'heavy_snow':            'Heavy Snow',
    'freezing_snow':         'Freezing Snow',
    'light_freezing_snow':   'Light Freezing Snow',
    'heavy_freezing_snow':   'Heavy Freezing Snow',
    'snow_showers':          'Snow Showers',
    'light_snow_showers':    'Light Snow Showers',
    'heavy_snow_showers':    'Heavy Snow Showers',
    'blowing_snow':          'Blowing Snow',
    'light_blowing_snow':    'Light Blowing Snow',
    'heavy_blowing_snow':    'Heavy Blowing Snow',
    'snow_pellets':          'Snow Pellets',
    'blowing_snow_pellets':  'Blowing Snow Pellets',
    'ice_crystals':          'Ice Crystals',
    'ice_pellets':           'Ice Pellets',
    'hail':                  'Hail',
    'heavy_hail':            'Heavy Hail',
}


# =============================================================================
# 5. SUN AND MOON
# =============================================================================
LSunRise = 'Sun Rise: '
LSet = ' · Set: '
LMoonPhase = ' · Moon: '

Lmoon1 = 'New Moon'
Lmoon2 = 'Waxing Crescent'
Lmoon3 = 'First Quarter'
Lmoon4 = 'Waxing Gibbous'
Lmoon5 = 'Full Moon'
Lmoon6 = 'Waning Gibbous'
Lmoon7 = 'Third Quarter'
Lmoon8 = 'Waning Crescent'


# =============================================================================
# 6. SEVERE WEATHER ALERTS
# =============================================================================
# The red bubble, and the panel that opens when you tap it.
LAlertGeneric = 'Alert'                    # when the feed names no event type
LAlertUntil = '  ·  until {0:%-I:%M %p}'   # appended to the alert headline
LAlertEffective = 'Effective {0:%a %-I:%M %p}'
LAlertExpires = 'Until {0:%a %-I:%M %p}'
LAlertInstruction = 'WHAT TO DO:'          # heading above the advice text
LAlertSource = 'Source: '
LAlertPaging = 'Alert {0} of {1}'          # {0} current, {1} total


# =============================================================================
# 7. AIRCRAFT OVERHEAD
# =============================================================================
LFlightUnknown = 'Aircraft'                # when the feed gives no callsign
LFlightTitle = '%s %s'                     # airline name, then the flight number
LFlightBearing = '%s to the %s %s'         # distance, compass point, arrow
LFlightAway = '%s away'                    # when no bearing was reported
LFlightElevation = '%.0f%s above horizon'  # degrees, then the degree sign
LFlightSpeed = '%.0f %s'                   # speed, then its unit

# Airline names, keyed by the ICAO prefix of the callsign. Leave the keys alone.
Lairlines = {
    'AAL': 'American', 'AAY': 'Allegiant', 'ACA': 'Air Canada', 'ASA': 'Alaska',
    'ASH': 'Mesa', 'AWI': 'Air Wisconsin', 'DAL': 'Delta', 'EDV': 'Endeavor',
    'ENY': 'Envoy', 'FFT': 'Frontier', 'GJS': 'GoJet', 'HAL': 'Hawaiian',
    'JBU': 'JetBlue', 'JIA': 'PSA', 'JZA': 'Jazz', 'KAP': 'Cape Air',
    'MXY': 'Breeze', 'NKS': 'Spirit', 'PDT': 'Piedmont', 'POE': 'Porter',
    'QXE': 'Horizon', 'ROU': 'Air Canada Rouge', 'RPA': 'Republic',
    'SCX': 'Sun Country', 'SKW': 'SkyWest', 'SWA': 'Southwest',
    'TSC': 'Air Transat', 'UAL': 'United', 'VOI': 'Volaris', 'WJA': 'WestJet',

    'ABX': 'ABX Air', 'CKS': 'Kalitta', 'CLX': 'Cargolux', 'FDX': 'FedEx',
    'GEC': 'Lufthansa Cargo', 'GTI': 'Atlas Air', 'PAC': 'Polar Air',
    'UPS': 'UPS',

    'EJA': 'NetJets', 'LXJ': 'Flexjet',

    'AUA': 'Austrian', 'AFR': 'Air France', 'BAW': 'British Airways',
    'BEL': 'Brussels', 'CFG': 'Condor', 'DLH': 'Lufthansa', 'EIN': 'Aer Lingus',
    'EZY': 'easyJet', 'FIN': 'Finnair', 'IBE': 'Iberia', 'ICE': 'Icelandair',
    'KLM': 'KLM', 'LOT': 'LOT', 'NAX': 'Norwegian', 'RYR': 'Ryanair',
    'SAS': 'SAS', 'SWR': 'Swiss', 'TAP': 'TAP', 'THY': 'Turkish',
    'VIR': 'Virgin Atlantic', 'VLG': 'Vueling', 'WZZ': 'Wizz Air',

    'AMX': 'Aeromexico', 'ANA': 'All Nippon', 'ANZ': 'Air New Zealand',
    'AVA': 'Avianca', 'CPA': 'Cathay Pacific', 'CMP': 'Copa', 'ETD': 'Etihad',
    'ETH': 'Ethiopian', 'JAL': 'Japan Airlines', 'KAL': 'Korean Air',
    'LAN': 'LATAM', 'QFA': 'Qantas', 'QTR': 'Qatar', 'SIA': 'Singapore',
    'UAE': 'Emirates', 'VOZ': 'Virgin Australia',

    'CAP': 'Civil Air Patrol',
}


# =============================================================================
# 8. BLUE IRIS CAMERAS
# =============================================================================

# --- what the camera panel says while it works ------------------------------
LCameraConnecting = 'Connecting to %s...'  # camera name
LCameraSigningIn = 'Signing in to Blue Iris...'
LCameraSigningInAgain = 'Signing in to Blue Iris again...'
LCameraUnavailable = '%s unavailable\n%s'  # camera name, then the reason below
LCameraLoginFailed = 'Blue Iris login failed\n'
LCameraNoServer = 'blueiris_server is not set in Config.py'

# --- the reasons that fill in the %s above -----------------------------------
LBiNoUser = 'blueiris_user is not set in Config.py'
LBiNotJson = 'Blue Iris did not return JSON from /json'
LBiNoSession = 'no session key in the Blue Iris login response'
LBiBuildFailed = 'could not build the Blue Iris login response'
LBiReadFailed = 'could not read the Blue Iris login response'
LBiLoginRefused = 'login refused'
LBiLoginReason = 'Blue Iris %s (check blueiris_user/blueiris_password)'
LBiNotVideo = ('not a video stream (server sent "%s") - check the Blue Iris '
               'credentials and blueiris_use_session_login')
LBiNoContentType = 'no content type'


# =============================================================================
# 9. SHARED BITS
# =============================================================================
# Used by more than one part of the display.
LBubbleCount = '  ({0}/{1})'   # alert and aircraft bubbles, when several are up
LBulletWide = '  •  '          # between the parts of a bubble's sub-line
LBulletNarrow = ' · '          # between the badges on the alert detail panel
