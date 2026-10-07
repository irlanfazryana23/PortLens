# Build the portable PortLens package. Compiles and packages only; never launches the app.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\build.ps1 [-SkipInstall]
[CmdletBinding()]
param(
    # Skip "pip install" when the build dependencies are already installed (CI does this).
    [switch]$SkipInstall
)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot

$version = (Get-Content -LiteralPath (Join-Path $projectRoot 'VERSION') -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'VERSION must contain major.minor.patch, for example 1.0.0.' }

$python = (Get-Command python -ErrorAction Stop).Source
if (-not $SkipInstall) {
    & $python -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'requirements-dev.txt')
    if ($LASTEXITCODE -ne 0) { throw "Installing build dependencies failed (exit code $LASTEXITCODE)." }
}

$outputDirectory = Join-Path $projectRoot 'dist'
New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null
$executableName = 'PortLens-' + $version + '.exe'
$archiveName = 'PortLens-' + $version + '-portable.zip'
$executable = Join-Path $outputDirectory $executableName
$archivePath = Join-Path $outputDirectory $archiveName
$checksumPath = Join-Path $outputDirectory 'SHA256SUMS.txt'
# Remove only this version's previous outputs so stale files are never packaged.
foreach ($stale in @($executable, $archivePath, $checksumPath)) {
    if (Test-Path -LiteralPath $stale) { Remove-Item -LiteralPath $stale -Force }
}

& $python -m PyInstaller (Join-Path $projectRoot 'PortLens.spec') --noconfirm --clean `
    --distpath $outputDirectory --workpath (Join-Path $projectRoot 'build')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed (exit code $LASTEXITCODE)." }
if (-not (Test-Path -LiteralPath $executable)) { throw "Expected build output was not created: $executableName" }

# Package: EXE + documents + the EXE checksum.
$packageFiles = @($executable)
foreach ($document in @('README.md', 'LICENSE', 'CHANGELOG.md')) {
    $destination = Join-Path $outputDirectory $document
    Copy-Item -LiteralPath (Join-Path $projectRoot $document) -Destination $destination -Force
    $packageFiles += $destination
}
$digest = (Get-FileHash -LiteralPath $executable -Algorithm SHA256).Hash
Set-Content -LiteralPath $checksumPath -Value ($digest + '  ' + $executableName) -Encoding ASCII
$packageFiles += $checksumPath
Compress-Archive -LiteralPath $packageFiles -DestinationPath $archivePath -Force

# The ZIP contains its EXE checksum; the standalone file also covers the ZIP.
$archiveDigest = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash
Add-Content -LiteralPath $checksumPath -Value ($archiveDigest + '  ' + $archiveName) -Encoding ASCII

Write-Host 'Build complete. The application was not launched.'
Write-Host $executable
