"""Reading and writing conf/Config.py from the panel.

Config.py is a Python module the clock executes, so writing it from a browser
is the most dangerous thing this panel does. Three things keep it safe:

  * only settings whose current value is a plain literal are offered at all -
    a QColor() or a LatLng() call is shown but never editable here;
  * whatever is submitted is put through ast.literal_eval and then written
    back as repr() of the resulting object. Nothing survives that round trip
    except a number, string, boolean, None, or a container of those, so a
    submitted value cannot become code however it is spelled;
  * a value may not change type. A setting that is an int stays an int, so a
    stray string cannot reach code expecting arithmetic.

The file is then re-parsed in full and compared against what it was, and only
written if the sole differences are the settings that were meant to change.
Every write leaves a timestamped backup, and the panel can put one back.
"""

import ast
import os
import re
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG = os.path.join(REPO, 'conf', 'Config.py')

sys.path.insert(0, REPO)
import merge_config                                            # noqa: E402
sys.path.pop(0)

# Value shapes the form knows how to render and read back.
BOOL, INT, FLOAT, TEXT, LITERAL = 'bool', 'int', 'float', 'text', 'literal'

SECRET_HINTS = ('password', 'passwd', 'token', 'secret', 'api', 'key', 'auth')

# Settings the panel must not offer, whatever their type: changing these from
# the panel could lock you out of the panel itself.
LOCKED = ('web_enabled', 'web_port', 'web_bind', 'web_command_port')

BACKUP_PREFIX = 'Config.py.bak-'

# Which panel each setting is filed under. Config.py has only a couple of
# section banners, so the grouping is derived from the names instead. Matched
# in order on a substring, first match wins - so 'blueiris_password' is filed
# under the cameras rather than under anything matching 'password'.
GROUPS = (
    ('Blue Iris cameras', ('blueiris',)),
    # Before the web panel, so web_slideshow_playlist files with the slideshow
    # it configures rather than with the panel it is named after.
    ('Slideshow', ('slide', 'useslideshow', 'icloud')),
    ('Web control panel', ('web_',)),
    ('Radar and maps', ('radar', 'map_', 'mapbox', 'google', 'usemapbox', 'tile')),
    ('Aircraft', ('flight',)),
    ('Alerts and radio', ('noaa', 'alert')),
    ('Screen and brightness', ('brightness', 'day_', 'night_', 'prevent_screen',
                              'cursor', 'sleep')),
    ('Clock face and layout', ('digital', 'font', 'layout', 'scrim', 'textcolor',
                               'footer', 'date', 'clock', 'size', 'color',
                               'background', 'icons')),
    ('Weather', ('metric', 'weather', 'temp', 'wind', 'pressure', 'metar',
                 'coordinates', 'location', 'language', 'units')),
)
DEFAULT_GROUP = 'Other'
GROUP_ORDER = tuple(name for name, _ in GROUPS) + (DEFAULT_GROUP,)


def group_of(name):
    lowered = name.lower()
    for group, keywords in GROUPS:
        if any(keyword in lowered for keyword in keywords):
            return group
    return DEFAULT_GROUP


def grouped(rows):
    """[(group, [rows])] in a fixed order, skipping groups with nothing in."""
    buckets = {}
    for row in rows:
        buckets.setdefault(row['group'], []).append(row)
    return [(name, buckets[name]) for name in GROUP_ORDER if name in buckets]


def looks_secret(name):
    lowered = name.lower()
    return any(hint in lowered for hint in SECRET_HINTS)


def kind_of(value, name=''):
    """How to render this value in the form."""
    if isinstance(value, bool):
        return BOOL
    if isinstance(value, int):
        # 0/1 flags are the house style for on-off settings, and a checkbox
        # reads better than a number box - but only where the name says so,
        # so a genuine count that happens to be 0 is not turned into a toggle.
        if value in (0, 1) and re.search(r'(enabled|_on$|use[a-z]*|metric)',
                                         name, re.I):
            return BOOL
        return INT
    if isinstance(value, float):
        return FLOAT
    if isinstance(value, str):
        return TEXT
    return LITERAL


