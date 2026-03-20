"""
Parameter-Aware Component Search for KiCad Symbol Libraries

Searches KiCad .kicad_sym library files by keywords, component type,
pin count, or property values. Returns matching components with their
lib_id, description, default footprint, and pin information.
"""

import os
import re
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("kicad_interface")


def search_components(
    query: str = "",
    library: Optional[str] = None,
    max_results: int = 20,
    library_paths: Optional[List[Path]] = None,
) -> dict:
    """Search KiCad symbol libraries for components matching criteria.

    Args:
        query: Search string matched against symbol name, description,
               and keyword properties (case-insensitive).
        library: Optional library name to restrict search (e.g. "Device").
        max_results: Maximum number of results to return.
        library_paths: Optional list of directories to search. If None,
                       uses standard KiCad library locations.

    Returns:
        {
            "success": True,
            "result_count": N,
            "results": [
                {
                    "lib_id": "Device:R",
                    "name": "R",
                    "library": "Device",
                    "description": "Resistor",
                    "keywords": "R res resistor",
                    "footprint_filters": ["R_*", "Resistor_*"],
                    "pin_count": 2,
                },
                ...
            ],
        }
    """
    try:
        if not query and not library:
            return {
                "success": False,
                "message": "At least one of query or library must be provided",
            }

        lib_dirs = library_paths or _find_kicad_symbol_libraries()
        if not lib_dirs:
            return {
                "success": False,
                "message": "No KiCad symbol library directories found",
            }

        results = []
        query_lower = query.lower()
        query_terms = query_lower.split() if query_lower else []

        for lib_dir in lib_dirs:
            if not lib_dir.is_dir():
                continue

            for lib_file in sorted(lib_dir.glob("*.kicad_sym")):
                lib_name = lib_file.stem
                if library and lib_name != library:
                    continue

                try:
                    matches = _search_library_file(lib_file, lib_name, query_terms)
                    results.extend(matches)
                except Exception as e:
                    logger.warning(f"Error scanning {lib_file}: {e}")
                    continue

                if len(results) >= max_results * 3:
                    break  # Early exit, we'll trim later

        # Sort by relevance (exact name match first, then by match quality)
        results.sort(key=lambda r: _relevance_score(r, query_terms), reverse=True)
        results = results[:max_results]

        return {
            "success": True,
            "result_count": len(results),
            "results": results,
        }

    except Exception as e:
        logger.error(f"Component search failed: {e}")
        return {"success": False, "message": str(e)}


def _find_kicad_symbol_libraries() -> List[Path]:
    """Find KiCad symbol library directories."""
    candidates = [
        Path("/usr/share/kicad/symbols"),
        Path("/usr/local/share/kicad/symbols"),
        Path("C:/Program Files/KiCad/9.0/share/kicad/symbols"),
        Path("C:/Program Files/KiCad/8.0/share/kicad/symbols"),
        Path("/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"),
        Path.home() / ".local" / "share" / "kicad" / "9.0" / "symbols",
    ]
    for env_var in ("KICAD9_SYMBOL_DIR", "KICAD8_SYMBOL_DIR", "KICAD_SYMBOL_DIR"):
        if env_var in os.environ:
            candidates.insert(0, Path(os.environ[env_var]))

    return [p for p in candidates if p.exists() and p.is_dir()]


def _search_library_file(
    lib_file: Path,
    lib_name: str,
    query_terms: List[str],
) -> List[dict]:
    """Search a single .kicad_sym file for matching symbols."""
    results = []

    with open(lib_file, "r", encoding="utf-8") as f:
        content = f.read()

    # Find top-level symbol definitions
    # Pattern: (symbol "SymbolName" ... ) at the first nesting level inside (kicad_symbol_lib ...)
    # We look for lines starting with a symbol definition
    symbol_pattern = re.compile(
        r'^\s{2,4}\(symbol\s+"([^"]+)"',
        re.MULTILINE,
    )

    for match in symbol_pattern.finditer(content):
        sym_name = match.group(1)

        # Skip sub-symbols (like R_0_1, R_1_1)
        if re.match(r'.*_\d+_\d+$', sym_name):
            continue

        # Extract the symbol block for property scanning
        block_start = match.start()
        block = _extract_block_fast(content, block_start)
        if not block:
            continue

        # Extract properties
        description = _extract_property(block, "Description") or ""
        keywords = _extract_property(block, "ki_keywords") or ""
        fp_filters = _extract_fp_filters(block)
        pin_count = block.count("(pin ")

        # Build searchable text
        searchable = f"{sym_name} {description} {keywords}".lower()

        # Check if all query terms match
        if query_terms and not all(term in searchable for term in query_terms):
            continue

        results.append({
            "lib_id": f"{lib_name}:{sym_name}",
            "name": sym_name,
            "library": lib_name,
            "description": description,
            "keywords": keywords,
            "footprint_filters": fp_filters,
            "pin_count": pin_count,
        })

    return results


def _extract_block_fast(content: str, start: int) -> Optional[str]:
    """Extract a balanced block starting from a position. Returns the block text."""
    # Find the opening paren
    paren_pos = content.find("(", start)
    if paren_pos == -1:
        return None

    depth = 0
    in_string = False
    i = paren_pos
    while i < len(content):
        ch = content[i]
        if ch == '"' and (i == paren_pos or content[i - 1] != '\\'):
            in_string = not in_string
        elif not in_string:
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
                if depth == 0:
                    return content[paren_pos:i + 1]
        i += 1
    return None


def _extract_property(block: str, prop_name: str) -> Optional[str]:
    """Extract a property value from a symbol block."""
    pattern = re.compile(
        r'\(property\s+"' + re.escape(prop_name) + r'"\s+"([^"]*)"',
        re.IGNORECASE,
    )
    match = pattern.search(block)
    return match.group(1) if match else None


def _extract_fp_filters(block: str) -> List[str]:
    """Extract footprint filter patterns from a symbol block."""
    filters = []
    # Pattern: (property "ki_fp_filters" "Filter1 Filter2 ...")
    fp_str = _extract_property(block, "ki_fp_filters")
    if fp_str:
        filters = fp_str.split()
    return filters


def _relevance_score(result: dict, query_terms: List[str]) -> float:
    """Score a result for relevance to the query."""
    score = 0.0
    name_lower = result["name"].lower()

    for term in query_terms:
        # Exact name match is best
        if name_lower == term:
            score += 100
        # Name starts with term
        elif name_lower.startswith(term):
            score += 50
        # Term in name
        elif term in name_lower:
            score += 20
        # Term in description
        elif term in result.get("description", "").lower():
            score += 10
        # Term in keywords
        elif term in result.get("keywords", "").lower():
            score += 5

    return score
