"""Build a fresh LED-switch schematic and check it with kicad-cli.

Does not modify MCP-E2E-LED or any IPM board. Does not synchronise a PCB.
"""

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

os.environ["KICAD_BACKEND"] = "swig"
os.environ["KICAD_AUTO_LAUNCH"] = "false"
for name in ("KICAD_SYMBOL_DIR", "KICAD10_SYMBOL_DIR", "KICAD9_SYMBOL_DIR", "KICAD8_SYMBOL_DIR"):
    os.environ.pop(name, None)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

PROJECT = Path(r"C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED-P7A")
EVIDENCE = PROJECT / "evidence"
KICAD_CLI = Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe")

BLANK = """(kicad_sch (version 20250114) (generator "KiCAD-MCP-Server")
  (uuid {uuid})
  (paper "A4")
  (lib_symbols
  )
  (sheet_instances
    (path "/" (page "1"))
  )
)
"""


def write_blank(path: Path) -> None:
    path.write_text(BLANK.format(uuid=uuid.uuid4()), encoding="utf-8")


def net_map(path: Path) -> dict:
    import sexpdata
    from sexpdata import Symbol

    data = sexpdata.loads(path.read_text(encoding="utf-8"))

    def find_nets(node):
        if not isinstance(node, list):
            return None
        if node and node[0] == Symbol("nets"):
            return node
        for child in node:
            found = find_nets(child)
            if found is not None:
                return found
        return None

    nets = {}
    for item in find_nets(data)[1:]:
        if not (isinstance(item, list) and item and item[0] == Symbol("net")):
            continue
        name = None
        nodes = set()
        for part in item[1:]:
            if isinstance(part, list) and part and part[0] == Symbol("name"):
                name = str(part[1]).strip('"')
            elif isinstance(part, list) and part and part[0] == Symbol("node"):
                ref = pin = None
                for field in part[1:]:
                    if isinstance(field, list) and field and field[0] == Symbol("ref"):
                        ref = str(field[1]).strip('"')
                    elif isinstance(field, list) and field and field[0] == Symbol("pin"):
                        pin = str(field[1]).strip('"')
                if ref and pin:
                    nodes.add(f"{ref}.{pin}")
        nets[name] = nodes
    return nets


def node_net(nets: dict, node: str):
    for name, nodes in nets.items():
        if node in nodes:
            return name
    return None


