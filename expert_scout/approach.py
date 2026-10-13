"""Ground-truth teacher navigator for collecting expert demonstrations."""

from .collector import CollectorNavigator


class OracleBoxNavigator(CollectorNavigator):
    """Approach the nearest uncollected box using simulator coordinates.

    This navigator is intentionally restricted to demonstration collection.
    It uses privileged ``boxTimeList`` positions as a teacher while the logged
    camera frames remain the inputs intended for VLA fine-tuning.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._requested_box_id = None

    @property
    def target_box(self) -> dict | None:
        return dict(self._next_box) if self._next_box is not None else None

    def set_target_box(self, box_id: int) -> None:
        if box_id != self._requested_box_id:
            self._next_box = None
        self._requested_box_id = box_id

    def clear_target_box(self) -> None:
        self._requested_box_id = None
        self._next_box = None

    def _get_next_box(self):
        if self._requested_box_id is None:
            self._next_box = None
            return

        boxes = self._state.snapshot().get("boxTimeList", [])
        for box in boxes:
            if (
                isinstance(box, dict)
                and box.get("boxID") == self._requested_box_id
                and box.get("boxID") not in self._boxes_collected
                and isinstance(box.get("boxPosition"), dict)
            ):
                self._next_box = {
                    "id": box["boxID"],
                    "position": box["boxPosition"],
                }
                return
        self._next_box = None

    def action(self):
        self._get_next_box()
        self.navigate()
        from .action import Action
        return Action.from_movement_keys(dict(self._movement_keys), source="expert")
