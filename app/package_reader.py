from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .models import (
    AircraftInfo,
    BackupManifest,
    DesignInfo,
    PackageInfo,
    PackageManifest,
    RestoreEntry,
)


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str]
    warnings: list[str]
    package_info: PackageInfo | None = None


def list_recent_zip_files(folder: Path, limit: int = 10) -> list[Path]:
    if not folder.exists() or not folder.is_dir():
        return []

    zips = [path for path in folder.glob("*.zip") if path.is_file()]
    zips.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return zips[:limit]


def _normalize_zip_path(name: str) -> str:
    normalized = name.replace("\\", "/").lstrip("./")
    return normalized.strip()


def _parse_manifest(payload: dict) -> PackageManifest:
    try:
        design_data = payload["design"]
        aircraft_data = payload["aircraft"]

        design = DesignInfo(
            name=str(design_data["name"]).strip(),
            pilot_name=str(design_data["pilotName"]).strip(),
        )

        aircraft = AircraftInfo(
            key=str(aircraft_data["key"]).strip(),
            kneeboard_folder=str(aircraft_data["kneeboardFolder"]).strip(),
            dtc_folder=str(aircraft_data["dtcFolder"]).strip(),
            dcs_folder=str(aircraft_data.get("dcsFolder", "DCS")).strip() or "DCS",
            dtc_saved_games_folder=(
                str(aircraft_data["dtcSavedGamesFolder"]).strip()
                if aircraft_data.get("dtcSavedGamesFolder")
                else None
            ),
            dtc_in_dcs_folder=bool(aircraft_data.get("dtcInDcsFolder", False)),
        )

        return PackageManifest(
            manifest_version=int(payload.get("manifestVersion", 1)),
            design=design,
            aircraft=aircraft,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid manifest.json schema: {exc}") from exc


def _read_standard_package(
    zip_path: Path,
    archive: zipfile.ZipFile,
    entries: list[str],
) -> PackageInfo:
    warnings: list[str] = []

    manifest_entries = sorted(
        name for name in entries if name.lower().endswith("/manifest.json")
    )

    if not manifest_entries:
        raise ValueError("No manifest.json found in ZIP payload.")

    manifest_entry = manifest_entries[0]
    if len(manifest_entries) > 1:
        warnings.append(
            f"Multiple manifest.json files found; using '{manifest_entry}'."
        )

    payload_root = manifest_entry[: -len("manifest.json")]

    try:
        manifest_payload = json.loads(archive.read(manifest_entry).decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Failed to read manifest.json: {exc}") from exc

    manifest = _parse_manifest(manifest_payload)

    pilot_folder_prefix = f"{payload_root}{manifest.design.pilot_name}/"
    png_entries = sorted(
        name
        for name in entries
        if name.lower().endswith(".png") and name.startswith(pilot_folder_prefix)
    )

    if not png_entries:
        raise ValueError(
            "No kneeboard PNG files found in the pilot folder declared by manifest.json."
        )

    dtc_json_entry = f"{pilot_folder_prefix}dtc.json"
    if dtc_json_entry not in entries:
        dtc_json_entry = None

    in_game_dtc_candidates = sorted(
        name
        for name in entries
        if name.startswith(payload_root) and name.lower().endswith("_ob.dtc")
    )
    in_game_dtc_entry = in_game_dtc_candidates[0] if in_game_dtc_candidates else None

    loadout_entries = sorted(
        name
        for name in entries
        if name.startswith(f"{payload_root}lua-loadouts/") and name.lower().endswith(".lua")
    )

    merge_script_entry = f"{payload_root}merge-loadouts.lua"
    if merge_script_entry not in entries:
        merge_script_entry = None

    if "install.bat" not in entries:
        warnings.append("install.bat not present at ZIP root.")
    if "README.txt" not in entries:
        warnings.append("README.txt not present at ZIP root.")

    return PackageInfo(
        zip_path=zip_path,
        kind="standard",
        payload_root=payload_root,
        manifest=manifest,
        pilot_png_entries=png_entries,
        dtc_json_entry=dtc_json_entry,
        in_game_dtc_entry=in_game_dtc_entry,
        loadout_entries=loadout_entries,
        merge_script_entry=merge_script_entry,
        warnings=warnings,
    )


def _read_backup_snapshot_package(
    zip_path: Path,
    archive: zipfile.ZipFile,
    entries: list[str],
) -> PackageInfo:
    manifest_name = "backup-manifest.json"
    if manifest_name not in entries:
        raise ValueError("No backup-manifest.json found.")

    try:
        payload = json.loads(archive.read(manifest_name).decode("utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid backup-manifest.json: {exc}") from exc

    restore_entries_raw = payload.get("restoreEntries", [])
    if not isinstance(restore_entries_raw, list):
        raise ValueError("backup-manifest.json restoreEntries must be a list.")

    restore_entries: list[RestoreEntry] = []
    for row in restore_entries_raw:
        if not isinstance(row, dict):
            continue
        archive_path = str(row.get("archivePath", "")).strip().replace("\\", "/")
        target_path = str(row.get("targetPath", "")).strip()
        if not archive_path or not target_path:
            continue
        if archive_path not in entries:
            raise ValueError(
                f"Backup archive entry missing from ZIP: '{archive_path}'"
            )
        restore_entries.append(
            RestoreEntry(archive_path=archive_path, target_path=Path(target_path))
        )

    if not restore_entries:
        raise ValueError("Backup ZIP has no usable restore entries.")

    backup_manifest = BackupManifest(
        backup_version=int(payload.get("backupVersion", 1)),
        created_at_utc=str(payload.get("createdAtUtc", "")),
        source_zip=str(payload.get("sourceZip", "")),
        selected_variant=str(payload.get("selectedVariant", "")),
        selected_dcs_saved_games_folder=str(payload.get("selectedDcsSavedGamesFolder", "")),
        restore_entries=restore_entries,
    )

    return PackageInfo(
        zip_path=zip_path,
        kind="backup_snapshot",
        backup_manifest=backup_manifest,
    )


def read_package_info(zip_path: Path) -> PackageInfo:
    if not zip_path.exists():
        raise ValueError(f"ZIP not found: {zip_path}")
    if zip_path.suffix.lower() != ".zip":
        raise ValueError("Selected file is not a .zip archive.")

    with zipfile.ZipFile(zip_path, "r") as archive:
        entries = [
            _normalize_zip_path(info.filename)
            for info in archive.infolist()
            if not info.is_dir() and _normalize_zip_path(info.filename)
        ]

        standard_error: Exception | None = None
        try:
            return _read_standard_package(zip_path, archive, entries)
        except Exception as exc:  # pylint: disable=broad-except
            standard_error = exc

        try:
            return _read_backup_snapshot_package(zip_path, archive, entries)
        except Exception as backup_exc:  # pylint: disable=broad-except
            details = (
                f"Standard package parse failed: {standard_error}. "
                f"Backup package parse failed: {backup_exc}."
            )
            raise ValueError(details) from backup_exc


def validate_package(zip_path: Path) -> ValidationResult:
    try:
        info = read_package_info(zip_path)
    except Exception as exc:  # pylint: disable=broad-except
        return ValidationResult(is_valid=False, errors=[str(exc)], warnings=[])

    warnings = list(info.warnings)
    errors: list[str] = []

    if info.kind == "standard":
        if info.manifest is None:
            errors.append("Manifest missing.")
        if not info.pilot_png_entries:
            errors.append("No kneeboard PNG files found.")
    elif info.kind == "backup_snapshot":
        if not info.backup_manifest or not info.backup_manifest.restore_entries:
            errors.append("Backup manifest has no restore entries.")

    return ValidationResult(
        is_valid=not errors,
        errors=errors,
        warnings=warnings,
        package_info=info,
    )
