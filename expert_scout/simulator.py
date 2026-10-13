"""Collection identity for the ONRScubaCFF telemetry format."""
import math


def finite_number(value):
    return value if not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value) else None


class CollectionTracker:
    """Identify opened boxes from stopped findTime clocks and the collection count.

    In this build, CargoBox.Update advances findTime only while searching and
    before OnOpenBox. Require multiple advancing simulator snapshots and a
    matching boxesFound count; a repeated file or paused game is not evidence.
    """
    def __init__(self, freeze_sec=0.5):
        self.freeze_sec = freeze_sec
        self.opened = set()
        self.clocks = {}
        self.previous_time = None

    def update(self, snapshot):
        self.opened.update(box_id for box_id in snapshot.get("collectedBoxIds", [])
                           if isinstance(box_id, int) and not isinstance(box_id, bool))
        now = finite_number(snapshot.get("totalTime"))
        if snapshot.get("curState") != "searching" or now is None:
            self.clocks.clear()
            self.previous_time = None
            return set(self.opened)
        if self.previous_time is not None and now <= self.previous_time:
            if now < self.previous_time:
                self.clocks.clear()
            return set(self.opened)
        self.previous_time = now
        present, frozen = set(), []
        for box in snapshot.get("boxTimeList", []):
            box_id, value = box.get("boxID"), finite_number(box.get("findTime"))
            if not isinstance(box_id, int) or isinstance(box_id, bool) or value is None or value < 0:
                continue
            present.add(box_id)
            old = self.clocks.get(box_id)
            if old is None or value != old[0]:
                self.clocks[box_id] = (value, now)
            elif box_id not in self.opened and now - old[1] >= self.freeze_sec:
                frozen.append(box_id)
        self.clocks = {box_id: value for box_id, value in self.clocks.items() if box_id in present}
        count = snapshot.get("boxesFound")
        if isinstance(count, int) and not isinstance(count, bool):
            remaining = count - len(self.opened)
            if 0 < len(frozen) <= remaining:
                self.opened.update(frozen)
        return set(self.opened)
