# DKS Flight Plan Installer - MVP Guide (Windows)

Last updated: 2026-05-24

## Purpose

Build a Windows desktop installer for DKS flight-plan ZIPs using **Python + tkinter/ttk**, then package as a single executable with **PyInstaller**.

The app should replace fragile hardcoded `.bat` path logic with user-configurable paths, auto-detection, backups, and a clear GUI workflow.

---

## Locked Decisions (Confirmed)

1. **Platform:** Windows only.
2. **DCS Saved Games folder:** Detect a sensible default DCS Saved Games folder and let user change it directly.
3. **Install actions:**
   - **Install Only** (remove old DKS files + install new, overwrite as needed).
   - **Backup Current + Install** (zip current target files, then install new).
4. **Loadout merge fallback:** if `luae.exe` is not found, **skip loadout merge with warning** (do not fail install).
5. **Config scope:** per-user local config file.
6. **ZIP source flow:**
   - list recent ZIPs from Downloads,
   - include **Auto install latest ZIP** option,
   - include **manual ZIP picker** for non-recent files.
7. **Backups as source:** user should be able to choose previous backup ZIPs as install source.

---

## Package Contract (Observed in current ZIP)

Typical ZIP root:
- `install.bat`
- `README.txt`
- `LICENSES.txt`
- payload folder (example: `Viper_TR-1/`)

Payload folder contains:
- `manifest.json` (primary metadata source)
- `remove.bat`
- pilot folder with PNG pages (example: `ATHENA_02/*.png`)
- optional in-game DTC file (`*_OB.dtc`)
- optional `lua-loadouts/*.lua`
- optional `dtc.json` inside pilot folder

`manifest.json` fields used by installer:
- `design.name`
- `design.pilotName`
- `aircraft.kneeboardFolder`
- `aircraft.dtcFolder`
- `aircraft.dcsFolder`
- `aircraft.dtcSavedGamesFolder`
- `aircraft.dtcInDcsFolder`

---

## MVP UX

## Main screen
- **Source section**
  - Recent ZIPs (latest 10) from Downloads
  - Recent Backups (latest 10) from backup folder
  - Manual file picker (`*.zip`)
  - Checkbox/button: **Auto install latest ZIP**

- **Environment section**
  - DCS Saved Games Folder (editable + Browse)
  - Documents path (editable + Browse)
  - DCS install path (optional; used for `luae.exe`)

- **Actions**
  - **Install Only**
  - **Backup Current + Install**
  - **Validate Package**
  - **Open Logs** / **Open Backup Folder**

- **Status**
  - progress bar
  - step log text area
  - final summary (installed files, warnings, failures)

---

## Core Behavior

### 1) Startup
- Load user config file.
- Detect known folders:
  - `Documents`
  - default DCS Saved Games folder
  - DCS install path candidates (registry + Steam + shortcuts)
- Scan ZIP sources:
  - `%USERPROFILE%\Downloads\*.zip`
  - backup folder `*.zip`
- Preselect:
  - newest ZIP (if available)
  - detected DCS Saved Games folder (if available)

### 2) Package validation
- Open ZIP safely and validate expected structure.
- Parse `manifest.json`; fail with user-friendly error if missing/invalid.
- Confirm pilot PNG files exist.

