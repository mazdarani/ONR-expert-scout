from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import patch

from expert_scout.confidence import ConfidenceSender
from expert_scout.config import Config
from expert_scout.vision import Capture
from test_scout_route import make_run, boxes


def test_collection_key_queued_just_before_questionnaire_is_not_discarded():
    controller, value, step = make_run(boxes())
    value['latestPositions']['auvPosition']['z'] = 7
    value['latestPositions']['diverPosition']['z'] = 8
    step()
    event = dict(deepcopy(value), _interaction_time=100)
    value['curState'] = 'sagat'
    value['_sourceMtime'] = 100.1
    with patch('time.time', return_value=100.1):
        record = controller.step(value, None, [event])
    assert record['action'].is_empty()
    assert record['collected_box_ids'] == [2]
    value['curState'] = 'searching'
    record = step(500)
    assert record['target_box_id'] == 1
    assert record['action'].forward


def test_resume_with_partial_rotation_holds_instead_of_raising_key_error():
    controller, value, step = make_run(boxes())
    step()
    value['curState'] = 'sagat'
    step(101)
    value['curState'] = 'searching'
    value['latestPositions']['auvRotation'] = {'x': 0, 'z': 0}
    frame = Capture(None, [{'class_name':'box','confidence':.9,'xywh':[50,50,10,10]}], 102,100,100)
    value['_sourceMtime'] = 102
    with patch('time.time', return_value=102):
        result = controller.step(value, frame)
    assert result['action'].is_empty()
    assert result['wait_reason'] == 'missing_auv_pose'


def test_questionnaire_never_sends_confidence_keys_even_with_last_box_frame():
    keys=[]
    sender=ConfidenceSender(Config(), SimpleNamespace(tap_key=lambda name: keys.append(name)))
    frame=Capture(None,[{'class_name':'box','confidence':.9}],100,100,100)
    result=sender.update({'phase':'waiting_for_diver','collected_box_ids':[]},
                         {'curState':'sagat','_sourceMtime':100},100,frame)
    assert not result['sent']
    assert keys == []


def test_missed_f_is_recovered_from_frozen_timer_and_collection_count():
    controller, value, step = make_run(boxes())
    for b in value['boxTimeList']:
        b['findTime'] = 10
    step()
    value['curState'] = 'sagat'
    value['boxesFound'] = 1
    step(101)
    # The entire pause cannot be mistaken for elapsed searching time.
    step(500)
    assert controller.collected == []
    value['curState'] = 'searching'
    assert step(501)['action'].source == 'waiting_for_collection_identity'
    value['totalTime'] = 10.6
    value['boxTimeList'][0]['findTime'] = 10.6
    step(501.6)
    value['totalTime'] = 10.7
    value['boxTimeList'][0]['findTime'] = 10.7
    record = step(501.7)
    assert record['confirmed_box_ids'] == [2]
    assert record['target_box_id'] == 1
    assert record['action'].forward


def test_restart_holds_until_the_already_opened_id_is_recovered():
    controller, value, step = make_run(boxes())
    value['boxesFound'] = 1
    for b in value['boxTimeList']:
        b['findTime'] = 10 if b['boxID'] == 1 else 5
    assert step()['action'].is_empty()
    assert controller.target_id is None
    value['totalTime'] = 11
    value['boxTimeList'][0]['findTime'] = 11
    assert step(101)['action'].is_empty()
    value['totalTime'] = 12
    value['boxTimeList'][0]['findTime'] = 12
    result = step(102)
    assert result['collected_box_ids'] == [2]
    assert result['target_box_id'] == 1


def test_ambiguous_frozen_boxes_do_not_guess_or_move():
    controller, value, step = make_run(boxes())
    value['boxesFound'] = 1
    for b in value['boxTimeList']:
        b['findTime'] = 10
    step()
    value['totalTime'] = 11
    result = step(101)
    assert result['collected_box_ids'] == []
    assert result['action'].source == 'waiting_for_collection_identity'


def test_opened_high_score_is_ignored_but_visible_unopened_box_can_signal():
    keys=[]
    sender=ConfidenceSender(Config(),SimpleNamespace(tap_key=lambda name: keys.append(name) or {'sent':True}))
    value={'curState':'searching','_sourceMtime':100,
           'latestPositions':{'auvPosition':{'x':0,'y':0,'z':0},'auvRotation':{'y':0}},
           'boxTimeList':[{'boxID':0,'boxPosition':{'x':0,'y':0,'z':8}},
                          {'boxID':1,'boxPosition':{'x':10,'y':0,'z':10}}]}
    frame=Capture(None,[{'class_name':'box','confidence':.99,'xywh':[50,50,10,10]},
                        {'class_name':'box','confidence':.8,'xywh':[100,50,10,10]}],100,100,100)
    result=sender.update({'collected_box_ids':[0]},value,100,frame)
    assert result['box_id']==1 and result['score']==.8
    assert keys==['shift+2']
    frame.detections.pop()
    assert not sender.update({'collected_box_ids':[0]},value,100,frame)['sent']
    assert keys==['shift+2']


