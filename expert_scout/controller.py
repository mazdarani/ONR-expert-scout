"""Nearest-box scouting with the original diver interaction rules."""
import time
from .action import Action
from .companion import CompanionNavigator
from .matching import match_detections
from .interaction import collection_from_interaction
from .maps import map_name
from .routing import nearest_box, valid_position, valid_rotation, distance
from .opened import OpenedBoxes


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
        self.companion = CompanionNavigator(
            approach._state, "scout", collected, lambda role: None,
            collision_threshold=approach._collision_threshold,
            yaw_threshold=approach._yaw_threshold)
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
        self.following_diver = False
        self.opened = OpenedBoxes()
        self.was_active = False
        self.camera_not_before = None

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
            pressed_at = snapshot.get("_interaction_time", 0)
            age = pressed_at - snapshot.get("_sourceMtime", 0)
            if (snapshot.get("curState") != "searching" or not 0 <= age <= self.config.max_sensor_age_sec
                    or pressed_at > now
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

    def _diver_action(self, snapshot):
        pose = snapshot.get("latestPositions", {})
        auv, diver = pose.get("auvPosition"), pose.get("diverPosition")
        if not valid_position(auv) or not valid_position(diver):
            return Action.none(source="waiting_for_diver_pose")
        separation = ((auv["x"] - diver["x"]) ** 2 + (auv["z"] - diver["z"]) ** 2) ** 0.5
        if separation > self.config.diver_max_separation:
            if not self.following_diver:
                self.event = "companion_started"
            self.following_diver = True
        elif separation < self.config.diver_resume_separation:
            if self.following_diver:
                self.event = "scouting_resumed"
            self.following_diver = False
        if self.following_diver:
            return self.companion.action(self.config.diver_resume_separation)
        return None

    def step(self, snapshot, capture, interactions=()):
        now = time.time()
        self.event = None
        pose = snapshot.get("latestPositions") or {}
        state_age = now - snapshot.get("_sourceMtime", 0)
        fresh = 0 <= state_age <= self.config.max_sensor_age_sec
        game_state = snapshot.get("curState")
        if game_state in ("titleScreen", "endScreen", "endProgram", "outOfOxygen") and fresh:
            if not self.new_session:
                self._collect(interactions, now)
            self.new_session = True
        selected_map = map_name(snapshot, self.map_override) if self.search_areas is not None else None
        if fresh and game_state == "searching" and self.search_areas is not None and selected_map is not None:
            sim_time = snapshot.get("totalTime")
            restarted = (isinstance(sim_time, (float, int)) and self.last_sim_time is not None
                         and sim_time < self.last_sim_time)
            if selected_map != self.current_map or restarted or self.new_session:
                self._select_map(selected_map)
            self.last_sim_time = sim_time if isinstance(sim_time, (float, int)) else None
        if (not self.new_session and (self.search_areas is None or selected_map == self.current_map)):
            # An F event from searching must survive the next frame entering SAGAT.
            self._collect(interactions, now)
            if fresh:
                for box_id in sorted(self.opened.update(snapshot)):
                    if box_id not in self.collected:
                        self.collected.append(box_id)
                        box = next((b for b in snapshot.get("boxTimeList", []) if b.get("boxID") == box_id), None)
                        if box and valid_position(box.get("boxPosition")):
                            self.grid.mark_opened_area(box["boxPosition"])
                        if box_id == self.target_id:
                            self._finish()
                        self.event = "opened_box_confirmed"
        if (game_state != "searching" or not valid_position(pose.get("auvPosition"))
                or not valid_rotation(pose.get("auvRotation")) or not fresh):
            self.was_active = False
            if not game_state:
                reason = "missing_game_state"
            elif game_state != "searching":
                reason = "game_not_searching"
            elif not valid_position(pose.get("auvPosition")) or not valid_rotation(pose.get("auvRotation")):
                reason = "missing_auv_pose"
            else:
                reason = "stale_telemetry"
            record = self._record(Action.none(source="telemetry_wait"))
            record["wait_reason"] = reason
            return record
        if not self.was_active:
            self.camera_not_before = now
        self.was_active = True
        if self.search_areas is not None and selected_map is None:
            return self._record(Action.none(source="waiting_for_map"), phase="waiting_for_map")
        count = snapshot.get("boxesFound")
        if isinstance(count, int) and count > len(self.collected):
            return self._record(Action.none(source="waiting_for_collection_identity"))
        matches = []
        if (capture is not None and 0 <= now - capture.timestamp <= self.config.max_sensor_age_sec
                and (self.map_changed_at is None or capture.timestamp >= self.map_changed_at)
                and capture.timestamp >= self.camera_not_before):
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
                action = self._diver_action(snapshot) if complete else None
                return self._record(action if action is not None else Action.none(source=phase), phase=phase)
            self.target_id = candidate["boxID"]
            self.target_detection = next((m for m in matches if m["box_id"] == self.target_id), None)
            self.approach.set_target_box(self.target_id)
            self.phase, self.event = "approaching", "nearest_box_selected"
        if self.phase == "searching":
            eligible = [m for m in matches if m["box_id"] not in self.collected
                        and not set(m.get("candidate_box_ids", [])).intersection(self.collected)]
            candidate = eligible[0] if eligible else None
            if capture is not None and capture.timestamp != self.last_frame:
                box_id = candidate["box_id"] if candidate else None
                self.streak = self.streak + 1 if box_id is not None and box_id == self.candidate_id else int(box_id is not None)
                self.candidate_id, self.last_frame = box_id, capture.timestamp
            if candidate and self.streak >= self.config.detection_frames:
                self.target_id, self.target_detection = candidate["box_id"], candidate
                self.approach.set_target_box(self.target_id)
                self.phase, self.event = "approaching", "expert_started"
        if self.phase in ("searching", "approaching"):
            companion = self._diver_action(snapshot)
            if companion is not None:
                return self._record(companion)
        if self.phase == "approaching":
            target = next((b for b in snapshot.get("boxTimeList", []) if b.get("boxID") == self.target_id), None)
            if target is None or not valid_position(target.get("boxPosition")):
                action = Action.none(source="waiting_for_target_telemetry")
            elif distance(pose["auvPosition"], target["boxPosition"]) < self.config.collection_distance:
                self.reached(self.target_id)
                action = self._waiting_action(signal=True)
            else:
                action = self.approach.action()
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
            action = self.grid.action()
        return self._record(action)

    def _record(self, action, phase=None):
        return {"phase": phase or self.phase, "route_mode": self.config.route_mode, "map_name": self.current_map, "map_epoch": self.map_epoch,
                "search_bounds": self.search_bounds, "event": self.event, "target_box_id": self.target_id,
                "target_detection": self.target_detection, "collected_box_ids": list(self.collected), "confirmed_box_ids": sorted(self.opened.confirmed),
                "camera_not_before": self.camera_not_before, "action": action}
