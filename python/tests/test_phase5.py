"""Phase 5 routing tests. They do not open a KiCad editor document."""

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
from kicad_api.phase5 import (
    add_net_class_result,
    add_wire_result,
    assign_net_to_class_result,
    check_clearance_result,
    export_netlist,
    export_position_file,
    export_vrml,
    replace_component_result,
    set_layer_constraints_result,
)
from kicad_interface import KiCADInterface
from kipy.board_types import Net, ZoneConnectionStyle


class ProtoId:
    def __init__(self, value):
        self.value = value


class Text:
    def __init__(self, value):
        self.value = value


class Field:
    def __init__(self, value, visible=True):
        self.text = Text(value)
        self.visible = visible


class Footprint:
    def __init__(self, reference, ident):
        self.reference_field = Field(reference)
        self.description_field = Field("existing")
        self.id = ProtoId(ident)


class StoredZone:
    def __init__(self, source, ident):
        self.id = ProtoId(ident)
        self.net = types.SimpleNamespace(name=source.net.name)
        self.connection = types.SimpleNamespace(
            zone_connection=source.connection.zone_connection
        )
        self.clearance = source.clearance


class StoredGroup:
    def __init__(self, name, members, ident):
        self.name = name
        self.id = ProtoId(ident)
        self.items = list(members)
        self._item_ids = [member.id for member in members]


class FakeBoard:
    def __init__(self, nets=None, footprints=None):
        self.nets = list(nets or [])
        self.footprints = list(footprints or [])
        self.zones = []
        self.groups = []
        self.events = []

    def get_nets(self):
        return list(self.nets)

    def get_footprints(self):
        return list(self.footprints)

    def get_zones(self):
        return list(self.zones)

    def get_groups(self):
        return list(self.groups)

    def get_layer_by_name(self, name):
        if name == "Missing.Cu":
            raise ValueError(name)
        return 3

    def begin_commit(self):
        self.events.append("begin")
        return "commit"

    def drop_commit(self, _commit):
        self.events.append("drop")

    def push_commit(self, _commit, message):
        self.events.append(("push", message))

    def create_items(self, item):
        if hasattr(item, "net"):
            stored = StoredZone(item, "zone-1")
            self.zones.append(stored)
            self.events.append(("create-zone", stored.net.name))
            return [stored]
        stored = StoredGroup(item._proto.name, item.items, "group-1")
        self.groups.append(stored)
        self.events.append(("create-group", stored.name))
        return [stored]

    def update_items(self, items):
        self.events.append(("update", len(items)))

    def remove_items(self, items):
        self.events.append("remove")


def _api(board):
    api = IPCBoardAPI.__new__(IPCBoardAPI)
    api._board = board
    api._kicad = None
    api._notify = lambda *args, **kwargs: None
    api._current_commit = None
    return api


def test_aliases_are_rejected_without_a_file_edit():
    for result in (
        add_wire_result({"start": {"x": 0, "y": 0}, "end": {"x": 1, "y": 0}}),
        add_net_class_result({"name": "Power", "clearance": 0.2, "trackWidth": 0.25, "viaDiameter": 0.6, "viaDrill": 0.3}),
        assign_net_to_class_result({"net": "GND", "netClass": "Power"}),
        check_clearance_result({}),
        replace_component_result({"reference": "R1", "newComponentId": "R"}),
        set_layer_constraints_result({"layer": "F.Cu"}),
    ):
        assert result["success"] is False
        assert result["error"] == "UNSUPPORTED_OPERATION"


def test_dispatcher_does_not_label_unsupported_as_swig():
    interface = KiCADInterface.__new__(KiCADInterface)
    interface.use_ipc = False
    interface.command_routes = {
        "add_wire": lambda params: KiCADInterface._phase5_add_wire(interface, params)
    }
    result = interface.handle_command("add_wire", {"start": {"x": 0, "y": 0}, "end": {"x": 1, "y": 0}})
    assert result["success"] is False
    assert result["error"] == "UNSUPPORTED_OPERATION"
    assert result["_backend"] == "unavailable"
    assert result["_realtime"] is False


