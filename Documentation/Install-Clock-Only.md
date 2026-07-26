# Install Instructions for PiClock (Clock Only)

This version of the instructions is for setting up just the clock
itself, ignoring all the other options.   It also assumes you have
some OS already setup.   So this is useful for setting up the
clock on a desktop OS.

# Prerequisites

The minium requirements for a PiClock is pretty simple
* Python 3
* Python Qt6, known as PyQt6
* git (as an alternative to git, you can download the zip file from GitHub)

Theses are available under Windows, Linux, and OSX OS's.

How to get these installed on your choice of system I'll leave
as an exercise for the reader.

### Get the PiClock software
1. On GitHub.com, navigate to the main page of the repository: [PiClock](../)
2. Above the list of files, click the **< > Code** button.
3. Copy the HTTPS URL for the repository. It'll look something like this:
https://github.com/USERNAME/PiClock.git
4. Log into your Pi, (either on the screen or via ssh) (NOT as root).
You'll be in the home directory of the user pi (/home/pi) by default,
and this is where you want to be.  Note that the following command while
itself not being case-sensitive, further operation of PiClock may be
affected if the upper and lower case of the command is not followed.
5. Download PiClock using the `git clone` command followed by the 
HTTPS URL for the repository, for example:

```
git clone https://github.com/USERNAME/PiClock.git
```

Once that is done, you'll have a new directory called PiClock.

Alternatively, you can download the zip file from GitHub
by clicking the **< > Code** button above the list of files at [PiClock](../), 
select **Download ZIP**, then unzip it onto your system.

### Quick install (recommended)
For a standard install (no GPIO buttons, IR remote, temperature sensors, or
NeoPixel LEDs), an installer script will create the virtual environment,
install the required Python packages, install the bundled Open Sans fonts
from the `fonts` folder for the current user, set up `Clock/ApiKeys.py` and
`Clock/Config.py` from the examples, and interactively prompt you for your
location, API keys, map provider, slideshow, and NOAA alert settings.

