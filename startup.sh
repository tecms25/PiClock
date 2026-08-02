#!/bin/bash
# Startup script for the PiClock
# Designed to be started from PiClock.desktop (autostart)
# or alternatively from crontab as follows
#@reboot bash /home/pi/PiClock/startup.sh

#
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
cd "$SCRIPT_DIR" || exit

#
if [ "$DISPLAY" = "" ]; then
  export DISPLAY=:0
fi

# wait for Xwindows and the desktop to start up
MSG="echo Waiting 45 seconds before starting"
DELAY="sleep 45"
if [ "$1" = "-n" ] || [ "$1" = "--no-sleep" ] || [ "$1" = "--no-delay" ]; then
  MSG=""
  DELAY=""
  shift
fi
if [ "$1" = "-d" ] || [ "$1" = "--delay" ]; then
  MSG="echo Waiting $2 seconds before starting"
  DELAY="sleep $2"
  shift
  shift
fi
if [ "$1" = "-m" ] || [ "$1" = "--message-delay" ]; then
  MSG="echo Waiting $2 seconds for response before starting"
  #DELAY="xmessage -buttons Now:0,Cancel:1 -default Now -timeout $2 Starting PiClock in $2 seconds"
  DELAY='zenity --question --title PiClock --ok-label=Now --cancel-label=Cancel --timeout '$2' --text "Starting PiClock in '$2' seconds" >/dev/null 2>&1'
  shift
  shift
fi

$MSG
eval "$DELAY"
if [ $? -eq 1 ]; then
  echo "PiClock Cancelled"
  exit 0
fi

#xmessage -timeout 5 Starting PiClock... &
zenity --info --timeout 3 --text "Starting PiClock..." >/dev/null 2>&1 &

# stop screen blanking (xset is X11-only; skip on non-Linux dev machines and
# on Wayland sessions, where xset has no effect and may just error out)
if [ "$(uname -s)" = "Linux" ] && [ -z "$WAYLAND_DISPLAY" ] && [ "$XDG_SESSION_TYPE" != "wayland" ]; then
  echo "Disabling screen blanking..."
  xset s off
  xset -dpms
  xset s noblank
fi

# echo "Setting sound to max (assuming Monitor Tv controls volume)..."
# push sound level to maximum
# amixer cset numid=1 -- 400 >/dev/null 2>&1

# virtual environment
echo "Activating virtual environment..."
source venv/bin/activate || exit

echo "Checking for GPIO Buttons..."
# gpio button to keyboard input (Button/gpio-keys is a compiled ARM/Linux
# binary; skip it on non-Linux dev machines where it can't execute at all)
if [ "$(uname -s)" = "Linux" ] && [ -x Button/gpio-keys ]; then
  pgrep -f gpio-keys
  if [ $? -eq 1 ]; then
    echo "Starting gpio-keys Service..."
    Button/gpio-keys 23:KEY_SPACE 24:KEY_F2 25:KEY_UP &
  fi
fi

# the main app
cd Clock || exit
if [ "$1" = "-s" ] || [ "$1" = "--screen-log" ]; then
  echo "Starting PiClock... logging to screen."
  python3 -u PyQtPiClock.py
else
#  # create a new log file name, max of 7 log files
#  echo "Rotating log files..."
#  rm ../logs/PyQtPiClock.7.log >/dev/null 2>&1
#  mv ../logs/PyQtPiClock.6.log ../logs/PyQtPiClock.7.log >/dev/null 2>&1
#  mv ../logs/PyQtPiClock.5.log ../logs/PyQtPiClock.6.log >/dev/null 2>&1
#  mv ../logs/PyQtPiClock.4.log ../logs/PyQtPiClock.5.log >/dev/null 2>&1
#  mv ../logs/PyQtPiClock.3.log ../logs/PyQtPiClock.4.log >/dev/null 2>&1
#  mv ../logs/PyQtPiClock.2.log ../logs/PyQtPiClock.3.log >/dev/null 2>&1
#  mv ../logs/PyQtPiClock.1.log ../logs/PyQtPiClock.2.log >/dev/null 2>&1
#  echo "Starting PiClock... logging to logs/PyQtPiClock.1.log"
#  # start PiClock and add timestamp to log output
#  python3 -u PyQtPiClock.py 2>&1 | (while read -r line; do echo "$(date +'%F %T.%6N %Z (UTC%z) -') $line"; done) >../logs/PyQtPiClock.1.log
  echo "Starting PiClock... logging to logs/PyQtPiClock.1.log (rotates daily at midnight)"
  PICLOCK_DAILY_LOG=1 python3 -u PyQtPiClock.py
fi
