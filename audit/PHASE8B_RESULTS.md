# Phase 8B — Net-aware PCB routing

Status: **PASS** for connectivity of the six nets on the placed Phase 8A board. KiCad 10.0.5 DRC reports 0 unconnected items, 0 schematic parity issues, and no short, clearance, or tracks-crossing violations. Two `lib_footprint_mismatch` warnings remain. They are library serialization differences. Pad numbers, pad geometry, and pad nets were left unchanged.

This is not an autorouter. `route_pad_to_pad` returns `optimised: false`. Each link is one direct segment, one orthogonal bend, or a short escape. Gerbers were not exported. No copper zones were added.

The open board was `C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7B-PROJECT\MCP-E2E-LED-P7B.kicad_pcb`. Every copper change went through KiCad IPC (`begin_commit` / `push_commit` / `drop_commit`) and was read back. The file was then saved with IPC `SaveDocument`. `pcbnew.SaveBoard` was not used. The Phase 8A placement engine was not modified.

Versions measured in this run: `pcbnew.GetBuildVersion()` and `kicad-cli` report **10.0.5**.

## Footprint warnings

DRC type `lib_footprint_mismatch`:

| Ref | Board and schematic library id | Library |
| --- | --- | --- |
| D1 | `LED_SMD:LED_0603_1608Metric` | `C:\Program Files\KiCad\10.0\share\kicad\footprints\LED_SMD.pretty` |
| Q1 | `Package_TO_SOT_THT:TO-92_Inline` | `C:\Program Files\KiCad\10.0\share\kicad\footprints\Package_TO_SOT_THT.pretty` |

The identifiers on the PCB match the schematic assignments and the installed KiCad 10 libraries. `FootprintNeedsUpdate` is true for both. After undoing the 180° placement, pad numbers, local positions, copper sizes, and drills match the library (`pads_equal` true). Graphic polylines match except coordinates that differ by about 1 nm. Both board footprints omit the library 3D model. D1 also carries empty Datasheet and Description properties that the `.kicad_mod` does not.

Adding only the 3D model on a copy left `FootprintNeedsUpdate` true and left both DRC warnings in place. A full library replace on a copy cleared the warning and kept pad number, net, position, size, and drill, and it also rewrote the graphic coordinates. That replace was not applied to the open board, because the requested fix must not change geometry. There is no KiCad 10 IPC command that reloads a footprint from its library. The two warnings are still present after routing. Re-run DRC shows exactly those two warnings and 0 schematic parity issues.

## Routing architecture

KiCad 10 IPC can create a track with `CreateItems(Track)` inside a commit. It has no route or autoroute command, and none was invented. `kicad-cli pcb drc` checks the saved board. `kicad-cli` does not route. The existing Freerouting DSN/SES path writes a board file offline and was not used.

`route_pad_to_pad` is IPC-only:

- `IPC_CAPABLE_COMMANDS` maps it to `_ipc_route_pad_to_pad`.
- The offline command map maps it to `_refuse_offline_route`, which returns `IPC_UNAVAILABLE`, sets `_keep_backend`, and does not write the file.
- The older SWIG method in `python/commands/routing.py` is no longer called. That method could insert a via when footprint layers differed. The IPC path does not insert vias. It routes on the requested copper layer, `F.Cu` or `B.Cu`.

`route_trace` remains the lower-level XY segment tool and still requires an existing net. KiCad 10 IPC cannot create nets. A missing net returns `NET_NOT_FOUND` and adds no track.

Before any commit, `validate_connection` checks:

1. Both pads exist (`MISSING_PAD`).
2. Both pads already belong to the requested net (`NET_MISMATCH`).
3. The net name is the same at both ends.
4. The layer is `F.Cu` or `B.Cu` (`UNSUPPORTED_LAYER`).
5. The width is from 0.20 mm to 5.00 mm (`INVALID_WIDTH`).
6. The pads are not already joined by same-net copper within 0.05 mm (`DUPLICATE_CONNECTION`).
7. A candidate path stays inside Edge.Cuts and stays clear of other-net pad copper and other-net tracks (`CLEARANCE_CONFLICT`).

