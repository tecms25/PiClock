#!/usr/bin/env python3
"""Add newly released settings to an existing Clock/Config.py and ApiKeys.py.

PiClock picks up new settings over time. Copying the example files over the top
would wipe your location, API keys and preferences, so this only appends the
settings you are missing and leaves everything you have already set alone.

    python3 merge_config.py              # show what is missing, then merge
    python3 merge_config.py --dry-run    # show what is missing, change nothing

A timestamped backup of each file is written before it is touched.
"""

import argparse
import ast
import os
import shutil
import sys
import time

REPO = os.path.dirname(os.path.abspath(__file__))

# (example file, the live file it seeds)
PAIRS = (
    (os.path.join('Clock', 'Config-Example.py'), os.path.join('Clock', 'Config.py')),
    (os.path.join('Clock', 'ApiKeys-example.py'), os.path.join('Clock', 'ApiKeys.py')),
)


def read_text(path):
    """Return (text, newline) with the file's own line ending remembered, so a
    CRLF file stays CRLF when written back."""
    with open(path, 'rb') as handle:
        raw = handle.read()
    newline = '\r\n' if b'\r\n' in raw else '\n'
    return raw.replace(b'\r\n', b'\n').decode('utf-8'), newline


def write_text(path, text, newline):
    with open(path, 'wb') as handle:
        handle.write(text.replace('\n', newline).encode('utf-8'))


def assigned_names(tree):
    """Every name assigned at the top level of a parsed module."""
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def imported_names(tree):
    names = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.add(alias.asname or alias.name)
    return names


def setting_blocks(text):
    """Yield (name, source) for each top-level setting, in file order.

    A block carries the comment lines directly above the assignment, since
    those are the documentation for it, plus any follow-up statement that
    mutates the same name (Config-Example.py does 'dimcolor = QColor(...)'
    then 'dimcolor.setAlpha(0)').
    """
    lines = text.split('\n')
    body = ast.parse(text).body
    blocks = []
    seen = set()

    for index, node in enumerate(body):
        name = None
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)):
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if name is None or name in seen:
            continue
        seen.add(name)

        start = node.lineno - 1
        above = start - 1
        while above >= 0 and lines[above].lstrip().startswith('#'):
            above -= 1
        start = above + 1

        end = node.end_lineno
        for later in body[index + 1:]:
            if isinstance(later, ast.Expr) and isinstance(later.value, ast.Call):
                func = later.value.func
                if (isinstance(func, ast.Attribute)
                        and isinstance(func.value, ast.Name)
                        and func.value.id == name):
                    end = later.end_lineno
                    continue
            break

        blocks.append((name, '\n'.join(lines[start:end])))
    return blocks


def merge_one(example_rel, target_rel, dry_run, prompt=False):
    """Bring one example/live pair up to date.

    Returns 'merged' if settings were written, True if there was nothing to do
    (or the user declined), and False if something went wrong.
    """
    example = os.path.join(REPO, example_rel)
    target = os.path.join(REPO, target_rel)

    if not os.path.isfile(example):
        print('  SKIP %s: %s not found' % (target_rel, example_rel))
        return True
    if not os.path.isfile(target):
        print('  SKIP %s: not present, so there is nothing to upgrade.' % target_rel)
        print('       Run install.sh (or copy %s) to create it.' % example_rel)
        return True

    example_text, _ = read_text(example)
    target_text, newline = read_text(target)

    try:
        target_tree = ast.parse(target_text, filename=target_rel)
    except SyntaxError as exc:
        print('  ERROR %s has a syntax error, refusing to touch it: %s'
              % (target_rel, exc))
        return False

    have = assigned_names(target_tree)
    missing = [(n, src) for n, src in setting_blocks(example_text) if n not in have]

    if not missing:
        print('  %s is already up to date.' % target_rel)
        return True

    print('  %s is missing %d setting(s):' % (target_rel, len(missing)))
    for name, _ in missing:
        print('      %s' % name)

    # A new setting may need an import the old file predates.
    new_imports = imported_names(ast.parse(example_text)) - imported_names(target_tree)
    if new_imports:
        print('      NOTE: %s also imports %s, which %s does not. Check the top '
              'of the file if the clock fails to start.'
              % (example_rel, ', '.join(sorted(new_imports)), target_rel))

    if dry_run:
        print('      (dry run, nothing written)')
        return True

    if prompt:
        try:
            answer = input('      Add these to %s? [Y/n] ' % target_rel).strip().lower()
        except EOFError:  # non-interactive, e.g. piped input
            answer = 'n'
        if answer.startswith('n'):
            print('      Skipped. Run "python3 merge_config.py" later to add them.')
            return True

    header = ('# --- added by merge_config.py on %s, from %s ---'
              % (time.strftime('%Y-%m-%d'), os.path.basename(example_rel)))
    merged = (target_text.rstrip('\n') + '\n\n\n' + header + '\n'
              + '\n\n'.join(src for _, src in missing) + '\n')

    try:
        ast.parse(merged, filename=target_rel)
    except SyntaxError as exc:
        print('  ERROR merging would have broken %s (%s). Nothing written.'
              % (target_rel, exc))
        return False

    backup = '%s.bak-%s' % (target, time.strftime('%Y%m%d-%H%M%S'))
    shutil.copy2(target, backup)
    write_text(target, merged, newline)
    print('      added to %s (backup: %s)' % (target_rel, os.path.basename(backup)))
    return 'merged'


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Add new PiClock settings to an existing config, keeping '
                    'your current values.')
    parser.add_argument('--dry-run', action='store_true',
                        help='report what is missing without changing anything')
    parser.add_argument('--prompt', action='store_true',
                        help='ask before writing (used by update.py)')
    args = parser.parse_args(argv)

    print('Checking for new settings...')
    ok = True
    changed = False
    for example_rel, target_rel in PAIRS:
        result = merge_one(example_rel, target_rel, args.dry_run, args.prompt)
        if result is False:
            ok = False
        elif result == 'merged':
            changed = True

    if not ok:
        print('\nFinished with errors; see above.')
        return 1
    if args.dry_run:
        print('\nDry run only. Re-run without --dry-run to apply.')
    elif changed:
        print('\nDone. New settings are appended at the end of each file with '
              'their default values -')
        print('edit them there if you want something other than the defaults.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
