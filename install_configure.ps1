# Interactive configuration step for install.bat.
# Prompts for the main PiClock settings and writes them into Clock\Config.py
# and Clock\ApiKeys.py, which install.bat has already created from the
# example files.

param([string]$RepoDir = $PSScriptRoot)

$ErrorActionPreference = 'Stop'
Set-Location $RepoDir

$ConfigPath = Join-Path $RepoDir 'Clock\Config.py'
$KeysPath = Join-Path $RepoDir 'Clock\ApiKeys.py'

function Set-PyLine {
    param([string]$Path, [string]$Pattern, [string]$Replacement)
    $found = $false
    $content = Get-Content -Path $Path | ForEach-Object {
        if (-not $found -and $_ -match $Pattern) { $found = $true; $Replacement } else { $_ }
    }
    Set-Content -Path $Path -Value $content
}

function PyStr([string]$s) {
    $escaped = $s.Replace('\', '\\').Replace('"', '\"')
    return '"' + $escaped + '"'
}

function Read-YesNo([string]$prompt, [bool]$defaultYes) {
    $suffix = if ($defaultYes) { '[Y/n]' } else { '[y/N]' }
    $answer = Read-Host "$prompt $suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $defaultYes }
    return $answer.Trim().ToLower() -eq 'y'
}

Write-Host ""
Write-Host "--- Location ---"
# Example numbers for the prompts, regenerated each run so a real address is
# never hardcoded into this script.
$exampleLat = "{0}.{1:D4}" -f (Get-Random -Minimum -90 -Maximum 90), (Get-Random -Minimum 0 -Maximum 10000)
$exampleLon = "{0}.{1:D4}" -f (Get-Random -Minimum -180 -Maximum 180), (Get-Random -Minimum 0 -Maximum 10000)
do {
    $lat = Read-Host "Latitude (decimal degrees, e.g. $exampleLat)"
} while ($lat -notmatch '^-?[0-9]+(\.[0-9]+)?$')
do {
    $lon = Read-Host "Longitude (decimal degrees, e.g. $exampleLon)"
} while ($lon -notmatch '^-?[0-9]+(\.[0-9]+)?$')
Set-PyLine -Path $ConfigPath -Pattern '^primary_coordinates *=' -Replacement "primary_coordinates = $lat, $lon  # Change to your Lat/Lon"

Write-Host ""
Write-Host "--- Units ---"
$useMetric = Read-YesNo "Use metric units instead of imperial?" $false
$metricVal = if ($useMetric) { 1 } else { 0 }
Set-PyLine -Path $ConfigPath -Pattern '^metric *=' -Replacement "metric = $metricVal  # 0 = English, 1 = Metric"

Write-Host ""
Write-Host "--- Weather ---"
$tmapi = Read-Host "Tomorrow.io API key (https://www.tomorrow.io/weather-api/, blank to skip)"
if ($tmapi) {
    Set-PyLine -Path $KeysPath -Pattern '^#? *tmapi *=' -Replacement "tmapi = $(PyStr $tmapi)"
}

Write-Host ""
Write-Host "--- Maps ---"
Write-Host "1) Mapbox (recommended - supports custom map styles)"
Write-Host "2) Google Maps"
$mapChoice = Read-Host "Choose a map provider [1]"
if ([string]::IsNullOrWhiteSpace($mapChoice)) { $mapChoice = '1' }
if ($mapChoice -eq '2') {
    $googleapi = Read-Host "Google Maps API key (blank to skip)"
    if ($googleapi) {
        Set-PyLine -Path $KeysPath -Pattern '^#? *googleapi *=' -Replacement "googleapi = $(PyStr $googleapi)"
    }
} else {
    $mbapi = Read-Host "Mapbox access token (https://www.mapbox.com/signup/, blank to skip)"
    if ($mbapi) {
        Set-PyLine -Path $KeysPath -Pattern '^#? *mbapi *=' -Replacement "mbapi = $(PyStr $mbapi)"

        $mapBase = Read-Host "Custom Mapbox base map style (e.g. username/style-id, blank for Mapbox's default satellite style)"
        if ($mapBase) {
            Set-PyLine -Path $ConfigPath -Pattern '^map_base *=' -Replacement "map_base = $(PyStr $mapBase)  # blank uses Mapbox's default 'mapbox/satellite-streets-v12'; or your own custom style, see below"
        }
        $mapOverlay = Read-Host "Custom Mapbox overlay style, e.g. for labels/roads/borders (blank to disable)"
        if ($mapOverlay) {
            Set-PyLine -Path $ConfigPath -Pattern '^map_overlay *=' -Replacement "map_overlay = $(PyStr $mapOverlay)  # optional custom overlay style (labels/roads/borders only); blank disables the overlay"
        }
        Write-Host "See Clock\Config.py (map_base/map_overlay, radar1-4) to customize further."
    }
}

Write-Host ""
Write-Host "--- NOAA weather radio stream (F2 key) ---"
$noaastream = Read-Host "NOAA weather radio stream URL (blank to keep default)"
if ($noaastream) {
    Set-PyLine -Path $ConfigPath -Pattern '^noaastream *=' -Replacement "noaastream = $(PyStr $noaastream) # Change to local NOAA stream"
}

Write-Host ""
Write-Host "--- Slideshow ---"
$useSlideshow = Read-YesNo "Enable background slideshow?" $true
if (-not $useSlideshow) {
    Set-PyLine -Path $ConfigPath -Pattern '^useslideshow *=' -Replacement "useslideshow = 0  # 1 to enable, 0 to disable"
} else {
    Set-PyLine -Path $ConfigPath -Pattern '^useslideshow *=' -Replacement "useslideshow = 1  # 1 to enable, 0 to disable"
    Write-Host "1) Local images from PiClock\Pictures\Slideshow"
    Write-Host "2) Web playlist (a URL to a text file listing one image URL per line)"
    Write-Host "3) Shared iCloud album"
    $slideChoice = Read-Host "Choose a slideshow source [1]"
    if ([string]::IsNullOrWhiteSpace($slideChoice)) { $slideChoice = '1' }
    if ($slideChoice -eq '2') {
        Set-PyLine -Path $ConfigPath -Pattern '^web_slideshow_playlist *=' -Replacement "web_slideshow_playlist = 1"
        $slideUrl = Read-Host "Slideshow playlist URL"
        if ($slideUrl) {
            Set-PyLine -Path $ConfigPath -Pattern '^slideshow_url *=' -Replacement "slideshow_url = $(PyStr $slideUrl) # must be text file, one image url per line"
        }
    } elseif ($slideChoice -eq '3') {
        Set-PyLine -Path $ConfigPath -Pattern '^web_slideshow_playlist *=' -Replacement "web_slideshow_playlist = 2"
        Write-Host "In Photos: create an album, share it, turn on 'Public Website', and copy the link."
        Write-Host "Anyone with that link can view the album, so don't use it for private photos."
        do {
            $icloudAlbum = Read-Host "Shared iCloud album link (blank to skip)"
            if (-not $icloudAlbum) { break }
            if ($icloudAlbum -match '#.+') {
                Set-PyLine -Path $ConfigPath -Pattern '^slideshow_icloud_album *=' -Replacement "slideshow_icloud_album = $(PyStr $icloudAlbum)"
                break
            }
            Write-Host "That doesn't look like a share link. Expected something like"
            Write-Host "  https://www.icloud.com/sharedalbum/#B0Xabc123"
        } while ($true)
    } else {
        Set-PyLine -Path $ConfigPath -Pattern '^web_slideshow_playlist *=' -Replacement "web_slideshow_playlist = 0"
    }
}

Write-Host ""
Write-Host "--- Severe weather alerts ---"
$useAlerts = Read-YesNo "Enable NOAA/NWS severe weather alert bubble?" $true
$alertVal = if ($useAlerts) { 1 } else { 0 }
Set-PyLine -Path $ConfigPath -Pattern '^noaa_alerts_enabled *=' -Replacement "noaa_alerts_enabled = $alertVal  # 1 to show a warning bubble for active NOAA/NWS alerts, 0 to disable"

Write-Host ""
Write-Host "--- Screen Brightness ---"
$dimEnabled = Read-YesNo "Automatically dim the display at night?" $true
if (-not $dimEnabled) {
    Set-PyLine -Path $ConfigPath -Pattern '^brightness_enabled *=' -Replacement "brightness_enabled = 0  # 1 to enable time-based dimming, 0 to always use day_brightness"
} else {
    Set-PyLine -Path $ConfigPath -Pattern '^brightness_enabled *=' -Replacement "brightness_enabled = 1  # 1 to enable time-based dimming, 0 to always use day_brightness"

    do {
        $dayBrightInput = Read-Host "Daytime brightness percentage (0-100) [100]"
        if ([string]::IsNullOrWhiteSpace($dayBrightInput)) { $dayBrightInput = '100' }
    } while ($dayBrightInput -notmatch '^[0-9]+$' -or [int]$dayBrightInput -gt 100)
    Set-PyLine -Path $ConfigPath -Pattern '^day_brightness *=' -Replacement "day_brightness = $dayBrightInput  # 0-100, brightness percentage during the day"

    do {
        $nightBrightInput = Read-Host "Nighttime brightness percentage (0-100) [30]"
        if ([string]::IsNullOrWhiteSpace($nightBrightInput)) { $nightBrightInput = '30' }
    } while ($nightBrightInput -notmatch '^[0-9]+$' -or [int]$nightBrightInput -gt 100)
    Set-PyLine -Path $ConfigPath -Pattern '^night_brightness *=' -Replacement "night_brightness = $nightBrightInput  # 0-100, brightness percentage at night"

    do {
        $dayStart = Read-Host "Time day brightness begins, 24-hour HH:MM [07:00]"
        if ([string]::IsNullOrWhiteSpace($dayStart)) { $dayStart = '07:00' }
    } while ($dayStart -notmatch '^([01][0-9]|2[0-3]):[0-5][0-9]$')
    Set-PyLine -Path $ConfigPath -Pattern '^day_start *=' -Replacement "day_start = $(PyStr $dayStart)  # 24-hour clock (HH:MM) when day_brightness begins"

    do {
        $nightStart = Read-Host "Time night brightness begins, 24-hour HH:MM [22:00]"
        if ([string]::IsNullOrWhiteSpace($nightStart)) { $nightStart = '22:00' }
    } while ($nightStart -notmatch '^([01][0-9]|2[0-3]):[0-5][0-9]$')
    Set-PyLine -Path $ConfigPath -Pattern '^night_start *=' -Replacement "night_start = $(PyStr $nightStart)  # 24-hour clock (HH:MM) when night_brightness begins"

    do {
        $transMin = Read-Host "Minutes to fade gradually between day/night brightness, 0 for instant [30]"
        if ([string]::IsNullOrWhiteSpace($transMin)) { $transMin = '30' }
    } while ($transMin -notmatch '^[0-9]+$')
    Set-PyLine -Path $ConfigPath -Pattern '^brightness_transition_minutes *=' -Replacement "brightness_transition_minutes = $transMin  # minutes to gradually fade between day/night brightness; 0 for an instant switch"
}

$keepAwake = Read-YesNo "Keep the display always on (prevent OS screensaver/sleep while PiClock runs)?" $true
$keepAwakeVal = if ($keepAwake) { 1 } else { 0 }
Set-PyLine -Path $ConfigPath -Pattern '^prevent_screen_sleep *=' -Replacement "prevent_screen_sleep = $keepAwakeVal  # 1 to enable, 0 to disable"

Write-Host ""
Write-Host "Configuration saved to Clock\Config.py and Clock\ApiKeys.py."
