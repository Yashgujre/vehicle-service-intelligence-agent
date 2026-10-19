"""Map NHTSA component strings onto the canonical taxonomy in config/settings.yaml."""

from __future__ import annotations

from vsia.config import components

_ALIASES = {
    "ELECTRICAL SYSTEM": "ELECTRICAL SYSTEM",
    "AIR BAG": "AIR BAGS",
    "AIR BAGS": "AIR BAGS",
    "BACKOVER PREVENTION": "BACK OVER PREVENTION",
    "BACK OVER PREVENTION": "BACK OVER PREVENTION",
    "LANE DEPARTURE": "LANE DEPARTURE",
    "SERVICE BRAKES": "SERVICE BRAKES",
    "SERVICE BRAKES, HYDRAULIC": "SERVICE BRAKES",
    "SERVICE BRAKES, AIR": "SERVICE BRAKES",
    "SERVICE BRAKES, ELECTRIC": "SERVICE BRAKES",
    "FUEL SYSTEM": "FUEL/PROPULSION SYSTEM",
    "FUEL/PROPULSION SYSTEM": "FUEL/PROPULSION SYSTEM",
    "VISIBILITY": "VISIBILITY/WIPER",
    "VISIBILITY/WIPER": "VISIBILITY/WIPER",
    "WHEELS": "WHEELS",
    "TIRES": "TIRES",
}


def normalize_component(raw: str | None) -> str:
    """Return the canonical label for one NHTSA component string such as
    'ELECTRICAL SYSTEM:PROPULSION SYSTEM:TRACTION BATTERY' or 'POWER TRAIN'."""
    if not raw:
        return "OTHER"
    top = raw.strip().upper().split(":")[0].strip()
    canon = set(components())
    if top in canon:
        return top
    if top in _ALIASES and _ALIASES[top] in canon:
        return _ALIASES[top]
    for c in canon:
        if top.startswith(c):
            return c
    return "OTHER"


def split_components(raw: str | None) -> list[str]:
    """NHTSA joins multiple components with commas; return canonical labels in order, deduplicated.
    'SERVICE BRAKES, HYDRAULIC' contains a comma inside one label, so rejoin known fragments."""
    if not raw:
        return []
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    merged: list[str] = []
    for p in parts:
        if merged and p.upper() in {"HYDRAULIC", "AIR", "ELECTRIC"}:
            merged[-1] = f"{merged[-1]}, {p}"
        else:
            merged.append(p)
    out: list[str] = []
    for p in merged:
        c = normalize_component(p)
        if c not in out:
            out.append(c)
    return out


def primary_component(raw: str | None) -> str:
    """First specific component; 'UNKNOWN OR OTHER' only wins when nothing specific is listed."""
    comps = split_components(raw)
    specific = [c for c in comps if c != "OTHER"]
    return specific[0] if specific else "OTHER"
