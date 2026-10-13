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

## Confidence keys

Python taps a key when the AUV has reached its target and a fresh YOLO score is
available. It sends another only if that box's category changes, with at least
0.75 seconds between taps. Matching uses the target box, rather than the highest
score elsewhere in the image. Keys are not sent during grid search, approach,
SAGAT, collection dwell or stale camera/telemetry updates. `--dry-run` reports
which key would be sent. No keyboard listener or pause/stop hotkeys are added.

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

**The inspected build does not receive these confidence-category keys yet.**
The Unity team must bind each combination to update
the nearest AUV box's feedback label to Low, Medium or High and show its panel
or circle. `0` currently opens the panel using a stored Unity score; pressing it
does not transfer YOLO confidence. Python sends the category key only; three
combinations cannot carry the exact numeric score. The numeric score is saved in logs.

The build also contains a legacy input map that assigns plain `1` to a camera
change. Check whether that map is active when wiring the confidence receiver;
the combinations must select their own categories, so Shift/Ctrl+1 must not also
trigger the plain-1 handler.

The sender checks that the target is within collection distance and is the
nearest box to the AUV, matching the current panel's target selection. It logs
`confidence_feedback` in `actions.jsonl` and `status.json`: score, category, key,
sent status and any skip reason. A successful key press confirms transmission,
not that Unity received or displayed it. Diver collection hides the panel and
confirmed opened IDs prevent further approach or confidence signals.

## Maps

The build has `training` (two boxes), `map1` (five) and `map2` (five), with different
box locations. The expert reads target positions from the current `boxTimeList`;
no old target coordinates are used. X/Z are world coordinates, Y is vertical,
and yaw is measured in degrees.

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
