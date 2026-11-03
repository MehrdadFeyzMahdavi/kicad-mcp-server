"""Clearance-checked pad-to-pad routes. This module does not open a board."""

import math
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Point = Tuple[float, float]
Box = Dict[str, float]

COPPER_LAYERS = ("F.Cu", "B.Cu")
MIN_TRACK_WIDTH_MM = 0.2
MAX_TRACK_WIDTH_MM = 5.0

LED_SWITCH_LINKS = (
    ("J1", "1", "R1", "1", "+5V", 0.40),
    ("R1", "2", "D1", "2", "/LED_A", 0.25),
    ("D1", "1", "Q1", "3", "/LED_K", 0.25),
    ("J2", "1", "R2", "1", "/CTRL_IN", 0.25),
    ("R2", "2", "R3", "1", "/BASE", 0.25),
    ("R3", "1", "Q1", "2", "/BASE", 0.25),
    ("J1", "2", "J2", "2", "GND", 0.40),
    ("J2", "2", "R3", "2", "GND", 0.40),
    ("R3", "2", "Q1", "1", "GND", 0.40),
)


def track_width_error(width: float) -> Optional[str]:
    try:
        value = float(width)
    except (TypeError, ValueError):
        return "Track width must be a number of millimetres."
    if not math.isfinite(value) or value < MIN_TRACK_WIDTH_MM or value > MAX_TRACK_WIDTH_MM:
        return (
            f"Track width {width} mm is outside {MIN_TRACK_WIDTH_MM:.2f}–"
            f"{MAX_TRACK_WIDTH_MM:.2f} mm."
        )
    return None


def layer_error(layer: str) -> Optional[str]:
    if layer not in COPPER_LAYERS:
        return f"Layer '{layer}' is not a supported copper layer. Use F.Cu or B.Cu."
    return None


def track_obstacle(track: Dict, clearance: float, half_width: float) -> Box:
    inflate = clearance + half_width + float(track.get("width", 0.0)) / 2.0
    x1 = float(track["start"]["x"])
    y1 = float(track["start"]["y"])
    x2 = float(track["end"]["x"])
    y2 = float(track["end"]["y"])
    return {
        "xmin": min(x1, x2) - inflate,
        "ymin": min(y1, y2) - inflate,
        "xmax": max(x1, x2) + inflate,
        "ymax": max(y1, y2) + inflate,
    }


def pad_box(pad: Dict, clearance: float, half_width: float) -> Box:
    hx = float(pad["width"]) / 2.0 + clearance + half_width
    hy = float(pad["height"]) / 2.0 + clearance + half_width
    rotation = float(pad.get("rotation", 0.0)) % 180.0
    if abs(rotation - 90.0) < 1.0:
        hx, hy = hy, hx
    return {
        "xmin": float(pad["x"]) - hx,
        "ymin": float(pad["y"]) - hy,
        "xmax": float(pad["x"]) + hx,
        "ymax": float(pad["y"]) + hy,
    }


def _inside(x: float, y: float, box: Box, eps: float = 1e-9) -> bool:
    return box["xmin"] + eps < x < box["xmax"] - eps and box["ymin"] + eps < y < box["ymax"] - eps


def segment_hits_box(start: Point, end: Point, box: Box, eps: float = 1e-9) -> bool:
    """True when the open segment enters the open box. Touching the boundary is allowed."""
    x1, y1 = start
    x2, y2 = end
    dx = x2 - x1
    dy = y2 - y1
    pairs = ((-dx, x1 - box["xmin"]), (dx, box["xmax"] - x1), (-dy, y1 - box["ymin"]), (dy, box["ymax"] - y1))
    enter = 0.0
    leave = 1.0
    for direction, distance in pairs:
        if abs(direction) <= eps:
            if distance < -eps:
                return False
            continue
        hit = distance / direction
        if direction < 0:
            if hit > leave:
                return False
            if hit > enter:
                enter = hit
        else:
            if hit < enter:
                return False
            if hit < leave:
                leave = hit
    return leave - enter > eps and leave > eps and enter < 1.0 - eps


