import json
import math
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from expert_scout.approach import OracleBoxNavigator
from expert_scout.config import Config
from expert_scout.controller import ExpertController
from expert_scout.grid import GridSearchNavigator
from expert_scout.maps import load_search_areas, map_name
from expert_scout.matching import match_detections
from expert_scout.state import AtomicState
from expert_scout.vision import Capture

ROOT = Path(__file__).resolve().parents[1]
POSITIONS = json.loads((Path(__file__).parent / 'fixtures/ONRScubaCFF_maps.json').read_text())
CASES = [(name, box) for name, boxes in POSITIONS.items() for box in boxes]


@pytest.mark.parametrize('value,name',[(0,'training'),(1,'map1'),(2,'map2'),('training','training'),('Map 1','map1'),
                                      ('MAP2','map2'),('TutorialMap','training'),(3,None),(True,None),('unknown',None)])
def test_map_identity_matches_build_enum_and_names(value,name):
    assert map_name({'mapType':value})==name


def test_map_string_is_a_fallback_and_explicit_override_is_supported():
    assert map_name({'mapString':'map2'})=='map2'
    assert map_name({},'map1')=='map1'
    assert map_name({'mapType':2},'training')=='training'
    assert map_name({'mapType':99,'mapString':'map1'}) is None


@pytest.mark.parametrize('name,box',CASES)
def test_search_area_contains_every_box_from_the_build(name,box):
    area=load_search_areas(ROOT/'configs/maps.json')[name]
    point=box['position']
    assert area.x_min <= point['x'] <= area.x_max
    assert area.z_min <= point['z'] <= area.z_max


def test_map2_has_targets_outside_the_old_grid():
    outside=[box['id'] for box in POSITIONS['map2'] if not (-10<=box['position']['x']<=55 and -40<=box['position']['z']<=60)]
    assert outside==[0,4]


@pytest.mark.parametrize('name,box',CASES)
def test_actual_new_box_positions_match_yolo_from_world_yaw(name,box):
    target=box['position']
    yaw=math.degrees(math.atan2(target['x'],target['z'])) % 360
    snapshot={'latestPositions':{'auvPosition':{'x':0,'y':-23.36,'z':0},'auvRotation':{'y':yaw}},
              'boxTimeList':[{'boxID':b['id'],'boxPosition':b['position']} for b in POSITIONS[name]]}
    detection={'xywh':[500,300,100,100],'confidence':.9,'class_name':'box'}
    matches=match_detections(snapshot,[detection],1000,Config())
    assert matches[0]['box_id']==box['id']


@pytest.fixture
def run():
    state=AtomicState()
    collected=[]
    config=Config()
    grid=GridSearchNavigator(state,'scout',collected,lambda role:None,randomize_route=True,
                             waypoint_jitter=2.5,depth_jitter=1.5,seed=123)
    approach=OracleBoxNavigator(state,'scout',collected,lambda role:None,lambda box_id:None,
                                 collection_distance=1.5,yaw_threshold=.3)
    areas=load_search_areas(ROOT/'configs/maps.json')
    controller=ExpertController(config,grid,approach,collected,areas)
    snapshot={'curState':'searching','mapType':1,'totalTime':10,'boxesFound':0,'_sourceMtime':100,
              'latestPositions':{'auvPosition':{'x':0,'y':-23.36,'z':0},'auvRotation':{'y':0},
                                 'diverPosition':{'x':0,'y':-23.36,'z':0}},
              'boxTimeList':[{'boxID':b['id'],'boxPosition':b['position'],'findTime':10} for b in POSITIONS['map1']]}
    def step(now=100,frame=None):
        snapshot['_sourceMtime']=now
        state.update(snapshot)
        with patch('time.time',return_value=now):
            return controller.step(snapshot,frame)
    return SimpleNamespace(state=state,grid=grid,approach=approach,controller=controller,snapshot=snapshot,
                           collected=collected,areas=areas,step=step)


def test_map_is_automatically_selected_and_reported(run):
    record=run.step()
    assert record['map_name']=='map1'
    assert record['search_bounds']==run.areas['map1'].to_dict()
    assert record['action'].source=='grid'
    for waypoint in run.grid._waypoints:
        assert run.areas['map1'].x_min<=waypoint['x']<=run.areas['map1'].x_max
        assert run.areas['map1'].z_min<=waypoint['z']<=run.areas['map1'].z_max


def test_grid_route_does_not_depend_on_known_box_positions(run):
    run.step()
    original=list(run.grid._waypoints)
    run.snapshot['boxTimeList']=[]
    run.step(100.1)
    assert run.grid._waypoints==original


def test_unknown_map_holds_motion_until_it_is_known(run):
    run.snapshot['mapType']=99
    record=run.step()
    assert record['phase']=='waiting_for_map'
    assert record['action'].is_empty()
    assert run.grid._waypoints==[]
    run.snapshot['mapType']=2
    assert run.step(100.1)['action'].source=='grid'


