from __future__ import annotations

import subprocess
from pathlib import Path

from .detect import detect_dcs_install_path


def resolve_luae_path(dcs_install_path: Path | None) -> Path | None:
    if dcs_install_path:
        luae = dcs_install_path / "bin" / "luae.exe"
        if luae.exists():
            return luae

    detected = detect_dcs_install_path()
    if detected:
        luae = detected / "bin" / "luae.exe"
        if luae.exists():
            return luae

    return None


def merge_loadouts(
    loadout_files: list[Path],
    merge_script_path: Path | None,
    target_dir: Path,
    dcs_install_path: Path | None,
    log: callable,
) -> tuple[list[Path], list[str]]:
    merged: list[Path] = []
    warnings: list[str] = []

    if not loadout_files:
        return merged, warnings

    if merge_script_path is None or not merge_script_path.exists():
        warnings.append(
            "merge-loadouts.lua missing in package; skipped loadout merge to avoid overwriting user payloads."
        )
        return merged, warnings

    luae_path = resolve_luae_path(dcs_install_path)
    if luae_path is None:
        warnings.append(
            "Could not find DCS luae.exe; skipped loadout merge."
        )
        return merged, warnings

    target_dir.mkdir(parents=True, exist_ok=True)

    for source_file in loadout_files:
        target_file = target_dir / source_file.name
        command = [
            str(luae_path),
            str(merge_script_path),
            str(source_file),
            str(target_file),
        ]
        log(f"Merging loadout: {source_file.name}")
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode == 0:
            merged.append(target_file)
            continue

        stderr = (result.stderr or "").strip()
        warning = (
            f"Loadout merge failed for {source_file.name}; preserved existing payload file."
            + (f" Details: {stderr}" if stderr else "")
        )
        warnings.append(warning)

    return merged, warnings
