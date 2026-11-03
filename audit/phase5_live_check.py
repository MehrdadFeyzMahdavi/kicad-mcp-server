"""Live Phase 5 check. Mutates only the disposable IPC board, and never saves it."""

import hashlib
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

os.environ["KICAD_BACKEND"] = "ipc"
os.environ["KICAD_AUTO_LAUNCH"] = "false"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

ALLOWED = Path(r"C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\ipc-phase3-test.kicad_pcb").resolve()
ORIGINAL = Path(r"C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\ipc-move-test.kicad_pcb").resolve()
OUT = Path(__file__).resolve().parent / "phase5_live_output.json"


def file_stamp(path: Path) -> dict:
    data = path.read_bytes()
    stat = path.stat()
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main() -> int:
    import pcbnew
    from kicad_interface import KiCADInterface

    blocked = {"save": 0, "load": 0}

    def refuse_save(*_args, **_kwargs):
        blocked["save"] += 1
        raise RuntimeError("Phase 5 blocked a SWIG board save")

    def refuse_load(*_args, **_kwargs):
        blocked["load"] += 1
        raise RuntimeError("Phase 5 blocked a SWIG board load")

    pcbnew.SaveBoard = refuse_save
    pcbnew.LoadBoard = refuse_load

    record = {"steps": [], "failures": [], "error": None}
    interface = KiCADInterface()
    api = interface.ipc_board_api
    created_refs = []
    baseline_zone_ids = None

    def open_paths():
        return [str(Path(path).resolve()) for path in api._open_pcb_paths()]

    def require_allowed():
        paths = open_paths()
        if paths != [str(ALLOWED)]:
            raise RuntimeError(f"Open PCB is not the disposable board: {paths}")
        return paths

    def step(name, payload):
        record["steps"].append({"name": name, "result": payload})
        print(name, json.dumps(payload, default=str)[:700], flush=True)

    def fail(message):
        record["failures"].append(message)
        print("FAIL", message, flush=True)

    def footprint_state(reference):
        for footprint in api._get_board().get_footprints():
            if footprint.reference_field and footprint.reference_field.text.value == reference:
                return {
                    "reference": reference,
                    "id": str(footprint.id.value),
                    "description": footprint.description_field.text.value or "",
                    "visible": bool(footprint.description_field.visible),
                    "x": footprint.position.x / 1_000_000,
                    "y": footprint.position.y / 1_000_000,
                    "rotation": footprint.orientation.degrees,
                    "footprint": str(footprint.definition.id),
                }
        return None

    def counts():
        board = api._get_board()
        return {
            "footprints": len(list(board.get_footprints())),
            "zones": len(list(board.get_zones())),
            "groups": len(list(board.get_groups())),
            "tracks": len(list(board.get_tracks())),
            "nets": len(list(board.get_nets())),
        }

    def cleanup():
        if open_paths() != [str(ALLOWED)]:
            step("cleanup", {"skipped": True, "openPaths": open_paths()})
            return
        removed_zones = []
        if baseline_zone_ids is not None:
            extras = [
                zone
                for zone in api._get_board().get_zones()
                if str(zone.id.value) not in baseline_zone_ids
            ]
            if extras:
                board = api._get_board()
                commit = board.begin_commit()
                try:
                    board.remove_items(extras)
                    board.push_commit(commit, "Remove phase 5 temporary zones")
                    removed_zones = [str(zone.id.value) for zone in extras]
                except Exception:
                    board.drop_commit(commit)
        deleted = []
        for reference in created_refs:
            if footprint_state(reference) is not None:
                deleted.append(
                    {
                        "reference": reference,
                        "response": interface.handle_command(
                            "delete_component", {"reference": reference}
                        ),
                    }
                )
        step("cleanup", {"deleted": deleted, "removedZones": removed_zones, "counts": counts()})

    try:
        paths = require_allowed()
        before_files = {"phase3": file_stamp(ALLOWED), "original": file_stamp(ORIGINAL)}
        place = footprint_state("R_PLACE")
        if place is None:
            raise RuntimeError("R_PLACE is not on the disposable board")
        baseline = counts()
        baseline_zone_ids = {str(zone.id.value) for zone in api._get_board().get_zones()}
        nets = sorted(net.name for net in api._get_board().get_nets() if net.name)
        chosen = "GND" if "GND" in nets else nets[0]
        step(
            "baseline",
            {
                "openPaths": paths,
                "counts": baseline,
                "net": chosen,
                "rPlace": place,
                "files": before_files,
            },
        )

        unsupported = {}
        for command, params in (
            ("add_wire", {"start": {"x": 0, "y": 0}, "end": {"x": 1, "y": 0}}),
            ("add_net_class", {"name": "PHASE5", "clearance": 0.2, "trackWidth": 0.25, "viaDiameter": 0.6, "viaDrill": 0.3}),
            ("assign_net_to_class", {"net": chosen, "netClass": "PHASE5"}),
            ("check_clearance", {"item1": {"type": "track"}, "item2": {"type": "pad"}}),
            ("replace_component", {"reference": "R_PLACE", "newComponentId": "R"}),
            ("set_layer_constraints", {"layer": "F.Cu", "minTrackWidth": 0.2}),
        ):
            require_allowed()
            unsupported[command] = interface.handle_command(command, params)
        after_unsupported = counts()
        step("unsupported", {"responses": unsupported, "counts": after_unsupported})
        for command, response in unsupported.items():
            if response.get("success") is not False or response.get("error") != "UNSUPPORTED_OPERATION":
                fail(f"{command} did not return UNSUPPORTED_OPERATION: {response}")
        if after_unsupported != baseline or footprint_state("R_PLACE") != place:
            fail("An unsupported command changed the board")

        require_allowed()
        missing_zone = interface.handle_command(
            "add_zone",
            {
                "layer": "F.Cu",
                "net": "PHASE5_MISSING_NET",
                "unit": "mm",
                "points": [{"x": 530, "y": 530}, {"x": 531, "y": 530}, {"x": 531, "y": 531}],
            },
        )
        step("zone_missing_net", {"response": missing_zone, "counts": counts()})
        if missing_zone.get("error") != "NET_NOT_FOUND" or counts() != baseline:
            fail("A missing zone net changed the board")

        require_allowed()
        zone = interface.handle_command(
            "add_zone",
            {
                "layer": "F.Cu",
                "net": chosen,
                "unit": "mm",
                "padConnection": "thermal",
                "clearance": 0.2,
                "points": [
                    {"x": 540, "y": 540},
                    {"x": 541, "y": 540},
                    {"x": 541, "y": 541},
                    {"x": 540, "y": 541},
                ],
            },
        )
        zone_ids = {str(item.id.value) for item in api._get_board().get_zones()}
        step("add_zone", {"response": zone, "zoneCount": len(zone_ids)})
        if zone.get("success") is not True or zone.get("net") != chosen or zone.get("id") not in zone_ids:
            fail(f"Zone was not verified on the board: {zone}")
        else:
            undo = api._kicad.run_action("common.Interactive.undo")
            remaining = {str(item.id.value) for item in api._get_board().get_zones()}
            step(
                "zone_undo",
                {
                    "undo": str(getattr(undo, "status", undo)),
                    "present": zone["id"] in remaining,
                    "zoneCount": len(remaining),
                },
            )
            if zone["id"] in remaining or len(remaining) != baseline["zones"]:
                fail("Undo did not remove the temporary zone")

        require_allowed()
        for reference, position in (("R_P5A", (470, 450)), ("R_P5B", (490, 450))):
            if footprint_state(reference) is not None:
                raise RuntimeError(f"{reference} already exists")
            cloned = interface.handle_command(
                "clone_component",
                {
                    "sourceReference": "R_PLACE",
                    "newReference": reference,
                    "position": {"x": position[0], "y": position[1], "unit": "mm"},
                    "rotation": 0,
                    "copyNets": False,
                },
            )
            created_refs.append(reference)
            step(f"clone_{reference}", {"response": cloned, "state": footprint_state(reference)})
            if cloned.get("success") is not True:
                fail(f"Could not create {reference}")

        if footprint_state("R_PLACE") != place:
            fail("Cloning changed R_PLACE")

        require_allowed()
        before_note = footprint_state("R_P5A")
        noted = interface.handle_command(
            "add_component_annotation",
            {"reference": "R_P5A", "annotation": "PHASE5 NOTE", "visible": True},
        )
        after_note = footprint_state("R_P5A")
        step("annotate", {"response": noted, "before": before_note, "after": after_note})
        if (
            noted.get("success") is not True
            or after_note is None
            or before_note is None
            or "PHASE5 NOTE" not in after_note["description"]
            or after_note["id"] != before_note["id"]
            or after_note["visible"] is not True
            or footprint_state("R_PLACE") != place
        ):
            fail("Annotation was not verified on the disposable clone")
        else:
            undo = api._kicad.run_action("common.Interactive.undo")
            restored = footprint_state("R_P5A")
            step(
                "annotation_undo",
                {
                    "undo": str(getattr(undo, "status", undo)),
                    "description": None if restored is None else restored["description"],
                },
            )
            if restored is None or restored["description"] != before_note["description"] or restored["id"] != before_note["id"]:
                fail("Undo did not restore the clone description")

        require_allowed()
        grouped = interface.handle_command(
            "group_components",
            {"references": ["R_P5A", "R_P5B"], "groupName": "PHASE5_GROUP"},
        )
        groups = []
        for group in api._get_board().get_groups():
            if group.name == "PHASE5_GROUP":
                groups.append(
                    {
                        "id": str(group.id.value),
                        "name": group.name,
                        "members": [str(getattr(item.id, "value", "")) for item in group.items],
                    }
                )
        step("group", {"response": grouped, "groups": groups, "rPlace": footprint_state("R_PLACE")})
        member_ok = False
        if grouped.get("success") is True and len(groups) == 1:
            expected = {footprint_state("R_P5A")["id"], footprint_state("R_P5B")["id"]}
            member_ok = set(groups[0]["members"]) == expected and place["id"] not in groups[0]["members"]
        if not member_ok or footprint_state("R_PLACE") != place:
            fail("Group membership was not verified")
        else:
            undo = api._kicad.run_action("common.Interactive.undo")
            remaining_groups = [group.name for group in api._get_board().get_groups() if group.name == "PHASE5_GROUP"]
            still_there = footprint_state("R_P5A") is not None and footprint_state("R_P5B") is not None
            step(
                "group_undo",
                {
                    "undo": str(getattr(undo, "status", undo)),
                    "groupRemains": remaining_groups,
                    "clonesRemain": still_there,
                },
            )
            if remaining_groups or not still_there:
                fail("Undo did not remove only the temporary group")

        cleanup()
        created_refs = []
        with tempfile.TemporaryDirectory(prefix="kicad-mcp-phase5-") as temporary:
            temporary = Path(temporary)
            positions = interface.handle_command(
                "export_position_file",
                {
                    "outputPath": str(temporary / "positions.csv"),
                    "format": "CSV",
                    "units": "mm",
                    "side": "top",
                },
            )
            position_text = (temporary / "positions.csv").read_text(encoding="utf-8") if positions.get("success") else ""
            vrml = interface.handle_command(
                "export_vrml",
                {"outputPath": str(temporary / "board.wrl"), "includeComponents": True, "useRelativePaths": False},
            )
            vrml_head = ""
            vrml_path = temporary / "board.wrl"
            if vrml.get("success") and vrml_path.is_file():
                vrml_head = vrml_path.read_text(encoding="utf-8", errors="ignore")[:40]
            netlist = interface.handle_command(
                "export_netlist",
                {"outputPath": str(temporary / "board.net"), "format": "KiCad"},
            )
            step(
                "exports",
                {
                    "position": positions,
                    "positionHasRPlace": "R_PLACE" in position_text and "230.000000" in position_text,
                    "positionHasClone": "R_P5A" in position_text,
                    "vrml": {key: vrml.get(key) for key in ("success", "error", "message", "source", "_backend")},
                    "vrmlHeader": vrml_head,
                    "netlist": netlist,
                },
            )
        if not positions.get("success") or "R_PLACE" not in position_text or "R_P5A" in position_text:
            fail("Position export did not match the live board")
        if not vrml.get("success") or "#VRML" not in vrml_head:
            fail(f"VRML export was not verified: {vrml}")
        if netlist.get("success") is not False or netlist.get("error") != "NOT_FOUND":
            fail(f"Netlist export did not refuse the missing schematic: {netlist}")

        final_place = footprint_state("R_PLACE")
        final_counts = counts()
        after_files = {"phase3": file_stamp(ALLOWED), "original": file_stamp(ORIGINAL)}
        step(
            "final",
            {
                "counts": final_counts,
                "countsMatch": final_counts == baseline,
                "rPlaceUnchanged": final_place == place,
                "blockedSwig": blocked,
                "openPaths": open_paths(),
                "filesUnchanged": after_files == before_files,
                "files": after_files,
            },
        )
        if final_counts != baseline or final_place != place:
            fail("The disposable board was not restored")
        if after_files != before_files or blocked["save"] or blocked["load"]:
            fail("A PCB file was written or loaded through SWIG")
        if open_paths() != [str(ALLOWED)]:
            fail("The open PCB path changed")
    except Exception as exc:
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
        traceback.print_exc()
        try:
            cleanup()
        except Exception:
            traceback.print_exc()
    finally:
        OUT.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")

    if record["error"] or record["failures"]:
        print("LIVE FAILED", record["failures"], record["error"], flush=True)
        return 1
    print("LIVE PASSED", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