def test_add_zone_requires_ipc_and_does_not_fall_back():
    interface = KiCADInterface.__new__(KiCADInterface)
    interface.use_ipc = True
    interface.ipc_board_api = None
    interface.command_routes = {}
    result = interface.handle_command("add_zone", {"layer": "F.Cu", "net": "GND", "points": [], "unit": "mm"})
    assert result["error"] == "IPC_UNAVAILABLE"
    assert result["_backend"] == "unavailable"


def test_missing_zone_net_does_not_open_a_commit():
    board = FakeBoard([Net(name="GND")])
    result = _api(board).create_verified_zone(
        {
            "layer": "F.Cu",
            "net": "PHASE5_MISSING",
            "unit": "mm",
            "points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}],
        }
    )
    assert result["success"] is False
    assert result["error"] == "NET_NOT_FOUND"
    assert board.events == []


def test_zone_creation_verifies_the_net_and_pad_connection():
    board = FakeBoard([Net(name="GND")])
    result = _api(board).create_verified_zone(
        {
            "layer": "F.Cu",
            "net": "GND",
            "unit": "inch",
            "padConnection": "thermal",
            "clearance": 0.01,
            "points": [{"x": 0, "y": 0}, {"x": 0.1, "y": 0}, {"x": 0.1, "y": 0.1}],
        }
    )
    assert result["success"] is True
    assert result["id"] == "zone-1"
    assert result["net"] == "GND"
    assert result["pointCount"] == 3
    assert board.zones[0].connection.zone_connection == ZoneConnectionStyle.ZCS_THERMAL
    assert ("create-zone", "GND") in board.events


def test_annotation_is_read_back_on_the_same_footprint():
    footprint = Footprint("R_PHASE5", "fp-1")
    board = FakeBoard(footprints=[footprint])
    result = _api(board).annotate_component("R_PHASE5", "PHASE5 NOTE", True)
    assert result["success"] is True
    assert result["id"] == "fp-1"
    assert result["reference"] == "R_PHASE5"
    assert "PHASE5 NOTE" in result["description"]
    assert "existing" in result["description"]
    assert result["visible"] is True
    assert ("update", 1) in board.events


def test_group_requires_existing_components_and_reads_members_back():
    board = FakeBoard(footprints=[Footprint("R_A", "a"), Footprint("R_B", "b")])
    missing = _api(board).group_components(["R_A", "R_MISSING"], "PHASE5")
    assert missing["success"] is False
    assert missing["error"] == "NOT_FOUND"
    assert board.events == []

    import kipy.board_types as board_types

    class FakeGroup:
        def __init__(self):
            self._proto = types.SimpleNamespace(name="")
            self.items = []

    original = board_types.Group
    board_types.Group = FakeGroup
    try:
        created = _api(board).group_components(["R_A", "R_B"], "PHASE5")
    finally:
        board_types.Group = original
    assert created["success"] is True
    assert created["id"] == "group-1"
    assert created["memberIds"] == ["a", "b"]
    assert board.groups[0].name == "PHASE5"


def test_position_export_uses_the_supplied_components_and_refuses_a_board_path(tmp_path=None):
    import tempfile

    temporary = tmp_path or Path(tempfile.mkdtemp())
    output = temporary / "positions.csv"
    components = [
        {
            "reference": "R_PLACE",
            "value": "10k",
            "footprint": "Resistors SMD:RESC2012X60N",
            "position": {"x": 230.0, "y": 170.0},
            "rotation": 0,
            "layer": "F.Cu",
        }
    ]
    refused = export_position_file(
        components,
        {"outputPath": str(temporary / "board.kicad_pcb"), "format": "CSV", "units": "mm", "side": "both"},
    )
    assert refused["success"] is False
    result = export_position_file(
        components,
        {"outputPath": str(output), "format": "CSV", "units": "mm", "side": "top"},
    )
    assert result["success"] is True
    assert result["count"] == 1
    text = output.read_text(encoding="utf-8")
    assert "R_PLACE" in text
    assert "230.000000" in text
    assert "170.000000" in text


