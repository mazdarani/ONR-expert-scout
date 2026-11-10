from concurrent.futures import Future
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import copy
import pytest

from expert_scout.action import Action
from expert_scout.approach import OracleBoxNavigator
from expert_scout.config import Config
from expert_scout.controller import ExpertController
from expert_scout.grid import GridSearchNavigator
from expert_scout.matching import match_detections
from expert_scout.runtime import build_parser
from expert_scout.state import AtomicState
from expert_scout.vision import Capture


@pytest.fixture
def setup():
    state = AtomicState()
    config = Config(route_mode="grid", diver_max_separation=100, diver_resume_separation=100)
    snapshot = {'curState':'searching', '_sourceMtime':100, 'boxesFound':0,
                'latestPositions': {'auvPosition': {'x':0,'y':0,'z':0}, 'auvRotation': {'x':0,'y':0,'z':0},
                                    'diverPosition': {'x':0,'y':0,'z':0}},
                'boxTimeList':[{'boxID':0,'boxPosition':{'x':0,'y':0,'z':10},'findTime':10}]}
    collected = []
    grid = GridSearchNavigator(state,'scout',collected,lambda role:None,collision_threshold=1.5,yaw_threshold=.3,
                               randomize_route=True,waypoint_jitter=2.5,depth_jitter=1.5,seed=123)
    approach = OracleBoxNavigator(state,'scout',collected,lambda role:None,lambda box_id:None,
                                   collision_threshold=1.5,yaw_threshold=.3,collection_distance=1.5)
    controller = ExpertController(config,grid,approach,collected)
    capture = Capture(object(),[{'xywh':[50,40,15,10],'frame_width':100,'frame_height':100,
                                 'confidence':.8,'class_name':'box','timestamp':100}],100,100,100)
    def step(now=100, frame=capture, press=False):
        snapshot['_sourceMtime'] = now
        state.update(snapshot)
        if frame is not None:
            frame.timestamp = now
        with patch('time.time',return_value=now):
            return controller.step(snapshot,frame, [dict(copy.deepcopy(snapshot), _interaction_time=now)] if press else ())
    return SimpleNamespace(state=state,config=config,snapshot=snapshot,grid=grid,approach=approach,
                           controller=controller,capture=capture,collected=collected,step=step)


def test_grid_search_does_not_use_box_coordinates(setup):
    setup.capture.detections=[]
    first = setup.step()['action'].active_keys()
    setup.snapshot['boxTimeList'][0]['boxPosition']={'x':1000,'y':300,'z':1000}
    assert setup.step()['action'].active_keys() == first
    assert setup.controller.phase == 'searching'


def test_yolo_triggers_coordinate_expert_not_a_model(setup):
    result=setup.step()
    assert result['phase']=='approaching'
    assert result['target_box_id']==0
    assert result['action'].source=='expert'
    assert result['action'].forward
    assert result['target_detection']['confidence']==.8


def test_expert_keeps_target_when_yolo_disappears(setup):
    setup.step()
    setup.capture.detections=[]
    result=setup.step(101)
    assert result['phase']=='approaching'
    assert result['action'].forward


def test_arrival_waits_for_diver_and_never_presses_collection_key(setup):
    setup.snapshot['boxTimeList'][0]['boxPosition']['z']=1
    result=setup.step()
    assert result['phase']=='waiting_for_diver'
    assert result['event']=='box_reached'
    assert result['action'].signal and result['action'].lights and result['action'].yaw_right
    assert setup.collected==[]
    assert setup.step(200)['phase']=='waiting_for_diver'


def test_f_collection_resumes_grid_without_dwell(setup):
    setup.snapshot['boxTimeList'][0]['boxPosition']['z']=1
    setup.step()
    setup.capture.detections=[]
    result=setup.step(101, press=True)
    assert result['event']=='diver_collection_inferred'
    assert setup.collected==[0]
    assert len(setup.grid._excluded_areas)==1
    assert result['phase']=='searching'
    assert result['action'].source=='grid'