def _help_for(text):
    """{name: comment above it} - the documentation already in the file.

    Section banners like '# WEATHER' are dropped: they head a group of
    settings rather than describe the one below them, and repeating them
    against every field just adds noise.
    """
    notes = {}
    for name, block in merge_config.setting_blocks(text):
        lines = []
        for line in block.split('\n'):
            stripped = line.strip()
            if not stripped.startswith('#'):
                continue
            comment = stripped.lstrip('#').strip()
            if not comment or (comment.isupper() and len(comment.split()) <= 3):
                continue
            lines.append(comment)
        notes[name] = ' '.join(lines)
    return notes


def _trailing_comment(suffix):
    """The '# 1 to enable' part of a line, which is often the clearest note."""
    if '#' not in suffix:
        return ''
    return suffix.split('#', 1)[1].strip()


def _spans(text):
    """{name: (first_line, last_line, prefix, suffix)} for literal settings.

    prefix is what comes before the value on its first line ('metric = ') and
    suffix what follows it on its last ('  # 1 for celsius'), so rewriting a
    value keeps the trailing comment that explains it.
    """
    lines = text.split('\n')
    spans = {}
    for node in ast.parse(text).body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            continue
        name = node.targets[0].id
        if name in spans:
            continue
        try:
            ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError):
            continue  # a call or a name; not ours to edit
        first, last = node.lineno - 1, node.end_lineno - 1
        spans[name] = (first, last,
                       lines[first][:node.value.col_offset],
                       lines[last][node.value.end_col_offset:])
    return spans


def read(path=None):
    """Every setting, with the editable ones marked."""
    path = path or CONFIG
    text, _ = merge_config.read_text(path)
    values = merge_config.literal_settings(text)
    spans = _spans(text)
    notes = _help_for(text)

    rows = []
    for name, start, _end in merge_config.setting_ranges(text):
        editable = name in spans and name not in LOCKED
        secret = looks_secret(name)
        value = values.get(name)
        note = ' '.join(part for part in (
            notes.get(name, ''),
            _trailing_comment(spans[name][3]) if name in spans else '') if part)
        rows.append({
            'name': name,
            'kind': kind_of(value, name) if editable else LITERAL,
            'editable': editable,
            'secret': secret,
            'locked': name in LOCKED,
            'value': value,
            'display': ('' if secret else
                        (value if isinstance(value, str) else repr(value))
                        if name in spans else '(not a plain value)'),
            'help': note,
            'group': group_of(name),
            'order': start,
        })
    rows.sort(key=lambda row: row['order'])
    return rows


def _backup_path(path):
    """A backup name that is not already taken.

    The timestamp only resolves to the second, and two saves in the same
    second are easy to make from a form - without the suffix the second one
    would quietly overwrite the copy the first had just made, losing the very
    state you would want back.
    """
    base = path + '.bak-' + time.strftime('%Y%m%d-%H%M%S')
    if not os.path.exists(base):
        return base
    for suffix in range(2, 100):
        candidate = '%s-%d' % (base, suffix)
        if not os.path.exists(candidate):
            return candidate
    return base


def _coerce(kind, current, raw):
    """Turn one submitted string into a value. Raises ValueError if it will not."""
    raw = raw.strip()
    if kind == BOOL:
        return 1 if raw in ('1', 'on', 'true', 'True', 'yes') else 0
    if kind == INT:
        return int(raw)
    if kind == FLOAT:
        return float(raw)
    if kind == TEXT:
        return raw
    value = ast.literal_eval(raw)
    if type(value) is not type(current):
        raise ValueError('expected %s, got %s'
                         % (type(current).__name__, type(value).__name__))
    return value


def _same_family(old, new):
    """True if new may replace old without changing what the clock will see.

    bool counts as int because the configs use 0 and 1 for flags; everything
    else must match exactly, so a number cannot quietly become a string.
    """
    if isinstance(old, bool) or isinstance(new, bool):
        return isinstance(old, (bool, int)) and isinstance(new, (bool, int))
    if isinstance(old, int) and isinstance(new, int):
        return True
    if isinstance(old, float) and isinstance(new, (int, float)):
        return True
    return type(old) is type(new)


