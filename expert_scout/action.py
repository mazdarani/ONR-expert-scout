"""AUV movement commands."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from time import time
from typing import Any


ACTION_KEYS = (
    "up",
    "down",
    "left",
    "right",
    "forward",
    "backward",
    "yaw_left",
    "yaw_right",
    "signal",
    "lights",
)

META_KEYS = ("source", "confidence", "created_time", "metadata")
VALID_KEYS = set(ACTION_KEYS) | set(META_KEYS)
CONFLICT_PAIRS = (
    ("up", "down"),
    ("left", "right"),
    ("forward", "backward"),
    ("yaw_left", "yaw_right"),
)


@dataclass
class Action:
    up: bool = False
    down: bool = False
    left: bool = False
    right: bool = False
    forward: bool = False
    backward: bool = False
    yaw_left: bool = False
    yaw_right: bool = False
    signal: bool = False
    lights: bool = False
    source: str = "unknown"
    confidence: float | None = None
    created_time: float | None = None
    metadata: dict = field(default_factory=dict)

    @classmethod
    def none(cls, source: str = "none") -> "Action":
        return cls(source=source, created_time=time())

    @classmethod
    def from_movement_keys(cls, movement_keys: dict, source: str) -> "Action":
        unknown = set(movement_keys) - set(ACTION_KEYS)
        if unknown:
            raise ValueError(f"Unknown movement key(s): {sorted(unknown)}")
        values = {key: bool(movement_keys.get(key, False)) for key in ACTION_KEYS}
        return cls(**values, source=source, created_time=time())

    @classmethod
    def from_dict(cls, data: dict) -> "Action":
        if data is None:
            raise ValueError("Action data cannot be None")
        if not isinstance(data, dict):
            raise ValueError(f"Action data must be a dict, got {type(data).__name__}")

        unknown = set(data) - VALID_KEYS
        if unknown:
            raise ValueError(f"Unknown action key(s): {sorted(unknown)}")

        values: dict[str, Any] = {key: bool(data.get(key, False)) for key in ACTION_KEYS}
        values["source"] = str(data.get("source", "unknown"))
        values["confidence"] = data.get("confidence")
        values["created_time"] = data.get("created_time")
        metadata = data.get("metadata", {})
        values["metadata"] = metadata if isinstance(metadata, dict) else {"raw_metadata": metadata}
        action = cls(**values)
        valid, errors = action.validate()
        if not valid:
            raise ValueError(f"Invalid action: {errors}")
        return action

    def to_dict(self) -> dict:
        return {
            **{key: bool(getattr(self, key)) for key in ACTION_KEYS},
            "source": self.source,
            "confidence": self.confidence,
            "created_time": self.created_time,
            "metadata": dict(self.metadata),
        }

    def active_keys(self) -> list[str]:
        return [key for key in ACTION_KEYS if bool(getattr(self, key))]

    def validate(self) -> tuple[bool, list[str]]:
        errors: list[str] = []
        for first, second in CONFLICT_PAIRS:
            if getattr(self, first) and getattr(self, second):
                errors.append(f"Conflicting actions: {first} and {second}")

        if self.confidence is not None:
            try:
                confidence = float(self.confidence)
            except (TypeError, ValueError):
                errors.append("confidence must be a number between 0 and 1")
            else:
                if confidence < 0.0 or confidence > 1.0:
                    errors.append("confidence must be between 0 and 1")

        if self.metadata is None or not isinstance(self.metadata, dict):
            errors.append("metadata must be a dict")

        return len(errors) == 0, errors

    def without_conflicts(self) -> tuple["Action", list[str]]:
        cleaned = self.copy_with()
        conflicts: list[str] = []
        for first, second in CONFLICT_PAIRS:
            if getattr(cleaned, first) and getattr(cleaned, second):
                setattr(cleaned, first, False)
                setattr(cleaned, second, False)
                conflicts.append(f"Removed conflicting actions: {first} and {second}")
        return cleaned, conflicts

    def is_empty(self) -> bool:
        return not any(bool(getattr(self, key)) for key in ACTION_KEYS)

    def copy_with(self, **kwargs) -> "Action":
        unknown = set(kwargs) - VALID_KEYS
        if unknown:
            raise ValueError(f"Unknown action key(s): {sorted(unknown)}")
        if "metadata" not in kwargs:
            kwargs["metadata"] = dict(self.metadata)
        return replace(self, **kwargs)
