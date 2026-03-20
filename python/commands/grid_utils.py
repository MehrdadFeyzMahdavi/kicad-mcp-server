"""
Shared utilities for KiCad schematic manipulation.

Provides grid snapping, number formatting, and S-expression helpers
used across wire_manager, hierarchical_sheets, and other modules.
"""

from typing import Optional


def snap_to_grid(x: float, y: float, grid: float = 1.27) -> tuple:
    """Snap coordinates to the nearest grid point.

    Args:
        x: X coordinate in mm
        y: Y coordinate in mm
        grid: Grid spacing in mm (default 1.27mm = 50mil)

    Returns:
        (snapped_x, snapped_y) rounded to the nearest grid point
    """
    snapped_x = round(x / grid) * grid
    snapped_y = round(y / grid) * grid
    # Round to avoid floating-point artifacts (e.g. 50.799999... -> 50.8)
    snapped_x = round(snapped_x, 4)
    snapped_y = round(snapped_y, 4)
    return (snapped_x, snapped_y)


def fmt_coord(val) -> str:
    """Format a number for KiCad S-expression output.

    Integers and float values equal to integers are rendered without decimal point.
    """
    if isinstance(val, float) and val == int(val):
        return str(int(val))
    return str(val)


def find_balanced_end(content: str, start: int) -> Optional[int]:
    """Return the past-the-end position of a balanced parenthesized block.

    Handles parentheses inside quoted strings correctly.

    Args:
        content: Full text to search.
        start: Position of the opening '('.

    Returns:
        Index one past the matching ')', or None if unbalanced.
    """
    depth = 0
    in_string = False
    i = start
    while i < len(content):
        ch = content[i]
        if ch == '"' and (i == start or content[i - 1] != '\\'):
            in_string = not in_string
        elif not in_string:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return None
