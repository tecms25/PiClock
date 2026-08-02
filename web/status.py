"""Everything the panel reports, gathered read-only.

Nothing here writes, starts, stops or configures anything - that arrives in
later phases. Every collector answers with a dict and swallows its own errors,
because a control panel that will not render because one `systemctl` call
failed is worse than one showing "unknown" in a single row.
"""

import os
import re
import subprocess
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(REPO, 'conf', 'Config.py')
LOG = os.path.join(REPO, 'logs', 'PyQtPiClock.1.log')
SERVICE = 'piclock.service'

# Settings whose value must never reach a browser. Matched as substrings and
# case-insensitively so anything added later that is obviously a credential is
# hidden by default: a new setting is redacted until someone decides it is
# safe, rather than exposed until someone notices.
SECRET_HINTS = ('password', 'passwd', 'token', 'secret', 'api', 'key', 'auth')


def looks_secret(name):
    lowered = name.lower()
    return any(hint in lowered for hint in SECRET_HINTS)


# PiClock logs the URLs it fetches, and those carry credentials: a Mapbox tile
# request has ?access_token=..., a weather call has &apikey=.... Showing a raw
# log tail in a browser would put the account keys on screen, into the browser
# cache, and into any screenshot of the page.
CREDENTIAL_IN_URL = re.compile(
    r'(?i)\b(access_token|apikey|api_key|key|token|password|passwd|pw|session|'
    r'secret|auth|signature)=([^&\s"\'<>]+)')


def _api_key_values():
    """Literal values from ApiKeys.py, so they can be scrubbed by value too.

    The pattern above catches credentials in a query string, which is how they
    reach the log today. This catches them wherever else they might turn up -
    inside an error message, say - and costs one small file read per refresh.
    """
    sys.path.insert(0, REPO)
    try:
        import merge_config
        text, _ = merge_config.read_text(os.path.join(REPO, 'conf', 'ApiKeys.py'))
        values = merge_config.literal_settings(text)
    except Exception:
        return ()
    finally:
        sys.path.pop(0)
    # Short values would match everywhere and turn the log into asterisks.
    return tuple(v for v in values.values() if isinstance(v, str) and len(v) >= 8)


def scrub(lines):
    """Log lines with every credential in them replaced.

    Takes the whole list rather than one line so ApiKeys.py is read once per
    refresh instead of once per line.
    """
    known = _api_key_values()
    cleaned = []
    for line in lines:
        line = CREDENTIAL_IN_URL.sub(r'\1=********', line)
        for value in known:
            if value in line:
                line = line.replace(value, '********')
        cleaned.append(line)
    return cleaned


