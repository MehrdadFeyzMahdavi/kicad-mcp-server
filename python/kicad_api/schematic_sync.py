"""Offline schematic-to-PCB update.

The authoritative connectivity is the netlist exported by kicad-cli from the
schematic. Footprints are loaded from the installed KiCad libraries. The
target file is saved only after every footprint and pad assignment has been
checked in memory. This module does not write a board that is open in the
PCB editor; the caller enforces that guard first.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import sexpdata
from sexpdata import Symbol


class SyncFailure(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def find_kicad_cli() -> Optional[str]:
    sibling = Path(sys.executable).resolve().parent / "kicad-cli.exe"
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("kicad-cli")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe",
        r"C:\Program Files\KiCad\9.0\bin\kicad-cli.exe",
        r"C:\Program Files\KiCad\8.0\bin\kicad-cli.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def footprint_library_roots() -> List[Path]:
    candidates: List[Path] = []
    for name in (
        "KICAD_FOOTPRINT_DIR",
        "KICAD10_FOOTPRINT_DIR",
        "KICAD9_FOOTPRINT_DIR",
        "KICAD8_FOOTPRINT_DIR",
    ):
        value = os.environ.get(name)
        if value:
            candidates.append(Path(value))
    candidates.append(
        Path(sys.executable).resolve().parent.parent / "share" / "kicad" / "footprints"
    )
    program_roots = [
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ]
    for root in program_roots:
        kicad_root = Path(root) / "KiCad"
        if not kicad_root.is_dir():
            continue
        for version_dir in sorted(
            (child for child in kicad_root.iterdir() if child.is_dir()),
            key=lambda child: child.name,
            reverse=True,
        ):
            candidates.append(version_dir / "share" / "kicad" / "footprints")
    found: List[Path] = []
    seen = set()
    for path in candidates:
        try:
            key = str(path.resolve()).lower()
        except OSError:
            key = str(path).lower()
        if key in seen or not path.is_dir():
            continue
        seen.add(key)
        found.append(path)
    return found


def _token(value: Any) -> str:
    return str(value).strip('"')


def _child(node: list, name: str) -> Optional[list]:
    for item in node[1:]:
        if isinstance(item, list) and item and item[0] == Symbol(name):
            return item
    return None


def _children(node: list, name: str) -> List[list]:
    return [
        item
        for item in node[1:]
        if isinstance(item, list) and item and item[0] == Symbol(name)
    ]


def _text_value(node: Optional[list], index: int = 1) -> str:
    if not node or len(node) <= index:
        return ""
    return _token(node[index])


def parse_kicad_netlist(text: str) -> Dict[str, Any]:
    """Parse a kicad-cli sexpr netlist. Names are kept exactly as exported."""
    data = sexpdata.loads(text)
    if not isinstance(data, list) or not data or data[0] != Symbol("export"):
        raise SyncFailure("NETLIST_FORMAT", "The file is not a KiCad netlist export.")
    design = _child(data, "design")
    source = _text_value(_child(design, "source")) if design else ""
    components = []
    seen_refs = set()
    for comp in _children(_child(data, "components") or [Symbol("components")], "comp"):
        reference = _text_value(_child(comp, "ref"))
        if not reference:
            raise SyncFailure("NETLIST_FORMAT", "A component has no reference.")
        if reference in seen_refs:
            raise SyncFailure(
                "DUPLICATE_REFERENCE",
                f"The netlist contains more than one component {reference}.",
            )
        seen_refs.add(reference)
        libsource = _child(comp, "libsource")
        sheet_name = ""
        sheet_file = ""
        for prop in _children(comp, "property"):
            name_node = _child(prop, "name")
            value_node = _child(prop, "value")
            if name_node and value_node:
                if _text_value(name_node) == "Sheetname":
                    sheet_name = _text_value(value_node)
                elif _text_value(name_node) == "Sheetfile":
                    sheet_file = _text_value(value_node)
        components.append(
            {
                "reference": reference,
                "value": _text_value(_child(comp, "value")),
                "footprint": _text_value(_child(comp, "footprint")),
                "library": _text_value(_child(libsource, "lib")) if libsource else "",
                "symbol": _text_value(_child(libsource, "part")) if libsource else "",
                "tstamp": _text_value(_child(comp, "tstamps")),
                "sheetName": sheet_name,
                "sheetFile": sheet_file,
            }
        )
    nets = []
    for net in _children(_child(data, "nets") or [Symbol("nets")], "net"):
        name = _text_value(_child(net, "name"))
        if not name:
            raise SyncFailure("NETLIST_FORMAT", "A net has no name.")
        nodes = []
        for node in _children(net, "node"):
            nodes.append(
                {
                    "reference": _text_value(_child(node, "ref")),
                    "pin": _text_value(_child(node, "pin")),
                    "pinFunction": _text_value(_child(node, "pinfunction")),
                }
            )
        nets.append({"name": name, "nodes": nodes})
    return {"source": source, "components": components, "nets": nets}


def logical_net_name(name: str) -> str:
    """Compare local labels with or without KiCad's root-sheet slash."""
    return name[1:] if name.startswith("/") else name


