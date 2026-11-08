"""Participant prompts and automatic per-mission data recording."""
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime
import json
from pathlib import Path
import re
import sys
import threading
import time
import uuid

from .config import ROOT, load_config
from .io import TelemetryReader, atomic_json
from .maps import map_name

PHASES = {'1': 'Training', '2': 'Control', '3': 'CFF',
          'training': 'Training', 'control': 'Control', 'cff': 'CFF'}


def settings(snapshot):
    cff = snapshot.get('cffType')
    if type(cff) is not int or cff not in (0, 1):
        cff = {'off': 0, 'on': 1}.get(str(snapshot.get('cffString', '')).lower())
    exp = snapshot.get('expType')
    if type(exp) is not int or exp not in (0, 1):
        exp = {'screenspace': 0, 'worldspace': 1}.get(str(snapshot.get('expString', '')).lower())
    return {'map': map_name(snapshot), 'cff': cff,
            'explainability': {0: 'General', 1: 'Local'}.get(exp)}


def prompt_session(input_fn=input):
    while True:
        value = input_fn('Participant ID: ').strip()
        if value.isascii() and value.isdecimal():
            pid = int(value)
            break
        print('Enter a numeric participant ID, for example 123.')
    while True:
        value = input_fn('Condition: 1=Training, 2=Control, 3=CFF: ').strip().lower()
        if value in PHASES:
            return pid, PHASES[value]
        print('Enter Training, Control or CFF (or 1, 2, 3).')


def wait_for_mission(reader, phase):
    expected = 1 if phase == 'CFF' else 0
    previous = None
    while True:
        snapshot = reader.read()
        current = settings(snapshot)
        fresh = 0 <= time.time() - snapshot.get('_sourceMtime', 0) <= 1
        if fresh and snapshot.get('curState') == 'searching':
            correct_map = current['map'] == 'training' if phase == 'Training' else current['map'] in ('map1', 'map2')
            if current['cff'] == expected and current['explainability'] and correct_map:
                return snapshot, Path(reader.selected_path), current
        message = (f'Waiting for participant {reader.pid}, {phase}. Start the assigned scenario in Unity. '
                   f'CFF Condition must be {"B (on)" if expected else "A (off)"}; '
                   f'map must be {"Training" if phase == "Training" else "Map 1 or Map 2"}.')
        if message != previous:
            print(message, flush=True)
            previous = message
        time.sleep(.25)


class Tee:
    def __init__(self, console, log):
        self.console, self.log = console, log
        self.lock = threading.RLock()

    def write(self, text):
        with self.lock:
            self.console.write(text)
            self.log.write(text)
            self.log.flush()
        return len(text)

    def flush(self):
        with self.lock:
            self.console.flush()
            self.log.flush()

    def __getattr__(self, name):
        return getattr(self.console, name)


class SessionRecorder:
    def __init__(self, source, run_dir, pid, expected, positions_before, initial=None):
        self.source, self.run_dir = Path(source), Path(run_dir)
        self.pid, self.expected = pid, expected
        self.data_dir = self.run_dir / 'simulator'
        self.data_dir.mkdir()
        if initial is not None:
            initial = {key: value for key, value in initial.items() if not key.startswith('_')}
            atomic_json(self.data_dir / 'initial_state.json', initial)
            atomic_json(self.data_dir / 'last_searching.json', initial)
        self.positions_before = positions_before
        self.saved = {}
        self.positions_saved = set()
        self.finished = threading.Event()
        self.stop = threading.Event()
        self.error = None
        self.warning = None
        self.thread = threading.Thread(target=self._loop, name='session-recorder', daemon=True)

    def validate(self, snapshot):
        if snapshot.get('curState') == 'searching' and settings(snapshot) != self.expected:
            raise RuntimeError('Unity map or condition changed. Close Unity and start a new session with 02-cmd.')
        if snapshot.get('curState') == 'endProgram':
            self.finished.set()
        if self.error is not None:
            raise RuntimeError(f'Simulator recording failed: {self.error}. Original files remain in simulator/OutputData.')

    def _save(self, source):
        stat = source.stat()
        signature = (stat.st_mtime_ns, stat.st_size)
        if self.saved.get(source) == signature:
            return None
        value = json.loads(source.read_bytes())
        if source == self.source and settings(value) != self.expected:
            raise RuntimeError('Simulator settings changed while recording this session.')
        if source == self.source and value.get('curState') == 'endProgram':
            self.finished.set()
        atomic_json(self.data_dir / source.name, value)
        if source == self.source:
            if not (self.data_dir / 'initial_state.json').exists():
                atomic_json(self.data_dir / 'initial_state.json', value)
            if value.get('curState') == 'searching':
                atomic_json(self.data_dir / 'last_searching.json', value)
            if value.get('curState') == 'endProgram':
                self.finished.set()
        else:
            self.positions_saved.add(source.name)
        self.saved[source] = signature
        return value

    def poll(self):
        self._save(self.source)
        for source in positions_files(self.source.parent, self.pid):
            stat = source.stat()
            if self.positions_before.get(source) != (stat.st_mtime_ns, stat.st_size):
                self._save(source)

    def _loop(self):
        try:
            while not self.stop.is_set():
                try:
                    self.poll()
                    self.warning = None
                except (OSError, ValueError) as error:
                    # Copy locks and partial Unity writes do not interrupt the controller.
                    if self.warning is None:
                        print(f'Simulator backup will be retried: {error}. Original files remain in OutputData.', flush=True)
                    self.warning = str(error)
                self.stop.wait(.5)
        except Exception as error:
            self.error = str(error)
            self.finished.set()

    def start(self):
        self.thread.start()

    def close(self):
        self.stop.set()
        self.thread.join()
        # Unity saves AllPositions after writing endProgram. Allow that final write to finish.
        for _ in range(10):
            try:
                self.poll()
                if self.finished.is_set() and self.positions_saved and self.error is None:
                    return True
            except (OSError, ValueError, RuntimeError) as error:
                self.warning = str(error)
            time.sleep(.5)
        return False


