#!/bin/bash
# Installer for PiClock - standard software-only setup.
# Sets up the virtual environment, Python packages, and config files needed
# to run the clock, weather, radar, slideshow, and NOAA alert/radio features.
# Does NOT set up optional hardware add-ons (GPIO buttons, IR remote,
# temperature sensors, NeoPixel LEDs) - see Documentation/Install.md if you
# need those.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$SCRIPT_DIR" || exit 1

# A rare delimiter for sed, so URLs/keys containing '/' don't break the substitution.
SED_DELIM=$'\001'

# Replaces the whole line matching $2 (an extended-regex anchor, e.g. '^tmapi *=')
# in file $1 with the literal text $3. No-op if no line matches.
set_py_line() {
  local file="$1" anchor="$2" replacement="$3"
  local esc
  esc=$(printf '%s' "$replacement" | sed -e 's/\\/\\\\/g' -e 's/&/\\\&/g')
  sed -E -i.bak "s${SED_DELIM}${anchor}.*${SED_DELIM}${esc}${SED_DELIM}" "$file"
  rm -f "${file}.bak"
}

# Builds a safely-escaped Python double-quoted string literal from arbitrary input.
py_quote() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  printf '"%s"' "$s"
}

configure_piclock() {
  local CFG="Clock/Config.py"
  local KEYS="Clock/ApiKeys.py"
  local REPLY LAT LON TMAPI MAPCHOICE MBAPI GOOGLEAPI NOAASTREAM SLIDECHOICE SLIDEURL

  echo ""
  echo "--- Location ---"
  while true; do
    read -r -p "Latitude (decimal degrees, e.g. 42.8045): " LAT
    [[ "$LAT" =~ ^-?[0-9]+(\.[0-9]+)?$ ]] && break
    echo "Please enter a valid decimal number."
  done
  while true; do
    read -r -p "Longitude (decimal degrees, e.g. -77.7871): " LON
    [[ "$LON" =~ ^-?[0-9]+(\.[0-9]+)?$ ]] && break
    echo "Please enter a valid decimal number."
  done
  set_py_line "$CFG" '^primary_coordinates *=' "primary_coordinates = $LAT, $LON  # Change to your Lat/Lon"

  echo ""
  echo "--- Units ---"
  read -r -p "Use metric units instead of imperial? [y/N] " REPLY
  if [ "$REPLY" = "y" ] || [ "$REPLY" = "Y" ]; then
    set_py_line "$CFG" '^metric *=' "metric = 1  # 0 = English, 1 = Metric"
  else
    set_py_line "$CFG" '^metric *=' "metric = 0  # 0 = English, 1 = Metric"
  fi

  echo ""
  echo "--- Weather ---"
  read -r -p "Tomorrow.io API key (https://www.tomorrow.io/weather-api/, blank to skip): " TMAPI
  if [ -n "$TMAPI" ]; then
    set_py_line "$KEYS" '^#? *tmapi *=' "tmapi = $(py_quote "$TMAPI")"
  fi

  echo ""
  echo "--- Maps ---"
  echo "1) Mapbox (recommended - supports custom map styles)"
  echo "2) Google Maps"
  read -r -p "Choose a map provider [1]: " MAPCHOICE
  MAPCHOICE=${MAPCHOICE:-1}
  if [ "$MAPCHOICE" = "2" ]; then
    read -r -p "Google Maps API key (blank to skip): " GOOGLEAPI
    if [ -n "$GOOGLEAPI" ]; then
      set_py_line "$KEYS" '^#? *googleapi *=' "googleapi = $(py_quote "$GOOGLEAPI")"
    fi
  else
    read -r -p "Mapbox access token (https://www.mapbox.com/signup/, blank to skip): " MBAPI
    if [ -n "$MBAPI" ]; then
      set_py_line "$KEYS" '^#? *mbapi *=' "mbapi = $(py_quote "$MBAPI")"
      echo "Using the default Mapbox satellite style; see Clock/Config.py (map_base/map_overlay, radar1-4) to customize further."
    fi
  fi

  echo ""
  echo "--- NOAA weather radio stream (F2 key) ---"
  read -r -p "NOAA weather radio stream URL (blank to keep default): " NOAASTREAM
  if [ -n "$NOAASTREAM" ]; then
    set_py_line "$CFG" '^noaastream *=' "noaastream = $(py_quote "$NOAASTREAM") # Change to local NOAA stream"
  fi

  echo ""
  echo "--- Slideshow ---"
  read -r -p "Enable background slideshow? [Y/n] " REPLY
  if [ "$REPLY" = "n" ] || [ "$REPLY" = "N" ]; then
    set_py_line "$CFG" '^useslideshow *=' "useslideshow = 0  # 1 to enable, 0 to disable"
  else
    set_py_line "$CFG" '^useslideshow *=' "useslideshow = 1  # 1 to enable, 0 to disable"
    echo "1) Local images from PiClock/Pictures/Slideshow"
    echo "2) Web playlist (a URL to a text file listing one image URL per line)"
    read -r -p "Choose a slideshow source [1]: " SLIDECHOICE
    SLIDECHOICE=${SLIDECHOICE:-1}
    if [ "$SLIDECHOICE" = "2" ]; then
      set_py_line "$CFG" '^web_slideshow_playlist *=' "web_slideshow_playlist = 1"
      read -r -p "Slideshow playlist URL: " SLIDEURL
      if [ -n "$SLIDEURL" ]; then
        set_py_line "$CFG" '^slideshow_url *=' "slideshow_url = $(py_quote "$SLIDEURL") # must be text file, one image url per line"
      fi
    else
      set_py_line "$CFG" '^web_slideshow_playlist *=' "web_slideshow_playlist = 0"
    fi
  fi

  echo ""
  echo "--- Severe weather alerts ---"
  read -r -p "Enable NOAA/NWS severe weather alert bubble? [Y/n] " REPLY
  if [ "$REPLY" = "n" ] || [ "$REPLY" = "N" ]; then
    set_py_line "$CFG" '^noaa_alerts_enabled *=' "noaa_alerts_enabled = 0  # 1 to show a warning bubble for active NOAA/NWS alerts, 0 to disable"
  else
    set_py_line "$CFG" '^noaa_alerts_enabled *=' "noaa_alerts_enabled = 1  # 1 to show a warning bubble for active NOAA/NWS alerts, 0 to disable"
  fi

  echo ""
  echo "Configuration saved to Clock/Config.py and Clock/ApiKeys.py."
}

