[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')),
    [string]$InnoSetupDir = (Join-Path $RepoRoot '.github\inno-setup'),
    [string]$WorkspaceDir = (Join-Path $RepoRoot 'examples\haitun-workspace')
)

$issPath = Join-Path $InnoSetupDir 'haitun.iss'
$issText = Get-Content -Raw -Encoding UTF8 $issPath
$match = [regex]::Match($issText, '#define\s+MyAppVersion\s+"([^"]+)"')
if (-not $match.Success) {
    throw "Could not parse MyAppVersion from $issPath"
}

$version = $match.Groups[1].Value
$baseUrl = [Environment]::GetEnvironmentVariable('HAITUN_DOWNLOAD_BASE_URL')
if ([string]::IsNullOrWhiteSpace($baseUrl)) {
    $baseUrl = ''
    Write-Warning 'HAITUN_DOWNLOAD_BASE_URL is not set; the built launcher will skip update checks.'
} else {
    $baseUrl = $baseUrl.TrimEnd('/')
}

$intervalHours = [Environment]::GetEnvironmentVariable('HAITUN_UPDATE_INTERVAL_HOURS')
if ([string]::IsNullOrWhiteSpace($intervalHours) -or
    $intervalHours -notmatch '^\d+$' -or
    [int]$intervalHours -le 0) {
    $intervalHours = '24'
}

$installerName = [Environment]::GetEnvironmentVariable('HAITUN_UPDATE_INSTALLER_NAME')
if ([string]::IsNullOrWhiteSpace($installerName)) {
    $installerName = 'HaiTun_Agent_Setup.exe'
}

$updateMode = [Environment]::GetEnvironmentVariable('HAITUN_UPDATE_MODE')
if ([string]::IsNullOrWhiteSpace($updateMode)) {
    $updateMode = ''
}

if (-not (Test-Path $WorkspaceDir)) {
    New-Item -ItemType Directory -Path $WorkspaceDir -Force | Out-Null
}

$confPath = Join-Path $WorkspaceDir 'haitun-update.conf'
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
$confLines = @(
    "HAITUN_VERSION=$version",
    "HAITUN_UPDATE_BASE_URL=$baseUrl",
    "HAITUN_UPDATE_INTERVAL_HOURS=$intervalHours",
    "HAITUN_UPDATE_INSTALLER_NAME=$installerName"
)
if (-not [string]::IsNullOrWhiteSpace($updateMode)) {
    $confLines += "HAITUN_UPDATE_MODE=$updateMode"
}
[System.IO.File]::WriteAllLines($confPath, $confLines, $utf8NoBom)

if ([string]::IsNullOrWhiteSpace($updateMode)) {
    Write-Host "Wrote $confPath (version=$version, mode=legacy)"
} else {
    Write-Host "Wrote $confPath (version=$version, mode=$updateMode)"
}

Push-Location $InnoSetupDir
try {
    rc /nologo 'haitun.rc'
    if ($LASTEXITCODE -ne 0) {
        throw "rc failed with exit code $LASTEXITCODE"
    }
    cl /nologo /O2 /utf-8 'haitun.c' 'haitun.res' /Fe:'haitun.exe' /link /SUBSYSTEM:WINDOWS user32.lib shell32.lib wininet.lib urlmon.lib ole32.lib gdi32.lib
    if ($LASTEXITCODE -ne 0) {
        throw "cl failed with exit code $LASTEXITCODE"
    }
    cl /nologo /O2 /utf-8 'haitun-updater.c' /Fe:'haitun-updater.exe' /link /SUBSYSTEM:WINDOWS /ENTRY:wmainCRTStartup kernel32.lib user32.lib
    if ($LASTEXITCODE -ne 0) {
        throw "cl failed with exit code $LASTEXITCODE"
    }
} finally {
    Pop-Location
}
