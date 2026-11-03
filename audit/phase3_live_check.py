"""Live Phase 3 check. Mutates only the disposable IPC board, and never saves it."""

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
OUT = Path(__file__).resolve().parent / "phase3_live_output.json"

TRACE = {
    "start": {"x": 500.0, "y": 500.0, "unit": "mm"},
    "end": {"x": 501.25, "y": 500.0, "unit": "mm"},
    "layer": "F.Cu",
    "width": 0.2,
    "net": "PHASE3_TEMP_NET",
}
OUTLINE = {
    "shape": "rectangle",
    "width": 1.2,
    "height": 0.8,
    "x": 520.0,
    "y": 520.0,
    "unit": "mm",
}


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

    def refuse_file_io(*_args, **_kwargs):
        raise RuntimeError("Phase 3 blocked a SWIG board load or save")

    pcbnew.SaveBoard = refuse_file_io
    pcbnew.LoadBoard = refuse_file_io

    record = {"steps": [], "error": None}
    interface = KiCADInterface()

    def open_paths():
        return [str(Path(path).resolve()) for path in interface.ipc_board_api._open_pcb_paths()]

    def require_allowed():
        paths = open_paths()
        if paths != [str(ALLOWED)]:
            raise RuntimeError(f"Open PCB is not the disposable board: {paths}")
        return paths

    def step(name, payload):
        record["steps"].append({"name": name, "result": payload})
        print(name, json.dumps(payload, default=str)[:500])

    try:
        paths = require_allowed()
        step("ipc_connected", {"openPaths": paths, "useIpc": interface.use_ipc})

        info = interface.handle_command("get_board_info", {})
        components = interface.handle_command("get_component_list", {})
        refs = [item.get("reference") for item in components.get("components", [])]
        step(
            "baseline",
            {
                "boardInfo": info,
                "componentCount": components.get("count"),
                "hasRPlace": "R_PLACE" in refs,
                "backend": components.get("_backend"),
                "realtime": components.get("_realtime"),
            },
        )
        before_tracks = interface.ipc_board_api.get_tracks()
        before_raw = interface.ipc_board_api._get_board().get_tracks()
        before_values = {str(getattr(track.id, "value", "")) for track in before_raw}
        before_ids = set(before_values)
        before_ids.update(item.get("id") for item in before_tracks)
        before_shapes = {
            str(getattr(getattr(shape, "id", None), "value", ""))
            for shape in interface.ipc_board_api._get_board().get_shapes()
        }
        step(
            "baseline_counts",
            {
                "tracks": len(before_tracks),
                "shapes": len(before_shapes),
                "files": {"phase3": file_stamp(ALLOWED), "original": file_stamp(ORIGINAL)},
            },
        )

        held = interface.ipc_board_api
        interface.ipc_board_api = None
        unavailable = interface.handle_command("delete_trace", {"traceUuid": "phase3-not-a-track"})
        interface.ipc_board_api = held
        after_unavailable = len(interface.ipc_board_api.get_tracks())
        step(
            "ipc_unavailable",
            {"response": unavailable, "trackCountAfter": after_unavailable, "unchanged": after_unavailable == len(before_tracks)},
        )

        require_allowed()
        created = interface.handle_command("route_trace", TRACE)
        raw_tracks = interface.ipc_board_api._get_board().get_tracks()
        detailed = []
        for track in raw_tracks:
            detailed.append(
                {
                    "value": str(getattr(track.id, "value", "")),
                    "text": str(track.id),
                    "start": (track.start.x / 1_000_000, track.start.y / 1_000_000),
                    "end": (track.end.x / 1_000_000, track.end.y / 1_000_000),
                    "net": track.net.name if track.net else "",
                }
            )
        new_tracks = [item for item in detailed if item["value"] not in before_ids and item["text"] not in before_ids]
        # Also catch ids reported as the KIID text by get_tracks.
        reported_new = [item for item in interface.ipc_board_api.get_tracks() if item.get("id") not in before_ids]
        step(
            "add_trace",
            {
                "request": TRACE,
                "response": created,
                "newRaw": new_tracks,
                "newReported": reported_new,
            },
        )
        if len(new_tracks) != 1:
            raise RuntimeError(f"Expected one new track, found {len(new_tracks)}")
        created_track = new_tracks[0]
        if abs(created_track["start"][0] - 500.0) > 0.001 or abs(created_track["end"][0] - 501.25) > 0.001:
            raise RuntimeError(f"New track geometry is not the temporary trace: {created_track}")

        require_allowed()
        deleted = interface.handle_command("delete_trace", {"traceUuid": created_track["value"]})
        remaining_values = {
            str(getattr(track.id, "value", ""))
            for track in interface.ipc_board_api._get_board().get_tracks()
        }
        missing_originals = [
            item for item in before_values if item and item not in remaining_values
        ]
        step(
            "delete_trace",
            {
                "request": {"traceUuid": created_track["value"]},
                "response": deleted,
                "createdStillPresent": created_track["value"] in remaining_values,
                "trackCount": len(remaining_values),
                "missingPreexistingSample": missing_originals[:5],
                "missingPreexistingCount": len(missing_originals),
            },
        )

        kicad = interface.ipc_board_api._kicad
        undo = kicad.run_action("common.Interactive.undo")
        after_undo = {
            str(getattr(track.id, "value", ""))
            for track in interface.ipc_board_api._get_board().get_tracks()
        }
        redo = kicad.run_action("common.Interactive.redo")
        after_redo = {
            str(getattr(track.id, "value", ""))
            for track in interface.ipc_board_api._get_board().get_tracks()
        }
        step(
            "trace_undo_redo",
            {
                "undo": str(undo),
                "restored": created_track["value"] in after_undo,
                "redo": str(redo),
                "removedAgain": created_track["value"] not in after_redo,
                "trackCount": len(after_redo),
            },
        )
        if created_track["value"] in after_redo:
            require_allowed()
            cleanup = interface.handle_command("delete_trace", {"traceUuid": created_track["value"]})
            step("trace_cleanup", {"response": cleanup})

        require_allowed()
        outline = interface.handle_command("add_board_outline", OUTLINE)
        shapes_after = interface.ipc_board_api._get_board().get_shapes()
        shape_ids = {str(getattr(getattr(shape, "id", None), "value", "")) for shape in shapes_after}
        new_shapes = sorted(shape_ids - before_shapes)
        step(
            "add_outline",
            {
                "request": OUTLINE,
                "response": outline,
                "newShapeIds": new_shapes,
                "shapeCount": len(shape_ids),
            },
        )
        undo_outline = kicad.run_action("common.Interactive.undo")
        shapes_undone = {
            str(getattr(getattr(shape, "id", None), "value", ""))
            for shape in interface.ipc_board_api._get_board().get_shapes()
        }
        step(
            "outline_undo",
            {
                "undo": str(undo_outline),
                "newShapesRemain": sorted(set(new_shapes) & shapes_undone),
                "shapeCount": len(shapes_undone),
            },
        )
        if set(new_shapes) & shapes_undone:
            require_allowed()
            board = interface.ipc_board_api._get_board()
            leftovers = [shape for shape in board.get_shapes() if str(getattr(shape.id, "value", "")) in new_shapes]
            commit = board.begin_commit()
            try:
                board.remove_items(leftovers)
                board.push_commit(commit, "Remove Phase 3 temporary outline")
            except Exception:
                board.drop_commit(commit)
                raise
            step("outline_cleanup", {"removed": [str(shape.id.value) for shape in leftovers]})

        step(
            "files_after",
            {"phase3": file_stamp(ALLOWED), "original": file_stamp(ORIGINAL), "openPaths": require_allowed()},
        )
    except Exception as exc:
        record["error"] = {"message": str(exc), "traceback": traceback.format_exc()}
        print("ERROR", exc)
    OUT.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    return 1 if record["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
