from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path

# DKS packages store the Viggen plan as sequential lowercase slots [b1]..[b9].
# Current DCS exports key each fix by its real id: [B1], [BX6], [L1], [LS].
_LEGACY_SLOT = re.compile(r"b(\d+)$")
_POINT_ID = re.compile(r"(LS|BX|B|L|M)(\d+)?$")
_ROUTE_NAME = re.compile(r'\["name"\]\s*=\s*"([^"]+)"')
_POINT_TOKEN = re.compile(r"^(LS|BX\d{1,2}|B\d{1,2}|L\d{1,2}|M\d{1,2})$")

_GROUP_ORDER = {"LS": 0, "B": 1, "L": 2, "BX": 3, "M": 4}


def install_ajs37_cartridge(source: Path, destination: Path) -> tuple[bool, list[str]]:
    """Write the cartridge DCS can load.

    Legacy DKS cartridges are rewritten into the current export layout.
    A cartridge that already uses that layout is copied unchanged.
    """
    try:
        original = source.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise OSError(f"Could not read AJS37 cartridge {source}: {exc}") from exc

    header, sections = _parse_cartridge(original)
    if not _is_legacy(sections):
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return False, []

    slot_sections = [(name, fields) for name, fields in sections if _LEGACY_SLOT.fullmatch(name)]
    point_names, name_source = _flight_plan_names(source.parent, len(slot_sections))
    converted, warnings = _convert_legacy(header, sections, point_names, name_source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(converted, encoding="utf-8", newline="\r\n")
    return True, warnings


def _is_legacy(sections: list[tuple[str, dict[str, str]]]) -> bool:
    return any(_LEGACY_SLOT.fullmatch(name) for name, _fields in sections)


def _flight_plan_names(payload_dir: Path, slot_count: int) -> tuple[list[str], str | None]:
    candidates: list[tuple[str, list[str]]] = []
    if payload_dir.is_dir():
        for path in sorted(payload_dir.glob("theway*.tw")):
            names = _names_from_theway(path)
            if names:
                candidates.append((path.name, names))
        route_preset = payload_dir / "route-tool-preset.lua"
        if route_preset.is_file():
            names = _names_from_route_preset(route_preset)
            if names:
                candidates.append((route_preset.name, names))

    matching = [(label, names) for label, names in candidates if len(names) == slot_count]
    preferred = [item for item in matching if item[0] == "theway.tw"]
    if preferred:
        return preferred[0][1], preferred[0][0]
    if matching:
        return matching[0][1], matching[0][0]
    if len(candidates) == 1:
        return candidates[0][1], candidates[0][0]
    return [], None


def _names_from_theway(path: Path) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return []
    if not isinstance(payload, list):
        return []
    names: list[str] = []
    for item in payload:
        if isinstance(item, dict) and item.get("name"):
            names.append(str(item["name"]).strip())
    return names


def _names_from_route_preset(path: Path) -> list[str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return []
    return [match.strip() for match in _ROUTE_NAME.findall(text) if match.strip()]


def _convert_legacy(
    header: dict[str, str],
    sections: list[tuple[str, dict[str, str]]],
    point_names: list[str],
    name_source: str | None,
) -> tuple[str, list[str]]:
    warnings: list[str] = []
    slot_names = [name for name, _fields in sections if _LEGACY_SLOT.fullmatch(name)]
    renamed = _rename_slots(slot_names, point_names, name_source, warnings)

    converted_sections: list[tuple[str, dict[str, str]]] = []
    seen: set[str] = set()
    for original_name, fields in sections:
        point_id = renamed.get(original_name, _normalize_point_id(original_name) or original_name.upper())
        if point_id in seen:
            warnings.append(
                f"AJS37 cartridge skipped duplicate point {point_id} from [{original_name}]."
            )
            continue
        seen.add(point_id)
        converted_sections.append((point_id, _normalize_fields(fields)))

    converted_sections.sort(key=lambda item: _section_sort_key(item[0]))
    mark_count = sum(1 for name, _fields in converted_sections if name != "LS")
    text = _render(header, converted_sections, mark_count)
    return text, warnings


def _rename_slots(
    slot_names: list[str],
    point_names: list[str],
    name_source: str | None,
    warnings: list[str],
) -> dict[str, str]:
    renamed: dict[str, str] = {}
    if not point_names:
        warnings.append(
            "AJS37 cartridge used sequential b1-b9 slots and no flight-plan names were found. "
            "Waypoints were saved as B1, B2, and so on, so BX and L points may be missing."
        )
        for slot_name in slot_names:
            number = _LEGACY_SLOT.fullmatch(slot_name).group(1)
            renamed[slot_name] = f"B{int(number)}"
        return renamed

    if len(point_names) != len(slot_names):
        source = name_source or "the flight plan"
        warnings.append(
            f"AJS37 flight plan in {source} lists {len(point_names)} names for "
            f"{len(slot_names)} cartridge waypoints. Extra waypoints were saved as B-points."
        )

    for index, slot_name in enumerate(slot_names):
        if index < len(point_names):
            point_id = _normalize_point_id(point_names[index])
            if point_id is None or point_id == "LS":
                number = _LEGACY_SLOT.fullmatch(slot_name).group(1)
                point_id = f"B{int(number)}"
                warnings.append(
                    f"AJS37 flight-plan name {point_names[index]!r} is not a Viggen point id. "
                    f"[{slot_name}] was saved as [{point_id}]."
                )
        else:
            number = _LEGACY_SLOT.fullmatch(slot_name).group(1)
            point_id = f"B{int(number)}"
        renamed[slot_name] = point_id
    return renamed


def _normalize_point_id(name: str) -> str | None:
    token = re.sub(r"\s+", "", name).upper()
    if _POINT_TOKEN.fullmatch(token):
        return token
    return None


def _normalize_fields(fields: dict[str, str]) -> dict[str, str]:
    latitude = _truncate_coord(
        _decimal_degrees(
            fields.get("latitude", "0"),
            fields.get("latitudeminutes", "0"),
            fields.get("latitudeseconds", "0"),
        )
    )
    longitude = _truncate_coord(
        _decimal_degrees(
            fields.get("longitude", "0"),
            fields.get("longitudeminutes", "0"),
            fields.get("longitudeseconds", "0"),
        )
    )
    missiontime = _as_float(fields.get("missiontime", "0"))
    velocity = _as_float(fields.get("velocity", "-1"))
    normalized = {
        "latitude": _format_coord(latitude),
        "longitude": _format_coord(longitude),
        "missiontime": _format_decimal(missiontime),
        "velocity": _format_decimal(velocity),
        "etalocked": _format_bool(fields.get("etalocked", "false")),
        "velocitylocked": _format_bool(fields.get("velocitylocked", "false")),
        "istargetpoint": _format_bool(fields.get("istargetpoint", "false")),
        "rwyheading": _format_decimal(_as_float(fields.get("rwyheading", "-1"))),
        "mapmarkerrwy": _format_bool(fields.get("mapmarkerrwy", "false")),
    }
    for key, value in fields.items():
        if key.lower() in {
            "latitude",
            "latitudeminutes",
            "latitudeseconds",
            "longitude",
            "longitudeminutes",
            "longitudeseconds",
            "missiontime",
            "velocity",
            "etalocked",
            "velocitylocked",
            "istargetpoint",
            "rwyheading",
            "mapmarkerrwy",
        }:
            continue
        normalized[key] = value
    normalized["__latitude"] = str(latitude)
    normalized["__longitude"] = str(longitude)
    normalized["__missiontime"] = str(missiontime)
    return normalized


def _render(
    header: dict[str, str],
    sections: list[tuple[str, dict[str, str]]],
    mark_count: int,
) -> str:
    created = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cartridge_name = header.get("cartridgename", "Custom cartridge")
    cartridge_info = header.get(
        "cartridgeinfo",
        f"Created: {created} Contains {mark_count} marks.",
    )
    cartridge_info_ext = header.get("cartridgeinfoext", "")
    lines = [
        "; This cartridge has been exported from DCS.",
        "",
        f"cartridgename = {cartridge_name}",
        "; .ini files seems to allow at most around 160 characters per definition.",
        f"cartridgeinfo = {cartridge_info}",
        f"cartridgeinfoext = {cartridge_info_ext}",
        "",
    ]
    for name, fields in sections:
        latitude = float(fields["__latitude"])
        longitude = float(fields["__longitude"])
        missiontime = float(fields["__missiontime"])
        lines.append(f"[{name}]")
        lines.append(f"; {_format_dms(latitude)} {_format_dms(longitude)}")
        lines.append(f"latitude = {fields['latitude']}")
        lines.append(f"longitude = {fields['longitude']}")
        lines.append(f"; {_format_mission_clock(missiontime)}")
        lines.append(f"missiontime = {fields['missiontime']}")
        lines.append(f"velocity = {fields['velocity']}")
        lines.append(f"etalocked = {fields['etalocked']}")
        lines.append(f"velocitylocked = {fields['velocitylocked']}")
        lines.append(f"istargetpoint = {fields['istargetpoint']}")
        lines.append(f"rwyheading = {fields['rwyheading']}")
        lines.append(f"mapmarkerrwy = {fields['mapmarkerrwy']}")
        for key, value in fields.items():
            if key.startswith("__") or key in {
                "latitude",
                "longitude",
                "missiontime",
                "velocity",
                "etalocked",
                "velocitylocked",
                "istargetpoint",
                "rwyheading",
                "mapmarkerrwy",
            }:
                continue
            lines.append(f"{key} = {value}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _section_sort_key(name: str) -> tuple[int, int, str]:
    match = _POINT_ID.fullmatch(name)
    if match is None:
        return (9, 0, name)
    kind = match.group(1)
    number = int(match.group(2) or 0)
    return (_GROUP_ORDER.get(kind, 9), number, name)


def _parse_cartridge(text: str) -> tuple[dict[str, str], list[tuple[str, dict[str, str]]]]:
    header: dict[str, str] = {}
    sections: list[tuple[str, dict[str, str]]] = []
    current: dict[str, str] | None = None
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]") and len(line) > 2:
            current = {}
            sections.append((line[1:-1].strip(), current))
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if current is None:
            header[key] = value
        else:
            current[key] = value
    return header, sections


def _decimal_degrees(degrees: str, minutes: str, seconds: str) -> float:
    degree_value = _as_float(degrees)
    sign = -1.0 if degree_value < 0 or degrees.strip().startswith("-") else 1.0
    return sign * (
        abs(degree_value) + abs(_as_float(minutes)) / 60.0 + abs(_as_float(seconds)) / 3600.0
    )


def _as_float(value: str) -> float:
    try:
        return float(value.strip())
    except (TypeError, ValueError):
        return 0.0


def _truncate_coord(value: float) -> float:
    sign = -1.0 if value < 0 else 1.0
    return sign * (int(abs(value) * 10000) / 10000)


def _format_coord(value: float) -> str:
    return f"{value:.4f}"


def _format_decimal(value: float) -> str:
    text = f"{value:.6f}".rstrip("0").rstrip(".")
    return text if text not in {"", "-0"} else "0"


def _format_bool(value: str) -> str:
    return "true" if value.strip().lower() in {"true", "1", "yes"} else "false"


def _format_dms(value: float) -> str:
    sign = "-" if value < 0 else ""
    total_seconds = int(abs(value) * 3600)
    degrees = total_seconds // 3600
    remainder = total_seconds % 3600
    minutes = remainder // 60
    seconds = remainder % 60
    return f"{sign}{degrees:03d}:{minutes:02d}:{seconds:02d}"


def _format_mission_clock(missiontime: float) -> str:
    total = int(missiontime)
    if total < 0:
        total = 0
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}{minutes:02d}{seconds:02d}"
