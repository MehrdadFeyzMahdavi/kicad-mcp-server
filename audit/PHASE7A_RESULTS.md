# Phase 7A — Schematic correctness

The schematic engine now produces the LED switch that KiCad 10 accepts. PCB synchronisation and routing were not started. The Phase 6 project `MCP-E2E-LED` was left unchanged.

Fresh project: `C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7A`.

## What was wrong

- Symbol search looked at KiCad 8 and 9 only. `Transistor_BJT:2N3904` was not found until `KICAD_SYMBOL_DIR` was set by hand.
- `PinLocator` added library Y to the sheet Y. Sheet Y increases downward and library Y increases upward, so vertical pins were mirrored. KiCad connected the collector to GND and left both connector ground pins open.
- `connect_to_net` drew its stub from that mirrored point, then grid-snapped the endpoint.
- `run_erc` read a top-level `violations` array. KiCad 10 stores them in `sheets[].violations` and exits 0, so the handler reported zero violations.
- The project template already contained compacted `Device:R`, `Device:LED`, and `Connector_Generic:Conn_01x02` symbols. Injection treated those names as present and kept the old definitions. ERC reported `lib_symbol_mismatch`. `2N3904` was not in the template, so it was copied from the library and did not warn.

## What changed

- Library search now checks `KICAD_SYMBOL_DIR`, `KICAD10_SYMBOL_DIR`, the directory beside the running KiCad Python, and installed KiCad 10, 9, and 8 trees, newest first. A missing symbol still returns no definition.
- Pin placement mirrors, rotates counterclockwise in the library frame, then subtracts Y. The same transform is used for the stub direction and for the internal schematic ERC pin check. Symbol unit and body style select which pins are used.
- Wire and label endpoints written by `connect_to_net` are not snapped off the pin.
- ERC parsing reads `sheets[].violations`, and the older top-level array when there is no `sheets` key. `success` means the report was read. `ercPassed` means the error count is zero. The process exit code is recorded and is not treated as the violation count.
- Adding a symbol replaces an embedded definition when it differs from the installed library. The replacement is the library symbol, including its pins and properties.

## KiCad 10 check

`audit/phase7a_verify.py` built two new schematics without `KICAD_SYMBOL_DIR` set. `kicad-cli` 10.0.5 exported the netlists.

Rotation and mirror, each pin on its own net:

| Symbol | Rotation | Mirror | Pin 1 | Pin 2 |
| --- | --- | --- | --- | --- |
| R0 | 0 | | `/R0_A` | `/R0_B` |
| R90 | 90 | | `/R90_A` | `/R90_B` |
| R180 | 180 | | `/R180_A` | `/R180_B` |
| R270 | 270 | | `/R270_A` | `/R270_B` |
| RMX | 0 | x | `/RMX_A` | `/RMX_B` |
| RMY | 0 | y | `/RMY_A` | `/RMY_B` |

LED switch nets from `evidence/led.net`:

| Net | KiCad nodes |
| --- | --- |
| `+5V` | J1.1, R1.1 |
| `/LED_A` | D1.2 anode, R1.2 |
| `/LED_K` | D1.1 cathode, Q1.3 collector |
| `GND` | J1.2, J2.2, Q1.1 emitter, R3.2 |
| `/CTRL_IN` | J2.1, R2.1 |
| `/BASE` | Q1.2 base, R2.2, R3.1 |

`run_erc` returned `ERC complete: 0 error(s), 0 warning(s)`, `ercPassed: true`, KiCad version 10.0.5. There is no `lib_symbol_mismatch`, no unconnected pin, and no dangling wire. The report is `MCP-E2E-LED-P7A/evidence/erc.json`.

Unit tests in `python/tests/test_phase7_schematic.py`: 7 passed.
