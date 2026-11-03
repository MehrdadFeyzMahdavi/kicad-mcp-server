"""KiCad 10 checks for the Phase 8A board. Loads copies and does not save."""

import shutil
import sys
import tempfile
from pathlib import Path

_PYTHON_ROOT = Path(__file__).resolve().parent.parent
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))

import pcbnew

from kicad_api.placement import plan_led_switch, placed_parts, validate_placement, board_box

BASELINE = Path(
    r"C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7B-BASELINE\MCP-E2E-LED-P7B.kicad_pcb"
)
PLACED = Path(
    r"C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7B-PROJECT\MCP-E2E-LED-P7B.kicad_pcb"
)

ORIGINAL = {
    "D1": (20.0, 20.0),
    "J1": (45.0, 20.0),
    "J2": (70.0, 20.0),
    "Q1": (95.0, 20.0),
    "R1": (20.0, 45.0),
    "R2": (45.0, 45.0),
    "R3": (70.0, 45.0),
}
PLANNED = {
    "J1": (-21.73, -16.49, 0.0),
    "J2": (-21.73, -9.4, 0.0),
    "R1": (-17.48, -16.49, 0.0),
    "D1": (-13.52, -16.49, 180.0),
    "Q1": (-7.04, -16.49, 180.0),
    "R2": (-17.48, -9.4, 0.0),
    "R3": (-13.52, -9.4, 0.0),
}
NETS = {
    ("J1", "1"): "+5V",
    ("J1", "2"): "GND",
    ("J2", "1"): "/CTRL_IN",
    ("J2", "2"): "GND",
    ("R1", "1"): "+5V",
    ("R1", "2"): "/LED_A",
    ("D1", "1"): "/LED_K",
    ("D1", "2"): "/LED_A",
    ("Q1", "1"): "GND",
    ("Q1", "2"): "/BASE",
    ("Q1", "3"): "/LED_K",
    ("R2", "1"): "/CTRL_IN",
    ("R2", "2"): "/BASE",
    ("R3", "1"): "/BASE",
    ("R3", "2"): "GND",
}
PATHS = {
    "Q1": "/d95379df-973c-4d3f-9a6e-a4efdc2bfb81/f935c3be-3693-47d9-bd9f-390a03261218",
    "D1": "/d95379df-973c-4d3f-9a6e-a4efdc2bfb81/a8d5e263-f1e2-460a-92a4-d423d997b7fe",
    "R1": "/d95379df-973c-4d3f-9a6e-a4efdc2bfb81/f4ead3bf-3e20-4205-9a63-164ab2eaa010",
    "R2": "/d95379df-973c-4d3f-9a6e-a4efdc2bfb81/b17ac674-35ff-4b29-a2ef-5d089b2efb12",
    "R3": "/d95379df-973c-4d3f-9a6e-a4efdc2bfb81/d29483d0-1b97-40a6-a6ea-8522609ea8aa",
    "J1": "/d95379df-973c-4d3f-9a6e-a4efdc2bfb81/70fa8411-de67-4312-9e68-325c2588a66d",
    "J2": "/d95379df-973c-4d3f-9a6e-a4efdc2bfb81/d7d0d023-2756-44a7-b939-d1cb2d1d56bb",
}


def _load_copy(source: Path):
    folder = Path(tempfile.mkdtemp(prefix="phase8a-"))
    copy = folder / source.name
    shutil.copy2(source, copy)
    return pcbnew.LoadBoard(str(copy))


def _mm(value) -> float:
    return value / 1e6


def _courtyard(footprint) -> dict:
    layer = footprint.GetBoard().GetLayerID("F.CrtYd")
    points = []
    anchor = footprint.GetPosition()
    for item in footprint.GraphicalItems():
        if item.GetLayer() != layer:
            continue
        for point in (item.GetStart(), item.GetEnd()):
            points.append((_mm(point.x - anchor.x), _mm(point.y - anchor.y)))
    assert points, footprint.GetReference()
    return {
        "xmin": min(point[0] for point in points),
        "ymin": min(point[1] for point in points),
        "xmax": max(point[0] for point in points),
        "ymax": max(point[1] for point in points),
    }


def test_kicad_version_is_10():
    version = pcbnew.GetBuildVersion()
    assert version.startswith("10."), version


def test_baseline_copy_still_has_the_grid_and_a_valid_plan():
    board = _load_copy(BASELINE)
    courtyards = {}
    seen = set()
    for footprint in board.GetFootprints():
        reference = footprint.GetReference()
        seen.add(reference)
        assert abs(footprint.GetOrientationDegrees()) < 0.05
        expected = ORIGINAL[reference]
        assert abs(_mm(footprint.GetPosition().x) - expected[0]) < 0.01
        assert abs(_mm(footprint.GetPosition().y) - expected[1]) < 0.01
        courtyards[reference] = _courtyard(footprint)
    assert seen == set(ORIGINAL)
    plan = plan_led_switch(courtyards, edge_clearance_mm=1.5)
    assert plan["optimised"] is False
    parts = placed_parts(courtyards, plan["placements"])
    checked = validate_placement(
        parts,
        board_box(50, 40),
        edge_clearance_mm=1.5,
        courtyard_gap_mm=1.0,
        max_connected_span_mm=25.0,
    )
    assert checked["success"], checked["problems"]


def test_placed_board_outline_positions_and_nets():
    board = _load_copy(PLACED)
    assert len(list(board.GetTracks())) == 0
    edge = board.GetLayerID("Edge.Cuts")
    rectangles = [
        item
        for item in board.GetDrawings()
        if item.GetLayer() == edge and item.GetClass() == "PCB_SHAPE"
    ]
    assert len(rectangles) == 1
    shape = rectangles[0]
    assert abs(_mm(shape.GetStart().x) + 25) < 0.05
    assert abs(_mm(shape.GetStart().y) + 20) < 0.05
    assert abs(_mm(shape.GetEnd().x) - 25) < 0.05
    assert abs(_mm(shape.GetEnd().y) - 20) < 0.05
    pads = {}
    seen = set()
    for footprint in board.GetFootprints():
        reference = footprint.GetReference()
        seen.add(reference)
        x, y, rotation = PLANNED[reference]
        assert abs(_mm(footprint.GetPosition().x) - x) < 0.02
        assert abs(_mm(footprint.GetPosition().y) - y) < 0.02
        assert abs(footprint.GetOrientationDegrees() - rotation) < 0.05
        path = footprint.GetPath().AsString()
        assert path == PATHS[reference]
        for pad in footprint.Pads():
            pads[(reference, pad.GetNumber())] = pad.GetNetname()
    assert seen == set(PLANNED)
    assert pads == NETS


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
