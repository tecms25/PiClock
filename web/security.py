"""Who is allowed to reach the control panel at all.

The panel exists to change settings that the clock then executes as Python, so
reaching it is close enough to running code on the Pi that it deserves two
independent gates rather than one:

  1. the caller's address must be on a private network, and
  2. the session must be authenticated with the shared password.

The address check runs first, and covers the login page as well, so a caller
from outside your LAN never gets as far as a password prompt to guess at.
"""

import ipaddress
import json
import os
import secrets
import time

# RFC 1918 is the IPv4 part of "local". The rest are addresses that are just as
# local and would be surprising to lock out: loopback for a browser on the Pi
# itself, link-local for a direct cable, and the IPv6 equivalents.
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(cidr) for cidr in (
    '10.0.0.0/8',        # RFC 1918
    '172.16.0.0/12',     # RFC 1918
    '192.168.0.0/16',    # RFC 1918
    '127.0.0.0/8',       # loopback
    '169.254.0.0/16',    # RFC 3927 link-local
    '::1/128',           # IPv6 loopback
    'fc00::/7',          # RFC 4193 unique local
    'fe80::/10',         # RFC 4291 link-local
))


def is_private_address(raw):
    """True when raw is an address on a local network.

    Anything that will not parse is refused rather than allowed. An empty
    string, a hostname, or a header a proxy mangled must all fail closed - the
    whole point of this gate is that it cannot be talked around.
    """
    if not raw:
        return False
    text = str(raw).strip()
    # A scoped address arrives as fe80::1%eth0; the zone says nothing about
    # whether it is local, so drop it before parsing.
    text = text.split('%', 1)[0]
    try:
        address = ipaddress.ip_address(text)
    except ValueError:
        return False
    # A dual-stack socket reports IPv4 callers as ::ffff:192.168.1.5. Compare
    # the address that actually means something.
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        address = address.ipv4_mapped
    return any(address in network for network in PRIVATE_NETWORKS)


class LoginThrottle:
    """Per-address backoff, so a single shared password cannot be brute forced.

    Held in memory only. Restarting the panel clears it, which is acceptable:
    an attacker cannot restart it, and the address gate already means they are
    on your LAN before any of this applies.
    """

    def __init__(self, max_attempts=5, lockout_seconds=300):
        self.max_attempts = max_attempts
        self.lockout_seconds = lockout_seconds
        self._failures = {}

    def locked_for(self, key):
        """Seconds this caller must wait, or 0 if they may try now."""
        count, last = self._failures.get(key, (0, 0.0))
        if count < self.max_attempts:
            return 0
        remaining = self.lockout_seconds - (time.monotonic() - last)
        if remaining <= 0:
            self._failures.pop(key, None)
            return 0
        return int(remaining) + 1

    def record_failure(self, key):
        count, _ = self._failures.get(key, (0, 0.0))
        self._failures[key] = (count + 1, time.monotonic())

    def record_success(self, key):
        self._failures.pop(key, None)


def read_secrets(path):
    """The panel's password hash and session key, or {} if not set up yet."""
    try:
        with open(path) as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_secrets(path, data):
    """Write the secrets file so only its owner can read it.

    Created at 0600 from the start rather than chmod'ed afterwards, because
    between the two there is a moment where the password hash is world
    readable.
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    temporary = path + '.tmp'
    handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(handle, 'w') as stream:
            json.dump(data, stream, indent=2, sort_keys=True)
            stream.write('\n')
    except Exception:
        os.unlink(temporary)
        raise
    os.replace(temporary, path)


def ensure_command_token(path):
    """Return the secret shared with the clock's command channel.

    Generated here rather than configured, because nobody should have to
    invent one: both sides read the same 0600 file. The clock reads it at
    startup, so a token created after the clock started needs a restart before
    live commands work.
    """
    data = read_secrets(path)
    token = data.get('command_token')
    if not token:
        token = secrets.token_urlsafe(32)
        data['command_token'] = token
        write_secrets(path, data)
    return token


def ensure_session_key(path):
    """Return the panel's Flask session key, creating one on first run.

    Persisted rather than generated per start, so restarting the panel - which
    it will do whenever you update - does not log you out.
    """
    data = read_secrets(path)
    key = data.get('session_key')
    if not key:
        key = secrets.token_hex(32)
        data['session_key'] = key
        write_secrets(path, data)
    return key
