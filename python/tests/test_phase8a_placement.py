"""Geometry tests for Phase 8A. These do not open a KiCad board."""

import sys
from pathlib import Path

_PYTHON_ROOT = Path(__file__).resolve().parent.parent
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))

from kicad_api.placement import (
    PlacementError,
    board_box,
    boxes_overlap,
    edge_clearance,
    local_box,
    outside_board,
    plan_led_switch,
    placed_parts,
    rotate_xy,
    separation,
    transform_box,
    validate_placement,
)

MEASURED = {
    "D1": {"xmin": -1.48, "ymin": -0.73, "xmax": 1.48, "ymax": 0.73},
    "J1": {"xmin": -1.77, "ymin": -1.77, "xmax": 1.77, "ymax": 4.32},
    "J2": {"xmin": -1.77, "ymin": -1.77, "xmax": 1.77, "ymax": 4.32},
    "Q1": {"xmin": -1.46, "ymin": -2.73, "xmax": 4.00, "ymax": 2.01},
    "R1": {"xmin": -1.48, "ymin": -0.73, "xmax": 1.48, "ymax": 0.73},
    "R2": {"xmin": -1.48, "ymin": -0.73, "xmax": 1.48, "ymax": 0.73},
    "R3": {"xmin": -1.48, "ymin": -0.73, "xmax": 1.48, "ymax": 0.73},
}

NETS = {
    "J1": ["+5V", "GND"],
    "R1": ["+5V", "LED_A"],
    "D1": ["LED_A", "LED_K"],
    "Q1": ["LED_K", "BASE", "GND"],
    "J2": ["CTRL_IN", "GND"],
    "R2": ["CTRL_IN", "BASE"],
    "R3": ["BASE", "GND"],
}


def test_rotation_180_mirrors_both_axes():
    rotated = rotate_xy(2.54, 0.0, 180)
    assert abs(rotated[0] + 2.54) < 1e-9
    assert abs(rotated[1]) < 1e-9
    box = transform_box(MEASURED["Q1"], 0, 0, 180)
    assert abs(box["xmin"] - (-4.00)) < 1e-9
    assert abs(box["xmax"] - 1.46) < 1e-9


def test_touching_edges_are_not_an_overlap():
    left = {"xmin": 0, "ymin": 0, "xmax": 1, "ymax": 1}
    right = {"xmin": 1, "ymin": 0, "xmax": 2, "ymax": 1}
    assert boxes_overlap(left, right) is False
    assert separation(left, right) == 0


def test_overlap_and_gap_are_distinct():
    left = {"xmin": 0, "ymin": 0, "xmax": 2, "ymax": 1}
    overlap = {"xmin": 1, "ymin": 0, "xmax": 3, "ymax": 1}
    apart = {"xmin": 2.2, "ymin": 0, "xmax": 3, "ymax": 1}
    assert boxes_overlap(left, overlap) is True
    assert separation(left, overlap) < 0
    assert boxes_overlap(left, apart) is False
    assert abs(separation(left, apart) - 0.2) < 1e-9


def test_edge_clearance_and_outside():
    board = board_box(50, 40)
    inside = {"xmin": -24, "ymin": -19, "xmax": 24, "ymax": 19}
    hanging = {"xmin": -26, "ymin": -1, "xmax": -20, "ymax": 1}
    assert abs(edge_clearance(inside, board) - 1.0) < 1e-9
    assert outside_board(hanging, board) is True
    assert edge_clearance(hanging, board) < 0


def test_local_box_removes_the_anchor():
    points = [(18.52, 44.27), (21.48, 45.73)]
    box = local_box(points, 20.0, 45.0, 0)
    assert abs(box["xmin"] - (-1.48)) < 1e-9
    assert abs(box["ymin"] - (-0.73)) < 1e-9


def test_led_switch_plan_meets_its_own_rules():
    plan = plan_led_switch(MEASURED)
    assert plan["optimised"] is False
    assert plan["placements"]["D1"]["rotation"] == 180
    assert plan["placements"]["Q1"]["rotation"] == 180
    parts = placed_parts(MEASURED, plan["placements"], NETS)
    result = validate_placement(
        parts,
        board_box(50, 40),
        edge_clearance_mm=0.5,
        courtyard_gap_mm=1.0,
        max_connected_span_mm=25.0,
    )
    assert result["problems"] == []
    assert result["success"] is True
    wider = plan_led_switch(MEASURED, edge_clearance_mm=1.5)
    wider_parts = placed_parts(MEASURED, wider["placements"], NETS)
    wider_result = validate_placement(
        wider_parts,
        board_box(50, 40),
        edge_clearance_mm=1.5,
        courtyard_gap_mm=1.0,
        max_connected_span_mm=25.0,
    )
    assert wider_result["success"] is True
    assert wider["placements"]["J1"]["y"] > plan["placements"]["J1"]["y"]


def test_duplicate_and_missing_courtyard_are_reported():
    board = board_box(50, 40)
    box = {"xmin": 0, "ymin": 0, "xmax": 1, "ymax": 1}
    result = validate_placement(
        [
            {"reference": "R1", "courtyard": box, "x": 0, "y": 0},
            {"reference": "R1", "courtyard": box, "x": 5, "y": 0},
            {"reference": "R2", "x": 0, "y": 0},
        ],
        board,
        max_connected_span_mm=None,
    )
    codes = {item["code"] for item in result["problems"]}
    assert "DUPLICATE_REFERENCE" in codes
    assert "MISSING_COURTYARD" in codes


def test_long_connection_is_reported_without_moving_anything():
    board = board_box(50, 40)
    result = validate_placement(
        [
            {
                "reference": "J1",
                "x": -20,
                "y": 0,
                "courtyard": {"xmin": -21, "ymin": -1, "xmax": -19, "ymax": 1},
                "nets": ["+5V"],
            },
            {
                "reference": "R1",
                "x": 20,
                "y": 0,
                "courtyard": {"xmin": 19, "ymin": -1, "xmax": 21, "ymax": 1},
                "nets": ["+5V"],
            },
        ],
        board,
        edge_clearance_mm=0.5,
        courtyard_gap_mm=0.25,
        max_connected_span_mm=25.0,
    )
    assert any(item["code"] == "LONG_CONNECTION" for item in result["problems"])


def test_other_component_sets_are_refused():
    try:
        plan_led_switch({"R1": MEASURED["R1"]})
    except PlacementError as failure:
        assert failure.code == "UNSUPPORTED_PLACEMENT"
    else:
        raise AssertionError("a partial component set was planned")


if __name__ == "__main__":
    import traceback

    passed = failed = 0
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        try:
            test()
        except Exception:
            failed += 1
            print(f"FAIL {test.__name__}")
            traceback.print_exc()
            continue
        passed += 1
        print(f"PASS {test.__name__}")
    print(f"passed={passed} failed={failed}")
    raise SystemExit(1 if failed else 0)
