from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


InstallMode = Literal["install_only", "backup_install"]
PackageKind = Literal["standard", "backup_snapshot"]


@dataclass
class DesignInfo:
    name: str
    pilot_name: str


@dataclass
class AircraftInfo:
    key: str
    kneeboard_folder: str
    dtc_folder: str
    dcs_folder: str
    dtc_saved_games_folder: str | None
    dtc_in_dcs_folder: bool


@dataclass
class PackageManifest:
    manifest_version: int
    design: DesignInfo
    aircraft: AircraftInfo


@dataclass
class RestoreEntry:
    archive_path: str
    target_path: Path


@dataclass
class BackupManifest:
    backup_version: int
    created_at_utc: str
    source_zip: str
    selected_variant: str
    selected_dcs_saved_games_folder: str = ""
    restore_entries: list[RestoreEntry] = field(default_factory=list)


@dataclass
class PackageInfo:
    zip_path: Path
    kind: PackageKind
    payload_root: str | None = None
    manifest: PackageManifest | None = None
    pilot_png_entries: list[str] = field(default_factory=list)
    dtc_json_entry: str | None = None
    in_game_dtc_entry: str | None = None
    loadout_entries: list[str] = field(default_factory=list)
    merge_script_entry: str | None = None
    backup_manifest: BackupManifest | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class InstallPlan:
    kneeboard_dir: Path | None
    custom_kneeboard_dir: Path | None
    dtc_preset_target: Path | None
    in_game_dtc_target: Path | None
    loadout_dir: Path | None


@dataclass
class InstallOptions:
    mode: InstallMode
    zip_path: Path
    saved_games_path: Path
    documents_path: Path
    dcs_install_path: Path | None
    dtc_app_path: Path | None
    custom_kneeboard_path: Path | None
    kill_dtc_before_launch: bool
    backup_dir: Path
    show_restore_preview: bool
    write_install_manifest: bool
    safe_cleanup_mode: bool
    open_destinations_after_install: bool


@dataclass
class InstallResult:
    success: bool
    installed_files: list[Path] = field(default_factory=list)
    removed_files: list[Path] = field(default_factory=list)
    skipped_items: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dtc_manual_close_required: bool = False
    backup_zip: Path | None = None
    opened_destinations: list[Path] = field(default_factory=list)
    summary: str = ""


@dataclass
class AppConfig:
    saved_games_path: str = ""
    documents_path: str = ""
    dcs_install_path: str = ""
    dtc_app_path: str = ""
    custom_kneeboard_path: str = ""
    custom_zip_folder: str = ""
    kill_dtc_before_launch: bool = True
    last_source_zip: str = ""
    last_source_type: str = "download"
    backup_dir: str = ""
    auto_install_latest_enabled: bool = False
    show_restore_preview: bool = True
    write_install_manifest: bool = True
    safe_cleanup_mode: bool = False
    open_destinations_after_install: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "saved_games_path": self.saved_games_path,
            "documents_path": self.documents_path,
            "dcs_install_path": self.dcs_install_path,
            "dtc_app_path": self.dtc_app_path,
            "custom_kneeboard_path": self.custom_kneeboard_path,
            "custom_zip_folder": self.custom_zip_folder,
            "kill_dtc_before_launch": self.kill_dtc_before_launch,
            "last_source_zip": self.last_source_zip,
            "last_source_type": self.last_source_type,
            "backup_dir": self.backup_dir,
            "auto_install_latest_enabled": self.auto_install_latest_enabled,
            "show_restore_preview": self.show_restore_preview,
            "write_install_manifest": self.write_install_manifest,
            "safe_cleanup_mode": self.safe_cleanup_mode,
            "open_destinations_after_install": self.open_destinations_after_install,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        return cls(
            saved_games_path=str(data.get("saved_games_path", "")),
            documents_path=str(data.get("documents_path", "")),
            dcs_install_path=str(data.get("dcs_install_path", "")),
            dtc_app_path=str(data.get("dtc_app_path", "")),
            custom_kneeboard_path=str(data.get("custom_kneeboard_path", "")),
            custom_zip_folder=str(data.get("custom_zip_folder", "")),
            kill_dtc_before_launch=bool(data.get("kill_dtc_before_launch", True)),
            last_source_zip=str(data.get("last_source_zip", "")),
            last_source_type=str(data.get("last_source_type", "download")),
            backup_dir=str(data.get("backup_dir", "")),
            auto_install_latest_enabled=bool(data.get("auto_install_latest_enabled", False)),
            show_restore_preview=bool(data.get("show_restore_preview", True)),
            write_install_manifest=bool(data.get("write_install_manifest", True)),
            safe_cleanup_mode=bool(data.get("safe_cleanup_mode", False)),
            open_destinations_after_install=bool(data.get("open_destinations_after_install", False)),
        )
