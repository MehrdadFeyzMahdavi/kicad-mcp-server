"""
Tests for the text-based wire_manager rewrite.

Validates that all WireManager operations use text manipulation (not sexpdata.dumps())
and that the critical "add component -> add wire" sequence no longer corrupts files.
"""

import re
import shutil
import tempfile
from pathlib import Path

import pytest
import sexpdata

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
EMPTY_SCH = TEMPLATES_DIR / "empty.kicad_sch"

_WIRE_SCH = """\
(kicad_sch (version 20250114) (generator "test")
  (uuid aaaaaaaa-0000-0000-0000-000000000000)
  (paper "A4")
  (wire (pts (xy 10 20) (xy 30 20))
    (stroke (width 0) (type default))
    (uuid bbbbbbbb-0000-0000-0000-000000000001)
  )
  (label "VCC" (at 50 50 0)
    (effects (font (size 1.27 1.27)) (justify left bottom))
    (uuid cccccccc-0000-0000-0000-000000000002)
  )
  (sheet_instances (path "/" (page "1")))
)
"""


def _count_elements(content: str, element_type: str) -> int:
    """Count top-level elements of a given type via sexpdata parse."""
    data = sexpdata.loads(content)
    return sum(
        1
        for item in data
        if isinstance(item, list)
        and item
        and item[0] == sexpdata.Symbol(element_type)
    )


def _all_uuids(content: str) -> list:
    """Extract all UUIDs from file content."""
    return re.findall(r'uuid\s+"?([a-f0-9-]+)"?', content)


# ---------------------------------------------------------------------------
# Grid snapping utility
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSnapToGrid:
    def setup_method(self):
        from commands.grid_utils import snap_to_grid
        self.snap = snap_to_grid

    def test_already_on_grid(self):
        assert self.snap(50.8, 50.8) == (50.8, 50.8)

    def test_snaps_to_nearest(self):
        # 10.0 -> nearest 1.27 multiple is 10.16 (8*1.27=10.16)
        x, y = self.snap(10.0, 20.0)
        assert x == pytest.approx(10.16)
        assert y == pytest.approx(20.32)

    def test_zero(self):
        assert self.snap(0, 0) == (0, 0)

    def test_negative_coords(self):
        x, y = self.snap(-5.0, -5.0)
        assert x == pytest.approx(-5.08)  # -4 * 1.27
        assert y == pytest.approx(-5.08)

    def test_custom_grid(self):
        x, y = self.snap(10.0, 10.0, grid=2.54)
        assert x == pytest.approx(10.16)
        assert y == pytest.approx(10.16)

    def test_no_floating_point_artifacts(self):
        x, y = self.snap(1.27, 2.54)
        # Should be exact, no 1.2700000001 etc.
        assert x == 1.27
        assert y == 2.54


