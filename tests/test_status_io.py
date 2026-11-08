import ctypes
import errno
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from expert_scout.io import atomic_json, StatusWriter


def locked_error():
    error = PermissionError('Access is denied')
    error.winerror = 5
    return error


def test_atomic_replace_retries_a_temporary_access_lock(tmp_path):
    path = tmp_path / 'status.json'
    path.write_text('{"version": 1}')
    original = os.replace
    attempts = []
    def replace_file(source, destination):
        attempts.append(source)
        if len(attempts) < 3:
            raise locked_error()
        original(source, destination)
    with patch('expert_scout.io.os.replace', side_effect=replace_file), patch('expert_scout.io.time.sleep'):
        atomic_json(path, {'version': 2})
    assert json.loads(path.read_text()) == {'version': 2}
    assert len(attempts) == 3
    assert list(tmp_path.iterdir()) == [path]


def test_persistent_status_lock_keeps_last_file_and_recovers_without_warning_spam(tmp_path, capsys):
    path = tmp_path / 'status.json'
    path.write_text('{"version": 1}')
    writer = StatusWriter(path)
    with patch('expert_scout.io.os.replace', side_effect=locked_error()) as rename, patch('expert_scout.io.time.sleep'):
        with patch('expert_scout.io.time.monotonic', return_value=100):
            assert not writer.write({'version': 2})
        assert rename.call_count == 4
        with patch('expert_scout.io.time.monotonic', return_value=100.5):
            assert not writer.write({'version': 3})
        assert rename.call_count == 4
        with patch('expert_scout.io.time.monotonic', return_value=102):
            assert not writer.write({'version': 4})
    assert json.loads(path.read_text()) == {'version': 1}
    assert list(tmp_path.iterdir()) == [path]
    assert capsys.readouterr().out.count('Status file could not be updated') == 1
    with patch('expert_scout.io.time.monotonic', return_value=104):
        assert writer.write({'version': 5})
    assert json.loads(path.read_text()) == {'version': 5}
    assert writer.error is None
    assert 'updates resumed' in capsys.readouterr().out


def test_non_lock_errors_are_not_retried_and_bad_payloads_are_not_silenced(tmp_path):
    with patch('expert_scout.io.os.replace', side_effect=OSError(errno.ENOSPC, 'Disk full')) as rename, patch('expert_scout.io.time.sleep') as sleep:
        with pytest.raises(OSError):
            atomic_json(tmp_path/'config.json', {'value': 1})
    assert rename.call_count == 1
    sleep.assert_not_called()
    with pytest.raises(ValueError):
        StatusWriter(tmp_path/'status.json').write({'value': float('nan')})


@pytest.mark.skipif(sys.platform != 'win32', reason='Native Windows sharing lock')
def test_windows_reader_without_delete_sharing_does_not_crash_status_updates(tmp_path):
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    path = tmp_path/'status.json'
    path.write_text('{"version": 1}')
    handle = kernel.CreateFileW(str(path), 0x80000000, 3, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    writer = StatusWriter(path)
    try:
        with patch('expert_scout.io.time.monotonic', return_value=100):
            assert not writer.write({'version': 2})
        assert json.loads(path.read_text()) == {'version': 1}
    finally:
        kernel.CloseHandle(handle)
    with patch('expert_scout.io.time.monotonic', return_value=102):
        assert writer.write({'version': 3})
    assert json.loads(path.read_text()) == {'version': 3}


@pytest.mark.parametrize('action_log_failed', [False, True])
def test_runtime_continues_with_locked_status_but_stops_if_action_logging_fails(tmp_path, monkeypatch, action_log_failed):
    from expert_scout import runtime
    from expert_scout.config import Config
    from expert_scout.io import RunLog
    class Reader:
        def __init__(self, *args):
            self.count = 0
        def read(self):
            self.count += 1
            if self.count > 2:
                raise KeyboardInterrupt
            return {'curState':'searching','mapType':1,'totalTime':10,'boxesFound':0,
                    '_sourceMtime':runtime.time.time(),
                    'latestPositions':{'auvPosition':{'x':0,'y':-23,'z':0},'auvRotation':{'y':0},
                                       'diverPosition':{'x':0,'y':-23,'z':0}},
                    'boxTimeList':[{'boxID':0,'boxPosition':{'x':0,'y':-23,'z':10}}]}
        def diagnostics(self):
            return {'path':'state.json','status':'ready','game_state':'searching'}
    class Detector:
        error = None
        def __init__(self, *args): pass
        def start(self): pass
        def snapshot(self): return None
        def close(self): pass
    motions = []
    closed = []
    actuator = SimpleNamespace(apply=lambda action: motions.append(action) or {'actuator':'test'},
                               close=lambda:closed.append(True))
    monkeypatch.setattr(sys, 'argv', ['main.py','--pid','0'])
    monkeypatch.setattr(runtime, 'load_config', lambda path: replace(Config(), output_directory=str(tmp_path/'logs')))
    monkeypatch.setattr(runtime, 'simulator_folder', lambda *args:(tmp_path/'simulator','test'))
    monkeypatch.setattr(runtime, 'TelemetryReader', Reader)
    monkeypatch.setattr('expert_scout.vision.Detector', Detector)
    monkeypatch.setattr('expert_scout.actuator.KeyboardActuator', lambda:actuator)
    monkeypatch.setattr('expert_scout.interaction.DiverInteractions.start', lambda self:None)
    original = os.replace
    def replace_file(source, destination):
        if Path(destination).name == 'status.json':
            raise locked_error()
        original(source, destination)
    monkeypatch.setattr('expert_scout.io.os.replace', replace_file)
    if action_log_failed:
        def failed_write(self, value):
            raise OSError('Action log unavailable')
        monkeypatch.setattr(RunLog, 'write', failed_write)
        with pytest.raises(OSError, match='Action log unavailable'):
            runtime.main()
    else:
        runtime.main()
        assert len(motions) == 2 and all(action.forward for action in motions)
        log, = (tmp_path/'logs').rglob('actions.jsonl')
        records = [json.loads(line) for line in log.read_text().splitlines()]
        assert len(records) == 2 and all(record['selected_action']['forward'] for record in records)
    assert closed == [True]
