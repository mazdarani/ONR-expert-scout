import threading
import time

from pynput.keyboard import Listener

from modules.state.atomic_state import AtomicState
from modules.auv.vision.yolo_cv import VisionSystem
from modules.auv.navigator import AutonomousNavigator, CompanionNavigator, ScoutNavigator, Navigator

class AUV:
    def __init__(
        self,
        name: str,
        state: AtomicState,
        role: str,
        monitor_index: int,
        model_path: str,
        activate_after=1,
        deactivate_after=5,
        conf_threshold=0.4,
        interaction_threshold=10.0,
        follow_distance=5.0
    ):
        self._name = name
        self._state = state

        print(f"[{self._name}] Initializing vision system...")
        self._vision = VisionSystem(model_path=model_path, monitor_index=monitor_index, conf=conf_threshold)

        # Mode management
        self._mode = "static"  # "static" or "autonomous"
        self._init_role = role.lower()
        self._role = role.lower()

        print(f"[{self._name}] Initializing navigation systems...")
        self._interaction_threshold = interaction_threshold
        self._follow_distance = follow_distance
        self._navigator_list = []

        # Remember collection state
        self._collected_boxes = []

        print(f"[{self._name}] Initializing Companion navigator...")
        self._companion_navigator = CompanionNavigator(
            self._state,
            self._init_role,
            self._collected_boxes,
            self._set_role,
            self._switch_to_static,
            collision_threshold=1.5, 
            yaw_threshold=0.3,  
            interaction_threshold=self._interaction_threshold,
            follow_distance=self._follow_distance)  # Reduced to stay closer to diver
        self._navigator_list.append(self._companion_navigator)

        print(f"[{self._name}] Initializing Scout navigator...")
        self._scout_navigator = ScoutNavigator(
            self._state,
            self._init_role,
            self._collected_boxes,
            self._set_role,
            self._switch_to_static,
            collision_threshold=1.5, 
            yaw_threshold=0.3,  # ~17 degrees - consistent with companion
            interaction_threshold=self._interaction_threshold,
            follow_distance=self._follow_distance)
        self._navigator_list.append(self._scout_navigator)

        print(f"[{self._name}] Initializing Autonomous navigator...")
        self._autonomous_navigator = AutonomousNavigator(
            self._state,
            self._init_role,
            self._collected_boxes,
            self._set_role,
            self._switch_to_static,
            collision_threshold=1.5, 
            yaw_threshold=0.3,  # 30% of the screen width, AKA put it in the center 1/3
            interaction_threshold=self._interaction_threshold,
            follow_distance=self._follow_distance,
            size_threshold=0.01, # Default is set to 20% of screen width, the threshold widens or narrows the acceptable size range
            monitor=self._vision.get_monitor())
        self._navigator_list.append(self._autonomous_navigator)

        # Set static navigator based on role
        if self._role == "companion":
            self._static_navigator = self._companion_navigator
        elif self._role == "scout":
            self._static_navigator = self._scout_navigator
        else:
            raise ValueError(f"Unknown AUV role: {self._role}")
        
        # Initialize mode
        print(f"[{self._name}] Initializing STATIC mode with role '{self._role}'...")
        self._navigator = self._static_navigator
        self._last_time_autonomous = 0.0

        # Detection hysteresis parameters
        self._activate_after = activate_after
        self._deactivate_after = deactivate_after
        self._conf_threshold = conf_threshold

        # Counters
        self._consecutive_valid = 0
        self._consecutive_miss = 0

        # Control thread
        self._control_thread = threading.Thread(target=self._control_loop, daemon=True)

        # User interaction handling
        self._interaction_listener = Listener(on_press=None, on_release=self._on_user_interact)

    def start(self):
        print(f"[{self._name}] Starting systems...")
        print(f"[{self._name}] Starting vision system...")
        self._vision.start()
        print(f"[{self._name}] Starting control system...")
        self._control_thread.start()
        self._interaction_listener.start()
        self._navigator.activate()

    def stop(self):
        print(f"[{self._name}] Shutting down...")
        print(f"[{self._name}] Stopping control system...")
        self._control_thread.join(timeout=1.0)
        self._interaction_listener.stop()
        self._navigator.deactivate()
        print(f"[{self._name}] Stopping vision system...")
        self._vision.stop()

    # -----------------------------
    # CONTROL LOOP
    # -----------------------------
    def _control_loop(self):
        while True:
            active = self._state.snapshot().get("curState") == "searching"
            if not active:
                """
                IMPORTANT: Only deactivating the current navigator, since switching 
                modes AND roles also deactivates/activates navigators. You must
                ensure only the active navigator is active at any time.
                """
                self._navigator.deactivate()
                time.sleep(1.0) 
                continue
            else:
                self._navigator.activate()

            # Get latest detections
            detections = self._vision.get_detections()

            # Handle mode switching based on detections
            self._handle_mode_switching(detections)

            # Execute navigation
            self._navigator.navigate(detections=detections)
            self._navigator.move_auv()

            time.sleep(0.05)  # Control loop delay

    # -----------------------------
    # USER INTERACTION HANDLER
    # -----------------------------
    def _collect_box(self, box_id: int, close: bool = False):
        """
        Mark a box as collected across all navigators.
        """
        if box_id in self._collected_boxes:
            return
        
        self._collected_boxes.append(box_id)
        print(f"[{self._name}] Box {box_id} collected.")
        
        if self._navigator.is_waiting_for_collection() and close:
            print(f"[{self._name}] Collected the box the AUV was waiting for. Forcing STATIC mode navigation.")
            self._navigator.stop_waiting()
            self._switch_to_static()
        else:
            print(f"[{self._name}] Collected box {box_id}, but AUV was not waiting for it.")

    def _on_user_interact(self, key):
        """
        Method to handle user interaction events.
        """
        # print(f"[{self._name}] Key pressed: {key}")  # Add this
        # Check if key is a character key and if it's 'f' or '9'
        try:
            if not (hasattr(key, 'char') and key.char in ['f', '9']):
                return
        except AttributeError:
            return
        
        if key.char == 'f':
            print(f"[{self._name}] User crate interaction detected. Checking diver nearness to AUV and box...")

            # Get diver distance to box
            diver_box = self._navigator.diver_nearest_box()
            if not diver_box:
                print(f"[{self._name}] No box near diver.")
                return
            
            if diver_box["boxID"] in self._collected_boxes:
                print(f"[{self._name}] Diver's nearest box {diver_box['boxID']} already collected.")
                return
            
            diverPos = self._state.snapshot().get("latestPositions", {}).get("diverPosition", None)
            
            if Navigator.get_3d_distance(diverPos, diver_box["boxPosition"]) > self._interaction_threshold:
                print(f"[{self._name}] Diver is too far from nearest box: {diver_box['diverDist']:.2f}m (threshold: {self._interaction_threshold}m).")
                return
            
            auv_box = self._navigator.nearest_box()

            if not auv_box:
                print(f"[{self._name}] No box near AUV.")
                return
            
            # Check if AUV is waiting for a specific box
            if self._navigator.is_waiting_for_collection():
                waiting_box_id = self._navigator.get_waiting_box_id()
                
                # Validate the AUV is still near the box it's waiting for
                if not auv_box or auv_box["boxID"] != waiting_box_id:
                    print(f"[{self._name}] AUV was waiting for box {waiting_box_id}, but it's no longer the nearest box. Forcing STATIC mode navigation.")
                    self._navigator.stop_waiting()
                    self._switch_to_static()
                    # Still allow diver to collect their box
                    if diver_box["boxID"] != waiting_box_id:
                        self._collect_box(diver_box["boxID"], close=False)
                    return
                
                # Validate AUV is still close enough to the target box
                if auv_box["auvDist"] > self._interaction_threshold:
                    print(f"[{self._name}] AUV drifted too far from box {waiting_box_id}: {auv_box['auvDist']:.2f}m (threshold: {self._interaction_threshold}m). Forcing STATIC mode navigation.")
                    self._navigator.stop_waiting()
                    self._switch_to_static()
                    return
            
            # Get AUV distance to diver and nearest box
            auv_to_diver = self._navigator.distance_to_diver()

            if auv_to_diver is None:
                print(f"[{self._name}] Cannot determine distance to diver.")
                return
            
            # Check if AUV and diver are at the same box
            if auv_to_diver > self._interaction_threshold or auv_box["boxID"] != diver_box["boxID"]:
                print(f"[{self._name}] AUV and diver are at different boxes: AUV-{auv_box['boxID']}, Diver-{diver_box['boxID']}; Distance: {auv_to_diver:.2f}m (threshold: {self._interaction_threshold}m).")
                self._collect_box(diver_box["boxID"], close=False)
                return
            
            # All conditions met, collect the box
            self._collect_box(diver_box["boxID"], close=True)
        elif key.char == '9':
            print(f"[{self._name}] User interaction: Manual AUV reset.")
            # Reset mode switching counters
            self._consecutive_valid = 0
            self._consecutive_miss = 0
            # Switch back to static mode (will reset current navigator automatically)
            self._switch_to_static()

        return

    # -----------------------------
    # MODE SWITCHING LOGIC
    # -----------------------------
    def _handle_mode_switching(self, detections: list = []):        
        if self._navigator.is_waiting_for_collection(): # Hold off mode switching if waiting for box collection
            return

        has_valid = len(detections) > 0

        if self._mode == "static":
            if has_valid:
                self._consecutive_valid += 1
                self._consecutive_miss = 0
                print(f"[Static] Valid detection ({self._consecutive_valid}/{self._activate_after})")
                if self._consecutive_valid >= self._activate_after:
                    self._switch_to_autonomous()
            else:
                self._consecutive_valid = 0

        elif self._mode == "autonomous":
            if has_valid:
                self._consecutive_miss = 0
                self._consecutive_valid = 0
            else:
                self._consecutive_miss += 1
                print(f"[Autonomous] Missed detection ({self._consecutive_miss}/{self._deactivate_after})")
                if self._consecutive_miss >= self._deactivate_after:
                    self._switch_to_static()

    # -----------------------------
    # MODE TRANSITIONS
    # -----------------------------
    def _switch_to_autonomous(self):
        if time.time() - self._last_time_autonomous < 2.0: # Minimum time out of autonomous mode
            return
        
        print(f"[{self._name}] {self._name} entering AUTONOMOUS mode")
        self._mode = "autonomous"
        self._navigator.deactivate()  # Deactivate static navigator
        self._navigator.reset()  # Reset static navigator state
        self._navigator = self._autonomous_navigator
        self._navigator.activate()  # Activate autonomous navigator
        self._consecutive_valid = 0
    def _switch_to_static(self):
        self._last_time_autonomous = time.time()

        print(f"[{self._name}] {self._name} reverting to STATIC mode")
        self._mode = "static"
        self._navigator.deactivate()  # Deactivate autonomous navigator
        self._navigator.reset()  # Reset autonomous navigator state
        self._navigator = self._static_navigator
        self._navigator.activate()  # Activate static navigator
        self._consecutive_miss = 0

    # -----------------------------
    # ROLE TRANSITIONS
    # -----------------------------
    # Left as protected, since dynamic role changes should only occur via callbacks from navigators
    def _set_role(self, role: str):
        print(f"[{self._name}] {self._name} switching role to '{role}'")
        self._role = role.lower()
        if self._role == "companion":
            self._static_navigator.deactivate() # Deactivate current static navigator
            self._static_navigator.reset() # Reset old static navigator state
            self._static_navigator = self._companion_navigator # Switch to companion
            self._static_navigator.activate() # Activate companion
            # Update current navigator if in static mode
            if self._mode == "static":
                self._navigator = self._static_navigator
        elif self._role == "scout":
            self._static_navigator.deactivate() # Deactivate current static navigator
            self._static_navigator.reset() # Reset old static navigator state
            self._static_navigator = self._scout_navigator # Switch to scout
            self._static_navigator.activate() # ...
            # Update current navigator if in static mode
            if self._mode == "static":
                self._navigator = self._static_navigator
        else:
            raise ValueError(f"Unknown AUV role: {self._role}")
    
    # -----------------------------
    # GETTERS
    # -----------------------------
    def get_collected_boxes(self):
        return self._collected_boxes
        


    