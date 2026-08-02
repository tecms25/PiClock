#!/usr/bin/env python3
"""Set the web control panel's shared password.

    venv/bin/python3 web/set_password.py

Only a hash is stored, in conf/web_secret.json at mode 0600. There is no way to
recover the password from it - run this again to set a new one.
"""

import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import security                                                # noqa: E402
from werkzeug.security import generate_password_hash           # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRETS = os.path.join(REPO, 'conf', 'web_secret.json')

MIN_LENGTH = 10


def main():
    print('Setting the PiClock control panel password.')
    print('It is stored as a hash in %s\n' % os.path.relpath(SECRETS, REPO))

    try:
        password = getpass.getpass('New password: ')
        again = getpass.getpass('Repeat: ')
    except (EOFError, KeyboardInterrupt):
        print('\nCancelled.')
        return 1

    if password != again:
        print('Those do not match. Nothing was changed.')
        return 1
    # One shared password is the only thing between your LAN and a panel that
    # can change what the clock runs, so a short one is not worth offering.
    if len(password) < MIN_LENGTH:
        print('Too short - use at least %d characters. Nothing was changed.'
              % MIN_LENGTH)
        return 1

    import secrets as _secrets

    data = security.read_secrets(SECRETS)
    had_password = bool(data.get('password_hash'))
    data['password_hash'] = generate_password_hash(password)
    # Rotate the session key too. Changing a password should end the sessions
    # opened with the old one - if you are changing it because someone else
    # learned it, leaving their browser signed in defeats the point.
    data['session_key'] = _secrets.token_hex(32)
    # The secret the clock's live-command channel checks. Created here so that
    # setting a password is the only setup step - neither side needs it typed
    # in anywhere.
    new_channel = not data.get('command_token')
    data.setdefault('command_token', _secrets.token_urlsafe(32))
    security.write_secrets(SECRETS, data)

    print('\nPassword set.')
    if had_password:
        print('Every signed-in browser has been signed out, including yours.')
    print('Restart the panel for it to take effect:')
    print('    systemctl --user restart piclock-web')
    if new_channel:
        print('\nA command token was created for the live commands on the')
        print('Control page. Restart the clock so it picks that up:')
        print('    systemctl --user restart piclock')
    return 0


if __name__ == '__main__':
    sys.exit(main())
