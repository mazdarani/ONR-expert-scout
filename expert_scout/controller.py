"""Nearest-box scouting with diver escort and confirmed collection."""
import time
from .action import Action
from .matching import match_detections
from .simulator import CollectionTracker
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
        self.collection_tracker = CollectionTracker()
        self.dwell_until = None
        self.flashes_left = 0
        self.next_flash_at = 0
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

    def _collect(self, snapshot, now):
        if 0 <= now - snapshot.get("_sourceMtime", 0) <= self.config.max_sensor_age_sec:
            self._apply_collection(self.collection_tracker.update(snapshot), snapshot, now)

    def _apply_collection(self, ids, snapshot, now):
        for box_id in ids:
            if box_id not in self.collected:
                self.collected.append(box_id)
                box = next((b for b in snapshot.get("boxTimeList", []) if b.get("boxID") == box_id), None)
                if box:
                    self.grid.mark_opened_area(box["boxPosition"])
        if self.target_id in self.collected and self.phase in ("approaching", "waiting_for_diver"):
            self.phase, self.event = "collection_dwell", "diver_collection_confirmed"
            self.dwell_until = now + self.config.collection_dwell_sec
            self.flashes_left, self.next_flash_at = 3, now

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
        separation = distance(auv, diver)
        if separation > self.config.diver_max_separation:
            self.diver_paused = True
        elif separation <= self.config.diver_resume_separation:
            self.diver_paused = False
        if self.diver_paused:
            return Action.none(source="waiting_for_diver_to_follow")
        return None

    def _grid_action(self, snapshot):
        wait = self._diver_wait(snapshot)
        return wait if wait is not None else self.grid.action()

    def step(self, snapshot, capture):
        now = time.time()
        self.event = None
        pose = snapshot.get("latestPositions", {})
        state_age = now - snapshot.get("_sourceMtime", 0)
        if snapshot.get("curState") in ("titleScreen", "endScreen", "endProgram", "outOfOxygen") and 0 <= state_age <= self.config.max_sensor_age_sec:
            self.new_session = True
        if (snapshot.get("curState") != "searching" or not valid_position(pose.get("auvPosition")) or not pose.get("auvRotation")
                or not 0 <= state_age <= self.config.max_sensor_age_sec):
            if snapshot.get("curState") != "searching" and 0 <= state_age <= self.config.max_sensor_age_sec:
                self.collection_tracker.update(snapshot)
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
        self._collect(snapshot, now)
        count = snapshot.get("boxesFound")
        if isinstance(count, int) and count > len(self.collected):
            return self._record(Action.none(source="waiting_for_collection_identity"))
        matches = []
        if (capture is not None and 0 <= now - capture.timestamp <= self.config.max_sensor_age_sec
                and (self.map_changed_at is None or capture.timestamp >= self.map_changed_at)):
            matches = match_detections(snapshot, capture.detections, capture.width, self.config)
            for match in matches:
                match["timestamp"] = capture.timestamp
        target_matches = [m for m in matches if m["box_id"] == self.target_id]
        if target_matches:
            self.target_detection = target_matches[0]
        if self.phase == "collection_dwell" and now >= self.dwell_until:
            self._finish()
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
            elif distance(pose["auvPosition"], target["boxPosition"]) <= self.config.collection_distance:
                self.reached(self.target_id)
                action = Action.none(source="waiting_for_diver")
            else:
                wait = self._diver_wait(snapshot)
                action = wait if wait is not None else self.approach.action()
                if self.event == "box_reached":
                    action = Action.none(source="waiting_for_diver")
        elif self.phase in ("waiting_for_diver", "collection_dwell"):
            action = Action.none(source=self.phase)
            if self.phase == "collection_dwell" and self.flashes_left and now >= self.next_flash_at:
                action = action.copy_with(lights=True)
                self.flashes_left -= 1
                self.next_flash_at = now + 0.75
        else:
            action = self._grid_action(snapshot)
        return self._record(action)

    def _record(self, action, phase=None):
        return {"phase": phase or self.phase, "route_mode": self.config.route_mode, "map_name": self.current_map, "map_epoch": self.map_epoch,
                "search_bounds": self.search_bounds, "event": self.event, "target_box_id": self.target_id,
                "target_detection": self.target_detection, "collected_box_ids": list(self.collected), "action": action}