def segment_inside_board(start: Point, end: Point, board: Optional[Box]) -> bool:
    if board is None:
        return True
    for x, y in (start, end):
        if x < board["xmin"] - 1e-6 or x > board["xmax"] + 1e-6:
            return False
        if y < board["ymin"] - 1e-6 or y > board["ymax"] + 1e-6:
            return False
    return True


def _length(start: Point, end: Point) -> float:
    return math.hypot(end[0] - start[0], end[1] - start[1])


def _blocked(start: Point, end: Point, obstacles: Sequence[Box], board: Optional[Box]) -> bool:
    if _length(start, end) <= 1e-9:
        return True
    if not segment_inside_board(start, end, board):
        return True
    return any(segment_hits_box(start, end, box) for box in obstacles)


def _obstacles_for(
    pads: Sequence[Dict],
    net: str,
    ignored: Iterable[Tuple[str, str]],
    clearance: float,
    width: float,
    tracks: Sequence[Dict] = (),
) -> List[Box]:
    skip = {(ref, str(number)) for ref, number in ignored}
    half = width / 2.0
    boxes = []
    for pad in pads:
        if pad.get("net") == net:
            continue
        if (pad["reference"], str(pad["number"])) in skip:
            continue
        boxes.append(pad_box(pad, clearance, half))
    for track in tracks:
        if track.get("net") == net:
            continue
        boxes.append(track_obstacle(track, clearance, half))
    return boxes


def plan_pad_route(
    start: Dict,
    end: Dict,
    pads: Sequence[Dict],
    clearance: float,
    width: float,
    board: Optional[Box] = None,
    tracks: Sequence[Dict] = (),
) -> Dict:
    """Direct segment, then one bend, then a short escape bend. No search."""
    a = (float(start["x"]), float(start["y"]))
    b = (float(end["x"]), float(end["y"]))
    foreign = _obstacles_for(
        pads,
        str(start["net"]),
        ((start["reference"], start["number"]), (end["reference"], end["number"])),
        clearance,
        width,
        tracks,
    )
    direct = [(a, b)]
    if not _blocked(a, b, foreign, board):
        return {"success": True, "kind": "direct", "segments": direct, "length": _length(a, b)}

    candidates = []
    for corner in ((b[0], a[1]), (a[0], b[1])):
        if corner == a or corner == b:
            continue
        segments = [(a, corner), (corner, b)]
        if any(_blocked(left, right, foreign, board) for left, right in segments):
            continue
        candidates.append(("bend", segments, sum(_length(left, right) for left, right in segments)))

    escapes = []
    for pad, point in ((start, a), (end, b)):
        hx = float(pad["width"]) / 2.0 + clearance + width / 2.0 + 0.2
        hy = float(pad["height"]) / 2.0 + clearance + width / 2.0 + 0.2
        escapes.append((
            (point[0] + hx, point[1]),
            (point[0] - hx, point[1]),
            (point[0], point[1] + hy),
            (point[0], point[1] - hy),
        ))
    for left in escapes[0]:
        for right in escapes[1]:
            mids = (right[0], left[1]), (left[0], right[1])
            for mid in mids:
                segments = [(a, left), (left, mid), (mid, right), (right, b)]
                if any(_blocked(p1, p2, foreign, board) for p1, p2 in segments):
                    continue
                kind = "escape"
                length = sum(_length(p1, p2) for p1, p2 in segments)
                candidates.append((kind, segments, length))

    if not candidates:
        return {
            "success": False,
            "error": "CLEARANCE_CONFLICT",
            "message": "Every direct and single-bend route hits copper on another net. No track was created.",
            "segments": [],
        }
    kind, segments, length = min(candidates, key=lambda item: item[2])
    return {"success": True, "kind": kind, "segments": segments, "length": round(length, 6)}


