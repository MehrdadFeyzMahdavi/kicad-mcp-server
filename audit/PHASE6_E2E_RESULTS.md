# Phase 6 — End-to-end LED switch

The current server can create a project and place this circuit’s symbols. It cannot produce an electrically correct schematic, and it cannot transfer that schematic onto a PCB. Layout, routing, DRC, Gerber, drill, BOM, and pick-and-place were not run.

Test project: `C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED`. The IPM boards were not opened or written. Their hashes before and after the run are in `MCP-E2E-LED\evidence\summary.json` (`protectedUnchanged: true`).

Commands were the Python handlers behind the registered MCP tools (`KiCADInterface.handle_command`), which is what the TypeScript tools call. This was not a live MCP JSON-RPC session. No server source was changed.

## Answers

1. From a blank project the server gets through symbol placement, footprint properties, and stub-and-label wiring. KiCad 10.0.5 then reports a reversed 2N3904 and two open ground pins. PCB synchronisation raises `NameError: name 'pcbnew' is not defined` and stops.
2. Entirely through those handlers: create the project, place symbols, set reference, value, and footprint, add net labels by `connect_to_net`, and export a schematic PDF. The in-memory netlist and `run_erc` also return without crashing, but both disagree with KiCad.
3. Missing for this workflow: a KiCad 10 symbol-library search path, a Y-axis pin transform that matches the schematic editor, an ERC parser for the KiCad 10 report, and a schematic-to-PCB update that places footprints. `add_wire` is an explicit unsupported operation. There is no separate drill tool; drill output is a flag on `export_gerber`, and that path was not reached.
4. On this KiCad 10 install: symbol lookup fails until `KICAD_SYMBOL_DIR` points at `C:\Program Files\KiCad\10.0\share\kicad\symbols`. ERC JSON has no top-level `violations` array, so the handler reports zero violations while `kicad-cli` reports errors. With `KICAD_BACKEND=ipc`, `pcbnew` is never imported, so `sync_schematic_to_board` cannot load the new board. The handler also only assigns nets to footprints that are already on the board. The new board is empty (2196 bytes) and was left empty.
5. Minimum work, as a separate change, not done here:
   - Search `KICAD10_SYMBOL_DIR` and `C:\Program Files\KiCad\10.0\share\kicad\symbols`.
   - In `pin_locator.py`, place a symbol pin at `symbol_y - pin_rel_y`. Sheet Y increases downward and symbol Y increases upward. The current code adds them (`abs_y = symbol_y + pin_rel_y`).
   - Read ERC violations from `sheets[].violations`.
   - Import `pcbnew` for the sync handler, and make sync add the schematic footprints instead of only calling `SetNet` on footprints already present.
   - Re-run this project from the schematic onward. Do not treat a later `route_trace` success as a routed board until the ratsnest is empty.

## Stage results

| Stage | Result | What was checked |
| --- | --- | --- |
| 1 Capability discovery | PASS | Handlers inspected, then exercised where the stage allowed |
| 2 Schematic | FAIL | Seven parts, values, and footprints are in the file. KiCad’s netlist is not the specified circuit |
| 3 ERC and connectivity | FAIL | Two pin errors remain. The MCP ERC result said zero |
| 4 PCB synchronisation | FAIL | `pcbnew` is not defined. No footprints were transferred |
| 5 Layout and routing | NOT TESTED | Stopped after stage 4 |
| 6 Manufacturing outputs | NOT TESTED | Gerber, Excellon, BOM, and position files were not generated |
| 7 Evidence | PASS | This file and `MCP-E2E-LED\evidence` |

## Capability status

| # | Capability | Status |
| --- | --- | --- |
| 1 | Create a KiCad project | Confirmed working |
| 2 | Create a schematic | Confirmed working, as the schematic `create_project` writes |
| 3 | Load library symbols | Failed with the built-in search. Confirmed working after `KICAD_SYMBOL_DIR` was set |
| 4 | Place symbols | Confirmed working under that same condition |
| 5 | Set reference and value | Confirmed working. Read back from the file |
| 6 | Connect pins with wires | `add_wire` is unsupported. `connect_to_net` runs, but KiCad does not accept the pin-2 and transistor geometry |
| 7 | Add net labels | Confirmed working. Labels are in the file |
| 8 | Assign footprints | Confirmed working as schematic properties. Not transferred to the PCB |
| 9 | Run ERC | Failed. The command returns success and zero violations for a schematic KiCad rejects |
| 10 | Generate a netlist | Failed as a check of the circuit. The in-memory netlist repeats the pin locator and does not match `kicad-cli` |
| 11 | Synchronise schematic to PCB | Failed. `NameError` on `pcbnew`. The handler would also not place new footprints |
| 12 | Place footprints on a new PCB | Not tested. Live IPC placement cannot import a library footprint that is not already on the open board, and the open board was left untouched |
| 13 | Route tracks | Not tested on this project |
| 14 | Add a board outline | Not tested. The IPC outline command would draw on the open IPM board |
| 15 | Run DRC | Not tested |
| 16 | Export Gerber and drill | Implemented in `export.py` (`generateDrillFiles` calls `kicad-cli pcb export drill`). Not tested |
| 17 | Export BOM and position file | Not tested on this project. Schematic PDF export did write a nonempty file |

