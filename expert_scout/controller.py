"""Nearest-box scouting with the original diver interaction rules."""
import time
from .action import Action
from .matching import match_detections
from .interaction import collection_from_interaction
from .maps import map_name
from .routing import nearest_box, valid_position, distance


class ExpertController:
    def __init__(self, config, grid, approach, collected, search_areas=None, map_override="auto"):
        self.config, self.grid, self.approach, self.collected = config, grid, approach, collected
        self.search_areas, self.map_override = search_areas, map_override
        self.current_map = None
        self.search_bounds = None
        self.last_sim_time = None
        self.new_session = False
        self.map_epoch = 0
        self.map_changed_at = None
        self._reset_control()
        self.approach._collect_box = self.reached

    def _reset_control(self):
        self.phase = "searching"
        self.target_id = None
        self.target_detection = None
        self.event = None
        self.streak = 0
        self.candidate_id = None
        self.last_frame = None
        self.diver_paused = False

    def _select_map(self, name):
        self._reset_control()
        self.collected.clear()
        self.approach.clear_target_box()
        self.approach._clear_motion_keys()
        area = self.search_areas[name]
        self.grid.set_search_area(area)
        self.current_map, self.search_bounds = name, area.to_dict()
        self.new_session = False
        self.map_epoch += 1
        self.map_changed_at = time.time()
        self.event = "map_selected"
        print(f"Map: {name}, grid X=[{area.x_min:.3f}, {area.x_max:.3f}], "
              f"Z=[{area.z_min:.3f}, {area.z_max:.3f}]")

    def reached(self, box_id):
        if self.phase == "approaching" and box_id == self.target_id:
            self.phase, self.event = "waiting_for_diver", "box_reached"

    def _collect(self, interactions, now):
        for snapshot in interactions:
            age = now - snapshot.get("_sourceMtime", 0)
            pressed_at = snapshot.get("_interaction_time", 0)
            if (snapshot.get("curState") != "searching" or not 0 <= age <= self.config.max_sensor_age_sec
                    or not 0 <= now - pressed_at <= self.config.max_sensor_age_sec
                    or (self.map_changed_at is not None and pressed_at < self.map_changed_at)):
                continue
            if self.current_map is not None and map_name(snapshot, self.map_override) != self.current_map:
                continue
            result = collection_from_interaction(snapshot, self.config.interaction_distance)
            if result is None:
                continue
            box_id, close = result
            if box_id in self.collected:
                continue
            self.collected.append(box_id)
            box = next(b for b in snapshot["boxTimeList"] if b["boxID"] == box_id)
            self.grid.mark_opened_area(box["boxPosition"])
            if box_id == self.target_id or (self.phase == "waiting_for_diver" and close):
                self._finish()
            self.event = "diver_collection_inferred"

    def _waiting_action(self, signal=False):
        # The original scout holds with clockwise yaw and repeated light flashes.
        self.approach._apply_motion(False, False, False, False, False, False, False, True)
        return Action.from_movement_keys(self.approach._movement_keys, source="waiting_for_diver").copy_with(
            signal=signal, lights=True)

    def _finish(self):
        self.phase, self.event = "searching", "route_resumed"
        self.target_id = self.target_detection = None
        self.approach.clear_target_box()
        self.streak = 0

    def _diver_wait(self, snapshot):
        pose = snapshot.get("latestPositions", {})
        auv, diver = pose.get("auvPosition"), pose.get("diverPosition")
        if not valid_position(auv) or not valid_position(diver):
            return Action.none(source="waiting_for_diver_pose")
        separation = ((auv["x"] - diver["x"]) ** 2 + (auv["z"] - diver["z"]) ** 2) ** 0.5
        if separation > self.config.diver_max_separation:
            self.diver_paused = True
        elif separation < self.config.diver_resume_separation:
            self.diver_paused = False
        if self.diver_paused:
            return Action.none(source="waiting_for_diver_to_follow")
        return None

    def _grid_action(self, snapshot):
        wait = self._diver_wait(snapshot)
        return wait if wait is not None else self.grid.action()

    def step(self, snapshot, capture, interactions=()):
        now = time.time()
        self.event = None
        pose = snapshot.get("latestPositions", {})
        state_age = now - snapshot.get("_sourceMtime", 0)
        if snapshot.get("curState") in ("titleScreen", "endScreen", "endProgram", "outOfOxygen") and 0 <= state_age <= self.config.max_sensor_age_sec:
            self.new_session = True
        if (snapshot.get("curState") != "searching" or not valid_position(pose.get("auvPosition")) or not pose.get("auvRotation")
                or not 0 <= state_age <= self.config.max_sensor_age_sec):
            if not snapshot.get("curState"):
                reason = "missing_game_state"
            elif snapshot.get("curState") != "searching":
                reason = "game_not_searching"
            elif not valid_position(pose.get("auvPosition")) or not pose.get("auvRotation"):
                reason = "missing_auv_pose"
            else:
                reason = "stale_telemetry"
            record = self._record(Action.none(source="telemetry_wait"))
            record["wait_reason"] = reason
            return record
        if self.search_areas is not None:
            name = map_name(snapshot, self.map_override)
            if name is None:
                return self._record(Action.none(source="waiting_for_map"), phase="waiting_for_map")
            sim_time = snapshot.get("totalTime")
            restarted = (isinstance(sim_time, (float, int)) and self.last_sim_time is not None
                         and sim_time < self.last_sim_time)
            if name != self.current_map or restarted or self.new_session:
                self._select_map(name)
            self.last_sim_time = sim_time if isinstance(sim_time, (float, int)) else None
        self._collect(interactions, now)
        matches = []
        if (capture is not None and 0 <= now - capture.timestamp <= self.config.max_sensor_age_sec
                and (self.map_changed_at is None or capture.timestamp >= self.map_changed_at)):
            matches = match_detections(snapshot, capture.detections, capture.width, self.config)
            for match in matches:
                match["timestamp"] = capture.timestamp
        target_matches = [m for m in matches if m["box_id"] == self.target_id]
        if target_matches:
            self.target_detection = target_matches[0]
        if self.phase in ("searching", "complete") and self.config.route_mode == "nearest":
            candidate = nearest_box(pose.get("auvPosition"), snapshot.get("boxTimeList", []), self.collected)
            if candidate is None:
                boxes = snapshot.get("boxTimeList", [])
                complete = boxes and all(b.get("boxID") in self.collected for b in boxes)
                phase = "complete" if complete else "waiting_for_boxes"
                return self._record(Action.none(source=phase), phase=phase)
            self.target_id = candidate["boxID"]
            self.target_detection = next((m for m in matches if m["box_id"] == self.target_id), None)
            self.approach.set_target_box(self.target_id)
            self.phase, self.event = "approaching", "nearest_box_selected"
        if self.phase == "searching":
            known = any(m["box_id"] in self.collected for m in matches)
            candidate = matches[0] if matches and not known else None
            if capture is not None and capture.timestamp != self.last_frame:
                box_id = candidate["box_id"] if candidate else None
                self.streak = self.streak + 1 if box_id is not None and box_id == self.candidate_id else int(box_id is not None)
                self.candidate_id, self.last_frame = box_id, capture.timestamp
            if candidate and self.streak >= self.config.detection_frames:
                self.target_id, self.target_detection = candidate["box_id"], candidate
                self.approach.set_target_box(self.target_id)
                self.phase, self.event = "approaching", "expert_started"
        if self.phase == "approaching":
            target = next((b for b in snapshot.get("boxTimeList", []) if b.get("boxID") == self.target_id), None)
            if target is None or not valid_position(target.get("boxPosition")):
                action = Action.none(source="waiting_for_target_telemetry")
            elif distance(pose["auvPosition"], target["boxPosition"]) < self.config.collection_distance:
                self.reached(self.target_id)
                action = self._waiting_action(signal=True)
            else:
                wait = self._diver_wait(snapshot)
                action = wait if wait is not None else self.approach.action()
                if self.event == "box_reached":
                    action = self._waiting_action(signal=True)
        elif self.phase == "waiting_for_diver":
            nearest = nearest_box(pose["auvPosition"], snapshot.get("boxTimeList", []))
            if nearest is None or distance(pose["auvPosition"], nearest["boxPosition"]) >= self.config.interaction_distance:
                self.phase, self.event = "approaching", "collection_wait_released"
                action = Action.none(source="waiting_for_target_telemetry")
            else:
                action = self._waiting_action()
        else:
            action = self._grid_action(snapshot)
        return self._record(action)

    def _record(self, action, phase=None):
        return {"phase": phase or self.phase, "route_mode": self.config.route_mode, "map_name": self.current_map, "map_epoch": self.map_epoch,
                "search_bounds": self.search_bounds, "event": self.event, "target_box_id": self.target_id,
                "target_detection": self.target_detection, "collected_box_ids": list(self.collected), "action": action}
