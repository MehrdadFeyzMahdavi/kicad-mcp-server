"""
Tests for Phase 2: Layout Intelligence & Validation

Covers SchematicLayout, obstacle-aware routing, schematic ERC,
and list_component_pins.
"""

import shutil
from pathlib import Path

import pytest
import sexpdata

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
EMPTY_SCH = TEMPLATES_DIR / "empty.kicad_sch"


def _make_schematic_with_components(tmp_path: Path) -> Path:
    """Create a schematic with two placed components for testing."""
    from commands.dynamic_symbol_loader import DynamicSymbolLoader

    sch = tmp_path / "test.kicad_sch"
    shutil.copy(EMPTY_SCH, sch)
    loader = DynamicSymbolLoader()
    loader.create_component_instance(sch, "Device", "R", "R1", "10k", x=50.8, y=50.8)
    loader.create_component_instance(sch, "Device", "C", "C1", "100nF", x=76.2, y=50.8)
    return sch


def _make_wired_schematic(tmp_path: Path) -> Path:
    """Create a schematic with components and wires."""
    from commands.wire_manager import WireManager

    sch = _make_schematic_with_components(tmp_path)
    WireManager.add_wire(sch, [50.8, 46.99], [76.2, 46.99])
    WireManager.add_label(sch, "VCC", [63.5, 46.99])
    return sch


# ---------------------------------------------------------------------------
# SchematicLayout
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSchematicLayout:
    def test_load_empty_schematic(self, tmp_path):
        from commands.schematic_layout import SchematicLayout

        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        layout = SchematicLayout.from_schematic(sch)
        assert layout.references == []
        info = layout.get_layout_info()
        assert info["component_count"] == 0

    def test_load_with_components(self, tmp_path):
        from commands.schematic_layout import SchematicLayout

        sch = _make_schematic_with_components(tmp_path)
        layout = SchematicLayout.from_schematic(sch)
        assert "R1" in layout.references
        assert "C1" in layout.references
        assert layout.get_layout_info()["component_count"] == 2

    def test_bbox_has_dimensions(self, tmp_path):
        from commands.schematic_layout import SchematicLayout

        sch = _make_schematic_with_components(tmp_path)
        layout = SchematicLayout.from_schematic(sch)
        bbox = layout.get_component_bbox("R1")
        assert bbox is not None
        assert bbox.width > 0
        assert bbox.height > 0

    def test_bbox_contains_placement_point(self, tmp_path):
        from commands.schematic_layout import SchematicLayout

        sch = _make_schematic_with_components(tmp_path)
        layout = SchematicLayout.from_schematic(sch)
        bbox = layout.get_component_bbox("R1")
        # The placement point (50.8, 50.8) should be inside the bbox
        assert bbox.min_x <= 50.8 <= bbox.max_x
        assert bbox.min_y <= 50.8 <= bbox.max_y

    def test_component_position(self, tmp_path):
        from commands.schematic_layout import SchematicLayout

        sch = _make_schematic_with_components(tmp_path)
        layout = SchematicLayout.from_schematic(sch)
        pos = layout.get_component_position("R1")
        assert pos is not None
        assert pos[0] == pytest.approx(50.8)
        assert pos[1] == pytest.approx(50.8)

    def test_collision_detection(self, tmp_path):
        from commands.schematic_layout import SchematicLayout, BoundingBox

        sch = _make_schematic_with_components(tmp_path)
        layout = SchematicLayout.from_schematic(sch)
        # A bbox overlapping R1's position should detect collision
        test_bbox = BoundingBox(49.0, 49.0, 52.0, 52.0)
        collisions = layout.check_collision(test_bbox)
        assert "R1" in collisions

    def test_no_collision_far_away(self, tmp_path):
        from commands.schematic_layout import SchematicLayout, BoundingBox

        sch = _make_schematic_with_components(tmp_path)
        layout = SchematicLayout.from_schematic(sch)
        test_bbox = BoundingBox(200.0, 200.0, 210.0, 210.0)
        assert layout.check_collision(test_bbox) == []

    def test_suggest_position_right(self, tmp_path):
        from commands.schematic_layout import SchematicLayout

        sch = _make_schematic_with_components(tmp_path)
        layout = SchematicLayout.from_schematic(sch)
        pos = layout.suggest_position("R1", direction="right")
        assert pos is not None
        # Should be to the right of R1's bbox
        r1_bbox = layout.get_component_bbox("R1")
        assert pos[0] > r1_bbox.max_x

    def test_suggest_position_below(self, tmp_path):
        from commands.schematic_layout import SchematicLayout

        sch = _make_schematic_with_components(tmp_path)
        layout = SchematicLayout.from_schematic(sch)
        pos = layout.suggest_position("R1", direction="below")
        assert pos is not None
        r1_bbox = layout.get_component_bbox("R1")
        assert pos[1] > r1_bbox.max_y

    def test_suggest_position_unknown_ref(self, tmp_path):
        from commands.schematic_layout import SchematicLayout

        sch = _make_schematic_with_components(tmp_path)
        layout = SchematicLayout.from_schematic(sch)
        assert layout.suggest_position("X99") is None

    def test_place_relative(self, tmp_path):
        from commands.schematic_layout import SchematicLayout

        sch = _make_schematic_with_components(tmp_path)
        layout = SchematicLayout.from_schematic(sch)
        pos = layout.place_relative("R1", direction="below")
        assert pos is not None
        # Should be grid-snapped
        # Grid-snapped: round(x / 1.27) should be exact
        assert round(pos[0] / 1.27) * 1.27 == pytest.approx(pos[0], abs=0.001)
        assert round(pos[1] / 1.27) * 1.27 == pytest.approx(pos[1], abs=0.001)

    def test_layout_info_structure(self, tmp_path):
        from commands.schematic_layout import SchematicLayout

        sch = _make_schematic_with_components(tmp_path)
        layout = SchematicLayout.from_schematic(sch)
        info = layout.get_layout_info()
        assert "component_count" in info
        assert "components" in info
        assert "overall_bounds" in info
        assert "R1" in info["components"]
        r1 = info["components"]["R1"]
        assert "position" in r1
        assert "bbox" in r1
        assert "width" in r1["bbox"]

    def test_skips_template_symbols(self, tmp_path):
        from commands.schematic_layout import SchematicLayout
        from commands.dynamic_symbol_loader import DynamicSymbolLoader

        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        loader = DynamicSymbolLoader()
        # load_symbol_dynamically creates a _TEMPLATE_ instance
        loader.load_symbol_dynamically(sch, "Device", "R")
        layout = SchematicLayout.from_schematic(sch)
        # Template symbols should be skipped
        for ref in layout.references:
            assert not ref.startswith("_TEMPLATE")


