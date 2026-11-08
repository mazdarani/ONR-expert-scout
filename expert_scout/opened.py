"""Recover opened IDs when an F-key event was missed or the controller restarted."""
import math


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class OpenedBoxes:
    """Use advancing search time, frozen box clocks and Unity's collection count."""
    def __init__(self):
        self.confirmed = set()
        self.clocks = {}
        self.last_time = None

    def update(self, snapshot):
        if snapshot.get('curState') != 'searching':
            # Time spent on the questionnaire is not evidence of an opened box.
            self.clocks.clear()
            self.last_time = None
            return self.confirmed
        for box_id in (snapshot.get('collectedBoxIds') or []):
            if isinstance(box_id, int) and not isinstance(box_id, bool):
                self.confirmed.add(box_id)
        now = snapshot.get('totalTime')
        if not finite(now) or (self.last_time is not None and now <= self.last_time):
            return self.confirmed
        self.last_time = now
        frozen, present = set(), set()
        for box in snapshot.get('boxTimeList', []):
            box_id, timer = box.get('boxID'), box.get('findTime')
            if not isinstance(box_id, int) or isinstance(box_id, bool) or not finite(timer) or timer < 0:
                continue
            present.add(box_id)
            old = self.clocks.get(box_id)
            if old is None or timer != old[0]:
                self.clocks[box_id] = (timer, now, 0)
            else:
                stable_updates = old[2] + 1
                self.clocks[box_id] = (timer, old[1], stable_updates)
                if stable_updates >= 2 and now - old[1] >= .5 and box_id not in self.confirmed:
                    frozen.add(box_id)
        self.clocks = {key: value for key, value in self.clocks.items() if key in present}
        count = snapshot.get('boxesFound')
        if isinstance(count, int) and not isinstance(count, bool):
            remaining = count - len(self.confirmed)
            if frozen and len(frozen) <= remaining:
                self.confirmed.update(frozen)
        return self.confirmed
