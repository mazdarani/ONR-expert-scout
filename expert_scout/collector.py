"""
Self-collecting navigator for AUV-only box collection.
"""

import math
import random
from typing import Callable

from .state import AtomicState

from .navigation import Navigation as Navigator


class CollectorNavigator(Navigator):
    """Navigate to boxes and collect them without diver waiting/signaling."""

    def __init__(
        self,
        state: AtomicState,
        init_role: str,
        boxes_collected: list,
        set_role: callable,
        collect_box: Callable[[int], None],
        switch_to_static: callable = None,
        collision_threshold=5.0,
        yaw_threshold=0.2,
        interaction_threshold=15.0,
        follow_distance=5.0,
        collection_distance: float | None = None,
        target_randomness: float = 0.0,
        seed: int | None = None,
    ):
        super().__init__(
            state,
            init_role,
            boxes_collected,
            set_role,
            switch_to_static,
            collision_threshold,
            yaw_threshold,
            interaction_threshold,
            follow_distance,
        )
        self._collect_box = collect_box
        self._collection_distance = collection_distance or follow_distance
        self._next_box = None
        self._target_randomness = max(0.0, float(target_randomness))
        self._rng = random.Random(seed)

    def _get_next_box(self):
        boxes = self._state.snapshot().get("boxTimeList", [])
        if not boxes:
            print("[Collector] Failed to retrieve box information.")
            return

        box_dist = [box for box in boxes if box.get("auvDist") is not None]
        if not box_dist:
            print("[Collector] No boxes with distance information available.")
            return

        if self._target_randomness > 0.0:
            box_dist.sort(
                key=lambda box: float(box["auvDist"])
                + self._rng.uniform(0.0, self._target_randomness)
            )
        else:
            box_dist.sort(key=lambda box: box["auvDist"])
        for box in box_dist:
            box_id = box.get("boxID")
            if box_id not in self._boxes_collected and box.get("boxPosition") is not None:
                self._next_box = {
                    "id": box_id,
                    "position": box["boxPosition"],
                }
                return

        self._next_box = None

    def navigate(self, detections=[]):
        if self._next_box is None:
            self._get_next_box()
            if self._next_box is None:
                print("[Collector] No more boxes to collect. Holding position.")
                self._apply_motion(False, False, False, False, False, False, False, False)
                return

        positions = self._state.snapshot().get("latestPositions", {})
        auv_pos = positions.get("auvPosition")
        auv_rot = positions.get("auvRotation")
        if not auv_pos or not auv_rot:
            print("[Collector] Missing AUV position or rotation.")
            self._apply_motion(False, False, False, False, False, False, False, False)
            return

        box_pos = self._next_box["position"]
        box_dx = box_pos["x"] - auv_pos["x"]
        box_dy = box_pos["y"] - auv_pos["y"]
        box_dz = box_pos["z"] - auv_pos["z"]
        horizontal_distance = Navigator.get_2d_distance(auv_pos, box_pos)
        box_dist = Navigator.get_3d_distance(auv_pos, box_pos)

        print(
            f"[Collector] Navigating to box {self._next_box['id']} at "
            f"x={box_pos['x']}, y={box_pos['y']}, z={box_pos['z']}, distance={box_dist:.2f}"
        )

        if box_dist <= self._collection_distance:
            box_id = self._next_box["id"]
            print(f"[Collector] AUV is close enough to self-collect box {box_id}.")
            self._clear_motion_keys()
            self._collect_box(box_id)
            self._next_box = None
            return

        desired_yaw = math.atan2(box_dx, box_dz)
        current_yaw_rad = math.radians(auv_rot["y"])
        yaw_error = desired_yaw - current_yaw_rad
        yaw_error = (yaw_error + math.pi) % (2 * math.pi) - math.pi

        yaw_left = yaw_error < -self._yaw_threshold
        yaw_right = yaw_error > self._yaw_threshold
        up = box_dy > 0.5
        down = box_dy < -0.5

        cone_max_dist = 30.0
        cone_min_dist = self._collection_distance
        denominator = max(0.001, cone_max_dist - cone_min_dist)
        cone_ratio = max(0.0, min(1.0, (horizontal_distance - cone_min_dist) / denominator))
        max_cone_angle = math.pi / 2
        cone_threshold = self._yaw_threshold + (max_cone_angle - self._yaw_threshold) * cone_ratio
        in_cone = abs(yaw_error) < cone_threshold

        forward = horizontal_distance > self._collection_distance and in_cone
        self._apply_motion(up, down, False, False, forward, False, yaw_left, yaw_right)