# ---------------------------------------------------------------------------
# Add operations — verify text insertion preserves formatting
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAddWireTextBased:
    def setup_method(self):
        from commands.wire_manager import WireManager
        self.WireManager = WireManager

    def test_add_wire_creates_valid_sexp(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        assert self.WireManager.add_wire(sch, [10.0, 20.0], [30.0, 20.0])
        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)  # must parse
        assert _count_elements(content, "wire") == 1

    def test_add_wire_preserves_lib_symbols(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        original = sch.read_text(encoding="utf-8")
        # Extract lib_symbols block from original
        orig_lib_start = original.find("(lib_symbols")
        assert orig_lib_start != -1

        self.WireManager.add_wire(sch, [10.0, 20.0], [30.0, 20.0])
        modified = sch.read_text(encoding="utf-8")
        mod_lib_start = modified.find("(lib_symbols")
        assert mod_lib_start != -1
        # lib_symbols content should be byte-identical
        # Find the end of lib_symbols in both
        assert '(symbol "Device:R"' in modified
        assert '(symbol "Device:C"' in modified
        assert '(symbol "Device:LED"' in modified

    def test_add_multiple_wires(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        self.WireManager.add_wire(sch, [10.0, 20.0], [30.0, 20.0])
        self.WireManager.add_wire(sch, [40.0, 50.0], [60.0, 50.0])
        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        assert _count_elements(content, "wire") == 2

    def test_add_wire_unique_uuids(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        self.WireManager.add_wire(sch, [10.0, 20.0], [30.0, 20.0])
        self.WireManager.add_wire(sch, [40.0, 50.0], [60.0, 50.0])
        uuids = _all_uuids(sch.read_text(encoding="utf-8"))
        assert len(uuids) == len(set(uuids)), "All UUIDs must be unique"

    def test_add_wire_integer_coords_formatted_cleanly(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        # Use grid-aligned coords (multiples of 1.27mm)
        self.WireManager.add_wire(sch, [50.8, 50.8], [76.2, 50.8])
        content = sch.read_text(encoding="utf-8")
        # Integer-valued floats should render without decimal
        assert "(xy 50.8 50.8)" in content
        assert "(xy 76.2 50.8)" in content

    def test_add_wire_coords_snapped_to_grid(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        # Off-grid coords should snap to nearest 1.27mm grid
        # 10.0 -> 10.16 (8*1.27), 20.0 -> 20.32 (16*1.27)
        self.WireManager.add_wire(sch, [10.0, 20.0], [30.0, 20.0])
        content = sch.read_text(encoding="utf-8")
        assert "(xy 10.16 20.32)" in content
        assert "(xy 30.48 20.32)" in content

    def test_add_wire_no_sexpdata_dumps(self, tmp_path):
        """The output must NOT look like sexpdata.dumps() compacted output."""
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        self.WireManager.add_wire(sch, [10.0, 20.0], [30.0, 20.0])
        content = sch.read_text(encoding="utf-8")
        # sexpdata.dumps() produces single-line output without indentation
        # Our text-based output should have newlines and indentation
        assert "\n" in content
        # lib_symbols should still be multi-line (not compacted)
        lines = content.split("\n")
        assert len(lines) > 10, "File should be multi-line, not compacted"


@pytest.mark.unit
class TestAddPolylineWireTextBased:
    def setup_method(self):
        from commands.wire_manager import WireManager
        self.WireManager = WireManager

    def test_polyline_creates_segments(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        points = [[10.0, 20.0], [30.0, 20.0], [30.0, 40.0]]
        assert self.WireManager.add_polyline_wire(sch, points)
        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        # 3 points -> 2 wire segments
        assert _count_elements(content, "wire") == 2

    def test_polyline_two_points_creates_one_segment(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        assert self.WireManager.add_polyline_wire(sch, [[10.0, 20.0], [30.0, 20.0]])
        content = sch.read_text(encoding="utf-8")
        assert _count_elements(content, "wire") == 1

    def test_polyline_fewer_than_two_points_fails(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        assert not self.WireManager.add_polyline_wire(sch, [[10.0, 20.0]])

    def test_polyline_unique_uuids_per_segment(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        self.WireManager.add_polyline_wire(
            sch, [[10.0, 20.0], [30.0, 20.0], [30.0, 40.0], [50.0, 40.0]]
        )
        uuids = _all_uuids(sch.read_text(encoding="utf-8"))
        assert len(uuids) == len(set(uuids))


@pytest.mark.unit
class TestAddLabelTextBased:
    def setup_method(self):
        from commands.wire_manager import WireManager
        self.WireManager = WireManager

    def test_add_label_valid_sexp(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        assert self.WireManager.add_label(sch, "VCC", [50.0, 50.0])
        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        assert _count_elements(content, "label") == 1

    def test_add_label_text_in_output(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        self.WireManager.add_label(sch, "MY_NET", [50.0, 50.0])
        assert '"MY_NET"' in sch.read_text(encoding="utf-8")

    def test_add_global_label(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        assert self.WireManager.add_label(
            sch, "GND", [50.0, 50.0], label_type="global_label"
        )
        content = sch.read_text(encoding="utf-8")
        assert "(global_label" in content


@pytest.mark.unit
class TestAddJunctionTextBased:
    def setup_method(self):
        from commands.wire_manager import WireManager
        self.WireManager = WireManager

    def test_add_junction_valid_sexp(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        assert self.WireManager.add_junction(sch, [50.0, 50.0])
        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        assert _count_elements(content, "junction") == 1


@pytest.mark.unit
class TestAddNoConnectTextBased:
    def setup_method(self):
        from commands.wire_manager import WireManager
        self.WireManager = WireManager

    def test_add_no_connect_valid_sexp(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        assert self.WireManager.add_no_connect(sch, [50.0, 50.0])
        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        assert _count_elements(content, "no_connect") == 1


# ---------------------------------------------------------------------------
# Delete operations — verify text-based removal
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDeleteWireTextBased:
    def setup_method(self):
        from commands.wire_manager import WireManager
        self.WireManager = WireManager

    def test_exact_match(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_WIRE_SCH, encoding="utf-8")
        assert self.WireManager.delete_wire(sch, [10.0, 20.0], [30.0, 20.0])
        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        assert _count_elements(content, "wire") == 0

    def test_reversed_match(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_WIRE_SCH, encoding="utf-8")
        assert self.WireManager.delete_wire(sch, [30.0, 20.0], [10.0, 20.0])

    def test_within_tolerance(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_WIRE_SCH, encoding="utf-8")
        assert self.WireManager.delete_wire(sch, [10.3, 20.3], [30.3, 20.3], tolerance=0.5)

    def test_outside_tolerance(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_WIRE_SCH, encoding="utf-8")
        assert not self.WireManager.delete_wire(
            sch, [10.6, 20.0], [30.0, 20.0], tolerance=0.5
        )

    def test_preserves_label(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_WIRE_SCH, encoding="utf-8")
        self.WireManager.delete_wire(sch, [10.0, 20.0], [30.0, 20.0])
        content = sch.read_text(encoding="utf-8")
        assert _count_elements(content, "label") == 1

    def test_no_match_returns_false(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        assert not self.WireManager.delete_wire(sch, [99.0, 99.0], [100.0, 100.0])

    def test_nonexistent_file_returns_false(self, tmp_path):
        assert not self.WireManager.delete_wire(
            tmp_path / "nope.kicad_sch", [0, 0], [10, 10]
        )


@pytest.mark.unit
class TestDeleteLabelTextBased:
    def setup_method(self):
        from commands.wire_manager import WireManager
        self.WireManager = WireManager

    def test_delete_by_name(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_WIRE_SCH, encoding="utf-8")
        assert self.WireManager.delete_label(sch, "VCC")
        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        assert _count_elements(content, "label") == 0

    def test_delete_with_position(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_WIRE_SCH, encoding="utf-8")
        assert self.WireManager.delete_label(sch, "VCC", position=[50.0, 50.0])

    def test_position_mismatch(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_WIRE_SCH, encoding="utf-8")
        assert not self.WireManager.delete_label(
            sch, "VCC", position=[99.0, 99.0], tolerance=0.5
        )

    def test_preserves_wire(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        sch.write_text(_WIRE_SCH, encoding="utf-8")
        self.WireManager.delete_label(sch, "VCC")
        content = sch.read_text(encoding="utf-8")
        assert _count_elements(content, "wire") == 1

    def test_nonexistent_label_returns_false(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        assert not self.WireManager.delete_label(sch, "NONEXISTENT")

    def test_delete_global_label(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        self.WireManager.add_label(sch, "GND", [50.8, 50.8], label_type="global_label")
        assert "(global_label" in sch.read_text(encoding="utf-8")
        assert self.WireManager.delete_label(sch, "GND")
        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        assert "(global_label" not in content


# ---------------------------------------------------------------------------
# Critical regression: add component -> add wire must not corrupt
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestComponentThenWireSequence:
    """Regression test for the sexpdata corruption bug.

    The old wire_manager used sexpdata.dumps() which would reformat the entire
    file, corrupting symbol definitions injected by DynamicSymbolLoader's
    text manipulation. This sequence must now be safe.
    """

    def setup_method(self):
        from commands.wire_manager import WireManager
        from commands.dynamic_symbol_loader import DynamicSymbolLoader
        self.WireManager = WireManager
        self.loader = DynamicSymbolLoader()

    def test_add_components_then_wires(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)

        # Step 1: Add components (text-based via DynamicSymbolLoader)
        self.loader.create_component_instance(
            sch, "Device", "R", "R1", "10k", x=50.8, y=50.8
        )
        self.loader.create_component_instance(
            sch, "Device", "C", "C1", "100nF", x=76.2, y=50.8
        )

        # Step 2: Add wires (text-based via WireManager)
        assert self.WireManager.add_wire(sch, [50.8, 50.8], [76.2, 50.8])
        assert self.WireManager.add_label(sch, "VCC", [63.5, 50.8])
        assert self.WireManager.add_junction(sch, [63.5, 50.8])

        # Verify: file parses correctly
        content = sch.read_text(encoding="utf-8")
        data = sexpdata.loads(content)

        # Verify: all elements present
        assert _count_elements(content, "wire") == 1
        assert _count_elements(content, "label") == 1
        assert _count_elements(content, "junction") == 1
        assert _count_elements(content, "symbol") == 2

        # Verify: lib_symbols section survived
        lib_symbols = [
            i
            for i in data
            if isinstance(i, list)
            and i
            and i[0] == sexpdata.Symbol("lib_symbols")
        ]
        assert len(lib_symbols) == 1, "lib_symbols must survive wire operations"

        # Verify: symbol definitions intact
        assert '(symbol "Device:R"' in content
        assert '(symbol "Device:C"' in content

        # Verify: UUIDs unique
        uuids = _all_uuids(content)
        assert len(uuids) == len(set(uuids)), "All UUIDs must be unique"

    def test_add_components_then_polyline(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)

        self.loader.create_component_instance(
            sch, "Device", "R", "R1", "10k", x=50.8, y=50.8
        )

        path_pts = self.WireManager.create_orthogonal_path(
            [50.8, 50.8], [76.2, 76.2]
        )
        assert self.WireManager.add_polyline_wire(sch, path_pts)

        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        # 3 points -> 2 segments
        assert _count_elements(content, "wire") == 2
        assert '(symbol "Device:R"' in content

    def test_add_wire_then_delete_then_add_again(self, tmp_path):
        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)

        self.loader.create_component_instance(
            sch, "Device", "R", "R1", "10k", x=50.8, y=50.8
        )

        # Add, delete, re-add
        assert self.WireManager.add_wire(sch, [50.8, 50.8], [76.2, 50.8])
        assert self.WireManager.delete_wire(sch, [50.8, 50.8], [76.2, 50.8])
        assert self.WireManager.add_wire(sch, [50.8, 50.8], [101.6, 50.8])

        content = sch.read_text(encoding="utf-8")
        sexpdata.loads(content)
        assert _count_elements(content, "wire") == 1
        assert '(symbol "Device:R"' in content
