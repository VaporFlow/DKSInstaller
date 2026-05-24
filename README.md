# DKS Flight Plan Installer (Python MVP)

Windows desktop installer for DKS flight-plan ZIP packages.

Current version: `v0.7.1`

## Current project layout

- `app/` - Python application source (tkinter/ttk GUI)
- `MVP_GUIDE.md` - Scope and product decisions
- `requirements.txt` - Packaging dependency list
- `build.ps1` - Build script for PyInstaller
- `CHANGELOG.md` - Versioned change history
- `unk/legacy_package/` - Archived legacy sample/package files moved out of root

## Run (development)

1. Open a PowerShell terminal in this project folder.
2. (Recommended) Create/activate a Python virtual environment.
3. Install dependencies from `requirements.txt`.
4. Run the app entrypoint:
  - `python main.py`

Alternative module mode:
- `python -m app.main`

## Build executable

Run:
- `./build.ps1`

The script installs dependencies and creates a one-file executable with PyInstaller.
It now builds from the top-level launcher `main.py` to avoid package-relative import issues in frozen mode.
The build script auto-detects `python` or `py -3`.

## Notes

- The app supports:
  - Install Only
  - Backup Current + Install
  - recent Downloads ZIP list
  - recent Backups ZIP list
  - manual ZIP selection
  - sticky source preference (remembers last source type: download/backup/manual)
  - direct `DCS Saved Games Folder` selection (editable)
  - optional `DTC App Path (DTC.exe)` selection
  - optional `Custom Kneeboard Folder` mirror output
  - one-click clear for `Custom Kneeboard Folder`
  - optional pre-launch `DTC.exe` process kill (legacy behavior)
  - advanced options in a collapsible section
  - one-click utility to open DCS Saved Games helper folders
- Logs now include per-phase elapsed timing (`step` and `total` seconds) for install/restore pipelines.
