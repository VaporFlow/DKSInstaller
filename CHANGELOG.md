# Changelog

All notable changes to this project will be documented in this file.

## [0.6.0] - 2026-05-24

### Added
- Introduced central app version constants (`app/version.py`) and surfaced version in the main window title.
- Added optional "Kill running DTC.exe before auto-launch" behavior to better match legacy BAT workflow.
- Added startup window icon override so the app uses the DKS icon (instead of default Tk leaf) when available.
- Added version metadata (`appVersion`) to generated install history and backup manifest payloads.

### Changed
- Updated `README.md` to include current version and changelog reference.
