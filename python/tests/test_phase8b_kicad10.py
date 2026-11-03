"""Read-only KiCad 10 check of the routed Phase 8B board. Loads a copy and does not save."""

import shutil
import sys
import tempfile
from pathlib import Path

_PYTHON_ROOT = Path(__file__).resolve().parent.parent
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))

import pcbnew

PLACED = Path(
    r"C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7B-PROJECT\MCP-E2E-LED-P7B.kicad_pcb"
)
SNAPSHOT = Path(
    r"C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P8A-PLACED\MCP-E2E-LED-P7B.kicad_pcb"
)
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
ANCHORS = {
    "J1": (-21.73, -16.49, 0.0),
    "J2": (-21.73, -9.4, 0.0),
    "R1": (-17.48, -16.49, 0.0),
    "D1": (-13.52, -16.49, 180.0),
    "Q1": (-7.04, -16.49, 180.0),
    "R2": (-17.48, -9.4, 0.0),
    "R3": (-13.52, -9.4, 0.0),
}


def _load(path: Path):
    folder = Path(tempfile.mkdtemp(prefix="phase8b-"))
    copy = folder / path.name
    shutil.copy2(path, copy)
    return pcbnew.LoadBoard(str(copy))


def test_routed_board_keeps_placement_and_assigns_every_track():
    board = _load(PLACED)
    assert pcbnew.GetBuildVersion().startswith("10.")
    pads = {}
    for footprint in board.GetFootprints():
        reference = footprint.GetReference()
        x, y, rotation = ANCHORS[reference]
        assert abs(footprint.GetPosition().x / 1e6 - x) < 0.02
        assert abs(footprint.GetPosition().y / 1e6 - y) < 0.02
        assert abs(footprint.GetOrientationDegrees() - rotation) < 0.05
        for pad in footprint.Pads():
            pads[(reference, pad.GetNumber())] = pad.GetNetname()
    assert pads == NETS
    tracks = [item for item in board.GetTracks() if item.GetClass() == "PCB_TRACK"]
    vias = [item for item in board.GetTracks() if item.GetClass() != "PCB_TRACK"]
    assert len(tracks) == 17
    assert vias == []
    names = {track.GetNetname() for track in tracks}
    assert names == {"+5V", "GND", "/LED_A", "/LED_K", "/CTRL_IN", "/BASE"}
    assert all(track.GetLayerName() == "F.Cu" for track in tracks)


def test_phase8a_snapshot_has_no_tracks():
    board = _load(SNAPSHOT)
    assert list(board.GetTracks()) == []


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