def export_netlist(schematic: Path, output: Path) -> None:
    completed = subprocess.run(
        [
            str(KICAD_CLI),
            "sch",
            "export",
            "netlist",
            "--format",
            "kicadsexpr",
            "--output",
            str(output),
            str(schematic),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(completed.stderr or completed.stdout or "netlist export failed")


def main() -> int:
    from commands.connection_schematic import ConnectionManager
    from commands.dynamic_symbol_loader import DynamicSymbolLoader
    from kicad_interface import KiCADInterface

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    loader = DynamicSymbolLoader()
    failures = []

    geometry = PROJECT / "geometry.kicad_sch"
    write_blank(geometry)
    parts = [
        ("R0", 50.8, 50.8, 0, None),
        ("R90", 88.9, 50.8, 90, None),
        ("R180", 127.0, 50.8, 180, None),
        ("R270", 165.1, 50.8, 270, None),
        ("RMX", 50.8, 88.9, 0, "x"),
        ("RMY", 88.9, 88.9, 0, "y"),
    ]
    for reference, x, y, rotation, mirror in parts:
        loader.add_component(
            geometry, "Device", "R", reference, "1k", "", x, y,
            rotation=rotation, mirror=mirror,
        )
        for pin, suffix in (("1", "A"), ("2", "B")):
            ok = ConnectionManager.connect_to_net(
                geometry, reference, pin, f"{reference}_{suffix}"
            )
            if not ok:
                failures.append(f"geometry wire failed for {reference} pin {pin}")

    geometry_netlist = EVIDENCE / "geometry.net"
    export_netlist(geometry, geometry_netlist)
    geometry_nets = net_map(geometry_netlist)
    geometry_result = {}
    for reference, *_rest in parts:
        pin1 = node_net(geometry_nets, f"{reference}.1")
        pin2 = node_net(geometry_nets, f"{reference}.2")
        geometry_result[reference] = {"pin1": pin1, "pin2": pin2}
        if pin1 is None or f"{reference}_A" not in pin1:
            failures.append(f"{reference} pin 1 is on {pin1}, expected {reference}_A")
        if pin2 is None or f"{reference}_B" not in pin2:
            failures.append(f"{reference} pin 2 is on {pin2}, expected {reference}_B")
        if pin1 == pin2:
            failures.append(f"{reference} pins are shorted on {pin1}")

    circuit = PROJECT / "MCP-E2E-LED-P7A.kicad_sch"
    write_blank(circuit)
    circuit_parts = [
        ("Transistor_BJT", "2N3904", "Q1", "2N3904", "Package_TO_SOT_THT:TO-92_Inline", 127.0, 50.8, 0, None),
        ("Device", "LED", "D1", "Red", "LED_SMD:LED_0603_1608Metric", 96.52, 38.1, 0, None),
        ("Device", "R", "R1", "330", "Resistor_SMD:R_0603_1608Metric", 66.04, 38.1, 0, None),
        ("Device", "R", "R2", "4.7k", "Resistor_SMD:R_0603_1608Metric", 96.52, 76.2, 0, None),
        ("Device", "R", "R3", "100k", "Resistor_SMD:R_0603_1608Metric", 127.0, 88.9, 0, None),
        ("Connector_Generic", "Conn_01x02", "J1", "PWR", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", 30.48, 38.1, 0, None),
        ("Connector_Generic", "Conn_01x02", "J2", "CTRL", "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical", 30.48, 76.2, 0, None),
        ("power", "+5V", "#PWR01", "+5V", "", 66.04, 20.32, 0, None),
        ("power", "GND", "#PWR02", "GND", "", 152.4, 101.6, 0, None),
        ("power", "PWR_FLAG", "#FLG01", "PWR_FLAG", "", 81.28, 20.32, 0, None),
        ("power", "PWR_FLAG", "#FLG02", "PWR_FLAG", "", 139.7, 101.6, 0, None),
    ]
    for library, symbol, reference, value, footprint, x, y, rotation, mirror in circuit_parts:
        loader.add_component(
            circuit, library, symbol, reference, value, footprint, x, y,
            rotation=rotation, mirror=mirror,
        )

    connections = [
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
        ("#FLG02", "1", "GND"),
    ]
    for reference, pin, net in connections:
        if not ConnectionManager.connect_to_net(circuit, reference, pin, net):
            failures.append(f"circuit wire failed for {reference} pin {pin}")

    circuit_netlist = EVIDENCE / "led.net"
    export_netlist(circuit, circuit_netlist)
    nets = net_map(circuit_netlist)

    def members(name_part):
        found = set()
        for name, nodes in nets.items():
            if name_part in name:
                found |= nodes
        return found

    plus = members("+5V")
    led_a = members("LED_A")
    led_k = members("LED_K")
    gnd = members("GND")
    ctrl = members("CTRL_IN")
    base = members("BASE")
    observed = {
        "+5V": sorted(plus),
        "LED_A": sorted(led_a),
        "LED_K": sorted(led_k),
        "GND": sorted(gnd),
        "CTRL_IN": sorted(ctrl),
        "BASE": sorted(base),
    }
    if "J1.1" not in plus or not ({"R1.1", "R1.2"} & plus):
        failures.append(f"+5V is {sorted(plus)}")
    if "D1.2" not in led_a or not ({"R1.1", "R1.2"} & led_a):
        failures.append(f"LED anode net is {sorted(led_a)}")
    if plus & led_a:
        failures.append("+5V and LED anode are shorted")
    if "D1.1" not in led_k or "Q1.3" not in led_k or "Q1.1" in led_k:
        failures.append(f"LED cathode net is {sorted(led_k)}")
    if "Q1.1" not in gnd or "Q1.3" in gnd or "J1.2" not in gnd or "J2.2" not in gnd:
        failures.append(f"GND is {sorted(gnd)}")
    if "J2.1" not in ctrl or not ({"R2.1", "R2.2"} & ctrl):
        failures.append(f"CTRL_IN is {sorted(ctrl)}")
    if "Q1.2" not in base or not ({"R2.1", "R2.2"} & base) or not ({"R3.1", "R3.2"} & base):
        failures.append(f"BASE is {sorted(base)}")
    if ({"R2.1", "R2.2"} <= ctrl) or ({"R2.1", "R2.2"} <= base):
        failures.append("R2 does not span CTRL_IN and BASE")
    if ({"R3.1", "R3.2"} <= base) or ({"R3.1", "R3.2"} <= gnd):
        failures.append("R3 does not span BASE and GND")

    interface = KiCADInterface()
    erc = interface.handle_command("run_erc", {"schematicPath": str(circuit)})
    erc_path = EVIDENCE / "erc.json"
    erc_path.write_text(json.dumps(erc, indent=2), encoding="utf-8")
    if not erc.get("success"):
        failures.append(f"ERC command failed: {erc}")
    if erc.get("ercPassed") is not True:
        failures.append(f"ERC did not pass: {erc.get('message')}")
    mismatch = [
        item for item in erc.get("violations", [])
        if item.get("type") == "lib_symbol_mismatch"
    ]
    unconnected = [
        item for item in erc.get("violations", [])
        if item.get("type") in ("pin_not_connected", "unconnected_wire_endpoint")
    ]
    if mismatch:
        failures.append(f"library symbol mismatches: {len(mismatch)}")
    if unconnected:
        failures.append(f"unconnected items: {len(unconnected)}")

    summary = {
        "geometry": geometry_result,
        "circuitNets": observed,
        "erc": {
            "success": erc.get("success"),
            "ercPassed": erc.get("ercPassed"),
            "message": erc.get("message"),
            "exitCode": erc.get("exitCode"),
            "kicadVersion": erc.get("kicadVersion"),
        },
        "failures": failures,
    }
    (EVIDENCE / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
