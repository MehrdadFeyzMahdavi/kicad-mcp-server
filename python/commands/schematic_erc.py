"""
Electrical Rule Check (ERC) for KiCad Schematics

Parses .kicad_sch files and checks for common schematic errors.
Returns structured JSON that an LLM agent can act on to self-correct.

Uses sexpdata for read-only parsing (never writes with sexpdata.dumps).
"""

import logging
import re
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import sexpdata
from sexpdata import Symbol

logger = logging.getLogger("kicad_interface")

# Pin types that must be connected (not left floating)
_POWER_PIN_TYPES = {"power_in", "power_out"}
_INPUT_PIN_TYPES = {"input"}
_OUTPUT_PIN_TYPES = {"output"}


def run_schematic_erc(schematic_path: Path) -> dict:
    """Run electrical rule checks on a schematic file.

    Returns:
        {
            "success": True,
            "errors": [...],    # Critical issues
            "warnings": [...],  # Non-critical issues
            "info": {...},      # Summary statistics
        }
    """
    try:
        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        sch_data = sexpdata.loads(content)

        errors: List[dict] = []
        warnings: List[dict] = []

        # Gather data from the schematic
        lib_symbols = _extract_lib_symbols(sch_data)
        placed_symbols = _extract_placed_symbols(sch_data)
        wires = _extract_wires(sch_data)
        labels = _extract_labels(sch_data)
        junctions = _extract_junctions(sch_data)
        no_connects = _extract_no_connects(sch_data)

        # --- Check 1: Duplicate reference designators ---
        _check_duplicate_refs(placed_symbols, errors)

        # --- Check 2: Unconnected pins ---
        _check_unconnected_pins(
            placed_symbols, lib_symbols, wires, labels,
            junctions, no_connects, errors, warnings,
        )

        # --- Check 3: Floating nets (labels with no wire) ---
        _check_floating_nets(labels, wires, warnings)

        return {
            "success": True,
            "error_count": len(errors),
            "warning_count": len(warnings),
            "errors": errors,
            "warnings": warnings,
            "info": {
                "component_count": len(placed_symbols),
                "wire_count": len(wires),
                "label_count": len(labels),
                "net_names": sorted(set(l["text"] for l in labels)),
            },
        }

    except Exception as e:
        logger.error(f"ERC failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "success": False,
            "error_count": 1,
            "warning_count": 0,
            "errors": [{"type": "erc_failure", "message": str(e)}],
            "warnings": [],
            "info": {},
        }


# -----------------------------------------------------------------------
# Data extraction helpers
# -----------------------------------------------------------------------

def _extract_lib_symbols(sch_data) -> Dict[str, list]:
    """Extract lib_id -> symbol definition from lib_symbols section."""
    result = {}
    for item in sch_data:
        if isinstance(item, list) and item and item[0] == Symbol("lib_symbols"):
            for sym in item[1:]:
                if isinstance(sym, list) and len(sym) > 1 and sym[0] == Symbol("symbol"):
                    lib_id = str(sym[1]).strip('"')
                    result[lib_id] = sym
    return result


def _extract_placed_symbols(sch_data) -> List[dict]:
    """Extract placed symbol instances with reference, lib_id, position."""
    symbols = []
    for item in sch_data:
        if not (isinstance(item, list) and item and item[0] == Symbol("symbol")):
            continue

        info: dict = {
            "lib_id": None,
            "reference": None,
            "x": 0,
            "y": 0,
            "rotation": 0,
            "mirror": None,
            "unit": 1,
            "style": 1,
        }
        for sub in item[1:]:
            if not isinstance(sub, list) or len(sub) < 2:
                continue
            if sub[0] == Symbol("lib_id"):
                info["lib_id"] = str(sub[1]).strip('"')
            elif sub[0] == Symbol("at") and len(sub) >= 3:
                info["x"] = float(sub[1])
                info["y"] = float(sub[2])
                info["rotation"] = float(sub[3]) if len(sub) >= 4 else 0.0
            elif sub[0] == Symbol("mirror") and len(sub) >= 2:
                info["mirror"] = str(sub[1]).strip('"')
            elif sub[0] == Symbol("unit") and len(sub) >= 2:
                info["unit"] = int(sub[1])
            elif sub[0] == Symbol("body_style") and len(sub) >= 2:
                info["style"] = int(sub[1])
            elif sub[0] == Symbol("property"):
                if len(sub) >= 3 and str(sub[1]).strip('"') == "Reference":
                    info["reference"] = str(sub[2]).strip('"')

        if info["reference"] and not info["reference"].startswith("_TEMPLATE"):
            symbols.append(info)

    return symbols


def _extract_wires(sch_data) -> List[dict]:
    """Extract wire segments with start/end points."""
    wires = []

    for item in sch_data:
        if not (isinstance(item, list) and item and item[0] == Symbol("wire")):
            continue

        pts = []
        for sub in item[1:]:
            if isinstance(sub, list) and sub and sub[0] == Symbol("pts"):
                for pt in sub[1:]:
                    if isinstance(pt, list) and len(pt) >= 3 and pt[0] == Symbol("xy"):
                        pts.append((float(pt[1]), float(pt[2])))

        if len(pts) >= 2:
            wires.append({"start": pts[0], "end": pts[-1], "all_points": pts})

    return wires


