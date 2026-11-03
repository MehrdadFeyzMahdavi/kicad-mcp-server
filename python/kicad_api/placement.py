"""PCB placement geometry.

Courtyard and body boxes are axis-aligned. Rotation is about the footprint
anchor, using the same 180-degree result for either angle direction. This
module does not move a board and it is not a placement optimiser.
"""

from __future__ import annotations

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


Point = Tuple[float, float]
LED_SWITCH_REFS = ("Q1", "D1", "R1", "R2", "R3", "J1", "J2")


class PlacementError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def rotate_xy(x: float, y: float, degrees: float) -> Point:
    """Rotate a point about the origin."""
    radians = math.radians(float(degrees))
    cosine = math.cos(radians)
    sine = math.sin(radians)
    return (x * cosine - y * sine, x * sine + y * cosine)


def aabb_from_points(points: Sequence[Point]) -> Dict[str, float]:
    if not points:
        raise PlacementError("EMPTY_GEOMETRY", "A bounding box needs at least one point.")
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return {"xmin": min(xs), "ymin": min(ys), "xmax": max(xs), "ymax": max(ys)}


def corners(box: Dict[str, float]) -> List[Point]:
    return [
        (box["xmin"], box["ymin"]),
        (box["xmax"], box["ymin"]),
        (box["xmax"], box["ymax"]),
        (box["xmin"], box["ymax"]),
    ]


def transform_box(local: Dict[str, float], x: float, y: float, rotation: float) -> Dict[str, float]:
    """Move a footprint-local box onto the board."""
    moved = []
    for px, py in corners(local):
        rx, ry = rotate_xy(px, py, rotation)
        moved.append((x + rx, y + ry))
    return aabb_from_points(moved)


def local_box(points: Sequence[Point], origin_x: float, origin_y: float, rotation: float) -> Dict[str, float]:
    """Convert board-space points back to the footprint anchor frame."""
    local = [rotate_xy(px - origin_x, py - origin_y, -rotation) for px, py in points]
    return aabb_from_points(local)


def board_box(width: float, height: float, center_x: float = 0.0, center_y: float = 0.0) -> Dict[str, float]:
    if width <= 0 or height <= 0:
        raise PlacementError("INVALID_BOARD", "Board width and height must be positive.")
    return {
        "xmin": center_x - width / 2.0,
        "ymin": center_y - height / 2.0,
        "xmax": center_x + width / 2.0,
        "ymax": center_y + height / 2.0,
    }


def boxes_overlap(left: Dict[str, float], right: Dict[str, float]) -> bool:
    """True when the box interiors intersect. Shared edges do not count."""
    return (
        left["xmin"] < right["xmax"]
        and right["xmin"] < left["xmax"]
        and left["ymin"] < right["ymax"]
        and right["ymin"] < left["ymax"]
    )


def separation(left: Dict[str, float], right: Dict[str, float]) -> float:
    """Positive gap, zero when touching, negative when the interiors overlap."""
    if left["xmax"] <= right["xmin"]:
        dx = right["xmin"] - left["xmax"]
    elif right["xmax"] <= left["xmin"]:
        dx = left["xmin"] - right["xmax"]
    else:
        dx = 0.0
    if left["ymax"] <= right["ymin"]:
        dy = right["ymin"] - left["ymax"]
    elif right["ymax"] <= left["ymin"]:
        dy = left["ymin"] - right["ymax"]
    else:
        dy = 0.0
    if dx > 0 and dy > 0:
        return math.hypot(dx, dy)
    if dx == 0 and dy == 0:
        overlap_x = min(left["xmax"], right["xmax"]) - max(left["xmin"], right["xmin"])
        overlap_y = min(left["ymax"], right["ymax"]) - max(left["ymin"], right["ymin"])
        return -min(overlap_x, overlap_y)
    return dx + dy


def edge_clearance(box: Dict[str, float], board: Dict[str, float]) -> float:
    """Smallest distance from the box to the board edge. Negative means outside."""
    return min(
        box["xmin"] - board["xmin"],
        board["xmax"] - box["xmax"],
        box["ymin"] - board["ymin"],
        board["ymax"] - box["ymax"],
    )


def outside_board(box: Dict[str, float], board: Dict[str, float]) -> bool:
    return (
        box["xmin"] < board["xmin"]
        or box["xmax"] > board["xmax"]
        or box["ymin"] < board["ymin"]
        or box["ymax"] > board["ymax"]
    )


def _anchor_distance(left: Dict[str, float], right: Dict[str, float]) -> float:
    return math.hypot(left["x"] - right["x"], left["y"] - right["y"])


