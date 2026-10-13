"""
Autonomous navigator module for ONR project autonomous deviations for all AUV Roles.
"""
from modules.state.atomic_state import AtomicState

from .navigator import Navigator

class AutonomousNavigator(Navigator):
    def __init__(self, state: AtomicState, init_role: str, boxes_collected: list, set_role: callable, switch_to_static: callable = None, collision_threshold=5.0, yaw_threshold=0.2, interaction_threshold=15.0, follow_distance=5.0, size_threshold=0.05, monitor=None):
        super().__init__(state, init_role, boxes_collected, set_role, switch_to_static, collision_threshold, yaw_threshold, interaction_threshold, follow_distance)
        self._yaw_threshold = yaw_threshold
        self._target_size = 0.2  # Desired normalized width (how close to get)
        self._size_threshold = size_threshold  # Size tolerance
        self._img_width = monitor['width'] if monitor else 1920
        self._img_height = monitor['height'] if monitor else 1080
        self._monitor_center_x = self._img_width / 2
        self._monitor_center_y = self._img_height / 2

    def navigate(self, detections=[]):
        if not len(detections) > 0:
            print("[Autonomous] No detections — searching...")
            # self._search_pattern()
            return

        # Pull out detection parameters from the first detection
        detection_center_x, detection_center_y, detection_w, _ = detections[0][:4]
    
        # Calculate normalized alignment errors, uses standard image coords
        # Positive error = target is right/down, Negative = target is left/up
        error_x = (detection_center_x - self._monitor_center_x) / self._img_width # Normalize to [-1, 1]
        error_y = (detection_center_y - self._monitor_center_y) / self._img_height # Normalize to [-1, 1]

        # Size error (positive = too small/far, negative = too big/close)
        error_size = (self._target_size - (detection_w / self._img_width))

        print(f"[Autonomous] Detection at x={detection_center_x:.2f}, y={detection_center_y:.2f}, width={detection_w:.2f}")
        print(f"[Autonomous] Errors: x={error_x:+.2f}, y={error_y:+.2f}, size={error_size:+.2f}")

        # Determine yaw commands based on horizontal position
        yaw_left = error_x < -self._yaw_threshold / 2 # Target is left
        yaw_right = error_x > self._yaw_threshold / 2  # Target is right
        
        # Determine vertical movement based on vertical position
        up = error_y < -self._yaw_threshold / 2  # Target is above (move up towards it)
        down = error_y > self._yaw_threshold / 2  # Target is below (move down towards it)

        # Determine forward/backward movement based on size
        # Move forward if target is too small (far away) and reasonably centered
        within_range = error_size <= 0 or error_size < self._size_threshold
        forward = not within_range  # Too far
        backward = False # Never move backward in autonomous mode
        
        # No left/right strafing
        left = False
        right = False

        if within_range:
            print("[Autonomous] Target is within desired size range.")
            nearest_box = self.nearest_box()
            # Check if this box has already been collected
            if nearest_box and nearest_box["boxID"] not in self._boxes_collected:
                print(f"[Autonomous] AUV is close to box {nearest_box['boxID']}'s position.")
                self._signal_diver(box_id=nearest_box["boxID"])
            elif nearest_box:
                print(f"[Autonomous] Box {nearest_box['boxID']} already collected. Forcing switch to static mode.")
                self.stop_waiting()
                self._apply_motion(False, False, False, False, False, False, False, False)  # Stop movement
                # Trigger immediate switch to static mode via callback
                if self._switch_to_static:
                    self._switch_to_static()
            else:
                print("[Autonomous] No nearest box found. Forcing switch to static mode.")
                self.stop_waiting()
                self._apply_motion(False, False, False, False, False, False, False, False)  # Stop movement
                # Trigger immediate switch to static mode via callback
                if self._switch_to_static:
                    self._switch_to_static()
        else:
            self._apply_motion(up, down, left, right, forward, backward, yaw_left, yaw_right)
        
        return

    def _search_pattern(self):
        # Basic scanning motion if no target - slowly rotate to search
        print("[Autonomous] Scanning environment...")
        # Implement a simple yaw rotation pattern
        self._apply_motion(False, False, False, False, False, False, False, True) # Rotate right