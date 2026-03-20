"""
Schematic Layout Manager for KiCad Schematics

Provides spatial awareness for component placement: bounding box tracking,
collision detection, and relative placement helpers. Rebuilt from the
schematic file on load.

Uses sexpdata for read-only parsing (never sexpdata.dumps for writing).
"""

import math
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import sexpdata
from sexpdata import Symbol

from commands.grid_utils import snap_to_grid

logger = logging.getLogger("kicad_interface")


class BoundingBox:
    """Axis-aligned bounding box in schematic coordinates (mm)."""

    __slots__ = ("min_x", "min_y", "max_x", "max_y")

    def __init__(self, min_x: float, min_y: float, max_x: float, max_y: float):
        self.min_x = min_x
        self.min_y = min_y
        self.max_x = max_x
        self.max_y = max_y

    @property
    def width(self) -> float:
        return self.max_x - self.min_x

    @property
    def height(self) -> float:
        return self.max_y - self.min_y

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.min_x + self.max_x) / 2, (self.min_y + self.max_y) / 2)

    def overlaps(self, other: "BoundingBox") -> bool:
        """Check if this bbox overlaps with another."""
        return (
            self.min_x < other.max_x
            and self.max_x > other.min_x
            and self.min_y < other.max_y
            and self.max_y > other.min_y
        )

    def expanded(self, margin: float) -> "BoundingBox":
        """Return a new bbox expanded by margin on all sides."""
        return BoundingBox(
            self.min_x - margin,
            self.min_y - margin,
            self.max_x + margin,
            self.max_y + margin,
        )

    def to_dict(self) -> dict:
        return {
            "min_x": round(self.min_x, 4),
            "min_y": round(self.min_y, 4),
            "max_x": round(self.max_x, 4),
            "max_y": round(self.max_y, 4),
            "width": round(self.width, 4),
            "height": round(self.height, 4),
        }

    def __repr__(self):
        return (
            f"BoundingBox({self.min_x:.2f}, {self.min_y:.2f}, "
            f"{self.max_x:.2f}, {self.max_y:.2f})"
        )


def _rotate_point(x: float, y: float, angle_degrees: float) -> Tuple[float, float]:
    """Rotate a point around the origin by angle_degrees."""
    if angle_degrees == 0:
        return (x, y)
    angle_rad = math.radians(angle_degrees)
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    return (x * cos_a - y * sin_a, x * sin_a + y * cos_a)


def _extract_symbol_extents(symbol_def: list) -> List[Tuple[float, float]]:
    """Extract all boundary points from a symbol definition's graphics and pins.

    Walks the parsed sexpdata tree for rectangle, polyline, and pin elements.
    Returns a list of (x, y) points in symbol-local coordinates.
    """
    points: List[Tuple[float, float]] = []

    def _walk(sexp):
        if not isinstance(sexp, list) or len(sexp) == 0:
            return

        tag = sexp[0]

        # (rectangle (start x1 y1) (end x2 y2) ...)
        if tag == Symbol("rectangle"):
            for item in sexp[1:]:
                if isinstance(item, list) and len(item) >= 3:
                    if item[0] in (Symbol("start"), Symbol("end")):
                        points.append((float(item[1]), float(item[2])))
            return

        # (polyline (pts (xy x1 y1) (xy x2 y2) ...) ...)
        if tag == Symbol("polyline"):
            for item in sexp[1:]:
                if isinstance(item, list) and len(item) > 0 and item[0] == Symbol("pts"):
                    for pt in item[1:]:
                        if isinstance(pt, list) and len(pt) >= 3 and pt[0] == Symbol("xy"):
                            points.append((float(pt[1]), float(pt[2])))
            return

        # (pin type shape (at x y angle) (length L) ...)
        if tag == Symbol("pin"):
            for item in sexp[1:]:
                if isinstance(item, list) and len(item) >= 3 and item[0] == Symbol("at"):
                    points.append((float(item[1]), float(item[2])))
            return

        # Recurse into sub-expressions (sub-symbols like R_0_1, R_1_1)
        for item in sexp:
            if isinstance(item, list):
                _walk(item)

    _walk(symbol_def)
    return points


