# Phase 7B — Schematic-to-PCB synchronisation

Status: **PASS**. Live IPC and project consistency both passed. The board is unrouted and has no outline, which is the expected state before placement and routing.

The validated Phase 7A schematic was transferred into a new board. All seven library footprints are present, every pad carries the KiCad netlist net, and the source schematic and the protected IPM boards are unchanged. The running PCB editor is still `ipc-phase3-test.kicad_pcb`. It was not closed and was not written. Live IPC of the new board is therefore not complete.

Versions read from the tools:

- `pcbnew.GetBuildVersion()` and `kicad-cli version`: **10.0.5** (this is the interpreter that created and reopened the file)
- Running PCB editor, `kipy` `get_api_version()`: **10.0.6**

## Root cause

The previous `sync_schematic_to_board` handler did not transfer footprints.

1. It loaded an existing board and called `SetNet` on footprints that were already there. It never called `FootprintLoad`. A blank project PCB stayed empty, and the command could still report success.
2. IPC mode does not import `pcbnew` at startup. The old handler then raised `NameError: pcbnew is not defined` before it reached the board. Importing `pcbnew` alone would not place footprints.
3. After a successful SWIG handler, `handle_command` autosaves `self.board` for every board-mutating command. That object can be a previously loaded board, not the requested target. A naive sync could therefore `SaveBoard` the wrong file.
4. The reconstructed internal netlist is not the authority. Phase 6 showed it can repeat a bad pin map. The authority is the sexpr netlist exported by `kicad-cli` from the schematic. The handler compares the two and refuses to write when footprint pins disagree. The first comparison failed because the handler passed a string path into `PinLocator`, which needs a `Path`; the internal netlist came back empty. Passing `Path(schematic_path)` makes the two netlists agree on the seven footprints.

## What the new command does

`synchronize_schematic_to_pcb` in `python/kicad_api/schematic_sync.py`:

- Requires an explicit `boardPath`. A missing path returns `MISSING_PCB_TARGET` and writes nothing.
- Refuses the target when `evaluate_pcb_file_access` says the editor owns it or a lock file is present.
- Exports the netlist with `kicad-cli sch export netlist --format kicadsexpr`.
- Refuses if that export changes the schematic, if the netlist `source` is a different file, or if the internal netlist disagrees on any footprint pin (a leading `/` on a local net is the same name).
- Loads each footprint with `pcbnew.FootprintLoad` from the installed `.pretty` library. A missing library id is `FOOTPRINT_NOT_FOUND`. Nothing is substituted.
- Checks pad numbers. A netlist pin with no pad is `MISSING_PAD`. A footprint pad with no netlist node is `UNASSIGNED_PAD`. Two nets on one pin are `NET_MISMATCH`.
- Records geometry before `board.Add` and refuses if adding the footprint changes pad size, drill, or position.
- Creates nets with `NETINFO_ITEM` and assigns them with `pad.SetNet`. Net names are copied exactly, including `/LED_A`, `/LED_K`, `/CTRL_IN`, and `/BASE`. `+5V` and `GND` stay global names.
- Sets reference, value, footprint id, sheet name, sheet file, and the KiCad path `/{sheet uuid}/{symbol tstamp}`.
- Saves only that board with `BOARD.Save`. `sync_schematic_to_board` is excluded from `_auto_save_board`, so a previously loaded board is not written.
- Reloads the file and compares every pad with the netlist. On a failure after the save, the previous bytes are restored, or a newly created file is deleted.
- A second run updates the same footprints in place and does not move them.

New footprints are placed on a 25 mm grid from (20, 20) mm so they are not stacked. That is not placement optimisation. There is no routing, outline, zone, or Gerber export.

`pcbnew.Save` also writes a sibling project file. Its schematic entry is `MCP-E2E-LED-P7B.kicad_sch`, which was not created. The footprints' sheet file remains `MCP-E2E-LED-P7A.kicad_sch`. Do not let the editor create a replacement schematic.

## Saved board

`C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7B\MCP-E2E-LED-P7B.kicad_pcb`

Sibling files written by KiCad while saving: `MCP-E2E-LED-P7B.kicad_pro`, `MCP-E2E-LED-P7B.kicad_prl`.