A rejected request creates no track. Clearance is an axis-aligned box: pad copper, or the track segment, inflated by the requested clearance plus half the new width (and half the existing width for a track). The same-net endpoint pads are excluded. Touching the inflated boundary is allowed. A 90° or 270° pad swaps width and height. The check is not an exact pad polygon, courtyard, or zone test.

The strategy tries a direct segment, then one orthogonal bend, then a short escape in four directions from each pad. The shortest clear candidate is used. If none are clear, the result is `CLEARANCE_CONFLICT` and `segments: []`.

## Net-to-pad connections

All nine links are on `F.Cu`. Signal width is 0.25 mm. `+5V` and `GND` are 0.40 mm. Clearance is 0.20 mm, the board default netclass clearance. `m_TrackMinWidth` is 0.20 mm.

| Net | From | To | Kind | Segments | Length mm |
| --- | --- | --- | ---: | ---: | ---: |
| `+5V` | J1.1 | R1.1 | direct | 1 | 3.4250 |
| `/LED_A` | R1.2 | D1.2 | direct | 1 | 2.3475 |
| `/LED_K` | D1.1 | Q1.3 | direct | 1 | 3.1525 |
| `/CTRL_IN` | J2.1 | R2.1 | direct | 1 | 3.4250 |
| `/BASE` | R2.2 | R3.1 | direct | 1 | 2.3100 |
| `/BASE` | R3.1 | Q1.2 | escape | 4 | 13.1250 |
| `GND` | J1.2 | J2.2 | escape | 4 | 9.9900 |
| `GND` | J2.2 | R3.2 | bend | 2 | 11.5750 |
| `GND` | R3.2 | Q1.1 | bend | 2 | 12.7450 |

`GND` between the two connectors runs to the left of the headers, centre x = -23.180 mm:

- (-21.730, -13.950) to (-21.730, -12.500)
- (-21.730, -12.500) to (-23.180, -12.500)
- (-23.180, -12.500) to (-23.180, -6.860)
- (-23.180, -6.860) to (-21.730, -6.860)

A first escape put that vertical at x = -20.280 mm, on the right of the headers. DRC then reported `tracks_crossing` between that `GND` segment and the `/CTRL_IN` track. The planner at that point treated only foreign pads as obstacles. All tracks were deleted in one IPC commit, the planner was given foreign tracks as obstacles, and the nine links were created again. The saved board is that second route.

## Track count and read-back

A `pcbnew` load of a temporary copy of the saved board, with no save:

- 17 tracks, 0 vias
- every track on `F.Cu`
- nets present: `+5V`, `GND`, `/LED_A`, `/LED_K`, `/CTRL_IN`, `/BASE`
- total length 62.095 mm
- the seven footprints are still at the Phase 8A anchors and rotations
- all 15 pad nets still match the table above

Per-net length: `+5V` 3.425 mm (1), `/LED_A` 2.3475 mm (1), `/LED_K` 3.1525 mm (1), `/CTRL_IN` 3.425 mm (1), `/BASE` 15.435 mm (5), `GND` 34.310 mm (8).

Unrouted connections reported by DRC: **0**.

## DRC

`kicad-cli pcb drc --schematic-parity --format json --severity-error --severity-warning` (no `--save-board`, no `--refill-zones`):

- kicad_version 10.0.5
- violations: 2, both warnings, both `lib_footprint_mismatch` (D1, Q1)
- unconnected items: 0
- schematic parity issues: 0
- exit code 0

Report: `C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7B-PROJECT\evidence\phase8b-drc.json` (2026-11-01T15:59:32). Render: `evidence\phase8b-routed.png`.

## Live IPC evidence

The only open PCB was the project board above. The PCB editor was the active frame.

Before any copper was added, these requests were rejected and the track count stayed 0:

- J1.1 to R1.1 requested as `GND` → `NET_MISMATCH`
- Q1 pad 9 → `MISSING_PAD`
- width 0 → `INVALID_WIDTH`
- layer `F.SilkS` → `UNSUPPORTED_LAYER`

The nine links were then created, read back, and a second request for J1.1–R1.1 on `+5V` returned `DUPLICATE_CONNECTION`. After the crossing repair, IPC `get_tracks` returned 17 tracks whose nets, widths, and endpoints matched the committed segments. `save()` returned true (`SaveDocument`).

