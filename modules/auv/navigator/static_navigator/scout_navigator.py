"""
Scout navigator module for ONR project scout AUV Role.
"""
from modules.state.atomic_state import AtomicState

from ..navigator import Navigator
import math

class ScoutNavigator(Navigator):
    def __init__(self, state: AtomicState, init_role: str, boxes_collected: list, set_role: callable, switch_to_static: callable = None, collision_threshold=5.0, yaw_threshold=0.2, interaction_threshold=15.0, follow_distance=5.0):
        super().__init__(state, init_role, boxes_collected, set_role, switch_to_static, collision_threshold, yaw_threshold, interaction_threshold, follow_distance)
        self._next_box = None

    def _get_next_box(self):
        # Retrieve the next box position that hasn't been collected yet
        boxes = self._state.snapshot().get("boxTimeList", [])
        print(self._state.snapshot())
    
        if not boxes:
            print("[Scout] Failed to retrieve box information.")
            return
        
        box_dist: list = [b for b in boxes if b.get("auvDist") is not None]
        if not box_dist:
            print("[Scout] No boxes with distance information available.")
            return
        
        # Sort boxes by distance and pick the closest uncollected one
        box_dist.sort(key=lambda b: b["auvDist"])
        for box in box_dist:
            box_id = box["boxID"]
            if box_id not in self._boxes_collected:
                self._next_box = {
                    "id": box_id,
                    "position": box["boxPosition"]
                }
                return
        return
    
    def navigate(self, detections=[]):
        if self._next_box is None:
            self._get_next_box()
            if self._next_box is None:
                print("[Scout] No more boxes to collect. Switching to Companion role.")
                self._set_role("companion")
                return  # No target detected
            
        positions = self._state.snapshot().get("latestPositions", {})

        diverPos = positions.get("diverPosition", None)
        auvPos = positions.get("auvPosition", None)
        auvRot = positions.get("auvRotation", None)

        if not diverPos or not auvPos or not auvRot:
            print("[Scout] Missing diver or AUV position or rotation.")
            return  # No target detected
        
        # Calculate distance to diver
        distance = Navigator.get_2d_distance(auvPos, diverPos)

        # If diver is too far away, switch to companion role to follow diver
        if distance > self._follow_distance:
            print(f"[Scout] Diver is too far away (distance={distance:.2f}m). Switching to companion role.")
            self._set_role("companion")
            return
        
        # Extract box position
        box_pos = self._next_box["position"]

        # Calculate cartesian deltas from AUV to box (world frame)
        box_dx = box_pos["x"] - auvPos["x"] # Horizontal difference (left/right)
        box_dy = box_pos["y"] - auvPos["y"] # Vertical difference (up/down)
        box_dz = box_pos["z"] - auvPos["z"] # Horizontal difference (forward/backward)

        # Calculate horizontal distance and total distance to the box
        horizontal_distance = Navigator.get_2d_distance(auvPos, box_pos)
        box_dist = Navigator.get_3d_distance(auvPos, box_pos)
        
        print(f"[Scout] Navigating towards box at position: x={box_pos['x']}, y={box_pos['y']}, z={box_pos['z']}, distance={box_dist:.2f}")
        
        # Calculate desired bearing (yaw) in world frame (X-Z horizontal plane)
        desired_yaw = math.atan2(box_dx, box_dz)
        
        # Calculate yaw error relative to current AUV orientation
        current_yaw_rad = math.radians(auvRot["y"])
        yaw_error = desired_yaw - current_yaw_rad
        
        # Normalize yaw error to [-pi, pi] to always take shortest path
        yaw_error = (yaw_error + math.pi) % (2 * math.pi) - math.pi
        
        # Determine yaw commands based on error (only correct if outside dead-band)
        # Negative error = target is to the left, turn left
        # Positive error = target is to the right, turn right
        yaw_left = yaw_error < -self._yaw_threshold
        yaw_right = yaw_error > self._yaw_threshold
        
        # Determine vertical movement based on dy (Y axis is vertical in Unity)
        up = box_dy > 0.5  # Box is above (higher Y), move up
        down = box_dy < -0.5  # Box is below (lower Y), move down
        
        # Create a dynamic forward cone based on distance to diver
        # Wider cone when farther away, narrower when closer
        cone_max_dist = 30.0  # Max distance for full cone
        cone_min_dist = self._follow_distance  # Min distance for minimum cone
        
        # Calculate cone ratio (0.0 at min distance, 1.0 at max distance or beyond)
        cone_ratio = max(0.0, min(1.0, (horizontal_distance - cone_min_dist) / (cone_max_dist - cone_min_dist)))
        
        # The cone half-angle ranges from _yaw_threshold to π/2 radians (90 degrees)
        # Ensures cone is never narrower than the alignment threshold
        max_cone_angle = math.pi / 2
        cone_threshold = self._yaw_threshold + (max_cone_angle - self._yaw_threshold) * cone_ratio
        in_cone = abs(yaw_error) < cone_threshold

        # Determine forward movement: allow if target is in the forward cone AND beyond interaction threshold
        # This allows approach even with imprecise bearing, reducing distance-based bearing errors
        forward = horizontal_distance > self._follow_distance and in_cone
        backward = False  # Don't move backward
        
        # No left/right strafing
        left = False
        right = False
        
        # Apply motion only when in searching state
        if box_dist < self._follow_distance:
            # Check if this box has already been collected
            if self._next_box["id"] in self._boxes_collected:
                print(f"[Scout] Box {self._next_box['id']} already collected. Moving to next box.")
                self._next_box = None  # Reset to find next uncollected box
                self.stop_waiting()
                self._apply_motion(False, False, False, False, False, False, False, False)  # Stop movement
            else:
                print("[Scout] AUV is close to box's position.")
                self._signal_diver(box_id=self._next_box["id"])
        else:
            self._apply_motion(up, down, left, right, forward, backward, yaw_left, yaw_right)
        
        return

        