import json
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
UNIT_DIR = os.path.expanduser('~/.config/systemd/user')


def unit_path(name):
    return os.path.join(UNIT_DIR, name)


def ask(question, default_yes=True):
    """Prompt, treating a non-interactive run as 'no' rather than crashing."""
    try:
        answer = input(question + (' [Y/n] ' if default_yes else ' [y/N] ')).strip().lower()
    except EOFError:
        return False
    if not answer:
        return default_yes
    return answer.startswith('y')


def install_systemd_unit(name, late_note):
    """Write one of the repo's unit templates with this install's path baked
    in, then enable it. late_note is what to say when it could only be enabled
    rather than started."""
    template = os.path.join('systemd', name)
    if not os.path.isfile(template):
        print('WARNING: %s is missing, so the service was not set up.' % template)
        return False
    with open(template) as handle:
        text = handle.read().replace('__PICLOCK_DIR__', os.getcwd())
    os.makedirs(UNIT_DIR, exist_ok=True)
    with open(unit_path(name), 'w') as handle:
        handle.write(text)
    print('Wrote ' + unit_path(name))
    os.system('systemctl --user daemon-reload')
    if os.system('systemctl --user enable --now ' + name) != 0:
        # Starting needs a session bus, which a plain ssh login does not have.
        # Enabling alone still brings it up at the next login.
        os.system('systemctl --user enable ' + name)
        print(late_note)
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
    has_unit = os.path.isfile(unit_path('piclock.service'))
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
            if install_systemd_unit('piclock.service',
                                    'Enabled. The clock starts at your next '
                                    'graphical login.'):
                remove_autostart()
    else:
        print('No autostart shortcut and no service, so the clock is started')
        print('by hand.')
        if ask('Set up the systemd service?', default_yes=False):
            install_systemd_unit('piclock.service',
                                 'Enabled. The clock starts at your next '
                                 'graphical login.')

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

# The web control panel opens a listening socket, so an update never switches
# it on by itself - it is offered, and defaults to no. This runs after the
# config merge above because web_enabled only exists in Config.py once that has
# added it.
CONFIG = os.path.join('conf', 'Config.py')
WEB_CERT = os.path.join('conf', 'web-cert.pem')
WEB_KEY = os.path.join('conf', 'web-key.pem')
WEB_SECRET = os.path.join('conf', 'web_secret.json')
WEB_UNIT = 'piclock-web.service'


def config_value(name, default=None):
    """One setting read out of Config.py without executing it."""
    try:
        import merge_config
        text, _ = merge_config.read_text(CONFIG)
        return merge_config.literal_settings(text).get(name, default)
    except Exception:
        return default


def enable_web_in_config():
    """Set web_enabled = 1, keeping the file's comments and line endings."""
    try:
        import merge_config
        text, newline = merge_config.read_text(CONFIG)
    except Exception:
        print('WARNING: could not read ' + CONFIG)
        return False
    replacement = 'web_enabled = 1  # 1 to enable, 0 to disable'
    pattern = re.compile(r'^web_enabled\s*=.*$', re.M)
    if pattern.search(text):
        text = pattern.sub(replacement, text, count=1)
    else:
        # An install that declined the config merge above has no such setting
        # yet. Appending it beats leaving the panel unable to start.
        text = text.rstrip('\n') + '\n\n' + replacement + '\n'
    merge_config.write_text(CONFIG, text, newline)
    print('Set web_enabled = 1 in ' + CONFIG)
    return True


def web_password_set():
    try:
        with open(WEB_SECRET) as handle:
            return bool(json.load(handle).get('password_hash'))
    except (OSError, ValueError, AttributeError):
        return False


print('\nChecking the web control panel')
if not os.path.isfile(CONFIG):
    print('There is no conf/Config.py yet, so there is nothing to set up.')
else:
    have_cert = os.path.isfile(WEB_CERT) and os.path.isfile(WEB_KEY)
    have_password = web_password_set()
    web_on = bool(int(config_value('web_enabled', 0) or 0))
    systemd_here = bool(sys.platform.startswith('linux')
                        and shutil.which('systemctl'))
    have_unit = os.path.isfile(unit_path(WEB_UNIT))

    missing = []
    if not have_cert:
        missing.append('a TLS certificate')
    if not have_password:
        missing.append('a password')
    if not web_on:
        missing.append('web_enabled = 1')
    if systemd_here and not have_unit:
        missing.append('its systemd service')

    if not missing:
        print('Already set up, on port %s.' % config_value('web_port', 8443))
        # The panel is running last release's code until it is restarted, and
        # restarting costs nothing: the session key is stored, so nobody is
        # signed out by it.
        if systemd_here and os.system(
                'systemctl --user is-active --quiet ' + WEB_UNIT) == 0:
            os.system('systemctl --user restart ' + WEB_UNIT)
            print("Restarted it so it is running this update's code.")
    else:
        print('An HTTPS page for checking on the clock from another machine on')
        print('your network. It answers private (RFC 1918) addresses only, and')
        print('always needs a password.')
        print('Still needed: ' + ', '.join(missing) + '.')
        if ask('Set the web control panel up now?', default_yes=False):
            done = True
            if not have_cert:
                print('')
                done = os.system('bash web/make_cert.sh') == 0
            if done and not have_password:
                print('')
                done = os.system('"%s" web/set_password.py' % sys.executable) == 0
            if done and not web_on:
                done = enable_web_in_config()
            if done and systemd_here and not have_unit:
                install_systemd_unit(
                    WEB_UNIT, 'Enabled. The panel starts at your next login.')
            if done:
                print('\nThe panel is at https://<this machine>:%s/'
                      % config_value('web_port', 8443))
                print('The certificate is self-signed, so your browser asks you')
                print('to accept it the first time.')
                if not systemd_here:
                    print('Start it with: %s web/app.py' % sys.executable)
            else:
                print('\nSetup did not finish. Run update.sh again, or follow')
                print('the web control panel section of Documentation/Install.md')
