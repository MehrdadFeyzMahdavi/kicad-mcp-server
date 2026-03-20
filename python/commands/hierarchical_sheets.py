"""
Hierarchical Sheet Support for KiCad Schematics

Enables creating sub-sheets, defining hierarchical pins, and connecting
nets across sheet boundaries. All writes use text manipulation.

KiCad hierarchical sheet format (inside parent .kicad_sch):

  (sheet (at X Y) (size W H)
    (stroke (width 0.0001) (type solid))
    (fill (color 0 0 0 0.0000))
    (uuid "...")
    (property "Sheetname" "SubSheet" (at X Y 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Sheetfile" "subsheet.kicad_sch" (at X Y 0)
      (effects (font (size 1.27 1.27)))
    )
    (pin "NET_NAME" input (at X Y ANGLE)
      (effects (font (size 1.27 1.27)))
      (uuid "...")
    )
  )

Inside the sub-sheet .kicad_sch, corresponding hierarchical labels are used:

  (hierarchical_label "NET_NAME" (at X Y ANGLE)
    (effects (font (size 1.27 1.27)))
    (uuid "...")
  )
"""

import uuid
import logging
import os
import shutil
from pathlib import Path
from typing import List, Optional

from commands.grid_utils import snap_to_grid, fmt_coord as _fmt, find_balanced_end as _find_balanced_end

logger = logging.getLogger("kicad_interface")

