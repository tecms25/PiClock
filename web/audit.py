"""A record of what the panel did, and who asked for it.

Kept in SQLite rather than a text file because this is the one part of the
panel that is genuinely a query: "what happened, when, from where", read newest
first and capped. Configuration stays in conf/Config.py - a database would not
make that any safer, and would cost the comments that document it.

Writes here must never break a request. An action that succeeded but could not
be logged is still an action that succeeded, so every call swallows its errors
and says so on the page instead.
"""

import os
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    at      TEXT NOT NULL,
    address TEXT NOT NULL,
    action  TEXT NOT NULL,
    outcome TEXT NOT NULL,
    detail  TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS events_at ON events (id DESC);
"""


def _connect(path):
    fresh = not os.path.exists(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.executescript(SCHEMA)
    if fresh:
        # The log names source addresses and what was done with them; there is
        # no reason for anyone but the owner to read it.
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    return conn


def record(path, address, action, outcome, detail=''):
    """Append one event. Returns True if it was written."""
    try:
        conn = _connect(path)
        with conn:
            conn.execute(
                'INSERT INTO events (at, address, action, outcome, detail) '
                'VALUES (?, ?, ?, ?, ?)',
                (time.strftime('%Y-%m-%d %H:%M:%S'), str(address), str(action),
                 str(outcome), str(detail)[:500]))
        conn.close()
        return True
    except (sqlite3.Error, OSError):
        return False


def recent(path, limit=40):
    """The newest events first, or [] if the log cannot be read."""
    try:
        conn = _connect(path)
        rows = conn.execute(
            'SELECT at, address, action, outcome, detail FROM events '
            'ORDER BY id DESC LIMIT ?', (int(limit),)).fetchall()
        conn.close()
    except (sqlite3.Error, OSError, ValueError):
        return []
    return [{'at': r[0], 'address': r[1], 'action': r[2],
             'outcome': r[3], 'detail': r[4]} for r in rows]