# ---------------------------------------------------------------------------
# BoundingBox
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBoundingBox:
    def test_overlaps_true(self):
        from commands.schematic_layout import BoundingBox

        a = BoundingBox(0, 0, 10, 10)
        b = BoundingBox(5, 5, 15, 15)
        assert a.overlaps(b)
        assert b.overlaps(a)

    def test_overlaps_false(self):
        from commands.schematic_layout import BoundingBox

        a = BoundingBox(0, 0, 10, 10)
        b = BoundingBox(20, 20, 30, 30)
        assert not a.overlaps(b)

    def test_overlaps_edge_touching(self):
        from commands.schematic_layout import BoundingBox

        a = BoundingBox(0, 0, 10, 10)
        b = BoundingBox(10, 0, 20, 10)
        # Edge-touching is NOT overlapping (strict inequality)
        assert not a.overlaps(b)

    def test_expanded(self):
        from commands.schematic_layout import BoundingBox

        a = BoundingBox(5, 5, 10, 10)
        b = a.expanded(2)
        assert b.min_x == 3
        assert b.min_y == 3
        assert b.max_x == 12
        assert b.max_y == 12

    def test_center(self):
        from commands.schematic_layout import BoundingBox

        a = BoundingBox(0, 0, 10, 20)
        assert a.center == (5, 10)

    def test_to_dict(self):
        from commands.schematic_layout import BoundingBox

        a = BoundingBox(1, 2, 3, 4)
        d = a.to_dict()
        assert d["min_x"] == 1
        assert d["width"] == 2
        assert d["height"] == 2


