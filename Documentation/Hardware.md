# PiClock Hardware Guide

## Introduction

I'm going to assume you know how to connect your Raspberry Pi, Power supply, Monitor, 
keyboard/mouse and Wi-Fi or Wired Ethernet.

What follows is the details of the optional hardware you can add to your Raspi
to add features or make your clock cooler.

If you want to experiment and learn about the hardware, and possibly breadboard
it first, I've included some decent guides for that. *However, you can just skip to the
picture showing the hookup for the PiClock.*

## Raspberry Pi Models

This hardware guide directly supports the following

* Raspberry Pi Revision 2 Model B
* Raspberry Pi Revision 2 Model B
* Raspberry Pi Model B+
* Raspberry Pi 2 Model B

Changes can be made, alternate pins (grounds/gpios) can be used to support
other models, but this is left as an exercise for the reader.


## GPIO Buttons

Up to 3 simple push button switches come preconfigured in the software. The switches are
wired simply to connect a gpio pin to ground when pushed. The following line
in startup.sh configure their function, and which GPIO they are located on.
```
sudo Button/gpio-keys 23:KEY_SPACE 24:KEY_F2 25:KEY_UP &
```
 * GPIO23 (header pin 16) is mapped to a space (which flips pages on the clock).
 * GPIO24 (header pin 18) is mapped to F2 (which toggles the NOAA stream)
 * GPIO25 (header pin 22) is mapped to UP (which does nothing yet)
 * A convenient ground is on header pin 20.
 
![PiClock Picture](gpiobuttons.jpg)


## Schematic of all connections

For those that want to work from a schematic, I threw together a simple one.
It dates from when PiClock also supported an IR remote receiver, DS18B20
temperature probes and a NeoPixel ambilight strip, so it shows those parts too
- ignore everything but the buttons.

![PiClock Picture](Hardware_Schematic.png)



