#!/bin/bash
# Installer for PiClock - standard software-only setup.
# Sets up the virtual environment, Python packages, and config files needed
# to run the clock, weather, radar, slideshow, and NOAA alert/radio features.
# Does NOT set up the optional GPIO buttons - see Documentation/Install.md if
# you need those.

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
  local CFG="conf/Config.py"
  local KEYS="conf/ApiKeys.py"
  local REPLY LAT LON TMAPI MAPCHOICE MBAPI GOOGLEAPI NOAASTREAM SLIDECHOICE SLIDEURL ICLOUDALBUM
  local MAPBASE MAPOVERLAY
  local DIM_ENABLE DAYBRIGHT NIGHTBRIGHT DAYSTART NIGHTSTART TRANSMIN KEEPAWAKE

  # Example numbers for the lat/lon prompts, regenerated each run so a real
  # address is never hardcoded into this script.
  local EXAMPLE_LAT EXAMPLE_LON
  EXAMPLE_LAT="$(( (RANDOM % 180) - 90 )).$(printf '%04d' $((RANDOM % 10000)))"
  EXAMPLE_LON="$(( (RANDOM % 360) - 180 )).$(printf '%04d' $((RANDOM % 10000)))"

  echo ""
  echo "--- Location ---"
  while true; do
    read -r -p "Latitude (decimal degrees, e.g. $EXAMPLE_LAT): " LAT
    [[ "$LAT" =~ ^-?[0-9]+(\.[0-9]+)?$ ]] && break
    echo "Please enter a valid decimal number."
  done
  while true; do
    read -r -p "Longitude (decimal degrees, e.g. $EXAMPLE_LON): " LON
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

      read -r -p "Custom Mapbox base map style (e.g. username/style-id, blank for Mapbox's default satellite style): " MAPBASE
      if [ -n "$MAPBASE" ]; then
        set_py_line "$CFG" '^map_base *=' "map_base = $(py_quote "$MAPBASE")  # blank uses Mapbox's default 'mapbox/satellite-streets-v12'; or your own custom style, see below"
      fi
      read -r -p "Custom Mapbox overlay style, e.g. for labels/roads/borders (blank to disable): " MAPOVERLAY
      if [ -n "$MAPOVERLAY" ]; then
        set_py_line "$CFG" '^map_overlay *=' "map_overlay = $(py_quote "$MAPOVERLAY")  # optional custom overlay style (labels/roads/borders only); blank disables the overlay"
      fi
      echo "See conf/Config.py (map_base/map_overlay, radar1-4) to customize further."
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
    echo "3) Shared iCloud album"
    read -r -p "Choose a slideshow source [1]: " SLIDECHOICE
    SLIDECHOICE=${SLIDECHOICE:-1}
    if [ "$SLIDECHOICE" = "2" ]; then
      set_py_line "$CFG" '^web_slideshow_playlist *=' "web_slideshow_playlist = 1"
      read -r -p "Slideshow playlist URL: " SLIDEURL
      if [ -n "$SLIDEURL" ]; then
        set_py_line "$CFG" '^slideshow_url *=' "slideshow_url = $(py_quote "$SLIDEURL") # must be text file, one image url per line"
      fi
    elif [ "$SLIDECHOICE" = "3" ]; then
      set_py_line "$CFG" '^web_slideshow_playlist *=' "web_slideshow_playlist = 2"
      echo "In Photos: create an album, share it, turn on 'Public Website', and copy the link."
      echo "Anyone with that link can view the album, so don't use it for private photos."
      while true; do
        read -r -p "Shared iCloud album link: " ICLOUDALBUM
        [ -z "$ICLOUDALBUM" ] && break
        case "$ICLOUDALBUM" in
          *sharedalbum*\#?*|\#?*)
            set_py_line "$CFG" '^slideshow_icloud_album *=' "slideshow_icloud_album = $(py_quote "$ICLOUDALBUM")"
            break
            ;;
          *)
            echo "That doesn't look like a share link. Expected something like"
            echo "  https://www.icloud.com/sharedalbum/#B0Xabc123"
            ;;
        esac
      done
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
  echo "--- Aircraft overhead ---"
  echo "Shows a bubble when a plane passes overhead. Uses airplanes.live, a"
  echo "volunteer-run ADS-B feed - no account needed, but it is their bandwidth."
  read -r -p "Enable the aircraft overhead bubble? [y/N] " REPLY
  if [ "$REPLY" = "y" ] || [ "$REPLY" = "Y" ]; then
    set_py_line "$CFG" '^flights_enabled *=' "flights_enabled = 1  # 1 to enable, 0 to disable"
  else
    set_py_line "$CFG" '^flights_enabled *=' "flights_enabled = 0  # 1 to enable, 0 to disable"
  fi

  echo ""
  echo "--- Screen Brightness ---"
  read -r -p "Automatically dim the display at night? [Y/n] " DIM_ENABLE
  if [ "$DIM_ENABLE" = "n" ] || [ "$DIM_ENABLE" = "N" ]; then
    set_py_line "$CFG" '^brightness_enabled *=' "brightness_enabled = 0  # 1 to enable time-based dimming, 0 to always use day_brightness"
  else
    set_py_line "$CFG" '^brightness_enabled *=' "brightness_enabled = 1  # 1 to enable time-based dimming, 0 to always use day_brightness"

    while true; do
      read -r -p "Daytime brightness percentage (0-100) [100]: " DAYBRIGHT
      DAYBRIGHT=${DAYBRIGHT:-100}
      [[ "$DAYBRIGHT" =~ ^[0-9]+$ ]] && [ "$DAYBRIGHT" -le 100 ] && break
      echo "Please enter a whole number from 0 to 100."
    done
    set_py_line "$CFG" '^day_brightness *=' "day_brightness = $DAYBRIGHT  # 0-100, brightness percentage during the day"

    while true; do
      read -r -p "Nighttime brightness percentage (0-100) [30]: " NIGHTBRIGHT
      NIGHTBRIGHT=${NIGHTBRIGHT:-30}
      [[ "$NIGHTBRIGHT" =~ ^[0-9]+$ ]] && [ "$NIGHTBRIGHT" -le 100 ] && break
      echo "Please enter a whole number from 0 to 100."
    done
    set_py_line "$CFG" '^night_brightness *=' "night_brightness = $NIGHTBRIGHT  # 0-100, brightness percentage at night"

    while true; do
      read -r -p "Time day brightness begins, 24-hour HH:MM [07:00]: " DAYSTART
      DAYSTART=${DAYSTART:-07:00}
      [[ "$DAYSTART" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] && break
      echo "Please enter a time as HH:MM using a 24-hour clock, e.g. 07:00."
    done
    set_py_line "$CFG" '^day_start *=' "day_start = $(py_quote "$DAYSTART")  # 24-hour clock (HH:MM) when day_brightness begins"

    while true; do
      read -r -p "Time night brightness begins, 24-hour HH:MM [22:00]: " NIGHTSTART
      NIGHTSTART=${NIGHTSTART:-22:00}
      [[ "$NIGHTSTART" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]] && break
      echo "Please enter a time as HH:MM using a 24-hour clock, e.g. 22:00."
    done
    set_py_line "$CFG" '^night_start *=' "night_start = $(py_quote "$NIGHTSTART")  # 24-hour clock (HH:MM) when night_brightness begins"

    while true; do
      read -r -p "Minutes to fade gradually between day/night brightness, 0 for instant [30]: " TRANSMIN
      TRANSMIN=${TRANSMIN:-30}
      [[ "$TRANSMIN" =~ ^[0-9]+$ ]] && break
      echo "Please enter a whole number of minutes."
    done
    set_py_line "$CFG" '^brightness_transition_minutes *=' "brightness_transition_minutes = $TRANSMIN  # minutes to gradually fade between day/night brightness; 0 for an instant switch"
  fi

  read -r -p "Keep the display always on (prevent OS screensaver/sleep while PiClock runs)? [Y/n] " KEEPAWAKE
  if [ "$KEEPAWAKE" = "n" ] || [ "$KEEPAWAKE" = "N" ]; then
    set_py_line "$CFG" '^prevent_screen_sleep *=' "prevent_screen_sleep = 0  # 1 to enable, 0 to disable"
  else
    set_py_line "$CFG" '^prevent_screen_sleep *=' "prevent_screen_sleep = 1  # 1 to enable, 0 to disable"
  fi

  echo ""
  echo "Configuration saved to conf/Config.py and conf/ApiKeys.py."
}