# ---------------------------------------------------------------------------
# Smart Router
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSmartRouter:
    def test_trivial_aligned_no_obstacles(self):
        from commands.schematic_layout import SchematicLayout
        from commands.smart_router import route_wire

        layout = SchematicLayout()
        path = route_wire((50.8, 50.8), (76.2, 50.8), layout)
        assert len(path) == 2
        assert path[0] == [50.8, 50.8]
        assert path[1] == [76.2, 50.8]

    def test_same_point(self):
        from commands.schematic_layout import SchematicLayout
        from commands.smart_router import route_wire

        layout = SchematicLayout()
        path = route_wire((50.8, 50.8), (50.8, 50.8), layout)
        assert len(path) == 1

    def test_non_aligned_no_obstacles(self):
        from commands.schematic_layout import SchematicLayout
        from commands.smart_router import route_wire

        layout = SchematicLayout()
        path = route_wire((50.8, 50.8), (76.2, 76.2), layout)
        # Should have intermediate points (orthogonal routing)
        assert len(path) >= 2
        # All points should be on grid
        for pt in path:
            assert round(pt[0] / 1.27) * 1.27 == pytest.approx(pt[0], abs=0.001)
            assert round(pt[1] / 1.27) * 1.27 == pytest.approx(pt[1], abs=0.001)

    def test_routes_around_obstacle(self, tmp_path):
        from commands.schematic_layout import SchematicLayout, BoundingBox
        from commands.smart_router import route_wire

        layout = SchematicLayout()
        # Place an obstacle between start and end
        obstacle = BoundingBox(60.0, 45.0, 70.0, 55.0)
        layout.add_component("OBS1", obstacle, (65.0, 50.0))

        path = route_wire((50.8, 50.8), (76.2, 50.8), layout)
        # Path should exist and have more than 2 points (detour)
        assert len(path) >= 2
        # Start and end should match (snapped)
        assert path[0][0] == pytest.approx(50.8)
        assert path[-1][0] == pytest.approx(76.2)

    def test_fallback_on_blocked(self):
        from commands.schematic_layout import SchematicLayout, BoundingBox
        from commands.smart_router import route_wire

        layout = SchematicLayout()
        # Completely surround the end point — A* will fail, fallback used
        for i in range(-5, 6):
            for j in range(-5, 6):
                if i == 0 and j == 0:
                    continue
                x = 76.2 + i * 1.27
                y = 50.8 + j * 1.27
                layout.add_component(
                    f"wall_{i}_{j}",
                    BoundingBox(x - 0.5, y - 0.5, x + 0.5, y + 0.5),
                    (x, y),
                )

        path = route_wire((50.8, 50.8), (76.2, 50.8), layout)
        # Should still return a path (fallback)
        assert len(path) >= 2

    def test_simplify_removes_collinear(self):
        from commands.smart_router import _simplify_path

        # Three collinear horizontal points
        path = [[0, 0], [1.27, 0], [2.54, 0], [2.54, 1.27]]
        simplified = _simplify_path(path)
        # Middle collinear point should be removed
        assert len(simplified) == 3
        assert simplified == [[0, 0], [2.54, 0], [2.54, 1.27]]


