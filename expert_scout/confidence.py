"""Send the reached box's YOLO confidence category to the simulator."""
import math

CONFIDENCE_KEYS = {"low": "f6", "medium": "f7", "high": "f8"}


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
        self.last_sent = None
        self.next_send_at = 0

    def update(self, record, snapshot, now):
        result = {"source": "yolo_detector", "score": None, "level": None, "key": None, "sent": False}
        if record["phase"] != "waiting_for_diver":
            self.last_sent = None
            result["reason"] = "not_at_box"
            return result
        detection = record.get("target_detection") or {}
        score, timestamp = detection.get("confidence"), detection.get("timestamp")
        level = confidence_level(score, self.config)
        result.update(score=score, level=level)
        if level is None:
            result["reason"] = "no_valid_yolo_score"
            return result
        state_age = now - snapshot.get("_sourceMtime", 0)
        if snapshot.get("curState") != "searching" or not 0 <= state_age <= self.config.max_sensor_age_sec:
            result["reason"] = "inactive_or_stale_telemetry"
            return result
        if timestamp is None or not 0 <= now - timestamp <= self.config.max_sensor_age_sec:
            result["reason"] = "stale_yolo_score"
            return result
        box_id = record.get("target_box_id")
        if not self._target_is_nearest(snapshot, box_id):
            result["reason"] = "target_not_nearest_to_auv"
            return result
        identity = (box_id, level)
        result["key"] = CONFIDENCE_KEYS[level]
        if identity == self.last_sent:
            result["reason"] = "unchanged"
        elif now < self.next_send_at:
            result["reason"] = "rate_limited"
        else:
            actuation = self.actuator.tap_key(result["key"])
            result.update(actuation=actuation, sent=actuation["sent"], reason="category_sent" if actuation["sent"] else "dry_run")
            self.last_sent = identity
            self.next_send_at = now + self.config.confidence_key_interval_sec
            print(f"YOLO: box={box_id}, confidence={score:.3f}, level={level}, "
                  f"key={result['key'].upper()}, sent={result['sent']}", flush=True)
        return result

    def _target_is_nearest(self, snapshot, target_id):
        auv = snapshot.get("latestPositions", {}).get("auvPosition")
        if not auv:
            return False
        nearest, distance = None, float("inf")
        for box in snapshot.get("boxTimeList", []):
            position = box.get("boxPosition")
            if not position:
                continue
            current = math.sqrt(sum((position[axis] - auv[axis]) ** 2 for axis in ("x", "y", "z")))
            if current < distance:
                nearest, distance = box.get("boxID"), current
        return nearest == target_id and distance <= self.config.collection_distance
