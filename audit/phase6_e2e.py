"""Phase 6 end-to-end run. Creates only MCP-E2E-LED and never writes an IPM file."""

import hashlib
import json
import os
import sys
import traceback
from pathlib import Path

os.environ["KICAD_BACKEND"] = "ipc"
os.environ["KICAD_AUTO_LAUNCH"] = "false"
os.environ["KICAD_SYMBOL_DIR"] = r"C:\Program Files\KiCad\10.0\share\kicad\symbols"
kicad_bin = Path(r"C:\Program Files\KiCad\10.0\bin")
os.environ["PATH"] = str(kicad_bin) + os.pathsep + os.environ.get("PATH", "")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

PROJECT_DIR = Path(r"C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED")
PROJECT_NAME = "MCP-E2E-LED"
EVIDENCE = PROJECT_DIR / "evidence"
PHASE3 = Path(r"C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\ipc-phase3-test.kicad_pcb")
ORIGINAL = Path(r"C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\ipc-move-test.kicad_pcb")
IPM_PCB = Path(r"C:\Users\mehrdad.f.mahdavi\Desktop\IPM\IPM\IPM.kicad_pcb")

COMPONENTS = [
    ("Transistor_BJT", "2N3904", "Q1", "2N3904", "Package_TO_SOT_THT:TO-92_Inline", 140.0, 60.0),
    ("Device", "LED", "D1", "Red", "LED_SMD:LED_0603_1608Metric", 110.0, 40.0),
    ("Device", "R", "R1", "330", "Resistor_SMD:R_0603_1608Metric", 80.0, 40.0),
    ("Device", "R", "R2", "4.7k", "Resistor_SMD:R_0603_1608Metric", 100.0, 75.0),
    ("Device", "R", "R3", "100k", "Resistor_SMD:R_0603_1608Metric", 140.0, 90.0),
    ("Connector_Generic", "Conn_01x02", "J1", "PWR", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", 40.0, 40.0),
    ("Connector_Generic", "Conn_01x02", "J2", "CTRL", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", 40.0, 80.0),
    ("power", "+5V", "#PWR01", "+5V", "", 60.0, 25.0),
    ("power", "GND", "#PWR02", "GND", "", 160.0, 100.0),
    ("power", "PWR_FLAG", "#FLG01", "PWR_FLAG", "", 70.0, 25.0),
]

# Pin numbers verified from the KiCad 10 symbol files before this run.
CONNECTIONS = [
    ("J1", "1", "+5V"),
    ("R1", "1", "+5V"),
    ("#PWR01", "1", "+5V"),
    ("#FLG01", "1", "+5V"),
    ("R1", "2", "LED_A"),
    ("D1", "2", "LED_A"),
    ("D1", "1", "LED_K"),
    ("Q1", "3", "LED_K"),
    ("J2", "1", "CTRL_IN"),
    ("R2", "1", "CTRL_IN"),
    ("R2", "2", "BASE"),
    ("R3", "1", "BASE"),
    ("Q1", "2", "BASE"),
    ("J1", "2", "GND"),
    ("J2", "2", "GND"),
    ("Q1", "1", "GND"),
    ("R3", "2", "GND"),
    ("#PWR02", "1", "GND"),
]


def stamp(path: Path) -> dict:
    if not path.exists():
        return {"path": str(path), "exists": False}
    data = path.read_bytes()
    stat = path.stat()
    return {
        "path": str(path),
        "exists": True,
        "size": stat.st_size,
        "mtime": stat.st_mtime,
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def main() -> int:
    from kicad_interface import KiCADInterface

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    log_path = EVIDENCE / "calls.jsonl"
    log_path.write_text("", encoding="utf-8")
    summary = {"calls": [], "failures": [], "stopped": None, "error": None}
    interface = KiCADInterface()

    def record(name, params, result):
        entry = {"command": name, "params": params, "response": result}
        summary["calls"].append(entry)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, default=str) + "\n")
        print(name, json.dumps(result, default=str)[:500], flush=True)
        return result

    def call(name, params):
        blob = json.dumps(params)
        if "IPM" in blob or "ipc-phase3" in blob or "ipc-move-test" in blob:
            raise RuntimeError(f"Refusing {name}: parameters mention a protected board")
        return record(name, params, interface.handle_command(name, params))

    def fail(message):
        summary["failures"].append(message)
        print("FAIL", message, flush=True)

    try:
        open_paths = [str(Path(path).resolve()) for path in interface.ipc_board_api._open_pcb_paths()]
        protected_before = {
            "phase3": stamp(PHASE3),
            "original": stamp(ORIGINAL),
            "ipm": stamp(IPM_PCB),
        }
        record(
            "discovery_open_document",
            {},
            {"openPaths": open_paths, "protected": protected_before},
        )
        if open_paths != [str(PHASE3.resolve())]:
            raise RuntimeError(f"Unexpected open PCB documents: {open_paths}")

        created = call("create_project", {"path": str(PROJECT_DIR), "name": PROJECT_NAME})
        project_pcb = PROJECT_DIR / f"{PROJECT_NAME}.kicad_pcb"
        schematic = PROJECT_DIR / f"{PROJECT_NAME}.kicad_sch"
        if not created.get("success") or not schematic.is_file() or not project_pcb.is_file():
            summary["stopped"] = "create_project"
            fail(f"Project files were not created: {created}")
            return finish(summary, protected_before)
        if project_pcb.resolve() == PHASE3.resolve():
            raise RuntimeError("create_project targeted the disposable IPM board")

        placed = []
        for library, symbol, reference, value, footprint, x, y in COMPONENTS:
            result = call(
                "add_schematic_component",
                {
                    "schematicPath": str(schematic),
                    "component": {
                        "library": library,
                        "type": symbol,
                        "reference": reference,
                        "value": value,
                        "footprint": footprint,
                        "x": x,
                        "y": y,
                    },
                },
            )
            placed.append(result)
            if not result.get("success"):
                summary["stopped"] = "add_schematic_component"
                fail(f"{reference} was not added: {result}")
                return finish(summary, protected_before)

        listed = call("list_schematic_components", {"schematicPath": str(schematic)})
        by_ref = {item.get("reference"): item for item in listed.get("components", [])}
        record("schematic_readback", {}, {"components": by_ref})
        for library, symbol, reference, value, footprint, _x, _y in COMPONENTS:
            item = by_ref.get(reference)
            expected_lib = f"{library}:{symbol}"
            if item is None or item.get("value") != value or expected_lib not in item.get("libId", ""):
                summary["stopped"] = "schematic_readback"
                fail(f"Read-back mismatch for {reference}: {item}")
                return finish(summary, protected_before)
            if footprint and item.get("footprint") != footprint:
                summary["stopped"] = "footprint_readback"
                fail(f"Footprint mismatch for {reference}: {item.get('footprint')}")
                return finish(summary, protected_before)

        pins = {}
        for _library, _symbol, reference, _value, _footprint, _x, _y in COMPONENTS:
            located = call(
                "get_schematic_pin_locations",
                {"schematicPath": str(schematic), "reference": reference},
            )
            pins[reference] = located
            if not located.get("success"):
                summary["stopped"] = "pin_locations"
                fail(f"Pins for {reference} were not readable: {located}")
                return finish(summary, protected_before)

        required = {
            "Q1": {"1": "E", "2": "B", "3": "C"},
            "D1": {"1": "K", "2": "A"},
        }
        pin_map = {}
        for reference, expected in required.items():
            reported = pins[reference].get("pins", pins[reference])
            pin_map[reference] = reported
            for number, name in expected.items():
                entry = reported.get(number) if isinstance(reported, dict) else None
                actual_name = entry.get("name") if isinstance(entry, dict) else None
                if actual_name != name:
                    summary["stopped"] = "pin_verification"
                    fail(f"{reference} pin {number} is {actual_name}, expected {name}")
                    return finish(summary, protected_before)

        for reference, pin_name, net_name in CONNECTIONS:
            result = call(
                "connect_to_net",
                {
                    "schematicPath": str(schematic),
                    "componentRef": reference,
                    "pinName": pin_name,
                    "netName": net_name,
                },
            )
            if not result.get("success"):
                summary["stopped"] = "connect_to_net"
                fail(f"Wiring stopped at {reference} pin {pin_name}: {result}")
                return finish(summary, protected_before)

        wires = call("list_schematic_wires", {"schematicPath": str(schematic)})
        labels = call("list_schematic_labels", {"schematicPath": str(schematic)})
        netlist = call("generate_netlist", {"schematicPath": str(schematic)})
        erc = call("run_erc", {"schematicPath": str(schematic)})
        record(
            "connectivity_readback",
            {},
            {
                "wireCount": wires.get("count", len(wires.get("wires", []) or [])),
                "labelCount": labels.get("count", len(labels.get("labels", []) or [])),
                "netlist": netlist,
                "erc": erc,
            },
        )

        net_body = netlist.get("netlist") if isinstance(netlist.get("netlist"), dict) else {}
        nets = {}
        for entry in net_body.get("nets", []):
            members = tuple(
                sorted(
                    f"{item.get('component')}.{item.get('pin')}"
                    for item in entry.get("connections", [])
                )
            )
            nets[entry.get("name")] = members
        record("parsed_nets", {}, {key: list(value) for key, value in nets.items()})

        expected = {
            "+5V": {"J1.1", "R1.1"},
            "LED_A": {"R1.2", "D1.2"},
            "LED_K": {"D1.1", "Q1.3"},
            "CTRL_IN": {"J2.1", "R2.1"},
            "BASE": {"R2.2", "R3.1", "Q1.2"},
            "GND": {"J1.2", "J2.2", "Q1.1", "R3.2"},
        }
        parsed_ok = True
        for name, members in expected.items():
            actual = set(nets.get(name, ()))
            if not members.issubset(actual):
                parsed_ok = False
                fail(f"Net {name} read-back {sorted(actual)} does not contain {sorted(members)}")
        if not parsed_ok or not netlist.get("success"):
            summary["stopped"] = "netlist_verification"
            return finish(summary, protected_before)

        erc_errors = [
            item for item in erc.get("violations", []) if item.get("severity") == "error"
        ]
        record("erc_errors", {}, {"count": len(erc_errors), "errors": erc_errors})

        synced = call(
            "sync_schematic_to_board",
            {"schematicPath": str(schematic), "boardPath": str(project_pcb)},
        )
        record("pcb_after_sync_exists", {}, {"size": project_pcb.stat().st_size})
        if not synced.get("success"):
            summary["stopped"] = "sync_schematic_to_board"
            fail(f"Schematic synchronisation failed: {synced}")
            return finish(summary, protected_before)

        summary["stopped"] = "sync_completed_needs_footprint_verification"
    except Exception as exc:
        summary["error"] = {"type": type(exc).__name__, "message": str(exc), "trace": traceback.format_exc()}
        traceback.print_exc()
    return finish(summary, locals().get("protected_before", {}))


def finish(summary, protected_before) -> int:
    protected_after = {
        "phase3": stamp(PHASE3),
        "original": stamp(ORIGINAL),
        "ipm": stamp(IPM_PCB),
    }
    summary["protectedUnchanged"] = protected_after == protected_before
    summary["protectedAfter"] = protected_after
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print("STOPPED", summary.get("stopped"), "failures", len(summary["failures"]), flush=True)
    return 0 if summary.get("protectedUnchanged") else 2


if __name__ == "__main__":
    raise SystemExit(main())
