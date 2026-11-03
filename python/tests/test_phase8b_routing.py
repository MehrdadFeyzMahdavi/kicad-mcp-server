"""Routing checks. These do not open a KiCad board."""

import sys
from pathlib import Path

_PYTHON_ROOT = Path(__file__).resolve().parent.parent
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))

from kicad_api.routing_checks import LED_SWITCH_LINKS, validate_connection

PADS = [
    {"reference": "D1", "number": "1", "net": "/LED_K", "x": -12.732, "y": -16.490, "width": 0.875, "height": 0.950},
    {"reference": "D1", "number": "2", "net": "/LED_A", "x": -14.307, "y": -16.490, "width": 0.875, "height": 0.950},
    {"reference": "J1", "number": "1", "net": "+5V", "x": -21.730, "y": -16.490, "width": 1.700, "height": 1.700},
    {"reference": "J1", "number": "2", "net": "GND", "x": -21.730, "y": -13.950, "width": 1.700, "height": 1.700},
    {"reference": "J2", "number": "1", "net": "/CTRL_IN", "x": -21.730, "y": -9.400, "width": 1.700, "height": 1.700},
    {"reference": "J2", "number": "2", "net": "GND", "x": -21.730, "y": -6.860, "width": 1.700, "height": 1.700},
    {"reference": "Q1", "number": "1", "net": "GND", "x": -7.040, "y": -16.490, "width": 1.050, "height": 1.500},
    {"reference": "Q1", "number": "2", "net": "/BASE", "x": -8.310, "y": -16.490, "width": 1.050, "height": 1.500},
    {"reference": "Q1", "number": "3", "net": "/LED_K", "x": -9.580, "y": -16.490, "width": 1.050, "height": 1.500},
    {"reference": "R1", "number": "1", "net": "+5V", "x": -18.305, "y": -16.490, "width": 0.800, "height": 0.950},
    {"reference": "R1", "number": "2", "net": "/LED_A", "x": -16.655, "y": -16.490, "width": 0.800, "height": 0.950},
    {"reference": "R2", "number": "1", "net": "/CTRL_IN", "x": -18.305, "y": -9.400, "width": 0.800, "height": 0.950},
    {"reference": "R2", "number": "2", "net": "/BASE", "x": -16.655, "y": -9.400, "width": 0.800, "height": 0.950},
    {"reference": "R3", "number": "1", "net": "/BASE", "x": -14.345, "y": -9.400, "width": 0.800, "height": 0.950},
    {"reference": "R3", "number": "2", "net": "GND", "x": -12.695, "y": -9.400, "width": 0.800, "height": 0.950},
]
BOARD = {"xmin": -25.0, "ymin": -20.0, "xmax": 25.0, "ymax": 20.0}


def _request(**overrides):
    request = {
        "sourceRef": "J1",
        "sourcePad": "1",
        "destinationRef": "R1",
        "destinationPad": "1",
        "net": "+5V",
        "width": 0.40,
        "layer": "F.Cu",
        "clearance": 0.2,
    }
    request.update(overrides)
    return request


def test_same_net_direct_route():
    result = validate_connection(_request(), PADS, [], BOARD)
    assert result["success"] is True
    assert result["optimised"] is False
    assert result["kind"] == "direct"
    assert result["net"] == "+5V"
    assert len(result["segments"]) == 1


def test_different_net_is_rejected():
    result = validate_connection(_request(net="GND"), PADS, [], BOARD)
    assert result["success"] is False
    assert result["error"] == "NET_MISMATCH"
    assert result["segments"] == []


def test_missing_pad_is_rejected():
    result = validate_connection(_request(destinationPad="9"), PADS, [], BOARD)
    assert result["error"] == "MISSING_PAD"


def test_duplicate_connection_is_rejected():
    first = validate_connection(_request(), PADS, [], BOARD)
    tracks = [
        {
            "net": "+5V",
            "start": first["segments"][0]["start"],
            "end": first["segments"][0]["end"],
        }
    ]
    result = validate_connection(_request(), PADS, tracks, BOARD)
    assert result["error"] == "DUPLICATE_CONNECTION"


