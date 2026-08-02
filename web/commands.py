"""Live commands: the things the clock can do without being restarted.

These are the same actions the clock's own keyboard shortcuts trigger, sent to
the running process over a loopback-only channel it opens for the panel. Since
nothing restarts, the screen just does the thing.

The command name is validated against this list before anything is sent, and
validated again by the clock against its own table, so a name that is not on
both lists reaches nothing.
"""

import urllib.error
import urllib.parse
import urllib.request

# Mirrors COMMANDS in Clock/PyQtPiClock.py. 'key' is the keyboard shortcut that
# does the same thing, shown so the page matches what is written on the clock.
CATALOGUE = (
    {'name': 'next_page', 'label': 'Next page', 'key': 'Space',
     'describe': 'Move to the next screen of weather and radar.',
     'group': 'Display'},
    {'name': 'prev_page', 'label': 'Previous page', 'key': 'Left',
     'describe': 'Move back a screen.',
     'group': 'Display'},
    {'name': 'foreground_toggle', 'label': 'Toggle clock', 'key': 'F9',
     'describe': 'Hide or show the clock and weather, leaving just the photo.',
     'group': 'Display'},
    {'name': 'hide_alert', 'label': 'Close alert detail', 'key': 'Esc',
     'describe': 'Close the severe weather panel if it is open.',
     'group': 'Display'},
    {'name': 'prev_image', 'label': 'Previous image', 'key': 'F6',
     'describe': 'Step the slideshow back one photo.',
     'group': 'Slideshow'},
    {'name': 'next_image', 'label': 'Next image', 'key': 'F7',
     'describe': 'Step the slideshow on one photo.',
     'group': 'Slideshow'},
    {'name': 'slideshow_toggle', 'label': 'Pause / resume', 'key': 'F8',
     'describe': 'Hold the slideshow on the current photo, or start it again.',
     'group': 'Slideshow'},
    {'name': 'radio_toggle', 'label': 'Weather radio', 'key': 'F2',
     'describe': 'Start or stop the NOAA weather radio stream.',
     'group': 'Audio'},
)

NAMES = frozenset(entry['name'] for entry in CATALOGUE)

GROUPS = ('Display', 'Slideshow', 'Audio')

TIMEOUT_SECONDS = 4


def grouped():
    """The catalogue as (group, [commands]) for the page."""
    return [(group, [c for c in CATALOGUE if c['group'] == group])
            for group in GROUPS]


def send(name, port, token):
    """Ask the running clock to do one thing. Returns (ok, message).

    Never raises. The clock not answering is the ordinary case when it has been
    stopped, and that should read as a plain sentence on the page rather than a
    stack trace.
    """
    if name not in NAMES:
        return False, 'Unknown command.'
    if not token:
        return False, ('The command channel is not set up. Run '
                       'web/set_password.py, then restart the clock.')

    query = urllib.parse.urlencode({'token': token, 'do': name})
    url = 'http://127.0.0.1:%d/command?%s' % (int(port), query)
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT_SECONDS) as reply:
            body = reply.read().decode('utf-8', 'replace').strip()
        return True, body or 'Done.'
    except urllib.error.HTTPError as exc:
        detail = ''
        try:
            detail = exc.read().decode('utf-8', 'replace').strip()
        except Exception:
            pass
        if exc.code == 403:
            return False, ('The clock rejected the command token. Restart the '
                           'clock so it picks up the current one.')
        if exc.code == 503:
            return False, 'The clock has no command token; restart it.'
        return False, detail or 'The clock refused that command.'
    except (urllib.error.URLError, OSError):
        return False, ('The clock is not answering on port %s. It may be '
                       'stopped, or started without the panel switched on.'
                       % port)