# Best-effort: disables GNOME's idle screen blanking, auto-lock, and
# auto-dim, so an always-on display doesn't fight with PiClock's own
# brightness/sleep-prevention settings. No-op if gsettings isn't present
# (e.g. non-GNOME desktops, headless installs).
configure_gnome_idle() {
  command -v gsettings >/dev/null 2>&1 || return 0

  echo ""
  echo "--- Always-on display (GNOME) ---"
  read -r -p "Disable GNOME idle screen blanking, auto-lock, and auto-dim? [Y/n] " REPLY
  if [ "$REPLY" = "n" ] || [ "$REPLY" = "N" ]; then
    return 0
  fi

  gsettings set org.gnome.desktop.session idle-delay 0 2>/dev/null || true
  gsettings set org.gnome.desktop.screensaver lock-enabled false 2>/dev/null || true
  gsettings set org.gnome.settings-daemon.plugins.power ambient-enabled false 2>/dev/null || true
  gsettings set org.gnome.settings-daemon.plugins.power idle-dim false 2>/dev/null || true
  echo "GNOME idle blanking, lock, and auto-dim disabled."
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
  # ffmpeg supplies ffplay, which is what plays a scanner or internet radio
  # feed: those are nearly always .m3u8, and mpg123 cannot follow an HLS
  # playlist. mpg123 stays for plain MP3 streams like NOAA weather radio.
  read -r -p "Install/update system packages (python3-full, python3-pyqt6, mpg123, ffmpeg) via apt? [Y/n] " REPLY
  if [ "$REPLY" != "n" ] && [ "$REPLY" != "N" ]; then
    sudo apt update
    sudo apt install -y python3-full python3-pyqt6 mpg123 ffmpeg
    USE_SYSTEM_SITE_PACKAGES=1
  fi
elif [ "$OS_NAME" = "Darwin" ] && command -v brew >/dev/null 2>&1; then
  echo ""
  read -r -p "Install mpg123 and ffmpeg via Homebrew (for the audio streams)? [Y/n] " REPLY
  if [ "$REPLY" != "n" ] && [ "$REPLY" != "N" ]; then
    brew install mpg123 ffmpeg
  fi
fi

# Whatever route was taken - apt, brew, declined, or a distribution without
# either - say plainly what can be played, because the failure otherwise turns
# up much later as a scanner feed that silently will not start.
report_audio_players() {
  HAVE_MP3=""
  HAVE_HLS=""
  command -v mpg123 >/dev/null 2>&1 && HAVE_MP3="mpg123"
  for PLAYER in ffplay mpv cvlc; do
    if command -v "$PLAYER" >/dev/null 2>&1; then
      HAVE_HLS="$PLAYER"
      break
    fi
  done

  echo ""
  if [ -n "$HAVE_HLS" ]; then
    echo "Audio: MP3 and .m3u8 (HLS) streams can both be played ($HAVE_HLS found)."
  elif [ -n "$HAVE_MP3" ]; then
    echo "Audio: MP3 streams can be played (mpg123 found), but .m3u8 (HLS)"
    echo "       feeds - most police/fire/EMS scanners - cannot."
    echo "       Install one of these to enable them:"
    echo "         sudo apt install ffmpeg     # or mpv, or vlc"
  else
    echo "Audio: no player found, so no streams can be played."
    echo "       Install one with: sudo apt install ffmpeg mpg123"
  fi
}

report_audio_players

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

if [ ! -f "conf/ApiKeys.py" ]; then
  cp conf/ApiKeys-example.py conf/ApiKeys.py
  NEW_APIKEYS=1
  echo ""
  echo "Created conf/ApiKeys.py from the example."
else
  echo ""
  echo "conf/ApiKeys.py already exists, leaving it alone."
fi

if [ ! -f "conf/Config.py" ]; then
  cp conf/Config-Example.py conf/Config.py
  NEW_CONFIG=1
  echo "Created conf/Config.py from the example."
else
  echo "conf/Config.py already exists, leaving it alone."
fi

echo ""
if [ "$NEW_APIKEYS" = "1" ] || [ "$NEW_CONFIG" = "1" ]; then
  read -r -p "Interactively configure your API keys and Config.py settings now? [Y/n] " REPLY
  if [ "$REPLY" != "n" ] && [ "$REPLY" != "N" ]; then
    configure_piclock
  fi
else
  read -r -p "conf/ApiKeys.py and/or conf/Config.py already exist. Interactively reconfigure them now? [y/N] " REPLY
  if [ "$REPLY" = "y" ] || [ "$REPLY" = "Y" ]; then
    configure_piclock
  fi
fi

chmod +x startup.sh update.sh PiClock.desktop 2>/dev/null || true

install_autostart_entry() {
  mkdir -p "$HOME/.config/autostart"
  AUTOSTART_SHORTCUT="$HOME/.config/autostart/PiClock.desktop"
  ln -f PiClock.desktop "$AUTOSTART_SHORTCUT" 2>/dev/null || cp -f PiClock.desktop "$AUTOSTART_SHORTCUT"
  chmod +x "$AUTOSTART_SHORTCUT" 2>/dev/null || true
  echo "Auto start set up via ~/.config/autostart"
}

install_systemd_service() {
  # A user service, not a system one: the clock needs the desktop session's
  # display, which only the logged-in user's systemd instance is ordered after.
  UNIT_DIR="$HOME/.config/systemd/user"
  mkdir -p "$UNIT_DIR"
  # Substituted in bash rather than with sed, because a path containing & or |
  # would be mangled by sed's replacement syntax.
  UNIT_TEXT="$(cat systemd/piclock.service)"
  printf '%s\n' "${UNIT_TEXT//__PICLOCK_DIR__/$SCRIPT_DIR}" > "$UNIT_DIR/piclock.service"

  systemctl --user daemon-reload
  if systemctl --user enable --now piclock.service 2>/dev/null; then
    echo "piclock.service installed and started."
  else
    # enable --now fails when run over ssh with no session bus; the unit is
    # still written and will come up at the next graphical login.
    systemctl --user enable piclock.service 2>/dev/null || true
    echo "piclock.service installed. It starts at your next graphical login."
  fi

  # Both mechanisms firing would launch two clocks fighting over the display,
  # so the autostart entry goes when systemd takes over. The desktop icon is
  # left alone - that is a manual launch, not an automatic one.
  if [ -e "$HOME/.config/autostart/PiClock.desktop" ]; then
    rm -f "$HOME/.config/autostart/PiClock.desktop"
    echo "Removed the old ~/.config/autostart entry so only systemd starts the clock."
  fi

  echo ""
  echo "  systemctl --user status piclock    # is it running?"
  echo "  systemctl --user restart piclock   # restart it"
  echo "  journalctl --user -u piclock -f    # follow its output"
}

if [ "$OS_NAME" = "Linux" ] && [ -n "$XDG_CURRENT_DESKTOP$DISPLAY" ]; then
  echo ""
  read -r -p "Set up the desktop icon and auto start on login/reboot? [y/N] " REPLY
  if [ "$REPLY" = "y" ] || [ "$REPLY" = "Y" ]; then
    mkdir -p "$HOME/Desktop"
    DESKTOP_SHORTCUT="$HOME/Desktop/PiClock.desktop"

    # Prefer a hard link (edits to PiClock.desktop then apply everywhere), but
    # that fails when ~/Desktop is on another filesystem, so fall back to a copy.
    ln -f PiClock.desktop "$DESKTOP_SHORTCUT" 2>/dev/null || cp -f PiClock.desktop "$DESKTOP_SHORTCUT"
    chmod +x "$DESKTOP_SHORTCUT" 2>/dev/null || true
    echo "PiClock.desktop installed to ~/Desktop"

    # systemd restarts the clock if it dies and lets the web control panel
    # restart it on demand, so it is preferred wherever it is available. The
    # autostart .desktop entry is the fallback for systems without it.
    if command -v systemctl >/dev/null 2>&1; then
      echo ""
      read -r -p "Start the clock with systemd (restarts it if it crashes)? [Y/n] " REPLY
      if [ "$REPLY" = "n" ] || [ "$REPLY" = "N" ]; then
        install_autostart_entry
      else
        install_systemd_service
      fi
    else
      echo "systemctl not found."
      install_autostart_entry
    fi

    # GNOME 42+ (Ubuntu 22.04 and newer, Raspberry Pi OS with GNOME) refuses to
    # launch a desktop shortcut until it is both executable and marked trusted;
    # without this the icon shows as "Untrusted application launcher".
    if command -v gio >/dev/null 2>&1; then
      if gio set "$DESKTOP_SHORTCUT" metadata::trusted true 2>/dev/null; then
        echo "Desktop shortcut marked trusted."
      else
        echo "NOTE: could not mark the desktop shortcut trusted (not supported here)."
        echo "      If the icon shows as untrusted, right-click it and choose"
        echo "      'Allow Launching'."
      fi
    else
      echo "NOTE: 'gio' not found, so the desktop shortcut was not marked trusted."
      echo "      On GNOME, right-click the icon and choose 'Allow Launching'."
    fi
  fi

  configure_gnome_idle
fi

echo ""
echo "=== Install complete ==="
echo "Next steps:"
echo "  1. Double check conf/ApiKeys.py and conf/Config.py have what you expect."
echo "     (Rerun this script if you skipped the interactive configuration.)"
echo "  2. Test it: bash startup.sh -n -s"
echo ""
echo "See Documentation/Install.md or Documentation/Install-Clock-Only.md for details."
