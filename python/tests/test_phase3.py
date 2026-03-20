"""
Tests for Phase 3: Advanced Features

Covers hierarchical sheet support, standalone netlist export,
and parameter-aware component search.
"""

import shutil
from pathlib import Path

import pytest
import sexpdata
from sexpdata import Symbol

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
EMPTY_SCH = TEMPLATES_DIR / "empty.kicad_sch"


def _make_schematic_with_wired_components(tmp_path: Path) -> Path:
    """Create a schematic with two wired components for netlist testing."""
    from commands.dynamic_symbol_loader import DynamicSymbolLoader
    from commands.wire_manager import WireManager

    sch = tmp_path / "test.kicad_sch"
    shutil.copy(EMPTY_SCH, sch)
    loader = DynamicSymbolLoader()
    # R1 at (50.8, 50.8) — pin 1 at ~(50.8, 46.99), pin 2 at ~(50.8, 54.61)
    loader.create_component_instance(sch, "Device", "R", "R1", "10k", x=50.8, y=50.8)
    # C1 at (76.2, 50.8) — pin 1 at ~(76.2, 46.99), pin 2 at ~(76.2, 54.61)
    loader.create_component_instance(sch, "Device", "C", "C1", "100nF", x=76.2, y=50.8)

    # Wire R1 pin 1 to C1 pin 1 via a labeled net
    WireManager.add_wire(sch, [50.8, 46.99], [76.2, 46.99])
    WireManager.add_label(sch, "VCC", [63.5, 46.99])

    # Wire R1 pin 2 to C1 pin 2
    WireManager.add_wire(sch, [50.8, 54.61], [76.2, 54.61])
    WireManager.add_label(sch, "GND", [63.5, 54.61])

    return sch


# ---------------------------------------------------------------------------
# Hierarchical Sheets
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHierarchicalSheets:
    def test_create_sheet(self, tmp_path):
        from commands.hierarchical_sheets import create_hierarchical_sheet

        sch = tmp_path / "parent.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)

        result = create_hierarchical_sheet(
            sch, "Power", "power.kicad_sch", x=127.0, y=76.2,
        )
        assert result["success"] is True
        assert "sheet_uuid" in result

        # Verify parent file has sheet block
        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)  # must parse
        assert '(sheet ' in content
        assert '"Power"' in content
        assert '"power.kicad_sch"' in content

    def test_create_sheet_creates_subsheet_file(self, tmp_path):
        from commands.hierarchical_sheets import create_hierarchical_sheet

        sch = tmp_path / "parent.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)

        create_hierarchical_sheet(sch, "Sub", "sub.kicad_sch")

        subsheet = tmp_path / "sub.kicad_sch"
        assert subsheet.exists()
        # Sub-sheet must be valid S-expression
        sexpdata.loads(subsheet.read_text(encoding="utf-8"))

    def test_create_sheet_no_overwrite(self, tmp_path):
        from commands.hierarchical_sheets import create_hierarchical_sheet

        sch = tmp_path / "parent.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)

        # Pre-create the sub-sheet with custom content
        subsheet = tmp_path / "existing.kicad_sch"
        subsheet.write_text("custom content", encoding="utf-8")

        create_hierarchical_sheet(sch, "Existing", "existing.kicad_sch")

        # Should NOT overwrite
        assert subsheet.read_text(encoding="utf-8") == "custom content"

    def test_add_sheet_pin(self, tmp_path):
        from commands.hierarchical_sheets import (
            create_hierarchical_sheet,
            add_sheet_pin,
        )

        sch = tmp_path / "parent.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        create_hierarchical_sheet(sch, "Power", "power.kicad_sch")

        result = add_sheet_pin(sch, "Power", "VCC", pin_type="input")
        assert result["success"] is True
        assert "pin_uuid" in result

        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        assert '(pin "VCC"' in content

    def test_add_sheet_pin_creates_hierarchical_label(self, tmp_path):
        from commands.hierarchical_sheets import (
            create_hierarchical_sheet,
            add_sheet_pin,
        )

        sch = tmp_path / "parent.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        create_hierarchical_sheet(sch, "Power", "power.kicad_sch")
        add_sheet_pin(sch, "Power", "VCC", pin_type="input")

        subsheet = tmp_path / "power.kicad_sch"
        content = subsheet.read_text(encoding="utf-8")
        sexpdata.loads(content)
        assert '(hierarchical_label "VCC"' in content

    def test_add_multiple_pins(self, tmp_path):
        from commands.hierarchical_sheets import (
            create_hierarchical_sheet,
            add_sheet_pin,
        )

        sch = tmp_path / "parent.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        create_hierarchical_sheet(sch, "IO", "io.kicad_sch")

        add_sheet_pin(sch, "IO", "SDA", pin_type="bidirectional", position_index=0)
        add_sheet_pin(sch, "IO", "SCL", pin_type="bidirectional", position_index=1)

        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        assert '(pin "SDA"' in content
        assert '(pin "SCL"' in content

    def test_add_pin_unknown_sheet_fails(self, tmp_path):
        from commands.hierarchical_sheets import add_sheet_pin

        sch = tmp_path / "parent.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)

        result = add_sheet_pin(sch, "Nonexistent", "VCC")
        assert result["success"] is False

    def test_multiple_sheets(self, tmp_path):
        from commands.hierarchical_sheets import create_hierarchical_sheet

        sch = tmp_path / "parent.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)

        create_hierarchical_sheet(sch, "Power", "power.kicad_sch", x=50.8, y=50.8)
        create_hierarchical_sheet(sch, "Digital", "digital.kicad_sch", x=127.0, y=50.8)

        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        assert content.count("(sheet ") == 2
        assert (tmp_path / "power.kicad_sch").exists()
        assert (tmp_path / "digital.kicad_sch").exists()


