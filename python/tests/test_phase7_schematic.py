"""Phase 7A schematic geometry, library discovery, and ERC parsing tests."""

import os
import sys
from pathlib import Path

_PYTHON_ROOT = Path(__file__).resolve().parent.parent
if str(_PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(_PYTHON_ROOT))

from commands.dynamic_symbol_loader import DynamicSymbolLoader
from commands.erc_report import parse_kicad_erc_report
from commands.pin_locator import PinLocator


def test_sheet_positions_match_kicad_y_axis():
    """Q1 and J1 positions established from the KiCad 10 ERC coordinates."""
    emitter = PinLocator.sheet_pin_position(139.7, 59.69, 0, 2.54, -5.08)
    base = PinLocator.sheet_pin_position(139.7, 59.69, 0, -5.08, 0)
    collector = PinLocator.sheet_pin_position(139.7, 59.69, 0, 2.54, 5.08)
    assert emitter == (142.24, 64.77)
    assert base == (134.62, 59.69)
    assert collector == (142.24, 54.61)

    j1_pin1 = PinLocator.sheet_pin_position(39.37, 39.37, 0, -5.08, 0)
    j1_pin2 = PinLocator.sheet_pin_position(39.37, 39.37, 0, -5.08, -2.54)
    assert j1_pin1 == (34.29, 39.37)
    assert j1_pin2 == (34.29, 41.91)


def test_resistor_rotation_and_mirror():
    pin1 = PinLocator.sheet_pin_position(80.01, 39.37, 0, 0, 3.81)
    pin2 = PinLocator.sheet_pin_position(80.01, 39.37, 0, 0, -3.81)
    assert pin1[1] < 39.37
    assert pin2[1] > 39.37

    turned = PinLocator.sheet_pin_position(100, 100, 90, 0, 3.81)
    assert turned == (96.19, 100)

    swapped = PinLocator.sheet_pin_position(100, 100, 180, 0, 3.81)
    assert swapped == (100, 103.81)

    mirrored = PinLocator.sheet_pin_position(100, 100, 0, 0, 3.81, mirror="x")
    assert mirrored == (100, 103.81)

    side = PinLocator.sheet_pin_position(100, 100, 0, -5.08, 0, mirror="y")
    assert side == (105.08, 100)


def test_outward_stub_leaves_the_pin():
    angle = PinLocator.sheet_outward_angle(270, 0)
    assert round(angle) == 90
    turned = PinLocator.sheet_outward_angle(270, 90)
    assert round(turned) == 180


def test_erc_parser_reads_kicad10_sheets_and_does_not_hide_errors():
    report = {
        "kicad_version": "10.0.5",
        "coordinate_units": "mm",
        "sheets": [
            {
                "path": "/",
                "violations": [
                    {
                        "description": "Pin not connected",
                        "severity": "error",
                        "type": "pin_not_connected",
                        "items": [{"pos": {"x": 0.34, "y": 0.41}}],
                    },
                    {
                        "description": "Symbol differs",
                        "severity": "warning",
                        "type": "lib_symbol_mismatch",
                        "items": [],
                    },
                ],
            }
        ],
    }
    parsed = parse_kicad_erc_report(report)
    assert parsed["success"] is True
    assert parsed["ercPassed"] is False
    assert parsed["summary"]["errors"] == 1
    assert parsed["summary"]["warnings"] == 1
    assert parsed["summary"]["total"] == 2
    assert parsed["violations"][0]["sheet"] == "/"
    assert parsed["violations"][0]["location"] == {"x": 0.34, "y": 0.41}
    assert parsed["violations"][0]["description"] == "Pin not connected"


def test_erc_parser_reads_legacy_top_level_violations():
    parsed = parse_kicad_erc_report(
        {"violations": [{"description": "Old", "severity": "warning", "type": "note"}]}
    )
    assert parsed["ercPassed"] is True
    assert parsed["summary"]["warnings"] == 1
    assert parsed["violations"][0]["type"] == "note"


def test_kicad10_symbol_discovery_without_environment():
    saved = {
        name: os.environ.pop(name, None)
        for name in (
            "KICAD_SYMBOL_DIR",
            "KICAD10_SYMBOL_DIR",
            "KICAD9_SYMBOL_DIR",
            "KICAD8_SYMBOL_DIR",
        )
    }
    try:
        loader = DynamicSymbolLoader()
        for library, symbol in (
            ("Device", "R"),
            ("Device", "LED"),
            ("Transistor_BJT", "2N3904"),
            ("Connector_Generic", "Conn_01x02"),
        ):
            block = loader.extract_symbol_from_library(library, symbol)
            assert block, f"{library}:{symbol} was not found"
            assert f'(symbol "{library}:{symbol}"' in block
        missing = loader.extract_symbol_from_library("Device", "NOT_A_REAL_SYMBOL")
        assert missing is None
    finally:
        for name, value in saved.items():
            if value is not None:
                os.environ[name] = value


def test_stale_embedded_symbol_is_replaced_from_the_library(tmp_path):
    schematic = Path(tmp_path) / "stale.kicad_sch"
    schematic.write_text(
        """(kicad_sch (version 20250114) (generator "KiCAD-MCP-Server")
  (uuid 11111111-1111-1111-1111-111111111111)
  (paper "A4")
  (lib_symbols
    (symbol "Device:R" (pin_numbers hide) (in_bom yes) (on_board yes)
      (property "Reference" "R" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
      (symbol "R_1_1"
        (pin passive line (at 0 3.81 270) (length 1.27)
          (name "~" (effects (font (size 1.27 1.27))))
          (number "1" (effects (font (size 1.27 1.27))))
        )
      )
    )
  )
  (sheet_instances
    (path "/" (page "1"))
  )
)
""",
        encoding="utf-8",
    )
    loader = DynamicSymbolLoader()
    assert loader.inject_symbol_into_schematic(schematic, "Device", "R")
    text = schematic.read_text(encoding="utf-8")
    assert text.count('(symbol "Device:R"') == 1
    assert '(property "ki_keywords" "R res resistor"' in text
    assert '(name ""' in text
    assert '(name "~"' not in text


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
