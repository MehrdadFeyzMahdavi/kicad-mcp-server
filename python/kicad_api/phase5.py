"""Routing for the twelve previously unrouted MCP tools.

Aliases are used only where the published schema matches an existing
operation. File exports copy their input before calling kicad-cli so the
open PCB and schematic are not the process input.
"""

from __future__ import annotations

import csv
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence


NETLIST_FORMATS = {
    "KiCad": "kicadsexpr",
    "Spice": "spice",
    "Cadstar": "cadstar",
    "OrcadPCB2": "orcadpcb2",
}

PROTECTED_SUFFIXES = {".kicad_pcb", ".kicad_sch", ".kicad_pro", ".kicad_prl"}


def unsupported(message: str) -> Dict[str, Any]:
    return {
        "success": False,
        "error": "UNSUPPORTED_OPERATION",
        "message": message,
        "_keep_backend": True,
        "_backend": "unavailable",
    }


def external(result: Dict[str, Any]) -> Dict[str, Any]:
    result["_keep_backend"] = True
    result["_backend"] = "external"
    return result


def add_wire_result(_params: Dict[str, Any]) -> Dict[str, Any]:
    return unsupported(
        "add_wire is not an alias of add_schematic_wire. "
        "add_wire takes start and end points and no schematic path. "
        "add_schematic_wire edits a schematic file named by schematicPath, "
        "using startPoint and endPoint. No schematic was edited."
    )


def add_net_class_result(_params: Dict[str, Any]) -> Dict[str, Any]:
    return unsupported(
        "add_net_class is not an alias of create_netclass. "
        "The registered tool requires clearance, trackWidth, viaDiameter, and viaDrill, "
        "and can also carry a description, microvia sizes, differential-pair rules, and a net list. "
        "create_netclass writes those rules through the SWIG board object. "
        "KiCad 10 IPC can read a net's class and cannot create one. No net class was created."
    )


def assign_net_to_class_result(_params: Dict[str, Any]) -> Dict[str, Any]:
    return unsupported(
        "KiCad 10 IPC can read the class of a net and cannot assign a net to a class. "
        "The SWIG net-class editor is not used on an open PCB. No assignment was made."
    )


def check_clearance_result(_params: Dict[str, Any]) -> Dict[str, Any]:
    return unsupported(
        "KiCad 10 IPC has no pairwise clearance query. "
        "A distance estimate would not be the design-rule result, so no pass or fail is reported."
    )


def replace_component_result(_params: Dict[str, Any]) -> Dict[str, Any]:
    return unsupported(
        "KiCad 10 IPC cannot change the library definition of an existing footprint in place. "
        "Deleting it and placing another would change its id and pad nets. No component was replaced."
    )


def set_layer_constraints_result(_params: Dict[str, Any]) -> Dict[str, Any]:
    return unsupported(
        "KiCad 10 IPC has no per-layer minimum track, clearance, or via constraint command. "
        "Board stackup updates are a different operation. No constraint was changed."
    )


def _protected_output(path: Path, open_paths: Sequence[str]) -> Optional[str]:
    if path.suffix.lower() in PROTECTED_SUFFIXES:
        return "The export path must not be a KiCad board, schematic, or project file."
    resolved = str(path.resolve())
    for candidate in open_paths:
        if candidate and str(Path(candidate).resolve()) == resolved:
            return "The export path is the open PCB."
    return None


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _kicad_cli() -> Optional[Path]:
    sibling = Path(sys.executable).resolve().parent / "kicad-cli.exe"
    if sibling.is_file():
        return sibling
    found = shutil.which("kicad-cli")
    return Path(found) if found else None