Independent reopen: `pcbnew.LoadBoard` returned seven footprints, and `kicad-cli pcb drc` (10.0.5) read the same file. The board hash was the same after DRC.

DRC, which is outside this phase, reported one error and nine unconnected items:

- `invalid_outline`: no Edge.Cuts edges. No outline was added.
- Nine `unconnected_items`: copper was not routed. The pad nets in those messages are the nets in the table below.

`schematic_parity` is empty because the generated project does not point at the Phase 7A schematic.

## Footprint mapping

Sheet UUID `d95379df-973c-4d3f-9a6e-a4efdc2bfb81`. Each path is `/{sheet uuid}/{symbol tstamp}`. Each footprint has one 3D model. Courtyard, silkscreen, and fabrication graphics from the library file are present. SMD pads are front copper, paste, and mask (`layer set 00002003`). Through-hole pads are on the full copper set (`55555555_5555555f`).

| Ref | Value | Library footprint | Symbol tstamp | Graphics (silk / courtyard / fab) | 3D model |
| --- | --- | --- | --- | --- | --- |
| Q1 | 2N3904 | `Package_TO_SOT_THT:TO-92_Inline` | `f935c3be-3693-47d9-bd9f-390a03261218` | 3 / 4 / 4 | `Package_TO_SOT_THT.3dshapes/TO-92_Inline.step` |
| D1 | Red | `LED_SMD:LED_0603_1608Metric` | `a8d5e263-f1e2-460a-92a4-d423d997b7fe` | 3 / 1 / 6 | `LED_SMD.3dshapes/LED_0603_1608Metric.step` |
| R1 | 330 | `Resistor_SMD:R_0603_1608Metric` | `f4ead3bf-3e20-4205-9a63-164ab2eaa010` | 2 / 1 / 2 | `Resistor_SMD.3dshapes/R_0603_1608Metric.step` |
| R2 | 4.7k | `Resistor_SMD:R_0603_1608Metric` | `b17ac674-35ff-4b29-a2ef-5d089b2efb12` | 2 / 1 / 2 | `Resistor_SMD.3dshapes/R_0603_1608Metric.step` |
| R3 | 100k | `Resistor_SMD:R_0603_1608Metric` | `d29483d0-1b97-40a6-a6ea-8522609ea8aa` | 2 / 1 / 2 | `Resistor_SMD.3dshapes/R_0603_1608Metric.step` |
| J1 | PWR | `Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical` | `70fa8411-de67-4312-9e68-325c2588a66d` | 6 / 1 / 6 | `Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x02_P2.54mm_Vertical.step` |
| J2 | CTRL | `Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical` | `d7d0d023-2756-44a7-b939-d1cb2d1d56bb` | 6 / 1 / 6 | `Connector_PinHeader_2.54mm.3dshapes/PinHeader_1x02_P2.54mm_Vertical.step` |

Q1 uses the footprint already selected on the Phase 7A symbol, `Package_TO_SOT_THT:TO-92_Inline`. Its pads were read back rather than assumed: pad 1 is rectangular, pads 2 and 3 are oval, pitch 1.27 mm, drill 0.75 mm. That matches the 2N3904 E-B-C numbering in the netlist.

Library geometry that was preserved:

| Footprint | Pad | Shape | Copper size (mm) | Drill (mm) | Position relative to origin (mm) |
| --- | --- | --- | --- | --- | --- |
| TO-92_Inline | 1 | rectangle | 1.05 × 1.50 | 0.75 | 0, 0 |
| TO-92_Inline | 2 | oval | 1.05 × 1.50 | 0.75 | 1.27, 0 |
| TO-92_Inline | 3 | oval | 1.05 × 1.50 | 0.75 | 2.54, 0 |
| LED_0603 | 1 | round rectangle | 0.875 × 0.95 | none | −0.7875, 0 |
| LED_0603 | 2 | round rectangle | 0.875 × 0.95 | none | 0.7875, 0 |
| R_0603 | 1 | round rectangle | 0.80 × 0.95 | none | −0.825, 0 |
| R_0603 | 2 | round rectangle | 0.80 × 0.95 | none | 0.825, 0 |
| PinHeader_1x02 | 1 | rectangle | 1.70 × 1.70 | 1.00 | 0, 0 |
| PinHeader_1x02 | 2 | circle | 1.70 × 1.70 | 1.00 | 0, 2.54 |