def apply(submitted, path=None):
    """Write the settings that changed. Returns (ok, message, changed).

    submitted is {name: raw string}. A name that is not offered, is locked, or
    is unchanged is ignored; a blank secret means "leave it alone".
    """
    path = path or CONFIG
    rows = {row['name']: row for row in read(path)}
    text, newline = merge_config.read_text(path)
    spans = _spans(text)
    lines = text.split('\n')

    wanted, problems = {}, []
    for name, raw in submitted.items():
        row = rows.get(name)
        if row is None or not row['editable']:
            continue
        if row['secret'] and not raw.strip():
            continue  # blank means unchanged, so a secret need never be shown
        try:
            value = _coerce(row['kind'], row['value'], raw)
        except (ValueError, SyntaxError, TypeError) as exc:
            problems.append('%s: %s' % (name, exc))
            continue
        if not _same_family(row['value'], value):
            problems.append('%s: must stay a %s'
                            % (name, type(row['value']).__name__))
            continue
        if value != row['value'] or repr(value) != repr(row['value']):
            wanted[name] = value

    if problems:
        return False, 'Nothing was saved. ' + '; '.join(problems), []
    if not wanted:
        return True, 'No changes to save.', []

    for name, value in wanted.items():
        first, last, prefix, suffix = spans[name]
        lines[first:last + 1] = [prefix + repr(value) + suffix]
        # Rewriting one line shifts every span below it, so recompute.
        spans = _spans('\n'.join(lines))

    updated = '\n'.join(lines)

    # It must still be Python, and the only settings that moved must be the
    # ones asked for. This is what catches a rewrite landing in the wrong place.
    try:
        after = merge_config.literal_settings(updated)
    except SyntaxError as exc:
        return False, 'Nothing was saved: the result would not parse (%s).' % exc, []

    before = merge_config.literal_settings(text)
    moved = {name for name in set(before) | set(after)
             if before.get(name, object()) != after.get(name, object())}
    unexpected = moved - set(wanted)
    if unexpected:
        return False, ('Nothing was saved: that would also have changed %s.'
                       % ', '.join(sorted(unexpected))), []
    for name, value in wanted.items():
        if after.get(name) != value:
            return False, 'Nothing was saved: %s did not come back as written.' % name, []

    try:
        merge_config.write_text(_backup_path(path), text, newline)
        merge_config.write_text(path, updated, newline)
    except OSError as exc:
        return False, 'Could not write the config: %s' % exc, []

    names = ', '.join(sorted(wanted))
    return True, ('Saved %s. Restart the clock for it to take effect.'
                  % names), sorted(wanted)


def backups(path=None):
    """Timestamped backups, newest first."""
    path = path or CONFIG
    directory = os.path.dirname(os.path.abspath(path))
    try:
        names = os.listdir(directory)
    except OSError:
        return []
    found = []
    for name in names:
        if not name.startswith(BACKUP_PREFIX):
            continue
        full = os.path.join(directory, name)
        try:
            when = os.path.getmtime(full)
        except OSError:
            continue
        found.append({'name': name,
                      'when': time.strftime('%Y-%m-%d %H:%M:%S',
                                            time.localtime(when))})
    found.sort(key=lambda item: item['name'], reverse=True)
    return found


def restore(name, path=None):
    """Put a backup back, after backing up what is there now."""
    path = path or CONFIG
    # Rebuilt from the directory listing rather than joined with what was
    # submitted, so a name cannot walk out of conf/.
    if name not in {item['name'] for item in backups(path)}:
        return False, 'No such backup.'
    directory = os.path.dirname(os.path.abspath(path))
    source = os.path.join(directory, name)
    try:
        text, newline = merge_config.read_text(source)
        merge_config.literal_settings(text)  # must still parse
    except (OSError, SyntaxError) as exc:
        return False, 'That backup cannot be read: %s' % exc

    try:
        current, current_newline = merge_config.read_text(path)
        merge_config.write_text(_backup_path(path), current, current_newline)
        merge_config.write_text(path, text, newline)
    except OSError as exc:
        return False, 'Could not restore: %s' % exc
    return True, 'Restored %s. Restart the clock for it to take effect.' % name
