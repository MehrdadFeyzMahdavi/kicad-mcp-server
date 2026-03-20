"""
Wire Manager for KiCad Schematics

Handles wire creation and deletion using text manipulation to preserve file formatting.
All writes use direct text insertion/removal (never sexpdata.dumps()) to avoid
corrupting existing content such as symbol definitions and UUID formatting.
"""

import re
import uuid
import logging
from pathlib import Path
from typing import List, Optional

from commands.grid_utils import snap_to_grid, fmt_coord as _fmt, find_balanced_end as _find_balanced_end

logger = logging.getLogger("kicad_interface")


def _remove_block_from_text(content: str, block_start: int, block_end: int) -> str:
    """Remove a block and its surrounding whitespace from the text."""
    # Find start of the line containing block_start
    line_start = content.rfind('\n', 0, block_start)
    if line_start == -1:
        remove_start = 0
    else:
        prefix = content[line_start + 1:block_start]
        if prefix.strip() == '':
            remove_start = line_start + 1
        else:
            remove_start = block_start

    # Skip trailing whitespace + one newline
    remove_end = block_end
    while remove_end < len(content) and content[remove_end] in (' ', '\t'):
        remove_end += 1
    if remove_end < len(content) and content[remove_end] == '\n':
        remove_end += 1

    return content[:remove_start] + content[remove_end:]


