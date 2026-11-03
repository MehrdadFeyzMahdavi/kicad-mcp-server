"""Phase 4 tests for nets, track identity, and absolute rotation.

These tests use fakes. They do not open or modify a KiCad editor document.
"""

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

os.environ["KICAD_BACKEND"] = "swig"
os.environ["KICAD_AUTO_LAUNCH"] = "false"

_PYTHON_ROOT = Path(__file__).resolve().parent.parent
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))

if "pcbnew" not in sys.modules or not isinstance(
    getattr(sys.modules.get("pcbnew"), "__file__", None), str
):
    _pcbnew = types.ModuleType("pcbnew")
    _pcbnew.__file__ = "pcbnew-test-stub"
    _pcbnew.GetBuildVersion = lambda: "10.0-test"
    _pcbnew.SaveBoard = MagicMock()
    _pcbnew.LoadBoard = MagicMock()

    def _pcbnew_getattr(name):
        value = MagicMock()
        setattr(_pcbnew, name, value)
        return value

    _pcbnew.__getattr__ = _pcbnew_getattr
    sys.modules["pcbnew"] = _pcbnew

from kicad_api.ipc_backend import IPCBoardAPI
from kicad_interface import KiCADInterface
from kipy.board import Board
from kipy.board_types import Net


class ProtoId:
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return f'value: "{self.value}"\n'


class StoredTrack:
    def __init__(self, ident, net_name):
        self.id = ProtoId(ident)
        self.net = types.SimpleNamespace(name=net_name)


class FakeBoard:
    def __init__(self, nets, forced_net=None, explode=False):
        self._nets = list(nets)
        self.forced_net = forced_net
        self.explode = explode
        self.tracks = []
        self.events = []

    def get_nets(self):
        return list(self._nets)

    def begin_commit(self):
        self.events.append("begin")
        return "commit"

    def drop_commit(self, commit):
        self.events.append("drop")

    def push_commit(self, commit, message):
        self.events.append(("push", message))

    def create_items(self, item):
        if self.explode:
            raise RuntimeError("create failed")
        name = item.net.name if self.forced_net is None else self.forced_net
        stored = StoredTrack("track-1", name)
        self.tracks.append(stored)
        self.events.append(("create", name))
        return [stored]

    def get_tracks(self):
        return list(self.tracks)

    def remove_items(self, items):
        gone = {item.id.value for item in items}
        self.tracks = [item for item in self.tracks if item.id.value not in gone]
        self.events.append(("remove", sorted(gone)))


def _api(board):
    api = IPCBoardAPI.__new__(IPCBoardAPI)
    api._board = board
    api._kicad = None
    api._notify = lambda *args, **kwargs: None
    api._current_commit = None
    return api


def _interface(api):
    interface = KiCADInterface.__new__(KiCADInterface)
    interface.ipc_board_api = api
    return interface


def test_kicad_10_board_has_no_create_net():
    assert getattr(Board, "create_net", None) is None


def test_add_net_existing_is_not_modified():
    board = FakeBoard([Net(name="GND")])
    result = _api(board).add_net("GND")
    assert result["success"] is False
    assert result["error"] == "ALREADY_EXISTS"
    assert result["net"]["name"] == "GND"
    assert result["net"]["identifier"] == "GND"
    assert board.events == []


def test_add_net_missing_is_unsupported():
    board = FakeBoard([Net(name="GND")])
    result = _api(board).add_net("PHASE4_NEW", net_class="Power")
    assert result["success"] is False
    assert result["error"] == "UNSUPPORTED_OPERATION"
    assert "No net was created" in result["message"]
    assert board.events == []
    assert [net.name for net in board.get_nets()] == ["GND"]


def test_add_net_requires_a_name():
    result = _api(FakeBoard([])).add_net("  ")
    assert result["success"] is False
    assert result["error"] == "INVALID_ARGUMENT"


def test_named_missing_net_does_not_create_a_track():
    board = FakeBoard([Net(name="GND")])
    result = _api(board).add_track(1, 2, 3, 2, net_name="PHASE4_MISSING")
    assert result["success"] is False
    assert result["error"] == "NET_NOT_FOUND"
    assert board.events == []
    assert board.tracks == []


def test_blank_net_does_not_create_a_track():
    board = FakeBoard([Net(name="GND")])
    result = _api(board).add_track(1, 2, 3, 2, net_name="  ")
    assert result["success"] is False
    assert result["error"] == "INVALID_ARGUMENT"
    assert board.events == []


def test_existing_net_is_verified_on_the_created_track():
    board = FakeBoard([Net(name="GND")])
    result = _api(board).add_track(10, 20, 11, 20, width=0.2, layer="F.Cu", net_name="GND")
    assert result["success"] is True
    assert result["id"] == "track-1"
    assert result["net"] == "GND"
    assert ("create", "GND") in board.events
    assert board.tracks[0].net.name == "GND"
    assert "drop" not in board.events


def test_net_mismatch_removes_the_track_and_is_not_success():
    board = FakeBoard([Net(name="GND")], forced_net="")
    result = _api(board).add_track(10, 20, 11, 20, net_name="GND")
    assert result["success"] is False
    assert result["error"] == "NET_MISMATCH"
    assert result["removed"] is True
    assert board.tracks == []
    assert ("remove", ["track-1"]) in board.events


