"""Phase 7B schematic-to-PCB synchronisation tests. Uses real pcbnew."""

import hashlib
import os
import sys
from pathlib import Path

os.environ["KICAD_BACKEND"] = "swig"
os.environ["KICAD_AUTO_LAUNCH"] = "false"

_PYTHON_ROOT = Path(__file__).resolve().parent.parent
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))

import pcbnew

from kicad_api.pcb_safety import evaluate_pcb_file_access
from kicad_api.schematic_sync import (
    SyncFailure,
    apply_netlist_to_board,
    connectivity_matches,
    parse_kicad_netlist,
    synchronize_schematic_to_pcb,
)
from kicad_interface import KiCADInterface

SCHEMATIC = Path(r"C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7A\MCP-E2E-LED-P7A.kicad_sch")
BOARD = Path(r"C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7B\MCP-E2E-LED-P7B.kicad_pcb")
PHASE6 = Path(r"C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED\MCP-E2E-LED.kicad_sch")
PROTECTED = [
    Path(r"C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\ipc-phase3-test.kicad_pcb"),
    Path(r"C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\ipc-move-test.kicad_pcb"),
    Path(r"C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\IPM.kicad_pcb"),
]

EXPECTED = {
    ("J1", "1"): "+5V",
    ("R1", "1"): "+5V",
    ("R1", "2"): "/LED_A",
    ("D1", "2"): "/LED_A",
    ("D1", "1"): "/LED_K",
    ("Q1", "3"): "/LED_K",
    ("J1", "2"): "GND",
    ("J2", "2"): "GND",
    ("Q1", "1"): "GND",
    ("R3", "2"): "GND",
    ("J2", "1"): "/CTRL_IN",
    ("R2", "1"): "/CTRL_IN",
    ("R2", "2"): "/BASE",
    ("R3", "1"): "/BASE",
    ("Q1", "2"): "/BASE",
}


