from types import SimpleNamespace
from unittest.mock import patch

import pytest

from expert_scout.companion import CompanionNavigator
from expert_scout.confidence import ConfidenceSender
from expert_scout.config import Config
from expert_scout.state import AtomicState
from expert_scout.vision import Capture
from modules.auv.navigator.static_navigator.companion_navigator import CompanionNavigator as OriginalCompanion
from test_scout_route import boxes, make_run


@pytest.mark.parametrize('diver', [(0, 0, 8), (8, 2, 0), (-8, -2, -8), (0, 0, -8), (0, 0, 5)])
@pytest.mark.parametrize('yaw', [0, 90, 180, 355])
@pytest.mark.parametrize('obstacles', [{}, {'auvDistToFront': .5}, {'auvDistToFloor': .5},
                                      {'auvDistToFront': .5, 'auvDistToLeft': .5, 'auvDistToTop': .5}])
def test_follow_movement_matches_original_companion(diver, yaw, obstacles):
    state = AtomicState()
    state.update({'latestPositions': {
        'auvPosition': dict(x=0, y=0, z=0), 'auvRotation': {'y': yaw},
        'diverPosition': dict(zip(('x', 'y', 'z'), diver)), **obstacles}})
    original = OriginalCompanion(state, 'companion', [], lambda role: None,
                                 collision_threshold=1.5, yaw_threshold=.3)
    companion = CompanionNavigator(state, 'scout', [], lambda role: None,
                                   collision_threshold=1.5, yaw_threshold=.3)
    original.navigate()
    action = companion.action(5)
    assert {key: getattr(action, key) for key in original._movement_keys} == original._movement_keys


def test_following_stops_for_questionnaire_and_missing_or_stale_pose():
    controller, snapshot, step = make_run(boxes())
    pose = snapshot['latestPositions']
    pose['diverPosition']['z'] = -8
    assert step()['action'].source == 'companion'
    snapshot['curState'] = 'sagat'
    assert step(101)['action'].is_empty()
    snapshot['curState'] = 'searching'
    assert step(102)['action'].source == 'companion'
    with patch('time.time', return_value=104):
        assert controller.step(snapshot, None)['action'].is_empty()
    pose.pop('diverPosition')
    assert step(103)['action'].is_empty()
    pose['diverPosition'] = dict(x=0, y=-23.36, z=-8)
    pose['auvRotation'] = {}
    assert step(104)['action'].is_empty()


def test_wait_at_unopened_box_takes_priority_over_following():
    controller, snapshot, step = make_run(boxes())
    pose = snapshot['latestPositions']
    pose['auvPosition']['z'] = pose['diverPosition']['z'] = 7
    assert step()['action'].signal
    pose['diverPosition']['z'] = -20
    record = step(101)
    assert record['phase'] == 'waiting_for_diver'
    assert record['action'].source == 'waiting_for_diver'
    assert record['action'].lights and record['action'].yaw_right
    assert not record['action'].forward
    assert controller.collected == []


def test_collection_during_following_is_kept_and_opened_target_is_excluded():
    controller, snapshot, step = make_run(boxes())
    snapshot['latestPositions']['diverPosition']['z'] = 13
    assert step()['action'].source == 'companion'
    assert controller.target_id == 2
    assert step(101, press=True)['collected_box_ids'] == [1]
    snapshot['latestPositions']['diverPosition']['z'] = 0
    record = step(102)
    assert record['target_box_id'] == 2 and record['action'].source == 'expert'
    snapshot['collectedBoxIds'] = [1, 2]
    snapshot['boxesFound'] = 2
    assert step(103)['target_box_id'] is None
    snapshot['latestPositions']['diverPosition']['z'] = 8
    record = step(104)
    assert record['phase'] == 'complete'
    assert record['action'].source == 'companion' and record['action'].forward
    assert set(record['collected_box_ids']) == {1, 2}


def test_confidence_shortcut_remains_active_while_following():
    controller, snapshot, step = make_run(boxes())
    snapshot['latestPositions']['diverPosition']['z'] = -8
    record = step()
    record['selected_action'] = record.pop('action').to_dict()
    assert record['selected_action']['source'] == 'companion'
    keys = []
    def tap(key):
        keys.append(key)
        return {'sent': True}
    sender = ConfidenceSender(Config(), SimpleNamespace(tap_key=tap))
    frame = Capture(None, [{'class_name': 'box', 'confidence': .9}], 100, 100, 100)
    result = sender.update(record, snapshot, 100, frame)
    assert result['sent'] and keys == ['shift+3']
