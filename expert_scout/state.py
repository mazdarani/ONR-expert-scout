"""Shared simulator state."""

from copy import deepcopy
import threading


class AtomicState:
    """Keep snapshots separate from the shared state."""

    def __init__(self):
        self._lock = threading.Lock()
        self._active = {}

    def update(self, new_data: dict):
        with self._lock:
            self._active = deepcopy(new_data)

    def snapshot(self) -> dict:
        with self._lock:
            return deepcopy(self._active)
