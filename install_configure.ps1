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
do {
    $lat = Read-Host "Latitude (decimal degrees, e.g. 42.8045)"
} while ($lat -notmatch '^-?[0-9]+(\.[0-9]+)?$')
do {
    $lon = Read-Host "Longitude (decimal degrees, e.g. -77.7871)"
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
        Write-Host "Using the default Mapbox satellite style; see Clock\Config.py (map_base/map_overlay, radar1-4) to customize further."
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
    $slideChoice = Read-Host "Choose a slideshow source [1]"
    if ([string]::IsNullOrWhiteSpace($slideChoice)) { $slideChoice = '1' }
    if ($slideChoice -eq '2') {
        Set-PyLine -Path $ConfigPath -Pattern '^web_slideshow_playlist *=' -Replacement "web_slideshow_playlist = 1"
        $slideUrl = Read-Host "Slideshow playlist URL"
        if ($slideUrl) {
            Set-PyLine -Path $ConfigPath -Pattern '^slideshow_url *=' -Replacement "slideshow_url = $(PyStr $slideUrl) # must be text file, one image url per line"
        }
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
Write-Host "Configuration saved to Clock\Config.py and Clock\ApiKeys.py."
