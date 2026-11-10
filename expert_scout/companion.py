"""Follow the diver using the original companion movement rules."""
import math

from .action import Action
from .navigation import Navigation


class CompanionNavigator(Navigation):
    def action(self, follow_distance):
        pose = self._state.snapshot()["latestPositions"]
        auv, diver = pose["auvPosition"], pose["diverPosition"]
        dx, dy, dz = (diver[axis] - auv[axis] for axis in ("x", "y", "z"))
        horizontal_distance = math.hypot(dx, dz)
        yaw_error = math.atan2(dx, dz) - math.radians(pose["auvRotation"]["y"])
        yaw_error = (yaw_error + math.pi) % (2 * math.pi) - math.pi
        yaw_left = yaw_error < -self._yaw_threshold
        yaw_right = yaw_error > self._yaw_threshold
        # Widen the forward cone with distance, as in the original companion.
        cone_ratio = max(0.0, min(1.0, (horizontal_distance - follow_distance)
                                 / max(1.0, 30.0 - follow_distance)))
        cone = self._yaw_threshold + (math.pi / 2 - self._yaw_threshold) * cone_ratio
        close = math.sqrt(dx * dx + dy * dy + dz * dz) < follow_distance
        self._apply_motion(
            up=not close and dy > 0.5,
            down=not close and dy < -0.5,
            left=False,
            right=False,
            forward=horizontal_distance > follow_distance and abs(yaw_error) < cone,
            backward=False,
            yaw_left=yaw_left,
            yaw_right=yaw_right)
        return Action.from_movement_keys(self._movement_keys, source="companion")

    def navigate(self, detections=()):
        self.action(self._follow_distance)