def test_netlist_does_not_substitute_another_schematic(tmp_path=None):
    import tempfile

    temporary = tmp_path or Path(tempfile.mkdtemp())
    other = temporary / "IPM.kicad_sch"
    other.write_text("not the open board schematic", encoding="utf-8")
    calls = []
    result = export_netlist(
        str(temporary / "ipc-phase3-test.kicad_pcb"),
        {"outputPath": str(temporary / "out.net"), "format": "KiCad"},
        runner=lambda command: calls.append(command) or {"returncode": 0, "stdout": "", "stderr": ""},
    )
    assert result["success"] is False
    assert result["error"] == "NOT_FOUND"
    assert calls == []
    assert other.read_text(encoding="utf-8") == "not the open board schematic"


def test_vrml_omit_components_is_unsupported_and_writes_nothing(tmp_path=None):
    import tempfile

    temporary = tmp_path or Path(tempfile.mkdtemp())
    board = temporary / "board.kicad_pcb"
    board.write_text("pcb", encoding="utf-8")
    output = temporary / "board.wrl"
    result = export_vrml(str(board), {"outputPath": str(output), "includeComponents": False})
    assert result["success"] is False
    assert result["error"] == "UNSUPPORTED_OPERATION"
    assert not output.exists()
    assert board.read_text(encoding="utf-8") == "pcb"


def test_netlist_cli_exports_a_temporary_schematic_without_editing_it(tmp_path=None):
    import tempfile

    temporary = tmp_path or Path(tempfile.mkdtemp())
    schematic = temporary / "tiny.kicad_sch"
    schematic.write_text(
        """(kicad_sch
  (version 20250114)
  (generator "eeschema")
  (generator_version "10.0")
  (uuid "11111111-1111-4111-8111-111111111111")
  (paper "A4")
  (lib_symbols)
  (sheet_instances
    (path "/" (page "1"))
  )
)
""",
        encoding="utf-8",
    )
    before = schematic.read_bytes()
    output = temporary / "tiny.net"
    result = export_netlist(
        str(temporary / "tiny.kicad_pcb"),
        {"outputPath": str(output), "format": "KiCad"},
    )
    assert schematic.read_bytes() == before
    assert result["success"] is True
    assert output.is_file()
    assert output.stat().st_size > 0


def _fake_plotter(calls, extra=None):
    """Imitate kicad-cli: write plot files into --output and record the command."""

    def run(command):
        calls.append(list(command))
        out = Path(command[command.index("--output") + 1])
        stem = Path(command[-1]).stem
        if command[3] == "gerbers":
            (out / f"{stem}-F_Cu.gbr").write_text("G04 F.Cu*", encoding="utf-8")
            (out / f"{stem}-Edge_Cuts.gbr").write_text("G04 Edge*", encoding="utf-8")
            (out / f"{stem}-job.gbrjob").write_text("{}", encoding="utf-8")
            for name in extra or []:
                (out / name).write_text("stray", encoding="utf-8")
        else:
            (out / f"{stem}-PTH.drl").write_text("M48", encoding="utf-8")
            (out / f"{stem}-NPTH.drl").write_text("M48", encoding="utf-8")
        return {"returncode": 0, "stdout": "", "stderr": ""}

    return run


def test_gerber_plots_a_copy_and_never_the_open_pcb(tmp_path=None):
    import tempfile
    from kicad_api import phase5

    temporary = tmp_path or Path(tempfile.mkdtemp())
    board = temporary / "open.kicad_pcb"
    board.write_text("(kicad_pcb open)", encoding="utf-8")
    out = temporary / "fab"
    calls = []
    original = phase5._kicad_cli
    phase5._kicad_cli = lambda: Path("kicad-cli.exe")
    try:
        result = phase5.export_gerber(str(board), {"outputDir": str(out)}, runner=_fake_plotter(calls))
    finally:
        phase5._kicad_cli = original
    assert result["success"] is True, result
    assert result["source"] == "saved-pcb-copy"
    assert [command[3] for command in calls] == ["gerbers", "drill"]
    for command in calls:
        assert str(board) not in command
        assert Path(command[-1]).name == board.name
        assert Path(command[-1]).parent != board.parent
        assert "--check-zones" not in command
    assert "--no-protel-ext" in calls[0]
    assert "--layers" not in calls[0]
    assert "--excellon-separate-th" in calls[1]
    assert result["files"]["drill"] == ["open-NPTH.drl", "open-PTH.drl"]
    assert "open-F_Cu.gbr" in result["files"]["gerber"]
    assert (out / "open-PTH.drl").is_file()
    assert board.read_text(encoding="utf-8") == "(kicad_pcb open)"