def validate_placement(
    parts: Sequence[Dict],
    board: Dict[str, float],
    edge_clearance_mm: float = 0.5,
    courtyard_gap_mm: float = 0.25,
    max_connected_span_mm: Optional[float] = 25.0,
) -> Dict:
    """Check courtyards, bodies, the board edge, and long same-net anchors.

    ``max_connected_span_mm`` is a spacing rule for this small board. It does
    not search for a better arrangement.
    """
    problems: List[Dict[str, str]] = []
    seen = set()
    placed = []
    for part in parts:
        reference = part.get("reference", "")
        if reference in seen:
            problems.append(
                {
                    "code": "DUPLICATE_REFERENCE",
                    "message": f"{reference} appears more than once.",
                }
            )
            continue
        seen.add(reference)
        courtyard = part.get("courtyard")
        if not courtyard:
            problems.append(
                {
                    "code": "MISSING_COURTYARD",
                    "message": f"{reference} has no courtyard box.",
                }
            )
            continue
        placed.append(part)
        if outside_board(courtyard, board):
            problems.append(
                {
                    "code": "OUTSIDE_BOARD",
                    "message": f"{reference} courtyard is outside the board.",
                }
            )
        clearance = edge_clearance(courtyard, board)
        if clearance + 1e-6 < edge_clearance_mm:
            problems.append(
                {
                    "code": "EDGE_CLEARANCE",
                    "message": (
                        f"{reference} courtyard is {clearance:.3f} mm from the "
                        f"board edge; {edge_clearance_mm:.3f} mm is required."
                    ),
                }
            )
        body = part.get("body")
        if body and outside_board(body, board):
            problems.append(
                {
                    "code": "OUTSIDE_BOARD",
                    "message": f"{reference} body is outside the board.",
                }
            )

    for index, left in enumerate(placed):
        for right in placed[index + 1 :]:
            gap = separation(left["courtyard"], right["courtyard"])
            if boxes_overlap(left["courtyard"], right["courtyard"]):
                problems.append(
                    {
                        "code": "COURTYARD_OVERLAP",
                        "message": f"{left['reference']} and {right['reference']} courtyards overlap.",
                    }
                )
            elif gap + 1e-6 < courtyard_gap_mm:
                problems.append(
                    {
                        "code": "COURTYARD_GAP",
                        "message": (
                            f"{left['reference']} and {right['reference']} courtyards "
                            f"are {gap:.3f} mm apart."
                        ),
                    }
                )
            left_body = left.get("body")
            right_body = right.get("body")
            if left_body and right_body and boxes_overlap(left_body, right_body):
                problems.append(
                    {
                        "code": "FOOTPRINT_OVERLAP",
                        "message": f"{left['reference']} and {right['reference']} bodies overlap.",
                    }
                )

    if max_connected_span_mm is not None:
        by_ref = {part["reference"]: part for part in placed if "x" in part and "y" in part}
        nets: Dict[str, List[str]] = {}
        for part in placed:
            for net_name in part.get("nets", []):
                nets.setdefault(net_name, []).append(part["reference"])
        for net_name, references in nets.items():
            unique = list(dict.fromkeys(references))
            for index, left_ref in enumerate(unique):
                for right_ref in unique[index + 1 :]:
                    if left_ref not in by_ref or right_ref not in by_ref:
                        continue
                    distance = _anchor_distance(by_ref[left_ref], by_ref[right_ref])
                    if distance > max_connected_span_mm:
                        problems.append(
                            {
                                "code": "LONG_CONNECTION",
                                "message": (
                                    f"{left_ref} and {right_ref} share {net_name} and their "
                                    f"anchors are {distance:.2f} mm apart."
                                ),
                            }
                        )

    return {"success": not problems, "problems": problems}


def _rotated_local(box: Dict[str, float], rotation: float) -> Dict[str, float]:
    return transform_box(box, 0.0, 0.0, rotation)


