# Phase 3 live IPC results

Date: 2026-11-01.

KiCad was not running at the start. `KiCad()` returned `Connection refused`, and `%TEMP%\kicad\api.sock` did not exist. PCB Editor was then started on this file only:

`C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\ipc-phase3-test.kicad_pcb`

The IPC API reported version `10.0.6 (10.0.6-0-gcaf7377e9c)`. The only open PCB document, joined from `project.path` and `board_filename`, was that same full path. `ipc-move-test.kicad_pcb` was not opened.

Commands went through `KiCADInterface.handle_command` with `KICAD_BACKEND=ipc`. `pcbnew.SaveBoard` and `pcbnew.LoadBoard` were replaced with functions that raise, so a SWIG load or save would have failed the run. Neither was called. The board was not saved.

The raw record is `audit/phase3_live_output.json`.

## Baseline

`get_board_info` returned success, `_backend: ipc`, `_realtime: true`:

- Edge.Cuts box: 150.05 mm by 110.05 mm
- 73 footprints
- 545 tracks
- 24 vias
- 50 nets

`get_component_list` returned 73 footprints, `_backend: ipc`, `_realtime: true`. `R_PLACE` was present at 230 mm, 170 mm, value `10k`, footprint `Resistors SMD:RESC2012X60N`, UUID `9e910bf0-f26e-4922-aff9-97b23a798d21`. Graphic shape count was 914.

## Tests

| Step | Input | Observed result | PCB change |
|---|---|---|---|
| IPC unavailable | `delete_trace` with `traceUuid` `phase3-not-a-track`, board API detached for that call only | `success: false`, `error: IPC_UNAVAILABLE`, `_backend: unavailable`, `_realtime: false`. Log: `SWIG was not called.` | Track count stayed 545 |
| Add one trace | `route_trace` from (500, 500) mm to (501.25, 500) mm, `F.Cu`, width 0.2, net `PHASE3_TEMP_NET` | `success: true`, `_backend: ipc`, `_realtime: true` | Exactly one new track, UUID `7d0e8b06-4fc1-43f5-b4e2-17261d151a01`, endpoints unchanged. Its net name on the board was empty. |
| Delete that trace | `delete_trace` with that UUID | `success: true`, `deletedCount: 1`, `_backend: ipc`, `_realtime: true` | That UUID was gone. Track count returned to 545. No pre-existing track UUID was missing. |
| Undo, then redo | KiCad actions `common.Interactive.undo` and `common.Interactive.redo` | Both returned `RAS_OK` | Undo restored that UUID. Redo removed it again. Count was 545 after redo. |
| Add outline | `add_board_outline` rectangle, x 520, y 520, width 1.2, height 0.8, unit mm | `success: true`, one id `bd59055d-c9a3-40ee-8e77-9b090f18dbed`, `_backend: ipc`, `_realtime: true` | Shape count 914 to 915. The new id was the only addition. |
| Undo outline | `common.Interactive.undo` | `RAS_OK` | That shape id was gone. Shape count returned to 914. |

Successful IPC replies in this run were the ones that changed the editor, and each of those had `_backend: ipc` and `_realtime: true`. The unavailable call did not.

## File hash

SHA-256 before and after, for both files:

`04514a3e851369cee2364171711f0496c63ad3a89a1507cecd9fdbbc1146bbd8`

Size stayed 1,756,123 bytes. The modification time stayed `1793520690.2737627`. The disposable file and `ipc-move-test.kicad_pcb` were not written.

## Fixes

No Phase 2 code was changed. The live run did not show a SaveBoard fallback, a SWIG delete, or a SWIG outline.

Two unrelated observations, left unchanged:

- `route_trace` reported net `PHASE3_TEMP_NET`, but the created track's net name was empty. That net is not on the board, and `add_track` only assigns a net when `get_nets()` already contains it.
- `get_tracks` returns `id` as the protobuf text `value: "<uuid>"`, not the bare UUID. `delete_trace` matched the bare UUID from `id.value`.

## Next phase

1. `add_net`: return failure, or an explicit unsupported error, unless a net with that name is readable afterward. Do not report success for a net that was not created.
2. `rotate_component`: set the absolute angle described by the TypeScript tool, then repeat the check on `ipc-phase3-test.kicad_pcb` only.
3. The twelve unrouted tools: connect the name mismatches first (`add_wire` to `add_schematic_wire`, `add_zone` to `add_copper_pour`, `add_net_class` to `create_netclass`, `export_netlist` to `generate_netlist`). Implement or remove the rest only after those names are settled.
4. While touching routing, return bare UUIDs from `get_tracks` and make `route_trace` report the net that was actually stored.