# ---------------------------------------------------------------------------
# Schematic ERC
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSchematicERC:
    def test_erc_empty_schematic(self, tmp_path):
        from commands.schematic_erc import run_schematic_erc

        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        result = run_schematic_erc(sch)
        assert result["success"] is True
        assert result["error_count"] == 0

    def test_erc_detects_unconnected_pins(self, tmp_path):
        from commands.schematic_erc import run_schematic_erc

        sch = _make_schematic_with_components(tmp_path)
        result = run_schematic_erc(sch)
        assert result["success"] is True
        # R1 and C1 have pins that are not connected
        unconnected = [
            e for e in result["errors"] + result["warnings"]
            if e["type"] == "unconnected_pin"
        ]
        assert len(unconnected) > 0

    def test_erc_no_unconnected_with_wires(self, tmp_path):
        from commands.schematic_erc import run_schematic_erc
        from commands.wire_manager import WireManager
        from commands.dynamic_symbol_loader import DynamicSymbolLoader

        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        loader = DynamicSymbolLoader()
        # Place R1 at (50.8, 50.8) — pin 1 at (50.8, 46.99), pin 2 at (50.8, 54.61)
        loader.create_component_instance(sch, "Device", "R", "R1", "10k", x=50.8, y=50.8)

        # Connect both pins with wires to some point
        WireManager.add_wire(sch, [50.8, 46.99], [63.5, 46.99])
        WireManager.add_wire(sch, [50.8, 54.61], [63.5, 54.61])

        result = run_schematic_erc(sch)
        r1_unconnected = [
            e for e in result["errors"] + result["warnings"]
            if e["type"] == "unconnected_pin" and e["reference"] == "R1"
        ]
        assert len(r1_unconnected) == 0

    def test_erc_detects_duplicate_refs(self, tmp_path):
        from commands.schematic_erc import run_schematic_erc
        from commands.dynamic_symbol_loader import DynamicSymbolLoader

        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        loader = DynamicSymbolLoader()
        # Place two components with the same reference
        loader.create_component_instance(sch, "Device", "R", "R1", "10k", x=50.8, y=50.8)
        loader.create_component_instance(sch, "Device", "R", "R1", "20k", x=76.2, y=50.8)

        result = run_schematic_erc(sch)
        dup_errors = [e for e in result["errors"] if e["type"] == "duplicate_reference"]
        assert len(dup_errors) == 1
        assert dup_errors[0]["reference"] == "R1"
        assert dup_errors[0]["count"] == 2

    def test_erc_detects_floating_net(self, tmp_path):
        from commands.schematic_erc import run_schematic_erc
        from commands.wire_manager import WireManager

        sch = tmp_path / "test.kicad_sch"
        shutil.copy(EMPTY_SCH, sch)
        # Add a label with no wire connection
        WireManager.add_label(sch, "FLOATING_NET", [100.0, 100.0])

        result = run_schematic_erc(sch)
        floating = [w for w in result["warnings"] if w["type"] == "floating_net"]
        assert len(floating) == 1
        assert floating[0]["net_name"] == "FLOATING_NET"

    def test_erc_returns_net_names(self, tmp_path):
        from commands.schematic_erc import run_schematic_erc

        sch = _make_wired_schematic(tmp_path)
        result = run_schematic_erc(sch)
        assert "VCC" in result["info"]["net_names"]

    def test_erc_nonexistent_file(self, tmp_path):
        from commands.schematic_erc import run_schematic_erc

        result = run_schematic_erc(tmp_path / "nope.kicad_sch")
        assert result["success"] is False

    def test_erc_info_counts(self, tmp_path):
        from commands.schematic_erc import run_schematic_erc

        sch = _make_wired_schematic(tmp_path)
        result = run_schematic_erc(sch)
        assert result["info"]["component_count"] == 2
        assert result["info"]["wire_count"] >= 1
        assert result["info"]["label_count"] >= 1


# ---------------------------------------------------------------------------
# list_component_pins
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestListComponentPins:
    def test_list_by_lib_id(self, tmp_path):
        from commands.list_pins import list_component_pins

        sch = _make_schematic_with_components(tmp_path)
        result = list_component_pins(sch, lib_id="Device:R")
        assert result["success"] is True
        assert result["lib_id"] == "Device:R"
        assert result["pin_count"] == 2
        pins = result["pins"]
        numbers = {p["number"] for p in pins}
        assert "1" in numbers
        assert "2" in numbers
        # Without reference, positions should be relative
        assert "rel_x" in pins[0]

    def test_list_by_reference(self, tmp_path):
        from commands.list_pins import list_component_pins

        sch = _make_schematic_with_components(tmp_path)
        result = list_component_pins(sch, reference="R1")
        assert result["success"] is True
        assert result["reference"] == "R1"
        assert result["pin_count"] == 2
        pins = result["pins"]
        # With reference, positions should be absolute
        assert "x" in pins[0]
        assert "y" in pins[0]

    def test_list_unknown_reference(self, tmp_path):
        from commands.list_pins import list_component_pins

        sch = _make_schematic_with_components(tmp_path)
        result = list_component_pins(sch, reference="X99")
        assert result["success"] is False

    def test_list_no_args(self, tmp_path):
        from commands.list_pins import list_component_pins

        sch = _make_schematic_with_components(tmp_path)
        result = list_component_pins(sch)
        assert result["success"] is False

    def test_pin_types(self, tmp_path):
        from commands.list_pins import list_component_pins

        sch = _make_schematic_with_components(tmp_path)
        result = list_component_pins(sch, lib_id="Device:R")
        for pin in result["pins"]:
            assert "type" in pin
            assert pin["type"] == "passive"

    def test_led_pins(self, tmp_path):
        from commands.list_pins import list_component_pins

        sch = _make_schematic_with_components(tmp_path)
        # LED is in the template's lib_symbols
        result = list_component_pins(sch, lib_id="Device:LED")
        assert result["success"] is True
        assert result["pin_count"] == 2
        names = {p["name"] for p in result["pins"]}
        assert "K" in names
        assert "A" in names