def test_invalid_width_is_rejected():
    for width in (0, -0.25, 0.05):
        result = validate_connection(_request(width=width), PADS, [], BOARD)
        assert result["error"] == "INVALID_WIDTH", width
        assert result["segments"] == []


def test_unsupported_layer_is_rejected():
    result = validate_connection(_request(layer="F.SilkS"), PADS, [], BOARD)
    assert result["error"] == "UNSUPPORTED_LAYER"


def test_clearance_conflict_is_reported_without_segments():
    blocked = [
        {"reference": "A", "number": "1", "net": "N", "x": 0.0, "y": 0.0, "width": 1.0, "height": 1.0},
        {"reference": "B", "number": "1", "net": "N", "x": 10.0, "y": 0.0, "width": 1.0, "height": 1.0},
        {"reference": "C", "number": "1", "net": "OTHER", "x": 5.0, "y": 0.0, "width": 30.0, "height": 30.0},
    ]
    tight = {"xmin": -1.0, "ymin": -2.0, "xmax": 11.0, "ymax": 2.0}
    result = validate_connection(
        _request(sourceRef="A", sourcePad="1", destinationRef="B", destinationPad="1", net="N", width=0.25),
        blocked,
        [],
        tight,
    )
    assert result["success"] is False
    assert result["error"] == "CLEARANCE_CONFLICT"
    assert result["segments"] == []


def test_led_switch_links_cover_every_net_without_a_direct_short():
    tracks = []
    kinds = {}
    for source_ref, source_pad, dest_ref, dest_pad, net, width in LED_SWITCH_LINKS:
        result = validate_connection(
            _request(
                sourceRef=source_ref,
                sourcePad=source_pad,
                destinationRef=dest_ref,
                destinationPad=dest_pad,
                net=net,
                width=width,
            ),
            PADS,
            tracks,
            BOARD,
        )
        assert result["success"], (source_ref, source_pad, dest_ref, dest_pad, result)
        kinds[(source_ref, dest_ref, net)] = result["kind"]
        tracks.extend(
            {"net": net, "start": segment["start"], "end": segment["end"]}
            for segment in result["segments"]
        )
    assert kinds[("J1", "J2", "GND")] != "direct"
    assert {link[4] for link in LED_SWITCH_LINKS} == {"+5V", "/LED_A", "/LED_K", "/CTRL_IN", "/BASE", "GND"}


def test_foreign_track_is_not_crossed():
    blocked = {
        "net": "/CTRL_IN",
        "width": 0.25,
        "start": {"x": -21.730, "y": -9.400},
        "end": {"x": -18.305, "y": -9.400},
    }
    result = validate_connection(
        _request(
            sourceRef="J1",
            sourcePad="2",
            destinationRef="J2",
            destinationPad="2",
            net="GND",
            width=0.40,
        ),
        PADS,
        [blocked],
        BOARD,
    )
    assert result["success"] is True
    for segment in result["segments"]:
        xs = (segment["start"]["x"], segment["end"]["x"])
        ys = (segment["start"]["y"], segment["end"]["y"])
        crosses = min(xs) < -18.305 and max(xs) > -21.730 and min(ys) < -9.400 < max(ys)
        assert not crosses


def test_failed_check_drops_the_commit():
    calls = []

    class Commit:
        def __init__(self):
            self.state = "open"

    class Board:
        def begin_commit(self):
            commit = Commit()
            calls.append(("begin", commit))
            return commit

        def drop_commit(self, commit):
            commit.state = "dropped"
            calls.append(("drop", commit))

        def push_commit(self, commit, message):
            commit.state = "pushed"
            calls.append(("push", message))

    board = Board()
    commit = board.begin_commit()
    check = validate_connection(_request(net="GND"), PADS, [], BOARD)
    if not check["success"]:
        board.drop_commit(commit)
    else:
        board.push_commit(commit, "route")
    assert calls[-1][0] == "drop"
    assert commit.state == "dropped"


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