class WireManager:
    """Manage wires in KiCad schematics using text manipulation"""

    @staticmethod
    def add_wire(
        schematic_path: Path,
        start_point: List[float],
        end_point: List[float],
        stroke_width: float = 0,
        stroke_type: str = "default",
    ) -> bool:
        """
        Add a wire to the schematic using text manipulation.

        Args:
            schematic_path: Path to .kicad_sch file
            start_point: [x, y] coordinates for wire start
            end_point: [x, y] coordinates for wire end
            stroke_width: Wire width (default 0 for standard)
            stroke_type: Stroke type (default, solid, dashed, etc.)

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            sp = snap_to_grid(start_point[0], start_point[1])
            ep = snap_to_grid(end_point[0], end_point[1])
            x1, y1 = _fmt(sp[0]), _fmt(sp[1])
            x2, y2 = _fmt(ep[0]), _fmt(ep[1])
            w = _fmt(stroke_width)
            new_uuid = str(uuid.uuid4())

            wire_block = (
                f"(wire (pts (xy {x1} {y1}) (xy {x2} {y2}))\n"
                f"    (stroke (width {w}) (type {stroke_type}))\n"
                f"    (uuid \"{new_uuid}\")\n"
                f"  )"
            )

            insert_at = content.rfind("(sheet_instances")
            if insert_at == -1:
                logger.error("No sheet_instances section found in schematic")
                return False

            content = content[:insert_at] + wire_block + "\n  " + content[insert_at:]

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(f"Successfully added wire from {start_point} to {end_point}")
            return True

        except Exception as e:
            logger.error(f"Error adding wire: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_polyline_wire(
        schematic_path: Path,
        points: List[List[float]],
        stroke_width: float = 0,
        stroke_type: str = "default",
    ) -> bool:
        """
        Add a multi-segment wire path as individual 2-point wire segments.

        Args:
            schematic_path: Path to .kicad_sch file
            points: List of [x, y] coordinates for each point in the path
            stroke_width: Wire width
            stroke_type: Stroke type

        Returns:
            True if successful, False otherwise
        """
        try:
            if len(points) < 2:
                logger.error("Polyline requires at least 2 points")
                return False

            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            w = _fmt(stroke_width)
            snapped = [snap_to_grid(p[0], p[1]) for p in points]
            segments = []
            for i in range(len(snapped) - 1):
                x1, y1 = _fmt(snapped[i][0]), _fmt(snapped[i][1])
                x2, y2 = _fmt(snapped[i + 1][0]), _fmt(snapped[i + 1][1])
                new_uuid = str(uuid.uuid4())
                segment = (
                    f"(wire (pts (xy {x1} {y1}) (xy {x2} {y2}))\n"
                    f"    (stroke (width {w}) (type {stroke_type}))\n"
                    f"    (uuid \"{new_uuid}\")\n"
                    f"  )"
                )
                segments.append(segment)

            insert_at = content.rfind("(sheet_instances")
            if insert_at == -1:
                logger.error("No sheet_instances section found in schematic")
                return False

            all_blocks = "\n  ".join(segments)
            content = content[:insert_at] + all_blocks + "\n  " + content[insert_at:]

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(
                f"Successfully added polyline wire with {len(points)} points "
                f"({len(segments)} segments)"
            )
            return True

        except Exception as e:
            logger.error(f"Error adding polyline wire: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_label(
        schematic_path: Path,
        text: str,
        position: List[float],
        label_type: str = "label",
        orientation: int = 0,
    ) -> bool:
        """
        Add a net label to the schematic using text manipulation.

        Args:
            schematic_path: Path to .kicad_sch file
            text: Label text (net name)
            position: [x, y] coordinates for label
            label_type: Type of label ('label', 'global_label', 'hierarchical_label')
            orientation: Rotation angle (0, 90, 180, 270)

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            sp = snap_to_grid(position[0], position[1])
            x, y = _fmt(sp[0]), _fmt(sp[1])
            new_uuid = str(uuid.uuid4())

            label_block = (
                f"({label_type} \"{text}\" (at {x} {y} {orientation})\n"
                f"    (fields_autoplaced yes)\n"
                f"    (effects (font (size 1.27 1.27)) (justify left bottom))\n"
                f"    (uuid \"{new_uuid}\")\n"
                f"  )"
            )

            insert_at = content.rfind("(sheet_instances")
            if insert_at == -1:
                logger.error("No sheet_instances section found in schematic")
                return False

            content = content[:insert_at] + label_block + "\n  " + content[insert_at:]

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(f"Successfully added label '{text}' at {position}")
            return True

        except Exception as e:
            logger.error(f"Error adding label: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_junction(
        schematic_path: Path, position: List[float], diameter: float = 0
    ) -> bool:
        """
        Add a junction (connection dot) to the schematic using text manipulation.

        Args:
            schematic_path: Path to .kicad_sch file
            position: [x, y] coordinates for junction
            diameter: Junction diameter (0 for default)

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            sp = snap_to_grid(position[0], position[1])
            x, y = _fmt(sp[0]), _fmt(sp[1])
            d = _fmt(diameter)
            new_uuid = str(uuid.uuid4())

            junction_block = (
                f"(junction (at {x} {y}) (diameter {d}) (color 0 0 0 0)\n"
                f"    (uuid \"{new_uuid}\")\n"
                f"  )"
            )

            insert_at = content.rfind("(sheet_instances")
            if insert_at == -1:
                logger.error("No sheet_instances section found in schematic")
                return False

            content = content[:insert_at] + junction_block + "\n  " + content[insert_at:]

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(f"Successfully added junction at {position}")
            return True

        except Exception as e:
            logger.error(f"Error adding junction: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def add_no_connect(schematic_path: Path, position: List[float]) -> bool:
        """
        Add a no-connect flag to the schematic using text manipulation.

        Args:
            schematic_path: Path to .kicad_sch file
            position: [x, y] coordinates for no-connect flag

        Returns:
            True if successful, False otherwise
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            sp = snap_to_grid(position[0], position[1])
            x, y = _fmt(sp[0]), _fmt(sp[1])
            new_uuid = str(uuid.uuid4())

            no_connect_block = (
                f"(no_connect (at {x} {y})\n"
                f"    (uuid \"{new_uuid}\")\n"
                f"  )"
            )

            insert_at = content.rfind("(sheet_instances")
            if insert_at == -1:
                logger.error("No sheet_instances section found in schematic")
                return False

            content = content[:insert_at] + no_connect_block + "\n  " + content[insert_at:]

            with open(schematic_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(f"Successfully added no-connect at {position}")
            return True

        except Exception as e:
            logger.error(f"Error adding no-connect: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def delete_wire(
        schematic_path: Path,
        start_point: List[float],
        end_point: List[float],
        tolerance: float = 0.5,
    ) -> bool:
        """
        Delete a wire from the schematic matching given start/end coordinates.

        Uses text-based search and removal to preserve file formatting.

        Args:
            schematic_path: Path to .kicad_sch file
            start_point: [x, y] coordinates for wire start
            end_point: [x, y] coordinates for wire end
            tolerance: Maximum coordinate difference to consider a match (mm)

        Returns:
            True if a wire was found and removed, False otherwise
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            sx, sy = start_point
            ex, ey = end_point
            xy_pattern = re.compile(r'\(xy\s+([\d\.\-eE]+)\s+([\d\.\-eE]+)\s*\)')

            pos = 0
            while True:
                idx = content.find('(wire ', pos)
                if idx == -1:
                    break

                block_end = _find_balanced_end(content, idx)
                if block_end is None:
                    pos = idx + 1
                    continue

                block_text = content[idx:block_end]
                xy_matches = xy_pattern.findall(block_text)

                if len(xy_matches) >= 2:
                    x1, y1 = float(xy_matches[0][0]), float(xy_matches[0][1])
                    x2, y2 = float(xy_matches[-1][0]), float(xy_matches[-1][1])

                    match_fwd = (
                        abs(x1 - sx) < tolerance
                        and abs(y1 - sy) < tolerance
                        and abs(x2 - ex) < tolerance
                        and abs(y2 - ey) < tolerance
                    )
                    match_rev = (
                        abs(x1 - ex) < tolerance
                        and abs(y1 - ey) < tolerance
                        and abs(x2 - sx) < tolerance
                        and abs(y2 - sy) < tolerance
                    )

                    if match_fwd or match_rev:
                        content = _remove_block_from_text(content, idx, block_end)
                        with open(schematic_path, "w", encoding="utf-8") as f:
                            f.write(content)
                        logger.info(f"Deleted wire from {start_point} to {end_point}")
                        return True

                pos = block_end

            logger.warning(f"No matching wire found for {start_point} to {end_point}")
            return False

        except Exception as e:
            logger.error(f"Error deleting wire: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def delete_label(
        schematic_path: Path,
        net_name: str,
        position: Optional[List[float]] = None,
        tolerance: float = 0.5,
    ) -> bool:
        """
        Delete a net label from the schematic by name (and optionally position).

        Matches all label types: label, global_label, hierarchical_label.
        Uses text-based search and removal to preserve file formatting.

        Args:
            schematic_path: Path to .kicad_sch file
            net_name: Net label text to match
            position: Optional [x, y] to disambiguate when multiple labels share a name
            tolerance: Maximum coordinate difference to consider a match (mm)

        Returns:
            True if a label was found and removed, False otherwise
        """
        try:
            with open(schematic_path, "r", encoding="utf-8") as f:
                content = f.read()

            at_pattern = re.compile(r'\(at\s+([\d\.\-eE]+)\s+([\d\.\-eE]+)')
            label_types = ('(label ', '(global_label ', '(hierarchical_label ')

            pos = 0
            while True:
                # Find the nearest label of any type
                idx = -1
                for lt in label_types:
                    found = content.find(lt, pos)
                    if found != -1 and (idx == -1 or found < idx):
                        idx = found
                if idx == -1:
                    break

                block_end = _find_balanced_end(content, idx)
                if block_end is None:
                    pos = idx + 1
                    continue

                block_text = content[idx:block_end]

                # Extract label text: (label "TEXT" ...) or (global_label "TEXT" ...) etc.
                label_match = re.match(
                    r'\((?:label|global_label|hierarchical_label)\s+"([^"]*)"',
                    block_text,
                )
                if not label_match or label_match.group(1) != net_name:
                    pos = block_end
                    continue

                # Optionally check position
                if position is not None:
                    at_match = at_pattern.search(block_text)
                    if at_match:
                        lx = float(at_match.group(1))
                        ly = float(at_match.group(2))
                        if not (
                            abs(lx - position[0]) < tolerance
                            and abs(ly - position[1]) < tolerance
                        ):
                            pos = block_end
                            continue
                    else:
                        pos = block_end
                        continue

                content = _remove_block_from_text(content, idx, block_end)
                with open(schematic_path, "w", encoding="utf-8") as f:
                    f.write(content)
                logger.info(f"Deleted label '{net_name}'")
                return True

            logger.warning(f"No matching label found for '{net_name}'")
            return False

        except Exception as e:
            logger.error(f"Error deleting label: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return False

    @staticmethod
    def create_orthogonal_path(
        start: List[float], end: List[float], prefer_horizontal_first: bool = True
    ) -> List[List[float]]:
        """
        Create an orthogonal (right-angle) path between two points

        Args:
            start: [x, y] start coordinates
            end: [x, y] end coordinates
            prefer_horizontal_first: If True, route horizontally first, else vertically first

        Returns:
            List of points defining the path: [start, corner, end]
        """
        x1, y1 = start
        x2, y2 = end

        if prefer_horizontal_first:
            # Route: start -> (x2, y1) -> end
            corner = [x2, y1]
        else:
            # Route: start -> (x1, y2) -> end
            corner = [x1, y2]

        # If start and end are already aligned, return direct path
        if x1 == x2 or y1 == y2:
            return [start, end]

        return [start, corner, end]
