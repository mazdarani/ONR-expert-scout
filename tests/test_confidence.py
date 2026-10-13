from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from expert_scout.actuator import KeyboardActuator, DryRunActuator
from expert_scout.confidence import ConfidenceSender, confidence_level
from expert_scout.config import Config


@pytest.mark.parametrize('score,level', [
    (.25, 'low'), (.7199, 'low'), (.72, 'medium'), (.8199, 'medium'),
    (.82, 'high'), (1., 'high'), (.24, None), (-1, None), (1.1, None),
    (None, None), (True, None), (float('nan'), None),
])
def test_exact_score_boundaries(score, level):
    assert confidence_level(score, Config()) == level


@pytest.fixture
def feedback():
    keys = []
    actuator = SimpleNamespace(tap_key=lambda key: (keys.append(key) or {'key': key, 'sent': True}))
    capture = SimpleNamespace(detections=[{'class_name': 'box', 'confidence': .8}])
    # These values would have blocked the former target/proximity sender.
    record = {'phase': 'searching', 'target_box_id': None, 'target_detection': None}
    snapshot = {'curState': 'SAGAT', '_sourceMtime': 0, 'latestPositions': {}, 'boxTimeList': []}
    return SimpleNamespace(sender=ConfidenceSender(Config(), actuator), keys=keys, record=record,
                           snapshot=snapshot, capture=capture)


def test_detection_sends_immediately_without_target_or_telemetry_conditions(feedback):
    result = feedback.sender.update(feedback.record, feedback.snapshot, 100, feedback.capture)
    assert result['score'] == .8
    assert result['level'] == 'medium'
    assert result['key'] == 'shift+1'
    assert result['sent']
    assert feedback.keys == ['shift+1']


def test_each_detected_frame_sends_a_key(feedback):
    feedback.sender.update(feedback.record, feedback.snapshot, 100, feedback.capture)
    feedback.sender.update(feedback.record, feedback.snapshot, 100.01, feedback.capture)
    assert feedback.keys == ['shift+1', 'shift+1']


def test_highest_confidence_box_in_a_frame_selects_the_key(feedback):
    feedback.capture.detections.extend([
        {'class_name': 'crate', 'confidence': .95},
        {'class_name': 'box', 'confidence': .5},
    ])
    result = feedback.sender.update(feedback.record, feedback.snapshot, 100, feedback.capture)
    assert result['level'] == 'high'
    assert feedback.keys == ['ctrl+1']


@pytest.mark.parametrize('detections', [
    [], [{'class_name': 'fish', 'confidence': .99}], [{'class_name': 'box', 'confidence': .24}],
])
def test_non_box_or_below_threshold_detection_does_not_send(feedback, detections):
    feedback.capture.detections = detections
    result = feedback.sender.update(feedback.record, feedback.snapshot, 100, feedback.capture)
    assert result['reason'] == 'no_valid_yolo_box'
    assert feedback.keys == []


def test_dry_run_reports_key_without_claiming_it_was_sent(feedback):
    feedback.sender.actuator = DryRunActuator()
    result = feedback.sender.update(feedback.record, feedback.snapshot, 100, feedback.capture)
    assert result['key'] == 'shift+1'
    assert not result['sent']
    assert result['actuation']['would_send']


@pytest.mark.parametrize('name,modifier', [('1', None), ('shift+1', 'shift'), ('ctrl+1', 'ctrl')])
def test_top_row_number_chords_press_modifiers_first_and_release_last(name, modifier):
    events = []
    keyboard = SimpleNamespace(press=lambda key: events.append(('press', key)),
                               release=lambda key: events.append(('release', key)))
    actuator = KeyboardActuator(tap_duration=0, keyboard=keyboard)
    with patch('expert_scout.actuator.sys.platform', 'win32'):
        assert actuator.tap_key(name)['sent']
    digit = ('vk', 0x31)
    expected = [('press', digit), ('release', digit)]
    if modifier:
        expected = [('press', modifier), *expected, ('release', modifier)]
    assert events == expected
    assert ('vk', 0x61) not in [key for _, key in events]


@pytest.mark.parametrize('name,modifier', [('shift+1', 'shift'), ('ctrl+1', 'ctrl')])
def test_modifier_is_released_when_number_press_fails(name, modifier):
    events = []

    def press(key):
        events.append(('press', key))
        if key == ('vk', 0x31):
            raise RuntimeError('input failed')

    keyboard = SimpleNamespace(press=press, release=lambda key: events.append(('release', key)))
    actuator = KeyboardActuator(tap_duration=0, keyboard=keyboard)
    with patch('expert_scout.actuator.sys.platform', 'win32'), pytest.raises(RuntimeError):
        actuator.tap_key(name)
    assert events[-2:] == [('release', ('vk', 0x31)), ('release', modifier)]


def test_modifier_is_released_even_when_number_release_fails():
    events = []

    def release(key):
        events.append(('release', key))
        if key == ('vk', 0x31):
            raise RuntimeError('release failed')

    keyboard = SimpleNamespace(press=lambda key: None, release=release)
    actuator = KeyboardActuator(tap_duration=0, keyboard=keyboard)
    with patch('expert_scout.actuator.sys.platform', 'win32'), pytest.raises(RuntimeError):
        actuator.tap_key('ctrl+1')
    assert events == [('release', ('vk', 0x31)), ('release', 'ctrl')]


@pytest.mark.parametrize('medium,high', [(.25, .82), (.82, .72), (.72, .72), (.72, 1.1), (float('nan'), .82)])
def test_invalid_category_configuration_is_rejected(medium, high):
    with pytest.raises(ValueError):
        replace(Config(), medium_confidence=medium, high_confidence=high).validate()