Saved board sha256 `028568fa54de6a2750acdf158ba66c34f3849a6685d7b2051d26a91903cfdc26`, size 31403.

Unchanged files:

| File | sha256 | Size |
| --- | --- | ---: |
| Phase 8A snapshot `MCP-E2E-LED-P8A-PLACED\MCP-E2E-LED-P7B.kicad_pcb` | `aef33a20be27c8d18fce83f5aca155b0cabc32a4a1460ff95cbdf1b90308fc3c` | 28615 |
| Phase 7B baseline PCB | `28c77df5dfb183a6980fc7005385c8552fc46ccc0cff3b05dfa17b1d16e70d42` | 29607 |
| Unlinked `MCP-E2E-LED-P7B\MCP-E2E-LED-P7B.kicad_pcb` | `abcf77545e91bf9e6ebbbb127dd4a82358c6b6a2ced3dcd537119b8768cb9927` | 29607 |
| Phase 7A schematic | `81bb3b9e4e82f919c4305a48f5f57d528f91438c1b28021282f1eb416a2888f0` | 35284 |
| Project schematic (already rewritten by eeschema in Phase 8A) | `cdc63ff855c79e54eadc9f2db214c825fa74b84a8d96b8909098fcb9ab4bdd71` | 38057 |
| `ipc-move-test.kicad_pcb` | `04514a3e851369cee2364171711f0496c63ad3a89a1507cecd9fdbbc1146bbd8` | 1756123 |
| `ipc-phase3-test.kicad_pcb` | `383e481737b4c048c9f87335b48ff0fdb381fb47a816262da09930f7ca3d4996` | 1756093 |
| `IPM.kicad_pcb` | `6f6c38528b90e1326748c1a99027a6d7af1a44209d230b2d09aaf3c884bb50a2` | 1746410 |

## Modified source files

- `python/kicad_api/routing_checks.py` — pad, net, width, layer, duplicate, and clearance checks. No KiCad import.
- `python/kicad_api/ipc_backend.py` — `route_pad_to_pad`, `_commit_route`, read-back, and `delete_tracks`.
- `python/kicad_interface.py` — IPC dispatch and the offline refusal.
- `src/tools/routing.ts` — tool text and schema (`net`, `width`, `boardPath`, `clearance`). The TypeScript server was not rebuilt, so a running MCP process still has the previous schema until it is rebuilt.
- `python/tests/test_phase8b_routing.py` — 10 passed, 0 failed. No KiCad import.
- `python/tests/test_phase8b_kicad10.py` — 2 passed, 0 failed, against KiCad 10.0.5. Loads temporary copies and does not save.

`python/kicad_api/placement.py` was not changed.

## Tests

`test_phase8b_routing.py` covers a valid same-net direct route, a different-net rejection, a missing pad, a duplicate connection, an invalid width, an unsupported layer, a clearance conflict that returns no segments, the nine LED links (the connector `GND` link is not a straight crossing of `/CTRL_IN`), a foreign track that must not be crossed, and a failed check that drops the commit.

`test_phase8b_kicad10.py` loads a copy of the saved board and checks 17 tracks, 0 vias, `F.Cu`, the six net names, the 15 pad nets, and the Phase 8A positions. It also loads the Phase 8A snapshot and checks that snapshot still has no tracks.

## Remaining limitations

- The planner is a fixed set of direct, one-bend, and four-direction escape candidates. It does not push, shove, or search a general path. `optimised` is false.
- Copper layers are `F.Cu` and `B.Cu` only. This operation does not create vias.
- Clearance uses axis-aligned boxes of pad copper and of foreign tracks. It does not use exact pad outlines, courtyards, or zone geometry. Same-net copper may meet at a junction.
- A route requires a net that already exists. KiCad 10 IPC cannot create one.
- The two library-footprint warnings stay until a library replace is allowed to rewrite graphic coordinates by about 1 nm and add the 3D models.
- Track-to-edge checking keeps segment endpoints inside the Edge.Cuts box. DRC reported no edge-clearance violation on this board.
- `route_trace` still maps an unknown layer name to `F.Cu` on the low-level `add_track` path. `route_pad_to_pad` rejects an unknown layer before the commit.
- The TypeScript server was not rebuilt.
