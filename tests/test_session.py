import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from expert_scout.io import atomic_json, TelemetryReader
from expert_scout.session import (prompt_session, settings, wait_for_mission, SessionRecorder,
                                  position_baseline, run_session)


def value(pid=12, phase='searching', cff=0, exp=1, map_type=1):
    return {'PID':str(pid),'curState':phase,'cffType':cff,'expType':exp,'mapType':map_type,
            'boxTimeList':[],'latestPositions':{}}


def test_prompts_only_pid_and_phase_with_validation():
    answers=iter(['no','-2','12','wrong','2'])
    assert prompt_session(lambda prompt:next(answers))==(12,'Control')
    assert settings(value())=={'map':'map1','cff':0,'explainability':'Local'}
    assert settings({'mapString':'Map 2','cffString':'on','expString':'screenSpace'})=={
        'map':'map2','cff':1,'explainability':'General'}


def test_wrong_condition_or_map_never_starts_controller():
    samples=iter([dict(value(cff=1),_sourceMtime=100),dict(value(map_type=0),_sourceMtime=100),
                  dict(value(),_sourceMtime=100)])
    reader=SimpleNamespace(pid=12,read=lambda:next(samples),selected_path='ParticipantData_PID_12_COPY_1.json')
    with patch('expert_scout.session.time.time',return_value=100),patch('expert_scout.session.time.sleep'):
        sample,path,selected=wait_for_mission(reader,'Control')
    assert selected['cff']==0 and selected['map']=='map1'
    assert path.name.endswith('_COPY_1.json')


def test_archive_keeps_active_file_and_only_new_position_files_for_exact_pid(tmp_path):
    output=tmp_path/'OutputData';output.mkdir()
    source=output/'ParticipantData_PID_12_COPY_1.json'
    atomic_json(source,value())
    atomic_json(output/'ParticipantData_PID_12.json',value(phase='endProgram',cff=1))
    old=output/'AllPositions_PID_12.json';atomic_json(old,{'old':True})
    baseline=position_baseline(output,12)
    folder=tmp_path/'session';folder.mkdir()
    recorder=SessionRecorder(source,folder,12,settings(value()),baseline,value())
    recorder.poll()
    atomic_json(output/'AllPositions_PID_120.json',{'other_participant':True})
    final=output/'AllPositions_PID_12_COPY_1.json';atomic_json(final,{'positions':[1,2,3]})
    atomic_json(source,value(phase='endProgram'))
    recorder.poll()
    assert recorder.finished.is_set()
    assert recorder.positions_saved=={final.name}
    saved=folder/'simulator'
    assert json.loads((saved/source.name).read_text())['curState']=='endProgram'
    assert not (saved/old.name).exists()
    assert not (saved/'ParticipantData_PID_12.json').exists()
    assert json.loads((saved/'last_searching.json').read_text())['curState']=='searching'
    assert all(p.exists() for p in [source,old,final])  # Originals are never moved or deleted.


def test_partial_unity_write_does_not_damage_saved_copy(tmp_path):
    source=tmp_path/'ParticipantData_PID_12.json';atomic_json(source,value())
    folder=tmp_path/'session';folder.mkdir()
    recorder=SessionRecorder(source,folder,12,settings(value()),{})
    recorder.poll()
    source.write_text('{')
    with pytest.raises(ValueError):recorder.poll()
    assert json.loads((folder/'simulator'/source.name).read_text())['curState']=='searching'
    atomic_json(source,value(phase='sagat'))
    recorder.poll()
    assert json.loads((folder/'simulator'/'last_searching.json').read_text())['curState']=='searching'


def test_settings_change_is_rejected_before_next_movement(tmp_path):
    source=tmp_path/'state.json';atomic_json(source,value())
    folder=tmp_path/'session';folder.mkdir()
    recorder=SessionRecorder(source,folder,12,settings(value()),{})
    with pytest.raises(RuntimeError,match='map or condition changed'):
        recorder.validate(value(cff=1))
    recorder.validate(value(phase='sagat'))


