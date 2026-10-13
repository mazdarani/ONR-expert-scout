from dataclasses import replace
from copy import deepcopy
from types import SimpleNamespace
import pytest

from expert_scout.actuator import KeyboardActuator, DryRunActuator
from expert_scout.confidence import ConfidenceSender, confidence_level
from expert_scout.config import Config


@pytest.mark.parametrize('score,level',[(.25,'low'),(.7199,'low'),(.72,'medium'),(.8199,'medium'),(.82,'high'),(1.,'high'),
                                      (.24,None),(-1,None),(1.1,None),(None,None),(True,None),(float('nan'),None)])
def test_exact_score_boundaries(score,level):
    assert confidence_level(score,Config())==level


@pytest.fixture
def feedback():
    keys=[]
    actuator=SimpleNamespace(tap_key=lambda key: (keys.append(key) or {'key':key,'sent':True}))
    record={'phase':'waiting_for_diver','target_box_id':0,
            'target_detection':{'confidence':.8,'timestamp':100}}
    snapshot={'curState':'searching','_sourceMtime':100,
              'latestPositions':{'auvPosition':{'x':0,'y':0,'z':0}},
              'boxTimeList':[{'boxID':0,'boxPosition':{'x':0,'y':0,'z':1}}]}
    return SimpleNamespace(sender=ConfidenceSender(Config(),actuator),keys=keys,record=record,snapshot=snapshot)


def test_score_and_key_are_for_the_reached_target(feedback):
    result=feedback.sender.update(feedback.record,feedback.snapshot,100)
    assert result['score']==.8
    assert result['level']=='medium'
    assert feedback.keys==['f7']
    assert result['sent']


def test_same_category_does_not_repeat_key(feedback):
    feedback.sender.update(feedback.record,feedback.snapshot,100)
    feedback.sender.update(feedback.record,feedback.snapshot,100.5)
    assert feedback.keys==['f7']


def test_category_change_is_rate_limited_then_sent(feedback):
    feedback.sender.update(feedback.record,feedback.snapshot,100)
    feedback.record['target_detection']['confidence']=.9
    assert feedback.sender.update(feedback.record,feedback.snapshot,100.2)['reason']=='rate_limited'
    result=feedback.sender.update(feedback.record,feedback.snapshot,100.75)
    assert result['level']=='high'
    assert feedback.keys==['f7','f8']


@pytest.mark.parametrize('phase',['searching','approaching','collection_dwell','inactive'])
def test_no_keys_outside_reached_box_feedback(feedback,phase):
    feedback.record['phase']=phase
    assert not feedback.sender.update(feedback.record,feedback.snapshot,100)['sent']
    assert feedback.keys==[]


def test_stale_score_is_not_sent(feedback):
    feedback.record['target_detection']['timestamp']=90
    assert feedback.sender.update(feedback.record,feedback.snapshot,100)['reason']=='stale_yolo_score'
    assert feedback.keys==[]


def test_sagat_and_stale_telemetry_do_not_send_keys(feedback):
    feedback.snapshot['curState']='SAGAT'
    assert not feedback.sender.update(feedback.record,feedback.snapshot,100)['sent']
    feedback.snapshot['curState']='searching'
    feedback.snapshot['_sourceMtime']=90
    assert not feedback.sender.update(feedback.record,feedback.snapshot,100)['sent']
    assert feedback.keys==[]


def test_panel_target_mismatch_does_not_send_confidence_for_wrong_box(feedback):
    feedback.snapshot['boxTimeList'].append({'boxID':1,'boxPosition':{'x':0,'y':0,'z':.5}})
    assert feedback.sender.update(feedback.record,feedback.snapshot,100)['reason']=='target_not_nearest_to_auv'
    assert feedback.keys==[]


def test_drift_out_of_collection_distance_stops_signals(feedback):
    feedback.snapshot['boxTimeList'][0]['boxPosition']['z']=5
    assert not feedback.sender.update(feedback.record,feedback.snapshot,100)['sent']
    assert feedback.keys==[]


def test_same_category_for_a_new_box_is_sent_again(feedback):
    feedback.sender.update(feedback.record,feedback.snapshot,100)
    feedback.record['target_box_id']=1
    feedback.snapshot['boxTimeList'][0]['boxID']=1
    feedback.record['target_detection']['timestamp']=101
    feedback.snapshot['_sourceMtime']=101
    feedback.sender.update(feedback.record,feedback.snapshot,101)
    assert feedback.keys==['f7','f7']


def test_dry_run_reports_key_without_claiming_it_was_sent(feedback):
    feedback.sender.actuator=DryRunActuator()
    result=feedback.sender.update(feedback.record,feedback.snapshot,100)
    assert result['key']=='f7'
    assert not result['sent']
    assert result['actuation']['would_send']


def test_function_key_is_pressed_and_released_once():
    events=[]
    keyboard=SimpleNamespace(press=lambda key: events.append(('press',key)),release=lambda key:events.append(('release',key)))
    actuator=KeyboardActuator(tap_duration=0,keyboard=keyboard)
    assert actuator.tap_key('f6')['sent']
    assert events==[('press','f6'),('release','f6')]


def test_hotkey_is_released_when_key_press_fails():
    events=[]
    def fail(key):
        raise RuntimeError('input failed')
    actuator=KeyboardActuator(tap_duration=0,keyboard=SimpleNamespace(press=fail,release=events.append))
    with pytest.raises(RuntimeError):
        actuator.tap_key('f8')
    assert events==['f8']


@pytest.mark.parametrize('medium,high',[(.25,.82),(.82,.72),(.72,.72),(.72,1.1),(float('nan'),.82)])
def test_invalid_category_configuration_is_rejected(medium,high):
    with pytest.raises(ValueError):
        replace(Config(),medium_confidence=medium,high_confidence=high).validate()
