# ONR grid expert scout

The AUV follows a randomized grid route until YOLO detects a box. The expert
matches that detection to a simulator box and approaches using its coordinates.
At 1.5 m it stops for the human-controlled diver to collect the box. After
confirmed collection and a ten-second dwell, it resumes the same grid route.

```bat
python main.py --role scout-expert --pid 0
```

Use Windows and Python 3.11. Create and activate a virtual environment, then
install `requirements-expert.txt`. The trained YOLO checkpoint is included.
Keep the AUV view on monitor 2 and the simulator focused while running.
The diver view belongs on the other monitor. Only AUV keys are generated.

Extract `ONRScubaCFF.zip` into this repository so the executable is at
`ONRScubaCFF/ONR Scuba.exe`, or pass `--sim-dir "C:\path\to\ONRScubaCFF"`.
Use the same participant ID in the simulator and Python. Telemetry is read from
`OutputData/ParticipantData_PID_<id>*.json` beside the executable; the newest
copy is selected and partial writes preserve the last complete snapshot.

Settings are in `configs/expert.json`. Grid movement pauses when the diver is
more than 5 m away and resumes within 3 m. The route uses the earlier expert
randomization: 2.5 m waypoint jitter and 1.5 m depth jitter. Use `--seed 1234`
to repeat a route. Use `--state-file <path>` for participant telemetry and
`--monitor-index <n>` to select the AUV capture monitor.

The run has no default time limit. `--duration-sec 600` sets ten minutes;
`--dry-run` logs requested actions without pressing keys. Stop with Ctrl+C.
Runs write `config.json`, `actions.jsonl` and `status.json` under
`logs/expert/pid_<id>/<episode>/`. Target detection confidence is the YOLO score.
Expert movement uses simulator coordinates and does not load OpenVLA.

The first commit contains the original ONR controller at
`397c50b1dbf99a28ef55891e4c586ad91e07cebd`. The inherited `modules/` and
`requirements.txt` are unchanged. `expert_scout/` contains the added mode;
`main.py` dispatches it and keeps the original `scout` and `companion` roles.

```bat
python -m pip install pytest
python -m pytest -q
```

## Simulator compatibility

The inspected build keeps the AUV movement keys `i/k`, `j/l`, `u/o`, `n/m` and
light flash `p`. Diver movement and `f` collection remain under participant
control. Searching enables AUV movement; SAGAT, menus and stale telemetry stop it.

This build reports `boxesFound` and `boxTimeList`, but no collected ID list.
Each box's `findTime` advances until it opens. Python identifies collection
only after that timer stays fixed for 0.5 seconds across advancing searching
snapshots and `boxesFound` confirms the count. Pauses and repeated snapshots do
not count. Ambiguous or missing evidence keeps the AUV waiting. If a later build
supplies `collectedBoxIds`, those IDs are accepted directly. Opened IDs remain
excluded for the rest of the run; a scout approach does not mark a box opened.

The build has a box communication panel: `0` opens it, `9` closes it, and diver
collection hides it. Its confidence is currently stored in the Unity cargo asset.
It has no keyboard receiver for externally supplied confidence categories.