## How the run was performed

`audit\phase6_e2e.py` called `handle_command`. The first process did not set `KICAD_SYMBOL_DIR`. `add_schematic_component` for Q1 returned:

`Symbol '2N3904' not found in library 'Transistor_BJT'`

`DynamicSymbolLoader.find_kicad_symbol_libraries` looks at KiCad 9.0 and 8.0 directories and at `KICAD9_SYMBOL_DIR`, `KICAD8_SYMBOL_DIR`, and `KICAD_SYMBOL_DIR`. It does not look at KiCad 10. The second process set `KICAD_SYMBOL_DIR` to the KiCad 10 symbol directory. That is an existing hook, not a source change. Placement then succeeded.

The open editor document stayed `C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\ipc-phase3-test.kicad_pcb`. No command parameter pointed at an IPM file.

## Symbol and footprint mapping

Pin names were read from the KiCad 10 symbol files before wiring. Footprint pad numbers were read from the footprint files. None of these footprints were placed on the PCB, so pad nets were not checked on copper.

| Ref | Symbol | Value read back | Footprint property | Pins |
| --- | --- | --- | --- | --- |
| Q1 | `Transistor_BJT:2N3904` (extends `Q_NPN_EBC`) | 2N3904 | `Package_TO_SOT_THT:TO-92_Inline` | 1 = E, 2 = B, 3 = C. Pads 1, 2, 3 are inline at 0, 1.27, and 2.54 mm. Pad 1 is the square pad |
| D1 | `Device:LED` | Red | `LED_SMD:LED_0603_1608Metric` | 1 = K, 2 = A. Pad 1 is at x = −0.7875 mm and carries the cathode silk and fab mark |
| R1 | `Device:R` | 330 | `Resistor_SMD:R_0603_1608Metric` | 1 and 2. Pads at x = −0.825 and +0.825 mm |
| R2 | `Device:R` | 4.7k | same resistor footprint | 1 and 2 |
| R3 | `Device:R` | 100k | same resistor footprint | 1 and 2 |
| J1 | `Connector_Generic:Conn_01x02` | PWR | `Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical` | 1 and 2. Pad 1 is rectangular, pad 2 is round |
| J2 | `Connector_Generic:Conn_01x02` | CTRL | same connector footprint | 1 and 2 |

`power:+5V` (`#PWR01`), `power:GND` (`#PWR02`), and two `power:PWR_FLAG` symbols (`#FLG01` on `+5V`, `#FLG02` on `GND`) were placed so ERC had a power-source declaration. Positions requested on a 1 mm grid were stored on the 1.27 mm grid. Q1 was requested at (140, 60) and stored at (139.7, 59.69).

## Connectivity

`connect_to_net` returned success for every requested pin and wrote 18 wire stubs plus labels. The server’s own `generate_netlist` then reported the intended membership, including `LED_K = D1.1 + Q1.3` and `GND` containing `J1.2`, `J2.2`, and `Q1.1`.

`kicad-cli sch export netlist` of the same file does not. Evidence: `evidence\kicad-cli-netlist.net`.

| Net | KiCad 10 nodes | Specified circuit |
| --- | --- | --- |
| `+5V` | J1 pin 1, R1 pin 2 | J1 pin 1, R1 pin 1 |
| `/LED_A` | D1 pin 2 (anode), R1 pin 1 | D1 anode, R1 pin 2 |
| `/LED_K` | D1 pin 1 (cathode), Q1 pin 1 (emitter) | D1 cathode, Q1 pin 3 (collector) |
| `GND` | Q1 pin 3 (collector), R3 pin 1 | J1 pin 2, J2 pin 2, Q1 pin 1 (emitter), R3 pin 2 |
| `/CTRL_IN` | J2 pin 1, R2 pin 2 | J2 pin 1, R2 pin 1 |
| `/BASE` | Q1 pin 2 (base), R2 pin 1, R3 pin 2 | Q1 base, R2 pin 2, R3 pin 1 |
| unconnected | J1 pin 2, J2 pin 2 | both on GND |