## Pad-to-net mapping

Names are the KiCad netlist names. Logical names from the mission are in the second column. Q1 pad 1 is the emitter, pad 2 the base, and pad 3 the collector. D1 pad 1 is the cathode and pad 2 the anode.

| Net on the PCB | Logical name | Pads |
| --- | --- | --- |
| `+5V` | +5V | J1.1, R1.1 |
| `/LED_A` | LED_A | R1.2, D1.2 |
| `/LED_K` | LED_K | D1.1, Q1.3 |
| `GND` | GND | J1.2, J2.2, Q1.1, R3.2 |
| `/CTRL_IN` | CTRL_IN | J2.1, R2.1 |
| `/BASE` | BASE | R2.2, R3.1, Q1.2 |

Reload found these fifteen assignments and no others. The internal netlist, once given a `Path`, agrees. Its extra power-symbol nodes (`#PWR01`, `#PWR02`, `#FLG01`, `#FLG02`) are not footprints and are not compared.

## File hashes

SHA-256 after the final save, the DRC reopen, and a read-only IPC document list.

| File | SHA-256 | Bytes |
| --- | --- | --- |
| `MCP-E2E-LED-P7B.kicad_pcb` | `abcf77545e91bf9e6ebbbb127dd4a82358c6b6a2ced3dcd537119b8768cb9927` | 29607 |
| `MCP-E2E-LED-P7A.kicad_sch` | `81bb3b9e4e82f919c4305a48f5f57d528f91438c1b28021282f1eb416a2888f0` | 35284 |
| `MCP-E2E-LED.kicad_sch` (Phase 6) | `eb9719f84866115fe41cff17444c07758ca6cd2e5c49db5d7e4cab35f404e776` | 48807 |
| `ipc-phase3-test.kicad_pcb` | `383e481737b4c048c9f87335b48ff0fdb381fb47a816262da09930f7ca3d4996` | 1756093 |
| `ipc-move-test.kicad_pcb` | `04514a3e851369cee2364171711f0496c63ad3a89a1507cecd9fdbbc1146bbd8` | 1756123 |
| `IPM.kicad_pcb` | `6f6c38528b90e1326748c1a99027a6d7af1a44209d230b2d09aaf3c884bb50a2` | 1746410 |

The three IPM hashes match the baselines recorded before this phase. The Phase 7A schematic hash is unchanged. No `SaveBoard` was called against the open editor board.

## Modified source files

- `python/kicad_api/schematic_sync.py` — new offline synchroniser
- `python/kicad_interface.py` — `sync_schematic_to_board` calls that synchroniser, skips `_auto_save_board` for this command, and passes a `Path` into the internal netlist
- `python/tests/test_phase7b_sync.py` — new tests, using real `pcbnew` and `kicad-cli`

## Automated tests

`python/tests/test_phase7b_sync.py` with KiCad Python: **11 passed, 0 failed**. These are not mocks. The real schematic is exported by `kicad-cli` and the real libraries are loaded.

| Test | Result |
| --- | --- |
| Missing footprint, no board file created | PASS |
| Duplicate reference in the netlist | PASS |
| Missing pad number, no board file created | PASS |
| Net mismatch between netlist and reloaded pads | PASS |
| Open-editor target rejected, target bytes unchanged | PASS |
| Lock file rejects the target | PASS |
| Missing `boardPath` | PASS |
| Netlist source path is a different schematic | PASS |
| Repeated synchronisation updates seven footprints and does not move or duplicate them | PASS |
| Failure after save restores the previous board bytes | PASS |
| Partial netlist (second footprint missing) leaves no board | PASS |
| A different board already loaded in `self.board` is not written | PASS |
| Phase 7A schematic bytes unchanged | PASS |

Regression, separate processes, KiCad Python:

| Suite | Result |
| --- | --- |
| `test_phase4.py` | 16 passed |
| `test_phase5.py` | 11 passed |
| `test_phase_safety.py` | 29 passed |
| `test_phase7_schematic.py` | 7 passed |

These suites import `pytest`, which is not installed in KiCad's Python, so they were not executed: `test_phase2.py`, `test_phase3.py`, `test_schematic_tools.py`, `test_schematic_component_fields.py`, `test_wire_manager_text_based.py`, `test_delete_schematic_component.py`, `test_freerouting.py`. `python/test_ipc_backend.py` was not run. Its later steps add a track, a via, and text to whatever board is open, and the open board is `ipc-phase3-test.kicad_pcb`.

