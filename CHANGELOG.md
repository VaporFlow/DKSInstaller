# Changelog

All notable changes to this project will be documented in this file.

## [0.6.1] - 2026-05-24

### Added
- Added a dedicated warning path when automatic `DTC.exe` termination fails: installer now flags manual-close requirement and records it in install history (`dtcManualCloseRequired`).

### Changed
- App now shows a warning pop-up instructing the user to close `DTC.exe` manually before continuing when kill-before-launch cannot complete.

## [0.6.0] - 2026-05-24

### Added
- Introduced central app version constants (`app/version.py`) and surfaced version in the main window title.
- Added optional "Kill running DTC.exe before auto-launch" behavior to better match legacy BAT workflow.
- Added startup window icon override so the app uses the DKS icon (instead of default Tk leaf) when available.
- Added version metadata (`appVersion`) to generated install history and backup manifest payloads.

### Changed
- Updated `README.md` to include current version and changelog reference.
