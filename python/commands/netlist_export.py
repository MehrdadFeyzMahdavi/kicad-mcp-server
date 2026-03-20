"""
Standalone Netlist Export for KiCad Schematics

Generates a netlist from a .kicad_sch file by parsing the S-expression
structure directly. Works without kicad-skip or a running KiCad instance.

Produces a JSON netlist suitable for PCB tool integration, and optionally
a KiCad-compatible .net file.
"""

import math
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import sexpdata
from sexpdata import Symbol

logger = logging.getLogger("kicad_interface")

TOLERANCE = 0.5  # mm for point coincidence


def export_netlist(schematic_path: Path) -> dict:
    """Export a netlist from a schematic file.

    Parses the .kicad_sch directly (no kicad-skip needed) to extract:
    - All placed components with reference, value, footprint, lib_id
    - All net labels and their positions
    - Wire connectivity (which pins connect to which nets)

    Returns:
        {
            "success": True,
            "components": [
                {"reference": "R1", "value": "10k", "lib_id": "Device:R",
                 "footprint": "...", "pins": [...]},
                ...
            ],
            "nets": [
                {"name": "VCC", "connections": [
                    {"reference": "R1", "pin": "1"},
                    ...
                ]},
                ...
            ],
            "unconnected_nets": [...],
        }
    """
    try:
        with open(schematic_path, "r", encoding="utf-8") as f:
            content = f.read()

        sch_data = sexpdata.loads(content)

        # Extract all data
        lib_symbols = _extract_lib_symbols(sch_data)
        components = _extract_components(sch_data, lib_symbols)
        wires = _extract_wires(sch_data)
        labels = _extract_labels(sch_data)

        # Build connectivity graph
        nets = _build_nets(components, wires, labels)

        return {
            "success": True,
            "component_count": len(components),
            "net_count": len(nets),
            "components": components,
            "nets": nets,
        }

    except Exception as e:
        logger.error(f"Netlist export failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {"success": False, "message": str(e)}


def export_netlist_kicad_format(schematic_path: Path, output_path: Path) -> dict:
    """Export a KiCad-format .net file.

    This produces the traditional KiCad netlist format that can be imported
    by the PCB editor.

    Returns:
        {"success": True, "path": "..."} or error dict.
    """
    try:
        netlist_data = export_netlist(schematic_path)
        if not netlist_data["success"]:
            return netlist_data

        lines = []
        lines.append("(export (version D)")
        lines.append("  (design")
        lines.append(f'    (source "{schematic_path}")')
        lines.append("  )")

        # Components section
        lines.append("  (components")
        for comp in netlist_data["components"]:
            ref = comp["reference"]
            value = comp["value"]
            fp = comp.get("footprint", "")
            lib_id = comp.get("lib_id", "")
            lines.append(f"    (comp (ref {ref})")
            lines.append(f'      (value "{value}")')
            if fp:
                lines.append(f'      (footprint "{fp}")')
            if lib_id:
                lines.append(f'      (libsource (lib "{lib_id.split(":")[0]}") (part "{lib_id.split(":")[-1]}"))')
            lines.append("    )")
        lines.append("  )")

        # Nets section
        lines.append("  (nets")
        for i, net in enumerate(netlist_data["nets"], 1):
            name = net["name"]
            lines.append(f'    (net (code {i}) (name "{name}")')
            for conn in net["connections"]:
                lines.append(f'      (node (ref {conn["reference"]}) (pin {conn["pin"]}))')
            lines.append("    )")
        lines.append("  )")

        lines.append(")")

        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")

        logger.info(f"Exported KiCad netlist to {output_path}")
        return {"success": True, "path": str(output_path)}

    except Exception as e:
        logger.error(f"KiCad netlist export failed: {e}")
        return {"success": False, "message": str(e)}


# -----------------------------------------------------------------------
# Extraction helpers
# -----------------------------------------------------------------------

def _extract_lib_symbols(sch_data) -> Dict[str, list]:
    """lib_id -> symbol definition."""
    result = {}
    for item in sch_data:
        if isinstance(item, list) and item and item[0] == Symbol("lib_symbols"):
            for sym in item[1:]:
                if isinstance(sym, list) and len(sym) > 1 and sym[0] == Symbol("symbol"):
                    result[str(sym[1]).strip('"')] = sym
    return result


def _get_pins_from_def(sym_def: list) -> List[dict]:
    """Extract pin definitions from a symbol definition."""
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
            pins.append({"number": number, "name": name, "type": pin_type,
                         "rel_x": px, "rel_y": py})
            return
        for sub in sexp:
            if isinstance(sub, list):
                _walk(sub)

    _walk(sym_def)
    return pins


def _extract_components(sch_data, lib_symbols: Dict[str, list]) -> List[dict]:
    """Extract placed components with their pin positions."""
    components = []
    for item in sch_data:
        if not (isinstance(item, list) and item and item[0] == Symbol("symbol")):
            continue

        info = {"reference": None, "value": "", "footprint": "", "lib_id": None,
                "x": 0, "y": 0, "rotation": 0, "pins": []}

        for sub in item[1:]:
            if not isinstance(sub, list) or len(sub) < 2:
                continue
            if sub[0] == Symbol("lib_id"):
                info["lib_id"] = str(sub[1]).strip('"')
            elif sub[0] == Symbol("at") and len(sub) >= 3:
                info["x"] = float(sub[1])
                info["y"] = float(sub[2])
                info["rotation"] = float(sub[3]) if len(sub) >= 4 else 0.0
            elif sub[0] == Symbol("property") and len(sub) >= 3:
                prop_name = str(sub[1]).strip('"')
                prop_val = str(sub[2]).strip('"')
                if prop_name == "Reference":
                    info["reference"] = prop_val
                elif prop_name == "Value":
                    info["value"] = prop_val
                elif prop_name == "Footprint":
                    info["footprint"] = prop_val

        if not info["reference"] or info["reference"].startswith("_TEMPLATE"):
            continue

        # Calculate absolute pin positions
        sym_def = lib_symbols.get(info["lib_id"])
        if sym_def:
            raw_pins = _get_pins_from_def(sym_def)
            rotation = info["rotation"]
            for p in raw_pins:
                rx, ry = p["rel_x"], p["rel_y"]
                if rotation != 0:
                    rad = math.radians(rotation)
                    cos_a, sin_a = math.cos(rad), math.sin(rad)
                    rx, ry = rx * cos_a - ry * sin_a, rx * sin_a + ry * cos_a
                info["pins"].append({
                    "number": p["number"],
                    "name": p["name"],
                    "type": p["type"],
                    "x": round(info["x"] + rx, 4),
                    "y": round(info["y"] + ry, 4),
                })

        components.append(info)

    return components


def _extract_wires(sch_data) -> List[List[Tuple[float, float]]]:
    """Extract wire segments as lists of points."""
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
        if pts:
            wires.append(pts)
    return wires


def _extract_labels(sch_data) -> List[dict]:
    """Extract net labels."""
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
        labels.append({"text": text, "x": x, "y": y})
    return labels


# -----------------------------------------------------------------------
# Net building
# -----------------------------------------------------------------------

def _points_match(p1, p2) -> bool:
    return abs(p1[0] - p2[0]) < TOLERANCE and abs(p1[1] - p2[1]) < TOLERANCE


def _point_on_segment(pt, seg_start, seg_end) -> bool:
    """Check if a point lies on an axis-aligned wire segment."""
    px, py = pt
    x1, y1 = seg_start
    x2, y2 = seg_end
    # Horizontal segment
    if abs(y1 - y2) < TOLERANCE and abs(py - y1) < TOLERANCE:
        return min(x1, x2) - TOLERANCE <= px <= max(x1, x2) + TOLERANCE
    # Vertical segment
    if abs(x1 - x2) < TOLERANCE and abs(px - x1) < TOLERANCE:
        return min(y1, y2) - TOLERANCE <= py <= max(y1, y2) + TOLERANCE
    return False


def _build_nets(
    components: List[dict],
    wires: List[List[Tuple[float, float]]],
    labels: List[dict],
) -> List[dict]:
    """Build nets by tracing connectivity from labels through wires to pins."""
    # Group labels by net name
    net_labels: Dict[str, List[Tuple[float, float]]] = {}
    for lbl in labels:
        net_labels.setdefault(lbl["text"], []).append((lbl["x"], lbl["y"]))

    # Build wire segments
    wire_segments: List[Tuple[Tuple[float, float], Tuple[float, float]]] = []
    for wire_pts in wires:
        for i in range(len(wire_pts) - 1):
            wire_segments.append((wire_pts[i], wire_pts[i + 1]))

    # For each net label, find connected pins by flood-filling through wires
    nets = []
    for net_name, label_positions in net_labels.items():
        frontier = list(label_positions)
        visited_frontier: Set[Tuple[float, float]] = set()

        while frontier:
            pt = frontier.pop()
            pt_key = (round(pt[0], 2), round(pt[1], 2))
            if pt_key in visited_frontier:
                continue
            visited_frontier.add(pt_key)

            # Find wire segments touching this point (at endpoints OR mid-segment)
            for seg_start, seg_end in wire_segments:
                if _points_match(pt, seg_start):
                    frontier.append(seg_end)
                elif _points_match(pt, seg_end):
                    frontier.append(seg_start)
                elif _point_on_segment(pt, seg_start, seg_end):
                    # Point lies on the wire — both endpoints are reachable
                    frontier.append(seg_start)
                    frontier.append(seg_end)

        # Find pins at any visited point
        connections = []
        for comp in components:
            for pin in comp["pins"]:
                pin_pt = (pin["x"], pin["y"])
                for visited_pt in visited_frontier:
                    if _points_match(pin_pt, visited_pt):
                        connections.append({
                            "reference": comp["reference"],
                            "pin": pin["number"],
                            "pin_name": pin["name"],
                        })
                        break

        if connections:
            nets.append({"name": net_name, "connections": connections})

    return nets
