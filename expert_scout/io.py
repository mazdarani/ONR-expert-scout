"""Read telemetry and write run outputs."""
from pathlib import Path
import json
import os
import re
import tempfile
import time


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", delete=False) as stream:
            temporary = stream.name
            json.dump(payload, stream, allow_nan=False)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


class TelemetryReader:
    """Keep the last complete snapshot while the simulator writes."""

    def __init__(self, directory, pid, state_file=None):
        self.directory = Path(directory)
        self.pid = pid
        self.state_file = Path(state_file) if state_file else None
        self.latest = {}
        self._source = None
        self._stamp = None
        self._content = None

    def read(self):
        try:
            paths = [self.state_file] if self.state_file else list(
                self.directory.glob(f"ParticipantData_PID_{self.pid}*.json"))
            if not self.state_file:
                pattern = re.escape(f"ParticipantData_PID_{self.pid}") + r"(?:_COPY_\d+)?\.json"
                paths = [p for p in paths if re.fullmatch(pattern, p.name)]
            paths = [p for p in paths if p.is_file()]
            if not paths:
                return self.latest
            path = max(paths, key=lambda p: p.stat().st_mtime_ns)
            stat = path.stat()
            content = path.read_bytes()
            if path == self._source and stat.st_mtime_ns == self._stamp and content == self._content:
                return self.latest
            value = json.loads(content)
            if not isinstance(value, dict):
                raise ValueError("Participant telemetry must contain a JSON object")
            state = next((value[k] for k in ("curState", "currState", "currentState", "stateName", "gameState")
                          if isinstance(value.get(k), str)), None)
            if state is None and isinstance(value.get("latestPositions"), dict) and "totalTime" in value:
                state = "endProgram" if str(value.get("endTime") or "").strip() else "searching"
            normalized = str(state or "").replace("_", "").replace("-", "").lower()
            value["curState"] = {"searching": "searching", "endprogram": "endProgram"}.get(normalized, state)
            value.update(PID=self.pid, _sourceMtime=stat.st_mtime, _loadedWallTime=time.time())
            self.latest = value
            self._source, self._stamp, self._content = path, stat.st_mtime_ns, content
        except (OSError, ValueError):
            # The old source timestamp remains; freshness checks stop stale motion.
            pass
        return self.latest


class RunLog:
    def __init__(self, path):
        self.stream = Path(path).open("w", encoding="utf-8")

    def write(self, value):
        self.stream.write(json.dumps(value, allow_nan=False) + "\n")
        self.stream.flush()

    def close(self):
        self.stream.close()