def test_explicit_map_override_works_without_map_telemetry(run):
    del run.snapshot['mapType']
    run.controller.map_override='training'
    assert run.step()['map_name']=='training'


def test_map_switch_clears_targets_route_and_reused_opened_ids(run):
    run.snapshot['collectedBoxIds']=[0]
    run.step()
    assert run.collected==[0]
    run.controller.target_id=1
    run.controller.phase='approaching'
    run.approach.set_target_box(1)
    run.approach._get_next_box()
    run.snapshot.pop('collectedBoxIds')
    run.snapshot['mapType']=2
    run.snapshot['totalTime']=11
    run.snapshot['boxTimeList']=[{'boxID':b['id'],'boxPosition':b['position'],'findTime':11} for b in POSITIONS['map2']]
    record=run.step(101)
    assert record['map_name']=='map2'
    assert run.collected==[]
    assert run.grid._excluded_areas==[]
    assert run.controller.target_id is None
    assert run.approach.target_box is None
    assert record['phase']=='searching'


def test_restart_on_same_map_clears_old_collection_history(run):
    run.snapshot['collectedBoxIds']=[0]
    run.step()
    del run.snapshot['collectedBoxIds']
    run.snapshot['totalTime']=0
    assert run.step(101)['collected_box_ids']==[]


@pytest.mark.parametrize('name,box',CASES)
def test_coordinate_approach_uses_new_layout_and_arrives_at_each_box(run,name,box):
    target=box['position']
    dx,dz=target['x'],target['z']
    run.snapshot['mapType']={'training':0,'map1':1,'map2':2}[name]
    run.snapshot['boxTimeList']=[{'boxID':b['id'],'boxPosition':b['position'],'findTime':10} for b in POSITIONS[name]]
    run.snapshot['latestPositions']['auvRotation']['y']=math.degrees(math.atan2(dx,dz)) % 360
    detection={'xywh':[500,300,100,100],'class_name':'box','confidence':.9}
    frame=Capture(None,[detection],100,1000,600)
    record=run.step(frame=frame)
    assert record['phase']=='approaching'
    assert record['target_box_id']==box['id']
    assert record['action'].forward
    # No static coordinate table: the next pose is supplied by telemetry.
    run.snapshot['latestPositions']['auvPosition']={'x':target['x'],'y':target['y']+1,'z':target['z']}
    frame.timestamp=100.1
    record=run.step(100.1,frame)
    assert record['event']=='box_reached'
    assert record['phase']=='waiting_for_diver'
    assert run.collected==[]


def test_approach_refreshes_position_even_when_box_id_is_unchanged(run):
    run.snapshot['boxTimeList']=[{'boxID':0,'boxPosition':{'x':0,'y':-23.36,'z':10}}]
    run.state.update(run.snapshot)
    run.approach.set_target_box(0)
    assert run.approach.action().forward
    run.snapshot['boxTimeList'][0]['boxPosition']={'x':-10,'y':-23.36,'z':0}
    run.state.update(run.snapshot)
    action=run.approach.action()
    assert action.yaw_left
    assert not action.yaw_right
    assert run.approach.target_box['position']['x']==-10


def test_invalid_boundary_profile_is_rejected(tmp_path):
    values=json.loads((ROOT/'configs/maps.json').read_text())
    values['boundary_clearance_m']=1000
    path=tmp_path/'maps.json';path.write_text(json.dumps(values))
    with pytest.raises(ValueError):
        load_search_areas(path)


def test_new_trial_on_same_map_resets_ids_even_if_global_clock_does_not_restart(run):
    run.snapshot['collectedBoxIds']=[0]
    run.step()
    del run.snapshot['collectedBoxIds']
    run.snapshot['curState']='titleScreen'
    run.step(101)
    run.snapshot['curState']='searching'
    run.snapshot['totalTime']=12
    record=run.step(102)
    assert record['collected_box_ids']==[]
    assert record['map_epoch']==2


def test_camera_frame_from_previous_map_cannot_trigger_new_target(run):
    run.snapshot['latestPositions']['auvRotation']['y']=math.degrees(math.atan2(
        POSITIONS['map1'][0]['position']['x'],POSITIONS['map1'][0]['position']['z'])) % 360
    frame=Capture(None,[{'xywh':[500,300,100,100],'class_name':'box','confidence':.9}],99.9,1000,600)
    assert run.step(100,frame)['phase']=='searching'
    frame.timestamp=100.1
    assert run.step(100.1,frame)['phase']=='approaching'


def test_sagat_does_not_reset_map_or_opened_history(run):
    run.snapshot['collectedBoxIds']=[0]
    run.step()
    run.snapshot['curState']='sagat'
    run.step(101)
    run.snapshot['curState']='searching'
    run.snapshot['totalTime']=11
    record=run.step(102)
    assert record['map_epoch']==1
    assert record['collected_box_ids']==[0]