## Live IPC

**BLOCKED.** Not completed.

A read-only IPC connection succeeded. `get_open_documents` returned one PCB:

- `board_filename`: `ipc-phase3-test.kicad_pcb`
- `project.path`: `C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM`
- API version: `10.0.6`

That file's hash was the same after the call. `get_board_info`, `get_component_list`, and `get_nets_list` were not called, because they would describe the protected board rather than the Phase 7B board.

The editor window is on another monitor. This session can only see and type on the primary display, so the editor was not closed and the new file was not opened. Closing it from here could raise a save prompt for `ipc-phase3-test.kicad_pcb`. No process was killed.

### Manual check, not yet done

1. In the PCB editor that shows `ipc-phase3-test`, close that document. If asked to save, choose **Don't Save**.
2. Confirm the file hash is still `383e481737b4c048c9f87335b48ff0fdb381fb47a816262da09930f7ca3d4996`.
3. Open only `C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7B\MCP-E2E-LED-P7B.kicad_pcb`. If KiCad offers to create `MCP-E2E-LED-P7B.kicad_sch`, decline. Do not open the IPM project.
4. With IPC enabled, from KiCad Python and `KICAD_BACKEND=ipc`, call `get_board_info`, `get_component_list`, and `get_nets_list` on that document only.
5. Expect seven footprints with the library ids in the table above, and nets `+5V`, `/BASE`, `/CTRL_IN`, `/LED_A`, `/LED_K`, and `GND`. `list_components` does not include pad nets. Read those from each footprint's pads and compare them with the pad table. Do not route, save the IPM boards, or export Gerbers.

## Remaining unsupported cases

- Synchronising a board that is open in the editor. The command refuses it. IPC cannot load a library footprint that is not already on the open board, and it cannot create a net.
- A netlist whose internal reconstruction disagrees with `kicad-cli`. The command writes nothing.
- A footprint id that is not in the installed libraries, a missing pad, an extra pad, or a duplicate reference.
- Multi-sheet designs. The path uses the first `(uuid ...)` in the schematic, which on this root sheet is the sheet UUID. A hierarchical sheet was not part of this circuit.
- Power symbols and flags are not placed on the PCB.
- Board outline, routing, courtyard-to-courtyard placement, and Gerber export. DRC's missing outline and unconnected copper are the expected result of that limit.
- The first save in `MCP-E2E-LED-P7B` wrote a project whose root-sheet UUID was nil, so schematic parity had nothing to compare. The linked project below replaces that UUID with the schematic sheet UUID. The original directory was left as saved.

## Final validation

### Live IPC — passed

The first check found only `ipc-phase3-test.kicad_pcb` and stopped before any board read. After the schematic and PCB were opened in the editor, IPC 10.0.6 reported exactly one PCB and one schematic:

- PCB: `C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7B-PROJECT\MCP-E2E-LED-P7B.kicad_pcb`
- Schematic: `MCP-E2E-LED-P7B.kicad_sch` in the same project

`get_board_info`, `get_component_list`, and `get_nets_list` all returned `_backend: ipc`.

| Command | Result |
| --- | --- |
| `get_board_info` | 7 components, 0 tracks, 0 vias, 7 nets (6 named plus the unnamed default). Board size is 0 × 0 mm because Edge.Cuts is empty. |
| `get_component_list` | D1 Red, J1 PWR, J2 CTRL, Q1 2N3904, R1 330, R2 4.7k, R3 100k. All seven are on F.Cu with the library ids below. |
| `get_nets_list` | `+5V`, `/BASE`, `/CTRL_IN`, `/LED_A`, `/LED_K`, `GND` |

Pad nets were read from the open footprints and match Phase 7A on all fifteen pads: J1.1 and R1.1 are `+5V`; R1.2 and D1.2 are `/LED_A`; D1.1 and Q1.3 are `/LED_K`; J1.2, J2.2, Q1.1, and R3.2 are `GND`; J2.1 and R2.1 are `/CTRL_IN`; R2.2, R3.1, and Q1.2 are `/BASE`. Q1 is `Package_TO_SOT_THT:TO-92_Inline`, so pad 1 is the emitter, pad 2 the base, and pad 3 the collector.