# Minimal empty schematic template for new sub-sheets
_SUBSHEET_TEMPLATE = """\
(kicad_sch (version 20250114) (generator "KiCAD-MCP-Server")

  (uuid {uuid})

  (paper "A4")

  (lib_symbols
  )

  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


def create_hierarchical_sheet(
    parent_schematic_path: Path,
    sheet_name: str,
    sheet_file: str,
    x: float = 127.0,
    y: float = 76.2,
    width: float = 25.4,
    height: float = 25.4,
) -> dict:
    """Create a hierarchical sheet reference in the parent schematic.

    Also creates the sub-sheet .kicad_sch file if it doesn't exist.

    Args:
        parent_schematic_path: Path to the parent .kicad_sch file.
        sheet_name: Display name for the sheet (e.g. "Power Supply").
        sheet_file: Filename for the sub-sheet (e.g. "power_supply.kicad_sch").
        x, y: Position of the sheet symbol in the parent.
        width, height: Size of the sheet symbol.

    Returns:
        {"success": True, "sheet_uuid": "...", "sheet_file": "..."} or error dict.
    """
    try:
        x, y = snap_to_grid(x, y)

        with open(parent_schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        sheet_uuid = str(uuid.uuid4())
        sx, sy = _fmt(x), _fmt(y)
        sw, sh = _fmt(width), _fmt(height)
        # Property positions: name above the sheet, file below
        name_y = _fmt(y - 2.54)
        file_y = _fmt(y + height + 2.54)

        sheet_block = (
            f"(sheet (at {sx} {sy}) (size {sw} {sh})\n"
            f"    (stroke (width 0.0001) (type solid))\n"
            f"    (fill (color 0 0 0 0.0000))\n"
            f"    (uuid \"{sheet_uuid}\")\n"
            f"    (property \"Sheetname\" \"{sheet_name}\" (at {sx} {name_y} 0)\n"
            f"      (effects (font (size 1.27 1.27)))\n"
            f"    )\n"
            f"    (property \"Sheetfile\" \"{sheet_file}\" (at {sx} {file_y} 0)\n"
            f"      (effects (font (size 1.27 1.27)))\n"
            f"    )\n"
            f"  )"
        )

        insert_at = content.rfind("(sheet_instances")
        if insert_at == -1:
            return {"success": False, "message": "No sheet_instances section found"}

        content = content[:insert_at] + sheet_block + "\n  " + content[insert_at:]

        with open(parent_schematic_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Create the sub-sheet file if it doesn't exist
        parent_dir = Path(parent_schematic_path).parent
        subsheet_path = parent_dir / sheet_file
        if not subsheet_path.exists():
            subsheet_content = _SUBSHEET_TEMPLATE.format(uuid=str(uuid.uuid4()))
            with open(subsheet_path, "w", encoding="utf-8") as f:
                f.write(subsheet_content)
            logger.info(f"Created sub-sheet file: {subsheet_path}")

        logger.info(f"Added hierarchical sheet '{sheet_name}' -> {sheet_file}")
        return {
            "success": True,
            "sheet_uuid": sheet_uuid,
            "sheet_file": str(subsheet_path),
        }

    except Exception as e:
        logger.error(f"Error creating hierarchical sheet: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "message": str(e)}


def add_sheet_pin(
    parent_schematic_path: Path,
    sheet_name: str,
    pin_name: str,
    pin_type: str = "input",
    side: str = "left",
    position_index: int = 0,
) -> dict:
    """Add a hierarchical pin to a sheet in the parent schematic.

    Also adds a matching hierarchical_label in the sub-sheet file.

    Args:
        parent_schematic_path: Path to the parent .kicad_sch.
        sheet_name: Name of the sheet to add the pin to.
        pin_name: Net name for the pin (e.g. "VCC", "SDA").
        pin_type: Pin direction — "input", "output", "bidirectional", "passive".
        side: Which side of the sheet box — "left" or "right".
        position_index: Vertical position index (0 = top, increments downward).

    Returns:
        {"success": True, "pin_uuid": "..."} or error dict.
    """
    try:
        with open(parent_schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Find the sheet block by matching Sheetname property
        sheet_start = _find_sheet_block(content, sheet_name)
        if sheet_start is None:
            return {
                "success": False,
                "message": f"Sheet '{sheet_name}' not found in schematic",
            }

        # Find the sheet's position and size from the block
        sheet_end = _find_balanced_end(content, sheet_start)
        if sheet_end is None:
            return {"success": False, "message": "Malformed sheet block"}

        sheet_block = content[sheet_start:sheet_end]

        # Parse sheet position and size
        import re
        at_match = re.search(r'\(at\s+([\d.\-]+)\s+([\d.\-]+)\)', sheet_block)
        size_match = re.search(r'\(size\s+([\d.\-]+)\s+([\d.\-]+)\)', sheet_block)
        if not at_match or not size_match:
            return {"success": False, "message": "Cannot parse sheet position/size"}

        sheet_x = float(at_match.group(1))
        sheet_y = float(at_match.group(2))
        sheet_w = float(size_match.group(1))
        sheet_h = float(size_match.group(2))

        # Calculate pin position
        pin_y = sheet_y + 2.54 + (position_index * 2.54)
        if side == "left":
            pin_x = sheet_x
            angle = 0
        else:
            pin_x = sheet_x + sheet_w
            angle = 180

        pin_uuid = str(uuid.uuid4())
        px, py = _fmt(pin_x), _fmt(pin_y)

        pin_block = (
            f"\n    (pin \"{pin_name}\" {pin_type} (at {px} {py} {angle})\n"
            f"      (effects (font (size 1.27 1.27)))\n"
            f"      (uuid \"{pin_uuid}\")\n"
            f"    )"
        )

        # Insert pin just before the closing ) of the sheet block
        insert_pos = sheet_end - 1  # Position of the closing )
        # Walk backward past whitespace to find the right insertion point
        while insert_pos > sheet_start and content[insert_pos - 1] in (' ', '\t', '\n'):
            insert_pos -= 1

        content = content[:insert_pos] + pin_block + "\n  " + content[insert_pos:]

        with open(parent_schematic_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Find the sub-sheet file and add a matching hierarchical_label
        file_match = re.search(r'\(property\s+"Sheetfile"\s+"([^"]+)"', sheet_block)
        if file_match:
            subsheet_file = file_match.group(1)
            parent_dir = Path(parent_schematic_path).parent
            subsheet_path = parent_dir / subsheet_file
            if subsheet_path.exists():
                _add_hierarchical_label(subsheet_path, pin_name, pin_type)

        logger.info(f"Added sheet pin '{pin_name}' to sheet '{sheet_name}'")
        return {"success": True, "pin_uuid": pin_uuid}

    except Exception as e:
        logger.error(f"Error adding sheet pin: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "message": str(e)}


def _add_hierarchical_label(
    subsheet_path: Path,
    label_name: str,
    label_type: str = "input",
    x: float = 50.8,
    y: float = 50.8,
) -> bool:
    """Add a hierarchical_label to a sub-sheet file."""
    try:
        with open(subsheet_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Flip direction for the sub-sheet side
        sub_type = label_type
        if label_type == "input":
            sub_type = "output"
        elif label_type == "output":
            sub_type = "input"

        sx, sy = _fmt(x), _fmt(y)
        new_uuid = str(uuid.uuid4())

        label_block = (
            f"(hierarchical_label \"{label_name}\" (shape {sub_type}) (at {sx} {sy} 180)\n"
            f"    (effects (font (size 1.27 1.27)))\n"
            f"    (uuid \"{new_uuid}\")\n"
            f"  )"
        )

        insert_at = content.rfind("(sheet_instances")
        if insert_at == -1:
            return False

        content = content[:insert_at] + label_block + "\n  " + content[insert_at:]

        with open(subsheet_path, "w", encoding="utf-8") as f:
            f.write(content)

        return True

    except Exception as e:
        logger.error(f"Error adding hierarchical label: {e}")
        return False


def _find_sheet_block(content: str, sheet_name: str) -> Optional[int]:
    """Find the start position of a (sheet ...) block by its Sheetname property."""
    import re
    pos = 0
    while True:
        idx = content.find("(sheet ", pos)
        if idx == -1:
            # Also try without space (e.g. "(sheet(")
            idx = content.find("(sheet\n", pos)
            if idx == -1:
                return None

        end = _find_balanced_end(content, idx)
        if end is None:
            pos = idx + 1
            continue

        block = content[idx:end]
        name_match = re.search(r'\(property\s+"Sheetname"\s+"([^"]+)"', block)
        if name_match and name_match.group(1) == sheet_name:
            return idx

        pos = end