On Linux/macOS:
```
cd PiClock
bash install.sh
```
On Windows (the interactive prompts require PowerShell, included by default
on Windows 10/11):
```
cd PiClock
install.bat
```
It's safe to run again later - it won't overwrite an existing
`Clock/ApiKeys.py` or `Clock/Config.py` unless you explicitly opt back into
the interactive prompts. If you skip the prompts (or need settings the
installer doesn't ask about, like the radar map centers/markers), continue
with the manual steps below.

### Configure the PiClock API keys

You need to set API keys for one weather service and one map service.
These are free unless you have large volume.
The PiClock usage is well below the maximums imposed by the no cost API keys.

PiClock also caches weather and radar API responses to disk for a short time
(matching the `weather_refresh`/`radar_refresh` minutes set in Config.py), so
restarting the app repeatedly - for example while testing changes - reuses the
last response instead of re-calling the API on every launch. The cache lives in
`Clock/api_cache` and can be deleted at any time; it's just rebuilt on the next
launch.

_Protect your API keys._  You'd be surprised how many pastebin's are out
there with valid API keys, because of people not being careful.   _If you post
your keys somewhere, your usage will skyrocket, and your bill as well._  Google
has the ability to add referer, device and IP requirements on your API key.  It
can also allow you to limit an API key to specific applications only (static-maps)
in this case. Also, you might consider disabling all the other APIs on your
project dashboard. Under the Billing section of things you can set up budgets
and alerts (set to like $1.00).

#### Weather API Key

A Tomorrow.io API key is required to get your current weather and forecast data.

#### Tomorrow API key

A Tomorrow API key is required to use Tomorrow weather data.

Tomorrow API keys are created by signing up at this link:
https://www.tomorrow.io/weather-api/

#### Map API Key

You have your choice of Mapbox or Google Maps from which to get your underlying maps.
You only need one or the other (mbapi or googleapi)

#### Mapbox API key

A Mapbox API key (access token) is required to use Mapbox.

Mapbox access tokens are created by signing up at this link:
https://www.mapbox.com/signup/

#### Google Maps API key

A Google Maps API key is required to use Google Maps.
(Requires credit card which won't be charged unless usage is high.)

An intro to Google static maps API keys, and a link to creating your account and API keys:
https://developers.google.com/maps/documentation/maps-static/intro
You'll require a Google user and password.  It'll also require a credit card.
The credit card should not be charged, because my reading of
https://cloud.google.com/maps-platform/pricing/sheet/ the $200.00 credit will
apply, and your charges incurred will be for 31 map pulls per month will be
$0.62 , if you reboot daily.
You'll be required to create a "project" (maybe PiClock for a project name?)
You need to then activate the key.

Now that you have your API keys, copy the ApiKeys-example.py as ApiKeys.py and edit it...

```
cd PiClock/Clock
cp ApiKeys-example.py ApiKeys.py
nano ApiKeys.py
```
Put your API keys in the file as indicated. Comment out the lines of unused API keys.
```
# Change this to your API keys

# Map API keys -- only need 1 of the following
# Google Maps API key (if usemapbox is not set in Config)
googleapi = 'YOUR GOOGLE MAPS API KEY'
# Mapbox API key (access_token) [if usemapbox is set in Config]
mbapi = 'YOUR MAPBOX ACCESS TOKEN'

# Weather API key
tmapi = 'YOUR TOMORROW API KEY'
```

### Configure your PiClock
Here's where you tell PiClock where your weather should come from, and the
radar map centers and markers.  Copy the Config-Example.py as Config.py and edit it...

```
cd PiClock/Clock
cp Config-Example.py Config.py  (copy on windows)
[use your favorite editor] Config.py
```

This file is a python script, subject to python rules and syntax.
The configuration is a set of variables, objects and arrays,
set up in python syntax.  The positioning of the {} and () and ','
are not arbitrary.  If you're not familiar with python, use extra
care not to disturb the format while changing the data.

The first thing is to change the Latitudes and Longitudes you see to yours.
They occur in several places. The first one in the file is where your weather
forecast comes from.   The others are where your radar images are centered
and where the markers appear on those images.  Markers are those little red
location pointers.

#### SlideShow settings
PiClock can show a rotating background slideshow behind the clock. It's controlled
by these Config.py settings:
  * `useslideshow` - 1 to enable, 0 to disable
  * `slide_time` - seconds between image changes
  * `slide_bg_color` - background color shown behind images that don't fill the screen
  * `slide_transition_ms` - crossfade duration between images, in milliseconds; 0 for an instant hard cut
  * `web_slideshow_playlist` - 0 for your own local images, 1 for a web playlist (see below)
  * `slideshow_url` - only used when `web_slideshow_playlist = 1`

With `web_slideshow_playlist = 0`, drop your own images (`.jpg`, `.jpeg`, `.png`,
`.gif`, `.bmp`, `.webp`) into `PiClock/Pictures/Slideshow` and PiClock shows them
in random order.

With `web_slideshow_playlist = 1`, `slideshow_url` should point to a plain text
file listing one image URL per line. PiClock downloads every image in that list
and caches them in `PiClock/Clock/slideshow_cache`. The cache is cleared and
everything re-downloaded fresh on every launch; while running, the list is
re-checked every 2 hours, and only images newly added to the list get downloaded
(images removed from the list are deleted from the cache).

#### Severe weather alerts
PiClock can show a red warning bubble - below the clock, above the sunrise/set
line - whenever there's an active NOAA/NWS alert for your location (severe
thunderstorm watches/warnings, tornado warnings, flood warnings, etc.), using
the free, no-signup-required [National Weather Service API](https://www.weather.gov/documentation/services-web-api).
It's controlled by these Config.py settings:
  * `noaa_alerts_enabled` - 1 to enable, 0 to disable
  * `alert_refresh` - minutes between alert checks
  * `alert_severities` - which NWS severity levels trigger the bubble (defaults
    to `('Severe', 'Extreme')`; other levels, least to most severe, are
    `'Unknown'`, `'Minor'`, `'Moderate'`)

If multiple alerts are active at once, the bubble cycles through them one at a
time. Unlike the weather/radar API calls, alert checks are never served from
`Clock/api_cache` - they always hit the live API, since a stale cached "no
alerts" response could mask a genuinely new one.

#### Screen brightness and always-on display
PiClock can automatically dim the whole display at night and brighten it back
up during the day, on a schedule you set using a 24-hour clock. This is a
software dim (a black overlay drawn on top of everything), so it works the
same regardless of your monitor or OS - no special hardware backlight support
needed. It's controlled by these Config.py settings:
  * `brightness_enabled` - 1 to enable time-based dimming, 0 to always use `day_brightness`
  * `day_brightness` / `night_brightness` - 0-100 brightness percentage for day/night
  * `day_start` / `night_start` - 24-hour `HH:MM` times when each period begins
  * `brightness_transition_minutes` - minutes to fade gradually between day and
    night brightness; 0 for an instant switch

PiClock also tries, best-effort, to stop the OS from blanking or sleeping the
display while it's running (handy since this is meant to be an always-on
clock). This is controlled by `prevent_screen_sleep` (1 to enable, 0 to
disable), and uses the native mechanism for your OS: `SetThreadExecutionState`
on Windows, `caffeinate` on macOS, and `xset`/`systemd-inhibit` on Linux. Not
every desktop environment honors these, so treat it as a best effort rather
than a guarantee.

### Run it!

```
cd PiClock
python3 PyQtPiClock.py
```
After a few seconds, your screen should be covered by the PiClock. YAY!

There may be some output on the terminal screen as it executes.
If everything works, it can be ignored.  If for some reason the clock
doesn't work, or maps are missing, etc. the output may give a reason
or reasons, which usually reference something to do with the config
file (Config.py)

You'll see "using cached ..." instead of "getting ..." or "Fetching ..." for
weather/radar data whenever a recent-enough response was already saved in
`Clock/api_cache` - that's expected, not an error, and just means PiClock
didn't need to call the API again.

### First Use

  * The space bar or right or left arrows will change the page.
  * F2 will start and stop the NOAA weather radio stream
  * F4 will close the clock
  * F6 will show the previous slideshow image
  * F7 will show the next slideshow image
  * F8 will pause/resume the slideshow
  * F9 will toggle the foreground (clock/weather/radar) on and off, showing just the slideshow


### Updating to newer/updated versions
Since you pulled the software from GitHub originally, it can be updated
using git and GitHub.
```
cd PiClock
git pull
bash update.sh
```
This will automatically update any part(s) of the software that has changed.
The update.sh script will then convert any config files as needed.
