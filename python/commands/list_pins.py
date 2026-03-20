"""
List Component Pins for KiCad Schematics

Given a lib_id (e.g. "Device:R") or a placed component reference,
returns all pins with names, numbers, types, and positions.

Essential for the LLM to know what to connect before attempting wiring.
"""

import math
import logging
from pathlib import Path
from typing import Dict, List, Optional

import sexpdata
from sexpdata import Symbol

logger = logging.getLogger("kicad_interface")


def list_component_pins(
    schematic_path: Path,
    reference: Optional[str] = None,
    lib_id: Optional[str] = None,
) -> dict:
    """List all pins for a component.

    Provide either *reference* (a placed component like "R1") or *lib_id*
    (a library symbol like "Device:R"). If *reference* is given, pin positions
    are returned as absolute schematic coordinates.

    Returns:
        {
            "success": True,
            "lib_id": "Device:R",
            "reference": "R1" or None,
            "pin_count": 2,
            "pins": [
                {
                    "number": "1",
                    "name": "~",
                    "type": "passive",
                    "x": 50.8,    # absolute if reference given
                    "y": 46.99,
                },
                ...
            ],
        }
    """
    try:
        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        sch_data = sexpdata.loads(content)

        # Resolve lib_id from reference if needed
        resolved_lib_id = lib_id
        inst_x, inst_y, rotation = 0.0, 0.0, 0.0

        if reference:
            for item in sch_data:
                if not (isinstance(item, list) and item and item[0] == Symbol("symbol")):
                    continue
                ref_val = None
                for sub in item[1:]:
                    if (isinstance(sub, list) and len(sub) >= 3
                            and sub[0] == Symbol("property")
                            and str(sub[1]).strip('"') == "Reference"):
                        ref_val = str(sub[2]).strip('"')
                if ref_val != reference:
                    continue
                for sub in item[1:]:
                    if isinstance(sub, list) and len(sub) >= 2:
                        if sub[0] == Symbol("lib_id"):
                            resolved_lib_id = str(sub[1]).strip('"')
                        elif sub[0] == Symbol("at") and len(sub) >= 3:
                            inst_x = float(sub[1])
                            inst_y = float(sub[2])
                            rotation = float(sub[3]) if len(sub) >= 4 else 0.0
                break

            if resolved_lib_id is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

        if resolved_lib_id is None:
            return {
                "success": False,
                "message": "Either reference or lib_id must be provided",
            }

        # Find the symbol definition in lib_symbols
        sym_def = None
        for item in sch_data:
            if isinstance(item, list) and item and item[0] == Symbol("lib_symbols"):
                for sym in item[1:]:
                    if (isinstance(sym, list) and len(sym) > 1
                            and sym[0] == Symbol("symbol")
                            and str(sym[1]).strip('"') == resolved_lib_id):
                        sym_def = sym
                        break

        if sym_def is None:
            return {
                "success": False,
                "message": f"Symbol definition '{resolved_lib_id}' not found in lib_symbols",
            }

        # Extract pins
        raw_pins = _extract_pins(sym_def)

        # Apply rotation and translation if reference was given
        pins = []
        for p in raw_pins:
            rx, ry = p["rel_x"], p["rel_y"]
            if reference and rotation != 0:
                rad = math.radians(rotation)
                cos_a, sin_a = math.cos(rad), math.sin(rad)
                rx, ry = rx * cos_a - ry * sin_a, rx * sin_a + ry * cos_a

            pin_entry = {
                "number": p["number"],
                "name": p["name"],
                "type": p["type"],
            }
            if reference:
                pin_entry["x"] = round(inst_x + rx, 4)
                pin_entry["y"] = round(inst_y + ry, 4)
            else:
                pin_entry["rel_x"] = p["rel_x"]
                pin_entry["rel_y"] = p["rel_y"]

            pins.append(pin_entry)

        return {
            "success": True,
            "lib_id": resolved_lib_id,
            "reference": reference,
            "pin_count": len(pins),
            "pins": pins,
        }

    except Exception as e:
        logger.error(f"list_component_pins failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "message": str(e)}


def _extract_pins(sym_def: list) -> List[dict]:
    """Extract pin definitions from a parsed symbol definition."""
    pins = []

    def _walk(sexp):
        if not isinstance(sexp, list) or not sexp:
            return
        if sexp[0] == Symbol("pin"):
            pin_type = str(sexp[1]) if len(sexp) > 1 and isinstance(sexp[1], Symbol) else "passive"
            px, py = 0.0, 0.0
            name, number = "", ""
            for sub in sexp[1:]:
                if isinstance(sub, list) and sub:
                    if sub[0] == Symbol("at") and len(sub) >= 3:
                        px, py = float(sub[1]), float(sub[2])
                    elif sub[0] == Symbol("name") and len(sub) >= 2:
                        name = str(sub[1]).strip('"')
                    elif sub[0] == Symbol("number") and len(sub) >= 2:
                        number = str(sub[1]).strip('"')
            pins.append({
                "number": number,
                "name": name,
                "type": pin_type,
                "rel_x": px,
                "rel_y": py,
            })
            return
        for sub in sexp:
            if isinstance(sub, list):
                _walk(sub)

    _walk(sym_def)
    return pins
