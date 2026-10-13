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