class SchematicLayout:
    """Spatial index of placed components in a KiCad schematic.

    Tracks bounding boxes and provides collision detection and relative
    placement helpers for the LLM agent.
    """

    def __init__(self):
        self._components: Dict[str, BoundingBox] = {}
        self._positions: Dict[str, Tuple[float, float]] = {}
        self._schematic_path: Optional[Path] = None

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    @classmethod
    def from_schematic(cls, schematic_path: Path) -> "SchematicLayout":
        """Build a SchematicLayout by parsing an existing .kicad_sch file."""
        layout = cls()
        layout._schematic_path = Path(schematic_path)

        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        sch_data = sexpdata.loads(content)

        # 1. Build a map of lib_id -> symbol definition extent points
        lib_extents: Dict[str, List[Tuple[float, float]]] = {}
        for item in sch_data:
            if isinstance(item, list) and item and item[0] == Symbol("lib_symbols"):
                for sym in item[1:]:
                    if (
                        isinstance(sym, list)
                        and len(sym) > 1
                        and sym[0] == Symbol("symbol")
                    ):
                        lib_id = str(sym[1]).strip('"')
                        lib_extents[lib_id] = _extract_symbol_extents(sym)

        # 2. Walk placed symbol instances
        for item in sch_data:
            if not (
                isinstance(item, list)
                and len(item) > 1
                and item[0] == Symbol("symbol")
            ):
                continue

            # Extract lib_id, position, rotation, and reference
            lib_id = None
            inst_x, inst_y, rotation = 0.0, 0.0, 0.0
            reference = None

            for sub in item[1:]:
                if not isinstance(sub, list) or len(sub) < 2:
                    continue
                if sub[0] == Symbol("lib_id"):
                    lib_id = str(sub[1]).strip('"')
                elif sub[0] == Symbol("at") and len(sub) >= 3:
                    inst_x = float(sub[1])
                    inst_y = float(sub[2])
                    rotation = float(sub[3]) if len(sub) >= 4 else 0.0
                elif sub[0] == Symbol("property"):
                    if len(sub) >= 3 and str(sub[1]).strip('"') == "Reference":
                        reference = str(sub[2]).strip('"')

            if not reference or not lib_id:
                continue
            # Skip template symbols placed offscreen
            if reference.startswith("_TEMPLATE"):
                continue

            layout._positions[reference] = (inst_x, inst_y)

            extent_pts = lib_extents.get(lib_id, [])
            if not extent_pts:
                # Fallback: give a minimal bbox around the placement point
                layout._components[reference] = BoundingBox(
                    inst_x - 2.54, inst_y - 2.54,
                    inst_x + 2.54, inst_y + 2.54,
                )
                continue

            # Rotate extent points and compute bbox
            rotated = [_rotate_point(px, py, rotation) for px, py in extent_pts]
            xs = [inst_x + p[0] for p in rotated]
            ys = [inst_y + p[1] for p in rotated]
            layout._components[reference] = BoundingBox(
                min(xs), min(ys), max(xs), max(ys)
            )

        logger.info(
            f"SchematicLayout loaded {len(layout._components)} components "
            f"from {schematic_path}"
        )
        return layout

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_component_bbox(self, reference: str) -> Optional[BoundingBox]:
        """Return the bounding box of a placed component, or None."""
        return self._components.get(reference)

    def get_all_bboxes(self) -> Dict[str, BoundingBox]:
        """Return a dict of all component bounding boxes (ref -> BoundingBox)."""
        return dict(self._components)

    def get_component_position(self, reference: str) -> Optional[Tuple[float, float]]:
        """Return the placement (x, y) of a component, or None."""
        return self._positions.get(reference)

    def check_collision(self, bbox: BoundingBox) -> List[str]:
        """Return references of components whose bboxes overlap with *bbox*."""
        return [
            ref for ref, comp_bbox in self._components.items()
            if comp_bbox.overlaps(bbox)
        ]

    @property
    def references(self) -> List[str]:
        return list(self._components.keys())

    # ------------------------------------------------------------------
    # Placement helpers
    # ------------------------------------------------------------------

    def suggest_position(
        self,
        near_ref: str,
        direction: str = "right",
        spacing: float = 5.08,
    ) -> Optional[Tuple[float, float]]:
        """Suggest a grid-snapped position adjacent to *near_ref*.

        Args:
            near_ref: Reference designator of the anchor component.
            direction: One of 'right', 'left', 'above', 'below'.
            spacing: Minimum gap between bounding boxes in mm (default 5.08 = 4 grid units).

        Returns:
            (x, y) tuple snapped to grid, or None if near_ref not found.
        """
        anchor = self._components.get(near_ref)
        if anchor is None:
            return None

        cx, cy = anchor.center
        half_w = anchor.width / 2
        half_h = anchor.height / 2

        if direction == "right":
            x = anchor.max_x + spacing + half_w
            y = cy
        elif direction == "left":
            x = anchor.min_x - spacing - half_w
            y = cy
        elif direction == "below":
            x = cx
            y = anchor.max_y + spacing + half_h
        elif direction == "above":
            x = cx
            y = anchor.min_y - spacing - half_h
        else:
            logger.warning(f"Unknown direction '{direction}', defaulting to right")
            x = anchor.max_x + spacing + half_w
            y = cy

        return snap_to_grid(x, y)

    def place_relative(
        self,
        anchor_ref: str,
        direction: str = "right",
        offset: float = 5.08,
    ) -> Optional[Tuple[float, float]]:
        """Find a non-colliding position near *anchor_ref*.

        Tries the suggested position first. If it collides, shifts further
        in the given direction until a clear spot is found (up to 10 attempts).

        Returns:
            (x, y) tuple snapped to grid, or None if anchor not found.
        """
        pos = self.suggest_position(anchor_ref, direction, offset)
        if pos is None:
            return None

        anchor = self._components[anchor_ref]
        step = 2.54  # one grid step

        for _ in range(10):
            # Build a test bbox the same size as the anchor
            half_w = anchor.width / 2
            half_h = anchor.height / 2
            test_bbox = BoundingBox(
                pos[0] - half_w, pos[1] - half_h,
                pos[0] + half_w, pos[1] + half_h,
            )
            collisions = self.check_collision(test_bbox)
            if not collisions:
                return pos
            # Shift further in the direction
            if direction == "right":
                pos = snap_to_grid(pos[0] + step, pos[1])
            elif direction == "left":
                pos = snap_to_grid(pos[0] - step, pos[1])
            elif direction == "below":
                pos = snap_to_grid(pos[0], pos[1] + step)
            elif direction == "above":
                pos = snap_to_grid(pos[0], pos[1] - step)

        return pos  # Best effort after 10 attempts

    # ------------------------------------------------------------------
    # Incremental update
    # ------------------------------------------------------------------

    def add_component(self, reference: str, bbox: BoundingBox, position: Tuple[float, float]):
        """Register a newly placed component in the layout."""
        self._components[reference] = bbox
        self._positions[reference] = position

    # ------------------------------------------------------------------
    # JSON summary for MCP tool
    # ------------------------------------------------------------------

    def get_layout_info(self) -> dict:
        """Return a JSON-serializable summary of the layout.

        Intended to be returned directly by the get_layout_info MCP tool.
        """
        components = {}
        for ref in sorted(self._components.keys()):
            bbox = self._components[ref]
            pos = self._positions.get(ref)
            components[ref] = {
                "position": {"x": pos[0], "y": pos[1]} if pos else None,
                "bbox": bbox.to_dict(),
            }

        # Compute overall bounds
        if self._components:
            all_bboxes = list(self._components.values())
            overall = BoundingBox(
                min(b.min_x for b in all_bboxes),
                min(b.min_y for b in all_bboxes),
                max(b.max_x for b in all_bboxes),
                max(b.max_y for b in all_bboxes),
            )
        else:
            overall = BoundingBox(0, 0, 0, 0)

        return {
            "component_count": len(self._components),
            "components": components,
            "overall_bounds": overall.to_dict(),
        }