def test_unknown_identity_or_overlapping_opened_box_does_not_signal():
    keys=[]
    sender=ConfidenceSender(Config(),SimpleNamespace(tap_key=lambda name: keys.append(name)))
    value={'curState':'searching','_sourceMtime':100,
           'latestPositions':{'auvPosition':{'x':0,'y':0,'z':0},'auvRotation':{'y':0}},
           'boxTimeList':[{'boxID':0,'boxPosition':{'x':0,'y':0,'z':8}},
                          {'boxID':1,'boxPosition':{'x':0,'y':0,'z':20}}]}
    frame=Capture(None,[{'class_name':'box','confidence':.99,'xywh':[50,50,10,10]}],100,100,100)
    assert not sender.update({'collected_box_ids':[0]},value,100,frame)['sent']
    value.pop('latestPositions')
    assert not sender.update({'collected_box_ids':[0]},value,100,frame)['sent']
    assert keys==[]


def test_frame_from_questionnaire_is_not_used_after_resume():
    keys=[]
    sender=ConfidenceSender(Config(),SimpleNamespace(tap_key=lambda name: keys.append(name)))
    frame=Capture(None,[{'class_name':'box','confidence':.9}],100,100,100)
    result=sender.update({'camera_not_before':100.2}, {'curState':'searching','_sourceMtime':100.2},100.2,frame)
    assert result['reason']=='frame_before_resume'
    assert keys==[]


def test_movement_keys_release_for_sagat_and_press_again_after_resume():
    from expert_scout.actuator import KeyboardActuator
    keys=[]
    keyboard=SimpleNamespace(press=lambda key: keys.append(('press',key)),
                             release=lambda key: keys.append(('release',key)))
    actuator=KeyboardActuator(tap_duration=0,keyboard=keyboard)
    controller,value,step=make_run(boxes())
    actuator.apply(step()['action'])
    assert ('press','i') in keys
    value['curState']='sagat'
    actuator.apply(step(101)['action'])
    assert keys[-1]==('release','i')
    value['curState']='searching'
    actuator.apply(step(500)['action'])
    assert keys[-1]==('press','i')
    actuator.close()


def test_final_collection_is_recorded_even_when_next_snapshot_is_end_screen():
    controller,value,step=make_run(boxes())
    value['latestPositions']['diverPosition']['z']=8
    step()
    event=dict(deepcopy(value),_interaction_time=100)
    value['curState']='endScreen'
    with patch('time.time',return_value=100):
        record=controller.step(value,None,[event])
    assert record['collected_box_ids']==[2]
    assert record['action'].is_empty()


def test_one_lagging_unopened_clock_is_not_mistaken_for_a_collection():
    from expert_scout.opened import OpenedBoxes
    tracker=OpenedBoxes()
    value={'curState':'searching','totalTime':10,'boxesFound':0,
           'boxTimeList':[{'boxID':1,'findTime':10},{'boxID':2,'findTime':10}]}
    tracker.update(value)
    # On a slow frame, DataManager may run before one CargoBox updates its timer.
    value['totalTime']=10.8
    value['boxesFound']=1
    value['boxTimeList'][0]['findTime']=10.1
    assert tracker.update(value)==set()
    value['totalTime']=10.9
    value['boxTimeList'][1]['findTime']=10.9
    assert tracker.update(value)==set()
    value['totalTime']=11.4
    value['boxTimeList'][1]['findTime']=11.4
    assert tracker.update(value)=={1}


def test_missing_pose_after_resume_never_crashes_opened_box_matching():
    from expert_scout.matching import match_detections
    frame=Capture(None,[{'class_name':'box','confidence':.9,'xywh':[50,50,10,10]}],100,100,100)
    value={'curState':'searching','_sourceMtime':100,'latestPositions':None,'boxTimeList':None}
    assert match_detections(value,frame.detections,100,Config())==[]
    keys=[]
    sender=ConfidenceSender(Config(),SimpleNamespace(tap_key=lambda name:keys.append(name)))
    result=sender.update({'collected_box_ids':[0],'selected_action':{'source':'telemetry_wait'}},value,100,frame)
    assert result['reason']=='controller_wait' and keys==[]


def test_incomplete_resume_payload_keeps_last_complete_snapshot(tmp_path):
    import json
    from expert_scout.io import TelemetryReader
    path=tmp_path/'ParticipantData_PID_0.json'
    path.write_text(json.dumps({'curState':'sagat','latestPositions':{},'boxTimeList':[]}))
    reader=TelemetryReader(tmp_path,0)
    source_stamp=reader.read()['_sourceMtime']
    path.write_text(json.dumps({'curState':'searching','latestPositions':None}))
    assert reader.read()['curState']=='sagat'
    assert reader.read()['_sourceMtime']==source_stamp
    assert reader.diagnostics()['status']=='invalid_json'