def test_create_failure_drops_the_commit():
    board = FakeBoard([Net(name="GND")], explode=True)
    result = _api(board).add_track(10, 20, 11, 20, net_name="GND")
    assert result["success"] is False
    assert result["error"] == "IPC_ERROR"
    assert board.events == ["begin", "drop"]
    assert board.tracks == []


def test_route_trace_rejects_a_success_report_with_the_wrong_net():
    api = _api(FakeBoard([]))

    def add_track(**kwargs):
        return {"success": True, "id": "track-x", "net": ""}

    api.add_track = add_track
    result = _interface(api)._ipc_route_trace(
        {
            "start": {"x": 1, "y": 2},
            "end": {"x": 3, "y": 2},
            "layer": "F.Cu",
            "width": 0.2,
            "net": "GND",
        }
    )
    assert result["success"] is False
    assert result["error"] == "NET_MISMATCH"


def test_route_trace_requires_a_net_name():
    calls = []
    api = _api(FakeBoard([]))
    api.add_track = lambda **kwargs: calls.append(kwargs)
    result = _interface(api)._ipc_route_trace(
        {"start": {"x": 0, "y": 0}, "end": {"x": 1, "y": 0}, "layer": "F.Cu", "width": 0.2}
    )
    assert result["success"] is False
    assert result["error"] == "INVALID_ARGUMENT"
    assert calls == []


def test_item_ids_are_bare_uuids():
    ident = ProtoId("7d0e8b06-4fc1-43f5-b4e2-17261d151a01")
    point = types.SimpleNamespace(x=1_000_000, y=2_000_000)
    end = types.SimpleNamespace(x=3_000_000, y=2_000_000)
    track = types.SimpleNamespace(
        start=point,
        end=end,
        width=200_000,
        layer=3,
        net=types.SimpleNamespace(name="GND"),
        id=ident,
    )
    via = types.SimpleNamespace(
        position=point,
        diameter=800_000,
        drill_diameter=400_000,
        net=types.SimpleNamespace(name="GND"),
        type="through",
        id=ident,
    )
    zone = types.SimpleNamespace(
        name="zone",
        net=types.SimpleNamespace(name="GND"),
        priority=0,
        layers=["F.Cu"],
        filled=False,
        id=ident,
    )
    selected = types.SimpleNamespace(id=ident)
    board = FakeBoard([])
    board.get_tracks = lambda: [track]
    board.get_vias = lambda: [via]
    board.get_zones = lambda: [zone]
    board.get_selection = lambda: [selected]
    api = _api(board)
    assert api.get_tracks()[0]["id"] == ident.value
    assert "value:" not in api.get_tracks()[0]["id"]
    assert api.get_vias()[0]["id"] == ident.value
    assert api.get_zones()[0]["id"] == ident.value
    assert api.get_selection()[0]["id"] == ident.value


class Parts:
    def __init__(self, rotation):
        self.parts = [
            {
                "reference": "R_PHASE4",
                "rotation": rotation,
                "position": {"x": 10.0, "y": 20.0},
                "id": "fp-1",
                "footprint": "Resistors SMD:RESC2012X60N",
            }
        ]
        self.moves = []
        self.freeze = None

    def list_components(self):
        if self.freeze is not None and self.moves:
            shown = dict(self.parts[0])
            shown["rotation"] = self.freeze
            return [shown]
        return [dict(part) for part in self.parts]

    def move_component(self, reference, x, y, rotation=None):
        self.moves.append(rotation)
        if self.freeze is None:
            for part in self.parts:
                if part["reference"] == reference:
                    part["rotation"] = rotation
        return True


def test_rotate_sets_an_absolute_angle():
    parts = Parts(90)
    result = _interface(parts)._ipc_rotate_component(
        {"reference": "R_PHASE4", "angle": 180}
    )
    assert result["success"] is True
    assert result["newRotation"] == 180
    assert result["id"] == "fp-1"
    assert result["footprint"] == "Resistors SMD:RESC2012X60N"
    assert parts.moves == [180]


def test_rotate_zero_is_zero_rather_than_a_relative_noop():
    parts = Parts(90)
    result = _interface(parts)._ipc_rotate_component(
        {"reference": "R_PHASE4", "angle": 0}
    )
    assert result["success"] is True
    assert result["newRotation"] == 0
    assert parts.moves == [0]


def test_rotate_rejects_a_readback_mismatch():
    parts = Parts(90)
    parts.freeze = 12
    result = _interface(parts)._ipc_rotate_component(
        {"reference": "R_PHASE4", "angle": 180}
    )
    assert result["success"] is False
    assert result["error"] == "ROTATION_MISMATCH"
    assert parts.moves == [180, 90]


def test_rotate_missing_component_does_not_move():
    parts = Parts(0)
    result = _interface(parts)._ipc_rotate_component(
        {"reference": "R_MISSING", "angle": 90}
    )
    assert result["success"] is False
    assert parts.moves == []


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
