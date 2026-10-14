"""Send a YOLO box detection's confidence category to the simulator."""
import math

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
        """Immediately send one confidence chord for every captured box frame.

        This intentionally does not wait for a matched target, proximity,
        simulator state, or telemetry/camera freshness.  The only filter is
        that the model must identify a box-like class at the configured YOLO
        confidence threshold.  If multiple boxes are in a frame, the highest
        confidence one determines the chord.
        """
        result = {"source": "yolo_detector", "score": None, "level": None, "key": None, "sent": False}
        detection = self._best_box_detection(capture)
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