Resistor ends are swapped and the two-terminal parts still join the right pair of nets. LED polarity is correct because those pins differ in X, not Y. The transistor is reversed: the cathode lands on the emitter and GND lands on the collector. Both connector ground pins are unconnected.

Cause: `PinLocator.get_pin_location` uses `abs_y = symbol_y + pin_rel_y`. KiCad places that pin at `symbol_y - pin_rel_y`. J1 is at (39.37, 39.37). Its pin 2 is at local (−5.08, −2.54). The wire was drawn at y = 36.83. KiCad’s pin is at y = 41.91. The same mirror swaps Q1 emitter and collector. This was not patched.

## ERC

`run_erc` returned `ERC complete: 0 violation(s)` and `success: true`. The handler only reads a top-level `violations` array (`kicad_interface.py` around the ERC JSON load). The KiCad 10.0.5 report stores violations in `sheets[].violations` and still exits 0.

Direct `kicad-cli sch erc` found 11 violations (`evidence\erc-kicad-cli.json`): three errors and eight warnings. One error was `#PWR02` input power not driven. A second `PWR_FLAG` was added with `add_schematic_component` and `connect_to_net`. The following CLI report has 10 violations (`evidence\erc-after-gnd-flag.json`):

- Error: J1 pin 2 not connected.
- Error: J2 pin 2 not connected.
- Warning: unconnected wire endpoint at each of those stub positions.
- Warning: embedded `Conn_01x02`, `R`, and `LED` symbols do not match the KiCad 10 libraries. Q1 was not in that list.

The power-flag error is gone. The open connector pins and the reversed transistor remain. Those are electrical failures, not a warning-count problem. Schematic wiring was not continued through another mechanism.

## PCB

`sync_schematic_to_board` on `MCP-E2E-LED.kicad_pcb` returned `name 'pcbnew' is not defined`. In IPC mode the `pcbnew` import is skipped, and that import is not module-global. The handler at `LoadBoard` therefore cannot run.

The same handler, once past that line, walks `board.GetFootprints()` and assigns nets. It does not add footprints from the schematic. `create_project` had written an empty board of 2196 bytes. That file was not given the seven footprints, and no other placement command was used. Stages 5 and 6 were not started. No Gerber, Excellon, BOM, or position file was produced. The schematic PDF at `evidence\MCP-E2E-LED.pdf` is 49970 bytes. It is a picture of the failed schematic, not a manufacturing output.

## Evidence

| File | Contents |
| --- | --- |
| `MCP-E2E-LED\evidence\calls.jsonl` | Handler name, parameters, and response, including the GND-flag follow-up |
| `MCP-E2E-LED\evidence\summary.json` | Open-document path, protected-board hashes, stop point |
| `MCP-E2E-LED\evidence\erc-kicad-cli.json` | First direct ERC, 11 violations |
| `MCP-E2E-LED\evidence\erc-after-gnd-flag.json` | ERC after the extra power flag, 10 violations |
| `MCP-E2E-LED\evidence\kicad-cli-netlist.net` | KiCad netlist used for the connectivity table |
| `MCP-E2E-LED\evidence\MCP-E2E-LED.pdf` | Schematic PDF, 49970 bytes |
| `MCP-E2E-LED\MCP-E2E-LED.kicad_sch` | Schematic under test, 47871 bytes before the extra flag |
| `MCP-E2E-LED\MCP-E2E-LED.kicad_pcb` | Empty board, 2196 bytes |

## Separation of actions

- MCP handlers: `create_project`, `add_schematic_component`, `list_schematic_components`, `get_schematic_pin_locations`, `connect_to_net`, `list_schematic_wires`, `list_schematic_labels`, `generate_netlist`, `run_erc`, `sync_schematic_to_board`, `export_schematic_pdf`.
- External KiCad CLI, not counted as an MCP success: `sch erc` and `sch export netlist`. `export_schematic_pdf` also shells out to `kicad-cli`.
- Manual edits: none. The schematic was not hand-corrected, and `add_schematic_wire` was not used in place of `connect_to_net`.