def _extract_labels(sch_data) -> List[dict]:
    """Extract net labels with text and position."""
    labels = []
    for item in sch_data:
        if not isinstance(item, list) or not item:
            continue
        tag = item[0]
        if tag not in (Symbol("label"), Symbol("global_label"), Symbol("hierarchical_label")):
            continue

        text = str(item[1]).strip('"') if len(item) > 1 else ""
        x, y = 0.0, 0.0
        for sub in item[1:]:
            if isinstance(sub, list) and len(sub) >= 3 and sub[0] == Symbol("at"):
                x, y = float(sub[1]), float(sub[2])
                break

        labels.append({"text": text, "x": x, "y": y, "type": str(tag)})

    return labels


def _extract_junctions(sch_data) -> List[Tuple[float, float]]:
    """Extract junction positions."""
    junctions = []
    for item in sch_data:
        if isinstance(item, list) and item and item[0] == Symbol("junction"):
            for sub in item[1:]:
                if isinstance(sub, list) and len(sub) >= 3 and sub[0] == Symbol("at"):
                    junctions.append((float(sub[1]), float(sub[2])))
                    break
    return junctions


def _extract_no_connects(sch_data) -> List[Tuple[float, float]]:
    """Extract no-connect flag positions."""
    ncs = []
    for item in sch_data:
        if isinstance(item, list) and item and item[0] == Symbol("no_connect"):
            for sub in item[1:]:
                if isinstance(sub, list) and len(sub) >= 3 and sub[0] == Symbol("at"):
                    ncs.append((float(sub[1]), float(sub[2])))
                    break
    return ncs


def _get_pin_positions(
    symbol_info: dict,
    lib_symbols: Dict[str, list],
) -> List[dict]:
    """Get absolute pin positions for a placed symbol.

    Returns list of {"number": str, "name": str, "type": str, "x": float, "y": float}.
    """
    from commands.pin_locator import PinLocator

    lib_id = symbol_info["lib_id"]
    sym_def = lib_symbols.get(lib_id)
    if not sym_def:
        return []

    raw_pins = PinLocator.parse_symbol_definition(sym_def)
    pins = PinLocator.pins_for_unit(
        raw_pins, symbol_info.get("unit", 1), symbol_info.get("style", 1)
    )
    result = []
    for pin in pins.values():
        x, y = PinLocator.sheet_pin_position(
            symbol_info["x"],
            symbol_info["y"],
            symbol_info["rotation"],
            pin["x"],
            pin["y"],
            symbol_info.get("mirror"),
        )
        result.append({
            "number": pin["number"],
            "name": pin["name"],
            "type": pin["type"],
            "x": x,
            "y": y,
        })
    return result


# -----------------------------------------------------------------------
# ERC checks
# -----------------------------------------------------------------------

TOLERANCE = 0.5  # mm, for point coincidence


def _points_match(p1: Tuple[float, float], p2: Tuple[float, float]) -> bool:
    return abs(p1[0] - p2[0]) < TOLERANCE and abs(p1[1] - p2[1]) < TOLERANCE


def _check_duplicate_refs(placed_symbols: List[dict], errors: List[dict]):
    """Flag duplicate reference designators."""
    refs = [s["reference"] for s in placed_symbols]
    counts = Counter(refs)
    for ref, count in counts.items():
        if count > 1:
            errors.append({
                "type": "duplicate_reference",
                "reference": ref,
                "count": count,
                "message": f"Reference '{ref}' is used {count} times",
            })


def _check_unconnected_pins(
    placed_symbols, lib_symbols, wires, labels, junctions, no_connects,
    errors, warnings,
):
    """Check for pins that are not connected to any wire, label, or no-connect."""
    # Build a set of all wire endpoints and label positions
    connected_points: Set[Tuple[float, float]] = set()
    for w in wires:
        for pt in w["all_points"]:
            connected_points.add(pt)
    for lbl in labels:
        connected_points.add((lbl["x"], lbl["y"]))
    for nc in no_connects:
        connected_points.add(nc)

    for sym in placed_symbols:
        pin_positions = _get_pin_positions(sym, lib_symbols)
        for pin in pin_positions:
            pin_pt = (pin["x"], pin["y"])
            connected = any(
                _points_match(pin_pt, cp) for cp in connected_points
            )
            if not connected:
                if pin["type"] in ("power_in", "power_out", "input"):
                    errors.append({
                        "type": "unconnected_pin",
                        "reference": sym["reference"],
                        "pin": pin["number"],
                        "pin_name": pin["name"],
                        "pin_type": pin["type"],
                        "x": pin["x"],
                        "y": pin["y"],
                        "message": (
                            f"Pin {pin['number']} ({pin['name']}) on "
                            f"{sym['reference']} is unconnected"
                        ),
                    })
                else:
                    warnings.append({
                        "type": "unconnected_pin",
                        "reference": sym["reference"],
                        "pin": pin["number"],
                        "pin_name": pin["name"],
                        "pin_type": pin["type"],
                        "x": pin["x"],
                        "y": pin["y"],
                        "message": (
                            f"Pin {pin['number']} ({pin['name']}) on "
                            f"{sym['reference']} is unconnected"
                        ),
                    })


def _check_floating_nets(labels, wires, warnings):
    """Check for net labels not connected to any wire endpoint."""
    wire_points: Set[Tuple[float, float]] = set()
    for w in wires:
        for pt in w["all_points"]:
            wire_points.add(pt)

    for lbl in labels:
        lbl_pt = (lbl["x"], lbl["y"])
        if not any(_points_match(lbl_pt, wp) for wp in wire_points):
            warnings.append({
                "type": "floating_net",
                "net_name": lbl["text"],
                "x": lbl["x"],
                "y": lbl["y"],
                "message": (
                    f"Net label '{lbl['text']}' at ({lbl['x']}, {lbl['y']}) "
                    f"is not connected to any wire"
                ),
            })