def test_gerber_never_writes_kicad_files_into_output(tmp_path=None):
    import tempfile
    from kicad_api import phase5

    temporary = tmp_path or Path(tempfile.mkdtemp())
    board = temporary / "board.kicad_pcb"
    board.write_text("(kicad_pcb source)", encoding="utf-8")
    out = temporary / "fab"
    out.mkdir()
    neighbour = out / "other.kicad_pcb"
    neighbour.write_text("(kicad_pcb neighbour)", encoding="utf-8")
    calls = []
    original = phase5._kicad_cli
    phase5._kicad_cli = lambda: Path("kicad-cli.exe")
    try:
        result = phase5.export_gerber(
            str(board),
            {"outputPath": str(out), "includeDrillFiles": False, "layers": ["F.Cu", "Edge.Cuts"], "useProtelExtensions": True},
            runner=_fake_plotter(calls, extra=["other.kicad_pcb"]),
        )
    finally:
        phase5._kicad_cli = original
    assert result["success"] is True, result
    assert [command[3] for command in calls] == ["gerbers"]
    assert calls[0][calls[0].index("--layers") + 1] == "F.Cu,Edge.Cuts"
    assert "--no-protel-ext" not in calls[0]
    assert neighbour.read_text(encoding="utf-8") == "(kicad_pcb neighbour)"
    assert result["files"]["drill"] == []


def test_gerber_rejects_bad_output_and_runs_nothing(tmp_path=None):
    import tempfile
    from kicad_api import phase5

    temporary = tmp_path or Path(tempfile.mkdtemp())
    board = temporary / "board.kicad_pcb"
    board.write_text("pcb", encoding="utf-8")
    calls = []
    runner = _fake_plotter(calls)
    for params in (
        {},
        {"outputDir": str(board)},
        {"outputDir": str(temporary / "x.kicad_pro")},
        {"outputDir": str(temporary / "fab"), "layers": "F.Cu"},
        {"outputDir": str(temporary / "fab"), "generateDrillFiles": "yes"},
    ):
        result = phase5.export_gerber(str(board), params, runner=runner)
        assert result["success"] is False
        assert result["error"] == "INVALID_ARGUMENT"
    assert calls == []
    assert board.read_text(encoding="utf-8") == "pcb"
    assert not (temporary / "fab").exists()


def test_gerber_failure_copies_nothing(tmp_path=None):
    import tempfile
    from kicad_api import phase5

    temporary = tmp_path or Path(tempfile.mkdtemp())
    board = temporary / "board.kicad_pcb"
    board.write_text("pcb", encoding="utf-8")
    out = temporary / "fab"
    original = phase5._kicad_cli
    phase5._kicad_cli = lambda: Path("kicad-cli.exe")
    try:
        result = phase5.export_gerber(
            str(board),
            {"outputDir": str(out)},
            runner=lambda command: {"returncode": 1, "stdout": "", "stderr": "plot failed"},
        )
    finally:
        phase5._kicad_cli = original
    assert result["success"] is False
    assert result["message"] == "plot failed"
    assert not out.exists()


if __name__ == "__main__":
    import tempfile
    import traceback

    passed = failed = 0
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        try:
            if "tmp_path" in test.__code__.co_varnames:
                with tempfile.TemporaryDirectory() as directory:
                    test(Path(directory))
            else:
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
