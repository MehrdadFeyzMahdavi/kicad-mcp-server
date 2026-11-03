# Phase 5 results

Date: 2026-11-01.

KiCad 10.0.6 and kicad-python 0.8.0. Live commands used the already open disposable board `C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\ipc-phase3-test.kicad_pcb`. `ipc-move-test.kicad_pcb` was not opened. The machine record is `audit/phase5_live_output.json`.

## Alias decisions

`add_wire` was not connected to `add_schematic_wire`. The tool sends `start` and `end` and has no schematic path. The existing writer requires `schematicPath`, `startPoint`, and `endPoint`, and edits the schematic file. No schematic was edited.

`add_zone` was not connected to `add_copper_pour`. The zone tool requires a unit and can request a pad connection. The pour tool treats coordinates as millimetres, can omit the outline, and its IPC path does not verify the net. `add_zone` now has its own IPC commit.

`add_net_class` was not connected to `create_netclass`. The registered tool requires clearance, track width, via diameter, and via drill, and can also carry microvia, differential-pair, and net-membership fields. `create_netclass` writes the SWIG board. KiCad 10 IPC can read a net's class and has no create-netclass command.

`export_netlist` was not connected to `generate_netlist`. The export tool writes a KiCad, Spice, Cadstar, or OrcadPCB2 file. `generate_netlist` returns an in-memory schematic netlist and does not write that file.

## What is operational

| Tool | Result |
|---|---|
| `add_zone` | Live. Zone `cfe9613c-e101-4c0e-bdd3-c200a20208ff` on `+5V_ISO`, thermal pad connection, clearance 0.2 mm. A missing net created nothing. Undo removed the zone. |
| `add_component_annotation` | Live on disposable `R_P5A`. The description read back `PHASE5 NOTE` and was visible. Undo restored the empty description. The same footprint id remained. |
| `group_components` | Live. Group `56370812-d864-4f70-8eeb-cf46ad1c57b5` contained `R_P5A` and `R_P5B` only. Undo removed the group and left both clones. |
| `export_position_file` | Live. CSV from the open editor included `R_PLACE` at 230 mm, 170 mm. It contained 72 top-side footprints. The temporary clones were already gone. |
| `export_vrml` | Live. `kicad-cli` wrote a file beginning `#VRML V2.0 utf8` from a copy of the saved PCB. `includeComponents: false` stays unsupported because the CLI cannot omit models entirely. |
| `export_netlist` | Implemented. `kicad-cli` exported a temporary schematic in the automated test, and that source file was unchanged. On the open board it returned `NOT_FOUND` because `ipc-phase3-test.kicad_sch` does not exist. `IPM.kicad_sch` was not used. |

## What remains unsupported

These return `success: false` and `UNSUPPORTED_OPERATION`. The live call left the board at 73 footprints, 26 zones, 0 groups, 545 tracks, and 50 nets.

- `add_wire`
- `add_net_class`
- `assign_net_to_class`
- `check_clearance`
- `replace_component`
- `set_layer_constraints`

`check_clearance` does not invent a pass or fail. `replace_component` does not delete and recreate a footprint. `set_layer_constraints` is not implemented as a stackup edit.

## Automated tests

`python/tests/test_phase5.py`: 11 passed, 0 failed. This includes the real `kicad-cli` netlist export. `python/tests/test_phase_safety.py`: 29 passed. `python/tests/test_phase4.py`: 16 passed.

## Live board result

`R_PLACE` remained `9e910bf0-f26e-4922-aff9-97b23a798d21`, `Resistors SMD:RESC2012X60N`, description empty, rotation 0, at (230, 170) mm. `R_P5A` and `R_P5B` were deleted after the annotation and group checks. No extra zone remained.

`SaveBoard` and `LoadBoard` were not called. The open path stayed the disposable board. From the start of this run to the end, `ipc-phase3-test.kicad_pcb` stayed size 1756093 and SHA-256 `383e481737b4c048c9f87335b48ff0fdb381fb47a816262da09930f7ca3d4996`. That hash was already different from the Phase 4 hash before the first Phase 5 command. `ipc-move-test.kicad_pcb` stayed SHA-256 `04514a3e851369cee2364171711f0496c63ad3a89a1507cecd9fdbbc1146bbd8`.

## Safety notes

`add_copper_pour` still uses its older IPC path. `add_zone` does not. A missing net on `add_zone` creates no zone.

VRML and netlist export copy the saved input and pass the copy to `kicad-cli`. They do not include unsaved editor changes, and they do not use the open PCB as the CLI input. The position file is read from the live editor.

Annotation writes the footprint description field. It is not a new free-standing text object.

## Counts and remaining KiCad 10 work

119 MCP tools are registered. All 119 now have a Python dispatch route. Four router tools remain unregistered, so the source still contains 123 `server.tool` declarations. `command_routes` has 126 entries and `IPC_CAPABLE_COMMANDS` has 26.

Still open: creating a net or net class through IPC, assigning a net to a class, pairwise clearance, per-layer constraints, replacing a footprint definition, schematic wires through the `add_wire` schema, library footprints that are not already on the board, flipping a footprint to the other copper side, and the unrouted MCP resource commands in D7.
