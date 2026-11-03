# KiCad MCP Server audit

Date of inspection: 2026-11-01.

Scope: static inspection of `C:\Users\mehrdad.f.mahdavi\Projects\KiCad\kicad-mcp-server`. No PCB command was sent. The disposable board was not modified. No functional source file was edited during the audit itself.

Phase 2, later the same day, changed the dispatcher and the IPC trace and outline handlers. That work is recorded in [Phase 2 status](#phase-2-status). Phase 3 then ran those paths against KiCad 10.0.6. The record is [PHASE3_RESULTS.md](PHASE3_RESULTS.md). Phase 4 corrected net reporting, track UUIDs, and absolute rotation. The record is [PHASE4_RESULTS.md](PHASE4_RESULTS.md). Phase 5 routed the twelve previously unrouted tools. The record is [PHASE5_RESULTS.md](PHASE5_RESULTS.md).

Evidence labels used below:

- **Registered**: `server.tool` exists and `src/server.ts` calls the registrar that contains it.
- **Implemented**: `python/kicad_interface.py` has a `command_routes` entry, an `IPC_CAPABLE_COMMANDS` entry, or both.
- **Statically inspected**: this audit read the source and did not execute the tool.
- **Confirmed prior session**: the operation succeeded on `ipc-move-test.kicad_pcb` before this audit. It was not repeated here.
- **Confirmed working** is used only for those prior-session operations. Source inspection alone is not treated as runtime success.

## Registration path

`KiCADMCPServer.registerAll` in `src/server.ts` passes `callKicadScript` into the project, board, component, routing, design-rule, export, schematic, library, symbol, JLCPCB, datasheet, footprint, symbol-creator, UI, and Freerouting registrars.

`registerRouterTools` is commented out. `list_tool_categories`, `get_category_tools`, `search_tools`, and `execute_tool` are defined in `src/tools/router.ts` and are not registered. `src/tools/registry.ts` is a category index only. It does not register handlers, and it does not list every live tool.

`callKicadScript` writes one JSON line, `{command, params, timeout}`, to the Python process stdin. `KiCADInterface.handle_command` checks `IPC_CAPABLE_COMMANDS` first. If IPC mode is on and the board API is connected, it returns that handler and marks `_backend: ipc`. If IPC mode is on but the board API is missing, Phase 2 returns `IPC_UNAVAILABLE` and does not call SWIG. Offline mode uses `command_routes` and marks `_backend: swig`.

## Counts

| Set | Count | Evidence |
|---|---:|---|
| `server.tool` declarations | 123 | Static parse of `src/**/*.ts` |
| Registered MCP tools | 119 | 123 minus the four disabled router tools |
| Registered tools with a Python route or IPC handler | 119 | Phase 5 added routes for the former twelve missing tools |
| Registered tools with no handler | 0 | D1 is routed. Six of those tools return `UNSUPPORTED_OPERATION` |
| `command_routes` entries | 126 | `python/kicad_interface.py` |
| `IPC_CAPABLE_COMMANDS` entries | 26 | Same file |
| Inventory rows, including resources and Python-only routes | 149 | `audit/tool-inventory.csv` |

The complete mapping is `audit/tool-inventory.csv`. Defects are `audit/defects.csv`.

## Backend classes

When `KICAD_BACKEND=ipc` and `ipc_board_api` is connected:

- **ipc_only**: `clone_component`. There is no SWIG route.
- **ipc_when_enabled**: the other IPC-capable commands. Phase 2 removed the silent SWIG fallback. Offline mode can still use the SWIG route where one exists.
- **delete_trace**: Phase 2 uses IPC `remove_items`. The audit originally found this handler calling SWIG.
- **add_board_outline**: Phase 2 draws rectangles, rounded rectangles, circles, and polygons through IPC. The audit originally found rectangles delegated to SWIG.
- **swig_file_or_external**: every implemented tool that is not IPC-capable. This includes schematic file edits, footprint and symbol library commands, export commands, DRC through `kicad-cli`, JLCPCB and datasheet HTTP calls, and the Freerouting external process.
- **none**: no longer used for a registered tool. Six tools now return `UNSUPPORTED_OPERATION` instead of `Unknown command`.

IPC handlers live on `KiCADInterface` in `python/kicad_interface.py` and call `self.ipc_board_api` in `python/kicad_api/ipc_backend.py`. SWIG command objects are constructed in `python/commands/`.

## Aliases

| Registered or routed name | Actual handler |
|---|---|
| `add_board_text` | Same handlers as `add_text`: `_ipc_add_text` and `BoardCommands.add_text` |
| `add_wire` | Not an alias of `add_schematic_wire`. Returns `UNSUPPORTED_OPERATION` |
| `add_zone` | Its own IPC zone creation. Not an alias of `add_copper_pour` |
| `add_net_class` | Not an alias of `create_netclass`. Returns `UNSUPPORTED_OPERATION` |
| `export_netlist` | `kicad-cli` export of the matching saved schematic. Not an alias of `generate_netlist` |

Python routes with no current tool call include `add_text`, `add_schematic_wire`, `load_schematic`, `list_schematic_libraries`, `get_backend_info`, and the `ipc_add_*` / `ipc_get_*` / `ipc_save_board` compatibility names.

## Confirmed working operations

These were demonstrated on the disposable board before this audit. This audit did not repeat them.

| Tool | Result established earlier |
|---|---|
| `get_board_info` | Board information was read through IPC. The reported dimensions are an Edge.Cuts bounding box. |
| `get_component_list` | Footprints were listed, including reference, value, `str(definition.id)`, position, rotation, layer, and UUID. |
| `move_component` | Movement updated the editor, and manual undo worked. |
| `delete_component` | Deletion through IPC worked. |
| `clone_component` | Cloning worked with `copyNets` false and true. The default clears pad nets inside the clone transaction. |
| `place_component` | Placement clones an existing footprint on the same copper side, rejects duplicate references, unknown footprints, library footprints that are not on the board, and a foreign `boardPath`, and converts inches. |
| Undo | Manual KiCad undo of movement and cloning was reported. There is no MCP undo tool. |

The board was left with 73 footprints, including `R_PLACE`. Do not use that board for mutating tests until a new disposable copy is intentional.

`clone_component` and `place_component` must be preserved: net clearing unless `copyNets` is true, duplicate-reference rejection, one IPC transaction for the clone, exact `Library:FootprintName` matching, same-side-only placement, and `boardPath` refusal. `place_component` must not regain `SaveBoard`, `revert`, or placeholder success.

## Critical defects

D2, D3, and D4 below are the original findings. Their source status after Phase 2 is in [Phase 2 status](#phase-2-status).

1. **Twelve registered tools had no Python handler.** Phase 5 gave each a route. Six perform a verified operation. Six return `UNSUPPORTED_OPERATION`. See D1.
2. **SWIG success can overwrite the open PCB file.** `_auto_save_board` calls `pcbnew.SaveBoard` after a successful board-mutating `command_routes` command. That uses the SWIG board object, not the editor's unsaved document.
3. **IPC failure falls back to SWIG for every IPC-capable command that also has a route.** `place_component` is in that set. Its SWIG handler can `LoadBoard` from `boardPath`. `clone_component` is not in that set.
4. **Two IPC handlers silently leave the IPC editor.** `delete_trace` always calls SWIG. Rectangle board outlines do too. Their IPC return path does not call `_auto_save`, so the result can also fail to reach either the editor or the file.
5. **`add_net` reports success without creating a net.** Fixed in Phase 4: the IPC handler now returns `UNSUPPORTED_OPERATION` or `ALREADY_EXISTS` and does not report success. KiCad 10 IPC still cannot create a net.
6. **`rotate_component` does not implement its published contract.** The TypeScript description says the angle is absolute. The original IPC handler added it to the current angle. Phase 4 sets the absolute angle and reads it back. Live-validated on a disposable clone.

Resource reads for project files, component groups, 3D views, and several library details are also unrouted. They are not tools, but the resources that call them cannot succeed.

## Compatibility with KiCad 10 and kicad-python 0.8.0

Preserved and already observed:

- `Box2` uses `pos` and `size`.
- Footprint identity is `str(fp.definition.id)`.
- UUID is `fp.id.value`.
- Copper sides `3` and `34` are `F.Cu` and `B.Cu`.
- `pcbnew.GetGlobalFootprintLib()` is absent.
- `KiCad.get_library_footprint()` is absent.
- A Python protobuf `Any` cannot be passed to SWIG `FOOTPRINT.Serialize()`.
- This KiCad build has no `FlipItems` handler, so a front-side footprint cannot be placed on `B.Cu` by flipping.
- A library footprint that is not already on the open board cannot be imported through IPC.

`set_board_size` and `get_board_info` still expose the Edge.Cuts bounding box as board size. That number is not a manufacturing dimension.

## Prioritised testing plan

Do this on a copy of the disposable board, not on a production board. Restart the Inspector from the current `dist/index.js` before testing.

1. Read-only regression: `get_board_info` and `get_component_list`. Confirm 73 footprints and `R_PLACE` before any write.
2. Do not re-test `clone_component` or `place_component` until a behavior change is proposed. Their prior results are the baseline.
3. Call each of the twelve unrouted tools once and record the `Unknown command` response. No board change is expected.
4. Call `add_net` and confirm whether a net appears. The source says it will not.
5. On a copy, compare `rotate_component` with angle `0` and angle `90` against the published absolute-angle contract.
6. On a copy, call `delete_trace` and rectangle `add_board_outline` while the editor has an unsaved edit. Confirm whether the editor, the file, or neither changes.
7. Only after those reads, test one SWIG-only mutating command with IPC connected and confirm it does not save over unsaved editor work.
8. Defer Freerouting, JLCPCB, datasheet download, and fabrication export until the dispatch and file-write defects are fixed.

## Prioritised development roadmap

1. Guard `pcbnew.SaveBoard` while the PCB editor is open. Done in source during Phase 2. Not live-tested. `clone_component` and the IPC `place_component` path were not edited.
2. Make IPC fallback visible and non-destructive. Done in source during Phase 2. A missing IPC connection returns `IPC_UNAVAILABLE` and does not call SWIG. Not live-tested.
3. Repair `delete_trace` and rectangle `add_board_outline` so they either use IPC or return unsupported. Done in source during Phase 2 with IPC commits. Not live-tested.
4. Stop `add_net` from returning success when no net is created. Done in Phase 4. Creation itself is unsupported by KiCad 10 IPC, so the tool returns `UNSUPPORTED_OPERATION`.
5. Make `rotate_component` absolute, matching its TypeScript description, and test it. Done and live-validated in Phase 4.
6. Connect or remove the twelve unrouted tools. Done in Phase 5. The four similar names were not aliased. Six tools remain explicit unsupported operations.
7. Connect or remove the unrouted resource commands.
8. Library-footprint import remains blocked on KiCad 10 IPC. Do not add a placeholder or a partial `.kicad_mod` parser. A future implementation must preserve pad geometry, drills, layers, silk, courtyard, net-tie data, and 3D models, or it must keep the current explicit rejection.

## Phase 2 status

Date: 2026-11-01. Source and mocked tests only. The disposable board was not opened or modified. `clone_component` and `place_component` were not edited.

| Defect | Status | What changed |
|---|---|---|
| D2 automatic `SaveBoard` | Live-validated on 2026-11-01 | `_auto_save_board` writes only an offline file this process opened or created. During the Phase 3 IPC edits, both PCB files kept SHA-256 `04514a3e851369cee2364171711f0496c63ad3a89a1507cecd9fdbbc1146bbd8`. |
| D3 silent IPC-to-SWIG fallback | Live-validated on 2026-11-01 | With the board API removed for one call, `delete_trace` returned `IPC_UNAVAILABLE` and the log said SWIG was not called. The track count stayed 545. |
| D4 `delete_trace` and rectangle `add_board_outline` | Live-validated on 2026-11-01 | A new trace `7d0e8b06-4fc1-43f5-b4e2-17261d151a01` was deleted through IPC. A 1.2 mm by 0.8 mm rectangle `bd59055d-c9a3-40ee-8e77-9b090f18dbed` was created through IPC. Undo and redo were re-read from the editor. No pre-existing track was removed. |

The twelve unrouted tools (D1) were left unchanged. D5 and D6 were fixed and live-validated in Phase 4.

Mocked coverage is `python/tests/test_phase_safety.py` (29 checks, KiCad Python 3.11.5). `pcbnew` was replaced with a stub in that process. No editor command was sent.

## Phase 4 status

Date: 2026-11-01. Automated tests ran on KiCad Python without opening the editor. The live run used only `ipc-phase3-test.kicad_pcb`, which pcbnew already had open. `R_PLACE` was not moved or rotated. The temporary clone `R_PHASE4` and the temporary track were removed before the run finished. Both PCB files kept SHA-256 `04514a3e851369cee2364171711f0496c63ad3a89a1507cecd9fdbbc1146bbd8`.

| Defect | Status | What changed |
|---|---|---|
| D5 `add_net` false success | Live-validated | `PHASE4_NEW_NET` returned `UNSUPPORTED_OPERATION`. The net count stayed 50. `+5V_ISO` returned `ALREADY_EXISTS` and was not modified. |
| D6 absolute rotation | Live-validated | Disposable `R_PHASE4` ended at 90, then 180, then 0 degrees. Undo restored 180 and redo restored 0. Its UUID and footprint stayed the same, and `R_PLACE` stayed at 0 degrees. |
| D13 `route_trace` net mismatch | Live-validated | `PHASE4_MISSING_NET` created no track. A track on the existing net `+5V_ISO` was re-read with that net, undone, redone, and deleted. |
| D14 protobuf UUID text | Live-validated | The new track id and the existing via ids are bare `id.value` strings. |

`python/tests/test_phase4.py` passed 16 checks. `python/tests/test_phase_safety.py` still passed 29. The twelve unrouted tools were not implemented.

## Phase 5 status

Date: 2026-11-01. The twelve missing routes now dispatch. `add_zone`, `add_component_annotation`, `group_components`, and `export_position_file` were live-validated on `ipc-phase3-test.kicad_pcb`. `export_vrml` wrote a VRML header from a copy of the saved PCB. `export_netlist` found no `ipc-phase3-test.kicad_sch` and did not read `IPM.kicad_sch`; a separate temporary schematic export succeeded through `kicad-cli`. The other six tools returned `UNSUPPORTED_OPERATION` and left the board counts unchanged.

`R_PLACE` stayed `9e910bf0-f26e-4922-aff9-97b23a798d21`. Temporary clones `R_P5A` and `R_P5B`, zone `cfe9613c-e101-4c0e-bdd3-c200a20208ff`, and group `56370812-d864-4f70-8eeb-cf46ad1c57b5` were removed. During this run both PCB hashes stayed at their starting values. The disposable file's hash was already different from the Phase 4 hash before the first Phase 5 command. `ipc-move-test.kicad_pcb` stayed `04514a3e851369cee2364171711f0496c63ad3a89a1507cecd9fdbbc1146bbd8`.

## What this audit did not do

No tool was executed. No footprint count was read from the live board. Prior success is cited only for the operations listed above. All other rows in the inventory are statically inspected.
