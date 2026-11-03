"""Decisions for PCB file ownership.

Live KiCad editor documents are not loaded or overwritten by the SWIG board.
Offline creates, explicit saves, and exports stay available when the target
file is not the editor's document.
"""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


IPC_UNAVAILABLE_ERROR = "IPC_UNAVAILABLE"
IPC_UNAVAILABLE_MESSAGE = (
    "Live PCB editing requires an active KiCad IPC connection."
)

# SWIG commands that change a board and then hit the auto-save path.
BOARD_MUTATING_COMMANDS = frozenset(
    {
        "place_component",
        "move_component",
        "rotate_component",
        "delete_component",
        "route_trace",
        "route_pad_to_pad",
        "add_via",
        "delete_trace",
        "add_net",
        "add_board_outline",
        "add_mounting_hole",
        "add_text",
        "add_board_text",
        "add_copper_pour",
        "refill_zones",
        "import_svg_logo",
        "sync_schematic_to_board",
        "connect_passthrough",
    }
)

EXPLICIT_FILE_COMMANDS = frozenset(
    {
        "create_project",
        "save_project",
        "sync_schematic_to_board",
        "import_svg_logo",
        "refill_zones",
    }
)

SWIG_LOAD_COMMANDS = frozenset({"open_project", "place_component"})

GUARDED_PCB_COMMANDS = BOARD_MUTATING_COMMANDS | EXPLICIT_FILE_COMMANDS | SWIG_LOAD_COMMANDS


def ipc_unavailable_result() -> Dict[str, Any]:
    """Structured error used when a live-board command cannot use IPC."""
    return {
        "success": False,
        "error": IPC_UNAVAILABLE_ERROR,
        "message": IPC_UNAVAILABLE_MESSAGE,
        "_backend": "unavailable",
        "_realtime": False,
    }


def normalize_pcb_path(path: str) -> str:
    """Return a comparable absolute path. The file does not need to exist."""
    return str(Path(os.path.expanduser(path)).resolve())


def paths_refer_to_same_file(left: str, right: str) -> bool:
    if not left or not right:
        return False
    try:
        return normalize_pcb_path(left) == normalize_pcb_path(right)
    except OSError:
        return os.path.normcase(os.path.abspath(os.path.expanduser(left))) == os.path.normcase(
            os.path.abspath(os.path.expanduser(right))
        )


def kicad_lock_candidates(board_path: str) -> List[Path]:
    """Possible KiCad lock files for a board path.

    KiCad's lock file for ``board.kicad_pcb`` is ``.board.kicad_pcb.lock``.
    The other names cover older and alternate lock filenames.
    """
    path = Path(os.path.expanduser(board_path))
    name = path.name
    parent = path.parent
    return [
        parent / f".{name}.lock",
        parent / f"{name}.lock",
        parent / f"~{name}.lck",
    ]


def lock_file_present(board_path: str) -> Optional[str]:
    if not board_path:
        return None
    for candidate in kicad_lock_candidates(board_path):
        try:
            if candidate.is_file():
                return str(candidate)
        except OSError:
            continue
    return None


def matches_live_editor(board_path: str, live_paths: Iterable[str]) -> bool:
    return any(paths_refer_to_same_file(board_path, live) for live in live_paths)


def board_path_for_open(filename: Optional[str]) -> str:
    if not filename:
        return ""
    expanded = os.path.abspath(os.path.expanduser(filename))
    if expanded.endswith(".kicad_pro"):
        return expanded[: -len(".kicad_pro")] + ".kicad_pcb"
    return expanded


def board_path_for_create(params: Dict[str, Any]) -> str:
    """Match ProjectCommands.create_project's destination PCB path."""
    project_name = params.get("name") or params.get("projectName") or "New_Project"
    path = params.get("path") or os.getcwd()
    project_path = os.path.join(path, project_name)
    if not str(project_path).endswith(".kicad_pro"):
        project_path += ".kicad_pro"
    return str(project_path).replace(".kicad_pro", ".kicad_pcb")


def swig_target_paths(command: str, params: Optional[Dict[str, Any]], current_board_path: str) -> List[str]:
    """PCB files a SWIG command would load or write."""
    params = params or {}
    if command == "open_project":
        path = board_path_for_open(params.get("filename"))
        return [path] if path else []
    if command == "create_project":
        return [board_path_for_create(params)]
    if command == "save_project":
        path = params.get("filename") or current_board_path
        return [path] if path else []
    if command == "sync_schematic_to_board":
        path = params.get("boardPath") or current_board_path
        return [path] if path else []
    if command == "import_svg_logo":
        path = params.get("pcbPath") or ""
        return [path] if path else []
    if command == "place_component":
        path = params.get("boardPath") or current_board_path
        return [path] if path else []
    if command in BOARD_MUTATING_COMMANDS:
        return [current_board_path] if current_board_path else []
    return []


