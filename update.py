import os
import re
import shutil
import sys
import traceback

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Settings and keys used to sit in Clock/. Move an older install's files across
# rather than leaving it pointing at a directory PiClock no longer reads.
print('\nChecking configuration layout')
os.makedirs('conf', exist_ok=True)
os.makedirs('logs', exist_ok=True)
for name in ('Config.py', 'ApiKeys.py'):
    old = os.path.join('Clock', name)
    new = os.path.join('conf', name)
    if os.path.isfile(old) and not os.path.isfile(new):
        shutil.move(old, new)
        print('Moved %s to %s' % (old, new))
    elif os.path.isfile(old):
        print('WARNING: both %s and %s exist. PiClock reads %s; delete the '
              'other once you are happy.' % (old, new, new))
for name in os.listdir('Clock'):
    if re.match(r'PyQtPiClock\.\d+\.log$', name):
        shutil.move(os.path.join('Clock', name), os.path.join('logs', name))
        print('Moved Clock/%s to logs/%s' % (name, name))

print('\nUpdating Python Package Manager')
cmd = 'python3 -m pip install --upgrade pip'
print(cmd)
os.system(cmd)
print('\nRemoving old Python Modules')
cmd = 'python3 -m pip uninstall python-metar -y'
print(cmd)
os.system(cmd)
print('\nUpdating Python Modules')
cmd = 'python3 -m pip install -r requirements.txt'
print(cmd)
os.system(cmd)

buttonFileName = 'Button/gpio-keys'
print('\nChecking ' + buttonFileName)
if os.path.isfile(buttonFileName):
    print('Setting proper permissions on ' + buttonFileName)
    os.chmod(buttonFileName, 0o744)

apikeysFileName = os.path.join('conf', 'ApiKeys.py')
# Providers no longer supported; any leftover key line for these gets stripped out.
deprecated_key_res = {
    'wuapi': re.compile('\\s*wuapi\\s*='),
    'dsapi': re.compile('\\s*dsapi\\s*='),
    'ccapi': re.compile('\\s*ccapi\\s*='),
    'owmapi': re.compile('\\s*owmapi\\s*='),
}
tmapi_re = re.compile('\\s*tmapi\\s*=')

print('\nChecking ' + apikeysFileName)
if os.path.isfile(apikeysFileName):
    altered = False
    foundtm = False
    newfile = ''
    apikeys = open(apikeysFileName, 'r')
    for aline in apikeys:
        if tmapi_re.match(aline):
            foundtm = True
        deprecated = False
        for name, pattern in deprecated_key_res.items():
            if pattern.match(aline):
                print('Removing ' + name + ' key from ' + apikeysFileName)
                altered = True
                deprecated = True
                break
        if not deprecated:
            newfile += aline
    apikeys.close()

    if not foundtm:
        print('\nThis version of PiClock requires a Tomorrow.io API key.')
        print('Get one at https://www.tomorrow.io/weather-api/')
        k = input('key: ')
        k = k.strip()
        if len(k) > 1:
            newfile += 'tmapi = \'' + k + '\'\n'
            altered = True

    if altered:
        print('\nWriting updated ' + apikeysFileName)
        apikeys = open(apikeysFileName, 'w')
        apikeys.write(newfile)
        apikeys.close()
    else:
        print('No changes made to ' + apikeysFileName)

# PiClock used to start from a ~/.config/autostart shortcut. It now prefers a
# systemd user service, which restarts the clock if it crashes and lets the web
# control panel restart it on demand. Both being set up at once is the failure
# worth catching here: each starts a clock at login and the two fight over the
# display.
AUTOSTART = os.path.expanduser('~/.config/autostart/PiClock.desktop')
USER_UNIT = os.path.expanduser('~/.config/systemd/user/piclock.service')


def ask(question, default_yes=True):
    """Prompt, treating a non-interactive run as 'no' rather than crashing."""
    try:
        answer = input(question + (' [Y/n] ' if default_yes else ' [y/N] ')).strip().lower()
    except EOFError:
        return False
    if not answer:
        return default_yes
    return answer.startswith('y')


def install_systemd_unit():
    """Write the user unit with this install's path baked in, then enable it."""
    template = os.path.join('systemd', 'piclock.service')
    if not os.path.isfile(template):
        print('WARNING: %s is missing, so the service was not set up.' % template)
        return False
    with open(template) as handle:
        text = handle.read().replace('__PICLOCK_DIR__', os.getcwd())
    os.makedirs(os.path.dirname(USER_UNIT), exist_ok=True)
    with open(USER_UNIT, 'w') as handle:
        handle.write(text)
    print('Wrote ' + USER_UNIT)
    os.system('systemctl --user daemon-reload')
    if os.system('systemctl --user enable --now piclock.service') != 0:
        # Starting needs a session bus, which a plain ssh login does not have.
        # Enabling alone still brings it up at the next graphical login.
        os.system('systemctl --user enable piclock.service')
        print('Enabled. The clock starts at your next graphical login.')
    return True


def remove_autostart():
    if not ask('Remove ' + AUTOSTART + '?'):
        print('Left in place. Until it goes, expect two clocks at login.')
        return
    os.remove(AUTOSTART)
    print('Removed. systemd now starts the clock on its own.')


print('\nChecking how the clock starts')
if not sys.platform.startswith('linux'):
    print('Not Linux, so there is no autostart entry to check.')
elif shutil.which('systemctl') is None:
    print('systemd is not available here; leaving the autostart entry alone.')
else:
    has_unit = os.path.isfile(USER_UNIT)
    has_autostart = os.path.isfile(AUTOSTART)
    if has_unit and has_autostart:
        print('Both piclock.service and the autostart shortcut are set up.')
        print('Each starts its own clock at login, and the two fight over the')
        print('display. The service should be the only one starting it.')
        remove_autostart()
    elif has_unit:
        print('Started by piclock.service. Nothing to clean up.')
    elif has_autostart:
        print('Started from ~/.config/autostart. A systemd service instead')
        print('would restart the clock if it crashed, and lets the web control')
        print('panel restart it on demand.')
        if ask('Switch to the systemd service?'):
            if install_systemd_unit():
                remove_autostart()
    else:
        print('No autostart shortcut and no service, so the clock is started')
        print('by hand.')
        if ask('Set up the systemd service?', default_yes=False):
            install_systemd_unit()

# A newer PiClock usually brings new Config.py settings with it. Offer to add
# the ones this install is missing, rather than leaving them to be found the
# hard way. Nothing is written without a yes, and a backup is taken first.
print('')
try:
    import merge_config
    merge_config.main(['--prompt'])
except Exception:
    print('WARNING: could not check for new config settings')
    print(traceback.format_exc())
