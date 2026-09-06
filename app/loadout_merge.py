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


def _run_luae(
    luae_path: Path,
    script_path: Path,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    command = [str(luae_path), str(script_path), *args]
    return subprocess.run(  # noqa: S603
        command,
        capture_output=True,
        text=True,
        check=False,
    )


def _format_luae_failure(name: str, result: subprocess.CompletedProcess[str]) -> str:
    details = ((result.stderr or result.stdout) or "").strip()
    if details:
        first_line = details.splitlines()[0]
        return f"{name}; preserved existing file. Details: {first_line}"
    return f"{name}; preserved existing file."


def remove_dks_lua_entries(
    merge_script_path: Path | None,
    target_files: list[Path],
    dcs_install_path: Path | None,
    log: callable,
    label: str,
) -> list[str]:
    warnings: list[str] = []
    existing_targets = [path for path in target_files if path.exists() and path.is_file()]
    if not existing_targets:
        return warnings

    if merge_script_path is None or not merge_script_path.exists():
        warnings.append(
            f"{label} cleanup skipped because the merge script is not in this package."
        )
        return warnings

    luae_path = resolve_luae_path(dcs_install_path)
    if luae_path is None:
        warnings.append(
            f"{label} cleanup skipped because DCS luae.exe was not found."
        )
        return warnings

    for target_file in existing_targets:
        log(f"Removing DKS {label} from: {target_file}")
        result = _run_luae(
            luae_path,
            merge_script_path,
            ["--remove-only", str(target_file)],
        )
        if result.returncode != 0:
            warnings.append(
                _format_luae_failure(f"{label} cleanup failed for {target_file.name}", result)
            )

    return warnings


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
        log(f"Merging loadout: {source_file.name}")
        result = _run_luae(
            luae_path,
            merge_script_path,
            [str(source_file), str(target_file)],
        )
        if result.returncode == 0:
            merged.append(target_file)
            continue

        warnings.append(
            _format_luae_failure(f"Loadout merge failed for {source_file.name}", result)
        )

    return merged, warnings


def merge_route_preset(
    source_file: Path,
    merge_script_path: Path | None,
    target_file: Path,
    dcs_install_path: Path | None,
    log: callable,
) -> tuple[bool, list[str]]:
    warnings: list[str] = []

    if merge_script_path is None or not merge_script_path.exists():
        warnings.append(
            "merge-route-preset.lua missing in package; Route Tool preset merge skipped to preserve existing presets."
        )
        return False, warnings

    luae_path = resolve_luae_path(dcs_install_path)
    if luae_path is None:
        warnings.append(
            "DCS luae.exe was not found. Route Tool preset merge skipped to preserve existing presets."
        )
        return False, warnings

    log(f"Merging Route Tool preset into: {target_file}")
    result = _run_luae(
        luae_path,
        merge_script_path,
        [str(source_file), str(target_file)],
    )
    if result.returncode == 0:
        return True, warnings

    warnings.append(
        _format_luae_failure(
            f"Route Tool preset merge failed for {target_file.name}",
            result,
        )
    )
    return False, warnings
