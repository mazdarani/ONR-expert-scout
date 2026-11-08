"""Choose the nearest unopened box from live world coordinates."""
import math


def valid_position(position):
    return (isinstance(position, dict) and all(
        isinstance(position.get(axis), (int, float)) and not isinstance(position[axis], bool)
        and math.isfinite(position[axis]) for axis in ('x', 'y', 'z')))


def valid_rotation(rotation):
    yaw = rotation.get('y') if isinstance(rotation, dict) else None
    return isinstance(yaw, (int, float)) and not isinstance(yaw, bool) and math.isfinite(yaw)


def distance(first, second):
    return math.dist([first[a] for a in ('x', 'y', 'z')], [second[a] for a in ('x', 'y', 'z')])


def nearest_box(position, boxes, collected=()):
    if not valid_position(position):
        return None
    candidates = [box for box in boxes if isinstance(box, dict)
                  and isinstance(box.get('boxID'), int) and not isinstance(box['boxID'], bool)
                  and box['boxID'] not in collected and valid_position(box.get('boxPosition'))]
    return min(candidates, key=lambda box: (distance(position, box['boxPosition']), box['boxID']), default=None)


def box_order(position, boxes, collected=()):
    """Preview center-to-center visit order; live selection uses the actual AUV pose."""
    opened = set(collected)
    order = []
    while (box := nearest_box(position, boxes, opened)) is not None:
        order.append(box['boxID'])
        opened.add(box['boxID'])
        position = box['boxPosition']
    return order
