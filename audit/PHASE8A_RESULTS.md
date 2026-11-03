# Phase 8A — PCB layout and placement

Status: **PASS** for the rule-based layout on the linked Phase 7B board. This is not a placement optimiser. `plan_led_switch` returns `optimised: false` and `strategy: led_switch_rules`.

The open board was `C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7B-PROJECT\MCP-E2E-LED-P7B.kicad_pcb`. Every mutation went through KiCad IPC (`begin_commit` / `push_commit` / `drop_commit`) and was read back. The file was then saved with IPC `SaveDocument`. `pcbnew.SaveBoard` was not used. No tracks, zones, or Gerbers were added.

Versions measured in this run: `pcbnew.GetBuildVersion()`, `kicad-cli`, and the live IPC `get_version()` all report **10.0.5**.

## Board outline

One Edge.Cuts rectangle, corners (-25, -20) mm and (25, 20) mm. Width 50 mm, height 40 mm, centre (0, 0). IPC `measure_edge_cuts` and a `pcbnew` load of a copy both read those corners. The stroke is 0.1 mm, so `GetBoardEdgesBoundingBox` is 50.1 × 40.1 mm. That box includes the stroke; the rectangle corners are the outline.

An outline that already exists and does not match this rectangle returns `OUTLINE_CONFLICT` and is left alone. A second rectangle was not added.

## Placement

The seven existing footprints were moved in one undoable commit. Pad nets and sheet paths were compared before and after. D1 and Q1 are at 180 degrees so the LED anode faces R1 and the transistor collector faces D1. The other five stay at 0 degrees. Connectors are on the left. R1, D1, and Q1 continue the +5V / LED / collector chain to the right. R2 and R3 sit on the control-connector row.

Courtyard gap is 1.0 mm. Courtyard-to-edge clearance is 1.5 mm. The first apply used 0.5 mm. That passed the courtyard check, and DRC then reported J1’s reference text clipped by the board edge, because the pin-header reference sits outside the courtyard. The same rule set was applied again at 1.5 mm. The silk-edge warning was gone on the second DRC. Positions below are that second layout.

| Ref | X mm | Y mm | Rotation |
| --- | ---: | ---: | ---: |
| J1 | -21.73 | -16.49 | 0 |
| J2 | -21.73 | -9.40 | 0 |
| R1 | -17.48 | -16.49 | 0 |
| D1 | -13.52 | -16.49 | 180 |
| Q1 | -7.04 | -16.49 | 180 |
| R2 | -17.48 | -9.40 | 0 |
| R3 | -13.52 | -9.40 | 0 |

All 15 pad nets still match the schematic: J1.1 `+5V`, J1.2 `GND`, J2.1 `/CTRL_IN`, J2.2 `GND`, R1.1 `+5V`, R1.2 `/LED_A`, D1.1 `/LED_K`, D1.2 `/LED_A`, Q1.1 `GND`, Q1.2 `/BASE`, Q1.3 `/LED_K`, R2.1 `/CTRL_IN`, R2.2 `/BASE`, R3.1 `/BASE`, R3.2 `GND`. Footprint sheet paths are still `/{sheet uuid}/{symbol tstamp}` for the original seven symbols. Track count is 0.

## Commands

IPC commands, refused offline with `IPC_UNAVAILABLE` and no file write:

- `get_footprint_geometry` — anchor, rotation, pad positions and nets, courtyard AABB, and a body box.
- `check_placement` — outside the board, courtyard overlap, courtyard gap, body overlap, edge clearance, and same-net anchor span.
- `apply_placement` — strategy `led_switch` only. Any other name is `UNSUPPORTED_PLACEMENT`.

Existing `move_component` / `rotate_component` still set an absolute position and angle. A move now fails if the read-back position is off by more than 0.01 mm or the angle by more than 0.05 degrees. `add_board_outline` is unchanged and still creates the rectangle through IPC.

The TypeScript tools are registered in `src/tools/component.ts` and `src/tools/registry.ts`. This run called the Python handlers directly. The TypeScript server was not rebuilt, so a running MCP process will not expose the three new names until it is rebuilt.

## Checks that are implemented