def validate_connection(request: Dict, pads: Sequence[Dict], tracks: Sequence[Dict], board: Optional[Box] = None) -> Dict:
    """Accept one same-net connection or reject it before any track exists."""
    source_ref = request.get("sourceRef")
    source_pad = str(request.get("sourcePad", ""))
    dest_ref = request.get("destinationRef")
    dest_pad = str(request.get("destinationPad", ""))
    net = request.get("net")
    layer = request.get("layer", "F.Cu")
    width = request.get("width")
    clearance = float(request.get("clearance", 0.2))

    if not source_ref or not source_pad or not dest_ref or not dest_pad:
        return _reject("INVALID_ARGUMENT", "Source and destination reference and pad number are required.")
    if source_ref == dest_ref and source_pad == dest_pad:
        return _reject("INVALID_ARGUMENT", "The source and destination pads are the same pad.")
    if not isinstance(net, str) or not net.strip():
        return _reject("INVALID_ARGUMENT", "A net name is required.")
    net = net.strip()
    width_problem = track_width_error(width)
    if width_problem:
        return _reject("INVALID_WIDTH", width_problem)
    layer_problem = layer_error(layer)
    if layer_problem:
        return _reject("UNSUPPORTED_LAYER", layer_problem)
    if clearance < 0:
        return _reject("INVALID_ARGUMENT", "Clearance cannot be negative.")

    index = {(pad["reference"], str(pad["number"])): pad for pad in pads}
    start = index.get((source_ref, source_pad))
    finish = index.get((dest_ref, dest_pad))
    if start is None:
        return _reject("MISSING_PAD", f"{source_ref} pad {source_pad} is not on the board.")
    if finish is None:
        return _reject("MISSING_PAD", f"{dest_ref} pad {dest_pad} is not on the board.")
    if start.get("net") != net or finish.get("net") != net or start.get("net") != finish.get("net"):
        return _reject(
            "NET_MISMATCH",
            f"{source_ref}.{source_pad} is '{start.get('net')}' and "
            f"{dest_ref}.{dest_pad} is '{finish.get('net')}'. Requested net is '{net}'.",
        )
    if _already_connected(start, finish, tracks, net):
        return _reject("DUPLICATE_CONNECTION", f"{source_ref}.{source_pad} is already connected to {dest_ref}.{dest_pad} on {net}.")

    route = plan_pad_route(start, finish, pads, clearance, float(width), board, tracks)
    if not route.get("success"):
        return route
    segments = [
        {
            "start": {"x": round(left[0], 6), "y": round(left[1], 6)},
            "end": {"x": round(right[0], 6), "y": round(right[1], 6)},
            "width": float(width),
            "layer": layer,
            "net": net,
        }
        for left, right in route["segments"]
    ]
    return {
        "success": True,
        "net": net,
        "layer": layer,
        "width": float(width),
        "kind": route["kind"],
        "length": route["length"],
        "optimised": False,
        "segments": segments,
    }


def _already_connected(start: Dict, finish: Dict, tracks: Sequence[Dict], net: str) -> bool:
    nodes = {
        (start["reference"], str(start["number"])): (float(start["x"]), float(start["y"])),
        (finish["reference"], str(finish["number"])): (float(finish["x"]), float(finish["y"])),
    }
    edges = []
    for track in tracks:
        if track.get("net") != net:
            continue
        a = (float(track["start"]["x"]), float(track["start"]["y"]))
        b = (float(track["end"]["x"]), float(track["end"]["y"]))
        edges.append((a, b))
    if not edges:
        return False
    parent = {key: key for key in ("start", "finish")}

    def find(key):
        while parent[key] != key:
            parent[key] = parent[parent[key]]
            key = parent[key]
        return key

    def union(left, right):
        parent.setdefault(left, left)
        parent.setdefault(right, right)
        parent[find(left)] = find(right)

    points = [("start", nodes[(start["reference"], str(start["number"]))]), ("finish", nodes[(finish["reference"], str(finish["number"]))])]
    extra = []
    for index, (a, b) in enumerate(edges):
        extra.append((f"a{index}", a))
        extra.append((f"b{index}", b))
        union(f"a{index}", f"b{index}")
    for name, point in points + extra:
        parent.setdefault(name, name)
    for left_name, left_point in points + extra:
        for right_name, right_point in points + extra:
            if math.hypot(left_point[0] - right_point[0], left_point[1] - right_point[1]) <= 0.05:
                union(left_name, right_name)
    return find("start") == find("finish")


def _reject(code: str, message: str) -> Dict:
    return {"success": False, "error": code, "message": message, "segments": []}
