import threading
import time
import cv2
import mss
import numpy as np
import torch
from ultralytics import YOLO

class VisionSystem:
    def __init__(self, model_path, monitor_index=2, conf=0.4):
        try:
            print(f"[Vision] YOLO model loading from: {model_path}")
            self._model = YOLO(model_path)
            # Basic sanity check: ultralytics YOLO exposes .model or .names
            if not hasattr(self._model, "model") and not hasattr(self._model, "names"):
                raise RuntimeError("YOLO model loaded but missing expected attributes")
            
            self._model.set_classes([ "small crate", "small box", "partial box", "blurry box", "box","crate"]) #(["box"])  ###
            if torch.cuda.is_available():
                print("[Vision] CUDA is available. Moving YOLO model to GPU.")
                self._model.model.to('cuda')
            print(f"[Vision] YOLO model loaded from: {model_path}")
        except Exception as e:
            print(f"[Vision] Failed to load YOLO model from {model_path}: {e}")
            raise

        self._monitor_index = monitor_index
        self._conf = conf

        self._running = False
        self._thread = None
        self._lock = threading.Lock()
        
        self._frame = None
        self._detections = []
       
        # Validate monitor exists (will create temp mss instance)
        with mss.mss() as sct:
            monitors = sct.monitors
            if monitor_index > len(monitors)-1:
                raise ValueError(f"Monitor {monitor_index} not available. Found: {len(monitors)-1}")
            self._monitor = monitors[monitor_index]
            print(f"[Vision] Capturing from monitor {monitor_index}: {self._monitor}")
        
        # Will create mss instance in the worker thread
        self._sct = None

    def start(self):
        if self._running:
            return
        print(f"[Vision] Starting YOLO vision system (monitor_index={self._monitor_index})")
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self):
        print("[Vision] Stopping vision system")
        self._running = False
        if self._thread:
            self._thread.join()
            self._thread = None
        # Clean up mss instance if it was created
        # Note: mss uses thread-local storage, so we can't close it from a different thread
        # The worker thread will clean it up when it exits
        self._sct = None

    def _capture_frame(self):
        """Capture frame depending on the source type."""
        # Convert screenshot to numpy array and BGR image for OpenCV
        img = np.array(self._sct.grab(self._monitor))
        if img is None or img.size == 0:
            print("[Vision] Captured empty frame")
            return None
        frame = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return frame

    def _run_loop(self):
        """Continuously capture frames and run YOLO inference."""
        # Create mss instance in this thread (required for thread-local storage)
        self._sct = mss.mss()
        
        try:
            while self._running:
                frame = self._capture_frame()
                if frame is None:
                    time.sleep(0.05)
                    continue

                results = self._model.predict(frame, conf=self._conf, verbose=False)
                boxes = results[0].boxes.xywh.cpu().numpy() if len(results) > 0 else []

                with self._lock:
                    self._frame = frame
                    self._detections = boxes

                # Optional: visualize for debugging (updates every 500ms to avoid flooding)
                annotated = results[0].plot() if len(results) > 0 else frame
                cv2.imshow("YOLO Monitor Feed", annotated)
                if cv2.waitKey(50) == 27:  # 500ms delay between updates, ESC to exit
                    break

                time.sleep(0.05)  # ~20 FPS limit
        finally:
            # Clean up mss instance in the same thread that created it
            if self._sct:
                self._sct.close()
                self._sct = None

    def get_detections(self):
        with self._lock:
            return self._detections.copy()

    def get_frame(self):
        with self._lock:
            return self._frame.copy() if self._frame is not None else None
        
    def get_monitor(self):
        return self._monitor
