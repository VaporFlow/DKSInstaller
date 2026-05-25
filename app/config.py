from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from .models import AppConfig


APP_NAME = "DKSInstaller"


def get_local_appdata_dir() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata) / APP_NAME

    return Path.home() / "AppData" / "Local" / APP_NAME


def get_runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent

    return Path(__file__).resolve().parent.parent


def get_config_path() -> Path:
    return get_local_appdata_dir() / "config.json"


def is_writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        test_file = path / ".write_test"
        test_file.write_text("ok", encoding="utf-8")
        test_file.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def _normalize_path_value(value: str | Path) -> str:
    return os.path.normpath(str(value)).strip()


def _is_same_or_child_path(path: Path, parent: Path) -> bool:
    normalized_path = os.path.normcase(os.path.abspath(str(path)))
    normalized_parent = os.path.normcase(os.path.abspath(str(parent)))

    try:
        return os.path.commonpath([normalized_path, normalized_parent]) == normalized_parent
    except ValueError:
        return False


def _is_temporary_path(path: Path) -> bool:
    return _is_same_or_child_path(path, Path(tempfile.gettempdir()))


def _migrate_config(config: AppConfig) -> bool:
    changed = False

    default_backup_dir = _normalize_path_value(get_local_appdata_dir() / "backups")
    legacy_runtime_backup_dir = get_runtime_dir() / "backups"

    if not config.backup_dir.strip():
        config.backup_dir = default_backup_dir
        changed = True
    else:
        backup_dir = Path(config.backup_dir)
        if (
            _is_same_or_child_path(backup_dir, legacy_runtime_backup_dir)
            or _is_temporary_path(backup_dir)
        ):
            config.backup_dir = default_backup_dir
            changed = True
        else:
            normalized_backup_dir = _normalize_path_value(config.backup_dir)
            if config.backup_dir != normalized_backup_dir:
                config.backup_dir = normalized_backup_dir
                changed = True

    if config.custom_zip_folder.strip():
        custom_zip_folder = Path(config.custom_zip_folder)
        if _is_temporary_path(custom_zip_folder):
            config.custom_zip_folder = ""
            changed = True
        else:
            normalized_custom_zip_folder = _normalize_path_value(config.custom_zip_folder)
            if config.custom_zip_folder != normalized_custom_zip_folder:
                config.custom_zip_folder = normalized_custom_zip_folder
                changed = True

    if not config.custom_zip_folder and config.last_source_type == "custom":
        config.last_source_type = "download"
        changed = True

    return changed


def get_default_backup_dir() -> Path:
    backup_dir = get_local_appdata_dir() / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return backup_dir


def load_config() -> AppConfig:
    config_path = get_config_path()
    if not config_path.exists():
        config = AppConfig(backup_dir=str(get_default_backup_dir()))
        save_config(config)
        return config

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        config = AppConfig.from_dict(data)
    except (OSError, json.JSONDecodeError, ValueError):
        config = AppConfig()

    if _migrate_config(config):
        save_config(config)

    return config


def save_config(config: AppConfig) -> None:
    config_path = get_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)

    if not config.backup_dir:
        config.backup_dir = str(get_default_backup_dir())

    payload = json.dumps(config.to_dict(), indent=2, ensure_ascii=False)
    temp_path = config_path.with_suffix(".tmp")
    temp_path.write_text(payload, encoding="utf-8")
    temp_path.replace(config_path)