def sheet_uuid(schematic_path: Path) -> str:
    text = schematic_path.read_text(encoding="utf-8")
    match = re.search(r"\(uuid ([0-9a-fA-F-]{36})\)", text)
    if not match:
        raise SyncFailure(
            "SCHEMATIC_IDENTITY",
            "The schematic has no sheet UUID.",
        )
    return match.group(1)


def export_cli_netlist(schematic_path: Path) -> str:
    cli = find_kicad_cli()
    if not cli:
        raise SyncFailure("KICAD_CLI_MISSING", "kicad-cli was not found.")
    with tempfile.TemporaryDirectory(prefix="kicad-sync-") as directory:
        output = Path(directory) / "netlist.net"
        completed = subprocess.run(
            [
                cli,
                "sch",
                "export",
                "netlist",
                "--format",
                "kicadsexpr",
                "--output",
                str(output),
                str(schematic_path),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise SyncFailure(
                "NETLIST_EXPORT_FAILED",
                f"kicad-cli did not export a netlist. {detail}",
            )
        return output.read_text(encoding="utf-8")


def _same_file(left: str, right: str) -> bool:
    try:
        return Path(left).resolve() == Path(right).resolve()
    except OSError:
        return False


def load_library_footprint(pcbnew, footprint_id: str):
    if ":" not in footprint_id:
        raise SyncFailure(
            "FOOTPRINT_ID",
            f"Footprint {footprint_id!r} is not a Library:Name identifier.",
        )
    library, name = footprint_id.split(":", 1)
    if not library or not name:
        raise SyncFailure("FOOTPRINT_ID", f"Footprint {footprint_id!r} is incomplete.")
    for root in footprint_library_roots():
        library_dir = root / f"{library}.pretty"
        module_file = library_dir / f"{name}.kicad_mod"
        if not module_file.is_file():
            continue
        loaded = pcbnew.FootprintLoad(str(library_dir), name)
        if loaded is None:
            continue
        loaded.SetFPID(pcbnew.LIB_ID(library, name))
        return loaded
    raise SyncFailure(
        "FOOTPRINT_NOT_FOUND",
        f"Footprint {footprint_id} is not in the installed KiCad libraries.",
    )


def _pad_geometry(footprint) -> List[Dict[str, Any]]:
    origin = footprint.GetPosition()
    pads = []
    for pad in footprint.Pads():
        drill = pad.GetDrillSize()
        size = pad.GetSize()
        position = pad.GetPosition()
        layer_set = ""
        try:
            layer_set = str(pad.GetLayerSet().FmtHex())
        except Exception:
            layer_set = ""
        pads.append(
            {
                "number": str(pad.GetNumber()),
                "size": (int(size.x), int(size.y)),
                "drill": (int(drill.x), int(drill.y)),
                "position": (int(position.x - origin.x), int(position.y - origin.y)),
                "layerSet": layer_set,
            }
        )
    return sorted(pads, key=lambda item: item["number"])


def _geometry_changed(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> bool:
    return before != after


def _ensure_net(board, pcbnew, name: str):
    existing = board.FindNet(name)
    if existing is not None and existing.GetNetname() == name:
        return existing
    board.Add(pcbnew.NETINFO_ITEM(board, name))
    created = board.FindNet(name)
    if created is None:
        raise SyncFailure("NET_CREATE_FAILED", f"Could not create net {name}.")
    return created


def _footprints_by_reference(board) -> Dict[str, Any]:
    found = {}
    for footprint in board.GetFootprints():
        reference = footprint.GetReference()
        if reference in found:
            raise SyncFailure(
                "DUPLICATE_REFERENCE",
                f"The board already contains more than one {reference}.",
            )
        found[reference] = footprint
    return found


def apply_netlist_to_board(
    pcbnew,
    board,
    netlist: Dict[str, Any],
    schematic_path: Path,
) -> Dict[str, Any]:
    """Place or update footprints. The caller saves only when this returns."""
    placed = [
        component
        for component in netlist["components"]
        if component["footprint"]
    ]
    if not placed:
        raise SyncFailure(
            "NO_FOOTPRINTS",
            "The netlist has no components with footprints.",
        )
    sheet = sheet_uuid(schematic_path)
    pad_nets: Dict[Tuple[str, str], str] = {}
    for net in netlist["nets"]:
        for node in net["nodes"]:
            key = (node["reference"], node["pin"])
            if key in pad_nets and pad_nets[key] != net["name"]:
                raise SyncFailure(
                    "NET_MISMATCH",
                    f"{key[0]} pad {key[1]} is on both {pad_nets[key]} and {net['name']}.",
                )
            pad_nets[key] = net["name"]

    existing = _footprints_by_reference(board)
    wanted = {component["reference"] for component in placed}
    created = []
    updated = []
    slot = 0
    for component in placed:
        reference = component["reference"]
        if not component["tstamp"]:
            raise SyncFailure(
                "SCHEMATIC_IDENTITY",
                f"{reference} has no schematic symbol identifier.",
            )
        footprint_id = component["footprint"]
        current = existing.get(reference)
        current_id = current.GetFPIDAsString() if current is not None else ""
        if current is not None and current_id == footprint_id:
            footprint = current
            updated.append(reference)
        else:
            if current is not None:
                board.Remove(current)
            footprint = load_library_footprint(pcbnew, footprint_id)
            before = _pad_geometry(footprint)
            footprint.SetPosition(
                pcbnew.VECTOR2I(int((20 + (slot % 4) * 25) * 1_000_000), int((20 + (slot // 4) * 25) * 1_000_000))
            )
            slot += 1
            board.Add(footprint)
            after = _pad_geometry(footprint)
            if _geometry_changed(before, after):
                raise SyncFailure(
                    "FOOTPRINT_GEOMETRY",
                    f"Adding {reference} changed the library footprint geometry.",
                )
            created.append(reference)
        footprint.SetReference(reference)
        footprint.SetValue(component["value"])
        footprint.SetFPID(pcbnew.LIB_ID(*footprint_id.split(":", 1)))
        path = pcbnew.KIID_PATH(f"/{sheet}/{component['tstamp']}")
        footprint.SetPath(path)
        footprint.SetSheetname(component["sheetName"] or "Root")
        footprint.SetSheetfile(schematic_path.name)
        pads = {str(pad.GetNumber()): pad for pad in footprint.Pads()}
        if len(pads) != len(list(footprint.Pads())):
            raise SyncFailure(
                "DUPLICATE_PAD",
                f"{reference} has more than one pad with the same number.",
            )
        expected_pads = {
            pin for (ref, pin), _name in pad_nets.items() if ref == reference
        }
        missing = sorted(expected_pads - set(pads))
        if missing:
            raise SyncFailure(
                "MISSING_PAD",
                f"{reference} has no pad {', '.join(missing)}.",
            )
        extra = sorted(set(pads) - expected_pads)
        if extra:
            raise SyncFailure(
                "UNASSIGNED_PAD",
                f"{reference} pad {', '.join(extra)} is not in the schematic netlist.",
            )
        for pin in expected_pads:
            pads[pin].SetNet(_ensure_net(board, pcbnew, pad_nets[(reference, pin)]))

    return {
        "created": created,
        "updated": updated,
        "references": sorted(wanted),
    }


def read_board_connectivity(pcbnew, board_path: Path) -> Dict[str, Any]:
    board = pcbnew.LoadBoard(str(board_path))
    footprints = []
    seen = set()
    for footprint in board.GetFootprints():
        reference = footprint.GetReference()
        if reference in seen:
            raise SyncFailure(
                "DUPLICATE_REFERENCE",
                f"Reloaded board contains more than one {reference}.",
            )
        seen.add(reference)
        pads = []
        for pad in footprint.Pads():
            net = pad.GetNet()
            pads.append(
                {
                    "number": str(pad.GetNumber()),
                    "net": net.GetNetname() if net is not None else "",
                    "drill": (int(pad.GetDrillSize().x), int(pad.GetDrillSize().y)),
                    "size": (int(pad.GetSize().x), int(pad.GetSize().y)),
                }
            )
        models = list(footprint.Models()) if hasattr(footprint, "Models") else []
        footprints.append(
            {
                "reference": reference,
                "value": footprint.GetValue(),
                "footprint": footprint.GetFPIDAsString(),
                "path": footprint.GetPath().AsString(),
                "sheetName": footprint.GetSheetname(),
                "sheetFile": footprint.GetSheetfile(),
                "position": (
                    int(footprint.GetPosition().x),
                    int(footprint.GetPosition().y),
                ),
                "padCount": len(pads),
                "pads": sorted(pads, key=lambda item: item["number"]),
                "modelCount": len(models),
            }
        )
    return {"footprints": sorted(footprints, key=lambda item: item["reference"])}


def connectivity_matches(netlist: Dict[str, Any], board_info: Dict[str, Any]) -> List[str]:
    expected: Dict[Tuple[str, str], str] = {}
    for net in netlist["nets"]:
        for node in net["nodes"]:
            if node["reference"] and node["pin"]:
                expected[(node["reference"], node["pin"])] = net["name"]
    actual: Dict[Tuple[str, str], str] = {}
    for footprint in board_info["footprints"]:
        for pad in footprint["pads"]:
            actual[(footprint["reference"], pad["number"])] = pad["net"]
    problems = []
    for key, net_name in sorted(expected.items()):
        if actual.get(key) != net_name:
            problems.append(
                f"{key[0]} pad {key[1]} is {actual.get(key, 'missing')}, expected {net_name}"
            )
    for key, net_name in sorted(actual.items()):
        if key not in expected:
            problems.append(f"{key[0]} pad {key[1]} has net {net_name} but no schematic node")
    return problems


def synchronize_schematic_to_pcb(
    schematic_path: str,
    board_path: str,
    internal_netlist: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Export the KiCad netlist, load real footprints, assign pads, and save.

    On failure the previous board bytes are restored. A board that did not
    exist is removed. The schematic file is only read.
    """
    schematic = Path(schematic_path)
    board = Path(board_path)
    if not schematic.is_file():
        raise SyncFailure("SCHEMATIC_NOT_FOUND", f"Schematic not found: {schematic}")
    if schematic.resolve() == board.resolve():
        raise SyncFailure(
            "SCHEMATIC_IDENTITY",
            "The PCB target is the same file as the schematic.",
        )
    schematic_before = schematic.read_bytes()
    netlist_text = export_cli_netlist(schematic)
    if schematic.read_bytes() != schematic_before:
        raise SyncFailure(
            "SCHEMATIC_CHANGED",
            "Exporting the netlist modified the schematic.",
        )
    netlist = parse_kicad_netlist(netlist_text)
    if not _same_file(netlist["source"], schematic):
        raise SyncFailure(
            "INCONSISTENT_SCHEMATIC",
            f"The netlist source is {netlist['source']}, not {schematic}.",
        )
    disagreements = []
    if internal_netlist is not None:
        disagreements = compare_internal_netlist(netlist, internal_netlist)
        if disagreements:
            raise SyncFailure(
                "NETLIST_DISAGREEMENT",
                "The internal netlist does not match kicad-cli: " + "; ".join(disagreements[:8]),
            )
    import pcbnew

    existed = board.is_file()
    previous = board.read_bytes() if existed else None
    if existed:
        working = pcbnew.LoadBoard(str(board))
    else:
        working = pcbnew.BOARD()
        working.SetFileName(str(board))
    saved = False
    try:
        summary = apply_netlist_to_board(pcbnew, working, netlist, schematic)
        board.parent.mkdir(parents=True, exist_ok=True)
        working.Save(str(board))
        saved = True
        reloaded = read_board_connectivity(pcbnew, board)
        problems = connectivity_matches(netlist, reloaded)
        if problems:
            raise SyncFailure("NET_MISMATCH", "; ".join(problems[:12]))
        by_ref = {item["reference"]: item for item in reloaded["footprints"]}
        for component in netlist["components"]:
            if not component["footprint"]:
                continue
            item = by_ref.get(component["reference"])
            if item is None:
                raise SyncFailure(
                    "FOOTPRINT_MISSING",
                    f"{component['reference']} is missing after reload.",
                )
            if item["footprint"] != component["footprint"]:
                raise SyncFailure(
                    "FOOTPRINT_ID",
                    f"{component['reference']} is {item['footprint']}, expected {component['footprint']}.",
                )
            if item["value"] != component["value"]:
                raise SyncFailure(
                    "VALUE_MISMATCH",
                    f"{component['reference']} value is {item['value']!r}.",
                )
            expected_path = f"/{sheet_uuid(schematic)}/{component['tstamp']}"
            if item["path"] != expected_path:
                raise SyncFailure(
                    "SCHEMATIC_IDENTITY",
                    f"{component['reference']} path is {item['path']}, expected {expected_path}.",
                )
    except Exception:
        if saved:
            if existed and previous is not None:
                board.write_bytes(previous)
            elif board.is_file():
                board.unlink()
        raise
    if schematic.read_bytes() != schematic_before:
        raise SyncFailure(
            "SCHEMATIC_CHANGED",
            "Synchronisation modified the schematic.",
        )
    return {
        "success": True,
        "boardPath": str(board),
        "schematicPath": str(schematic),
        "netlistSource": netlist["source"],
        "created": summary["created"],
        "updated": summary["updated"],
        "footprints": reloaded["footprints"],
        "nets": [net["name"] for net in netlist["nets"]],
        "internalNetlistAgrees": internal_netlist is not None and not disagreements,
    }


def compare_internal_netlist(cli_netlist: Dict[str, Any], internal: Dict[str, Any]) -> List[str]:
    """Return disagreements. A leading slash on a local net is not a disagreement."""
    placed = {
        component["reference"]
        for component in cli_netlist["components"]
        if component["footprint"]
    }
    cli_map = {}
    for net in cli_netlist["nets"]:
        for node in net["nodes"]:
            if node["reference"] in placed:
                cli_map[(node["reference"], node["pin"])] = logical_net_name(net["name"])
    internal_map = {}
    for net in internal.get("nets", []):
        for conn in net.get("connections", []):
            reference = conn.get("component", "")
            if reference in placed:
                internal_map[(reference, str(conn.get("pin", "")))] = logical_net_name(
                    net.get("name", "")
                )
    problems = []
    for key in sorted(set(cli_map) | set(internal_map)):
        if cli_map.get(key) != internal_map.get(key):
            problems.append(
                f"{key[0]}.{key[1]}: kicad-cli {cli_map.get(key)!r}, internal {internal_map.get(key)!r}"
            )
    return problems
