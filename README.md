# PiClock Updates and Improvements
Fork of PiClock that uses custom maps from MapBox, for better contrast 
between the weather radar and the maps, with an additional map overlay so that 
rain/snow clouds do not obscure map information, such as labels, borders, and roads.
Also added is text shadows/borders for easier visibility. The original version can be hard to read with certain backgrounds.
Several other UX and language updates have been added, along with several codebase refactorings, including to PyQt6.
Other smaller changes were made to support more streamlined debugging, and enhance data caching to streamline API usages.

This PiClock fork has removed use of OpenWeatherMap in favor of Tomorrow.io. My experience with OWM
was mediocre at best, and although Tomorrow.io supports fewer free API calls, I've found their
forecasting to be better. Additional sources will be added if deemed accurate enough. The analog clock has also been removed. 
The digital display looks much sleaker and I didn't intend to support it for my own purposes.

### What this fork adds
  * **Severe weather alerts** - a warning bar for active NOAA/NWS alerts, with
    a scrolling headline; click or tap it for the full alert text and
    instructions. See [Install.md](Documentation/Install.md#severe-weather-alerts).
  * **Day/night screen brightness** - dims the display on a 24-hour schedule
    you configure, with a gradual fade between day and night.
  * **Always-on display** - best-effort suppression of the OS screensaver,
    screen blanking, and sleep on Windows, macOS, and Linux (X11 and Wayland).
  * **Slideshow from a web playlist or a shared iCloud album** - point PiClock
    at a text file of image URLs, or at an iCloud album so photos you add from
    your phone show up on the clock. Crossfade transitions between images.
  * **Scripted install** - `install.sh` (Linux/macOS) and `install.bat`
    (Windows) set up the virtualenv, packages, fonts, and config interactively.
  * **Pressure trend arrow**, cursor auto-hide, a short-lived on-disk API cache,
    and optional daily log rotation.

## Original PiClock (https://github.com/n0bel/PiClock)
Thanks to N0BEL for the original codebase. I've been running a PiClock in one fashion or another for over a decade.
Additional thanks to SerBrynden for the Python3 and PyQt5 updates. This repository is originally forked from his fork.
A Fancy Clock built around a monitor and a Raspberry Pi

![PiClock Picture](Pictures/20150307_222711.jpg)

This project started out as a way to waste a Saturday afternoon.
I had a Raspberry Pi and an extra monitor and had just taken down an analog clock from my living room wall.
I was contemplating getting a radio sync'ed analog clock to replace it, so I didn't have to worry about
it being accurate.

But instead the PiClock was born.

The early days and evolution of it are chronicled on my blog:
[NØBEL Blog - Raspberry Pi Clock](http://n0bel.net/v1/index.php/projects/raspberry-pi-clock)

If you want to build your own, I'd suggest starting with the overview:
[Overview of the PiClock](Documentation/Overview.md)

To install the PiClock on your Raspberry Pi, follow these instructions (all the extra hardware (IR Remote, GPIO buttons, Temperature, LEDs) are optional):
[Install Instructions for PiClock](Documentation/Install.md)

If you want to use the PiClock on a different desktop (not your Raspberry Pi), I'd suggest using these instructions:
[Install Instructions for PiClock (Clock Only)](Documentation/Install-Clock-Only.md)

Of course, you can jump to the hardware guide anytime:
[PiClock Hardware Guide](Documentation/Hardware.md)
