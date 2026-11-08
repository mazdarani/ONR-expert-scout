import json
import math
from pathlib import Path
from unittest.mock import patch

import pytest

from expert_scout.action import Action
from expert_scout.approach import OracleBoxNavigator
from expert_scout.config import Config, load_config
from expert_scout.controller import ExpertController
from expert_scout.grid import GridSearchNavigator
from expert_scout.routing import nearest_box, box_order
from expert_scout.state import AtomicState

ROOT = Path(__file__).resolve().parents[1]
LAYOUTS = json.loads((ROOT / 'tests/fixtures/ONRScubaCFF_maps.json').read_text())


def make_run(boxes):
    state = AtomicState()
    collected = []
    grid = GridSearchNavigator(state, 'scout', collected, lambda role: None)
    approach = OracleBoxNavigator(state, 'scout', collected, lambda role: None, lambda box: None,
                                  collection_distance=1.5, yaw_threshold=.3, collision_threshold=1.5)
    controller = ExpertController(Config(), grid, approach, collected)
    snapshot = {'curState': 'searching', 'totalTime': 10, 'boxesFound': 0,
                'boxTimeList': boxes, 'collectedBoxIds': [],
                'latestPositions': {'auvPosition': {'x': 0., 'y': -23.36, 'z': 0.},
                                    'auvRotation': {'y': 0.},
                                    'diverPosition': {'x': 0., 'y': -23.36, 'z': 0.}}}
    def step(now=100):
        snapshot['_sourceMtime'] = now
        state.update(snapshot)
        with patch('time.time', return_value=now):
            return controller.step(snapshot, None)
    return controller, snapshot, step


def boxes():
    return [{'boxID': 1, 'boxPosition': {'x': 0, 'y': -23.36, 'z': 8}},
            {'boxID': 2, 'boxPosition': {'x': 0, 'y': -23.36, 'z': 3}}]


def test_default_launch_uses_nearest_with_realistic_escort_distance():
    config = load_config(ROOT / 'configs/expert.json')
    assert config.route_mode == 'nearest'
    assert config.diver_max_separation == 5
    assert config.diver_resume_separation == 3


def test_nearest_uses_coordinates_not_input_order_distance_field_or_yolo():
    controller, snapshot, step = make_run(boxes())
    snapshot['boxTimeList'][0]['auvDist'] = .01
    assert step()['target_box_id'] == 2
    snapshot['boxTimeList'][0]['boxPosition']['z'] = .1
    assert step()['target_box_id'] == 2  # Do not switch targets mid-approach.


def test_escort_pause_covers_approach_and_resumes_same_target():
    controller, snapshot, step = make_run(boxes())
    snapshot['latestPositions']['diverPosition']['x'] = 6
    assert step()['action'].source == 'waiting_for_diver_to_follow'
    snapshot['latestPositions']['diverPosition']['x'] = 4
    assert step()['action'].is_empty()
    snapshot['latestPositions']['diverPosition']['x'] = 3
    record = step()
    assert record['target_box_id'] == 2
    assert record['action'].forward
    snapshot['latestPositions'].pop('diverPosition')
    assert step()['action'].source == 'waiting_for_diver_pose'


def test_box_wait_survives_diver_leaving_missing_target_and_other_collection():
    controller, snapshot, step = make_run(boxes())
    snapshot['latestPositions']['auvPosition']['z'] = 2
    assert step()['phase'] == 'waiting_for_diver'
    snapshot['latestPositions']['diverPosition']['z'] = 50
    snapshot['boxTimeList'] = []
    snapshot['collectedBoxIds'] = [1]
    assert step(500)['action'].is_empty()
    assert controller.target_id == 2
    snapshot['collectedBoxIds'] = [1, 2]
    assert step(501)['phase'] == 'collection_dwell'
    assert step(511)['action'].is_empty()


def test_lost_target_does_not_move_to_a_different_box():
    controller, snapshot, step = make_run(boxes())
    step()
    snapshot['boxTimeList'].pop()
    assert step()['action'].source == 'waiting_for_target_telemetry'
    assert controller.target_id == 2


def test_count_without_identity_holds_instead_of_revisiting_an_open_box():
    controller, snapshot, step = make_run(boxes())
    snapshot['boxesFound'] = 1
    assert step()['action'].source == 'waiting_for_collection_identity'


def test_tie_break_and_invalid_coordinates():
    candidates = boxes()
    candidates[0]['boxPosition'] = dict(candidates[1]['boxPosition'])
    assert nearest_box({'x': 0, 'y': 0, 'z': 0}, candidates)['boxID'] == 1
    candidates[0]['boxPosition']['x'] = float('nan')
    assert nearest_box({'x': 0, 'y': 0, 'z': 0}, candidates)['boxID'] == 2
    assert nearest_box({'x': 0}, candidates) is None


@pytest.mark.parametrize('layout', LAYOUTS)
def test_full_route_with_real_navigator_waits_for_each_opened_id(layout):
    targets = [{'boxID': b['id'], 'boxPosition': b['position']} for b in LAYOUTS[layout]]
    controller, snapshot, step = make_run(targets)
    pose = snapshot['latestPositions']
    expected = box_order(pose['auvPosition'], targets)
    visited = []
    now = 100.
    for _ in range(12000):
        record = step(now)
        action = record['action']
        if record['phase'] == 'complete':
            break
        if record['phase'] == 'waiting_for_diver':
            target = record['target_box_id']
            assert target not in visited
            assert action.is_empty()
            # No timeout or loss of YOLO may release the box wait.
            assert step(now + 300)['action'].is_empty()
            visited.append(target)
            snapshot['collectedBoxIds'].append(target)
            snapshot['boxesFound'] += 1
        else:
            yaw = pose['auvRotation']['y']
            yaw += (int(action.yaw_right) - int(action.yaw_left)) * 5
            pose['auvRotation']['y'] = yaw
            p = pose['auvPosition']
            p['x'] += (int(action.forward) - int(action.backward)) * .15 * math.sin(math.radians(yaw))
            p['z'] += (int(action.forward) - int(action.backward)) * .15 * math.cos(math.radians(yaw))
            p['y'] += (int(action.up) - int(action.down)) * .1
            pose['diverPosition'] = dict(p)
        now += .1
    else:
        pytest.fail('Route did not finish under unobstructed simulated motion')
    assert visited == expected
    assert set(visited) == {b['boxID'] for b in targets}
    assert step(now + 1000)['action'].is_empty()


def test_approach_turns_before_forward_and_closes_diagonal_arrival_gap():
    controller, snapshot, step = make_run(boxes())
    snapshot['latestPositions']['auvRotation']['y'] = 90
    action = step()['action']
    assert action.yaw_left and not action.forward
    target = snapshot['boxTimeList'][1]['boxPosition']
    snapshot['latestPositions']['auvRotation']['y'] = 0
    snapshot['latestPositions']['auvPosition'] = dict(x=0, y=target['y']+.49, z=target['z']-1.49)
    action = step()['action']
    assert action.forward and action.down
