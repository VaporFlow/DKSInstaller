from __future__ import annotations

import json
import os
import sys
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


def get_default_backup_dir() -> Path:
    runtime_backup = get_runtime_dir() / "backups"
    if is_writable_directory(runtime_backup):
        return runtime_backup

    fallback = get_local_appdata_dir() / "backups"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


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

    if not config.backup_dir:
        config.backup_dir = str(get_default_backup_dir())

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
