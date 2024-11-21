# PiClock Updates and Improvements

Fork of PiClock that uses custom maps from MapBox, for better contrast 
between the weather radar and the maps, with an additional map overlay so that 
rain/snow clouds do not obscure map information, such as labels, borders, and roads.
Also added is text shadows/borders for easier visibility. THe original version can be hard to read with certain backgrounds.
Several other UX and language updates have been added, along with the ability to specify remote images for a slideshow.

This PiClock fork is removing use of OpenWeatherMaps. Current PiClock support doesn't use v3 and my experience with OWM
has been mediocore at best. All code will be directed for use with Tomorrow.io. Although they support less free API calls,
I've found their forecasting to be better. Additional sources will be added if deemed accurate enough.

## Original PiClock (https://github.com/n0bel/PiClock)
## Thanks to N0BEL for the original codebase. I've been running a PiClock in one fashion or another for almost a decade.
## Additional thanks to SerBrynden for the Python3 and PyQt5 updates. This repository is originally forked from his PiClock fork.
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
