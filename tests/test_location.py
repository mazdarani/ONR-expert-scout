from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json
import subprocess
import sys

import pytest
from expert_scout.location import simulator_folder, running_simulator_folders
from expert_scout.io import TelemetryReader
from expert_scout.diagnostics import telemetry_wait_message
from expert_scout.config import Config
from expert_scout.controller import ExpertController
from expert_scout.action import Action
from expert_scout.maps import load_search_areas


def test_running_build_is_used_when_it_is_outside_the_repo(tmp_path):
    running=tmp_path/'Downloads'/'ONRScubaCFF'
    configured=tmp_path/'repo'/'ONRScubaCFF'
    with patch('expert_scout.location.running_simulator_folders',return_value=[running]):
        assert simulator_folder(configured)==(running,'running simulator')


def test_explicit_simulator_folder_takes_priority(tmp_path):
    selected=tmp_path/'my build'
    with patch('expert_scout.location.running_simulator_folders') as probe:
        assert simulator_folder(tmp_path/'default',str(selected))==(selected,'--sim-dir')
        probe.assert_not_called()


def test_explicit_telemetry_file_does_not_probe_other_simulators(tmp_path):
    with patch('expert_scout.location.running_simulator_folders') as probe:
        assert simulator_folder(tmp_path,state_file='data.json')[1]=='--state-file'
        probe.assert_not_called()


def test_no_running_simulator_uses_configured_folder(tmp_path):
    with patch('expert_scout.location.running_simulator_folders',return_value=[]):
        assert simulator_folder(tmp_path)==(tmp_path,'config')


def test_multiple_running_folders_require_an_unambiguous_selection(tmp_path):
    folders=[tmp_path/'first',tmp_path/'second']
    with patch('expert_scout.location.running_simulator_folders',return_value=folders):
        assert simulator_folder(folders[0])[0]==folders[0]
        with pytest.raises(ValueError,match='--sim-dir'):
            simulator_folder(tmp_path/'other')


def test_windows_probe_deduplicates_paths_and_does_not_open_a_terminal(tmp_path):
    exe=tmp_path/'ONR Scuba.exe'
    result=SimpleNamespace(stdout=f'{exe}\n{exe}\n',returncode=0)
    with patch('expert_scout.location.sys.platform','win32'), patch('expert_scout.location.subprocess.run',return_value=result) as run:
        assert running_simulator_folders()==[tmp_path]
    args,kwargs=run.call_args
    assert args[0][0]=='powershell.exe'
    assert '-NoProfile' in args[0]
    assert kwargs['creationflags']==0x08000000
    assert kwargs['timeout']==5


@pytest.mark.parametrize('error',[OSError('unavailable'),subprocess.TimeoutExpired('powershell',5)])
def test_failed_process_lookup_keeps_manual_folder_available(tmp_path,error):
    with patch('expert_scout.location.sys.platform','win32'), patch('expert_scout.location.subprocess.run',side_effect=error):
        assert simulator_folder(tmp_path)==(tmp_path,'config')


@pytest.mark.skipif(sys.platform!='win32',reason='Native Windows process lookup')
def test_native_windows_probe_runs_without_a_simulator_installed():
    assert isinstance(running_simulator_folders(),list)


def test_external_simulator_telemetry_allows_grid_motion(tmp_path):
    running=tmp_path/'separate build'
    output=running/'OutputData';output.mkdir(parents=True)
    value={'curState':'searching','mapType':1,'totalTime':10,'boxesFound':0,'boxTimeList':[],
           'latestPositions':{'auvPosition':{'x':0,'y':-23,'z':0},'auvRotation':{'y':0}}}
    (output/'ParticipantData_PID_0.json').write_text(json.dumps(value))
    with patch('expert_scout.location.running_simulator_folders',return_value=[running]):
        directory,_=simulator_folder(tmp_path/'repo'/'ONRScubaCFF')
    reader=TelemetryReader(directory/'OutputData',0)
    snapshot=reader.read()
    grid=SimpleNamespace(action=lambda:Action(forward=True,source='grid'),set_search_area=lambda area:None,
                         mark_opened_area=lambda position:None)
    approach=SimpleNamespace(clear_target_box=lambda:None,_clear_motion_keys=lambda:None)
    areas=load_search_areas(Path(__file__).resolve().parents[1]/'configs/maps.json')
    controller=ExpertController(Config(),grid,approach,[],areas)
    record=controller.step(snapshot,None)
    assert record['action'].forward
    assert reader.diagnostics()['path']==str(output/'ParticipantData_PID_0.json')


def test_missing_folder_is_reported_with_the_path(tmp_path):
    missing=tmp_path/'missing'/'OutputData'
    reader=TelemetryReader(missing,0)
    assert reader.read()=={}
    info=reader.diagnostics()
    assert info['status']=='missing_directory'
    message=telemetry_wait_message({}, {}, info)
    assert str(missing) in message
    assert '--sim-dir' in message


def test_existing_folder_without_matching_participant_reports_id(tmp_path):
    (tmp_path/'ParticipantData_PID_10.json').write_text('{}')
    reader=TelemetryReader(tmp_path,0)
    reader.read()
    assert reader.diagnostics()['status']=='missing_file'
    message=telemetry_wait_message({}, {}, reader.diagnostics())
    assert 'PID_0' in message
    assert 'participant ID' in message


def test_incomplete_json_preserves_previous_timestamp_and_explains_error(tmp_path):
    path=tmp_path/'ParticipantData_PID_0.json'
    path.write_text(json.dumps({'curState':'searching','totalTime':10}))
    reader=TelemetryReader(tmp_path,0)
    stamp=reader.read()['_sourceMtime']
    path.write_text('{')
    assert reader.read()['_sourceMtime']==stamp
    assert reader.diagnostics()['status']=='invalid_json'
    assert str(path) in telemetry_wait_message({}, {}, reader.diagnostics())


def test_stale_telemetry_and_menu_state_have_distinct_messages():
    info={'status':'ready','path':'participant.json'}
    stale=telemetry_wait_message({'wait_reason':'stale_telemetry'},{'curState':'searching'},info)
    menu=telemetry_wait_message({'wait_reason':'game_not_searching'},{'curState':'titleScreen'},info)
    assert 'stopped updating' in stale
    assert 'titleScreen' in menu


def test_missing_pose_is_distinct_from_missing_file():
    message=telemetry_wait_message({'wait_reason':'missing_auv_pose'},{'curState':'searching'},
                                   {'status':'ready','path':'participant.json'})
    assert 'position/rotation' in message
