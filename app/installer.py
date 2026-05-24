from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory
from typing import Callable

from .config import get_local_appdata_dir
from .loadout_merge import merge_loadouts
from .models import InstallOptions, InstallPlan, InstallResult, PackageInfo, RestoreEntry
from .version import APP_VERSION

ProgressCallback = Callable[[int, str], None]
LogCallback = Callable[[str], None]
StepLogCallback = Callable[[str], None]

# Mirrors the legacy remove.bat intent for DCS-DTC preset cleanup when
# aggressive cleanup mode is enabled.
AGGRESSIVE_DTC_PRESET_FOLDERS = (
    "F16C",
    "FA18C",
    "A10C",
    "AH64D",
    "AV8B",
    "OH58D",
    "F-15ESE",
)

CUSTOM_KNEEBOARD_TRACKER_FILE = ".dks-custom-kneeboard.json"


def _entry_to_path(root: Path, zip_entry: str) -> Path:
    parts = [part for part in zip_entry.split("/") if part]
    return root.joinpath(*parts)


def _validate_zip_entry_path(entry_name: str) -> None:
    normalized = entry_name.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute():
        raise ValueError(f"Blocked absolute ZIP entry path: {entry_name}")
    if any(part == ".." for part in pure.parts):
        raise ValueError(f"Blocked unsafe ZIP entry path traversal: {entry_name}")
    if pure.parts and ":" in pure.parts[0]:
        raise ValueError(f"Blocked ZIP entry with drive prefix: {entry_name}")


