import argparse

import os
import time

def main():
    from modules.auv.auv import AUV
    from modules.state.atomic_state import AtomicState
    from modules.state.buffered_observer import ManualObserver
    parser = argparse.ArgumentParser(description="ONR Project Main")
    parser.add_argument(
        "--role",
        choices=["companion", "scout"],
        required=True,
        help="Specify the role: companion or scout"
    )
    parser.add_argument(
        "--pid",
        type=int,
        required=True,
        help="Participant ID number"
    )
    
    args = parser.parse_args()
    
    print(f"Starting with role: {args.role}")
    print(f"Participant ID: {args.pid}")
    
    print("[System] Initializing shared atomic state...")
    state = AtomicState()
    print("[System] Initializing file observer...")
    filepath = f"ONR_Scuba_Pilot/OutputData/ParticipantData_PID_{args.pid}.json"
    observer = ManualObserver(filepath=filepath, shared_state=state)
    print(f"[System] Waiting for file to be created: {filepath}")
    
    while not os.path.exists(filepath):
        time.sleep(0.5)  # Check every 500ms
    
    print(f"[System] File found! Starting observer...")
    observer.start()

    print("[System] Initializing AUV...")
    auv = AUV(
        name="AUV",
        state=state,
        role=args.role,
        monitor_index=2,
        model_path="models/yolov8s-world.pt",
        activate_after=5,
        deactivate_after=20,
        conf_threshold=0.1,
        interaction_threshold=10.0,
        follow_distance=5.0,
    )

    print("[System] Entering main loop. Press Ctrl+C to exit.")
    try:
        auv.start()
        while True:
            time.sleep(1)
            end = state.snapshot().get("curState") == "endProgram"
            print("[System] Main loop heartbeat... current state:", state.snapshot().get("curState"))
            if end:
                print("\n\nEnd program state detected. Shutting down gracefully...")
                break
    except KeyboardInterrupt:
        print("\n\nKeyboard interrupt received. Shutting down gracefully...")
    finally:
        auv.stop()
        observer.stop()
        print("[System] AUV and observer stopped.")
        print("[System] Final collected boxes:", auv.get_collected_boxes())
        print("[System] Shutdown complete.")
        exit(0)

   
if __name__ == "__main__":
    role_parser = argparse.ArgumentParser(add_help=False)
    role_parser.add_argument("--role")
    role_parser.add_argument("--grid-search-expert", action="store_true")
    selected, _ = role_parser.parse_known_args()
    if selected.role == "scout-expert" or selected.grid_search_expert:
        from expert_scout.runtime import main as expert_main
        expert_main()
    else:
        main()
