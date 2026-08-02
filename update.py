import os
import re
import shutil
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
