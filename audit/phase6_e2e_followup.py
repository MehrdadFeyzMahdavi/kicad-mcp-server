"""Add the missing GND power flag through the existing command, then re-check ERC."""

import json
import os
import subprocess
import sys
from pathlib import Path

os.environ["KICAD_BACKEND"] = "ipc"
os.environ["KICAD_AUTO_LAUNCH"] = "false"
os.environ["KICAD_SYMBOL_DIR"] = r"C:\Program Files\KiCad\10.0\share\kicad\symbols"
kicad_bin = Path(r"C:\Program Files\KiCad\10.0\bin")
os.environ["PATH"] = str(kicad_bin) + os.pathsep + os.environ.get("PATH", "")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "python"))

PROJECT = Path(r"C:\Users\mehrdad.f.mahdavi\Projects\KiCad\MCP-E2E-LED")
SCHEMATIC = PROJECT / "MCP-E2E-LED.kicad_sch"
EVIDENCE = PROJECT / "evidence"
LOG = EVIDENCE / "calls.jsonl"


def main() -> int:
    from kicad_interface import KiCADInterface

    interface = KiCADInterface()

    def call(name, params):
        result = interface.handle_command(name, params)
        with LOG.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"command": name, "params": params, "response": result}, default=str) + "\n")
        print(name, json.dumps(result, default=str)[:400], flush=True)
        return result

    placed = call(
        "add_schematic_component",
        {
            "schematicPath": str(SCHEMATIC),
            "component": {
                "library": "power",
                "type": "PWR_FLAG",
                "reference": "#FLG02",
                "value": "PWR_FLAG",
                "footprint": "",
                "x": 175.0,
                "y": 100.0,
            },
        },
    )
    if not placed.get("success"):
        return 1
    connected = call(
        "connect_to_net",
        {
            "schematicPath": str(SCHEMATIC),
            "componentRef": "#FLG02",
            "pinName": "1",
            "netName": "GND",
        },
    )
    if not connected.get("success"):
        return 1
    erc_path = EVIDENCE / "erc-after-gnd-flag.json"
    completed = subprocess.run(
        [
            str(kicad_bin / "kicad-cli.exe"),
            "sch",
            "erc",
            "--format",
            "json",
            "--output",
            str(erc_path),
            str(SCHEMATIC),
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    print(completed.stdout)
    print(completed.stderr)
    report = json.loads(erc_path.read_text(encoding="utf-8"))
    violations = report["sheets"][0]["violations"]
    print("remaining", len(violations))
    for item in violations:
        print(item["severity"], item["type"], item["description"])
    pdf = call(
        "export_schematic_pdf",
        {
            "schematicPath": str(SCHEMATIC),
            "outputPath": str(EVIDENCE / "MCP-E2E-LED.pdf"),
        },
    )
    pdf_path = EVIDENCE / "MCP-E2E-LED.pdf"
    print("pdf_bytes", pdf_path.stat().st_size if pdf_path.exists() else 0, "success", pdf.get("success"))
    return 0 if completed.returncode == 0 else completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
