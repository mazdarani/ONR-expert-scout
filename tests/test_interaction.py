from copy import deepcopy
from inspect import getfullargspec
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from expert_scout.interaction import DiverInteractions, collection_from_interaction
from expert_scout.state import AtomicState
from test_scout_route import make_run, boxes


def snapshot(auv=(0, 0, 0), diver=(0, 0, 0), box=(0, 0, 2)):
    point = lambda p: dict(zip(('x', 'y', 'z'), p))
    return {'curState': 'searching', '_sourceMtime': 100,
            'latestPositions': {'auvPosition': point(auv), 'diverPosition': point(diver)},
            'boxTimeList': [{'boxID': 7, 'boxPosition': point(box)}]}


@pytest.mark.parametrize('auv,diver,box,expected', [
    ((0,0,0), (0,0,0), (0,0,2), (7,True)),
    ((0,0,0), (0,0,0), (0,0,10), (7,True)),
    ((0,0,0), (0,0,0), (0,0,10.01), None),
    ((0,0,0), (0,0,11), (0,0,12), (7,False)),
    ((0,0,0), (0,11,0), (0,11,1), (7,False)),
    ((0,0,0), (0,0,0), (0,11,0), None),
])
def test_collection_matches_original_ten_meter_3d_proximity_rules(auv, diver, box, expected):
    assert collection_from_interaction(snapshot(auv, diver, box), 10) == expected


def test_listener_queues_only_f_with_the_pose_at_keypress_and_stops():
    state = AtomicState()
    state.update(snapshot())
    lifecycle = []
    def factory(**callbacks):
        assert getfullargspec(callbacks['on_press'])
        return SimpleNamespace(start=lambda:lifecycle.append('start'), stop=lambda:lifecycle.append('stop'))
    inputs = DiverInteractions(state, listener_factory=factory)
    inputs.start()
    for char in ('1','2','3','x',' '):
        inputs._on_press(SimpleNamespace(char=char))
    assert inputs.drain() == []
    with patch('time.time', return_value=100):
        inputs._on_press(SimpleNamespace(char='f'))
    state.update(snapshot(diver=(0,0,50)))
    event, = inputs.drain()
    assert event['latestPositions']['diverPosition']['z'] == 0
    assert event['_interaction_time'] == 100
    assert inputs.drain() == []
    inputs.close()
    assert lifecycle == ['start','stop']


def test_escort_distance_is_horizontal_and_resume_has_no_three_meter_delay():
    controller, current, step = make_run(boxes())
    current['latestPositions']['diverPosition'] = {'x':6,'y':-23.36,'z':0}
    assert step()['action'].source == 'companion'
    current['latestPositions']['diverPosition'] = {'x':4.9,'y':20,'z':0}
    assert step()['action'].forward
    assert controller.target_id == 2


def test_collection_of_a_remote_box_keeps_current_box_wait_like_original():
    controller, current, step = make_run(boxes())
    current['latestPositions']['auvPosition']['z'] = 7
    current['latestPositions']['diverPosition']['z'] = 7
    step()
    current['boxTimeList'].append({'boxID':3,'boxPosition':{'x':0,'y':-23.36,'z':40}})
    current['latestPositions']['diverPosition']['z'] = 40
    result = step(101, press=True)
    assert controller.collected == [3]
    assert result['target_box_id'] == 2
    assert result['action'].yaw_right


@pytest.mark.parametrize('field,value', [('curState','sagat'),('_sourceMtime',90),('_interaction_time',90)])
def test_old_or_inactive_interactions_cannot_collect_in_a_later_frame(field, value):
    controller, current, step = make_run(boxes())
    step()
    event = deepcopy(current)
    event['_interaction_time'] = 100
    event[field] = value
    with patch('time.time',return_value=100):
        controller.step(current, None, [event])
    assert controller.collected == []


def test_repeated_f_does_not_mark_another_box_when_nearest_is_already_collected():
    controller, current, step = make_run(boxes())
    step(100, press=True)
    assert controller.collected == [2]
    step(100, press=True)
    assert controller.collected == [2]


def test_missing_diver_pose_rejects_collection():
    value = snapshot()
    value['latestPositions'].pop('diverPosition')
    assert collection_from_interaction(value, 10) is None


def test_box_wait_begins_below_original_five_meter_threshold():
    controller, current, step = make_run(boxes())
    current['latestPositions']['auvPosition']['z'] = 3
    current['latestPositions']['diverPosition']['z'] = 3
    assert step()['phase'] == 'approaching'  # Target is exactly 5 m away.
    current['latestPositions']['auvPosition']['z'] = 3.01
    assert step()['phase'] == 'waiting_for_diver'