def access_purpose(command: str) -> str:
    if command in SWIG_LOAD_COMMANDS:
        return "swig_load"
    if command in EXPLICIT_FILE_COMMANDS:
        return "explicit_file"
    return "autosave"


def evaluate_pcb_file_access(
    board_path: str,
    *,
    live_paths: Sequence[str],
    locked: bool,
    use_ipc: bool,
    purpose: str,
    owned: bool,
    live_paths_unknown: bool = False,
) -> Dict[str, Any]:
    """Decide whether SWIG may load or write this PCB file.

    ``purpose`` is ``autosave``, ``swig_load``, or ``explicit_file``.
    """
    if not board_path:
        return {
            "allow": False,
            "error": "NO_PCB_PATH",
            "reason": "no_path",
            "message": "No PCB file path is available for this file operation.",
        }

    if live_paths_unknown:
        return {
            "allow": False,
            "error": "EDITOR_STATE_UNKNOWN",
            "reason": "live_paths_unknown",
            "message": (
                "The open PCB editor document could not be identified. "
                "Refusing to load or overwrite a PCB file."
            ),
        }

    if matches_live_editor(board_path, live_paths) or locked:
        reason = "live_editor_document" if matches_live_editor(board_path, live_paths) else "lock_file"
        return {
            "allow": False,
            "error": "EDITOR_OWNS_FILE",
            "reason": reason,
            "message": (
                "The PCB file is open in the KiCad editor. "
                "This command will not load or overwrite it."
            ),
        }

    if purpose in ("autosave", "swig_load") and use_ipc:
        return {
            "allow": False,
            "error": "LIVE_SESSION",
            "reason": "live_ipc_mode",
            "message": "Live IPC mode does not load or save the PCB through the SWIG board.",
        }

    if purpose == "autosave" and not owned:
        return {
            "allow": False,
            "error": "FILE_NOT_OWNED",
            "reason": "not_owned",
            "message": (
                "Offline auto-save only writes a PCB file that this process opened or created."
            ),
        }

    return {"allow": True, "reason": "allowed", "error": "", "message": ""}


