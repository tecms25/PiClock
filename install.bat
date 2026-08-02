@echo off
setlocal enabledelayedexpansion

:: Installer for PiClock (Windows) - standard software-only setup.
:: Sets up the virtual environment, Python packages, and config files needed
:: to run the clock, weather, radar, slideshow, and NOAA alert features.
:: Does NOT set up the optional GPIO buttons - those are a Raspberry Pi-only
:: add-on and are not applicable on Windows.

cd /d "%~dp0"

:: Trailing backslash stripped so it's safe to pass to an external exe as a
:: quoted argument (a backslash right before a closing quote gets parsed as
:: an escaped quote by Windows' argv parser, e.g. for powershell.exe).
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

echo === PiClock Installer ===

where python >nul 2>nul
if errorlevel 1 (
    echo ERROR: python was not found on PATH. Install Python 3 from https://www.python.org/downloads/ and try again.
    exit /b 1
)

set HAVE_POWERSHELL=1
where powershell >nul 2>nul
if errorlevel 1 set HAVE_POWERSHELL=0

if exist "venv\Scripts\activate.bat" (
    echo Virtual environment already exists, reusing it.
) else (
    echo Creating virtual environment...
    python -m venv venv
    if errorlevel 1 exit /b 1
)

echo Activating virtual environment...
call venv\Scripts\activate.bat

echo.
echo Upgrading pip...
python -m pip install --upgrade pip

echo.
echo Installing PyQt6...
python -m pip install PyQt6
if errorlevel 1 goto :error

echo.
echo Installing required Python packages...
python -m pip install -r requirements.txt
if errorlevel 1 goto :error

call venv\Scripts\deactivate.bat

if exist "fonts\*.ttf" (
    if "%HAVE_POWERSHELL%"=="1" (
        powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%\install_fonts.ps1" -RepoDir "%SCRIPT_DIR%"
    ) else (
        echo.
        echo powershell was not found - skipping bundled font install.
    )
)

set NEW_APIKEYS=0
set NEW_CONFIG=0

if not exist "conf\ApiKeys.py" (
    copy /y "conf\ApiKeys-example.py" "conf\ApiKeys.py" >nul
    set NEW_APIKEYS=1
    echo.
    echo Created conf\ApiKeys.py from the example.
) else (
    echo.
    echo conf\ApiKeys.py already exists, leaving it alone.
)

if not exist "conf\Config.py" (
    copy /y "conf\Config-Example.py" "conf\Config.py" >nul
    set NEW_CONFIG=1
    echo Created conf\Config.py from the example.
) else (
    echo conf\Config.py already exists, leaving it alone.
)

echo.
if "%HAVE_POWERSHELL%"=="0" (
    echo powershell was not found - skipping interactive configuration.
    echo Edit conf\ApiKeys.py and conf\Config.py manually.
    goto :after_configure
)

set DOCONFIGURE=0
if "%NEW_APIKEYS%%NEW_CONFIG%" NEQ "00" (
    set /p DOCONFIG="Interactively configure your API keys and Config.py settings now? [Y/n] "
    if /i "!DOCONFIG!"=="n" (set DOCONFIGURE=0) else (set DOCONFIGURE=1)
) else (
    set /p DOCONFIG="conf\ApiKeys.py and/or conf\Config.py already exist. Interactively reconfigure them now? [y/N] "
    if /i "!DOCONFIG!"=="y" (set DOCONFIGURE=1) else (set DOCONFIGURE=0)
)

if "!DOCONFIGURE!"=="1" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%\install_configure.ps1" -RepoDir "%SCRIPT_DIR%"
    if errorlevel 1 (
        echo.
        echo Interactive configuration failed - edit conf\ApiKeys.py and conf\Config.py manually.
    )
)

:after_configure
echo.
echo === Install complete ===
echo Next steps:
echo   1. Double check conf\ApiKeys.py and conf\Config.py have what you expect.
echo      (Rerun this script if you skipped the interactive configuration.)
echo   2. Test it:
echo        venv\Scripts\activate
echo        cd Clock
echo        python PyQtPiClock.py
echo.
echo See Documentation\Install-Clock-Only.md for details.
goto :eof

:error
echo.
echo Install failed. See the error above.
exit /b 1
