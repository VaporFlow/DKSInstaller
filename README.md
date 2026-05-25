# DKS Installer

Windows desktop installer for Digital Kneeboard Simulator (DKS) flight-plan ZIP packages.

Current version: `v0.9.1`

![DKS Installer main window](docs/media/01-main-window.png)

## Download

Download the latest Windows executable from the repo releases page:

- https://github.com/VaporFlow/DKSInstaller/releases

Open the latest release, expand **Assets**, download `DKSInstaller.exe`, then run it directly. The app is portable; no MSI installer is required.

> If a release currently shows only `Source code (zip)` / `Source code (tar.gz)`, a binary `.exe` asset has not been attached to that release yet.

## Quick start

1. Launch `DKSInstaller.exe`.
2. Pick a DKS flight-plan ZIP from **Recent Downloads**, **Recent Backups**, **Custom DKS ZIP Folder**, or **Pick ZIP Manually...**.
3. Confirm your **DCS Saved Games Folder**.
4. Optionally set:
   - **DTC App Path (DTC.exe)**
   - **Custom DKS ZIP Folder**
   - **Custom Kneeboard Folder**
5. Click either:
   - **Install Only (Overwrite DKS Files)**
   - **Backup Current and Install**
6. Review the completion summary.

![DKS Installer install flow](docs/media/03-install-action.gif)

## What it does

- Installs kneeboard pages from DKS ZIP packages.
- Supports direct install or backup-before-install workflows.
- Finds recent ZIPs from Downloads, a custom ZIP folder, and previous backups.
- Supports manual ZIP selection.
- Can auto-install the latest Downloads ZIP.
- Persists user paths/preferences locally.
- Supports optional DTC integration.
- Supports optional custom kneeboard mirror output.
- Shows install progress, logs, timing, and a final summary.

## Full user guide

For detailed instructions, screenshots, troubleshooting, DTC notes, and backup/restore guidance, see:

- [`USER_GUIDE.md`](USER_GUIDE.md)

## Screenshots and walkthroughs

The full guide includes:

- Main window overview
- ZIP source and path selection GIF
- Install action GIF
- Completion summary screenshot

Media assets live in `docs/media/`.

## Development

### Run from source

1. Open PowerShell in this project folder.
2. Create and activate a Python virtual environment.
3. Install dependencies from `requirements.txt`.
4. Run either entrypoint:
   - `python main.py`
   - `python -m app.main`

### Build executable

Run:

- `./build.ps1`

The script installs dependencies and builds a one-file PyInstaller executable from `main.py`.

## Project layout

- `app/` - Python application source (tkinter/ttk GUI)
- `docs/media/` - User-guide screenshots and GIFs
- `USER_GUIDE.md` - Full end-user guide
- `MVP_GUIDE.md` - Scope and product decisions
- `requirements.txt` - Packaging dependency list
- `build.ps1` - Build script for PyInstaller
- `CHANGELOG.md` - Versioned change history

## Changelog

See [`CHANGELOG.md`](CHANGELOG.md) for version history.
