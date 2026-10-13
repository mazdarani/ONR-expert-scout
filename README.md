# ONR grid expert scout

This project runs a YOLO-assisted AUV scout alongside the ONR Unity simulator.
It captures the AUV camera, detects boxes, sends confidence hotkeys, and uses
the simulator telemetry to drive the AUV grid search and box approach. The
human-controlled diver still performs collection with `F`.

## What you need

- Windows 10 or 11 with Python 3.11.
- An AUV-view display. By default Python captures monitor `2`; use
  `--monitor-index` if your AUV view is elsewhere.
- The Unity simulator build, extracted locally as described below. It is
  intentionally ignored by Git because it is a large binary build.
- The included YOLO checkpoint:
  `checkpoints/yolo_box_detector_cvat_yolov8n_e20_best.pt`.

`requirements-expert.txt` installs the CUDA 12.1 PyTorch build. Use a
CUDA-capable NVIDIA system, or replace its PyTorch lines with an appropriate
CPU/other-CUDA build before installing.

## Repository layout

```text
ONR-expert-scout/
├── main.py                         # Command-line entry point
├── requirements-expert.txt         # Python packages for the expert scout
├── configs/
│   ├── expert.json                 # Detector, simulator, and control settings
│   └── maps.json                   # Grid-search map bounds
├── checkpoints/
│   └── yolo_box_detector_cvat_yolov8n_e20_best.pt
├── expert_scout/                   # YOLO, telemetry, controls, and navigation
├── modules/                        # Original project controller code
├── tests/                          # Automated tests
├── ONR_Scuba_Pilot/                # Local Unity build — required, Git-ignored
│   ├── ONR Scuba.exe
│   ├── ONR Scuba_Data/
│   └── OutputData/                 # Created/updated by the simulator at runtime
└── logs/                           # Generated run logs — Git-ignored
```

## Install the Unity simulator

Download or obtain the ONR Unity build and extract the entire build folder into
the repository root. Its executable must be at:

```text
ONR-expert-scout\ONR_Scuba_Pilot\ONR Scuba.exe
```

Keep every sibling file and folder that came with the executable, especially
`ONR Scuba_Data`, `UnityPlayer.dll`, and the runtime folders. Do not copy only
the `.exe`. `OutputData` must be writable because Unity writes participant
telemetry there.

If the simulator must live elsewhere, leave the repository layout unchanged and
pass its containing folder when launching Python:

```powershell
python main.py --role scout-expert --pid 0 --sim-dir "C:\path\to\ONR_Scuba_Pilot"
```

The folder passed to `--sim-dir` must directly contain both `ONR Scuba.exe` and
`OutputData`.

When Unity is already running on Windows, Python automatically finds its
`OutputData` folder beside the running `ONR Scuba.exe`, even if that build is
outside this repository. Use the same participant ID in Unity and Python.
Telemetry is read from `OutputData/ParticipantData_PID_<id>*.json`; the newest
copy is selected and partial writes preserve the last complete snapshot.

## Python setup

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-expert.txt
```

Confirm the included checkpoint is present before running:

```powershell
Test-Path .\checkpoints\yolo_box_detector_cvat_yolov8n_e20_best.pt
```

The command must return `True`.

## Run a session

1. Launch `ONR_Scuba_Pilot\ONR Scuba.exe`.
2. In Unity, select participant ID `0` (or another ID) and start a scenario.
3. Put the AUV camera on monitor `2`. Keep the diver view on the other display.
4. In the activated Python environment, use the same participant ID:

   ```powershell
   python main.py --role scout-expert --pid 0
   ```

5. Click the Unity AUV window after Python starts. The generated keyboard input
   is delivered to the foreground window, so it must be Unity—not PowerShell.

The terminal should print the telemetry location and selected map. On a YOLO
detection, it prints a line such as `YOLO: confidence=0.800, level=medium,
key=SHIFT+1, sent=True`.

Use `--monitor-index 1` to capture the first physical display, `--seed 1234`
to repeat a route, `--duration-sec 600` for a ten-minute limit, and `--dry-run`
to record requested actions without pressing keys. Stop with Ctrl+C.

The default settings are in `configs/expert.json`. The grid pauses only when the
diver is more than 100 m away. Runs are written to
`logs/expert/pid_<id>/<episode>/` as `config.json`, `actions.jsonl`, and
`status.json`.

### Session resets and oxygen

The current Unity build can end a session when the diver runs out of oxygen.
Python recognizes `outOfOxygen`, title/end screens, and `endProgram` (including
underscore or hyphenated variants). It releases all AUV movement, keeps the
Python process running, and clears the previous session's target and collected
box history when Unity returns to `searching`. Start the next Unity scenario
with the same participant ID; Python does not need to be restarted.

## Verify the installation

```powershell
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
collection hides it. The Unity receiver accepts the externally sent confidence
categories.

