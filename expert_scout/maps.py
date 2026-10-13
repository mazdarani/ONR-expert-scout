"""Select grid bounds from the simulator map, independently of box positions."""
from dataclasses import dataclass, asdict
import json
import math
from pathlib import Path

MAP_NAMES = {0: "training", 1: "map1", 2: "map2"}


def map_name(snapshot, override="auto"):
    if override != "auto":
        return override if override in MAP_NAMES.values() else None
    value = snapshot.get("mapType")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return MAP_NAMES.get(value)
    if value is None:
        value = snapshot.get("mapString")
    normalized = "".join(character for character in str(value or "").lower() if character.isalnum())
    return {"0": "training", "training": "training", "tutorialmap": "training",
            "1": "map1", "map1": "map1", "2": "map2", "map2": "map2"}.get(normalized)


@dataclass(frozen=True)
class SearchArea:
    x_min: float
    x_max: float
    z_min: float
    z_max: float

    def to_dict(self):
        return asdict(self)


def load_search_areas(path):
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    margin = values["boundary_clearance_m"]
    if isinstance(margin, bool) or not isinstance(margin, (int, float)) or not math.isfinite(margin) or margin < 0:
        raise ValueError("Map boundary clearance must be finite and nonnegative")
    areas = {}
    for name in MAP_NAMES.values():
        bounds = values["areas"][name]
        if any(isinstance(bounds[key], bool) or not isinstance(bounds[key], (int, float))
               or not math.isfinite(bounds[key]) for key in ("x_min", "x_max", "z_min", "z_max")):
            raise ValueError(f"Invalid bounds for {name}")
        area = SearchArea(bounds["x_min"] + margin, bounds["x_max"] - margin,
                          bounds["z_min"] + margin, bounds["z_max"] - margin)
        if area.x_min >= area.x_max or area.z_min >= area.z_max:
            raise ValueError(f"Boundary clearance leaves no search area for {name}")
        areas[name] = area
    return areas
