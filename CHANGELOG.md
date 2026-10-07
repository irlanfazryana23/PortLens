# Changelog

All notable changes to PortLens are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [1.0.0] - 2026-10-07

First public release. PortLens was previously an internal tool called Printer Port Detector.

### Added
- Printer list with status badges (Online, Offline, Virtual), the physical port, the Windows port, connection type and driver.
- Search box plus status and connection filter chips with live counts.
- Sortable columns (ascending, descending, scan order).
- Printer details panel with one-click copy for every value.
- Copy report for the printers currently shown.
- Custom diagnostic test page: color swatches, grayscale ramp, fine lines, text samples, alignment marks and a checklist. It scales to Letter, A4 and A5.
- Set as default, printer properties and print queue shortcuts.
- Optional auto-refresh every 15 seconds.
- Sort and filter choices are remembered between launches.
- Portable Windows build with version information and SHA-256 checksums.

### Changed
- Renamed from Printer Port Detector to PortLens. Settings from the old name are still read on first launch.
- Selection and scroll position are kept across refreshes.