### 3) Install plan generation
Compute destination paths using selected DCS Saved Games folder + manifest:
- Kneeboards -> `<DCS Saved Games Folder>\Kneeboard\<kneeboardFolder>\`
- DTC preset:
  - if `dtcInDcsFolder = true`: `%SavedGames%\<dtcSavedGamesFolder or aircraft.dcsFolder>\Mission3.json`
  - else: `%Documents%\DCS-DTC\Presets\<dtcFolder>\<design>_OB.json`
- In-game DTC (optional): `<DCS Saved Games Folder>\<design>_OB.dtc`
- Loadouts (optional): `<DCS Saved Games Folder>\MissionEditor\UnitPayloads\*.lua` via merge

### 4) Install Only
- Clean prior DKS files (MVP behavior mirrors existing `.bat` intent).
- Copy new files to targets.
- Run loadout merge when possible.
- Show summary.

### 5) Backup Current + Install
- Build file list from target locations that may be overwritten/removed.
- Zip those files before install.
- Perform install flow.
- Include backup metadata manifest in backup ZIP.

---

## Backup Design

### Backup location
Primary:
- `<exe_dir>\backups\`

Fallback if not writable:
- `%LOCALAPPDATA%\DKSInstaller\backups\`

### Backup naming
`YYYYMMDD-HHMMSS__<design>__<pilot>__<dcs_folder_name>.zip`

### Backup contents
- all replaced/removed files captured pre-install
- `backup-manifest.json` with:
  - timestamp
  - source ZIP path + hash (if available)
  - selected DCS Saved Games folder
  - resolved target paths
  - list of backed-up files

### Restore source support
- backups appear in “Recent Backups” list and can be installed like normal ZIP source.

---

## Safety/Robustness Requirements

- **Zip-slip protection** during extraction (`..` / absolute paths blocked).
- Use temp directory for extraction and clean up afterward.
- Never crash on missing optional files (`*_OB.dtc`, `lua-loadouts`, `dtc.json`).
- Log all actions and warnings.
- For destructive actions, prompt confirmation.
- Add dry-run engine internally (can be hidden in MVP UI, but code-ready).

---

## Proposed Project Layout

- `app/main.py` - tkinter app bootstrap
- `app/ui.py` - UI widgets/layout
- `app/config.py` - load/save user settings
- `app/detect.py` - folder and DCS variant detection
- `app/package_reader.py` - ZIP parsing + manifest validation
- `app/installer.py` - install/remove/backup pipeline
- `app/loadout_merge.py` - luae + merge-loadouts orchestration
- `app/models.py` - dataclasses for config/manifest/install plan
- `app/logging_utils.py` - file logger + UI log bridge
- `requirements.txt`
- `build.ps1` - pyinstaller build helper

---

## Config File (per-user)

Suggested path:
- `%LOCALAPPDATA%\DKSInstaller\config.json`

Suggested keys:
- `saved_games_path`
- `documents_path`
- `dcs_install_path`
- `selected_variant`
- `last_source_zip`
- `backup_dir`
- `auto_install_latest_enabled`

---

## Acceptance Criteria (MVP)

1. App starts on clean Windows machine with no crash.
2. Detects a DCS Saved Games folder and allows manual selection.
3. Lists recent download ZIPs and supports manual ZIP pick.
4. Valid ZIP installs kneeboard pages to selected variant folder.
5. DTC preset install follows `manifest.json` rules.
6. If `luae.exe` missing, loadouts are skipped with clear warning and install still succeeds.
7. Backup mode creates a ZIP before install and stores it in backup location.
8. User can choose a backup ZIP as installation source.
9. Settings persist across restarts.
10. Final summary reports installed/skipped/warning counts.

---

## Out of Scope for MVP (v2+)

- Multi-select install to multiple variants in one click
- Full rollback button with point-in-time restore wizard
- Auto-update mechanism for installer executable
- Localization
- Rich theme system

---

## Implementation Order

1. Data models + config persistence
2. DCS path/variant detection
3. ZIP scan + manifest parsing + validation
4. Basic GUI (source, variant, paths, action buttons, logs)
5. Install pipeline (install only)
6. Backup pipeline + backup list source
7. Optional auto-install latest zip
8. PyInstaller packaging + smoke test

---

## First Build Target

Deliver a runnable executable that can:
- pick a ZIP (recent or manual),
- pick/edit a detected DCS Saved Games folder,
- run **Install Only** safely,
- and show clear logs/results.

Then add **Backup Current + Install** in the next increment.

---

## Notes for future coding sessions

- Treat this guide as source-of-truth for MVP scope.
- When behavior conflicts with old `.bat`, preserve user safety first and document differences.
- Prefer manifest-driven behavior over filename heuristics.
