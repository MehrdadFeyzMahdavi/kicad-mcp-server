"""Parse kicad-cli schematic ERC JSON.

KiCad 10 puts violations in sheets[].violations. Older reports used a
top-level violations array. Command success is separate from ERC passing.
"""

from typing import Any, Dict, List


def _location(violation: Dict[str, Any]) -> Dict[str, float]:
    items = violation.get("items") or []
    if not items or not isinstance(items[0], dict):
        return {}
    position = items[0].get("pos") or {}
    if "x" not in position and "y" not in position:
        return {}
    return {"x": position.get("x", 0), "y": position.get("y", 0)}


def _collect(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    sheets = report.get("sheets")
    if isinstance(sheets, list):
        collected = []
        for sheet in sheets:
            if not isinstance(sheet, dict):
                continue
            sheet_path = sheet.get("path") or sheet.get("uuid_path") or ""
            for violation in sheet.get("violations") or []:
                if isinstance(violation, dict):
                    collected.append((sheet_path, violation))
        return collected

    collected = []
    for violation in report.get("violations") or []:
        if isinstance(violation, dict):
            collected.append(("", violation))
    return collected


def parse_kicad_erc_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Turn a kicad-cli ERC report into counts and violation records.

    ``success`` means the report was readable. ``ercPassed`` means it contains
    no errors. Warnings remain in the violation list either way.
    """
    violations = []
    severity_counts = {"error": 0, "warning": 0, "info": 0}
    for sheet_path, violation in _collect(report or {}):
        severity = violation.get("severity", "error")
        violations.append(
            {
                "type": violation.get("type", "unknown"),
                "severity": severity,
                "description": violation.get("description", ""),
                "sheet": sheet_path,
                "location": _location(violation),
            }
        )
        if severity in severity_counts:
            severity_counts[severity] += 1
        else:
            severity_counts[severity] = severity_counts.get(severity, 0) + 1

    error_count = severity_counts.get("error", 0)
    warning_count = severity_counts.get("warning", 0)
    return {
        "success": True,
        "ercPassed": error_count == 0,
        "message": (
            f"ERC complete: {error_count} error(s), {warning_count} warning(s)"
        ),
        "summary": {
            "total": len(violations),
            "errors": error_count,
            "warnings": warning_count,
            "by_severity": severity_counts,
        },
        "violations": violations,
        "kicadVersion": (report or {}).get("kicad_version", ""),
        "coordinateUnits": (report or {}).get("coordinate_units", ""),
    }
