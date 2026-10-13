"""Associate YOLO boxes with simulator targets using the expert bearing rule."""
import math


def match_detections(snapshot, detections, frame_width, config):
    positions = snapshot.get("latestPositions", {})
    auv, rotation = positions.get("auvPosition"), positions.get("auvRotation")
    if not auv or not rotation or not frame_width:
        return []
    yaw = math.radians(float(rotation["y"]))
    matches = []
    for detection in detections:
        label = str(detection.get("class_name", "")).lower()
        confidence = detection.get("confidence")
        if not any(word in label for word in ("box", "crate", "container", "case")):
            continue
        if (isinstance(confidence, bool) or not isinstance(confidence, (float, int))
                or not math.isfinite(confidence) or not config.detector_confidence <= confidence <= 1):
            continue
        xywh = detection.get("xywh") or []
        if len(xywh) != 4 or not all(isinstance(v, (float, int)) and math.isfinite(v) for v in xywh):
            continue
        if not 0 <= xywh[0] <= frame_width or xywh[2] <= 0 or xywh[3] <= 0:
            continue
        bearing = (xywh[0] / frame_width - 0.5) * math.radians(config.camera_hfov_deg)
        best = None
        for box in snapshot.get("boxTimeList", []):
            target, box_id = box.get("boxPosition"), box.get("boxID")
            if not isinstance(target, dict) or not isinstance(box_id, int) or isinstance(box_id, bool):
                continue
            dx, dz = float(target["x"]) - float(auv["x"]), float(target["z"]) - float(auv["z"])
            relative = (math.atan2(dx, dz) - yaw + math.pi) % (2 * math.pi) - math.pi
            error = abs((relative - bearing + math.pi) % (2 * math.pi) - math.pi)
            score = error + min(math.hypot(dx, dz), 100) * 0.0005
            if error <= math.radians(config.match_tolerance_deg) and (best is None or score < best[0]):
                best = (score, box_id)
        if best is not None:
            matches.append({"box_id": best[1], "confidence": confidence, "timestamp": detection.get("timestamp"),
                            "area": xywh[2] * xywh[3], "bearing_error": best[0]})
    return sorted(matches, key=lambda match: (-match["area"], match["bearing_error"]))
