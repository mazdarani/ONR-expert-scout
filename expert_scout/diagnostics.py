"""Explain why AUV movement is waiting."""


def telemetry_wait_message(record, snapshot, telemetry):
    state = telemetry["status"]
    path = telemetry.get("path")
    if state == "missing_directory":
        return (f"Telemetry folder does not exist: {telemetry['directory']}. "
                "Start ONR Scuba first, or set --sim-dir to its executable folder.")
    if state == "missing_file":
        return (f"No {telemetry['pattern']} in {telemetry['directory']}. "
                "Check the simulator participant ID and start the experiment.")
    if state in ("invalid_json", "read_error"):
        return f"Cannot read complete telemetry from {path}: {telemetry.get('error')}."
    reason = record.get("wait_reason")
    if reason == "stale_telemetry":
        return f"Telemetry has stopped updating: {path}. Check that this simulator session is running."
    if reason == "missing_auv_pose":
        return f"Telemetry has no complete AUV position/rotation: {path}."
    if reason == "missing_game_state":
        return f"Telemetry has no game state: {path}."
    return f"Simulator state is {snapshot.get('curState')!r}; movement starts in searching."
