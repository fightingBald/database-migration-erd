"""Orthogonal boundary routing must never cut through occupied rectangles."""

from itertools import pairwise

import pytest

from erd_generator.diagram_routing import Rect, route, segment_clear


def test_routes_around_an_obstacle_with_exact_endpoints():
    obstacles = [Rect(40, -20, 30, 40)]
    points = route((0, 0), (100, 0), obstacles)
    assert points[0] == (0, 0)
    assert points[-1] == (100, 0)
    assert all(segment_clear(a, b, obstacles) for a, b in pairwise(points))
    assert any(y != 0 for _, y in points)


def test_routing_is_deterministic_and_handles_a_narrow_corridor():
    obstacles = [Rect(20, -40, 60, 35), Rect(20, 5, 60, 35)]
    assert route((0, 0), (100, 0), obstacles) == [(0, 0), (100, 0)]
    assert route((0, 0), (100, 0), obstacles[::-1]) == route(
        (0, 0), (100, 0), obstacles
    )


def test_unreachable_endpoint_is_reported_instead_of_drawing_through_a_table():
    with pytest.raises(ValueError, match="blocked endpoint"):
        route((50, 0), (100, 0), [Rect(40, -20, 30, 40)])


def test_segments_on_obstacle_boundaries_are_allowed_but_interior_is_not():
    obstacles = [Rect(40, -20, 30, 40)]
    assert segment_clear((0, -20), (100, -20), obstacles)
    assert not segment_clear((0, 0), (100, 0), obstacles)
    assert not segment_clear((0, 0), (100, 1), obstacles)


def test_crossing_avoidance_respects_a_hard_length_budget():
    occupied = [[(50, -20), (50, 20)]]
    points = route((0, 0), (100, 0), [], occupied=occupied, max_length=110)
    assert sum(abs(a[0] - b[0]) + abs(a[1] - b[1]) for a, b in pairwise(points)) <= 110
    with pytest.raises(ValueError, match="no obstacle-free route"):
        route((0, 0), (100, 0), [], max_length=99)