@pytest.mark.parametrize('training', [False,True])
def test_two_input_session_saves_console_controller_and_final_unity_files(tmp_path,monkeypatch,training):
    import threading,time
    (tmp_path/'configs').mkdir()
    (tmp_path/'configs/expert.json').write_text(json.dumps({'simulator_directory':'simulator'}))
    output=tmp_path/'simulator/OutputData';output.mkdir(parents=True)
    source=output/'ParticipantData_PID_12.json'
    initial=value(map_type=0 if training else 1)
    atomic_json(source,initial)
    called=[]
    def finish_unity():
        atomic_json(source,value(phase='endProgram',map_type=0 if training else 1))
        name='AllPositions_PID_12_COPY_1.json' if (output/'AllPositions_PID_12.json').exists() else 'AllPositions_PID_12.json'
        atomic_json(output/name,{'positions':[1,2,3]})
    def controller(argv=None,session_check=None):
        called.append(argv)
        session_check(initial)
        controller_dir=Path(argv[argv.index('--run-dir')+1]);controller_dir.mkdir()
        (controller_dir/'actions.jsonl').write_text('{"action":"recorded"}\n')
        print('Test controller output')
        finish_unity()
    monkeypatch.setattr('expert_scout.runtime.main',controller)
    # Training records without ever starting controller/YOLO/keyboard code.
    if training:
        def training_exit():
            for _ in range(100):
                if list(tmp_path.glob('participant_data/PID12/Training/*/session.json')):
                    finish_unity();return
                time.sleep(.02)
        thread=threading.Thread(target=training_exit);thread.start()
    answers=iter(['12','Training' if training else 'Control'])
    folder=run_session(tmp_path,lambda prompt:next(answers))
    if training:thread.join()
    assert folder.parent.name==('Training' if training else 'Control')
    assert folder.parent.parent.name=='PID12'
    result=json.loads((folder/'session_result.json').read_text())
    assert result['recording_complete'] and result['explainability']=='Local'
    assert (folder/'simulator/AllPositions_PID_12.json').exists()
    assert (folder/'console.txt').is_file()
    assert bool(called)==(not training)
    if not training:
        assert 'Test controller output' in (folder/'console.txt').read_text()
        assert (folder/'controller/actions.jsonl').exists()
        previous_console=(folder/'console.txt').read_bytes()
        atomic_json(source,initial)
        answers2=iter(['12','Control'])
        second=run_session(tmp_path,lambda prompt:next(answers2))
        assert second != folder
        assert (folder/'console.txt').read_bytes()==previous_console
        assert (second/'simulator/AllPositions_PID_12_COPY_1.json').exists()
        assert not (second/'simulator/AllPositions_PID_12.json').exists()


def test_exit_is_detected_even_when_backup_destination_is_locked(tmp_path):
    source=tmp_path/'ParticipantData_PID_12.json';atomic_json(source,value(phase='endProgram'))
    folder=tmp_path/'session';folder.mkdir()
    recorder=SessionRecorder(source,folder,12,settings(value()),{})
    with patch('expert_scout.session.atomic_json',side_effect=PermissionError('locked')):
        with pytest.raises(PermissionError):recorder.poll()
    assert recorder.finished.is_set()
    assert source.is_file()



def test_final_position_file_written_after_exit_is_saved_automatically(tmp_path):
    import threading,time
    output=tmp_path/'OutputData';output.mkdir()
    source=output/'ParticipantData_PID_12.json';atomic_json(source,value(phase='endProgram'))
    folder=tmp_path/'session';folder.mkdir()
    recorder=SessionRecorder(source,folder,12,settings(value()),{})
    recorder.start()
    assert recorder.finished.wait(2)
    def delayed_positions():
        time.sleep(.1)
        atomic_json(output/'AllPositions_PID_12.json',{'positions':['final']})
    worker=threading.Thread(target=delayed_positions);worker.start()
    assert recorder.close()
    worker.join()
    assert json.loads((folder/'simulator/AllPositions_PID_12.json').read_text())=={'positions':['final']}


def test_controller_error_is_visible_and_final_unity_data_is_still_archived(tmp_path,monkeypatch):
    (tmp_path/'configs').mkdir()
    (tmp_path/'configs/expert.json').write_text(json.dumps({'simulator_directory':'simulator'}))
    output=tmp_path/'simulator/OutputData';output.mkdir(parents=True)
    source=output/'ParticipantData_PID_12.json';atomic_json(source,value())
    def failed_controller(argv=None,session_check=None):
        atomic_json(source,value(phase='endProgram'))
        atomic_json(output/'AllPositions_PID_12.json',{'positions':['final']})
        raise RuntimeError('Controller test failure')
    monkeypatch.setattr('expert_scout.runtime.main',failed_controller)
    answers=iter(['12','Control'])
    with pytest.raises(RuntimeError,match='Controller test failure'):
        run_session(tmp_path,lambda prompt:next(answers))
    result_file,=tmp_path.glob('participant_data/PID12/Control/*/session_result.json')
    result=json.loads(result_file.read_text())
    assert result['recording_complete'] and result['error']=='Controller test failure'
    assert 'Controller test failure' in (result_file.parent/'console.txt').read_text()
    assert (result_file.parent/'simulator/AllPositions_PID_12.json').exists()