echo "=== PiClock Installer ==="

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. Please install Python 3 first."
  exit 1
fi

OS_NAME="$(uname -s)"
USE_SYSTEM_SITE_PACKAGES=0

if [ "$OS_NAME" = "Linux" ] && command -v apt-get >/dev/null 2>&1; then
  echo ""
  echo "Detected a Debian/Raspberry Pi OS based Linux system."
  read -r -p "Install/update system packages (python3-full, python3-pyqt6, mpg123) via apt? [Y/n] " REPLY
  if [ "$REPLY" != "n" ] && [ "$REPLY" != "N" ]; then
    sudo apt update
    sudo apt install -y python3-full python3-pyqt6 mpg123
    USE_SYSTEM_SITE_PACKAGES=1
  fi
elif [ "$OS_NAME" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
  echo ""
  read -r -p "Install mpg123 via Homebrew (needed for the NOAA weather radio stream)? [Y/n] " REPLY
  if [ "$REPLY" != "n" ] && [ "$REPLY" != "N" ]; then
    brew install mpg123
  fi
fi

if [ -f "venv/bin/activate" ]; then
  echo ""
  echo "Virtual environment already exists, reusing it."
else
  echo ""
  echo "Creating virtual environment..."
  if [ "$USE_SYSTEM_SITE_PACKAGES" = "1" ]; then
    python3 -m venv --system-site-packages venv
  else
    python3 -m venv venv
  fi
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo ""
echo "Upgrading pip..."
python3 -m pip install --upgrade pip

if [ "$USE_SYSTEM_SITE_PACKAGES" != "1" ]; then
  echo ""
  echo "Installing PyQt6..."
  python3 -m pip install PyQt6
fi

echo ""
echo "Installing required Python packages..."
python3 -m pip install -r requirements.txt

deactivate

FONT_FILES=(fonts/*.ttf)
if [ -e "${FONT_FILES[0]}" ]; then
  echo ""
  echo "Installing bundled fonts..."
  if [ "$OS_NAME" = "Darwin" ]; then
    FONT_DEST="$HOME/Library/Fonts"
    mkdir -p "$FONT_DEST"
    cp -f "${FONT_FILES[@]}" "$FONT_DEST/"
    echo "Fonts copied to $FONT_DEST"
  elif [ "$OS_NAME" = "Linux" ]; then
    FONT_DEST="$HOME/.local/share/fonts/PiClock"
    mkdir -p "$FONT_DEST"
    cp -f "${FONT_FILES[@]}" "$FONT_DEST/"
    if command -v fc-cache >/dev/null 2>&1; then
      fc-cache -f "$FONT_DEST" >/dev/null 2>&1
    fi
    echo "Fonts copied to $FONT_DEST"
  fi
fi

NEW_APIKEYS=0
NEW_CONFIG=0

if [ ! -f "Clock/ApiKeys.py" ]; then
  cp Clock/ApiKeys-example.py Clock/ApiKeys.py
  NEW_APIKEYS=1
  echo ""
  echo "Created Clock/ApiKeys.py from the example."
else
  echo ""
  echo "Clock/ApiKeys.py already exists, leaving it alone."
fi

if [ ! -f "Clock/Config.py" ]; then
  cp Clock/Config-Example.py Clock/Config.py
  NEW_CONFIG=1
  echo "Created Clock/Config.py from the example."
else
  echo "Clock/Config.py already exists, leaving it alone."
fi

echo ""
if [ "$NEW_APIKEYS" = "1" ] || [ "$NEW_CONFIG" = "1" ]; then
  read -r -p "Interactively configure your API keys and Config.py settings now? [Y/n] " REPLY
  if [ "$REPLY" != "n" ] && [ "$REPLY" != "N" ]; then
    configure_piclock
  fi
else
  read -r -p "Clock/ApiKeys.py and/or Clock/Config.py already exist. Interactively reconfigure them now? [y/N] " REPLY
  if [ "$REPLY" = "y" ] || [ "$REPLY" = "Y" ]; then
    configure_piclock
  fi
fi

chmod +x startup.sh switcher.sh update.sh PiClock.desktop 2>/dev/null || true

if [ "$OS_NAME" = "Linux" ] && [ -n "$XDG_CURRENT_DESKTOP$DISPLAY" ]; then
  echo ""
  read -r -p "Set up PiClock to auto start on login/reboot? [y/N] " REPLY
  if [ "$REPLY" = "y" ] || [ "$REPLY" = "Y" ]; then
    mkdir -p "$HOME/Desktop" "$HOME/.config/autostart"
    ln -f PiClock.desktop "$HOME/Desktop/PiClock.desktop"
    ln -f PiClock.desktop "$HOME/.config/autostart/PiClock.desktop"
    echo "PiClock.desktop linked to ~/Desktop and ~/.config/autostart"
  fi
fi

echo ""
echo "=== Install complete ==="
echo "Next steps:"
echo "  1. Double check Clock/ApiKeys.py and Clock/Config.py have what you expect."
echo "     (Rerun this script if you skipped the interactive configuration.)"
echo "  2. Test it: bash startup.sh -n -s"
echo ""
echo "See Documentation/Install.md or Documentation/Install-Clock-Only.md for details."
