from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from expert_scout.io import TelemetryReader
from expert_scout.runtime import build_parser


def snapshot(time, found=0, clocks=(10,10), state='searching'):
    return {'totalTime':time,'boxesFound':found,'curState':state,
            'boxTimeList':[{'boxID':i,'findTime':value} for i,value in enumerate(clocks)]}


def test_telemetry_handles_string_pid_copied_files_and_partial_writes(tmp_path):
    path=tmp_path/'ParticipantData_PID_0_COPY_2.json'
    value=snapshot(10)
    value.update(PID='0', latestPositions={'auvPosition':{'x':0,'y':0,'z':0}}, endTime=None)
    path.write_text(json.dumps(value))
    reader=TelemetryReader(tmp_path,0)
    read=reader.read()
    assert read['PID']==0
    assert read['curState']=='searching'
    stamp=read['_sourceMtime']
    path.write_text('{')
    assert reader.read()['_sourceMtime']==stamp
    value['curState']='SAGAT'
    path.write_text(json.dumps(value))
    assert reader.read()['curState']=='SAGAT'
    value['curState']='endProgram'
    path.write_text(json.dumps(value))
    assert reader.read()['curState']=='endProgram'


def test_telemetry_normalizes_new_build_lifecycle_state_names(tmp_path):
    path=tmp_path/'ParticipantData_PID_0.json'
    value=snapshot(10)
    path.write_text(json.dumps(value))
    reader=TelemetryReader(tmp_path,0)
    assert reader.read()['curState']=='searching'
    for source, expected in [('out_of_oxygen','outOfOxygen'), ('title-screen','titleScreen'),
                             ('end_screen','endScreen'), ('end-program','endProgram')]:
        value['curState']=source
        path.write_text(json.dumps(value))
        assert reader.read()['curState']==expected


def test_simulator_path_can_be_supplied_without_changing_code():
    args=build_parser().parse_args(['--pid','0','--sim-dir',r'C:\Sim\ONRScubaCFF'])
    assert args.sim_dir==r'C:\Sim\ONRScubaCFF'


def test_changed_content_is_read_even_when_file_timestamp_is_unchanged(tmp_path):
    import os
    path=tmp_path/'ParticipantData_PID_0.json'
    value=snapshot(10)
    path.write_text(json.dumps(value))
    reader=TelemetryReader(tmp_path,0)
    first=reader.read()
    stamp=path.stat().st_mtime_ns
    value['curState']='endProgram'
    path.write_text(json.dumps(value))
    os.utime(path,ns=(stamp,stamp))
    assert reader.read()['curState']=='endProgram'
    assert reader.read()['_sourceMtime']==first['_sourceMtime']
    value['curState']='searching'
    value['totalTime']=11
    path.write_text(json.dumps(value))
    os.utime(path,ns=(stamp,stamp))
    assert reader.read()['totalTime']==11


def test_map_is_read_from_exact_participant_not_an_id_with_the_same_prefix(tmp_path):
    import os
    selected=tmp_path/'ParticipantData_PID_1_COPY_0.json'
    other=tmp_path/'ParticipantData_PID_10.json'
    selected.write_text(json.dumps(dict(snapshot(10),mapType=1)))
    other.write_text(json.dumps(dict(snapshot(10),mapType=2)))
    os.utime(selected,(100,100))
    os.utime(other,(200,200))
    assert TelemetryReader(tmp_path,1).read()['mapType']==1
