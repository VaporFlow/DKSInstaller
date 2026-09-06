from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

NICKNAME_LINE_RE = re.compile(r'^\s*\[\s*\d+\s*\]\s*=\s*"(.*)"\s*,?\s*$')
MAX_NICKNAMES = 5


def _unescape_lua_string(value: str) -> str:
    return value.replace('\\"', '"').replace("\\\\", "\\")


def _escape_lua_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def read_nicknames(path: Path) -> list[str]:
    if not path.exists() or not path.is_file():
        return []

    names: list[str] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    for line in text.splitlines():
        match = NICKNAME_LINE_RE.match(line)
        if not match:
            continue
        value = _unescape_lua_string(match.group(1)).strip()
        if value:
            names.append(value)
    return names


def build_nicknames_lua(names: list[str]) -> str:
    lines = ["nicknames = ", "{"]
    for index, name in enumerate(names, start=1):
        escaped = _escape_lua_string(name)
        lines.append(f'\t[{index}] = "{escaped}",')
    lines.append("} -- end of nicknames")
    return "\n".join(lines) + "\n"


def is_dcs_running() -> bool:
    try:
        completed = subprocess.run(  # noqa: S603
            ["tasklist", "/FI", "IMAGENAME eq DCS.exe", "/FO", "CSV", "/NH"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False

    for line in (completed.stdout or "").splitlines():
        first_column = line.split(",", 1)[0].strip().strip('"').lower()
        if first_column == "dcs.exe":
            return True
    return False


def set_multiplayer_nickname(
    name: str,
    nicknames_path: Path,
) -> tuple[bool, str | None]:
    """Write name as the first DCS multiplayer nickname. Returns (ok, warning)."""
    if not name.strip():
        return False, None
    if os.environ.get("DKS_SET_MP_NAME") == "0":
        return False, None

    existing = read_nicknames(nicknames_path)
    ordered: list[str] = [name]
    for current in existing:
        if current != name:
            ordered.append(current)
    ordered = ordered[:MAX_NICKNAMES]

    nicknames_path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_nicknames_lua(ordered)
    temp_path = nicknames_path.with_suffix(nicknames_path.suffix + ".tmp")
    temp_path.write_bytes(payload.encode("utf-8"))
    temp_path.replace(nicknames_path)

    warning = None
    if is_dcs_running():
        warning = (
            "DCS is running. The new multiplayer name applies the next time you "
            "start DCS, and will be lost if you change your nickname in the current session."
        )
    return True, warning
