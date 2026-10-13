from abc import ABC, abstractmethod
from pynput.keyboard import Controller
import math
import time

from modules.state.atomic_state import AtomicState

KEY_MAPPING = {
    "up": "o",
    "down": "u",
    "left": "j",
    "right": "l",
    "forward": "i",
    "backward": "k",
    "yaw_left": "n",
    "yaw_right": "m",
    "signal": "0",
    "lights": "p"
}

class Navigator(ABC):
    def __init__(self, state: AtomicState, init_role: str, boxes_collected: list, set_role: callable, switch_to_static: callable = None, collision_threshold=5.0, yaw_threshold=0.2, interaction_threshold=15.0, follow_distance=5.0):
        self._keyboard = Controller()
        self._movement_keys = {
            "up": False,
            "down": False,
            "left": False,
            "right": False,
            "forward": False,
            "backward": False,
            "yaw_left": False,
            "yaw_right": False,
        }
        self._state = state
        self._init_role = init_role
        self._set_role = set_role
        self._switch_to_static = switch_to_static

        self._collision_threshold = collision_threshold
        self._yaw_threshold = yaw_threshold
        self._interaction_threshold = interaction_threshold
        self._follow_distance = follow_distance

        print(f"[Navigator] Starting boxes {boxes_collected}")
        self._boxes_collected = boxes_collected

        self._active = False
        self._hold = False # used only when dev knows hold and release conditions
        self._waiting_for_collection = False # used when waiting for user to collect box
        self._waiting_box_id = None # tracks which box we're waiting for

    @abstractmethod
    def navigate(self, detections=[]) -> None:
        """
        Compute navigation commands based on the current state. Calls apply_motion() to issue commands.

        Returns:
            bool: True if navigation command was successfully computed, False otherwise.
                - True indicates active navigation towards a target. Default for static navigators.
                - False indicates no target detected. Triggered on no detections for autonomous navigators.
        """
        pass

    # -----------------------------
    # NAVIGATOR STATE
    # -----------------------------
    def is_active(self) -> bool:
        """
        Check if the navigator is active.

        Returns:
            bool: True if the navigator is active, False otherwise.
        """
        return self._active
    
    def is_waiting_for_collection(self) -> bool:
        """
        Check if the navigator is waiting for box collection.

        Returns:
            bool: True if waiting for collection, False otherwise.
        """
        return self._waiting_for_collection
    
    def get_waiting_box_id(self) -> int:
        """
        Get the box ID that the navigator is waiting for.

        Returns:
            int or None: Box ID if waiting for collection, None otherwise.
        """
        return self._waiting_box_id

    def activate(self):
        """
        Activate the navigator.
        """
        self._active = True

    def deactivate(self):
        """
        Deactivate the navigator, releasing all keys.
        """
        for key in self._movement_keys:
            self._keyboard.release(KEY_MAPPING[key])
        self._active = False

    def reset(self):
        """
        Reset all navigator state to initial values.
        Call this when swapping navigators to ensure clean state.
        """
        # Reset all movement keys to False
        for key in self._movement_keys:
            self._movement_keys[key] = False
            self._keyboard.release(KEY_MAPPING[key])
        
        # Reset state flags
        self._hold = False
        self._waiting_for_collection = False
        self._waiting_box_id = None
        self._active = False
        
        print(f"[Navigator] State reset complete.")

    # -----------------------------
    # NAVIGATOR MOVEMENT
    # -----------------------------
    #OBSTACLE AVOIDANCE
    def _avoid_obstacles(self):
        """
        Method for obstacle avoidance with escape logic for tight spaces.
        Returns True if obstacles were detected and handled, False otherwise.
        """
        dists = self._state.snapshot().get("latestPositions", {})
        front = dists.get("auvDistToFront", float('inf'))
        left = dists.get("auvDistToLeft", float('inf'))
        right = dists.get("auvDistToRight", float('inf'))
        bottom = dists.get("auvDistToFloor", float('inf'))
        top = dists.get("auvDistToTop", float('inf'))

        print(f"[Navigator] Obstacle distances - Front: {front}, Left: {left}, Right: {right}, Bottom: {bottom}, Top: {top}")

        def is_too_close(distance: float) -> bool:
            # -10 means clear path, distances < collision_threshold are too close
            return -10 < distance < self._collision_threshold

        # Count how many obstacles are too close
        obstacles = {
            'front': is_too_close(front),
            'left': is_too_close(left),
            'right': is_too_close(right),
            'bottom': is_too_close(bottom),
            'top': is_too_close(top)
        }
        
        obstacle_count = sum(obstacles.values())
        
        # TIGHT SPACE ESCAPE: If 3+ obstacles detected, execute escape maneuver
        if obstacle_count >= 3:
            print(f"[Navigator] TIGHT SPACE DETECTED ({obstacle_count} obstacles)! Executing escape maneuver.")
            return self._execute_escape_maneuver(obstacles, front, left, right, bottom, top)
        
        # NORMAL AVOIDANCE: Handle individual obstacles with priority
        if obstacle_count > 0:
            return self._execute_normal_avoidance(obstacles)
        
        return False  # No obstacles detected

    def _execute_escape_maneuver(self, obstacles: dict, front: float, left: float, right: float, bottom: float, top: float):
        """
        Execute escape maneuver when surrounded by obstacles.
        Strategy: Move in the direction with most clearance, combining backward + vertical movement.
        """
        # Find direction with most clearance
        # Use -10 as infinite clearance indicator
        clearances = {
            'top': float('inf') if top == -10 else top,
            'bottom': float('inf') if bottom == -10 else bottom,
            'left': float('inf') if left == -10 else left,
            'right': float('inf') if right == -10 else right,
            'back': float('inf')  # Always prefer backing out if needed
        }
        
        # Remove directions that are blocked (distance < collision_threshold and not -10)
        available_clearances = {k: v for k, v in clearances.items() 
                                if v >= self._collision_threshold}
        
        if not available_clearances:
            # Emergency: All directions blocked, try smallest collision
            print("[Navigator] EMERGENCY: All directions blocked, forcing backward+up")
            self._movement_keys["forward"] = False
            self._movement_keys["backward"] = True
            self._movement_keys["up"] = True
            self._movement_keys["down"] = False
            self._movement_keys["left"] = False
            self._movement_keys["right"] = False
            self._movement_keys["yaw_left"] = False
            self._movement_keys["yaw_right"] = False
            return True
        
        # Move in direction with most clearance, prioritizing vertical + backward
        best_direction = max(available_clearances, key=available_clearances.get)
        clearance_val = "clear" if clearances[best_direction] == float('inf') else f"{available_clearances[best_direction]:.2f}m"
        print(f"[Navigator] Escaping via: {best_direction} (clearance: {clearance_val})")
        
        # Always back up when escaping
        self._movement_keys["forward"] = False
        self._movement_keys["backward"] = True
        
        # Add vertical or lateral movement based on best clearance
        if best_direction == 'top' and not obstacles['top']:
            self._movement_keys["up"] = True
            self._movement_keys["down"] = False
        elif best_direction == 'bottom' and not obstacles['bottom']:
            self._movement_keys["down"] = True
            self._movement_keys["up"] = False
        elif best_direction == 'left' and not obstacles['left']:
            self._movement_keys["left"] = True
            self._movement_keys["right"] = False
        elif best_direction == 'right' and not obstacles['right']:
            self._movement_keys["right"] = True
            self._movement_keys["left"] = False
        else:
            # Default: just back up and go up
            self._movement_keys["up"] = True
            self._movement_keys["down"] = False
            self._movement_keys["left"] = False
            self._movement_keys["right"] = False
        
        return True

    def _execute_normal_avoidance(self, obstacles: dict):
        """
        Execute normal obstacle avoidance for 1-2 obstacles.
        Uses priority system to avoid conflicting commands.
        """
        # Priority order: front > bottom > top > lateral
        # This prevents getting stuck on seafloor while avoiding front obstacles
        
        if obstacles['front']:
            print("[Navigator] Obstacle in front! Stopping forward movement.")
            self._movement_keys["forward"] = False
            # Prefer ascending over lateral movement, top check will convert to lateral if needed
            if not obstacles['top']:
                print("[Navigator] Ascending to avoid front obstacle.")
                self._movement_keys["up"] = True
                self._movement_keys["down"] = False
        
        if obstacles['bottom']:
            print("[Navigator] Obstacle below!")
            self._movement_keys["down"] = False
            # Always ascend when bottom obstacle detected
            if not obstacles['top']:
                print("[Navigator] Ascending to avoid bottom obstacle.")
                self._movement_keys["up"] = True
        
        if obstacles['top']:
            print("[Navigator] Obstacle above!")
            self._movement_keys["up"] = False
            # Prefer lateral movement if no vertical space, left preferred
            if not obstacles['left']:
                self._movement_keys["left"] = True
                self._movement_keys["right"] = False
            else:
                self._movement_keys["right"] = True
                self._movement_keys["left"] = False
        
        # Handle lateral obstacles
        if obstacles['left'] and not obstacles['right']:
            print("[Navigator] Obstacle on left! Moving right.")
            self._movement_keys["left"] = False
            self._movement_keys["right"] = True
        
        if obstacles['right'] and not obstacles['left']:
            print("[Navigator] Obstacle on right! Moving left.")
            self._movement_keys["right"] = False
            self._movement_keys["left"] = True
        
        return True

    # MOTION CONTROL
    def _apply_motion(self, up: bool, down: bool, left: bool, right: bool, forward: bool, backward: bool, yaw_left: bool, yaw_right: bool):
        """
        Apply motion commands to the AUV. Obstacle avoidance may override commands.

        Args:
            up (bool): Move up command.
            down (bool): Move down command.
            left (bool): Move left command.
            right (bool): Move right command.
            forward (bool): Move forward command.
            backward (bool): Move backward command.
            yaw_left (bool): Yaw left command.
            yaw_right (bool): Yaw right command.
        """
        # Set intended movement first
        self._movement_keys["up"] = up
        self._movement_keys["down"] = down
        self._movement_keys["left"] = left
        self._movement_keys["right"] = right
        self._movement_keys["forward"] = forward
        self._movement_keys["backward"] = backward
        self._movement_keys["yaw_left"] = yaw_left
        self._movement_keys["yaw_right"] = yaw_right

        # Obstacle avoidance can modify movement_keys to prevent collisions
        obstacles_detected = self._avoid_obstacles()
        
        if obstacles_detected:
            print("[Navigator] Movement adjusted for obstacle avoidance")


    # AUXILIARY MOVEMENT COMMANDS
    def _hold_position(self):
        """
        Method to hold the AUV's position (e.g., spin and flash lights).
        """
        print("[Navigator] Holding position...")
        self._keyboard.tap(KEY_MAPPING["lights"])
        self._apply_motion(False, False, False, False, False, False, False, True)

    def _signal_diver(self, box_id: int = None):
        """
        Method to signal the diver (e.g., ping, then spin and flash lights).
        
        Args:
            box_id (int): The ID of the box the AUV is waiting for collection.
        """
        print(f"[Navigator] Signaling diver for box {box_id}...")
        if not self._waiting_for_collection:
            self._waiting_for_collection = True
            self._waiting_box_id = box_id
            self._keyboard.tap(KEY_MAPPING["signal"])
            self._keyboard.tap(KEY_MAPPING["lights"])
            self._apply_motion(False, False, False, False, False, False, False, True)

    # MOVEMENT ISSUANCE
    def move_auv(self):
        """
        Issue movement commands to the AUV based on the current movement keys and hold state.
        Yaw movements use quick taps for finite control without acceleration.
        Axial movements use press-and-hold for continuous motion.
        """
        if not self._active:
            print("[Navigator] Not active, no movement issued.")
            self._apply_motion(False, False, False, False, False, False, False, False)  # Ensure no movement
            return
        
        # Check if currently waiting for box collection
        # nearest box can be computationally expensive
        # avoid with this pre-check
        if self._waiting_for_collection:
            print(f"[Navigator] Currently waiting for box {self._waiting_box_id} collection.")
            nearest_box = self.nearest_box()
            if nearest_box is None:
                print("[Navigator] No nearest box found; stopping wait.")
                self.stop_waiting()
                self._apply_motion(False, False, False, False, False, False, False, False)  # Stop movement
            else:
                box_id = nearest_box.get("boxID")
                dist_to_box = nearest_box.get("auvDist")

                if box_id is None or dist_to_box is None:
                    print("[Navigator] Nearest box data incomplete; stopping wait.")
                    self.stop_waiting()
                    self._apply_motion(False, False, False, False, False, False, False, False)  # Stop movement
                elif self._waiting_box_id is not None and box_id != self._waiting_box_id:
                    print(f"[Navigator] Nearest box {box_id} is not the target box {self._waiting_box_id}; stopping wait.")
                    self.stop_waiting()
                    self._apply_motion(False, False, False, False, False, False, False, False)  # Stop movement
                elif dist_to_box >= self._interaction_threshold:
                    print(f"[Navigator] Far from box {box_id} ({dist_to_box:.2f}m >= {self._interaction_threshold}m), stopping wait for collection.")
                    self.stop_waiting()
                    self._apply_motion(False, False, False, False, False, False, False, False)  # Stop movement

        if self._hold or self._waiting_for_collection:
            self._hold_position()

        # Separate yaw keys from axial movement keys
        yaw_keys = ["yaw_left", "yaw_right"]
        axial_keys = ["up", "down", "left", "right", "forward", "backward"]

        print(f"[Navigator] Current movement keys: {self._movement_keys}, Hold: {self._hold}, Waiting for collection: {self._waiting_for_collection}")
        
        # Handle yaw movements as quick taps (press and immediately release)
        for key in yaw_keys:
            if self._movement_keys[key]:
                self._keyboard.press(KEY_MAPPING[key])
                time.sleep(0.1)
                self._keyboard.release(KEY_MAPPING[key])
        
        # Handle axial movements as press-and-hold
        for key in axial_keys:
            if self._movement_keys[key]:
                self._keyboard.press(KEY_MAPPING[key])
            else:
                self._keyboard.release(KEY_MAPPING[key])

    # -----------------------------
    # UTILITY METHODS
    # -----------------------------
    @staticmethod
    def get_2d_distance(pos1, pos2):
        """
        Calculate Euclidean distance between two 2D positions in a 3d space (ignoring the Y axis).

        Args:
            pos1 (dict): First position with 'x', 'z' keys.
            pos2 (dict): Second position with 'x', 'z' keys.

        Returns:
            float: Euclidean distance between pos1 and pos2.
        """
        dx = pos1["x"] - pos2["x"]
        dz = pos1["z"] - pos2["z"]
        return math.sqrt(dx**2 + dz**2)

    @staticmethod
    def get_3d_distance(pos1, pos2):
        """
        Calculate Euclidean distance between two 3D positions.

        Args:
            pos1 (dict): First position with 'x', 'y', 'z' keys.
            pos2 (dict): Second position with 'x', 'y', 'z' keys.

        Returns:
            float: Euclidean distance between pos1 and pos2.
        """
        dx = pos1["x"] - pos2["x"]
        dy = pos1["y"] - pos2["y"]
        dz = pos1["z"] - pos2["z"]
        return math.sqrt(dx**2 + dy**2 + dz**2)
    
    # -----------------------------
    # BOX COLLECTION
    # -----------------------------
    def distance_to_diver(self):
        """
        Get the distance from the AUV to the diver.
        """
        positions = self._state.snapshot().get("latestPositions", {})

        diverPos = positions.get("diverPosition", None)
        auvPos = positions.get("auvPosition", None)

        if not diverPos or not auvPos:
            return None

        return Navigator.get_3d_distance(diverPos, auvPos)
    
    def diver_nearest_box(self):
        """
        Get the nearest box to the diver.
        """
        diverPos = self._state.snapshot().get("latestPositions", {}).get("diverPosition", None)

        if not diverPos:
            return None
        
        boxes = self._state.snapshot().get("boxTimeList", [])
        if not boxes:
            return None

        box_dist: list = [b for b in boxes if b.get("boxPosition") is not None]
        if not box_dist:
            return None
        
        return min(box_dist, key=lambda b: Navigator.get_3d_distance(diverPos, b["boxPosition"]))
    
    def nearest_box(self):
        """
        Retrieve the nearest box position from the state snapshot.

        Returns:
            dict or None: Nearest box position dictionary or None if no boxes are available.
        """
        print("[Navigator] Retrieving nearest box...")
        boxes = self._state.snapshot().get("boxTimeList", [])
        if not boxes:
            print("[Navigator] No boxes available.")
            return None
        
        # Filter out collected boxes and boxes without distance information
        box_dist: list = [b for b in boxes 
                          if b.get("auvDist") is not None]
        if not box_dist:
            print("[Navigator] No uncollected boxes with distance information available.")
            return None
        
        # Return the closest uncollected box
        return min(box_dist, key=lambda b: b["auvDist"])

    def stop_waiting(self):
        """
        Stop waiting for box collection and clear the waiting box ID.
        """
        self._waiting_for_collection = False
        self._waiting_box_id = None

    def is_waiting(self):
        """
        Check if the AUV is currently waiting for a box to be collected.
        """
        return self._waiting_for_collection