def _run(args, timeout=5):
    """(ok, stdout) for a short command, never raising."""
    try:
        done = subprocess.run(args, capture_output=True, text=True,
                              timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return False, ''
    return done.returncode == 0, done.stdout.strip()


def systemd_available():
    if not sys.platform.startswith('linux'):
        return False
    ok, _ = _run(['systemctl', '--user', '--version'])
    return ok


def service_status():
    """State of the clock's systemd unit.

    `is-active` exits non-zero for anything that is not running, so its output
    matters more than its exit status - "inactive" and "failed" are answers,
    not errors.
    """
    if not systemd_available():
        return {'available': False, 'active': 'unknown', 'enabled': 'unknown',
                'since': '', 'pid': 0, 'restarts': 0,
                'note': 'systemd user services are not available here'}

    _, active = _run(['systemctl', '--user', 'is-active', SERVICE])
    _, enabled = _run(['systemctl', '--user', 'is-enabled', SERVICE])
    ok, shown = _run(['systemctl', '--user', 'show', SERVICE, '--property',
                      'ActiveEnterTimestamp,MainPID,NRestarts'])
    properties = {}
    if ok:
        for line in shown.splitlines():
            name, _, value = line.partition('=')
            properties[name] = value

    return {
        'available': True,
        'active': active or 'unknown',
        'enabled': enabled or 'unknown',
        'since': properties.get('ActiveEnterTimestamp', ''),
        'pid': int(properties.get('MainPID') or 0),
        'restarts': int(properties.get('NRestarts') or 0),
        'note': '',
    }


def clock_process():
    """The running clock, found by process table rather than by unit.

    Looked up this way so the panel still reports something useful when the
    clock was started by hand or from the desktop icon instead of by systemd.
    """
    ok, out = _run(['ps', '-Ao', 'pid=,pcpu=,pmem=,etime=,command='])
    if not ok:
        return {'running': False}
    for line in out.splitlines():
        if 'PyQtPiClock.py' not in line or 'ps -Ao' in line:
            continue
        # Skip the shell wrapper that startup.sh leaves in the table; only the
        # interpreter actually running the script counts.
        if 'python' not in line.lower():
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        return {'running': True, 'pid': int(parts[0]), 'cpu': parts[1],
                'mem': parts[2], 'elapsed': parts[3]}
    return {'running': False}


def log_tail(lines=60, path=None):
    """The last few log lines, read from the end rather than the start.

    The clock's log runs to megabytes over a day, so reading the whole file to
    show 60 lines would have the panel allocating the lot on every refresh.
    """
    path = path or LOG
    try:
        size = os.path.getsize(path)
        with open(path, 'rb') as handle:
            # Roughly 200 bytes a line, asked for generously, capped so a file
            # of very long lines cannot pull in everything.
            window = min(size, max(lines * 400, 8192))
            handle.seek(size - window)
            data = handle.read()
        text = data.decode('utf-8', 'replace')
        if window < size:
            # The first line is almost certainly cut in half by the seek.
            text = text.split('\n', 1)[-1]
        return scrub(text.strip().splitlines()[-lines:])
    except OSError:
        return []


def log_problems(entries):
    """Lines from the tail worth drawing attention to."""
    pattern = re.compile(r'\b(error|traceback|warning|failed|exception)\b', re.I)
    return [line for line in entries if pattern.search(line)]


def settings():
    """Current Config.py settings, read without executing the file.

    Importing the config would run it, which pulls in PyQt6 and
    GoogleMercatorProjection and would make this web app depend on Qt. Reading
    it as a syntax tree reaches every plain value, which is all the panel
    shows. Values that look like credentials are replaced, not omitted, so it
    is clear they are set.
    """
    sys.path.insert(0, REPO)
    try:
        import merge_config
    except ImportError:
        return []
    finally:
        sys.path.pop(0)

    try:
        text, _ = merge_config.read_text(CONFIG)
        values = merge_config.literal_settings(text)
    except (OSError, SyntaxError):
        return []

    rows = []
    for name in sorted(values):
        if looks_secret(name):
            rows.append({'name': name, 'value': '********', 'secret': True})
        else:
            rows.append({'name': name, 'value': repr(values[name]), 'secret': False})
    return rows


def host():
    """Basic facts about the machine the clock runs on."""
    info = {'hostname': '', 'uptime': '', 'disk_free': '', 'load': ''}
    ok, name = _run(['hostname'])
    if ok:
        info['hostname'] = name
    try:
        info['load'] = '%.2f %.2f %.2f' % os.getloadavg()
    except (OSError, AttributeError):
        pass
    try:
        usage = os.statvfs(REPO)
        free = usage.f_bavail * usage.f_frsize
        info['disk_free'] = '%.1f GB' % (free / (1024.0 ** 3))
    except (OSError, AttributeError):
        pass
    ok, out = _run(['uptime'])
    if ok:
        info['uptime'] = out
    return info


def snapshot():
    """One call for everything the status page shows."""
    entries = log_tail()
    return {
        'generated': time.strftime('%Y-%m-%d %H:%M:%S'),
        'service': service_status(),
        'process': clock_process(),
        'host': host(),
        'log': entries,
        'problems': log_problems(entries),
        'settings': settings(),
    }
