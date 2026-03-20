"""
Obstacle-Aware Wire Router for KiCad Schematics

Grid-based A* Manhattan router that treats component bounding boxes as
obstacles. Falls back to simple orthogonal routing if no path is found.
"""

import heapq
import logging
import math
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from commands.grid_utils import snap_to_grid
from commands.schematic_layout import BoundingBox, SchematicLayout

logger = logging.getLogger("kicad_interface")

# Grid resolution for the A* router (1.27mm = standard KiCad schematic grid)
GRID = 1.27
# Maximum search area expansion beyond start/end points (in grid units)
MAX_SEARCH_RADIUS = 80  # ~100mm in each direction


def route_wire(
    start: Tuple[float, float],
    end: Tuple[float, float],
    layout: SchematicLayout,
    margin: float = 1.27,
) -> List[List[float]]:
    """Route a wire from start to end, avoiding component bounding boxes.

    Uses A* pathfinding on a 1.27mm grid with Manhattan (orthogonal) movement.
    Component bounding boxes are expanded by *margin* to keep wires from
    touching component bodies.

    Args:
        start: (x, y) start point in mm.
        end: (x, y) end point in mm.
        layout: SchematicLayout with placed component bounding boxes.
        margin: Extra clearance around obstacles in mm.

    Returns:
        List of [x, y] waypoints defining the wire path. If A* fails,
        falls back to simple orthogonal routing.
    """
    sx, sy = snap_to_grid(start[0], start[1])
    ex, ey = snap_to_grid(end[0], end[1])

    # Trivial case: same point
    if sx == ex and sy == ey:
        return [[sx, sy]]

    # Trivial case: aligned and no obstacles in the way
    if sx == ex or sy == ey:
        if not _line_hits_obstacle(sx, sy, ex, ey, layout, margin):
            return [[sx, sy], [ex, ey]]

    # Build obstacle set
    obstacles = _build_obstacle_grid(layout, margin, sx, sy, ex, ey)

    # Run A*
    path = _astar(sx, sy, ex, ey, obstacles)

    if path:
        # Simplify: remove collinear intermediate points
        simplified = _simplify_path(path)
        return simplified

    # Fallback: simple orthogonal routing (horizontal-first)
    logger.warning(
        f"A* routing failed from ({sx},{sy}) to ({ex},{ey}), "
        f"falling back to orthogonal"
    )
    return _fallback_orthogonal(sx, sy, ex, ey)


def _line_hits_obstacle(
    x1: float, y1: float, x2: float, y2: float,
    layout: SchematicLayout, margin: float,
) -> bool:
    """Check if a straight line between two points crosses any obstacle."""
    # Only works for axis-aligned lines
    if x1 != x2 and y1 != y2:
        return False  # Not axis-aligned, can't check simply

    line_bbox = BoundingBox(
        min(x1, x2) - 0.01, min(y1, y2) - 0.01,
        max(x1, x2) + 0.01, max(y1, y2) + 0.01,
    )

    for ref, bbox in layout.get_all_bboxes().items():
        if bbox.expanded(margin).overlaps(line_bbox):
            return True
    return False


def _build_obstacle_grid(
    layout: SchematicLayout,
    margin: float,
    sx: float, sy: float,
    ex: float, ey: float,
) -> Set[Tuple[int, int]]:
    """Convert component bounding boxes into a set of blocked grid cells."""
    obstacles: Set[Tuple[int, int]] = set()

    for ref, bbox in layout.get_all_bboxes().items():
        exp = bbox.expanded(margin)
        # Convert to grid coordinates
        gx_min = int(math.floor(exp.min_x / GRID)) - 1
        gx_max = int(math.ceil(exp.max_x / GRID)) + 1
        gy_min = int(math.floor(exp.min_y / GRID)) - 1
        gy_max = int(math.ceil(exp.max_y / GRID)) + 1

        for gx in range(gx_min, gx_max + 1):
            for gy in range(gy_min, gy_max + 1):
                obstacles.add((gx, gy))

    # Make sure start and end are never blocked
    sg = (round(sx / GRID), round(sy / GRID))
    eg = (round(ex / GRID), round(ey / GRID))
    obstacles.discard(sg)
    obstacles.discard(eg)

    return obstacles


def _astar(
    sx: float, sy: float,
    ex: float, ey: float,
    obstacles: Set[Tuple[int, int]],
) -> Optional[List[List[float]]]:
    """A* pathfinding on a grid with Manhattan movement.

    Returns a list of [x, y] waypoints, or None if no path found.
    """
    start_g = (round(sx / GRID), round(sy / GRID))
    end_g = (round(ex / GRID), round(ey / GRID))

    # Limit search area
    min_gx = min(start_g[0], end_g[0]) - MAX_SEARCH_RADIUS
    max_gx = max(start_g[0], end_g[0]) + MAX_SEARCH_RADIUS
    min_gy = min(start_g[1], end_g[1]) - MAX_SEARCH_RADIUS
    max_gy = max(start_g[1], end_g[1]) + MAX_SEARCH_RADIUS

    def heuristic(node):
        return abs(node[0] - end_g[0]) + abs(node[1] - end_g[1])

    # Priority queue: (f_score, counter, node)
    counter = 0
    open_set = [(heuristic(start_g), counter, start_g)]
    came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}
    g_score: Dict[Tuple[int, int], float] = {start_g: 0}

    # Neighbors: Manhattan movement (4 directions)
    directions = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    while open_set:
        _, _, current = heapq.heappop(open_set)

        if current == end_g:
            # Reconstruct path
            path = []
            node = current
            while node in came_from:
                path.append([node[0] * GRID, node[1] * GRID])
                node = came_from[node]
            path.append([node[0] * GRID, node[1] * GRID])
            path.reverse()
            return path

        for dx, dy in directions:
            neighbor = (current[0] + dx, current[1] + dy)

            # Bounds check
            if not (min_gx <= neighbor[0] <= max_gx and min_gy <= neighbor[1] <= max_gy):
                continue

            # Obstacle check
            if neighbor in obstacles:
                continue

            tentative_g = g_score[current] + 1

            if tentative_g < g_score.get(neighbor, float("inf")):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f = tentative_g + heuristic(neighbor)
                counter += 1
                heapq.heappush(open_set, (f, counter, neighbor))

    return None  # No path found


def _simplify_path(path: List[List[float]]) -> List[List[float]]:
    """Remove collinear intermediate points from a path."""
    if len(path) <= 2:
        return path

    result = [path[0]]
    for i in range(1, len(path) - 1):
        prev = result[-1]
        curr = path[i]
        next_pt = path[i + 1]

        # Keep point if direction changes
        dx1 = curr[0] - prev[0]
        dy1 = curr[1] - prev[1]
        dx2 = next_pt[0] - curr[0]
        dy2 = next_pt[1] - curr[1]

        if (dx1 != 0 and dx2 == 0) or (dx1 == 0 and dx2 != 0) or \
           (dy1 != 0 and dy2 == 0) or (dy1 == 0 and dy2 != 0):
            result.append(curr)

    result.append(path[-1])
    return result


def _fallback_orthogonal(
    sx: float, sy: float, ex: float, ey: float,
) -> List[List[float]]:
    """Simple orthogonal routing without obstacle avoidance."""
    if sx == ex or sy == ey:
        return [[sx, sy], [ex, ey]]
    # Horizontal first
    return [[sx, sy], [ex, sy], [ex, ey]]
