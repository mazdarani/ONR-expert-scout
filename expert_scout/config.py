"""Grid expert settings."""
from dataclasses import dataclass
from pathlib import Path
import json
import math

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Config:
    detector_path: str = "checkpoints/yolo_box_detector_cvat_yolov8n_e20_best.pt"
    monitor_index: int = 2
    detector_confidence: float = 0.25
    detection_frames: int = 1
    camera_hfov_deg: float = 90.0
    match_tolerance_deg: float = 25.0
    collection_distance: float = 1.5
    collection_dwell_sec: float = 10.0
    max_sensor_age_sec: float = 1.0
    waypoint_jitter: float = 2.5
    depth_jitter: float = 1.5
    diver_max_separation: float = 5.0
    diver_resume_separation: float = 3.0
    output_directory: str = "logs/expert"

    def validate(self):
        for name in ("detector_path", "output_directory"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name).strip():
                raise ValueError(f"{name} must be a nonempty string")
        for name in ("detector_confidence", "camera_hfov_deg", "match_tolerance_deg", "collection_distance",
                     "collection_dwell_sec", "max_sensor_age_sec", "waypoint_jitter", "depth_jitter",
                     "diver_max_separation", "diver_resume_separation"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be a finite nonnegative number")
        if not 0 <= self.detector_confidence <= 1 or not 0 < self.camera_hfov_deg < 180:
            raise ValueError("Invalid detector confidence or camera field of view")
        if not 0 < self.match_tolerance_deg <= 90 or self.collection_distance <= 0 or self.max_sensor_age_sec <= 0:
            raise ValueError("Distances, sensor age and matching tolerance must be positive")
        for name in ("monitor_index", "detection_frames"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.diver_resume_separation > self.diver_max_separation:
            raise ValueError("Diver resume separation must not exceed the pause separation")
        return self

    def path(self, name):
        path = Path(getattr(self, name))
        return path if path.is_absolute() else ROOT / path


def load_config(path):
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError("Configuration must be a JSON object")
    try:
        return Config(**values).validate()
    except TypeError as error:
        raise ValueError(f"Invalid expert configuration: {error}") from error
