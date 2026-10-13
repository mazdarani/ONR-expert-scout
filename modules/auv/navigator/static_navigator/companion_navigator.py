"""
Companion navigator module for ONR project companion AUV Role.
"""

from modules.state.atomic_state import AtomicState

from ..navigator import Navigator
import math

class CompanionNavigator(Navigator):
    def __init__(self, state: AtomicState, init_role: str, boxes_collected: list, set_role: callable, switch_to_static: callable = None, collision_threshold=5.0, yaw_threshold=0.2, interaction_threshold=15.0, follow_distance=5.0):
        super().__init__(state, init_role, boxes_collected, set_role, switch_to_static, collision_threshold, yaw_threshold, interaction_threshold, follow_distance)

    def navigate(self, detections=[]) -> None:
        positions = self._state.snapshot().get("latestPositions", {})

        diverPos = positions.get("diverPosition", None)
        auvPos = positions.get("auvPosition", None)
        auvRot = positions.get("auvRotation", None)

        if not diverPos or not auvPos or not auvRot:
            print("[Companion] Missing diver or AUV position or rotation.")
            return  # No target detected
        
        # Compute cartesian deltas from AUV to diver
        # Unity coordinates: X = right, Y = up, Z = forward
        dx = diverPos["x"] - auvPos["x"]  # Horizontal difference (left/right)
        dy = diverPos["y"] - auvPos["y"]  # Vertical difference (up/down)
        dz = diverPos["z"] - auvPos["z"]  # Horizontal difference (forward/backward)
        
        # Calculate horizontal distance (X-Z plane) and total distance
        horizontal_distance = Navigator.get_2d_distance(auvPos, diverPos)
        distance = Navigator.get_3d_distance(auvPos, diverPos)

        # If close to the diver and in scout condition, switch back to scout role
        if self._init_role == "scout" and horizontal_distance < self._follow_distance:
            print("[Companion] Close enough to diver, switching back to Scout role.")
            self._set_role("scout")
            return
        
        print(f"[Companion] Navigating towards diver at position: x={diverPos['x']}, y={diverPos['y']}, z={diverPos['z']}, distance={distance:.2f}")
        
        # Calculate desired bearing (yaw) in world frame (X-Z horizontal plane)
        desired_yaw = math.atan2(dx, dz)
        
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
        
        # Check if well-aligned for precision work (using the tighter yaw threshold)
        is_aligned = abs(yaw_error) < self._yaw_threshold
        
        # Determine vertical movement based on dy (Y axis is vertical in Unity)
        up = dy > 0.5  # Diver is above (higher Y), move up
        down = dy < -0.5  # Diver is below (lower Y), move down
        
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
        if distance < self._follow_distance:
            print("[Companion] AUV is close to diver's position.")
            # Just adjust yaw when close
            self._apply_motion(False, False, False, False, False, False, yaw_left, yaw_right)
        else:
            self._apply_motion(up, down, left, right, forward, backward, yaw_left, yaw_right)
        
        return