# ---------------------------------------------------------------------------
# Netlist Export
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNetlistExport:
    def test_export_empty_schematic(self, tmp_path):
        from commands.netlist_export import export_netlist

        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)

        result = export_netlist(sch)
        assert result["success"] is True
        assert result["component_count"] == 0
        assert result["net_count"] == 0

    def test_export_with_components(self, tmp_path):
        from commands.netlist_export import export_netlist

        sch = _make_schematic_with_wired_components(tmp_path)
        result = export_netlist(sch)
        assert result["success"] is True
        assert result["component_count"] == 2

        refs = {c["reference"] for c in result["components"]}
        assert "R1" in refs
        assert "C1" in refs

    def test_export_detects_nets(self, tmp_path):
        from commands.netlist_export import export_netlist

        sch = _make_schematic_with_wired_components(tmp_path)
        result = export_netlist(sch)
        net_names = {n["name"] for n in result["nets"]}
        assert "VCC" in net_names
        assert "GND" in net_names

    def test_export_net_connections(self, tmp_path):
        from commands.netlist_export import export_netlist

        sch = _make_schematic_with_wired_components(tmp_path)
        result = export_netlist(sch)

        vcc_net = next(n for n in result["nets"] if n["name"] == "VCC")
        connected_refs = {c["reference"] for c in vcc_net["connections"]}
        # Both R1 and C1 pin 1 should be on VCC
        assert "R1" in connected_refs
        assert "C1" in connected_refs

    def test_export_component_values(self, tmp_path):
        from commands.netlist_export import export_netlist

        sch = _make_schematic_with_wired_components(tmp_path)
        result = export_netlist(sch)

        r1 = next(c for c in result["components"] if c["reference"] == "R1")
        assert r1["value"] == "10k"
        assert r1["lib_id"] == "Device:R"

    def test_export_component_pins(self, tmp_path):
        from commands.netlist_export import export_netlist

        sch = _make_schematic_with_wired_components(tmp_path)
        result = export_netlist(sch)

        r1 = next(c for c in result["components"] if c["reference"] == "R1")
        assert len(r1["pins"]) == 2
        pin_numbers = {p["number"] for p in r1["pins"]}
        assert "1" in pin_numbers
        assert "2" in pin_numbers

    def test_export_kicad_format(self, tmp_path):
        from commands.netlist_export import export_netlist_kicad_format

        sch = _make_schematic_with_wired_components(tmp_path)
        out = tmp_path / "test.net"

        result = export_netlist_kicad_format(sch, out)
        assert result["success"] is True
        assert out.exists()

        content = out.read_text(encoding="utf-8")
        assert "(export" in content
        assert "(components" in content
        assert "(nets" in content
        assert "(ref R1)" in content
        assert '(name "VCC")' in content

    def test_export_nonexistent_file(self, tmp_path):
        from commands.netlist_export import export_netlist

        result = export_netlist(tmp_path / "nope.kicad_sch")
        assert result["success"] is False


