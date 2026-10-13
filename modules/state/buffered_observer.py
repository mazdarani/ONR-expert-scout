import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import orjson, os, time, sys, logging

from modules.state.atomic_state import AtomicState

class AutomaticObserver(FileSystemEventHandler):
    def __init__(self, filepath, shared_state: AtomicState):
        # Normalize to an absolute, case-normalized path so comparisons
        # match what watchdog reports on Windows (and for relative paths).
        self._filepath = os.path.normcase(os.path.abspath(filepath))
        self._shared_state = shared_state
        self._last_update = 0.0

    def _handle_file_event(self, path):
        # Normalize incoming path the same way we normalized the target
        path = os.path.normcase(os.path.abspath(path))
        if path != self._filepath:
            return

        now = time.time()
        # debounce rapid successive events
        if now - self._last_update < 0.05:
            return
        self._last_update = now

        try:
            # Read the file fully and parse JSON.
            with open(self._filepath, "rb") as f:
                data = f.read()
            new_state = orjson.loads(data)

            # Ensure we only pass dicts into AtomicState.update
            if isinstance(new_state, dict):
                self._shared_state.update(new_state)
        except Exception as e:
            # Partial writes, transient IO or decode errors are common; log for debug.
            pass

    def on_modified(self, event):
        # Ignore directory events
        if getattr(event, "is_directory", False):
            return
        self._handle_file_event(event.src_path)

    def on_created(self, event):
        # Handle file create (useful if file is created after watcher started)
        if getattr(event, "is_directory", False):
            return
        self._handle_file_event(event.src_path)

    def on_moved(self, event):
        # Handle atomic replace patterns where a temp file is moved/renamed into place
        if getattr(event, "is_directory", False):
            return
        # watchdog uses dest_path for moved events
        dest = getattr(event, "dest_path", None)
        if dest:
            self._handle_file_event(dest)

def start_file_watcher(filepath, shared_state):
    """
    Start a watchdog Observer that watches the parent directory of `filepath`.

    Behavior: watchdog can only watch directories, so we schedule the observer
    on the file's parent directory and the handler filters events to the
    single target file. The `filepath` may be relative or absolute.

    Raises FileNotFoundError if the parent directory doesn't exist.
    """
    observer = Observer()
    handler = AutomaticObserver(filepath, shared_state)

    abs_filepath = os.path.normcase(os.path.abspath(filepath))
    watch_dir = os.path.dirname(abs_filepath) or os.getcwd()

    if not os.path.isdir(watch_dir):
        raise FileNotFoundError(f"Watch directory does not exist: {watch_dir}")

    observer.schedule(handler, watch_dir, recursive=False)
    observer.start()
    return observer

class ManualObserver:
    def __init__(self, filepath, shared_state: AtomicState):
        # Normalize to an absolute, case-normalized path so comparisons
        # match what watchdog reports on Windows (and for relative paths).
        self._filepath = os.path.normcase(os.path.abspath(filepath))
        self._shared_state = shared_state
        
        self._last_update = 0.0
        self._running = False

        self._observer_thread = threading.Thread(target=self._manual_loop, daemon=True)

    def start(self):
        self._running = True
        self._observer_thread.start()

    def stop(self):
        self._running = False
        self._observer_thread.join()

    def _manual_loop(self):
        while self._running:
            self.check_for_update()
            time.sleep(0.05)  # Check every 50ms

    def check_for_update(self):
        now = time.time()
        # debounce rapid successive events
        if now - self._last_update < 0.05:
            return
        self._last_update = now

        try:
            # Read the file fully and parse JSON.
            with open(self._filepath, "rb") as f:
                data = f.read()
            new_state = orjson.loads(data)

            # Ensure we only pass dicts into AtomicState.update
            if isinstance(new_state, dict):
                self._shared_state.update(new_state)
        except Exception as e:
            # Partial writes, transient IO or decode errors are common; log for debug.
            pass