def test_collected_boxes_do_not_trigger_new_approaches(setup):
    setup.collected.append(0)
    result=setup.step()
    assert result['phase']=='searching'
    assert result['target_box_id'] is None


def test_opened_box_does_not_suppress_a_different_unopened_box(setup):
    setup.collected.append(0)
    setup.snapshot['boxTimeList'].append({'boxID':1,'boxPosition':{'x':5,'y':0,'z':10}})
    setup.capture.detections.append(dict(setup.capture.detections[0],xywh=[79.5,40,10,10]))
    result=setup.step()
    assert result['phase']=='approaching'
    assert result['target_box_id']==1


def test_diver_follow_has_hysteresis(setup):
    setup.controller.config=replace(setup.config,diver_max_separation=5,diver_resume_separation=3)
    setup.capture.detections=[]
    setup.snapshot['latestPositions']['diverPosition']['z']=7
    assert setup.step()['action'].source=='companion'
    assert setup.step()['action'].forward
    setup.snapshot['latestPositions']['diverPosition']['z']=4
    assert setup.step()['action'].forward
    setup.snapshot['latestPositions']['diverPosition']['z']=2
    assert setup.step()['action'].source=='grid'


def test_paused_or_stale_telemetry_releases_all_motion(setup):
    setup.snapshot['curState']='sagat'
    assert setup.step()['action'].is_empty()
    setup.snapshot['curState']='searching'
    with patch('time.time',return_value=103):
        assert setup.controller.step(setup.snapshot,setup.capture)['action'].is_empty()


@pytest.mark.parametrize('score',[None,True,-1,1.2,float('nan'),.24])
def test_invalid_detector_scores_cannot_trigger_approach(setup,score):
    setup.capture.detections[0]['confidence']=score
    assert setup.step()['phase']=='searching'


def test_missing_or_stale_camera_keeps_grid_in_control(setup):
    assert setup.step(frame=None)['phase']=='searching'
    with patch('time.time',return_value=100):
        setup.capture.timestamp=90
        result=setup.controller.step(setup.snapshot,setup.capture)
    assert result['phase']=='searching'


def test_route_is_repeatable_for_a_fixed_seed(setup):
    setup.capture.detections=[]
    setup.step()
    other=GridSearchNavigator(setup.state,'scout',[],lambda role:None,randomize_route=True,
                              waypoint_jitter=2.5,depth_jitter=1.5,seed=123)
    other.action()
    assert other._waypoints==setup.grid._waypoints
    assert other._target_y==setup.grid._target_y


def test_command_has_no_default_time_limit():
    args=build_parser().parse_args(['--role','scout-expert','--pid','0'])
    assert args.duration_sec==0
    assert build_parser().parse_args(['--pid','0','--duration-sec','600']).duration_sec==600


def test_bad_time_limits_are_rejected():
    for value in ('-1','nan','inf'):
        with pytest.raises(SystemExit):
            build_parser().parse_args(['--pid','0','--duration-sec',value])


def test_explicit_opened_ids_recover_a_missed_f(setup):
    setup.snapshot['boxTimeList'][0]['boxPosition']['z']=1
    setup.step()
    setup.snapshot.update(boxesFound=1, totalTime=20, collectedBoxIds=[0])
    result=setup.step(101)
    assert result['phase']=='searching'
    assert setup.collected==[0]


def test_telemetry_wait_reports_missing_pose_and_stale_source_separately(setup):
    setup.snapshot['latestPositions'].pop('auvRotation')
    assert setup.step()['wait_reason']=='missing_auv_pose'
    setup.snapshot['latestPositions']['auvRotation']={'y':0}
    with patch('time.time',return_value=103):
        assert setup.controller.step(setup.snapshot,setup.capture)['wait_reason']=='stale_telemetry'
    setup.snapshot['curState']='titleScreen'
    assert setup.step()['wait_reason']=='game_not_searching'
