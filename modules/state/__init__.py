"""
State module for ONR project.
"""

from .atomic_state import AtomicState
from .buffered_observer import AutomaticObserver, start_file_watcher, ManualObserver

__version__ = "1.0.0"
__all__ = ["AtomicState", "AutomaticObserver", "start_file_watcher", "ManualObserver"]