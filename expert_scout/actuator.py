"""AUV keyboard controls."""

from __future__ import annotations

from abc import ABC, abstractmethod
import time

from .action import ACTION_KEYS, Action


KEY_MAPPING = {
    "up": "o",
    "down": "u",
    "left": "j",
    "right": "l",
    "forward": "i",
    "backward": "k",
    "yaw_left": "n",
    "yaw_right": "m",
    "signal": "0",
    "lights": "p",
}

HOLD_KEYS = ("up", "down", "left", "right", "forward", "backward")
TAP_KEYS = ("yaw_left", "yaw_right", "signal", "lights")


class BaseActuator(ABC):
    @abstractmethod
    def apply(self, action: Action) -> dict:
        """Apply an action and return actuation metadata."""

    @abstractmethod
    def stop_all(self) -> dict:
        """Release all held state."""

    @abstractmethod
    def close(self) -> None:
        """Release held keys."""


class KeyboardActuator(BaseActuator):
    """Keyboard actuator matching the Unity simulator control mapping."""

    def __init__(self, tap_duration: float = 0.1, repeat_hold: bool = True, keyboard=None):
        if keyboard is None:
            from pynput.keyboard import Controller

            keyboard = Controller()

        self._keyboard = keyboard
        self._pressed: set[str] = set()
        self._tap_duration = tap_duration
        self._repeat_hold = repeat_hold

    def apply(self, action: Action) -> dict:
        action, conflicts = action.without_conflicts()
        active_hold = {key for key in HOLD_KEYS if getattr(action, key)}
        pressed: list[str] = []
        released: list[str] = []
        repeated: list[str] = []
        tapped: list[str] = []

        for key in sorted(self._pressed - active_hold):
            self._keyboard.release(KEY_MAPPING[key])
            self._pressed.remove(key)
            released.append(key)

        for key in HOLD_KEYS:
            if key in active_hold and key not in self._pressed:
                self._keyboard.press(KEY_MAPPING[key])
                self._pressed.add(key)
                pressed.append(key)
            elif key in active_hold and self._repeat_hold:
                # Match the legacy navigator behavior: re-emit active hold keys
                # every tick so Unity still receives input if focus changed.
                self._keyboard.press(KEY_MAPPING[key])
                repeated.append(key)

        for key in TAP_KEYS:
            if getattr(action, key):
                self._keyboard.press(KEY_MAPPING[key])
                if self._tap_duration > 0:
                    time.sleep(self._tap_duration)
                self._keyboard.release(KEY_MAPPING[key])
                tapped.append(key)

        result = {
            "pressed": pressed,
            "released": released,
            "repeated": repeated,
            "tapped": tapped,
            "actuator": "keyboard",
        }
        if conflicts:
            result["conflicts"] = conflicts
        return result

    def stop_all(self) -> dict:
        released = []
        for key in sorted(self._pressed):
            self._keyboard.release(KEY_MAPPING[key])
            released.append(key)
        self._pressed.clear()
        return {"pressed": [], "released": released, "repeated": [], "tapped": [], "actuator": "keyboard"}

    def close(self) -> None:
        self.stop_all()


class DryRunActuator(BaseActuator):
    """Record actions without pressing keys."""

    def __init__(self):
        self._pressed: set[str] = set()
        self.history: list[dict] = []

    def apply(self, action: Action) -> dict:
        action, conflicts = action.without_conflicts()
        active_hold = {key for key in HOLD_KEYS if getattr(action, key)}
        pressed = [key for key in HOLD_KEYS if key in active_hold and key not in self._pressed]
        released = [key for key in sorted(self._pressed - active_hold)]
        tapped = [key for key in TAP_KEYS if getattr(action, key)]

        self._pressed = set(active_hold)
        result = {
            "pressed": pressed,
            "released": released,
            "tapped": tapped,
            "actuator": "dry_run",
            "would_press": [key for key in ACTION_KEYS if getattr(action, key)],
        }
        if conflicts:
            result["conflicts"] = conflicts
        self.history.append(result)
        return result

    def stop_all(self) -> dict:
        released = sorted(self._pressed)
        self._pressed.clear()
        result = {"pressed": [], "released": released, "tapped": [], "actuator": "dry_run"}
        self.history.append(result)
        return result

    def close(self) -> None:
        self.stop_all()