def _run_cli(command: List[str], timeout: int, runner: Optional[Callable] = None) -> Dict[str, Any]:
    if runner is not None:
        return runner(command)
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {"returncode": 124, "stdout": "", "stderr": "kicad-cli timed out"}
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def export_position_file(components: List[Dict[str, Any]], params: Dict[str, Any]) -> Dict[str, Any]:
    output = params.get("outputPath")
    if not isinstance(output, str) or not output.strip():
        return {"success": False, "error": "INVALID_ARGUMENT", "message": "outputPath is required."}
    file_format = params.get("format") or "CSV"
    units = params.get("units") or "mm"
    side = params.get("side") or "both"
    if file_format not in ("CSV", "ASCII"):
        return {"success": False, "error": "INVALID_ARGUMENT", "message": "format must be CSV or ASCII."}
    if units not in ("mm", "inch"):
        return {"success": False, "error": "INVALID_ARGUMENT", "message": "units must be mm or inch."}
    if side not in ("top", "bottom", "both"):
        return {"success": False, "error": "INVALID_ARGUMENT", "message": "side must be top, bottom, or both."}

    path = Path(output).expanduser()
    refusal = _protected_output(path, params.get("_open_paths") or [])
    if refusal:
        return {"success": False, "error": "INVALID_ARGUMENT", "message": refusal}

    scale = 1 / 25.4 if units == "inch" else 1.0
    rows = []
    for component in components:
        layer = component.get("layer")
        component_side = "top" if layer == "F.Cu" else "bottom" if layer == "B.Cu" else str(layer)
        if side != "both" and component_side != side:
            continue
        position = component.get("position") or {}
        rows.append(
            {
                "Ref": component.get("reference", ""),
                "Val": component.get("value", ""),
                "Package": component.get("footprint", ""),
                "PosX": f"{float(position.get('x', 0)) * scale:.6f}",
                "PosY": f"{float(position.get('y', 0)) * scale:.6f}",
                "Rot": f"{float(component.get('rotation', 0)):.6f}",
                "Side": component_side,
            }
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["Ref", "Val", "Package", "PosX", "PosY", "Rot", "Side"]
    if file_format == "CSV":
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        lines = [
            f"## Unit = {units}, Angle = deg.",
            f"## Side : {side}",
            " ".join(fieldnames),
        ]
        lines.extend(" ".join(row[name] for name in fieldnames) for row in rows)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    written = path.read_text(encoding="utf-8")
    missing = [row["Ref"] for row in rows if row["Ref"] and row["Ref"] not in written]
    if missing or not path.is_file():
        return {
            "success": False,
            "error": "IPC_ERROR",
            "message": "The position file did not contain the exported references.",
        }
    return {
        "success": True,
        "outputPath": str(path),
        "format": file_format,
        "units": units,
        "side": side,
        "count": len(rows),
        "message": f"Exported {len(rows)} position(s).",
    }


def _schematic_for_board(board_path: str) -> Path:
    return Path(board_path).with_suffix(".kicad_sch")


def export_netlist(
    board_path: str,
    params: Dict[str, Any],
    runner: Optional[Callable] = None,
) -> Dict[str, Any]:
    output = params.get("outputPath")
    if not isinstance(output, str) or not output.strip():
        return external({"success": False, "error": "INVALID_ARGUMENT", "message": "outputPath is required."})
    file_format = params.get("format") or "KiCad"
    if file_format not in NETLIST_FORMATS:
        return external(
            {
                "success": False,
                "error": "INVALID_ARGUMENT",
                "message": "format must be KiCad, Spice, Cadstar, or OrcadPCB2.",
            }
        )
    destination = Path(output).expanduser()
    refusal = _protected_output(destination, [board_path])
    if refusal:
        return external({"success": False, "error": "INVALID_ARGUMENT", "message": refusal})
    schematic = _schematic_for_board(board_path)
    if not schematic.is_file():
        return external(
            {
                "success": False,
                "error": "NOT_FOUND",
                "message": (
                    f"No schematic named {schematic.name} is next to the open PCB. "
                    "A different schematic in the directory was not used."
                ),
                "expectedSchematic": str(schematic),
            }
        )
    cli = _kicad_cli()
    if cli is None:
        return external({"success": False, "error": "UNSUPPORTED_OPERATION", "message": "kicad-cli was not found."})

    before = _file_hash(schematic)
    with tempfile.TemporaryDirectory(prefix="kicad-mcp-netlist-") as temporary:
        copied = Path(temporary) / schematic.name
        shutil.copy2(schematic, copied)
        command = [
            str(cli),
            "sch",
            "export",
            "netlist",
            "--format",
            NETLIST_FORMATS[file_format],
            "--output",
            str(destination),
            str(copied),
        ]
        completed = _run_cli(command, timeout=60, runner=runner)
    after = _file_hash(schematic)
    if after != before:
        return external(
            {
                "success": False,
                "error": "IPC_ERROR",
                "message": "The schematic file changed while exporting the netlist.",
            }
        )
    if completed["returncode"] != 0 or not destination.is_file() or destination.stat().st_size == 0:
        return external(
            {
                "success": False,
                "error": "IPC_ERROR",
                "message": completed.get("stderr") or "kicad-cli did not write a netlist.",
            }
        )
    return external(
        {
            "success": True,
            "outputPath": str(destination),
            "format": file_format,
            "source": "saved-schematic-copy",
            "schematic": str(schematic),
            "message": "Exported the saved schematic. Unsaved editor changes are not included.",
        }
    )


def export_vrml(
    board_path: str,
    params: Dict[str, Any],
    runner: Optional[Callable] = None,
) -> Dict[str, Any]:
    output = params.get("outputPath")
    if not isinstance(output, str) or not output.strip():
        return external({"success": False, "error": "INVALID_ARGUMENT", "message": "outputPath is required."})
    include_components = params.get("includeComponents", True)
    relative_paths = params.get("useRelativePaths", False)
    if not isinstance(include_components, bool) or not isinstance(relative_paths, bool):
        return external(
            {"success": False, "error": "INVALID_ARGUMENT", "message": "includeComponents and useRelativePaths must be booleans."}
        )
    if include_components is False:
        return unsupported(
            "kicad-cli VRML export has no switch that omits component models entirely. "
            "No VRML file was written."
        )
    destination = Path(output).expanduser()
    refusal = _protected_output(destination, [board_path])
    if refusal:
        return external({"success": False, "error": "INVALID_ARGUMENT", "message": refusal})
    source = Path(board_path)
    if not source.is_file():
        return external({"success": False, "error": "NOT_FOUND", "message": "The open PCB file is not readable."})
    cli = _kicad_cli()
    if cli is None:
        return external({"success": False, "error": "UNSUPPORTED_OPERATION", "message": "kicad-cli was not found."})

    before = _file_hash(source)
    with tempfile.TemporaryDirectory(prefix="kicad-mcp-vrml-") as temporary:
        copied = Path(temporary) / source.name
        shutil.copy2(source, copied)
        command = [str(cli), "pcb", "export", "vrml", "--output", str(destination), "--units", "mm"]
        if relative_paths:
            command.extend(["--models-dir", "models", "--models-relative"])
        command.append(str(copied))
        completed = _run_cli(command, timeout=120, runner=runner)
    after = _file_hash(source)
    if after != before:
        return external(
            {
                "success": False,
                "error": "IPC_ERROR",
                "message": "The PCB file changed while exporting VRML.",
            }
        )
    if completed["returncode"] != 0 or not destination.is_file() or destination.stat().st_size == 0:
        return external(
            {
                "success": False,
                "error": "IPC_ERROR",
                "message": completed.get("stderr") or "kicad-cli did not write a VRML file.",
            }
        )
    head = destination.read_text(encoding="utf-8", errors="ignore")[:200]
    if "#VRML" not in head:
        destination.unlink(missing_ok=True)
        return external(
            {
                "success": False,
                "error": "IPC_ERROR",
                "message": "The exported file is not VRML.",
            }
        )
    return external(
        {
            "success": True,
            "outputPath": str(destination),
            "source": "saved-pcb-copy",
            "includeComponents": True,
            "useRelativePaths": relative_paths,
            "message": "Exported VRML from a copy of the saved PCB. Unsaved editor changes are not included.",
        }
    )
