"""Live Phase 4 check. Mutates only the disposable IPC board, and never saves it."""

import hashlib
import json
import os
import sys
import traceback
from pathlib import Path

os.environ["KICAD_BACKEND"] = "ipc"
os.environ["KICAD_AUTO_LAUNCH"] = "false"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

ALLOWED = Path(r"C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\ipc-phase3-test.kicad_pcb").resolve()
ORIGINAL = Path(r"C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\ipc-move-test.kicad_pcb").resolve()
OUT = Path(__file__).resolve().parent / "phase4_live_output.json"
CLONE_REF = "R_PHASE4"
MISSING_NET = "PHASE4_MISSING_NET"
NEW_NET = "PHASE4_NEW_NET"


def file_stamp(path: Path) -> dict:
    data = path.read_bytes()
    stat = path.stat()
    return {
        "path": str(path),
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def close_angle(actual, expected) -> bool:
    if not isinstance(actual, (int, float)) or isinstance(actual, bool):
        return False
    delta = (float(actual) - float(expected)) % 360.0
    if delta > 180.0:
        delta = 360.0 - delta
    return delta <= 0.1


def main() -> int:
    import pcbnew
    from kicad_interface import KiCADInterface

    blocked = {"save": 0, "load": 0}

    def refuse_save(*_args, **_kwargs):
        blocked["save"] += 1
        raise RuntimeError("Phase 4 blocked a SWIG board save")

    def refuse_load(*_args, **_kwargs):
        blocked["load"] += 1
        raise RuntimeError("Phase 4 blocked a SWIG board load")

    pcbnew.SaveBoard = refuse_save
    pcbnew.LoadBoard = refuse_load

    record = {"steps": [], "failures": [], "error": None}
    interface = KiCADInterface()
    api = interface.ipc_board_api
    created_clone = False
    baseline_tracks = None

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

    def track_values():
        return {
            str(getattr(track.id, "value", ""))
            for track in api._get_board().get_tracks()
        }

    def component_map():
        listed = interface.handle_command("get_component_list", {})
        return {
            item.get("reference"): item
            for item in listed.get("components", [])
        }, listed

    def snapshot(component):
        if not component:
            return None
        position = component.get("position") or {}
        return {
            "reference": component.get("reference"),
            "id": component.get("id"),
            "footprint": component.get("footprint"),
            "value": component.get("value"),
            "rotation": component.get("rotation"),
            "layer": component.get("layer"),
            "x": position.get("x"),
            "y": position.get("y"),
        }

    def cleanup():
        if baseline_tracks is None or open_paths() != [str(ALLOWED)]:
            step(
                "cleanup",
                {
                    "skipped": True,
                    "baselineReady": baseline_tracks is not None,
                    "openPaths": open_paths(),
                },
            )
            return
        removed = []
        current = track_values()
        for ident in sorted(current - baseline_tracks):
            result = interface.handle_command("delete_trace", {"traceUuid": ident})
            removed.append({"id": ident, "response": result})
        deleted_clone = None
        parts, _listed = component_map()
        if created_clone and CLONE_REF in parts:
            deleted_clone = interface.handle_command(
                "delete_component", {"reference": CLONE_REF}
            )
        step(
            "cleanup",
            {
                "removedTracks": removed,
                "deletedClone": deleted_clone,
                "trackCount": len(track_values()),
                "componentCount": len(component_map()[0]),
            },
        )

    try:
        paths = require_allowed()
        before_files = {"phase3": file_stamp(ALLOWED), "original": file_stamp(ORIGINAL)}
        step("ipc_connected", {"openPaths": paths, "apiVersion": str(api._kicad.get_api_version())})

        info = interface.handle_command("get_board_info", {})
        parts, listed = component_map()
        place = snapshot(parts.get("R_PLACE"))
        if place is None:
            raise RuntimeError("R_PLACE is not on the disposable board")
        if CLONE_REF in parts:
            raise RuntimeError("R_PHASE4 already exists; rotation test was not started")
        baseline_tracks = track_values()
        baseline_nets = sorted(net.name for net in api._get_board().get_nets())
        raw_vias = list(api._get_board().get_vias())
        reported_vias = api.get_vias()
        step(
            "baseline",
            {
                "componentCount": listed.get("count"),
                "trackCount": info.get("trackCount", len(baseline_tracks)),
                "rawTrackCount": len(baseline_tracks),
                "netCount": len(baseline_nets),
                "viaIdsBare": [item.get("id") for item in reported_vias] == [
                    str(getattr(via.id, "value", "")) for via in raw_vias
                ],
                "viaIdSample": reported_vias[0]["id"] if reported_vias else None,
                "rPlace": place,
                "files": before_files,
            },
        )
        if not reported_vias or "value:" in reported_vias[0]["id"] or "\n" in reported_vias[0]["id"]:
            fail("Existing via id is not a bare UUID")

        chosen = "GND" if "GND" in baseline_nets else next(
            (name for name in baseline_nets if name), None
        )
        if chosen is None:
            raise RuntimeError("The disposable board has no named net")
        if MISSING_NET in baseline_nets or NEW_NET in baseline_nets:
            raise RuntimeError("Temporary net name already exists")

        require_allowed()
        added = interface.handle_command("add_net", {"name": NEW_NET})
        nets_after_add = sorted(net.name for net in api._get_board().get_nets())
        step("add_net_new", {"response": added, "netCount": len(nets_after_add)})
        if added.get("success") is not False or added.get("error") != "UNSUPPORTED_OPERATION":
            fail(f"add_net reported a creatable net: {added}")
        if nets_after_add != baseline_nets:
            fail("add_net changed the board net list")

        existing = interface.handle_command("add_net", {"name": chosen})
        nets_after_existing = sorted(net.name for net in api._get_board().get_nets())
        step("add_net_existing", {"net": chosen, "response": existing})
        if existing.get("success") is not False or existing.get("error") != "ALREADY_EXISTS":
            fail(f"existing add_net response: {existing}")
        if existing.get("net", {}).get("name") != chosen:
            fail("existing add_net did not echo the actual net name")
        if nets_after_existing != baseline_nets:
            fail("add_net modified an existing net list")

        require_allowed()
        missing = interface.handle_command(
            "route_trace",
            {
                "start": {"x": 500.0, "y": 506.0, "unit": "mm"},
                "end": {"x": 501.2, "y": 506.0, "unit": "mm"},
                "layer": "F.Cu",
                "width": 0.2,
                "net": MISSING_NET,
            },
        )
        tracks_after_missing = track_values()
        step(
            "route_missing_net",
            {
                "response": missing,
                "newTracks": sorted(tracks_after_missing - baseline_tracks),
            },
        )
        if missing.get("success") is not False or missing.get("error") != "NET_NOT_FOUND":
            fail(f"missing-net route response: {missing}")
        if tracks_after_missing != baseline_tracks:
            fail("A missing net still created a track")

        require_allowed()
        routed = interface.handle_command(
            "route_trace",
            {
                "start": {"x": 500.0, "y": 512.0, "unit": "mm"},
                "end": {"x": 501.4, "y": 512.0, "unit": "mm"},
                "layer": "F.Cu",
                "width": 0.2,
                "net": chosen,
            },
        )
        raw_new = []
        for track in api._get_board().get_tracks():
            ident = str(getattr(track.id, "value", ""))
            if ident in baseline_tracks:
                continue
            raw_new.append(
                {
                    "id": ident,
                    "text": str(track.id),
                    "net": track.net.name if track.net else "",
                    "start": (track.start.x / 1_000_000, track.start.y / 1_000_000),
                    "end": (track.end.x / 1_000_000, track.end.y / 1_000_000),
                }
            )
        reported_new = [
            item
            for item in api.get_tracks()
            if item.get("id") not in baseline_tracks
        ]
        step(
            "route_existing_net",
            {"response": routed, "raw": raw_new, "reported": reported_new},
        )
        if len(raw_new) != 1:
            fail(f"Expected one new track, found {len(raw_new)}")
        else:
            created = raw_new[0]
            if created["net"] != chosen or routed.get("success") is not True:
                fail(f"Track net verification failed: raw={created} response={routed}")
            if routed.get("trace", {}).get("net") != chosen or routed.get("id") != created["id"]:
                fail("route_trace response does not match the board track")
            if reported_new[0].get("id") != created["id"] or "value:" in reported_new[0].get("id", ""):
                fail(f"get_tracks id is not the bare UUID: {reported_new[0].get('id')}")
            if routed.get("_backend") != "ipc" or routed.get("_realtime") is not True:
                fail("Successful route was not labeled as realtime IPC")

            kicad = api._kicad
            undo = kicad.run_action("common.Interactive.undo")
            after_undo = track_values()
            restored = created["id"] not in after_undo and after_undo == baseline_tracks
            redo = None
            after_redo = None
            if restored:
                redo = kicad.run_action("common.Interactive.redo")
                after_redo = track_values()
                redone = [
                    {
                        "id": str(getattr(track.id, "value", "")),
                        "net": track.net.name if track.net else "",
                    }
                    for track in api._get_board().get_tracks()
                    if str(getattr(track.id, "value", "")) not in baseline_tracks
                ]
            else:
                redone = []
            step(
                "trace_undo_redo",
                {
                    "undo": str(getattr(undo, "status", undo)),
                    "restoredBaseline": restored,
                    "redo": None if redo is None else str(getattr(redo, "status", redo)),
                    "redone": redone,
                },
            )
            if not restored:
                fail("Undo did not remove the temporary track")
            elif len(redone) != 1 or redone[0]["id"] != created["id"] or redone[0]["net"] != chosen:
                fail(f"Redo did not restore the same net assignment: {redone}")
            else:
                deleted = interface.handle_command(
                    "delete_trace", {"traceUuid": created["id"]}
                )
                remaining = track_values()
                step(
                    "delete_verified_trace",
                    {
                        "response": deleted,
                        "present": created["id"] in remaining,
                        "trackCount": len(remaining),
                    },
                )
                if created["id"] in remaining or remaining != baseline_tracks:
                    fail("Deleting the temporary track left a track behind")

        require_allowed()
        if track_values() != baseline_tracks:
            fail("Track baseline was not restored before rotation")
        cloned = interface.handle_command(
            "clone_component",
            {
                "sourceReference": "R_PLACE",
                "newReference": CLONE_REF,
                "position": {"x": 480.0, "y": 460.0, "unit": "mm"},
                "rotation": 0,
                "copyNets": False,
            },
        )
        created_clone = True
        parts, _listed = component_map()
        clone = snapshot(parts.get(CLONE_REF))
        place_after_clone = snapshot(parts.get("R_PLACE"))
        step("clone", {"response": cloned, "clone": clone, "rPlace": place_after_clone})
        if cloned.get("success") is not True or clone is None:
            fail(f"Disposable clone was not created: {cloned}")
            created_clone = CLONE_REF in parts
        elif clone["id"] == place["id"] or clone["footprint"] != place["footprint"]:
            fail(f"Clone identity is wrong: {clone}")
        elif place_after_clone != place:
            fail(f"Cloning changed R_PLACE: {place_after_clone}")
        elif not close_angle(clone["rotation"], 0):
            fail(f"Clone rotation is not 0: {clone['rotation']}")
        else:
            observed = []
            for angle in (90, 180, 0):
                require_allowed()
                rotated = interface.handle_command(
                    "rotate_component", {"reference": CLONE_REF, "angle": angle}
                )
                parts, _listed = component_map()
                current = snapshot(parts.get(CLONE_REF))
                place_now = snapshot(parts.get("R_PLACE"))
                observed.append(
                    {
                        "requested": angle,
                        "response": rotated,
                        "actual": None if current is None else current["rotation"],
                        "id": None if current is None else current["id"],
                    }
                )
                if (
                    rotated.get("success") is not True
                    or current is None
                    or not close_angle(current["rotation"], angle)
                    or current["id"] != clone["id"]
                    or current["footprint"] != clone["footprint"]
                    or current["reference"] != CLONE_REF
                    or place_now != place
                ):
                    fail(f"Absolute rotation {angle} failed: {observed[-1]} rPlace={place_now}")
                    break
            else:
                kicad = api._kicad
                undo = kicad.run_action("common.Interactive.undo")
                parts, _listed = component_map()
                undone = snapshot(parts.get(CLONE_REF))
                redo = kicad.run_action("common.Interactive.redo")
                parts, _listed = component_map()
                redone = snapshot(parts.get(CLONE_REF))
                step(
                    "rotate_undo_redo",
                    {
                        "angles": observed,
                        "undo": str(getattr(undo, "status", undo)),
                        "afterUndo": None if undone is None else undone["rotation"],
                        "redo": str(getattr(redo, "status", redo)),
                        "afterRedo": None if redone is None else redone["rotation"],
                        "sameId": None if redone is None else redone["id"] == clone["id"],
                    },
                )
                if undone is None or not close_angle(undone["rotation"], 180):
                    fail(f"Undo did not restore 180 degrees: {undone}")
                if (
                    redone is None
                    or not close_angle(redone["rotation"], 0)
                    or redone["id"] != clone["id"]
                    or snapshot(parts.get("R_PLACE")) != place
                ):
                    fail(f"Redo did not restore the clone at 0 degrees: {redone}")

        cleanup()
        created_clone = False
        final_parts, final_listed = component_map()
        final_place = snapshot(final_parts.get("R_PLACE"))
        final_tracks = track_values()
        final_nets = sorted(net.name for net in api._get_board().get_nets())
        after_files = {"phase3": file_stamp(ALLOWED), "original": file_stamp(ORIGINAL)}
        step(
            "final",
            {
                "componentCount": final_listed.get("count"),
                "cloneRemains": CLONE_REF in final_parts,
                "rPlaceUnchanged": final_place == place,
                "tracksMatch": final_tracks == baseline_tracks,
                "netsMatch": final_nets == baseline_nets,
                "extraTracks": sorted(final_tracks - baseline_tracks),
                "blockedSwig": blocked,
                "openPaths": open_paths(),
                "files": after_files,
                "filesUnchanged": after_files == before_files,
            },
        )
        if CLONE_REF in final_parts:
            fail("Temporary clone remains on the board")
        if final_place != place:
            fail("R_PLACE changed")
        if final_tracks != baseline_tracks or final_nets != baseline_nets:
            fail("Temporary geometry or nets remain")
        if after_files != before_files:
            fail("A PCB file changed on disk")
        if blocked["save"] or blocked["load"]:
            fail("SWIG SaveBoard or LoadBoard was called")
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