`validate_placement` reports `OUTSIDE_BOARD`, `EDGE_CLEARANCE`, `COURTYARD_OVERLAP`, `COURTYARD_GAP`, `FOOTPRINT_OVERLAP`, `LONG_CONNECTION`, `DUPLICATE_REFERENCE`, and `MISSING_COURTYARD`. Shared edges are not an overlap. An exact required gap passes. `LONG_CONNECTION` is a fixed limit (25 mm between anchors that share a net name). It does not search for a better position.

Courtyard geometry is the axis-aligned box of the F.CrtYd graphics in board coordinates. Q1’s courtyard is four segments; the check uses their bounding box, not the exact polygon. The body used for footprint overlap is the bounding box of pad centres, not the copper polygons. Pad copper overlap is not detected.

## Tests

- `python/tests/test_phase8a_placement.py`: 9 passed, 0 failed. No KiCad import.
- `python/tests/test_phase8a_kicad10.py`: 3 passed, 0 failed, against KiCad 10.0.5. It loads temporary copies of the baseline and of the placed board and does not save.

## DRC and the picture

`kicad-cli pcb drc --schematic-parity --format json` (no `--save-board`, no `--refill-zones`):

- schematic parity: 0
- unconnected items: 9 (expected; the board is not routed)
- other violations: 2 warnings, `lib_footprint_mismatch` on D1 (`LED_0603_1608Metric`) and Q1 (`TO-92_Inline`)
- no `invalid_outline`, no courtyard or silk-edge violations after the 1.5 mm inset

Report: `MCP-E2E-LED-P7B-PROJECT\evidence\phase8a-drc.json`.

Render: `MCP-E2E-LED-P7B-PROJECT\evidence\phase8a-placement.png` (`kicad-cli pcb render`, top side, 1600×900). J1 and J2 are on the left edge with their references inside the rectangle. R1, D1, and Q1 are on the upper row. R2 and R3 are on the lower row. There is no copper routing.

## Files left in place

| File | sha256 | Bytes |
| --- | --- | ---: |
| Project PCB after placement | `aef33a20be27c8d18fce83f5aca155b0cabc32a4a1460ff95cbdf1b90308fc3c` | 28615 |
| Baseline PCB (unchanged grid) | `28c77df5dfb183a6980fc7005385c8552fc46ccc0cff3b05dfa17b1d16e70d42` | 29607 |
| Unlinked Phase 7B PCB | `abcf77545e91bf9e6ebbbb127dd4a82358c6b6a2ced3dcd537119b8768cb9927` | 29607 |
| Phase 7A schematic | `81bb3b9e4e82f919c4305a48f5f57d528f91438c1b28021282f1eb416a2888f0` | 35284 |
| Baseline schematic | `81bb3b9e4e82f919c4305a48f5f57d528f91438c1b28021282f1eb416a2888f0` | 35284 |
| IPM.kicad_pcb | `6f6c38528b90e1326748c1a99027a6d7af1a44209d230b2d09aaf3c884bb50a2` | 1746410 |

`ipc-move-test.kicad_pcb` and `ipc-phase3-test.kicad_pcb` were not opened and still match the hashes recorded before this placement.

The project schematic on disk is no longer byte-identical to the baseline. KiCad’s schematic editor rewrote it at 15:23 (generator `eeschema` 10.0) while that window was open. The exported sexpr netlists match except for the one-second export timestamp. The seven symbol UUIDs and the sheet UUID are still the originals. Placement did not change wires, pins, or pad assignments. The baseline schematic file was not overwritten.

## Not implemented

- A general placer or any search that tries alternate positions. Only the fixed `led_switch` rules.
- Exact courtyard polygons and copper-polygon overlap.
- A silkscreen-geometry clearance check. The 1.5 mm inset is a fixed allowance for reference text, chosen after the 0.5 mm layout clipped J1’s reference.
- Placement of footprints that are not already on the board.
- Routing, copper zones, and Gerber export.
- Offline placement. With no IPC connection the new commands return `IPC_UNAVAILABLE` and do not write the file.

IPC mutations fail with “KiCad is not ready to reply” when the schematic editor is the active frame. The PCB editor has to be the foreground window before `apply_placement` can commit.
