# Installs the bundled fonts (fonts\*.ttf) for the current Windows user -
# no administrator rights required. Mirrors what install.sh does on
# Linux/macOS: PiClock's stylesheets reference "Open Sans" by family name,
# so the font needs to be registered with the OS, not just present on disk.

param([string]$RepoDir = $PSScriptRoot)

$ErrorActionPreference = 'Stop'
$fontsDir = Join-Path $RepoDir 'fonts'

if (-not (Test-Path $fontsDir)) {
    exit 0
}

$ttfFiles = Get-ChildItem -Path $fontsDir -Filter '*.ttf' -ErrorAction SilentlyContinue
if (-not $ttfFiles) {
    exit 0
}

Add-Type -AssemblyName System.Drawing

$userFontsDir = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Fonts'
New-Item -ItemType Directory -Path $userFontsDir -Force | Out-Null
$regPath = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts'

Write-Host ""
Write-Host "Installing bundled fonts..."
foreach ($font in $ttfFiles) {
    $destPath = Join-Path $userFontsDir $font.Name
    Copy-Item -Path $font.FullName -Destination $destPath -Force

    $collection = New-Object System.Drawing.Text.PrivateFontCollection
    $collection.AddFontFile($destPath)
    $familyName = $collection.Families[0].Name

    New-ItemProperty -Path $regPath -Name "$familyName (TrueType)" -Value $destPath -PropertyType String -Force | Out-Null
    Write-Host "Installed font: $familyName ($($font.Name))"
}
Write-Host "Fonts installed for the current user."
