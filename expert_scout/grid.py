"""
Grid-search navigator for clue-free box discovery.

This navigator performs a lawnmower sweep over configurable X/Z bounds using
only AUV pose and obstacle telemetry. It does not inspect boxTimeList or choose
targets from known simulator box positions.
"""

import math
import random

from .state import AtomicState

from .navigation import Navigation as Navigator


class GridSearchNavigator(Navigator):
    """Sweep the environment in lanes without using known box locations."""

    def __init__(
        self,
        state: AtomicState,
        init_role: str,
        boxes_collected: list,
        set_role: callable,
        switch_to_static: callable = None,
        collision_threshold=5.0,
        yaw_threshold=0.2,
        interaction_threshold=15.0,
        follow_distance=5.0,
        x_min: float = -10.0,
        x_max: float = 55.0,
        z_min: float = -40.0,
        z_max: float = 60.0,
        lane_spacing: float = 10.0,
        waypoint_tolerance: float = 2.0,
        target_y: float | None = None,
        depth_tolerance: float = 0.75,
        randomize_route: bool = False,
        waypoint_jitter: float = 0.0,
        depth_jitter: float = 0.0,
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
        self._x_min = min(float(x_min), float(x_max))
        self._x_max = max(float(x_min), float(x_max))
        self._z_min = min(float(z_min), float(z_max))
        self._z_max = max(float(z_min), float(z_max))
        self._lane_spacing = max(1.0, float(lane_spacing))
        self._waypoint_tolerance = max(0.25, float(waypoint_tolerance))
        self._configured_target_y = target_y
        self._randomize_route = bool(randomize_route)
        self._waypoint_jitter = max(0.0, float(waypoint_jitter))
        self._depth_jitter = max(0.0, float(depth_jitter))
        self._seed = seed
        self._rng = random.Random(seed)
        self._target_y = self._randomized_depth(target_y)
        self._depth_tolerance = max(0.1, float(depth_tolerance))
        self._waypoints: list[dict[str, float]] = []
        self._waypoint_index = 0
        self._lap_count = 0
        self._excluded_areas: list[dict[str, float]] = []
        self._exclusion_radius = max(self._waypoint_tolerance * 1.5, self._lane_spacing * 0.5)

    def navigate(self, detections=[]):
        positions = self._state.snapshot().get("latestPositions", {})
        auv_pos = positions.get("auvPosition")
        auv_rot = positions.get("auvRotation")
        if not auv_pos or not auv_rot:
            print("[GridSearch] Missing AUV position or rotation.")
            self._apply_motion(False, False, False, False, False, False, False, False)
            return

        if self._target_y is None:
            self._target_y = self._randomized_depth(float(auv_pos.get("y", 0.0)))

        if not self._waypoints:
            self._build_route_from_position(auv_pos)

        target = self._current_waypoint(auv_pos)
        if target is None:
            print("[GridSearch] No waypoint available; holding position.")
            self._apply_motion(False, False, False, False, False, False, False, False)
            return

        dx = target["x"] - float(auv_pos["x"])
        dz = target["z"] - float(auv_pos["z"])
        target_y = self._target_y if self._target_y is not None else float(auv_pos["y"])
        dy = target_y - float(auv_pos["y"])
        horizontal_distance = math.sqrt(dx**2 + dz**2)

        desired_yaw = math.atan2(dx, dz)
        current_yaw_rad = math.radians(float(auv_rot["y"]))
        yaw_error = (desired_yaw - current_yaw_rad + math.pi) % (2 * math.pi) - math.pi

        yaw_left = yaw_error < -self._yaw_threshold
        yaw_right = yaw_error > self._yaw_threshold
        up = dy > self._depth_tolerance
        down = dy < -self._depth_tolerance

        cone_max_dist = 30.0
        cone_min_dist = self._waypoint_tolerance
        denominator = max(0.001, cone_max_dist - cone_min_dist)
        cone_ratio = max(0.0, min(1.0, (horizontal_distance - cone_min_dist) / denominator))
        max_cone_angle = math.pi / 2
        cone_threshold = self._yaw_threshold + (max_cone_angle - self._yaw_threshold) * cone_ratio
        in_cone = abs(yaw_error) < cone_threshold
        forward = horizontal_distance > self._waypoint_tolerance and in_cone

        print(
            f"[GridSearch] Lap {self._lap_count}, waypoint "
            f"{self._waypoint_index + 1}/{len(self._waypoints)}: "
            f"x={target['x']:.2f}, z={target['z']:.2f}, "
            f"distance={horizontal_distance:.2f}, yaw_error={yaw_error:+.2f}"
        )
        self._apply_motion(up, down, False, False, forward, False, yaw_left, yaw_right)

    def set_search_area(self, area):
        self._x_min, self._x_max = area.x_min, area.x_max
        self._z_min, self._z_max = area.z_min, area.z_max
        self._waypoints = []
        self._waypoint_index = self._lap_count = 0
        self._excluded_areas = []
        self._target_y = None
        self._rng = random.Random(self._seed)

    def reset(self):
        super().reset()
        self._waypoints = []
        self._waypoint_index = 0
        self._lap_count = 0
        self._target_y = self._randomized_depth(self._configured_target_y)

    def _current_waypoint(self, auv_pos: dict) -> dict[str, float] | None:
        while self._waypoints and self._waypoint_index < len(self._waypoints):
            target = self._waypoints[self._waypoint_index]
            horizontal_distance = math.sqrt(
                (target["x"] - float(auv_pos["x"])) ** 2
                + (target["z"] - float(auv_pos["z"])) ** 2
            )
            if self._is_excluded(target):
                print(
                    f"[GridSearch] Skipping waypoint {self._waypoint_index + 1}/{len(self._waypoints)} "
                    "inside an already opened area."
                )
                self._waypoint_index += 1
                continue
            if horizontal_distance > self._waypoint_tolerance:
                return target
            print(f"[GridSearch] Reached waypoint {self._waypoint_index + 1}/{len(self._waypoints)}.")
            self._waypoint_index += 1

        if self._waypoints and self._waypoint_index >= len(self._waypoints):
            self._lap_count += 1
            print(f"[GridSearch] Completed sweep lap {self._lap_count}; restarting route from current position.")
            self._build_route_from_position(auv_pos)

        return self._waypoints[self._waypoint_index] if self._waypoints else None

    def _build_route_from_position(self, auv_pos: dict) -> None:
        x = float(auv_pos["x"])
        z = float(auv_pos["z"])
        if self._randomize_route:
            start_x = self._rng.choice((self._x_min, self._x_max))
            start_z = self._rng.choice((self._z_min, self._z_max))
            sweep_along_x = bool(self._rng.getrandbits(1))
        else:
            start_x = self._x_min if abs(x - self._x_min) <= abs(x - self._x_max) else self._x_max
            start_z = self._z_min if abs(z - self._z_min) <= abs(z - self._z_max) else self._z_max
            sweep_along_x = True

        end_x = self._x_max if start_x == self._x_min else self._x_min
        waypoints: list[dict[str, float]] = []

        if sweep_along_x:
            z_step = self._lane_spacing if start_z == self._z_min else -self._lane_spacing
            lane_values = self._bounded_values(start_z, z_step, self._z_min, self._z_max)
            lane_start_x = start_x
            lane_end_x = end_x
            for lane_z in lane_values:
                if not waypoints or waypoints[-1]["x"] != lane_start_x or waypoints[-1]["z"] != lane_z:
                    waypoints.append({"x": lane_start_x, "z": lane_z})
                waypoints.append({"x": lane_end_x, "z": lane_z})
                lane_start_x, lane_end_x = lane_end_x, lane_start_x
        else:
            end_z = self._z_max if start_z == self._z_min else self._z_min
            x_step = self._lane_spacing if start_x == self._x_min else -self._lane_spacing
            lane_values = self._bounded_values(start_x, x_step, self._x_min, self._x_max)
            lane_start_z = start_z
            lane_end_z = end_z
            for lane_x in lane_values:
                if not waypoints or waypoints[-1]["x"] != lane_x or waypoints[-1]["z"] != lane_start_z:
                    waypoints.append({"x": lane_x, "z": lane_start_z})
                waypoints.append({"x": lane_x, "z": lane_end_z})
                lane_start_z, lane_end_z = lane_end_z, lane_start_z

        if self._randomize_route and self._waypoint_jitter > 0.0:
            waypoints = [self._jitter_waypoint(waypoint) for waypoint in waypoints]

        self._waypoints = [waypoint for waypoint in waypoints if not self._is_excluded(waypoint)]
        self._waypoint_index = 0
        print(
            f"[GridSearch] Built {len(self._waypoints)} waypoints over "
            f"x=[{self._x_min}, {self._x_max}], z=[{self._z_min}, {self._z_max}], "
            f"lane_spacing={self._lane_spacing}, randomized={self._randomize_route}, seed={self._seed}."
        )

    def _lane_values(self, start_z: float, z_step: float) -> list[float]:
        return self._bounded_values(start_z, z_step, self._z_min, self._z_max)

    @staticmethod
    def _bounded_values(start: float, step: float, lower: float, upper: float) -> list[float]:
        values = []
        value = start
        if step > 0:
            while value <= upper:
                values.append(value)
                value += step
            if values[-1] < upper:
                values.append(upper)
        else:
            while value >= lower:
                values.append(value)
                value += step
            if values[-1] > lower:
                values.append(lower)
        return values

    def _jitter_waypoint(self, waypoint: dict[str, float]) -> dict[str, float]:
        return {
            "x": min(
                self._x_max,
                max(
                    self._x_min,
                    waypoint["x"] + self._rng.uniform(-self._waypoint_jitter, self._waypoint_jitter),
                ),
            ),
            "z": min(
                self._z_max,
                max(
                    self._z_min,
                    waypoint["z"] + self._rng.uniform(-self._waypoint_jitter, self._waypoint_jitter),
                ),
            ),
        }

    def _randomized_depth(self, target_y: float | None) -> float | None:
        if target_y is None:
            return None
        target = float(target_y)
        if not self._randomize_route or self._depth_jitter <= 0.0:
            return target
        return target + self._rng.uniform(-self._depth_jitter, self._depth_jitter)

    def mark_opened_area(self, position: dict, radius: float | None = None) -> None:
        if not isinstance(position, dict):
            return
        try:
            area = {
                "x": float(position["x"]),
                "z": float(position["z"]),
                "radius": float(radius if radius is not None else self._exclusion_radius),
            }
        except (KeyError, TypeError, ValueError):
            return
        self._excluded_areas.append(area)
        print(
            f"[GridSearch] Marked opened area at x={area['x']:.2f}, z={area['z']:.2f}, "
            f"radius={area['radius']:.2f}; future grid sweeps will skip it."
        )

    def _is_excluded(self, waypoint: dict[str, float]) -> bool:
        for area in self._excluded_areas:
            distance = math.sqrt(
                (waypoint["x"] - area["x"]) ** 2 + (waypoint["z"] - area["z"]) ** 2
            )
            if distance <= area["radius"]:
                return True
        return False

    def action(self):
        self.navigate()
        from .action import Action
        return Action.from_movement_keys(dict(self._movement_keys), source="grid")
