# Static verification of the built package. Never launches the app.
# Usage: powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\verify.ps1
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

$version = (Get-Content -LiteralPath (Join-Path $projectRoot 'VERSION') -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'VERSION must contain major.minor.patch.' }
$exeName = 'PortLens-' + $version + '.exe'
$zipName = 'PortLens-' + $version + '-portable.zip'
$outputDirectory = Join-Path $projectRoot 'dist'
Add-Type -AssemblyName System.IO.Compression.FileSystem

# 1. PowerShell scripts parse cleanly.
foreach ($script in @('build.ps1', 'scripts\verify.ps1', 'scripts\release_notes.ps1')) {
    $tokens = $null
    $parseErrors = $null
    [System.Management.Automation.Language.Parser]::ParseFile((Join-Path $projectRoot $script), [ref]$tokens, [ref]$parseErrors) | Out-Null
    if ($parseErrors.Count) { throw ($script + ': ' + ($parseErrors -join "`n")) }
}

# 2. The changelog has an entry for this version.
$changelog = Get-Content -LiteralPath (Join-Path $projectRoot 'CHANGELOG.md') -Raw
if ($changelog -notmatch ('(?m)^## \[' + [regex]::Escape($version) + '\]')) { throw "CHANGELOG.md has no entry for $version." }

# 3. The EXE exists and carries the right Windows version information.
$exePath = Join-Path $outputDirectory $exeName
if (-not (Test-Path -LiteralPath $exePath)) { throw "Missing $exeName. Run build.ps1 first." }
$info = (Get-Item -LiteralPath $exePath).VersionInfo
if ($info.FileVersion -ne ($version + '.0')) { throw "EXE file version '$($info.FileVersion)' does not match VERSION $version." }
if ($info.ProductName -ne 'PortLens') { throw "Unexpected product name '$($info.ProductName)'." }

# 4. Checksums cover the EXE and the ZIP.
$checksumLines = @(Get-Content -LiteralPath (Join-Path $outputDirectory 'SHA256SUMS.txt'))
if ($checksumLines.Count -ne 2) { throw 'Expected EXE and ZIP checksums.' }
foreach ($fileName in @($exeName, $zipName)) {
    $hash = (Get-FileHash -LiteralPath (Join-Path $outputDirectory $fileName) -Algorithm SHA256).Hash
    if ($checksumLines -notcontains ($hash + '  ' + $fileName)) { throw "Invalid checksum for $fileName." }
}

# 5. The ZIP contains exactly the expected files, identical to the sources.
$expectedEntries = @($exeName, 'README.md', 'LICENSE', 'CHANGELOG.md', 'SHA256SUMS.txt')
$archive = [IO.Compression.ZipFile]::OpenRead((Join-Path $outputDirectory $zipName))
try {
    if ($archive.Entries.Count -ne $expectedEntries.Count) { throw 'Unexpected package contents.' }
    foreach ($entryName in $expectedEntries) {
        $entry = $archive.GetEntry($entryName)
        if ($null -eq $entry) { throw "Missing package entry: $entryName" }
        $stream = $entry.Open()
        try {
            if ($entryName -eq 'SHA256SUMS.txt') {
                $textReader = New-Object IO.StreamReader($stream)
                try { $embeddedChecksum = $textReader.ReadToEnd().Trim() } finally { $textReader.Dispose() }
                $exeHash = (Get-FileHash -LiteralPath $exePath -Algorithm SHA256).Hash
                if ($embeddedChecksum -ne ($exeHash + '  ' + $exeName)) { throw 'Invalid embedded EXE checksum.' }
            } else {
                $sha = [Security.Cryptography.SHA256]::Create()
                try { $entryHash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '') } finally { $sha.Dispose() }
                $originalPath = if ($entryName -eq $exeName) { $exePath } else { Join-Path $projectRoot $entryName }
                if ($entryHash -ne (Get-FileHash -LiteralPath $originalPath -Algorithm SHA256).Hash) { throw "Package entry differs from source: $entryName" }
            }
        } finally { $stream.Dispose() }
    }
} finally { $archive.Dispose() }

Write-Host "Static verification passed for version $version."
Write-Host 'Checked script syntax, changelog entry, EXE version information, package contents, and hashes.'
Write-Host 'The application was not launched.'