def _safe_extract_all(zip_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as archive:
        for info in archive.infolist():
            _validate_zip_entry_path(info.filename)

        archive.extractall(destination)


def _emit_progress(callback: ProgressCallback | None, value: int, message: str) -> None:
    if callback is not None:
        callback(value, message)


def _make_step_logger(log: LogCallback) -> StepLogCallback:
    start = time.perf_counter()
    last = start

    def mark(label: str) -> None:
        nonlocal last
        now = time.perf_counter()
        step_elapsed = now - last
        total_elapsed = now - start
        log(f"{label} | step {step_elapsed:.2f}s | total {total_elapsed:.2f}s")
        last = now

    return mark


def _build_install_plan(package_info: PackageInfo, options: InstallOptions) -> InstallPlan:
    if package_info.kind != "standard" or package_info.manifest is None:
        return InstallPlan(
            kneeboard_dir=None,
            custom_kneeboard_dir=None,
            dtc_preset_target=None,
            in_game_dtc_target=None,
            loadout_dir=None,
        )

    manifest = package_info.manifest
    dcs_saved_games_folder = options.saved_games_path

    kneeboard_dir = dcs_saved_games_folder / "Kneeboard" / manifest.aircraft.kneeboard_folder

    dtc_preset_target: Path | None = None
    if package_info.dtc_json_entry:
        if manifest.aircraft.dtc_in_dcs_folder:
            dtc_folder = (
                manifest.aircraft.dtc_saved_games_folder
                or manifest.aircraft.dcs_folder
                or dcs_saved_games_folder.name
            )
            dtc_preset_target = dcs_saved_games_folder.parent / dtc_folder / "Mission3.json"
        else:
            dtc_preset_target = (
                options.documents_path
                / "DCS-DTC"
                / "Presets"
                / manifest.aircraft.dtc_folder
                / f"{manifest.design.name}_OB.json"
            )

    in_game_dtc_target: Path | None = None
    if package_info.in_game_dtc_entry:
        in_game_dtc_target = dcs_saved_games_folder / Path(package_info.in_game_dtc_entry).name

    loadout_dir: Path | None = None
    if package_info.loadout_entries:
        loadout_dir = dcs_saved_games_folder / "MissionEditor" / "UnitPayloads"

    custom_kneeboard_dir: Path | None = None
    if options.custom_kneeboard_path is not None:
        custom_kneeboard_dir = options.custom_kneeboard_path

    return InstallPlan(
        kneeboard_dir=kneeboard_dir,
        custom_kneeboard_dir=custom_kneeboard_dir,
        dtc_preset_target=dtc_preset_target,
        in_game_dtc_target=in_game_dtc_target,
        loadout_dir=loadout_dir,
    )


def _get_custom_kneeboard_tracker_path(custom_dir: Path) -> Path:
    return custom_dir / CUSTOM_KNEEBOARD_TRACKER_FILE


def _read_custom_kneeboard_tracked_files(custom_dir: Path) -> list[Path]:
    tracker_path = _get_custom_kneeboard_tracker_path(custom_dir)
    if not tracker_path.exists() or not tracker_path.is_file():
        return []

    try:
        payload = json.loads(tracker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []

    installed_files_raw = payload.get("installedFiles", [])
    if not isinstance(installed_files_raw, list):
        return []

    tracked_files: set[Path] = set()
    for item in installed_files_raw:
        file_name = Path(str(item)).name
        if not file_name:
            continue
        tracked_files.add(custom_dir / file_name)

    return sorted(tracked_files, key=lambda item: str(item).lower())


def _write_custom_kneeboard_tracker(custom_dir: Path, installed_files: list[Path]) -> None:
    tracker_path = _get_custom_kneeboard_tracker_path(custom_dir)
    unique_names = sorted({path.name for path in installed_files if path.name})
    payload = {
        "version": 1,
        "updatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "installedFiles": unique_names,
    }
    tracker_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _collect_cleanup_candidates(
    package_info: PackageInfo,
    plan: InstallPlan,
    options: InstallOptions,
) -> list[Path]:
    if package_info.kind != "standard" or package_info.manifest is None:
        return []

    manifest = package_info.manifest
    candidates: set[Path] = set()
    dcs_saved_games_folder = options.saved_games_path

    def add_glob(folder: Path, pattern: str) -> None:
        if folder.exists():
            for item in folder.glob(pattern):
                if item.is_file():
                    candidates.add(item)

    if plan.kneeboard_dir:
        if options.safe_cleanup_mode:
            add_glob(plan.kneeboard_dir, f"*_{manifest.design.name}_OB.png")
        else:
            add_glob(plan.kneeboard_dir, "*_OB.png")

    common_kneeboard_dir = dcs_saved_games_folder / "Kneeboard"
    if options.safe_cleanup_mode:
        add_glob(common_kneeboard_dir, f"*_{manifest.design.name}_OB.png")
    else:
        add_glob(common_kneeboard_dir, "*_OB.png")

    if options.safe_cleanup_mode:
        if plan.in_game_dtc_target and plan.in_game_dtc_target.exists():
            candidates.add(plan.in_game_dtc_target)
    else:
        add_glob(dcs_saved_games_folder, "*_OB.dtc")

    if plan.dtc_preset_target and plan.dtc_preset_target.exists():
        candidates.add(plan.dtc_preset_target)

    dtc_presets_base = options.documents_path / "DCS-DTC" / "Presets"
    if dtc_presets_base.exists() and package_info.manifest:
        if options.safe_cleanup_mode:
            safe_target = (
                dtc_presets_base
                / manifest.aircraft.dtc_folder
                / f"{manifest.design.name}_OB.json"
            )
            if safe_target.exists():
                candidates.add(safe_target)
        else:
            for folder_name in AGGRESSIVE_DTC_PRESET_FOLDERS:
                folder_path = dtc_presets_base / folder_name
                if not folder_path.exists():
                    continue
                for preset_file in folder_path.glob("*_OB.json"):
                    if preset_file.is_file():
                        candidates.add(preset_file)

    if plan.loadout_dir and plan.loadout_dir.exists() and package_info.loadout_entries:
        for entry in package_info.loadout_entries:
            target_file = plan.loadout_dir / Path(entry).name
            if target_file.exists():
                candidates.add(target_file)

    if plan.custom_kneeboard_dir:
        for tracked_file in _read_custom_kneeboard_tracked_files(plan.custom_kneeboard_dir):
            if tracked_file.exists() and tracked_file.is_file():
                candidates.add(tracked_file)

    return sorted(candidates)


def _encode_snapshot_path(target_path: Path) -> str:
    target_posix = target_path.as_posix()
    drive = target_path.drive.replace(":", "")

    if drive and target_posix.lower().startswith(f"{drive.lower()}/"):
        relative_part = target_posix[len(drive) + 1 :]
    else:
        relative_part = target_posix.lstrip("/")

    if drive:
        return f"snapshot/{drive}/{relative_part}".replace("//", "/")

    return f"snapshot/{relative_part}".replace("//", "/")


def _create_backup_zip(
    files_to_backup: list[Path],
    options: InstallOptions,
    package_info: PackageInfo,
    log: LogCallback,
) -> Path | None:
    if not files_to_backup:
        return None

    options.backup_dir.mkdir(parents=True, exist_ok=True)

    design = "snapshot"
    pilot = "backup"
    if package_info.kind == "standard" and package_info.manifest is not None:
        design = package_info.manifest.design.name
        pilot = package_info.manifest.design.pilot_name

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dcs_folder_label = options.saved_games_path.name or "DCS"
    backup_name = f"{timestamp}__{design}__{pilot}__{dcs_folder_label}.zip"
    backup_zip = options.backup_dir / backup_name

    restore_entries: list[dict[str, str]] = []

    with zipfile.ZipFile(backup_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in files_to_backup:
            if not file_path.exists() or not file_path.is_file():
                continue
            archive_path = _encode_snapshot_path(file_path)
            archive.write(file_path, archive_path)
            restore_entries.append(
                {
                    "archivePath": archive_path,
                    "targetPath": str(file_path),
                }
            )

        backup_manifest = {
            "backupVersion": 1,
            "appVersion": APP_VERSION,
            "createdAtUtc": datetime.now(timezone.utc).isoformat(),
            "sourceZip": str(options.zip_path),
            "selectedVariant": dcs_folder_label,
            "selectedDcsSavedGamesFolder": str(options.saved_games_path),
            "restoreEntries": restore_entries,
        }

        archive.writestr(
            "backup-manifest.json",
            json.dumps(backup_manifest, indent=2, ensure_ascii=False),
        )

    log(f"Backup created: {backup_zip}")
    return backup_zip


def _write_install_manifest(result: InstallResult, options: InstallOptions) -> None:
    history_dir = get_local_appdata_dir() / "history"
    history_dir.mkdir(parents=True, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    history_path = history_dir / f"install-{stamp}.json"

    payload = {
        "appVersion": APP_VERSION,
        "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "mode": options.mode,
        "sourceZip": str(options.zip_path),
        "selectedVariant": options.saved_games_path.name,
        "selectedDcsSavedGamesFolder": str(options.saved_games_path),
        "dtcAppPath": str(options.dtc_app_path) if options.dtc_app_path else None,
        "customKneeboardPath": (
            str(options.custom_kneeboard_path)
            if options.custom_kneeboard_path
            else None
        ),
        "dtcManualCloseRequired": result.dtc_manual_close_required,
        "installedFiles": [str(path) for path in result.installed_files],
        "removedFiles": [str(path) for path in result.removed_files],
        "skippedItems": result.skipped_items,
        "warnings": result.warnings,
        "backupZip": str(result.backup_zip) if result.backup_zip else None,
        "success": result.success,
    }

    history_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _open_destinations(result: InstallResult, destinations: list[Path]) -> None:
    for destination in destinations:
        if destination.exists():
            os.startfile(str(destination))
            result.opened_destinations.append(destination)


def _resolve_dtc_app_path(options: InstallOptions) -> Path | None:
    candidates: list[Path] = []

    if options.dtc_app_path:
        explicit = options.dtc_app_path
        if explicit.is_dir():
            candidates.append(explicit / "DTC.exe")
        else:
            candidates.append(explicit)

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "DCS-DTC" / "DTC.exe")

    program_files = os.environ.get("PROGRAMFILES")
    if program_files:
        candidates.append(Path(program_files) / "DCS-DTC" / "DTC.exe")

    program_files_x86 = os.environ.get("PROGRAMFILES(X86)")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "DCS-DTC" / "DTC.exe")

    candidates.append(options.documents_path / "DCS-DTC" / "DTC.exe")

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    return None


def _is_dtc_process_running() -> bool | None:
    try:
        completed = subprocess.run(  # noqa: S603
            ["tasklist", "/FI", "IMAGENAME eq DTC.exe", "/FO", "CSV", "/NH"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None

    lines = [line.strip() for line in (completed.stdout or "").splitlines() if line.strip()]
    for line in lines:
        first_column = line.split(",", 1)[0].strip().strip('"').lower()
        if first_column == "dtc.exe":
            return True

    if lines:
        return False

    return None


def _kill_running_dtc_processes(result: InstallResult, log: LogCallback) -> bool:
    running_before = _is_dtc_process_running()
    if running_before is False:
        log("DTC.exe was not running before launch; no stop needed.")
        return True

    try:
        completed = subprocess.run(  # noqa: S603
            ["taskkill", "/IM", "DTC.exe", "/F"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        result.warnings.append(f"Failed to run taskkill for DTC.exe: {exc}")
        if running_before is True:
            result.dtc_manual_close_required = True
        return running_before is not True

    running_after = _is_dtc_process_running()

    if completed.returncode == 0 and running_after is not True:
        log("Stopped running DTC.exe process(es) before relaunch.")
        return True

    combined_output = "\n".join(
        text.strip()
        for text in [completed.stdout, completed.stderr]
        if text and text.strip()
    )
    if combined_output:
        first_line = combined_output.splitlines()[0]
        log(
            "DTC.exe pre-launch stop returned non-zero (non-fatal): "
            f"{first_line}"
        )
    else:
        log("DTC.exe pre-launch stop returned non-zero (non-fatal).")

    if running_after is True or running_before is True:
        result.dtc_manual_close_required = True
        result.warnings.append(
            "Could not stop DTC.exe automatically. Please close DTC.exe manually before continuing."
        )
        return False

    return True


def _maybe_launch_dtc_app(
    package_info: PackageInfo,
    plan: InstallPlan,
    options: InstallOptions,
    result: InstallResult,
    log: LogCallback,
) -> None:
    if package_info.manifest is None:
        return

    if package_info.manifest.aircraft.dtc_in_dcs_folder:
        return

    if plan.dtc_preset_target is None or not plan.dtc_preset_target.exists():
        return

    dtc_exe = _resolve_dtc_app_path(options)
    if dtc_exe is None:
        result.skipped_items.append(
            "DTC app launch skipped (DTC.exe not found). Preset was copied successfully."
        )
        return

    if options.kill_dtc_before_launch:
        killed = _kill_running_dtc_processes(result, log)
        if not killed:
            result.skipped_items.append(
                "DTC app launch skipped until DTC.exe is closed manually."
            )
            return

    load_arg = str(
        PureWindowsPath(package_info.manifest.aircraft.dtc_folder)
        / plan.dtc_preset_target.name
    )

    try:
        subprocess.Popen(  # noqa: S603
            [str(dtc_exe), "--load", load_arg],
            cwd=str(dtc_exe.parent),
        )
        log(f"Launched DTC app with preset: {load_arg}")
    except OSError as exc:
        result.warnings.append(f"Failed to launch DTC.exe automatically: {exc}")


def _install_backup_snapshot(
    package_info: PackageInfo,
    options: InstallOptions,
    log: LogCallback,
    step_log: StepLogCallback,
    progress: ProgressCallback | None,
) -> InstallResult:
    result = InstallResult(success=False)

    if package_info.backup_manifest is None:
        result.summary = "Backup manifest missing."
        return result

    restore_entries = package_info.backup_manifest.restore_entries
    _emit_progress(progress, 10, "Preparing backup restore...")
    step_log("Phase: prepare backup restore")

    existing_targets = [entry.target_path for entry in restore_entries if entry.target_path.exists()]
    if options.mode == "backup_install":
        backup_zip = _create_backup_zip(existing_targets, options, package_info, log)
        result.backup_zip = backup_zip
        step_log("Phase: backup current files before restore")

    with TemporaryDirectory(prefix="dks_restore_") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        _emit_progress(progress, 30, "Extracting backup archive...")
        _safe_extract_all(package_info.zip_path, temp_dir)
        step_log("Phase: extract backup archive")

        _emit_progress(progress, 60, "Restoring files from backup snapshot...")
        for entry in restore_entries:
            source_file = _entry_to_path(temp_dir, entry.archive_path)
            target_file = entry.target_path

            if not source_file.exists():
                result.warnings.append(f"Missing snapshot entry in ZIP: {entry.archive_path}")
                continue

            target_file.parent.mkdir(parents=True, exist_ok=True)
            if target_file.exists():
                result.removed_files.append(target_file)
            shutil.copy2(source_file, target_file)
            result.installed_files.append(target_file)
        step_log("Phase: restore snapshot files")

    result.success = True
    result.summary = (
        "Backup restore complete. "
        f"Restored {len(result.installed_files)} file(s), "
        f"warnings: {len(result.warnings)}."
    )
    _emit_progress(progress, 100, "Backup restore complete.")
    step_log("Phase: backup restore complete")
    return result


def _install_standard_package(
    package_info: PackageInfo,
    options: InstallOptions,
    log: LogCallback,
    step_log: StepLogCallback,
    progress: ProgressCallback | None,
) -> InstallResult:
    result = InstallResult(success=False)

    if package_info.manifest is None:
        result.summary = "Manifest missing."
        return result

    manifest = package_info.manifest
    plan = _build_install_plan(package_info, options)

    _emit_progress(progress, 10, "Preparing installation plan...")
    step_log("Phase: prepare installation plan")

    if package_info.dtc_json_entry is None:
        result.skipped_items.append("No dtc.json in package (DTC preset skipped).")
    if package_info.in_game_dtc_entry is None:
        result.skipped_items.append("No in-game *_OB.dtc in package.")
    if not package_info.loadout_entries:
        result.skipped_items.append("No lua-loadouts/*.lua in package.")
    elif package_info.loadout_entries:
        log(
            "Loadout files detected in package. "
            "These are merged into DCS UnitPayloads when luae.exe is available."
        )

    cleanup_candidates = _collect_cleanup_candidates(package_info, plan, options)
    step_log("Phase: resolve cleanup candidates")

    if options.mode == "backup_install":
        _emit_progress(progress, 20, "Creating backup of current files...")
        backup_zip = _create_backup_zip(cleanup_candidates, options, package_info, log)
        result.backup_zip = backup_zip
        if backup_zip is None:
            result.warnings.append("No existing files were found to back up.")
        step_log("Phase: backup current files")

    _emit_progress(progress, 30, "Extracting source ZIP...")
    with TemporaryDirectory(prefix="dks_install_") as temp_dir_raw:
        temp_dir = Path(temp_dir_raw)
        _safe_extract_all(package_info.zip_path, temp_dir)
        step_log("Phase: extract source ZIP")

        _emit_progress(progress, 45, "Cleaning previous DKS files...")
        for old_file in cleanup_candidates:
            if old_file.exists():
                old_file.unlink(missing_ok=True)
                result.removed_files.append(old_file)
        step_log("Phase: cleanup previous files")

        if plan.kneeboard_dir is None:
            raise ValueError("Install plan did not produce a kneeboard destination.")

        plan.kneeboard_dir.mkdir(parents=True, exist_ok=True)
        custom_kneeboard_dir = plan.custom_kneeboard_dir
        custom_kneeboard_copies: list[Path] = []
        if custom_kneeboard_dir is not None:
            try:
                custom_kneeboard_dir.mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                result.warnings.append(
                    "Custom kneeboard folder unavailable "
                    f"({custom_kneeboard_dir}): {exc}"
                )
                custom_kneeboard_dir = None

        _emit_progress(progress, 60, "Installing kneeboard pages...")
        sorted_png_entries = sorted(package_info.pilot_png_entries)
        for index, png_entry in enumerate(sorted_png_entries, start=1):
            source_file = _entry_to_path(temp_dir, png_entry)
            if not source_file.exists():
                result.warnings.append(f"Missing expected PNG in ZIP: {png_entry}")
                continue

            destination = plan.kneeboard_dir / f"{index:03d}_{manifest.design.name}_OB.png"
            shutil.copy2(source_file, destination)
            result.installed_files.append(destination)

            if custom_kneeboard_dir is not None:
                custom_destination = custom_kneeboard_dir / destination.name
                try:
                    shutil.copy2(source_file, custom_destination)
                    result.installed_files.append(custom_destination)
                    custom_kneeboard_copies.append(custom_destination)
                except OSError as exc:
                    result.warnings.append(
                        "Failed to copy kneeboard page to custom folder "
                        f"({custom_destination}): {exc}"
                    )

        if custom_kneeboard_dir is not None:
            try:
                _write_custom_kneeboard_tracker(custom_kneeboard_dir, custom_kneeboard_copies)
            except OSError as exc:
                result.warnings.append(
                    "Failed to update custom kneeboard tracker "
                    f"({custom_kneeboard_dir}): {exc}"
                )
        step_log("Phase: install kneeboard pages")

        _emit_progress(progress, 72, "Installing DTC files (if present)...")
        if package_info.dtc_json_entry and plan.dtc_preset_target:
            source_dtc_json = _entry_to_path(temp_dir, package_info.dtc_json_entry)
            if source_dtc_json.exists():
                plan.dtc_preset_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_dtc_json, plan.dtc_preset_target)
                result.installed_files.append(plan.dtc_preset_target)
            else:
                result.warnings.append(
                    "dtc.json entry was declared but missing from extracted content."
                )

        if package_info.in_game_dtc_entry and plan.in_game_dtc_target:
            source_ingame = _entry_to_path(temp_dir, package_info.in_game_dtc_entry)
            if source_ingame.exists():
                plan.in_game_dtc_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_ingame, plan.in_game_dtc_target)
                result.installed_files.append(plan.in_game_dtc_target)

        _maybe_launch_dtc_app(package_info, plan, options, result, log)
        step_log("Phase: install DTC artifacts")

        _emit_progress(progress, 84, "Processing loadouts (if present)...")
        if package_info.loadout_entries and plan.loadout_dir:
            loadout_sources = [
                _entry_to_path(temp_dir, entry)
                for entry in package_info.loadout_entries
                if _entry_to_path(temp_dir, entry).exists()
            ]

            if not loadout_sources:
                result.skipped_items.append(
                    "Loadout entries were declared but no loadout files were extracted."
                )

            merge_script_path = (
                _entry_to_path(temp_dir, package_info.merge_script_entry)
                if package_info.merge_script_entry
                else None
            )
            merged, warnings = merge_loadouts(
                loadout_files=loadout_sources,
                merge_script_path=merge_script_path,
                target_dir=plan.loadout_dir,
                dcs_install_path=options.dcs_install_path,
                log=log,
            )
            result.installed_files.extend(merged)
            result.warnings.extend(warnings)
            if loadout_sources and len(merged) < len(loadout_sources):
                result.skipped_items.append(
                    f"{len(loadout_sources) - len(merged)} loadout file(s) were not merged."
                )
            step_log("Phase: process loadouts")
        else:
            step_log("Phase: process loadouts (skipped)")

    _emit_progress(progress, 95, "Finalizing installation...")
    step_log("Phase: finalize installation")

    if options.open_destinations_after_install:
        destinations = [
            path
            for path in [plan.kneeboard_dir, plan.custom_kneeboard_dir, plan.loadout_dir]
            if path is not None
        ]
        if plan.dtc_preset_target is not None:
            destinations.append(plan.dtc_preset_target.parent)
        _open_destinations(result, destinations)

    result.success = True
    result.summary = (
        f"Installed {len(result.installed_files)} file(s), "
        f"removed {len(result.removed_files)} file(s), "
        f"skipped {len(result.skipped_items)} item(s), "
        f"warnings: {len(result.warnings)}."
    )
    _emit_progress(progress, 100, "Installation complete.")
    step_log("Phase: installation complete")
    return result


def build_install_preview(package_info: PackageInfo, options: InstallOptions) -> str:
    lines: list[str] = []

    lines.append(f"Mode: {'Backup Current + Install' if options.mode == 'backup_install' else 'Install Only'}")
    lines.append(f"Source ZIP: {options.zip_path}")

    if package_info.kind == "backup_snapshot" and package_info.backup_manifest:
        lines.append("Source Type: Backup Snapshot")
        lines.append(
            f"Restore entries: {len(package_info.backup_manifest.restore_entries)}"
        )
        lines.append("")
        lines.append("First restore targets:")
        for entry in package_info.backup_manifest.restore_entries[:12]:
            lines.append(f"- {entry.target_path}")
        return "\n".join(lines)

    lines.append("Source Type: DKS Package")
    lines.append(f"DCS Saved Games Folder: {options.saved_games_path}")
    if options.dtc_app_path:
        lines.append(f"DTC app path: {options.dtc_app_path}")
    lines.append(
        "Kill running DTC.exe before auto-launch: "
        f"{'yes' if options.kill_dtc_before_launch else 'no'}"
    )
    lines.append(
        f"Cleanup mode: {'Safe (current package only)' if options.safe_cleanup_mode else 'Aggressive (legacy-style DKS cleanup)'}"
    )

    if package_info.manifest is None:
        return "\n".join(lines)

    plan = _build_install_plan(package_info, options)

    lines.append("")
    lines.append("Target destinations:")
    if plan.kneeboard_dir:
        lines.append(f"- Kneeboards: {plan.kneeboard_dir}")
    if plan.custom_kneeboard_dir:
        lines.append(f"- Custom kneeboards: {plan.custom_kneeboard_dir}")
    if plan.dtc_preset_target:
        lines.append(f"- DTC preset: {plan.dtc_preset_target}")
    if plan.in_game_dtc_target:
        lines.append(f"- In-game DTC: {plan.in_game_dtc_target}")
    if plan.loadout_dir:
        lines.append(f"- Loadouts: {plan.loadout_dir}")

    lines.append("")
    lines.append("Package payload:")
    lines.append(f"- PNG pages: {len(package_info.pilot_png_entries)}")
    lines.append(f"- Has dtc.json: {'yes' if package_info.dtc_json_entry else 'no'}")
    lines.append(f"- Has in-game DTC: {'yes' if package_info.in_game_dtc_entry else 'no'}")
    lines.append(f"- Loadout files: {len(package_info.loadout_entries)}")

    return "\n".join(lines)


def install_package(
    package_info: PackageInfo,
    options: InstallOptions,
    log: LogCallback,
    progress: ProgressCallback | None = None,
) -> InstallResult:
    try:
        step_log = _make_step_logger(log)
        log("Starting installation pipeline...")
        step_log("Phase: pipeline start")

        if package_info.kind == "backup_snapshot":
            result = _install_backup_snapshot(package_info, options, log, step_log, progress)
        else:
            result = _install_standard_package(package_info, options, log, step_log, progress)

        if options.write_install_manifest:
            _write_install_manifest(result, options)
            step_log("Phase: write install manifest")

        if result.success:
            log(f"Done: {result.summary}")
        else:
            log(f"Install finished with errors: {result.summary}")
        step_log("Phase: pipeline end")

        return result

    except Exception as exc:  # pylint: disable=broad-except
        log(f"ERROR: {exc}")
        return InstallResult(success=False, summary=str(exc), warnings=[str(exc)])
