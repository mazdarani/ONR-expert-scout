"""Capture the AUV view and detect boxes."""
from dataclasses import dataclass
import threading
import time


@dataclass
class Capture:
    image: object
    detections: list
    timestamp: float
    width: int
    height: int

    def metadata(self):
        return {"timestamp": self.timestamp, "width": self.width, "height": self.height}


class Detector:
    def __init__(self, checkpoint, monitor_index, confidence):
        from ultralytics import YOLO
        self.model = YOLO(str(checkpoint))
        self.monitor_index = monitor_index
        self.confidence = confidence
        self.latest = None
        self.error = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, name="auv-camera", daemon=True)

    def start(self):
        self.thread.start()

    def snapshot(self):
        with self.lock:
            return self.latest  # Capture and its image are replaced, never mutated.

    def _run(self):
        try:
            import mss
            import numpy as np
            with mss.mss() as screen:
                if self.monitor_index >= len(screen.monitors):
                    raise ValueError(f"AUV monitor {self.monitor_index} is unavailable")
                monitor = screen.monitors[self.monitor_index]
                while not self.stop_event.is_set():
                    image = np.asarray(screen.grab(monitor))[:, :, :3].copy()
                    timestamp = time.time()
                    height, width = image.shape[:2]
                    detections = []
                    for result in self.model.predict(image, conf=self.confidence, verbose=False):
                        for box in result.boxes:
                            class_id = int(box.cls[0])
                            detections.append({"xywh": box.xywh[0].cpu().tolist(),
                                               "confidence": float(box.conf[0]), "class_id": class_id,
                                               "class_name": result.names[class_id], "timestamp": timestamp,
                                               "frame_width": width, "frame_height": height})
                    with self.lock:
                        self.latest = Capture(image, detections, timestamp, width, height)
                    self.stop_event.wait(0.05)
        except Exception as error:
            self.error = error

    def close(self):
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=2)