# ---------------------------------------------------------------------------
# Component Search
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestComponentSearch:
    def _make_test_library(self, tmp_path: Path) -> Path:
        """Create a minimal .kicad_sym library for testing."""
        lib_dir = tmp_path / "symbols"
        lib_dir.mkdir()

        content = """\
(kicad_symbol_lib (version 20211014) (generator test)
  (symbol "R" (pin_names (offset 0)) (in_bom yes) (on_board yes)
    (property "Reference" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Value" "R" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Description" "Resistor" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "ki_keywords" "R res resistor" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "ki_fp_filters" "R_* Resistor_*" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "R_0_1"
      (rectangle (start -1 -2.5) (end 1 2.5) (stroke (width 0.25) (type default)) (fill (type none)))
    )
    (symbol "R_1_1"
      (pin passive line (at 0 3.81 270) (length 1.27) (name "~" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 0 -3.81 90) (length 1.27) (name "~" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))
    )
  )
  (symbol "C" (pin_names (offset 0)) (in_bom yes) (on_board yes)
    (property "Reference" "C" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Value" "C" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Description" "Unpolarized capacitor" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "ki_keywords" "cap capacitor" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "C_0_1"
      (polyline (pts (xy -2 -0.75) (xy 2 -0.75)) (stroke (width 0.5) (type default)) (fill (type none)))
    )
    (symbol "C_1_1"
      (pin passive line (at 0 3.81 270) (length 2.79) (name "~" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 0 -3.81 90) (length 2.79) (name "~" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))
    )
  )
  (symbol "LED" (pin_names (offset 1) hide) (in_bom yes) (on_board yes)
    (property "Reference" "D" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Value" "LED" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "Description" "Light emitting diode" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (property "ki_keywords" "LED diode light" (at 0 0 0) (effects (font (size 1.27 1.27))))
    (symbol "LED_0_1"
      (polyline (pts (xy -1.27 0) (xy 1.27 0)) (stroke (width 0) (type default)) (fill (type none)))
    )
    (symbol "LED_1_1"
      (pin passive line (at -3.81 0 0) (length 2.54) (name "K" (effects (font (size 1.27 1.27)))) (number "1" (effects (font (size 1.27 1.27)))))
      (pin passive line (at 3.81 0 180) (length 2.54) (name "A" (effects (font (size 1.27 1.27)))) (number "2" (effects (font (size 1.27 1.27)))))
    )
  )
)
"""
        (lib_dir / "Device.kicad_sym").write_text(content, encoding="utf-8")
        return lib_dir

    def test_search_by_name(self, tmp_path):
        from commands.component_search import search_components

        lib_dir = self._make_test_library(tmp_path)
        result = search_components("R", library_paths=[lib_dir])
        assert result["success"] is True
        assert result["result_count"] >= 1
        lib_ids = {r["lib_id"] for r in result["results"]}
        assert "Device:R" in lib_ids

    def test_search_by_keyword(self, tmp_path):
        from commands.component_search import search_components

        lib_dir = self._make_test_library(tmp_path)
        result = search_components("resistor", library_paths=[lib_dir])
        assert result["success"] is True
        lib_ids = {r["lib_id"] for r in result["results"]}
        assert "Device:R" in lib_ids

    def test_search_by_description(self, tmp_path):
        from commands.component_search import search_components

        lib_dir = self._make_test_library(tmp_path)
        result = search_components("capacitor", library_paths=[lib_dir])
        assert result["success"] is True
        lib_ids = {r["lib_id"] for r in result["results"]}
        assert "Device:C" in lib_ids

    def test_search_led(self, tmp_path):
        from commands.component_search import search_components

        lib_dir = self._make_test_library(tmp_path)
        result = search_components("LED", library_paths=[lib_dir])
        assert result["success"] is True
        lib_ids = {r["lib_id"] for r in result["results"]}
        assert "Device:LED" in lib_ids

    def test_search_no_match(self, tmp_path):
        from commands.component_search import search_components

        lib_dir = self._make_test_library(tmp_path)
        result = search_components("FPGA_nonexistent", library_paths=[lib_dir])
        assert result["success"] is True
        assert result["result_count"] == 0

    def test_search_by_library(self, tmp_path):
        from commands.component_search import search_components

        lib_dir = self._make_test_library(tmp_path)
        result = search_components("", library="Device", library_paths=[lib_dir])
        assert result["success"] is True
        # Should return all symbols in Device library
        assert result["result_count"] == 3

    def test_result_has_metadata(self, tmp_path):
        from commands.component_search import search_components

        lib_dir = self._make_test_library(tmp_path)
        result = search_components("R", library_paths=[lib_dir])
        r = next(r for r in result["results"] if r["lib_id"] == "Device:R")
        assert r["description"] == "Resistor"
        assert "resistor" in r["keywords"]
        assert r["pin_count"] == 2
        assert "R_*" in r["footprint_filters"]

    def test_search_no_args_fails(self, tmp_path):
        from commands.component_search import search_components

        result = search_components("", library_paths=[])
        assert result["success"] is False

    def test_max_results(self, tmp_path):
        from commands.component_search import search_components

        lib_dir = self._make_test_library(tmp_path)
        result = search_components("", library="Device", max_results=2,
                                   library_paths=[lib_dir])
        assert len(result["results"]) <= 2

    def test_multi_term_search(self, tmp_path):
        from commands.component_search import search_components

        lib_dir = self._make_test_library(tmp_path)
        result = search_components("light diode", library_paths=[lib_dir])
        assert result["success"] is True
        lib_ids = {r["lib_id"] for r in result["results"]}
        assert "Device:LED" in lib_ids
        # R and C should NOT match "light diode"
        assert "Device:R" not in lib_ids
