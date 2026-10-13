"""Run the grid expert scout with a human-controlled diver."""
import argparse
from dataclasses import asdict
import math
import secrets
import time
import uuid
from .config import ROOT, load_config
from .io import RunLog, TelemetryReader, atomic_json
from .maps import load_search_areas
from .location import simulator_folder
from .diagnostics import telemetry_wait_message


def duration(value):
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("Duration must be a finite nonnegative number")
    return value


def build_parser():
    parser = argparse.ArgumentParser(description="ONR grid expert scout")
    parser.add_argument("--role", choices=["scout-expert"], default="scout-expert")
    parser.add_argument("--grid-search-expert", action="store_true", help="Select the grid expert scout")
    parser.add_argument("--pid", required=True, type=int)
    parser.add_argument("--config", default=str(ROOT / "configs/expert.json"))
    parser.add_argument("--map", choices=["auto", "training", "map1", "map2"], default="auto",
                        help="Select grid bounds; auto reads the current simulator map")
    parser.add_argument("--sim-dir", help="Folder containing ONR Scuba.exe and OutputData")
    parser.add_argument("--state-file", help="Select a participant telemetry file")
    parser.add_argument("--monitor-index", type=int, help="Override the AUV capture monitor")
    parser.add_argument("--seed", type=int, help="Repeat a randomized grid route")
    parser.add_argument("--duration-sec", type=duration, default=0, help="Optional time limit; default is unlimited")
    parser.add_argument("--dry-run", action="store_true", help="Record actions without pressing keys")
    return parser


def main():
    from dataclasses import replace
    parser = build_parser()
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        search_areas = load_search_areas(config.path("map_profiles_path"))
        sim_dir, location_source = simulator_folder(config.path("simulator_directory"), args.sim_dir, args.state_file)
        if args.monitor_index is not None:
            config = replace(config, monitor_index=args.monitor_index).validate()
        if not config.path("detector_path").is_file():
            raise ValueError(f"YOLO checkpoint is missing: {config.path('detector_path')}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.error(str(error))
    from .actuator import KeyboardActuator, DryRunActuator
    from .approach import OracleBoxNavigator
    from .controller import ExpertController
    from .confidence import ConfidenceSender
    from .grid import GridSearchNavigator
    from .state import AtomicState
    from .vision import Detector
    state, collected = AtomicState(), []
    seed = args.seed if args.seed is not None else secrets.randbits(32)
    grid = GridSearchNavigator(state, "scout", collected, lambda role: None,
                               collision_threshold=1.5, yaw_threshold=0.3, randomize_route=True,
                               waypoint_jitter=config.waypoint_jitter, depth_jitter=config.depth_jitter, seed=seed)
    approach = OracleBoxNavigator(state, "scout", collected, lambda role: None, lambda box_id: None,
                                   collision_threshold=1.5, yaw_threshold=0.3,
                                   collection_distance=config.collection_distance)
    controller = ExpertController(config, grid, approach, collected, search_areas, args.map)
    reader = TelemetryReader(sim_dir / "OutputData", args.pid, args.state_file)
    detector = Detector(config.path("detector_path"), config.monitor_index, config.detector_confidence)
    actuator = DryRunActuator() if args.dry_run else KeyboardActuator()
    confidence_sender = ConfidenceSender(config, actuator)
    episode = uuid.uuid4().hex
    run_dir = config.path("output_directory") / f"pid_{args.pid}" / episode
    run_dir.mkdir(parents=True)
    atomic_json(run_dir / "config.json", dict(asdict(config), seed=seed, duration_sec=args.duration_sec, simulator_path=str(sim_dir), map_selection=args.map, simulator_location_source=location_source))
    log = RunLog(run_dir / "actions.jsonl")
    print(f"Grid expert scout: participant {args.pid}, seed {seed}")
    print(f"Run outputs: {run_dir}")
    print(f"Simulator telemetry: {args.state_file or sim_dir / 'OutputData'} ({location_source})")
    print("Confidence keys (top row): 1=low, Shift+1=medium, Ctrl+1=high. Unity receiver required; this build has none.")
    previous = None
    previous_wait = None
    try:
        detector.start()
        started = time.time()
        while not args.duration_sec or time.time() - started < args.duration_sec:
            if detector.error is not None:
                raise RuntimeError(f"AUV capture failed: {detector.error}")
            snapshot = reader.read()
            telemetry = reader.diagnostics()
            if snapshot.get("curState") == "endProgram":
                break
            state.update(snapshot)
            record = controller.step(snapshot, detector.snapshot())
            action = record.pop("action")
            record.update(episode_id=episode, pid=args.pid, published_at=time.time(),
                          selected_action=action.to_dict(), actuation=actuator.apply(action), telemetry=telemetry)
            record["confidence_feedback"] = confidence_sender.update(record, snapshot, time.time())
            log.write(record)
            status = {k: record[k] for k in
                      ("episode_id", "pid", "published_at", "phase", "event", "map_name", "map_epoch", "search_bounds",
                       "target_box_id", "target_detection", "confidence_feedback", "telemetry")}
            status["wait_reason"] = record.get("wait_reason")
            atomic_json(run_dir / "status.json", status)
            if action.source == "telemetry_wait":
                message = telemetry_wait_message(record, snapshot, telemetry)
                if message != previous_wait:
                    print(message, flush=True)
                    previous_wait = message
            else:
                if previous_wait is not None:
                    print(f"Telemetry ready: {telemetry.get('path')}", flush=True)
                previous_wait = None
            mode = (record["phase"], action.source)
            if mode != previous or record["event"]:
                print(f"Expert: {record['phase']}, box={record['target_box_id']}, controller={action.source}")
                previous = mode
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("Expert scout stopped.")
    finally:
        actuator.close()
        detector.close()
        log.close()
