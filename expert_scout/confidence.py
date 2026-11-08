"""Send a YOLO box detection's confidence category to the simulator."""
import math
from .matching import match_detections

CONFIDENCE_KEYS = {"low": "shift+1", "medium": "shift+2", "high": "shift+3"}


def confidence_level(score, config):
    if (isinstance(score, bool) or not isinstance(score, (float, int)) or not math.isfinite(score)
            or not config.detector_confidence <= score <= 1):
        return None
    if score < config.medium_confidence:
        return "low"
    return "medium" if score < config.high_confidence else "high"


class ConfidenceSender:
    def __init__(self, config, actuator):
        self.config, self.actuator = config, actuator

    def update(self, record, snapshot, now, capture=None):
        """Send current YOLO confidence during searching, excluding known opened boxes."""
        result = {"source": "yolo_detector", "score": None, "level": None, "key": None, "sent": False}
        if snapshot.get("curState") != "searching" or not 0 <= now - snapshot.get("_sourceMtime", 0) <= self.config.max_sensor_age_sec:
            result["reason"] = "inactive_or_stale_telemetry"
            return result
        if capture is None or not 0 <= now - capture.timestamp <= self.config.max_sensor_age_sec:
            result["reason"] = "stale_camera"
            return result
        if record.get("camera_not_before") is not None and capture.timestamp < record["camera_not_before"]:
            result["reason"] = "frame_before_resume"
            return result
        if record.get("selected_action", {}).get("source") == "waiting_for_collection_identity":
            result["reason"] = "opened_box_identity_pending"
            return result
        if record.get("selected_action", {}).get("source") in (
                "telemetry_wait", "waiting_for_map", "waiting_for_diver_pose", "waiting_for_target_telemetry"):
            result["reason"] = "controller_wait"
            return result
        opened = set(record.get("collected_box_ids", []))
        detection = self._best_box_detection(capture)
        if detection is not None and opened:
            matches = match_detections(snapshot, capture.detections, capture.width, self.config)
            eligible = [m for m in matches if m["box_id"] not in opened
                        and not opened.intersection(m["candidate_box_ids"])]
            if not eligible:
                result["reason"] = "opened_or_unidentified_box"
                return result
            selected = max(eligible, key=lambda m: m["confidence"])
            detection = capture.detections[selected["detection_index"]]
            result["box_id"] = selected["box_id"]
        if detection is None:
            result["reason"] = "no_valid_yolo_box"
            return result
        score = detection.get("confidence")
        level = confidence_level(score, self.config)
        result.update(score=score, level=level)
        if level is None:
            result["reason"] = "no_valid_yolo_score"
            return result
        result["key"] = CONFIDENCE_KEYS[level]
        actuation = self.actuator.tap_key(result["key"])
        result.update(actuation=actuation, sent=actuation["sent"], reason="detection_sent" if actuation["sent"] else "dry_run")
        print(f"YOLO: confidence={score:.3f}, level={level}, "
              f"key={result['key'].upper()}, sent={result['sent']}", flush=True)
        return result

    def _best_box_detection(self, capture):
        if capture is None:
            return None
        candidates = []
        for detection in capture.detections:
            label = str(detection.get("class_name", "")).lower()
            if not any(word in label for word in ("box", "crate", "container", "case")):
                continue
            if confidence_level(detection.get("confidence"), self.config) is not None:
                candidates.append(detection)
        return max(candidates, key=lambda item: item["confidence"], default=None)
