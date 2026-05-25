# Changelog

All notable changes to this project will be documented in this file.

## [0.9.0] - 2026-05-25

### Added
- Added a persisted **Custom DKS ZIP Folder** selector with a dedicated Browse button in the source panel.
- Added a third recent-source list for ZIP files discovered in the selected custom folder.

### Changed
- Moved the Downloads quick-install button under the **Recent Downloads** source list and added matching green one-click install buttons for **Recent Backups** and **Custom DKS ZIP Folder**.
- Switched **Install Only (Overwrite DKS Files)** to the green success-action style and centered button labels consistently across the UI.
- ZIP source refresh now reports custom-folder ZIPs alongside Downloads and Backups.
- ZIP source scanning now safely ignores paths that exist but are not directories.

## [0.8.2] - 2026-05-24

### Changed
- Updated Actions button styling: stronger 3D hover/pressed feedback for primary blue buttons and utility gray buttons.
- Top-row **Validate ZIP Package** now matches utility-button look and uses multiline text so its height aligns with the other top-row buttons.
- Increased button spacing in Actions rows (20px separation via horizontal padding).

## [0.8.1] - 2026-05-24

### Changed
- Centered the top-row action buttons and their labels.
- Made top-row action buttons equal-width (`width=25`) with multiline labels for better readability and consistent alignment.

## [0.8.0] - 2026-05-24

### Added
- Actions panel now uses a two-row layout: top row for install actions, bottom row for utility actions.

### Changed
- Styled **Install Only (Overwrite DKS Files)** and **Backup Current and Install** as dark-blue primary buttons with white text.
- Refreshed overall UI styling (modernized theme, cleaner panel/list visuals, improved button hierarchy).

## [0.7.1] - 2026-05-24

### Fixed
- After installation (including DTC auto-launch), DKSInstaller now reclaims window focus so the app remains foreground instead of leaving focus on DTC.

## [0.7.0] - 2026-05-24

### Added
- Added optional **Custom Kneeboard Folder** destination; kneeboard PNGs are now copied to both the standard DCS kneeboard path and the custom path when configured.
- Added tracked cleanup for custom kneeboard installs: only previously installed DKS kneeboard files are removed from the custom folder before new files are copied.
- Added **Clear Custom Kneeboard Folder** action button in the UI for OpenKneeboard/external workflow users.

### Changed
- Styled **Install Latest Download Now** as a dark-green primary action with bold white text.
- Install preview and history manifest now include custom kneeboard path details when configured.

## [0.6.2] - 2026-05-24

### Fixed
- DTC auto-launch now uses legacy-compatible Windows `--load` argument format (for example `F16C\\Design_OB.json`) instead of forward-slash paths, avoiding DTC key lookup crashes.

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
