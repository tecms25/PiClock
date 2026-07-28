import os
import re
import traceback

os.chdir(os.path.dirname(os.path.abspath(__file__)))

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

apikeysFileName = 'Clock/ApiKeys.py'
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

    try:
        from rpi_ws281x import *  # NOQA
    except ModuleNotFoundError:
        print('\nERROR: rpi_ws281x not found')
        print('NeoAmbi.py now uses rpi-ws281x/rpi-ws281x-python')
        print('Please install it as follows:')
        print('python3 -m pip install rpi_ws281x')

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