def _finite(value: Any, name: str) -> Optional[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return f"{name} must be a finite number"
    if not math.isfinite(float(value)):
        return f"{name} must be a finite number"
    return None


def _to_mm(value: float, unit: str) -> float:
    if unit == "inch":
        return float(value) * 25.4
    return float(value)


def outline_primitives(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build Edge.Cuts geometry in millimetres. No KiCad objects are created."""
    params = params or {}
    nested = params.get("params")
    inner = nested if isinstance(nested, dict) else params
    shape = params.get("shape", inner.get("shape", "rectangle"))
    unit = inner.get("unit", params.get("unit", "mm"))
    if unit not in ("mm", "inch"):
        return {"success": False, "error": "INVALID_ARGUMENT", "message": "unit must be mm or inch"}

    width = inner.get("width", params.get("width"))
    height = inner.get("height", params.get("height"))
    radius = inner.get("radius", params.get("radius"))
    corner_radius = inner.get(
        "cornerRadius",
        inner.get("radius", params.get("cornerRadius", 0)),
    )
    if shape == "circle":
        corner_radius = 0
    points = inner.get("points", params.get("points", []))
    x = inner.get("x", params.get("x"))
    y = inner.get("y", params.get("y"))

    if shape == "rectangle" and corner_radius not in (None, 0):
        shape = "rounded_rectangle"

    if shape not in ("rectangle", "rounded_rectangle", "circle", "polygon"):
        return {
            "success": False,
            "error": "UNSUPPORTED_OPERATION",
            "message": f"Board outline shape '{shape}' is not supported.",
        }

    def mm(value: Any, name: str) -> float:
        error = _finite(value, name)
        if error:
            raise ValueError(error)
        return _to_mm(float(value), unit)

    try:
        if shape in ("rectangle", "rounded_rectangle"):
            if width is None or height is None:
                return {
                    "success": False,
                    "error": "INVALID_ARGUMENT",
                    "message": "Both width and height are required for a rectangular outline.",
                }
            width_mm = mm(width, "width")
            height_mm = mm(height, "height")
            if width_mm <= 0 or height_mm <= 0:
                return {
                    "success": False,
                    "error": "INVALID_ARGUMENT",
                    "message": "Outline width and height must be positive.",
                }
            left = mm(0 if x is None else x, "x")
            top = mm(0 if y is None else y, "y")
            if shape == "rectangle" or not corner_radius:
                return {
                    "success": True,
                    "shape": "rectangle",
                    "primitives": [
                        {
                            "type": "rectangle",
                            "x": left,
                            "y": top,
                            "width": width_mm,
                            "height": height_mm,
                        }
                    ],
                }
            radius_mm = mm(corner_radius, "cornerRadius")
            radius_mm = min(radius_mm, width_mm / 2.0, height_mm / 2.0)
            if radius_mm <= 0:
                return {
                    "success": True,
                    "shape": "rectangle",
                    "primitives": [
                        {
                            "type": "rectangle",
                            "x": left,
                            "y": top,
                            "width": width_mm,
                            "height": height_mm,
                        }
                    ],
                }
            return {
                "success": True,
                "shape": "rounded_rectangle",
                "primitives": _rounded_rectangle(left, top, width_mm, height_mm, radius_mm),
            }

        if shape == "circle":
            if radius is None:
                return {
                    "success": False,
                    "error": "INVALID_ARGUMENT",
                    "message": "Radius is required for a circular outline.",
                }
            radius_mm = mm(radius, "radius")
            if radius_mm <= 0:
                return {
                    "success": False,
                    "error": "INVALID_ARGUMENT",
                    "message": "Outline radius must be positive.",
                }
            center_x = mm(0 if x is None else x, "x")
            center_y = mm(0 if y is None else y, "y")
            if width is not None:
                center_x += mm(width, "width") / 2.0
            if height is not None:
                center_y += mm(height, "height") / 2.0
            return {
                "success": True,
                "shape": "circle",
                "primitives": [
                    {
                        "type": "circle",
                        "cx": center_x,
                        "cy": center_y,
                        "radius": radius_mm,
                    }
                ],
            }

        if not isinstance(points, list) or len(points) < 3:
            return {
                "success": False,
                "error": "INVALID_ARGUMENT",
                "message": "At least 3 points are required for a polygon outline.",
            }
        polygon = []
        for index, point in enumerate(points):
            if not isinstance(point, dict):
                return {
                    "success": False,
                    "error": "INVALID_ARGUMENT",
                    "message": "Each polygon point must contain x and y.",
                }
            polygon.append((mm(point.get("x"), f"points[{index}].x"), mm(point.get("y"), f"points[{index}].y")))
        segments = []
        for index, start in enumerate(polygon):
            end = polygon[(index + 1) % len(polygon)]
            segments.append(
                {
                    "type": "segment",
                    "x1": start[0],
                    "y1": start[1],
                    "x2": end[0],
                    "y2": end[1],
                }
            )
        return {"success": True, "shape": "polygon", "primitives": segments}
    except ValueError as exc:
        return {"success": False, "error": "INVALID_ARGUMENT", "message": str(exc)}


def _rounded_rectangle(
    left: float, top: float, width: float, height: float, radius: float
) -> List[Dict[str, Any]]:
    """Four straight edges and four quarter-circle corners, in millimetres."""
    right = left + width
    bottom = top + height
    centers = (
        (left + radius, top + radius, 180.0, 270.0),
        (right - radius, top + radius, 270.0, 360.0),
        (right - radius, bottom - radius, 0.0, 90.0),
        (left + radius, bottom - radius, 90.0, 180.0),
    )
    primitives: List[Dict[str, Any]] = []
    endpoints = []
    for cx, cy, start_angle, end_angle in centers:
        start = _polar(cx, cy, radius, start_angle)
        mid = _polar(cx, cy, radius, (start_angle + end_angle) / 2.0)
        end = _polar(cx, cy, radius, end_angle)
        endpoints.append((start, end))
        primitives.append(
            {
                "type": "arc",
                "x1": start[0],
                "y1": start[1],
                "mx": mid[0],
                "my": mid[1],
                "x2": end[0],
                "y2": end[1],
            }
        )
    # Connect each corner's end to the next corner's start.
    for index, (_start, end) in enumerate(endpoints):
        nxt = endpoints[(index + 1) % len(endpoints)][0]
        primitives.append(
            {"type": "segment", "x1": end[0], "y1": end[1], "x2": nxt[0], "y2": nxt[1]}
        )
    return primitives


def _polar(cx: float, cy: float, radius: float, degrees: float) -> tuple:
    radians = math.radians(degrees)
    return (cx + radius * math.cos(radians), cy + radius * math.sin(radians))