## Confidence keys

Python taps a key immediately whenever YOLO detects a box-like object at or above
the configured detector threshold. If more than one box is detected in a frame,
the highest-confidence detection selects the category. Sending does not wait for
target matching, AUV proximity, grid state, or fresh telemetry, and it repeats on
every detected frame. `--dry-run` reports which key would be sent. No keyboard
listener or pause/stop hotkeys are added.

| YOLO score | Category | Key |
| --- | --- | --- |
| 0.25 to below 0.72 | Low | 1 |
| 0.72 to below 0.82 | Medium | Shift+1 |
| 0.82 to 1.00 | High | Ctrl+1 |

Scores below 0.25 are ignored. The cutoffs are configurable. They are based on
5,202 distinct detection frames from six August 28 runs using the included
trained detector: the 33rd and 67th percentiles were 0.722 and 0.819. These are
relative detector-score categories, not measured probabilities of correctness.
Scores keep their original 0–1 scale. Recheck the cutoffs with this simulator's
images before the experiment; changed lighting or camera settings can shift them.

Use the top-row `1` key, not numpad 1. Python presses the modifier first and
releases it after the digit. On Windows it explicitly uses `VK_1` (0x31).

The Unity receiver binds each combination to update the confidence feedback.
Python sends the category key only; three combinations cannot carry the exact
numeric score. The numeric score is saved in logs.

The build also contains a legacy input map that assigns plain `1` to a camera
change. Check that this map does not override the confidence receiver; the
Shift/Ctrl+1 combinations must select their own categories.

The sender logs `confidence_feedback` in `actions.jsonl` and `status.json`:
score, category, key, sent status and any skip reason. A successful key press
confirms transmission, not that Unity received or displayed it.

## Maps

The build exposes `training`, `map1`, and `map2`, with different box locations.
The controller does not assume a fixed number of boxes: it reads the current
`boxTimeList`, uses the box IDs Unity provides, and tracks `boxesFound` only to
confirm collection. X/Z are world coordinates, Y is vertical, and yaw is
measured in degrees. A newly added map still needs a corresponding search-area
profile in `configs/maps.json` before the grid can move on it.

Grid bounds now come from the build's world-space constraint volumes, with 2 m
boundary clearance, rather than the earlier fixed rectangle. `training` uses
TutorialBoxConstrain; map1/map2 share MainBoxConstrain. The profiles are in
`configs/maps.json`. They contain search-area bounds, not box locations.

| Map | Search X | Search Z |
| --- | --- | --- |
| training | −13.509 to 17.471 | −17.915 to 32.255 |
| map1 / map2 | −37.319 to 58.681 | −61.030 to 84.970 |

The map is selected automatically from telemetry `mapType` or `mapString`.
Use `--map training`, `--map map1` or `--map map2` only when an explicit selection
is needed. Unknown maps hold movement until a valid map or override is available.
The selected map and bounds are printed and recorded in status/actions logs.
Map changes, returns from the title/end screens, or restarted simulator clocks
clear the previous route, target and opened-ID history, since the maps reuse
box IDs. Camera frames captured before a map switch are ignored. Grid search
continues without using live box coordinates; only a YOLO-triggered expert
approach uses them.

Checks use all twelve box positions extracted from the supplied build to test
coverage, coordinate directions and matching. Live Unity movement and detector
performance on each map still need testing on the simulator computer.

If movement reports `telemetry_wait`, read the accompanying message. It gives
the folder/file in use and distinguishes missing files, incomplete JSON, stale
updates, missing AUV pose and a game that has not entered searching. Match the
participant ID in the launch command to the simulator. Telemetry must be from
the executable you actually launched; copying the build elsewhere does not
redirect another running simulator's output. `status.json` includes the selected
telemetry path and read status.