def positions_files(directory, pid):
    pattern = re.compile(rf'AllPositions_PID_{pid}(?:_COPY_\d+)?\.json$')
    return [p for p in Path(directory).glob(f'AllPositions_PID_{pid}*.json') if pattern.fullmatch(p.name)]


def position_baseline(directory, pid):
    return {p: (p.stat().st_mtime_ns, p.stat().st_size) for p in positions_files(directory, pid)}


def run_session(root=ROOT, input_fn=input):
    root = Path(root)
    pid, phase = prompt_session(input_fn)
    config = load_config(root / 'configs/expert.json')
    simulator = Path(config.simulator_directory)
    if not simulator.is_absolute():
        simulator = root / simulator
    output = simulator / 'OutputData'
    reader = TelemetryReader(output, pid)
    snapshot, source, selected = wait_for_mission(reader, phase)
    before = position_baseline(output, pid)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
    folder = root / 'participant_data' / f'PID{pid}' / phase / stamp
    folder.mkdir(parents=True)
    metadata = {'pid': pid, 'condition': phase, **selected, 'started_at': datetime.now().isoformat(),
                'source': str(source)}
    atomic_json(folder / 'session.json', metadata)
    recorder = SessionRecorder(source, folder, pid, selected, before, snapshot)
    completed = False
    failure = None
    with (folder / 'console.txt').open('w', encoding='utf-8') as log:
        stdout, stderr = Tee(sys.stdout, log), Tee(sys.stderr, log)
        with redirect_stdout(stdout), redirect_stderr(stderr):
            print(f'Participant {pid}: {phase}, {selected["map"]}, {selected["explainability"]}')
            print(f'Session folder: {folder}', flush=True)
            print('Close Unity at the end of the mission to finish saving. Return focus to Unity now.', flush=True)
            recorder.start()
            try:
                if phase != 'Training':
                    from .runtime import main as controller_main
                    try:
                        controller_main(['--role','scout-expert','--pid',str(pid),'--sim-dir',str(simulator),
                                         '--state-file',str(source),'--run-dir',str(folder/'controller')],
                                        session_check=recorder.validate)
                    except Exception as error:
                        import traceback
                        traceback.print_exc()
                        failure = str(error)
                        print('Controller stopped after an error. Close Unity to finish saving this session.', flush=True)
                else:
                    print('Manual training: recording only; the AUV controller is not running.', flush=True)
                if not recorder.finished.is_set():
                    print('Waiting for Unity to close; simulator data recording continues.', flush=True)
                while not recorder.finished.wait(.25):
                    pass
                if recorder.error is not None:
                    raise RuntimeError(recorder.error)
            except KeyboardInterrupt:
                print('Session interrupted. Saving the available data; final position data may still be in Unity OutputData.')
            except Exception as error:
                import traceback
                traceback.print_exc()
                failure = str(error)
            finally:
                completed = recorder.close()
    metadata.update(finished_at=datetime.now().isoformat(), recording_complete=completed,
                    error=failure or recorder.error, archive_warning=recorder.warning if not completed else None,
                    positions_files=sorted(recorder.positions_saved))
    atomic_json(folder / 'session_result.json', metadata)
    print(f'Saved session: {folder}', flush=True)
    if not completed:
        print('Final simulator files were not all available. Keep simulator/OutputData and review session_result.json and console.txt.', flush=True)
    if failure or recorder.error:
        raise RuntimeError(failure or recorder.error)
    return folder
