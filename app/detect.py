from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

try:
    import winreg
except ImportError:  # pragma: no cover - windows only runtime
    winreg = None  # type: ignore[assignment]


@dataclass
class EnvironmentDetection:
    documents_path: Path
    saved_games_root: Path
    dcs_saved_games_folder: Path
    dcs_install_path: Path | None
    dtc_app_path: Path | None


def _read_registry_string(hive: int, subkey: str, value_name: str) -> str | None:
    if winreg is None:
        return None

    try:
        with winreg.OpenKey(hive, subkey) as key:
            value, _ = winreg.QueryValueEx(key, value_name)
            if isinstance(value, str) and value.strip():
                return value.strip()
    except OSError:
        return None

    return None


def detect_documents_path() -> Path:
    path = _read_registry_string(
        winreg.HKEY_CURRENT_USER if winreg else 0,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        "Personal",
    )
    if path:
        return Path(path)

    return Path.home() / "Documents"


def detect_saved_games_path() -> Path:
    path = _read_registry_string(
        winreg.HKEY_CURRENT_USER if winreg else 0,
        r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        "{4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}",
    )
    if path:
        return Path(path)

    return Path.home() / "Saved Games"


def detect_dcs_saved_games_folder(saved_games_root: Path) -> Path:
    preferred = (
        saved_games_root / "DCS.openbeta",
        saved_games_root / "DCS",
    )

    for candidate in preferred:
        if candidate.exists() and candidate.is_dir():
            return candidate

    if saved_games_root.exists() and saved_games_root.is_dir():
        pattern = re.compile(r"^DCS(?:\.[A-Za-z0-9_-]+)?$", re.IGNORECASE)
        candidates = [
            path
            for path in saved_games_root.iterdir()
            if path.is_dir() and pattern.match(path.name)
        ]
        if candidates:
            candidates.sort(key=lambda p: (0 if p.name.lower() == "dcs" else 1, p.name.lower()))
            return candidates[0]

    return saved_games_root / "DCS"


def detect_dcs_install_path() -> Path | None:
    if winreg is None:
        return None

    candidates: list[str] = []

    registry_targets = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Eagle Dynamics\DCS World", "Path"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Eagle Dynamics\DCS World", "Path"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Eagle Dynamics\DCS World OpenBeta", "Path"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Eagle Dynamics\DCS World OpenBeta", "Path"),
    ]

    for hive, key, value_name in registry_targets:
        value = _read_registry_string(hive, key, value_name)
        if value:
            candidates.append(value)

    steam_keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
    ]

    for hive, key, value_name in steam_keys:
        install_path = _read_registry_string(hive, key, value_name)
        if install_path:
            candidates.append(str(Path(install_path) / "steamapps" / "common" / "DCSWorld"))

    for raw in candidates:
        candidate = Path(raw)
        luae = candidate / "bin" / "luae.exe"
        dcs_exe = candidate / "bin" / "DCS.exe"
        if luae.exists() or dcs_exe.exists() or candidate.exists():
            return candidate

    return None


def detect_dtc_app_path(documents_path: Path) -> Path | None:
    candidates: list[Path] = []

    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        candidates.append(Path(local_appdata) / "DCS-DTC" / "DTC.exe")

    program_files = os.environ.get("PROGRAMFILES")
    if program_files:
        candidates.append(Path(program_files) / "DCS-DTC" / "DTC.exe")

    program_files_x86 = os.environ.get("PROGRAMFILES(X86)")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "DCS-DTC" / "DTC.exe")

    candidates.append(documents_path / "DCS-DTC" / "DTC.exe")

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate

    return None


def detect_environment() -> EnvironmentDetection:
    documents_path = detect_documents_path()
    saved_games_root = detect_saved_games_path()
    return EnvironmentDetection(
        documents_path=documents_path,
        saved_games_root=saved_games_root,
        dcs_saved_games_folder=detect_dcs_saved_games_folder(saved_games_root),
        dcs_install_path=detect_dcs_install_path(),
        dtc_app_path=detect_dtc_app_path(documents_path),
    )