The PCB hash was still `28c77df5dfb183a6980fc7005385c8552fc46ccc0cff3b05dfa17b1d16e70d42` after the reads. The schematic and `ipc-phase3-test.kicad_pcb` hashes were unchanged. Nothing was saved or routed.

### Linked project

Directory: `C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7B-PROJECT`

| File | SHA-256 | Bytes |
| --- | --- | --- |
| `MCP-E2E-LED-P7B.kicad_sch` | `81bb3b9e4e82f919c4305a48f5f57d528f91438c1b28021282f1eb416a2888f0` | 35284 |
| `MCP-E2E-LED-P7B.kicad_pcb` | `28c77df5dfb183a6980fc7005385c8552fc46ccc0cff3b05dfa17b1d16e70d42` | 29607 |
| `MCP-E2E-LED-P7B.kicad_pro` | `18b53c9058830cd8634bcb8dd6749c309b5b8816e073f1b94201cb6472fadd84` | 10099 |

The schematic is a byte copy of `MCP-E2E-LED-P7A.kicad_sch`, so the sheet UUID `d95379df-973c-4d3f-9a6e-a4efdc2bfb81` and every symbol UUID are unchanged. Phase 7A itself is still that same hash.

`pcbnew` loaded the original Phase 7B board and saved a new file. The only field written differently is each footprint's `sheetfile`, now `MCP-E2E-LED-P7B.kicad_sch`. References, values, library ids, paths, positions, pad geometry, and pad nets matched the source board after reload. The original `MCP-E2E-LED-P7B.kicad_pcb` is still `abcf77545e91bf9e6ebbbb127dd4a82358c6b6a2ced3dcd537119b8768cb9927`.

KiCad wrote the `.kicad_pro` during that save. Its root sheet filename was already `MCP-E2E-LED-P7B.kicad_sch`, and its UUID was `00000000-0000-0000-0000-000000000000`. That nil UUID was replaced with the schematic sheet UUID. The rest of the project file is the KiCad 10 project that `pcbnew.Save` produced.

### Netlist comparison

`kicad-cli` 10.0.5 exported both schematics. Components, footprint ids, symbol timestamps, net names, and pin nodes are the same. The only difference is the `(source ...)` path: the Phase 7A file versus the project copy.

### Project consistency

| Check | Result |
| --- | --- |
| Schematic ERC (`kicad-cli sch erc`, 10.0.5) | 0 violations on the root sheet |
| PCB DRC with `--schematic-parity` (10.0.5) | 0 schematic parity issues |
| Other DRC | 1 `invalid_outline` (no Edge.Cuts) and 9 unconnected items |
| Footprint count and references | 7, unchanged from the source board |
| Pad nets | unchanged |
| Schematic and original PCB hashes | unchanged |
| Protected IPM hashes | unchanged |

The DRC and ERC reports are in `MCP-E2E-LED-P7B-PROJECT\evidence`. Neither command was asked to save or refill the board, and both file hashes were the same after the reports were written.

The outline error and the unconnected copper are the expected unrouted state. No other DRC error or warning was reported. `missing_courtyard` and `footprint_filters_mismatch` are in the report's ignored-check list, which is KiCad's default exclusion set, not a new violation.

## Completion criteria

| # | Criterion | Status |
| --- | --- | --- |
| 1 | A fresh PCB contains all seven actual footprints | **PASS** |
| 2 | Every pad has the correct net assignment | **PASS** |
| 3 | The saved PCB can be reopened by KiCad 10 | **PASS** (`LoadBoard` and `kicad-cli` 10.0.5; the editor API that is running is 10.0.6 and has not opened this file) |
| 4 | IPC can read the new PCB | **PASS** (KiCad 10.0.6 read the project PCB: 7 footprints, 6 electrical nets, 15 pads) |
| 5 | Source schematic and protected projects are unchanged | **PASS** |
| 6 | No `SaveBoard` or SWIG fallback wrote a live board | **PASS** |

Phase 7B is **PASS**. Live IPC and schematic-to-PCB parity both agree with the Phase 7A netlist. The board still has no outline and no tracks. Placement optimisation, routing, and manufacturing export have not been started.
