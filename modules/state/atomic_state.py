import threading

class AtomicState:
    """Lock-free double-buffered state for fast readers."""
    def __init__(self):
        self._lock = threading.Lock()
        self._active = {}
        self._standby = {}

    def update(self, new_data: dict):
        with self._lock:
            self._standby.clear()
            self._standby.update(new_data)
            self._active, self._standby = self._standby, self._active

    def snapshot(self) -> dict:
        """Safe copy of the current state."""
        return dict(self._active)