def plan_led_switch(
    local_courtyards: Dict[str, Dict[str, float]],
    width: float = 50.0,
    height: float = 40.0,
    edge_clearance_mm: float = 0.5,
    courtyard_gap_mm: float = 1.0,
) -> Dict:
    """Place the seven LED-switch parts with fixed orientation rules.

    Connectors sit on the left edge. R1, D1, and Q1 follow +5V toward the
    collector, with D1 and Q1 turned 180 degrees so the anode faces R1 and
    the collector faces D1. R2 and R3 sit beside the control connector.
    """
    missing = [ref for ref in LED_SWITCH_REFS if ref not in local_courtyards]
    extra = sorted(set(local_courtyards) - set(LED_SWITCH_REFS))
    if missing or extra:
        raise PlacementError(
            "UNSUPPORTED_PLACEMENT",
            "This rule set only places Q1, D1, R1, R2, R3, J1, and J2. "
            f"Missing: {missing or 'none'}. Extra: {extra or 'none'}.",
        )
    rotations = {ref: 0.0 for ref in LED_SWITCH_REFS}
    rotations["D1"] = 180.0
    rotations["Q1"] = 180.0
    local = {ref: _rotated_local(local_courtyards[ref], rotations[ref]) for ref in LED_SWITCH_REFS}
    outline = board_box(width, height)
    inset_left = outline["xmin"] + edge_clearance_mm
    inset_top = outline["ymin"] + edge_clearance_mm

    def origin_x(ref: str, courtyard_xmin: float) -> float:
        return courtyard_xmin - local[ref]["xmin"]

    j1 = {
        "x": origin_x("J1", inset_left),
        "y": inset_top - local["J1"]["ymin"],
        "rotation": 0.0,
    }
    j1_box = transform_box(local_courtyards["J1"], j1["x"], j1["y"], 0.0)
    j2 = {
        "x": origin_x("J2", inset_left),
        "y": (j1_box["ymax"] + courtyard_gap_mm) - local["J2"]["ymin"],
        "rotation": 0.0,
    }
    j2_box = transform_box(local_courtyards["J2"], j2["x"], j2["y"], 0.0)
    r1 = {
        "x": origin_x("R1", j1_box["xmax"] + courtyard_gap_mm),
        "y": j1["y"],
        "rotation": 0.0,
    }
    r1_box = transform_box(local_courtyards["R1"], r1["x"], r1["y"], 0.0)
    d1 = {
        "x": origin_x("D1", r1_box["xmax"] + courtyard_gap_mm),
        "y": j1["y"],
        "rotation": 180.0,
    }
    d1_box = transform_box(local_courtyards["D1"], d1["x"], d1["y"], 180.0)
    q1 = {
        "x": origin_x("Q1", d1_box["xmax"] + courtyard_gap_mm),
        "y": j1["y"],
        "rotation": 180.0,
    }
    q1_box = transform_box(local_courtyards["Q1"], q1["x"], q1["y"], 180.0)
    shift = 0.0
    if q1_box["ymin"] < inset_top:
        shift = inset_top - q1_box["ymin"]
    placements = {"J1": j1, "J2": j2, "R1": r1, "D1": d1, "Q1": q1}
    for item in placements.values():
        item["y"] = round(item["y"] + shift, 4)
        item["x"] = round(item["x"], 4)
    j2_box = transform_box(local_courtyards["J2"], placements["J2"]["x"], placements["J2"]["y"], 0.0)
    r2 = {
        "x": round(origin_x("R2", j2_box["xmax"] + courtyard_gap_mm), 4),
        "y": round(placements["J2"]["y"], 4),
        "rotation": 0.0,
    }
    r2_box = transform_box(local_courtyards["R2"], r2["x"], r2["y"], 0.0)
    r3 = {
        "x": round(origin_x("R3", r2_box["xmax"] + courtyard_gap_mm), 4),
        "y": round(r2["y"], 4),
        "rotation": 0.0,
    }
    placements["R2"] = r2
    placements["R3"] = r3
    return {
        "strategy": "led_switch_rules",
        "optimised": False,
        "board": {"width": width, "height": height, "center": {"x": 0.0, "y": 0.0}, "unit": "mm"},
        "edgeClearance": edge_clearance_mm,
        "courtyardGap": courtyard_gap_mm,
        "placements": placements,
        "rotations": {
            "D1": "180 degrees so the anode faces R1 and the cathode faces Q1",
            "Q1": "180 degrees so the collector faces D1",
        },
    }


def placed_parts(
    local_courtyards: Dict[str, Dict[str, float]],
    placements: Dict[str, Dict[str, float]],
    nets_by_ref: Optional[Dict[str, Iterable[str]]] = None,
    local_bodies: Optional[Dict[str, Dict[str, float]]] = None,
) -> List[Dict]:
    parts = []
    for reference, place in placements.items():
        rotation = float(place.get("rotation", 0.0))
        part = {
            "reference": reference,
            "x": float(place["x"]),
            "y": float(place["y"]),
            "rotation": rotation,
            "courtyard": transform_box(local_courtyards[reference], place["x"], place["y"], rotation),
            "nets": list((nets_by_ref or {}).get(reference, [])),
        }
        if local_bodies and reference in local_bodies:
            part["body"] = transform_box(local_bodies[reference], place["x"], place["y"], rotation)
        parts.append(part)
    return parts
