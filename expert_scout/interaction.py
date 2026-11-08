"""Observe the diver's collection key without generating keyboard input."""
from queue import Empty, SimpleQueue
import time

from .routing import nearest_box, valid_position, distance


def collection_from_interaction(snapshot, interaction_distance):
    """Apply the original F-key proximity checks; return box ID and close flag."""
    pose = snapshot.get('latestPositions', {})
    auv, diver = pose.get('auvPosition'), pose.get('diverPosition')
    if not valid_position(auv) or not valid_position(diver):
        return None
    boxes = snapshot.get('boxTimeList', [])
    box = nearest_box(diver, boxes)
    if box is None or distance(diver, box['boxPosition']) > interaction_distance:
        return None
    if nearest_box(auv, boxes) is None:
        return None
    return box['boxID'], distance(auv, diver) <= interaction_distance


class DiverInteractions:
    """Queue the simulator state observed when the participant presses F."""
    def __init__(self, state, listener_factory=None):
        self.state = state
        self.listener_factory = listener_factory
        self.listener = None
        self.events = SimpleQueue()

    def _on_press(self, key):
        if str(getattr(key, 'char', '')).lower() != 'f':
            return
        snapshot = self.state.snapshot()
        snapshot['_interaction_time'] = time.time()
        self.events.put(snapshot)

    def start(self):
        if self.listener_factory is None:
            from pynput.keyboard import Listener
            self.listener_factory = Listener
        self.listener = self.listener_factory(on_press=self._on_press)
        self.listener.start()

    def drain(self):
        result = []
        while True:
            try:
                result.append(self.events.get_nowait())
            except Empty:
                return result

    def close(self):
        if self.listener is not None:
            self.listener.stop()
