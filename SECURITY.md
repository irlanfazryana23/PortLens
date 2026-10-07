# Security policy

## Reporting a vulnerability

Please report security problems privately through GitHub's **Report a vulnerability** option on the repository's Security tab, instead of opening a public issue. Include the PortLens version, your Windows version, and steps to reproduce.

## What PortLens does on your PC

- It reads printer, port and USB device information from Windows (through the Windows print API and short PowerShell commands).
- For network printers it sends a single `ping` to the printer's address to check that it answers.
- It can change the Windows default printer, open the Windows printer properties or queue, and print a test page, only when you choose those actions.
- It does not send data over the internet and has no telemetry.
- It stores your sort and filter choices in `%APPDATA%\PortLens\settings.json`.

## Supported versions

Security fixes go into the latest release.

## Release files

Release EXEs are not code-signed. Compare the download with `SHA256SUMS.txt` on the release page before running it.
