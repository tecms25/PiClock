# Install Instructions for PiClock
## For Raspberry Pi OS

PiClock and this install guide are based on Raspberry Pi OS downloaded from
https://www.raspberrypi.com/software/. I suggest using
"Raspberry Pi OS with desktop".  It will work with many Raspberry Pi OS versions,
but you may have to add more packages, etc.  That exercise is left for the reader.

What follows is a step-by-step guide.  If you start with a new clean Raspberry Pi OS
image, it should just work. I'm assuming that you already know how to hook
up your Raspberry Pi, monitor, and keyboard/mouse.   If not, please do a web search
regarding setting up the basic hardware for your Raspberry Pi.

### Download Raspberry Pi OS (or Ubuntu) and put it on an SD Card

The instructions for doing this are on the following page:
https://www.raspberrypi.com/documentation/computers/getting-started.html

### First boot and configure
A keyboard and mouse are really handy at this point.
When you first boot your Pi, you'll be presented with the desktop.
Following this there will be several prompts to set things up, follow
those prompts and set things as they make sense for you.  Of course
setting the proper timezone for a clock is key.

Eventually the Pi will reboot, and you'll be back to the desktop.
You need to configure a few more things.

Navigate to Menu->Preferences->Raspberry Pi Configuration.
Just change the Items below.
 - System Tab
  - Hostname: (Maybe set this to PiClock?)
  - Boot: To Desktop
  - Auto Login: Checked
  - Overscan: (Initially leave as default, but if your monitor has extra
    black area on the border, or bleeds off the edge, then change this)
 - Interfaces
  - SSH is handy (if you'd like to connect to your clock from another computer)
  - VNC can be handy  (same reason as ssh)


Click ok, and allow it to reboot.

### Get connected to the internet

Log into your Pi, (either on the screen or via ssh). 

Verify you have internet access from the Pi.

```
ping github.com
```
(remember ctrl-c aborts programs, like breaking out of ping, which will
go on forever)

### Get all the software that PiClock needs
Update the package repository and get the full Python3 and Qt6 for Python
```
sudo apt update
sudo apt install python3-full python3-pyqt6
```
(`python3-pyqt6` requires Raspberry Pi OS Bookworm or newer; on older releases, install PyQt6 via `pip install PyQt6` inside the virtual environment instead.)
You may need to confirm some things, like:
After this operation, 59.5 MB of additional disk space will be used.
Do you want to continue [Y/n]? 
Go ahead, say yes.

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

### Quick install (recommended)
For a standard install - no GPIO buttons - an installer script can do the rest
of this section for you:
it creates the virtual environment, installs PyQt6 and the required Python
packages (offering to use `apt` for `python3-pyqt6`/`mpg123`/`ffmpeg` on Raspberry Pi
OS), installs the bundled Open Sans fonts from the `fonts` folder for the
current user, sets up `conf/ApiKeys.py` and `conf/Config.py` from the
examples, and interactively prompts you for your location, API keys, map
provider (including custom Mapbox base/overlay styles), slideshow, NOAA alert,
and day/night screen brightness settings. On a GNOME desktop it also offers to
disable idle screen blanking, auto-lock, and auto-dim, so the clock stays
visible.
```
cd PiClock
bash install.sh
```
It's safe to run again later - it won't overwrite an existing
`conf/ApiKeys.py` or `conf/Config.py` unless you explicitly opt back into
the interactive prompts. If you skip the prompts (or need settings the
installer doesn't ask about, like the radar map centers/markers), continue
with the manual steps below. If you need the optional GPIO buttons, follow the
manual steps in this section instead.

### Create virtual environment
Create a Python virtual environment in the PiClock directory for 
installing the required Python packages and running PiClock.
```
cd PiClock
python3 -m venv venv
```
Activate the virtual environment in the PiClock directory 
before you install any Python packages.
```
source venv/bin/activate
```
You will know you are working in the virtual environment when the 
command prompt begins with (venv). 
It will look something like this:
```
(venv) pi@piclock:~/PiClock $
```

### Required software packages
Once inside the virtual environment, install required Python packages
```
python3 -m pip install --upgrade pip
python3 -m pip install -r requirements.txt
```
### Optional software packages
#### Optional - audio stream players
mpg123 plays MP3 streams such as NOAA weather radio. ffmpeg supplies ffplay,
which is also needed for `.m3u8` (HLS) feeds - most scanner streams - because
mpg123 cannot follow an HLS playlist.
```
sudo apt install mpg123 ffmpeg
```

### Exit virtual environment
To leave the virtual environment, use the following command
```
deactivate
```

### Reboot
To get some things running, and ensure the final config is right, do
a reboot
```
sudo reboot
```

Log into your Pi, (either on the screen or via ssh) (NOT as root).
You'll be in the home directory of the user pi (/home/pi) by default.

### Optional - Set up GPIO keys

A few commands are needed if you intend to use gpio buttons
and the gpio-keys driver to compile it for the latest Raspberry Pi OS:
```
cd PiClock/Button
make gpio-keys
cd ../..
```

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
cd PiClock/conf
cp ApiKeys-example.py ApiKeys.py
nano ApiKeys.py
```
Put your API keys in the file as indicated.  Comment out the lines of unused API keys.
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
cd PiClock/conf
cp Config-Example.py Config.py
nano Config.py
```

This file is a python script, subject to python rules and syntax.
The configuration is a set of variables, objects and arrays,
set up in python syntax.  The positioning of the {} and () and ','
are not arbitrary.  If you're not familiar with python, use extra
care not to disturb the format while changing the data.

The first thing is to change the primary_coordinates to yours.  That is really
all that is mandatory.  Further customization of the radar maps can be done in
the Radar section.  There you can customize where your radar images are centered
and where the markers appear on those images.  Markers are those little red
location pointers.  Radar1 and 2 show on the first page, and 3 and 4 show on the
second page of the display (here's a post of about that:
https://www.facebook.com/permalink.php?story_fbid=1371576642857593&id=946361588712436&substory_index=0)

The second thing to change is your NOAA weather radio stream url.  You can
find it here: http://noaaweatherradio.org/  They don't put the .mp3 urls
where they are easily accessible, so you need to use your browser to "View Page Source"
in order to find the proper .mp3 url.

#### SlideShow settings
PiClock can show a rotating background slideshow behind the clock. It's controlled
by these Config.py settings:
  * `useslideshow` - 1 to enable, 0 to disable
  * `slide_time` - seconds between image changes
  * `slide_bg_color` - background color shown behind images that don't fill the screen
  * `slide_transition_ms` - crossfade duration between images, in milliseconds; 0 for an instant hard cut
  * `web_slideshow_playlist` - 0 for your own local images, 1 for a web playlist,
    2 for a shared iCloud album (all described below)
  * `slideshow_url` - only used when `web_slideshow_playlist = 1`
  * `slideshow_icloud_album` - only used when `web_slideshow_playlist = 2`

With `web_slideshow_playlist = 0`, drop your own images (`.jpg`, `.jpeg`, `.png`,
`.gif`, `.bmp`, `.webp`) into `PiClock/Pictures/Slideshow` and PiClock shows them
in random order.

With `web_slideshow_playlist = 1`, `slideshow_url` should point to a plain text
file listing one image URL per line. PiClock downloads every image in that list
and caches them in `PiClock/Clock/slideshow_cache`. The cache is cleared and
everything re-downloaded fresh on every launch; while running, the list is
re-checked every 2 hours, and only images newly added to the list get downloaded
(images removed from the list are deleted from the cache).

With `web_slideshow_playlist = 2`, PiClock pulls photos from a shared iCloud
album, so anything you add to that album from an iPhone, iPad, or Mac appears
on the clock at the next refresh. To set it up, in Photos create an album,
share it, turn on **Public Website**, and copy the link into
`slideshow_icloud_album` - it looks like
`https://www.icloud.com/sharedalbum/#B0Xabc123`.

Notes on this mode:
  * No Apple ID or password is involved. It uses the same public endpoints the
    shared album's web page does, so nothing is stored on the Pi.
  * **Anyone with the link can view that album.** The link is long and
    unguessable, but it isn't password protected - don't put private photos in it.
  * Unlike the playlist mode, this cache is **kept between launches**. Photos
    are tracked by their iCloud IDs, so a restart re-uses what's already on
    disk and only syncs what actually changed in the album.
  * If the album can't be reached (no network yet at boot, for example) the
    previously cached photos keep showing rather than the screen going blank.
  * Videos in the album are skipped, and photos are shown newest first as they
    download.
  * Apple doesn't document these endpoints, so this could break if they change
    them. If that happens the slideshow falls back to the cached photos.

#### Severe weather alerts
PiClock can show a red warning bar - below the clock, above the sunrise/set
line - whenever there's an active NOAA/NWS alert for your location (severe
thunderstorm watches/warnings, tornado warnings, flood warnings, etc.), using
the free, no-signup-required [National Weather Service API](https://www.weather.gov/documentation/services-web-api).
It's controlled by these Config.py settings:
  * `noaa_alerts_enabled` - 1 to enable, 0 to disable
  * `alert_refresh` - minutes between alert checks
  * `alert_severities` - which NWS severity levels trigger the bar (defaults
    to `('Severe', 'Extreme')`; other levels, least to most severe, are
    `'Unknown'`, `'Minor'`, `'Moderate'`)

The bar shows the event name and expiry on its top line, with the affected
area and the NWS headline scrolling underneath. If multiple alerts are active
at once, it cycles through them one at a time and shows a "(1/2)" counter.

Click or tap the bar to open the full alert: the complete NWS description,
the "what to do" instructions, the affected area, timing, and severity. Use
the arrows to page through other active alerts, and the close button, Escape,
or a tap outside the card to dismiss it.

Unlike the weather/radar API calls, alert checks are never served from
`Clock/api_cache` - they always hit the live API, since a stale cached "no
alerts" response could mask a genuinely new one.

#### Aircraft overhead
PiClock can show a bubble naming an aircraft passing overhead - callsign and
airline, how far away it is and which way to look, its altitude, speed and
type. It uses the same spot on screen as the severe weather alert, and gives
way to it: while any alert is active the aircraft bubble stays hidden, and it
comes back once the alert clears. Settings:

  * `flights_enabled` - 1 to enable, 0 to disable (off by default)
  * `flight_poll_seconds` - how often to look for aircraft
  * `flight_min_elevation` - how high in the sky a plane must be to count,
    in degrees above the horizon
  * `flight_search_radius_nm` - how far out to ask for aircraft (max 250)

`flight_min_elevation` is the setting that decides what you actually see, and
it is deliberately an angle rather than a distance. A jet at 35,000ft is
genuinely overhead at 10nm but an invisible speck at 30nm, so a plain radius
would either miss the good ones or bury you in ones you cannot see. At the
default of 30 degrees you get a handful at a time, all high in the sky. Lower
it to catch more, raise it for only the ones nearly straight up.

Data comes from [airplanes.live](https://airplanes.live/), a volunteer-run
ADS-B feed. No account or API key is needed, but it is someone else's
bandwidth being spent, which is why this is off unless you turn it on. If you
enable it, keep `flight_poll_seconds` reasonable.

#### Where things live
```
Clock/          the application
conf/           settings, keys and wording
  Config.py         your settings (not in git)
  ApiKeys.py        your API keys (not in git)
  locale_en-us.py   every word the clock puts on screen
  GoogleMercatorProjection.py
logs/           PyQtPiClock.1.log ... .7.log
```

Wording used to be split between `Config.py` and the main script. It is all in
`conf/locale_en-us.py` now - labels, moon phases, weather-condition names,
units, alert and camera messages. To change what the clock says, edit that
file; to run another language, copy it to `conf/locale_<code>.py`, translate
the values on the right, and set `language` in `Config.py` to that code.

Console and log messages are deliberately not in there. They are diagnostics
for whoever is reading a terminal, not part of the display.

If you are upgrading, `update.py` moves your existing `Clock/Config.py` and
`Clock/ApiKeys.py` into `conf/` and your logs into `logs/`. A config that still
defines its own wording keeps working - those values win over the locale file,
and PiClock prints a note at startup naming what it picked up so you know what
to move.

`update.py` also checks how the clock starts. If you still launch it from
`~/.config/autostart`, it offers to switch you to the systemd service described
below and then removes the shortcut, since leaving both in place starts two
clocks at login. If the service is already installed and the shortcut is still
there, it offers to remove just the shortcut. Nothing is removed without a yes,
and a run with no terminal attached changes nothing.

`update.sh` also keeps translations current. `conf/locale_en-us.py` is the one
PiClock ships and updates, so when a release adds new wording, `merge_config.py`
appends the new entries (in English) to every other `conf/locale_*.py` you have,
ready for you to translate. Anything still missing falls back to English at
startup with a note in the log, so a translation that has fallen behind shows a
few English labels rather than stopping the clock.

#### Blue Iris camera alerts
If you run [Blue Iris](https://blueirissoftware.com/), a camera can put itself
on screen the moment it trips an alert, then the clock comes back. Nothing is
polled - Blue Iris calls PiClock, so the popup is as quick as the alert itself.

Settings:

  * `blueiris_enabled` - 1 to enable, 0 to disable (off by default)
  * `blueiris_listen_port` - port PiClock listens on (default 8127)
  * `blueiris_token` - shared secret, must match the `token=` in the web request
  * `blueiris_server` - Blue Iris web server, e.g. `http://192.168.1.10:81`
  * `blueiris_user` / `blueiris_password` - a Blue Iris user allowed to view cameras
  * `blueiris_cameras` - which cameras may pop up, by short name; empty means any
  * `blueiris_triggers` - only pop up when the alert memo mentions one of these
  * `blueiris_show_seconds` - how long the camera stays up
  * `blueiris_stream_width` - width Blue Iris scales the stream to before sending
  * `blueiris_allow_from` - optional source address allow-list
  * `blueiris_ignore_ssl_errors` - accept a certificate that fails validation
  * `blueiris_use_session_login` - sign in via the JSON interface (see below)
  * `blueiris_session_seconds` - how long a sign-in is reused before signing in
    again; keep it under the Blue Iris session timeout (about a minute by
    default), or set 0 to sign in afresh every time

In Blue Iris, open the camera's settings, go to **Alerts**, and add an
**On alert** action of **Web request**. Point it at the clock:

```
http://<pi-address>:8127/alert?token=<blueiris_token>&cam=&CAM&memo=&MEMO
```

`&CAM` and `&MEMO` are Blue Iris macros - it substitutes the camera's short
name and the alert memo before sending. Check the macro list in your version of
Blue Iris if those names differ. Repeat for each camera you want on the clock.

The memo is worth thinking about, because it becomes the caption *and* it is
what `blueiris_triggers` matches against. If your cameras send ONVIF events the
memo is the raw rule text, something like
`RuleEngine/PeopleDetector/People IsPeople="true"`. With TP-Link Tapo cameras
sending `IsPeople` and `IsPet` events, `blueiris_triggers = ['People']` then
shows someone at the door and ignores the cat.

You can put a friendlier label in the web request instead - `&memo=Person`
reads better on a wall clock than a rule path does - but if you do, set
`blueiris_triggers` to match what you actually send. The match is a plain
case-insensitive substring test, so a trigger of `'People'` does **not** match a
memo of `'Person'`. Either keep the ONVIF text, or change both together.

The stream is pulled from Blue Iris, not from the cameras, so the cameras
themselves stay off the internet and PiClock only needs the one Blue Iris
login. PiClock decodes every frame it is sent, so if the clock stutters while a
camera is up, lower `blueiris_stream_width` rather than the frame rate.

A note on the listener: it accepts a request from anywhere on your network
unless you set `blueiris_token` (and optionally `blueiris_allow_from`). Set the
token. It is the only thing stopping something else on the LAN putting a camera
on your wall.

##### Reaching Blue Iris when it wants a login
How PiClock authenticates to Blue Iris depends on one Blue Iris setting: **Use
secure session keys and login page**, on the Advanced page of
Settings/Webserver.

  * **Switched off** - Blue Iris accepts `user`/`pw` straight on the stream URL,
    so setting `blueiris_user` and `blueiris_password` is all you need.
  * **Switched on** (the default, and the safer choice) - that is refused, and
    the stream has to carry a session key instead. Set
    `blueiris_use_session_login = 1` and PiClock signs in through the Blue Iris
    JSON interface first: it asks `/json` for a challenge, answers with
    `MD5("user:session:password")`, and puts the session key it gets back on the
    stream request. The key is kept between alerts, so a camera does not pay for
    a login every time, and if it is ever refused PiClock signs in again once
    before reporting a problem.

If Blue Iris is on the same network as the clock, point `blueiris_server` at its
LAN address. Camera video then never leaves your network, there is no
certificate to validate, and any reverse proxy in front of the public hostname
is out of the picture. Reach for `blueiris_use_session_login` and
`blueiris_ignore_ssl_errors` when the clock has to come in from outside.

`blueiris_ignore_ssl_errors = 1` accepts a certificate that fails validation -
self-signed, or issued for a different name than you are connecting to. It
applies to the camera stream and its login only; the weather, radar and photo
fetches go on checking certificates properly. Whatever gets waved through is
named in the log:

```
WARNING: camera stream TLS problem ignored: The certificate is self-signed, and untrusted
```

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
disable), and uses the native mechanism for your OS:
  * **Windows** - `SetThreadExecutionState` with `ES_DISPLAY_REQUIRED`
  * **macOS** - a `caffeinate -d -i` process, plus a periodic `caffeinate -u`
    that resets the separate idle timer the screensaver and lock screen use
    (`-d -i` alone does not stop those)
  * **Linux** - `xset` to disable X11 blanking/DPMS, plus a `systemd-inhibit`
    idle/sleep lock that also covers Wayland

Not every desktop environment honors these, so treat it as a best effort. On
GNOME (including Raspberry Pi OS with GNOME), `install.sh` additionally offers
to turn off idle blanking, auto-lock, and auto-dim via `gsettings`, which is
the reliable fix there.

#### Layout and text legibility
Light text over a bright photo needs help to stay readable, but a heavy drop
shadow alone tends to bury the picture. Two settings control this:

  * `layout` - `'photo'` or `'classic'`
  * `scrim_opacity` - 0-255; 0 turns the gradient panels off

`'classic'` is the original arrangement: a large clock centered on the screen,
the day/date across the top, sun rise/set along the bottom.

`'photo'` rearranges page 1 to keep the background image visible. The time,
day/date and sun rise/set stack along the bottom, sized so
the time leads that group, and the severe weather alert moves up near the top.
The middle of the screen is left for the image.

`scrim_opacity` draws soft gradient panels behind the text along the left,
right, top and bottom edges. They fade out toward the middle, so text stays
fully opaque and readable while the photo still shows through - much better
than making the text itself transparent, which costs legibility at a distance.
This applies to both layouts, and to any background (it is not tied to the
slideshow).

Font sizes for the pieces this moves around:
  * `digitalsize` - the clock (the `'photo'` layout suits roughly 70-85;
    `'classic'` traditionally used 150)
  * `datesize` - the day/date
  * `footersize` - the sun rise/set and moon phase line

An existing `Config.py` that predates these settings keeps the classic layout
with no scrims, so upgrading changes nothing until you opt in.

At this point, I'd not recommend many other changes until you have tested
and gotten it running.

### Upgrading an existing install
Pulling a newer PiClock can bring new `Config.py` settings with it. Copying
`Config-Example.py` over the top would wipe your location, API keys and
preferences, so `update.sh` handles it for you:

```
cd PiClock
git pull
bash update.sh
```

Near the end it lists any settings your config is missing and asks before
adding them. You can also run it yourself at any time:

```
python3 merge_config.py --dry-run   # list what you are missing
python3 merge_config.py             # add it
```

It appends only the settings your `conf/Config.py` and `conf/ApiKeys.py` do
not already have, at their default values and with their explanatory comments,
and leaves everything you have already set alone. A timestamped `.bak-` copy of
each file is written first, and re-running it is harmless once you are up to
date.

New settings land at the end of the file, so edit them there if you want
something other than the defaults.

### Run it!
You'll need to be on the desktop, in a terminal program.

```
cd PiClock
bash startup.sh -n -s
```
Your screen should be covered by the PiClock  YAY!

There will be some output on the terminal screen as startup.sh executes.
If everything works, it can be ignored.  If for some reason the clock
doesn't work, or maps are missing, etc. the output may give a reason
or reasons, which usually reference something to do with the config
file (Config.py)

### Logs
The -s option causes no log files to be created, but
instead logs to your terminal screen.  If -s is omitted, logs are
created in PiClock/logs as PyQtPiClock.[1-7].log, which can also help
you find issues.  -s is normally omitted when started from the desktop icon
or from crontab.  Logs are then created for debugging auto starts.

You'll see "using cached ..." instead of "getting ..." or "Fetching ..." for
weather/radar data whenever a recent-enough response was already saved in
`Clock/api_cache` - that's expected, not an error, and just means PiClock
didn't need to call the API again.

### First Use

  * The space bar or right or left arrows will change the page.
  * Clicking anywhere (other than an alert bar) will also change the page.
  * Clicking or tapping the severe weather alert bar opens the full alert details.
  * Escape closes the alert details panel.
  * F2 will start and stop the NOAA weather radio stream
  * F4 will close the clock
  * F6 will show the previous slideshow image
  * F7 will show the next slideshow image
  * F8 will pause/resume the slideshow
  * F9 will toggle the foreground (clock/weather/radar) on and off, showing just the slideshow

### Setting the clock to auto start
At this point the clock will only start when you manually start it, as
described in the Run It section.

`install.sh` offers to do Method 1 for you, including the "Allow Launching"
step below. These are the manual equivalents.

Use only one autostart method.
#### Autostart Method 1
(NOT as root)
```
cd PiClock
chmod +x PiClock.desktop
ln PiClock.desktop ~/Desktop
mkdir ~/.config/autostart
ln PiClock.desktop ~/.config/autostart
```
This puts the PiClock icon on your desktop.  It also runs it when
the desktop starts.

On GNOME 42 and newer (Ubuntu 22.04+, and Raspberry Pi OS with GNOME) a
desktop shortcut is ignored until it is marked trusted - the icon shows as
"Untrusted application launcher" and does nothing when double-clicked. Mark
it trusted with:
```
chmod +x ~/Desktop/PiClock.desktop
gio set ~/Desktop/PiClock.desktop metadata::trusted true
```
Alternatively, right-click the icon and choose "Allow Launching". Neither is
needed for the `~/.config/autostart` copy, which runs regardless.

#### Autostart Method 2
To have it auto start on boot you need to do one more thing, edit the
crontab file as follows: (it will automatically start nano)  (NOT as root)
```
crontab -e
```
and add the following line:
```
@reboot bash /home/pi/PiClock/startup.sh
```
save the file
and reboot to test
```
sudo reboot
```

### Some notes about startup.sh
startup.sh has a few options:
* -n or --no-delay&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;Don't delay on starting the clock right away (default is 45 seconds delay)
* -d X or --delay X&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;&emsp;Delay X seconds before starting the clock
* -m X or --message-delay X&emsp;&emsp;Delay X seconds while displaying a message on the desktop

Startup also looks for the optional GPIO buttons and only starts the gpio-keys
driver if it has been built. It also checks whether it is already running, and
refrains from starting it again if it is.

### Running the clock as a systemd service

`install.sh` offers this and it is the recommended way to start the clock. A
systemd service restarts the clock if it ever crashes, and gives the web
control panel something it can restart on demand - neither of which the
`~/.config/autostart` shortcut can do.

It installs as a **user** service, not a system one, because the clock is a
fullscreen Qt app that needs the desktop session's display:

```
mkdir -p ~/.config/systemd/user
sed "s|__PICLOCK_DIR__|$HOME/PiClock|g" ~/PiClock/systemd/piclock.service \
    > ~/.config/systemd/user/piclock.service
systemctl --user daemon-reload
systemctl --user enable --now piclock
```

Day to day:
```
systemctl --user status piclock     # is it running?
systemctl --user restart piclock    # restart it
systemctl --user stop piclock       # stop it (F4 does the same)
journalctl --user -u piclock -f     # follow its output
```

**Only one thing may start the clock.** If `~/.config/autostart/PiClock.desktop`
is still present when the service is enabled, both fire at login and two clocks
fight over the display. `install.sh` deletes the autostart entry when you choose
systemd; if you set the service up by hand, remove it yourself:
```
rm -f ~/.config/autostart/PiClock.desktop
```
The desktop icon in `~/Desktop` is fine to keep - that is a manual launch.

Quitting with F4 exits cleanly (status 0), and `Restart=on-failure` leaves that
alone, so a deliberate quit stays quit. Start it again with
`systemctl --user start piclock`. If your display takes a long time to come up
at boot, change `-n` to `-d 15` in the unit's `ExecStart` to make the clock wait
15 seconds before starting.

### Web control panel

An HTTPS page for checking on and controlling the clock from another machine on
your network. It has two pages:

  * **Status** - service state, the clock process, a live screenshot of the
    screen, a log tail and your current settings, all read only
  * **Control** - start, restart and stop the clock, the live commands, and the
    record of who did what and when
  * **Settings** - edit `conf/Config.py`, with backups you can put back

The easiest way to set it up is to run the updater, which offers the whole
thing - certificate, password, `web_enabled = 1`, and the systemd service - and
does only the parts you are missing:

```
bash update.sh
```

It defaults to **no**, because the panel opens a listening socket and an update
should never switch that on by itself. On later runs it leaves a working setup
alone, and just restarts the panel so it picks up the new code.

To do it by hand instead:

```
bash web/make_cert.sh                        # self-signed certificate
venv/bin/python3 web/set_password.py         # the shared password
```

Then set `web_enabled = 1` in `conf/Config.py` and start it:

```
mkdir -p ~/.config/systemd/user
sed "s|__PICLOCK_DIR__|$HOME/PiClock|g" ~/PiClock/systemd/piclock-web.service \
    > ~/.config/systemd/user/piclock-web.service
systemctl --user daemon-reload
systemctl --user enable --now piclock-web
```

Open `https://<your-pi>:8443/`. The certificate is self-signed, so your browser
warns once; accept it and it is remembered. Settings in `conf/Config.py`:

  * `web_enabled` - 1 to enable, 0 to disable (off by default)
  * `web_port` - 8443 by default
  * `web_bind` - `'0.0.0.0'` for every interface, `'127.0.0.1'` for the Pi only
  * `web_session_hours` - how long a sign-in lasts

#### How it is secured

The panel is a way to read - and later change - what the Pi runs, so it has two
independent gates and refuses to start if either is missing.

**It answers private networks only.** RFC 1918 (`10/8`, `172.16/12`,
`192.168/16`) plus loopback, link-local and the IPv6 equivalents. Anything else
gets a 403 before the login page is even rendered, so an outside caller has no
password prompt to attack. This is deliberately based on the real connection
address and **not** on `X-Forwarded-For`, which any caller can set - so putting
a reverse proxy in front of the panel makes every request look like it comes
from the proxy. Don't do that without changing the check to understand your
proxy.

**One shared password**, stored only as a scrypt hash in
`conf/web_secret.json` (mode 0600, never committed). Five wrong guesses locks
that address out for five minutes. Changing the password signs every browser
out, including yours.

**TLS is required.** `web/make_cert.sh` writes a 10 year self-signed
certificate with your hostname and LAN addresses in it, TLS 1.2 is the minimum
version, and the session cookie is `Secure`, `HttpOnly` and `SameSite=Lax`.
Self-signed is worth having: without it the password crosses your LAN in clear
text.

**Credentials are never displayed.** Settings whose names look like secrets are
shown as `********`, and the log tail is scrubbed - PiClock logs the URLs it
fetches and those carry your Mapbox and Tomorrow.io keys.

**Audio streams** can be started and stopped from the Control page and play
through the Pi's own speakers - a NOAA weather feed, a scanner, an internet
radio station. `noaastream` is always offered first; anything else goes in
`audio_streams`:

```python
audio_streams = [
    {'name': 'County fire and EMS', 'url': 'https://example.com/feed.m3u8'},
    {'name': 'Police dispatch', 'url': 'https://example.com/police.m3u8'},
]
```

The Control page also has a **volume slider** for the Pi's output. It uses
whichever mixer the system has - `wpctl` on PipeWire (Raspberry Pi OS Bookworm
and current Ubuntu), then `pactl`, then `amixer` on older ALSA-only images -
and is hidden if none is installed. Moving it also unmutes, since a slider that
does nothing on a muted device just looks broken. It works whether or not the
clock is running, and follows a change made elsewhere within a few seconds.

Only one stream plays at a time - starting another swaps it over.

**While a stream is playing the clock shows a badge near the top** carrying a
play button, a moving equalizer and the stream name. It appears with the
stream and goes away with it - there is no launcher sitting on the clock face
the rest of the time.

**Tapping the badge moves to the next stream, and then stops.** With NOAA
weather radio and a scanner configured, tapping steps from one to the other
and a third tap stops playback, so what is playing can be changed without
reaching for the web panel. Start playback with **F2** or from the panel's
Control page.

The badge stays visible even with the clock face hidden by F9. It sits in the
same slot as the severe weather and aircraft bubbles when that slot is free,
and slides below whichever of them is showing, so it never floats in the
middle of nothing.

On a clock with no touchscreen the taps are no use, so they can be turned off
in `conf/Config.py`:

```
audio_button_enabled = 0   # 1 to make the audio badge tappable, 0 for display only
```

The badge itself looks the same either way; with it off it simply ignores
taps.

**The equalizer follows the actual output**, so it goes flat through the
silence between transmissions on a scanner feed and moves only when there is
something to hear. The audio never passes through the clock - a separate
player decodes it straight to the sound device - so the level is read from a
passive tap on the output sink:

```
parec --format=s16le --rate=8000 --channels=1 -d <default-sink>.monitor
```

That is a listener, not a filter. It observes the output and cannot affect it:
if it stalls or is killed the audio plays on, which is why the level is read
this way rather than by putting a meter inside the player's own pipeline.

It needs `parec` and `pactl`, both from `pulseaudio-utils`, which
pipewire-pulse satisfies on Raspberry Pi OS Bookworm. Without them the bars
fall back to animating whenever a stream is playing, and the log says which
mode it is in at the first play:

```
INFO: equalizer following the output level via alsa_output.<...>.monitor
INFO: no output monitor available (needs parec and pactl); the equalizer
      will animate rather than follow the audio
```

The fallback never claims a silence it cannot detect - it simply moves the
whole time a stream is playing.

**A scanner feed almost always needs more than mpg123.** An `.m3u8` is an HLS
playlist of segments, not an MP3 stream, and mpg123 cannot follow one. PiClock
uses the first of `ffplay`, `mpv`, `cvlc` or `mpg123` that is installed and can
handle the URL.

**Some hosts refuse the player outright.** Broadcastify is one, and it does it
below HTTP: it fingerprints the **TLS handshake**, not anything in the request.
It answers `curl` with 200 and Python's own TLS stack with **403 Forbidden**
for the same URL, from the same address, with byte-identical headers and
HTTP/1.1 forced on both. No User-Agent, Referer or other setting changes it,
because none of those is what it is looking at. That refuses ffmpeg and VLC,
and it refuses `streamlink` too, since streamlink is built on `requests`.

curl is on the accepted side, so PiClock fetches HLS with
`Clock/hls_fetch.py`: it walks the playlist itself, hands every request to
curl, and pipes plain MPEG-TS to ffplay, which then never talks to the host at
all. This is the default whenever curl is installed, which on Raspberry Pi OS
it always is.

**`streamlink` is the fallback**, and worth keeping installed. The small
fetcher covers ordinary HLS - the segment playlists scanner feeds serve - but
not three things streamlink handles:

- AES-128 encrypted segments (`#EXT-X-KEY`)
- fMP4/CMAF init segments (`#EXT-X-MAP`)
- byte-range segments (`#EXT-X-BYTERANGE`)

It recognises all three and stops rather than emitting bytes no player can
decode, and PiClock then **restarts the stream on streamlink by itself** - once
per stream, so a stream neither can play gives up instead of looping. You will
see it in the log:

```
INFO: segments need an fMP4 init segment (#EXT-X-MAP) - needs a fuller HLS client; retrying with streamlink
```

If streamlink is not installed when that happens, the panel says exactly that
rather than reporting a generic stopped stream:

```
sudo apt install streamlink
```

`install.sh` installs `ffmpeg` (which provides `ffplay`), `curl`, `streamlink`
and `mpg123`, and finishes by reporting what the machine can actually play, so
there is normally nothing to do. To add a player later:

```
sudo apt install ffmpeg     # provides ffplay - the smallest of the three
sudo apt install mpv
sudo apt install vlc
```

If none is present the panel says so rather than failing silently. Plain MP3
streams keep working with mpg123 alone.

**The live screenshot** on the Status page shows what is on the clock right
now, which is the difference between guessing and looking when you are working
on a clock in another room. The clock renders its own window rather than
capturing the display, so there is nothing to install and it behaves the same
on X11 and Wayland. Press **Refresh** for a frame, or tick **Keep refreshing**
for one every five seconds - it pauses while the browser tab is in the
background, since each frame is real work for a Pi.

It captures whatever is on screen, **including a camera popup**, so set
`web_screenshot_enabled = 0` in `conf/Config.py` to switch it off.

**Live commands** are the same things the clock's own keys do - next/previous
page, the slideshow controls, hiding the clock, the weather radio - and they
happen on the screen immediately, without a restart. The panel passes them to
the running clock over a channel **bound to 127.0.0.1 only**, so it is not
reachable from the network at all: the panel's TLS, password and
private-address checks are the one front door. Both ends check the command name
against their own list, and the shared secret is generated into
`conf/web_secret.json` by `web/set_password.py` - there is nothing to type in.
Set `web_command_port` if 8128 clashes with something. Quitting the clock is
deliberately not a live command; **Stop** does that through systemd, so it stays
stopped.

**Actions are a fixed list.** Start, restart and stop are entries in a table in
`web/control.py`, each holding the exact command to run. What the browser sends
is only ever a lookup key into that table - it is never put into a command, and
nothing runs through a shell - so a request cannot ask for anything that is not
on the list. Stop and restart also need confirming in the browser.

**Every state-changing request carries a CSRF token** tied to your session, on
top of the `SameSite=Lax` cookie. Stopping the clock is worth two controls.

**Editing settings is the most dangerous thing the panel does**, since
`conf/Config.py` is Python the clock executes. Four things constrain it:

  * only settings whose current value is a plain literal are editable. A
    `LatLng(...)` or `QColor(...)` - your coordinates, the radar blocks, the
    dimming colour - is listed but read only, and still edited by hand;
  * whatever you type goes through `ast.literal_eval` and is written back as
    `repr()` of the result. Nothing survives that round trip except a number,
    string, boolean, `None`, or a container of those, so a value cannot become
    code however it is spelled;
  * a value may not change type - an `int` stays an `int`;
  * the rewritten file is re-parsed and compared against the original, and is
    only saved if the only settings that moved are the ones you changed.

Comments, formatting and line endings are preserved, so the file stays as
readable as you left it. Every save writes a timestamped `Config.py.bak-*`
alongside it, and the Settings page can put any of them back - which also backs
up what was there first. Secrets show as empty password boxes: blank means
unchanged, so they are never rendered into the page. The clock reads its config
at startup, so restart it from **Control** after saving.

**Everything the panel does is recorded** in `logs/panel-audit.db`, a SQLite
file at mode 0600: time, source address, action and outcome, including refused
sign-ins. It is shown at the bottom of the Control page. Configuration
deliberately stays in `conf/Config.py` - a database would not make it any safer
and would lose the comments that document it.

It runs the Werkzeug server, which is right for one user on a LAN but is not a
hardened public web server. Do not expose port 8443 to the internet; reach it
over a VPN if you need it from outside.

### Setting the Pi to auto reboot every day
This is optional but some may want their PiClock to reboot every day.  I do this with mine,
but it is probably not needed.
```
sudo crontab -e
```
add the following line
```
22 3 * * * /sbin/reboot
```
save the file

This sets the reboot to occur at 3:22am every day.   Adjust as needed.

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

You'll want to reboot after the update.

Note: If you get errors because you've made changes to the base code you might need
```
git diff
```
To see your changes, so you can back them up

Then this will update to the current version
```
git reset --hard
```
(This won't bother your Config.py nor ApiKeys.py because they are not tracked in git.)

Also, if you're using gpio-keys, you may need to remake it:
```
cd PiClock/Button
rm gpio-keys
make gpio-keys
```
