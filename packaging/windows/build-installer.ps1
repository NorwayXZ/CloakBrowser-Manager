# Build "CloakBrowser Manager.exe" and its per-user installer.
#
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build-installer.ps1
#
# Needs Python 3.10+, Node.js 18+ and Inno Setup 6 (ISCC.exe).
# Output: build\windows\CloakBrowser-Manager-<version>-windows-x64-setup.exe
# Only touches build\windows and frontend\dist; never the profile data directory.
$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Here = Join-Path $Root "packaging\windows"
$Build = Join-Path $Root "build\windows"
$Venv = Join-Path $Build "venv"
$Python = Join-Path $Venv "Scripts\python.exe"

function Invoke-Checked {
    param([string]$File, [string[]]$Arguments)
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$File failed with exit code $LASTEXITCODE" }
}

$Version = $env:CLOAKBROWSER_APP_VERSION
if (-not $Version) {
    $Version = (git -C $Root tag --list "v[0-9]*" --sort=-v:refname | Select-Object -First 1) -replace "^v", ""
}
if (-not $Version) { $Version = "0.0.0" }
$BuildNumber = (git -C $Root rev-list --count HEAD)
$Commit = (git -C $Root rev-parse --short HEAD)
Write-Host "[build] version $Version build $BuildNumber ($Commit)"

New-Item -ItemType Directory -Force -Path $Build | Out-Null
@{ version = $Version; build = "$BuildNumber"; commit = "$Commit" } |
    ConvertTo-Json -Compress | Set-Content -Encoding utf8 (Join-Path $Build "app_version.json")

Write-Host "[build] frontend"
Push-Location (Join-Path $Root "frontend")
try {
    Invoke-Checked "npm.cmd" @("ci", "--no-audit", "--no-fund")
    Invoke-Checked "npm.cmd" @("run", "build")
} finally {
    Pop-Location
}

if (-not (Test-Path $Python)) {
    Write-Host "[build] creating build venv"
    Invoke-Checked "python" @("-m", "venv", $Venv)
}
Invoke-Checked $Python @(
    "-m", "pip", "install", "-q", "--disable-pip-version-check",
    "-r", (Join-Path $Root "backend\requirements.txt"),
    "-r", (Join-Path $Here "requirements-build.txt"),
    "-c", (Join-Path $Root "packaging\constraints.txt")
)

Write-Host "[build] icon"
Invoke-Checked $Python @(
    (Join-Path $Root "packaging\make_icon.py"),
    (Join-Path $Build "app_icon.png"),
    (Join-Path $Build "AppIcon.ico")
)

Write-Host "[build] app"
Invoke-Checked $Python @(
    "-m", "PyInstaller", "--noconfirm", "--clean",
    "--distpath", (Join-Path $Build "dist"), "--workpath", (Join-Path $Build "work"),
    (Join-Path $Here "CloakBrowserManager.spec")
)

Write-Host "[build] installer"
$Iscc = $env:ISCC
if (-not $Iscc) {
    $Iscc = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if (-not $Iscc) { throw "Inno Setup 6 (ISCC.exe) not found. Install it from https://jrsoftware.org/isinfo.php" }
Invoke-Checked $Iscc @(
    "/Q",
    "/DAppVersion=$Version",
    "/DSourceDir=$(Join-Path $Build 'dist\CloakBrowser Manager')",
    "/DOutputDir=$Build",
    "/DIconFile=$(Join-Path $Build 'AppIcon.ico')",
    (Join-Path $Here "installer.iss")
)

Write-Host "[done] $(Join-Path $Build "CloakBrowser-Manager-$Version-windows-x64-setup.exe")"
