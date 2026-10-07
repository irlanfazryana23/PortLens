# Extract the CHANGELOG.md section for the version in VERSION, with download notes.
# Used by the release workflow. Prints the notes, or writes them to -OutFile.
[CmdletBinding()]
param(
    [string]$OutFile
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot

$version = (Get-Content -LiteralPath (Join-Path $projectRoot 'VERSION') -Raw).Trim()
$lines = @(Get-Content -LiteralPath (Join-Path $projectRoot 'CHANGELOG.md') -Encoding UTF8)
$heading = '^## \[' + [regex]::Escape($version) + '\]'

$start = -1
for ($i = 0; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match $heading) { $start = $i; break }
}
if ($start -lt 0) { throw "CHANGELOG.md has no entry for version $version." }

$end = $lines.Count
for ($i = $start + 1; $i -lt $lines.Count; $i++) {
    if ($lines[$i] -match '^## ') { $end = $i; break }
}
$body = ''
if ($end -gt ($start + 1)) { $body = ($lines[($start + 1)..($end - 1)] -join "`n").Trim() }

$notes = $body + "`n`n" +
    "### Download`n" +
    "- **PortLens-$version-portable.zip**: extract and run PortLens-$version.exe. No installation needed.`n" +
    "- **SHA256SUMS.txt**: SHA-256 hashes for the ZIP and the EXE.`n`n" +
    "The EXE is not code-signed, so Windows SmartScreen may show a warning the first time you run it.`n"

if ($OutFile) {
    [IO.File]::WriteAllText($OutFile, $notes, (New-Object System.Text.UTF8Encoding($false)))
} else {
    Write-Output $notes
}
