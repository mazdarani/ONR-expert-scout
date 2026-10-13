from copy import deepcopy
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from expert_scout.io import TelemetryReader
from expert_scout.simulator import CollectionTracker
from expert_scout.runtime import build_parser


def snapshot(time, found=0, clocks=(10,10), state='searching'):
    return {'totalTime':time,'boxesFound':found,'curState':state,
            'boxTimeList':[{'boxID':i,'findTime':value} for i,value in enumerate(clocks)]}


def test_opened_box_zero_is_identified_while_other_clock_advances():
    tracker=CollectionTracker()
    assert tracker.update(snapshot(10))==set()
    assert tracker.update(snapshot(10.2,1,(10,10.2)))==set()
    assert tracker.update(snapshot(10.6,1,(10,10.6)))=={0}
    assert tracker.update(snapshot(11,1,(10,11)))=={0}


def test_count_increase_alone_does_not_collect_the_current_target():
    tracker=CollectionTracker()
    tracker.update(snapshot(10))
    assert tracker.update(snapshot(11,1,(11,11)))==set()


def test_frozen_clock_without_collection_count_is_not_confirmation():
    tracker=CollectionTracker()
    tracker.update(snapshot(10))
    assert tracker.update(snapshot(11,0,(10,11)))==set()


def test_pause_cannot_be_mistaken_for_open_boxes():
    tracker=CollectionTracker()
    tracker.update(snapshot(10))
    tracker.update(snapshot(20,1,(10,10),'sagat'))
    assert tracker.update(snapshot(21,1,(10,10)))==set()
    assert tracker.update(snapshot(21.6,1,(10,10.6)))=={0}


def test_ambiguous_frozen_clocks_do_not_guess_a_box_id():
    tracker=CollectionTracker()
    tracker.update(snapshot(10))
    assert tracker.update(snapshot(11,1,(10,10)))==set()
    assert tracker.update(snapshot(12,2,(10,10)))=={0,1}


def test_repeated_file_or_backwards_clock_cannot_confirm_collection():
    tracker=CollectionTracker()
    tracker.update(snapshot(10))
    for _ in range(20):
        assert tracker.update(snapshot(10,1))==set()
    assert tracker.update(snapshot(1,1))==set()
    assert tracker.update(snapshot(1.1,1))==set()


def test_collection_ids_are_authoritative_and_never_undone():
    tracker=CollectionTracker()
    value=snapshot(10)
    value['collectedBoxIds']=[0]
    assert tracker.update(value)=={0}
    assert tracker.update(snapshot(11))=={0}


def test_missing_timers_do_not_claim_success():
    tracker=CollectionTracker()
    value=snapshot(10,1,clocks=(None,float('nan')))
    assert tracker.update(value)==set()
    value['totalTime']=11
    assert tracker.update(value)==set()


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