def _stamp(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""


def _minimal_netlist(footprint="Resistor_SMD:R_0603_1608Metric", pin="1", reference="R1"):
    return {
        "source": "test.kicad_sch",
        "components": [
            {
                "reference": reference,
                "value": "330",
                "footprint": footprint,
                "library": "Device",
                "symbol": "R",
                "tstamp": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                "sheetName": "Root",
                "sheetFile": "test.kicad_sch",
            }
        ],
        "nets": [
            {
                "name": "NET",
                "nodes": [{"reference": reference, "pin": pin, "pinFunction": ""}],
            }
        ],
    }


def _blank_schematic(directory: Path) -> Path:
    path = directory / "identity.kicad_sch"
    path.write_text(
        """(kicad_sch (version 20250114) (generator "KiCAD-MCP-Server")
  (uuid 11111111-1111-1111-1111-111111111111)
  (paper "A4")
  (lib_symbols)
  (sheet_instances (path "/" (page "1")))
)
""",
        encoding="utf-8",
    )
    return path


def test_missing_footprint_does_not_create_a_board(tmp_path):
    board = tmp_path / "missing.kicad_pcb"
    schematic = _blank_schematic(tmp_path)
    netlist = _minimal_netlist(footprint="MissingLib:NotAFootprint")
    try:
        apply_netlist_to_board(pcbnew, pcbnew.BOARD(), netlist, schematic)
    except SyncFailure as failure:
        assert failure.code == "FOOTPRINT_NOT_FOUND"
    else:
        raise AssertionError("missing footprint was accepted")
    assert not board.exists()


def test_duplicate_reference_is_rejected():
    text = """(export (version "E") (design (source "a.kicad_sch"))
      (components
        (comp (ref "R1") (value "1") (footprint "Resistor_SMD:R_0603_1608Metric") (tstamps "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))
        (comp (ref "R1") (value "2") (footprint "Resistor_SMD:R_0603_1608Metric") (tstamps "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"))
      )
      (nets))"""
    try:
        parse_kicad_netlist(text)
    except SyncFailure as failure:
        assert failure.code == "DUPLICATE_REFERENCE"
    else:
        raise AssertionError("duplicate reference was accepted")


def test_missing_pad_number_leaves_no_file(tmp_path):
    schematic = _blank_schematic(tmp_path)
    netlist = _minimal_netlist(pin="99")
    try:
        apply_netlist_to_board(pcbnew, pcbnew.BOARD(), netlist, schematic)
    except SyncFailure as failure:
        assert failure.code == "MISSING_PAD"
    else:
        raise AssertionError("missing pad was accepted")
    assert list(tmp_path.glob("*.kicad_pcb")) == []


def test_net_mismatch_is_reported():
    info = {
        "footprints": [
            {
                "reference": "R1",
                "pads": [{"number": "1", "net": "GND"}],
            }
        ]
    }
    netlist = {
        "nets": [{"name": "+5V", "nodes": [{"reference": "R1", "pin": "1"}]}]
    }
    problems = connectivity_matches(netlist, info)
    assert problems
    assert "+5V" in problems[0]


def test_open_editor_target_is_rejected(tmp_path):
    board = tmp_path / "open.kicad_pcb"
    pcbnew.BOARD().Save(str(board))
    original = board.read_bytes()
    interface = KiCADInterface()
    interface._live_editor_paths = lambda: [str(board.resolve())]
    interface._live_paths_unknown = False
    result = interface.handle_command(
        "sync_schematic_to_board",
        {"schematicPath": str(SCHEMATIC), "boardPath": str(board)},
    )
    assert result["success"] is False
    assert result["error"] == "EDITOR_OWNS_FILE"
    assert board.read_bytes() == original
    decision = evaluate_pcb_file_access(
        str(board),
        live_paths=[str(board)],
        locked=False,
        use_ipc=False,
        purpose="explicit_file",
        owned=False,
    )
    assert decision["allow"] is False


def test_locked_target_is_rejected(tmp_path):
    board = tmp_path / "locked.kicad_pcb"
    pcbnew.BOARD().Save(str(board))
    original = board.read_bytes()
    lock = tmp_path / ".locked.kicad_pcb.lock"
    lock.write_text("locked", encoding="utf-8")
    interface = KiCADInterface()
    result = interface.handle_command(
        "sync_schematic_to_board",
        {"schematicPath": str(SCHEMATIC), "boardPath": str(board)},
    )
    assert result["success"] is False
    assert result["error"] == "EDITOR_OWNS_FILE"
    assert board.read_bytes() == original


def test_missing_pcb_target_creates_nothing(tmp_path):
    interface = KiCADInterface()
    result = interface.handle_command(
        "sync_schematic_to_board",
        {"schematicPath": str(SCHEMATIC)},
    )
    assert result["success"] is False
    assert result["error"] == "MISSING_PCB_TARGET"
    assert list(tmp_path.glob("*.kicad_pcb")) == []


def test_inconsistent_schematic_identity_writes_nothing(tmp_path):
    import kicad_api.schematic_sync as sync

    schematic = SCHEMATIC
    board = tmp_path / "identity.kicad_pcb"
    original_export = sync.export_cli_netlist

    def wrong_source(path):
        text = original_export(path)
        return text.replace(Path(path).name, "other-sheet.kicad_sch")

    sync.export_cli_netlist = wrong_source
    try:
        synchronize_schematic_to_pcb(str(schematic), str(board))
    except SyncFailure as failure:
        assert failure.code == "INCONSISTENT_SCHEMATIC"
    else:
        raise AssertionError("a foreign netlist source was accepted")
    finally:
        sync.export_cli_netlist = original_export
    assert not board.exists()


def test_partial_failure_does_not_leave_a_board(tmp_path):
    schematic = _blank_schematic(tmp_path)
    netlist = _minimal_netlist()
    netlist["nets"].append(
        {"name": "OTHER", "nodes": [{"reference": "R1", "pin": "2", "pinFunction": ""}]}
    )
    netlist["components"].insert(
        0,
        {
            "reference": "Q1",
            "value": "2N3904",
            "footprint": "MissingLib:NotAFootprint",
            "library": "Transistor_BJT",
            "symbol": "2N3904",
            "tstamp": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
            "sheetName": "Root",
            "sheetFile": "identity.kicad_sch",
        },
    )
    netlist["nets"].append(
        {"name": "COLLECTOR", "nodes": [{"reference": "Q1", "pin": "1", "pinFunction": ""}]}
    )
    try:
        apply_netlist_to_board(pcbnew, pcbnew.BOARD(), netlist, schematic)
    except SyncFailure as failure:
        assert failure.code == "FOOTPRINT_NOT_FOUND"
    else:
        raise AssertionError("partial netlist was saved")
    assert list(tmp_path.glob("*.kicad_pcb")) == []


def test_failed_repeat_restores_the_previous_board(tmp_path):
    import kicad_api.schematic_sync as sync

    board = tmp_path / "restore.kicad_pcb"
    synchronize_schematic_to_pcb(str(SCHEMATIC), str(board))
    original = board.read_bytes()
    original_match = sync.connectivity_matches

    def forced_mismatch(*_args, **_kwargs):
        return ["forced mismatch after save"]

    sync.connectivity_matches = forced_mismatch
    try:
        synchronize_schematic_to_pcb(str(SCHEMATIC), str(board))
    except SyncFailure as failure:
        assert failure.code == "NET_MISMATCH"
    else:
        raise AssertionError("a forced mismatch was saved")
    finally:
        sync.connectivity_matches = original_match
    assert board.read_bytes() == original


def test_real_schematic_sync_and_repeat_preserve_sources():
    schematic_hash = _stamp(SCHEMATIC)
    phase6_hash = _stamp(PHASE6)
    protected = {str(path): _stamp(path) for path in PROTECTED}
    first = synchronize_schematic_to_pcb(str(SCHEMATIC), str(BOARD))
    positions = {item["reference"]: item["position"] for item in first["footprints"]}
    second = synchronize_schematic_to_pcb(str(SCHEMATIC), str(BOARD))
    assert len(second["footprints"]) == 7
    assert second["created"] == []
    assert sorted(second["updated"]) == ["D1", "J1", "J2", "Q1", "R1", "R2", "R3"]
    assert {item["reference"]: item["position"] for item in second["footprints"]} == positions
    by_pad = {
        (item["reference"], pad["number"]): pad["net"]
        for item in second["footprints"]
        for pad in item["pads"]
    }
    assert by_pad == EXPECTED
    assert {item["reference"]: item["footprint"] for item in second["footprints"]} == {
        "Q1": "Package_TO_SOT_THT:TO-92_Inline",
        "D1": "LED_SMD:LED_0603_1608Metric",
        "R1": "Resistor_SMD:R_0603_1608Metric",
        "R2": "Resistor_SMD:R_0603_1608Metric",
        "R3": "Resistor_SMD:R_0603_1608Metric",
        "J1": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        "J2": "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
    }
    assert all(item["modelCount"] >= 1 for item in second["footprints"])
    import tempfile

    scratch = Path(tempfile.mkdtemp(prefix="p7b-other-"))
    other = scratch / "must-not-change.kicad_pcb"
    pcbnew.BOARD().Save(str(other))
    other_bytes = other.read_bytes()
    interface = KiCADInterface()
    interface.board = pcbnew.LoadBoard(str(other))
    handled = interface.handle_command(
        "sync_schematic_to_board",
        {"schematicPath": str(SCHEMATIC), "boardPath": str(BOARD)},
    )
    assert handled["success"] is True
    assert handled.get("_backend") == "swig"
    assert handled["internalNetlistAgrees"] is True
    assert len(handled["footprints"]) == 7
    assert other.read_bytes() == other_bytes
    import shutil

    shutil.rmtree(scratch, ignore_errors=True)
    reloaded = pcbnew.LoadBoard(str(BOARD))
    assert len(list(reloaded.GetFootprints())) == 7
    assert _stamp(SCHEMATIC) == schematic_hash
    assert _stamp(PHASE6) == phase6_hash
    for path, digest in protected.items():
        assert _stamp(Path(path)) == digest


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
