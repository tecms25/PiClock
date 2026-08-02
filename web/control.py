"""The only things the panel is allowed to do to the system.

Every action is a fixed argv list looked up by name. The name arriving from a
browser is used solely as a dictionary key - it is never interpolated into a
command, nothing here runs through a shell, and an unrecognised name is refused
before any process starts. So a request cannot invent an action that is not on
this list, whatever it puts in the form field.
"""

import shutil
import subprocess
import sys

SERVICE = 'piclock.service'
PANEL = 'piclock-web.service'

# name -> what it does. 'confirm' marks the ones that take the clock off the
# screen, which the page makes you agree to twice.
ACTIONS = {
    'start': {
        'label': 'Start',
        'describe': 'Start the clock if it is not running.',
        'argv': ['systemctl', '--user', 'start', SERVICE],
        'confirm': False,
        'danger': False,
    },
    'restart': {
        'label': 'Restart',
        'describe': 'Stop and start the clock. The screen goes blank for a few '
                    'seconds.',
        'argv': ['systemctl', '--user', 'restart', SERVICE],
        'confirm': True,
        'danger': False,
    },
    'stop': {
        'label': 'Stop',
        'describe': 'Stop the clock and leave the screen blank until it is '
                    'started again.',
        'argv': ['systemctl', '--user', 'stop', SERVICE],
        'confirm': True,
        'danger': True,
    },
}

ACTIONS['restart_panel'] = {
    'label': 'Restart panel',
    'describe': 'Restart this control panel, to pick up an update. The page '
                'will be unreachable for a few seconds.',
    # Scheduled a couple of seconds out through a transient systemd timer,
    # rather than run directly: restarting the panel from inside the panel
    # kills the process that still owes the browser a reply, so the request
    # has to be finished and answered before the restart lands.
    'argv': ['systemd-run', '--user', '--collect', '--on-active=2',
             'systemctl', '--user', 'restart', PANEL],
    'confirm': True,
    'danger': False,
}

# Order shown on the page; least destructive first.
ORDER = ('start', 'restart', 'stop', 'restart_panel')

TIMEOUT_SECONDS = 25


def available():
    """True when systemd user services can actually be driven from here."""
    return bool(sys.platform.startswith('linux')
                and shutil.which('systemctl') is not None)


def listed():
    """The actions, in display order, for the control page."""
    return [dict(ACTIONS[name], name=name) for name in ORDER if name in ACTIONS]


def run(name):
    """Carry out one named action. Returns (ok, message).

    Never raises: the caller is a request handler, and a control panel that
    returns a 500 because systemctl was slow is worse than one that says so.
    """
    action = ACTIONS.get(name)
    if action is None:
        return False, 'Unknown action.'
    if not available():
        return False, 'systemd user services are not available on this machine.'
    if action['argv'][0] == 'systemd-run' and shutil.which('systemd-run') is None:
        return False, ('systemd-run is not installed, so the panel cannot '
                       'restart itself. Run "systemctl --user restart %s" on '
                       'the Pi instead.' % PANEL)

    try:
        done = subprocess.run(action['argv'], capture_output=True, text=True,
                              timeout=TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        return False, '%s timed out after %d seconds.' % (action['label'],
                                                          TIMEOUT_SECONDS)
    except OSError as exc:
        return False, 'Could not run systemctl: %s' % exc

    if done.returncode == 0:
        if name == 'restart_panel':
            return True, ('Restarting the panel. Give it a few seconds, then '
                          'reload this page.')
        return True, '%s: done.' % action['label']
    # systemctl puts the useful part on stderr.
    detail = (done.stderr or done.stdout or '').strip().splitlines()
    return False, '%s failed (exit %d)%s' % (
        action['label'], done.returncode,
        ': ' + detail[0] if detail else '.')
