# Phase 4 live IPC results

Date: 2026-11-01.

Editor: KiCad 10.0.6 (`10.0.6-0-gcaf7377e9c`), kicad-python 0.8.0. pcbnew was already open on the disposable board. The resolved open path was `C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\ipc-phase3-test.kicad_pcb` before every mutation. `ipc-move-test.kicad_pcb` was not opened.

The run is `audit/phase4_live_check.py`. Its machine record is `audit/phase4_live_output.json`. `failures` is empty and `error` is null.

## Root causes

`kipy.board.Board` in kicad-python 0.8.0 exposes `get_nets`. The board command set has `GetNets` and `GetNetClassForNets`. It has no create-net command, and `Board.create_net` is absent. `_ipc_add_net` still returned `success: true` and said the net would appear later.

`add_track` looked up a requested net and, when the name was missing, created the track anyway. `_ipc_route_trace` then returned success with the requested name. Phase 3 showed that for `PHASE3_TEMP_NET`: the stored net was an empty string.

`get_tracks`, `get_vias`, `get_zones`, and `get_selection` used `str(item.id)`. That string is the protobuf text `value: "<uuid>"`, while `id.value` is the bare UUID. `delete_trace` already matched `id.value`.

`rotate_component` in `src/tools/component.ts` describes `angle` as absolute. `_ipc_rotate_component` computed `(current + angle) % 360` and did not read the footprint back.

## Fixes

`add_net` reads the board net list first. An existing name returns `ALREADY_EXISTS` and does not modify that net. A new name returns `UNSUPPORTED_OPERATION`. Neither path opens a commit or calls SWIG.

`route_trace` rejects a blank net. A named net that is not already on the board returns `NET_NOT_FOUND` before `begin_commit`. When the net exists, the track is created in one IPC commit, then read back. Success requires the stored net name to match. A mismatch drops the commit when KiCad reports it before push, or removes the committed track and returns `success: false`.

Track, via, zone, and selection ids now use `id.value`.

`rotate_component` sets the requested angle modulo 360. It then reads the same reference back. Success requires the same footprint id, the same footprint name, and an orientation within 0.05 degrees of the request. A mismatch restores the previous angle and returns `ROTATION_MISMATCH`.

## Automated tests

`python python/tests/test_phase4.py` on KiCad Python: 16 passed, 0 failed. The tests stub `pcbnew` and do not open the editor. They cover unsupported and existing `add_net`, a missing net that opens no commit, a verified net, removal after a net mismatch, commit drop on create failure, rejection of a success payload whose net is empty, bare UUIDs, and absolute rotation including 0 degrees from a current angle of 90.

`python python/tests/test_phase_safety.py`: 29 passed, 0 failed. `py_compile` succeeded for the changed Python files. No TypeScript schema changed, so the TypeScript build was not required.

## Live IPC results

Baseline: 73 footprints, 545 tracks, 50 nets. `R_PLACE` remained `9e910bf0-f26e-4922-aff9-97b23a798d21`, `Resistors SMD:RESC2012X60N`, value `10k`, rotation 0, `F.Cu`, at (230, 170) mm. Existing via ids from `get_vias` matched `id.value`; the sample was `0bbd31f7-f6bb-49fe-820d-40816261e910`.

| Check | Board evidence |
|---|---|
| `add_net` `PHASE4_NEW_NET` | `success: false`, `UNSUPPORTED_OPERATION`, `_realtime: false`. Net count stayed 50. |
| `add_net` `+5V_ISO` | `ALREADY_EXISTS`. Identifier is the name `+5V_ISO`. The proto still returned code 13. The net list was unchanged. |
| `route_trace` on `PHASE4_MISSING_NET` | `NET_NOT_FOUND`. No track id was added. |
| `route_trace` on `+5V_ISO` | Track `aa6cbda3-6973-48bf-874f-ce402892dd7f` from (500, 512) to (501.4, 512) mm. Raw `net.name` was `+5V_ISO`. `get_tracks` returned that bare id. |
| Undo and redo of that track | Undo restored 545 tracks. Redo restored the same id on `+5V_ISO`. `delete_trace` then removed only that id. |
| Rotation | Cloned `R_PLACE` as `R_PHASE4` (`0ddadca0-afdc-4f8e-a38c-3b8f719245f7`) at (480, 460), rotation 0, `copyNets: false`. Absolute requests 90, 180, and 0 read back as those angles. Undo restored 180. Redo restored 0. The clone id and footprint did not change. `R_PLACE` did not change. |
| Cleanup | `R_PHASE4` was deleted. Component count returned to 73. Track count returned to 545. No extra track id remained. |

`pcbnew.SaveBoard` and `pcbnew.LoadBoard` were replaced with counters that raise. Both counters stayed 0. The open path stayed the disposable board. Both PCB files stayed size 1756123, mtime 1793520690.2737627, and SHA-256 `04514a3e851369cee2364171711f0496c63ad3a89a1507cecd9fdbbc1146bbd8`.

Zones and selection were covered by the automated UUID test. The live board was not used to change a zone or the selection.

## Response changes

The Zod tool schemas were not edited.

`add_net` no longer returns success for a net that was not created. Errors are `INVALID_ARGUMENT`, `ALREADY_EXISTS`, and `UNSUPPORTED_OPERATION`. An existing net includes `name`, `identifier` (the same name), and `code` when the current proto still has one. KiCad 10 deprecates net codes; the stable identifier is the name.

`route_trace` success includes `id` and `trace.net` from the track read back after the commit. Failures use `INVALID_ARGUMENT`, `NET_NOT_FOUND`, `NET_MISMATCH`, or `IPC_ERROR`. A failed named-net request does not leave the new track.

`rotate_component` still takes `reference` and absolute `angle`. The response now includes `reference`, `id`, `footprint`, `requestedRotation`, and `newRotation` from the read-back. A missing angle is `INVALID_ARGUMENT` instead of an implied relative 90-degree turn.

`get_tracks`, `get_vias`, `get_zones`, and `get_selection` return bare UUID strings.

## Still unsupported

Creating a board net through KiCad 10 IPC. `route_trace` cannot invent a missing net; the caller has to use a net that is already on the board.

The twelve unrouted tools remain unconnected: `add_component_annotation`, `add_net_class`, `add_wire`, `add_zone`, `assign_net_to_class`, `check_clearance`, `export_netlist`, `export_position_file`, `export_vrml`, `group_components`, `replace_component`, and `set_layer_constraints`.

Library footprints that are not already on the board, and flipping a footprint to the other copper side, remain unsupported on this KiCad build.
