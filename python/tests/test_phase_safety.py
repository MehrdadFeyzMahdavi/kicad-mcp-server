"""Safety-policy tests. These use temporary files and mocks.

They do not open, load, or modify a KiCad editor document.
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

# Keep the tests off the real pcbnew module. Loading it does not open the
# editor board, but these tests must not be able to save through it.
# A MagicMock cannot expose __file__ on this Python, so use a module stub.
if "pcbnew" not in sys.modules or not isinstance(getattr(sys.modules.get("pcbnew"), "__file__", None), str):
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

import inspect

try:
    import pytest
except ImportError:  # KiCad's bundled Python does not ship pytest.
    class _Skip(Exception):
        pass

    class _Approx:
        def __init__(self, value):
            self.value = value

        def __eq__(self, other):
            return abs(float(other) - float(self.value)) <= 1e-9

    class _Mark:
        def unit(self, obj):
            return obj

    class pytest:  # noqa: N801 - stand-in for the real module
        mark = _Mark()

        @staticmethod
        def approx(value):
            return _Approx(value)

        @staticmethod
        def importorskip(name):
            try:
                return __import__(name)
            except ImportError as exc:
                raise _Skip(name) from exc

from kicad_api.ipc_backend import IPCBoardAPI
from kicad_api.pcb_safety import (
    IPC_UNAVAILABLE_ERROR,
    IPC_UNAVAILABLE_MESSAGE,
    evaluate_pcb_file_access,
    kicad_lock_candidates,
    lock_file_present,
    outline_primitives,
)
from kicad_interface import KiCADInterface, pcbnew


class _Id:
    def __init__(self, value):
        self.value = value


class _Net:
    def __init__(self, name):
        self.name = name


class _Point:
    def __init__(self, x_nm, y_nm):
        self.x = x_nm
        self.y = y_nm


class _Track:
    def __init__(self, ident, net="GND", layer="F.Cu", start=(0, 0), end=(1_000_000, 0)):
        self.id = _Id(ident)
        self.net = _Net(net)
        self.layer = layer
        self.start = _Point(*start)
        self.end = _Point(*end)


class _Via:
    def __init__(self, ident, net="GND", x_nm=0, y_nm=0):
        self.id = _Id(ident)
        self.net = _Net(net)
        self.position = _Point(x_nm, y_nm)


class _CommitBoard:
    def __init__(self, tracks=None, vias=None):
        self.tracks = list(tracks or [])
        self.vias = list(vias or [])
        self.events = []
        self.shapes = []
        self.created = []

    def get_tracks(self):
        return list(self.tracks)

    def get_vias(self):
        return list(self.vias)

    def get_shapes(self):
        return list(self.shapes)

    def begin_commit(self):
        self.events.append("begin")
        return "commit"

    def push_commit(self, commit, message):
        self.events.append(("push", message))

    def drop_commit(self, commit):
        self.events.append("drop")

    def remove_items(self, items):
        self.events.append(("remove", [item.id.value for item in items]))
        gone = {id(item) for item in items}
        self.tracks = [item for item in self.tracks if id(item) not in gone]
        self.vias = [item for item in self.vias if id(item) not in gone]
        self.shapes = [item for item in self.shapes if id(item) not in gone]

    def create_items(self, items):
        created = []
        for index, _item in enumerate(items):
            created.append(_Track(f"outline-{index}"))
        self.created = list(created)
        self.shapes.extend(created)
        self.events.append(("create", len(items)))
        return created


def _api(board):
    api = IPCBoardAPI.__new__(IPCBoardAPI)
    api._board = board
    api._kicad = None
    api._notify = lambda *args, **kwargs: None
    api._current_commit = None
    return api


def _interface():
    interface = KiCADInterface.__new__(KiCADInterface)
    interface.board = None
    interface.use_ipc = False
    interface.ipc_board_api = None
    interface.command_routes = {}
    interface._offline_owned_pcb_paths = set()
    interface._live_paths_unknown = False
    interface.project_commands = type("Project", (), {"board": None})()
    interface.routing_commands = type(
        "Routing",
        (),
        {"delete_trace": lambda self, params: (_ for _ in ()).throw(AssertionError("SWIG delete_trace"))},
    )()
    interface.board_commands = type(
        "Board",
        (),
        {
            "add_board_outline": lambda self, params: (_ for _ in ()).throw(
                AssertionError("SWIG add_board_outline")
            )
        },
    )()
    return interface


def _board_file(tmp_path: Path, name="offline.kicad_pcb") -> str:
    path = tmp_path / name
    path.write_text("(kicad_pcb (version 20240108))", encoding="utf-8")
    return str(path)


@pytest.mark.unit
class TestFileOwnership:
    def test_lock_file_blocks_overwrite(self, tmp_path):
        board = _board_file(tmp_path)
        lock = kicad_lock_candidates(board)[0]
        lock.write_text("locked", encoding="utf-8")
        assert lock_file_present(board) == str(lock)
        decision = evaluate_pcb_file_access(
            board,
            live_paths=[],
            locked=True,
            use_ipc=False,
            purpose="explicit_file",
            owned=True,
        )
        assert decision["allow"] is False
        assert decision["error"] == "EDITOR_OWNS_FILE"
        assert decision["reason"] == "lock_file"

    def test_live_editor_path_blocks_load(self, tmp_path):
        board = _board_file(tmp_path)
        decision = evaluate_pcb_file_access(
            board,
            live_paths=[board],
            locked=False,
            use_ipc=True,
            purpose="explicit_file",
            owned=True,
        )
        assert decision["allow"] is False
        assert decision["reason"] == "live_editor_document"

    def test_ipc_mode_blocks_autosave_of_a_different_file(self, tmp_path):
        board = _board_file(tmp_path)
        decision = evaluate_pcb_file_access(
            board,
            live_paths=[],
            locked=False,
            use_ipc=True,
            purpose="autosave",
            owned=True,
        )
        assert decision["allow"] is False
        assert decision["error"] == "LIVE_SESSION"

    def test_offline_owned_autosave_is_allowed(self, tmp_path):
        board = _board_file(tmp_path)
        decision = evaluate_pcb_file_access(
            board,
            live_paths=[],
            locked=False,
            use_ipc=False,
            purpose="autosave",
            owned=True,
        )
        assert decision["allow"] is True

    def test_unowned_autosave_is_refused(self, tmp_path):
        board = _board_file(tmp_path)
        decision = evaluate_pcb_file_access(
            board,
            live_paths=[],
            locked=False,
            use_ipc=False,
            purpose="autosave",
            owned=False,
        )
        assert decision["error"] == "FILE_NOT_OWNED"

    def test_explicit_create_of_a_different_file_stays_available(self, tmp_path):
        board = _board_file(tmp_path, "new-project.kicad_pcb")
        decision = evaluate_pcb_file_access(
            board,
            live_paths=[_board_file(tmp_path, "editor.kicad_pcb")],
            locked=False,
            use_ipc=True,
            purpose="explicit_file",
            owned=False,
        )
        assert decision["allow"] is True

    def test_unknown_editor_state_refuses_the_write(self, tmp_path):
        decision = evaluate_pcb_file_access(
            _board_file(tmp_path),
            live_paths=[],
            locked=False,
            use_ipc=False,
            purpose="explicit_file",
            owned=True,
            live_paths_unknown=True,
        )
        assert decision["error"] == "EDITOR_STATE_UNKNOWN"


@pytest.mark.unit
class TestOutlineGeometry:
    def test_rectangle_is_one_ipc_primitive(self):
        result = outline_primitives(
            {"shape": "rectangle", "width": 10, "height": 20, "x": 1, "y": 2, "unit": "mm"}
        )
        assert result["success"] is True
        assert result["primitives"] == [
            {"type": "rectangle", "x": 1, "y": 2, "width": 10, "height": 20}
        ]

    def test_inch_rectangle_converts_to_millimetres(self):
        result = outline_primitives(
            {"shape": "rectangle", "width": 1, "height": 2, "x": 0, "y": 0, "unit": "inch"}
        )
        primitive = result["primitives"][0]
        assert primitive["width"] == pytest.approx(25.4)
        assert primitive["height"] == pytest.approx(50.8)

    def test_rounded_rectangle_has_arcs_and_edges(self):
        result = outline_primitives(
            {
                "shape": "rounded_rectangle",
                "width": 10,
                "height": 10,
                "cornerRadius": 2,
                "x": 0,
                "y": 0,
                "unit": "mm",
            }
        )
        kinds = [item["type"] for item in result["primitives"]]
        assert kinds.count("arc") == 4
        assert kinds.count("segment") == 4
        top_edge = next(item for item in result["primitives"] if item["type"] == "segment")
        assert top_edge["x1"] == pytest.approx(2)
        assert top_edge["y1"] == pytest.approx(0)
        assert top_edge["x2"] == pytest.approx(8)
        assert top_edge["y2"] == pytest.approx(0)

    def test_unknown_shape_is_unsupported(self):
        result = outline_primitives({"shape": "hexagon", "unit": "mm"})
        assert result["success"] is False
        assert result["error"] == "UNSUPPORTED_OPERATION"


@pytest.mark.unit
class TestIpcMutations:
    def test_delete_trace_removes_through_ipc_and_rereads(self):
        track = _Track("track-1", net="VCC", start=(0, 0), end=(5_000_000, 0))
        board = _CommitBoard(tracks=[track])
        result = _api(board).delete_traces({"traceUuid": "track-1"})
        assert result["success"] is True
        assert result["deletedIds"] == ["track-1"]
        assert board.get_tracks() == []
        assert ("push", "Deleted 1 trace(s)") in board.events

    def test_delete_miss_does_not_open_a_commit(self):
        board = _CommitBoard(tracks=[_Track("track-1")])
        result = _api(board).delete_traces({"net": "MISSING"})
        assert result["success"] is False
        assert result["error"] == "NOT_FOUND"
        assert board.events == []

    def test_delete_failure_drops_the_commit(self):
        board = _CommitBoard(tracks=[_Track("track-1")])

        def fail(items):
            raise RuntimeError("no handler available for request of type DeleteItems")

        board.remove_items = fail
        result = _api(board).delete_traces({"traceUuid": "track-1"})
        assert result["success"] is False
        assert result["error"] == "UNSUPPORTED_OPERATION"
        assert "drop" in board.events
        assert not any(event[0] == "push" for event in board.events if isinstance(event, tuple))

    def test_rectangle_outline_uses_ipc_create_items(self):
        pytest.importorskip("kipy")
        board = _CommitBoard()
        result = _api(board).add_board_outline(
            {"shape": "rectangle", "width": 10, "height": 5, "x": 0, "y": 0, "unit": "mm"}
        )
        assert result["success"] is True
        assert result["shape"] == "rectangle"
        assert ("create", 1) in board.events
        assert any(isinstance(event, tuple) and event[0] == "push" for event in board.events)

    def test_outline_validation_failure_does_not_touch_the_board(self):
        board = _CommitBoard()

        def fail():
            raise AssertionError("board was touched")

        api = _api(board)
        api._get_board = fail
        result = api.add_board_outline({"shape": "hexagon"})
        assert result["error"] == "UNSUPPORTED_OPERATION"


@pytest.mark.unit
class TestDispatcher:
    def setup_method(self):
        pcbnew.SaveBoard.reset_mock()
        pcbnew.LoadBoard.reset_mock()

    def test_ipc_dispatch_does_not_save_or_call_swig(self):
        interface = _interface()
        interface.use_ipc = True
        seen = {}

        def place_component(**kwargs):
            seen.update(kwargs)
            return {"success": True, "reference": kwargs["reference"], "pads": 2}

        interface.ipc_board_api = type("Api", (), {"place_component": staticmethod(place_component)})()
        interface.command_routes["place_component"] = lambda params: (_ for _ in ()).throw(
            AssertionError("SWIG place_component")
        )
        result = interface.handle_command(
            "place_component",
            {
                "reference": "R_PLACE",
                "footprint": "Resistors SMD:RESC2012X60N",
                "position": {"x": 1, "y": 2, "unit": "mm"},
            },
        )
        assert result["success"] is True
        assert result["_backend"] == "ipc"
        assert result["_realtime"] is True
        assert seen["board_path"] is None
        pcbnew.SaveBoard.assert_not_called()
        pcbnew.LoadBoard.assert_not_called()

    def test_ipc_unavailable_does_not_fall_back(self):
        interface = _interface()
        interface.use_ipc = True
        interface.ipc_board_api = None
        interface.command_routes["move_component"] = lambda params: {"success": True}
        result = interface.handle_command(
            "move_component", {"reference": "R1", "position": {"x": 0, "y": 0}}
        )
        assert result["success"] is False
        assert result["error"] == IPC_UNAVAILABLE_ERROR
        assert result["message"] == IPC_UNAVAILABLE_MESSAGE
        assert result["_backend"] != "ipc"
        pcbnew.SaveBoard.assert_not_called()

    def test_failed_ipc_operation_does_not_write_a_file(self):
        interface = _interface()
        interface.use_ipc = True
        interface.ipc_board_api = type(
            "Api",
            (),
            {
                "move_component": staticmethod(lambda **kwargs: False)
            },
        )()
        result = interface.handle_command(
            "move_component", {"reference": "R1", "x": 1, "y": 2}
        )
        assert result["success"] is False
        assert result["_backend"] == "ipc"
        assert result["_realtime"] is False
        pcbnew.SaveBoard.assert_not_called()

    def test_delete_trace_is_not_labeled_as_swig_ipc(self):
        interface = _interface()
        interface.use_ipc = True
        interface.ipc_board_api = _api(_CommitBoard(tracks=[_Track("track-1")]))
        result = interface.handle_command("delete_trace", {"traceUuid": "track-1"})
        assert result["success"] is True
        assert result["_backend"] == "ipc"
        assert result["_realtime"] is True
        pcbnew.SaveBoard.assert_not_called()

    def test_rectangle_outline_is_not_delegated(self):
        pytest.importorskip("kipy")
        interface = _interface()
        interface.use_ipc = True
        interface.ipc_board_api = _api(_CommitBoard())
        result = interface.handle_command(
            "add_board_outline",
            {"shape": "rectangle", "width": 4, "height": 3, "x": 0, "y": 0, "unit": "mm"},
        )
        assert result["success"] is True
        assert result["_backend"] == "ipc"
        pcbnew.SaveBoard.assert_not_called()

    def test_swig_delegation_marker_is_not_reported_as_ipc(self):
        interface = _interface()
        result = interface._label_ipc_result(
            {"success": True, "message": "wrote file", "_delegated_to_swig": True}
        )
        assert result["success"] is False
        assert result["error"] == "IPC_DELEGATION_BLOCKED"
        assert result["_backend"] == "unavailable"
        assert result["_realtime"] is False

    def test_read_only_swig_remains_available_without_ipc(self):
        interface = _interface()
        interface.use_ipc = True
        interface.ipc_board_api = None
        interface.command_routes["list_libraries"] = lambda params: {
            "success": True,
            "libraries": ["Resistors SMD"],
        }
        result = interface.handle_command("list_libraries", {})
        assert result["success"] is True
        assert result["_backend"] == "swig"
        assert result["_realtime"] is False
        pcbnew.SaveBoard.assert_not_called()

    def test_explicit_offline_save_writes_only_an_owned_unlocked_file(self, tmp_path):
        interface = _interface()
        board_path = _board_file(tmp_path, "owned.kicad_pcb")
        interface.board = type("Board", (), {"GetFileName": lambda self: board_path})()
        interface._remember_offline_board()
        def save_project(params):
            pcbnew.SaveBoard(board_path, interface.board)
            return {"success": True, "message": "saved"}

        interface.project_commands.save_project = save_project
        interface.command_routes["save_project"] = interface._guarded_save_project
        result = interface.handle_command("save_project", {})
        assert result["success"] is True
        assert result["_backend"] == "swig"
        pcbnew.SaveBoard.assert_called_once_with(board_path, interface.board)

    def test_locked_file_is_not_saved(self, tmp_path):
        interface = _interface()
        board_path = _board_file(tmp_path, "locked.kicad_pcb")
        kicad_lock_candidates(board_path)[0].write_text("locked", encoding="utf-8")
        interface.board = type("Board", (), {"GetFileName": lambda self: board_path})()
        interface._remember_offline_board()
        interface.project_commands.save_project = lambda params: (_ for _ in ()).throw(
            AssertionError("save_project reached the SWIG writer")
        )
        interface.command_routes["save_project"] = interface._guarded_save_project
        result = interface.handle_command("save_project", {})
        assert result["success"] is False
        assert result["error"] == "EDITOR_OWNS_FILE"
        pcbnew.SaveBoard.assert_not_called()

    def test_offline_mutation_autosaves_only_an_owned_file(self, tmp_path):
        interface = _interface()
        board_path = _board_file(tmp_path, "mutate.kicad_pcb")
        interface.board = type("Board", (), {"GetFileName": lambda self: board_path})()
        interface._remember_offline_board()
        interface.command_routes["move_component"] = lambda params: {"success": True}
        result = interface.handle_command("move_component", {"reference": "R1"})
        assert result["success"] is True
        assert result["fileSaved"] is True
        pcbnew.SaveBoard.assert_called_once_with(board_path, interface.board)

    def test_offline_mutation_does_not_autosave_an_unowned_file(self, tmp_path):
        interface = _interface()
        board_path = _board_file(tmp_path, "unowned.kicad_pcb")
        interface.board = type("Board", (), {"GetFileName": lambda self: board_path})()
        interface.command_routes["move_component"] = lambda params: (_ for _ in ()).throw(
            AssertionError("mutation ran before the ownership check")
        )
        result = interface.handle_command("move_component", {"reference": "R1"})
        assert result["error"] == "FILE_NOT_OWNED"
        pcbnew.SaveBoard.assert_not_called()


@pytest.mark.unit
class TestPreservedContracts:
    def test_clone_and_place_source_contracts_remain(self):
        clone = inspect.getsource(IPCBoardAPI.clone_component)
        place = inspect.getsource(IPCBoardAPI.place_component)
        backend = Path(inspect.getfile(IPCBoardAPI)).read_text(encoding="utf-8")
        interface = Path(inspect.getfile(KiCADInterface)).read_text(encoding="utf-8")
        routes = interface.split("self.command_routes = {", 1)[1].split("logger.info(", 1)[0]
        assert "copy_nets: bool = False" in clone
        assert "pad.net = Net()" in clone
        assert "existing_footprint" in place
        assert "board_path" in place
        assert "SaveBoard" not in backend
        assert ".revert(" not in backend
        assert '"clone_component"' not in routes
        assert '"place_component": self._handle_place_component' in routes

    def test_clone_dispatch_defaults_copy_nets_to_false(self):
        pcbnew.SaveBoard.reset_mock()
        interface = _interface()
        interface.use_ipc = True
        seen = {}

        def clone_component(**kwargs):
            seen.update(kwargs)
            return {
                "success": True,
                "message": "cloned",
                "nets_copied": kwargs["copy_nets"],
                "pads": 2,
            }

        interface.ipc_board_api = type("Api", (), {"clone_component": staticmethod(clone_component)})()
        result = interface.handle_command(
            "clone_component",
            {
                "sourceReference": "R14",
                "newReference": "R_PLACE",
                "position": {"x": 230, "y": 170, "unit": "mm"},
                "rotation": 0,
            },
        )
        assert result["success"] is True
        assert result["_backend"] == "ipc"
        assert seen["copy_nets"] is False
        assert seen["new_reference"] == "R_PLACE"
        pcbnew.SaveBoard.assert_not_called()


if __name__ == "__main__":
    import tempfile
    import traceback

    passed = skipped = failed = 0
    for cls in (
        TestFileOwnership,
        TestOutlineGeometry,
        TestIpcMutations,
        TestDispatcher,
        TestPreservedContracts,
    ):
        for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
            if not name.startswith("test_"):
                continue
            obj = cls()
            if hasattr(obj, "setup_method"):
                obj.setup_method()
            label = f"{cls.__name__}.{name}"
            try:
                if "tmp_path" in inspect.signature(method).parameters:
                    with tempfile.TemporaryDirectory() as temporary:
                        method(obj, Path(temporary))
                else:
                    method(obj)
            except Exception as exc:
                if exc.__class__.__name__ in {"_Skip", "Skipped", "OutcomeException"}:
                    skipped += 1
                    print(f"SKIP {label}")
                    continue
                failed += 1
                print(f"FAIL {label}")
                traceback.print_exc()
                continue
            passed += 1
            print(f"PASS {label}")
    print(f"passed={passed} skipped={skipped} failed={failed}")
    raise SystemExit(1 if failed else 0)
