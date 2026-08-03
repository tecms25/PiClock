"""Live commands: the things the clock can do without being restarted.

These are the same actions the clock's own keyboard shortcuts trigger, sent to
the running process over a loopback-only channel it opens for the panel. Since
nothing restarts, the screen just does the thing.

The command name is validated against this list before anything is sent, and
validated again by the clock against its own table, so a name that is not on
both lists reaches nothing.
"""

import os
import sys
import urllib.error
import urllib.parse
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
)

# Commands that are accepted but have no button. radio_toggle is what F2 does
# on the clock; the Audio streams card does the same job with a named stream,
# so a second control for "whichever one is first" is only confusing.
NAMES = frozenset(entry['name'] for entry in CATALOGUE) | {
    'audio_play', 'audio_stop', 'audio_status', 'radio_toggle'}


def streams():
    """The audio streams the clock offers, read from Config.py.

    Read rather than imported, like everything else the panel takes from the
    config, so this process never executes it. The order must match
    audio_streams() in the clock, because a stream is asked for by index:
    noaastream first, then audio_streams.
    """
    sys.path.insert(0, REPO)
    try:
        import merge_config
        text, _ = merge_config.read_text(os.path.join(REPO, 'conf', 'Config.py'))
        values = merge_config.literal_settings(text)
    except Exception:
        return []
    finally:
        sys.path.pop(0)

    found = []
    noaa = (values.get('noaastream') or '').strip()
    if noaa:
        found.append({'name': 'NOAA weather radio', 'url': noaa})
    for entry in values.get('audio_streams') or []:
        if not isinstance(entry, dict):
            continue
        url = (entry.get('url') or '').strip()
        if url:
            found.append({'name': (entry.get('name') or '').strip() or url,
                          'url': url})
    for index, entry in enumerate(found):
        entry['index'] = index
        entry['hls'] = entry['url'].split('?')[0].lower().endswith('.m3u8')
    return found

GROUPS = ('Display', 'Slideshow', 'Audio')

TIMEOUT_SECONDS = 4


def grouped():
    """The catalogue as (group, [commands]) for the page.

    Groups with nothing left in them are dropped, so removing the last command
    from one does not leave a bare heading behind.
    """
    out = []
    for group in GROUPS:
        items = [c for c in CATALOGUE if c['group'] == group]
        if items:
            out.append((group, items))
    return out


SCREENSHOT_TIMEOUT_SECONDS = 12


def screenshot(port, token, width=960):
    """The clock's screen as (content_type, bytes), or (None, message).

    A longer timeout than the other commands: rendering and encoding a
    full-screen image on a Pi is slower than answering a one-line question.
    """
    if not token:
        return None, ('The command channel is not set up. Run '
                      'web/set_password.py, then restart the clock.')
    try:
        width = max(0, min(1920, int(width)))
    except (TypeError, ValueError):
        width = 960
    query = urllib.parse.urlencode({'token': token, 'do': 'screenshot',
                                    'w': width})
    url = 'http://127.0.0.1:%d/screenshot?%s' % (int(port), query)
    try:
        with urllib.request.urlopen(url, timeout=SCREENSHOT_TIMEOUT_SECONDS) as reply:
            kind = reply.headers.get('Content-Type', '')
            body = reply.read()
        if not kind.startswith('image/'):
            return None, (body.decode('utf-8', 'replace').strip()
                          or 'The clock did not send an image.')
        return kind, body
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode('utf-8', 'replace').strip()
        except Exception:
            detail = ''
        return None, detail or 'The clock refused the screenshot.'
    except (urllib.error.URLError, OSError):
        return None, ('The clock is not answering on port %s, so there is no '
                      'screen to capture.' % port)


def send(name, port, token, stream=None):
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

    fields = {'token': token, 'do': name}
    if stream is not None:
        # Sent as a number and checked again by the clock against its own
        # list, so a stream index from a browser can only ever select one of
        # the streams already in the config.
        try:
            fields['stream'] = int(stream)
        except (TypeError, ValueError):
            return False, 'That is not a stream number.'
    query = urllib.parse.urlencode(fields)
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
