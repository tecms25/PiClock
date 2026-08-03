"""Reading and setting the Pi's output volume.

Done here rather than in the clock because it is a property of the machine,
not of whatever happens to be playing - so it still works with the clock
stopped, and adjusting it does not interrupt a stream.

Whichever mixer the system uses is found at run time. Raspberry Pi OS Bookworm
and current Ubuntu both run PipeWire, where wpctl is the native tool and pactl
is its PulseAudio-compatible front; older images are plain ALSA and only have
amixer.

The level arriving from a browser is put through int() and clamped to 0-100
before it is formatted into an argument, and every command is a fixed argv with
no shell, so a submitted value can only ever be a number in that range.
"""

import re
import shutil
import subprocess

TIMEOUT_SECONDS = 5

# name -> how to read and how to write. {level} is substituted after clamping.
BACKENDS = (
    ('wpctl',
     ['wpctl', 'get-volume', '@DEFAULT_AUDIO_SINK@'],
     ['wpctl', 'set-volume', '@DEFAULT_AUDIO_SINK@', '{level}%']),
    ('pactl',
     ['pactl', 'get-sink-volume', '@DEFAULT_SINK@'],
     ['pactl', 'set-sink-volume', '@DEFAULT_SINK@', '{level}%']),
    ('amixer',
     ['amixer', 'sget', 'Master'],
     ['amixer', '-q', 'sset', 'Master', '{level}%']),
)

# wpctl answers "Volume: 0.65" (and "Volume: 0.65 [MUTED]"); pactl and amixer
# both put a percentage in their output, pactl per channel and amixer in
# brackets. Read the first number either way - the channels move together.
# Deliberately not anchored to the end of the line: [MUTED] follows the number.
FRACTION = re.compile(r'Volume:\s*([0-9]*\.?[0-9]+)')
PERCENT = re.compile(r'(\d{1,3})%')

# Moving the slider means "I want to hear this", so a muted sink is unmuted at
# the same time. Without it, dragging the volume up on a muted device does
# nothing at all and looks like a broken control.
UNMUTE = {
    'wpctl': ['wpctl', 'set-mute', '@DEFAULT_AUDIO_SINK@', '0'],
    'pactl': ['pactl', 'set-sink-mute', '@DEFAULT_SINK@', '0'],
    'amixer': ['amixer', '-q', 'sset', 'Master', 'unmute'],
}


def _run(argv):
    try:
        done = subprocess.run(argv, capture_output=True, text=True,
                              timeout=TIMEOUT_SECONDS, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return done if done.returncode == 0 else None


def backend():
    """(name, read_argv, write_argv) for the first mixer installed, or None."""
    for name, read_argv, write_argv in BACKENDS:
        if shutil.which(name):
            return name, read_argv, write_argv
    return None


def available():
    return backend() is not None


def clamp(value):
    """A submitted level as an int 0-100. Raises ValueError if it is not one."""
    level = int(str(value).strip())
    return max(0, min(100, level))


def get():
    """Current output level as a percentage, or None if it cannot be read."""
    found = backend()
    if found is None:
        return None
    name, read_argv, _ = found
    done = _run(read_argv)
    if done is None:
        return None
    text = done.stdout or ''

    if name == 'wpctl':
        match = FRACTION.search(text.strip())
        if match:
            try:
                return max(0, min(100, int(round(float(match.group(1)) * 100))))
            except ValueError:
                return None
        return None

    match = PERCENT.search(text)
    if match:
        return max(0, min(100, int(match.group(1))))
    return None


def set_level(value):
    """Set the output level. Returns (ok, message, level)."""
    found = backend()
    if found is None:
        return False, 'No mixer is available on this machine.', None
    try:
        level = clamp(value)
    except (TypeError, ValueError):
        return False, 'That is not a volume level.', None

    name, _, write_argv = found
    argv = [part.format(level=level) for part in write_argv]
    if _run(argv) is None:
        return False, 'Could not set the volume with %s.' % name, None
    # Best effort: a mixer that cannot unmute is not a reason to report the
    # volume change as failed, since that part did work.
    if name in UNMUTE:
        _run(UNMUTE[name])
    return True, 'Volume %d%%' % level, level
