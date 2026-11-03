"""
Pin Locator for KiCad Schematics

Discovers pin locations on symbol instances, accounting for position, rotation, and mirroring.
Uses S-expression parsing to extract pin data from symbol definitions.
"""

import logging
import math
import re
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional, Dict
import sexpdata
from sexpdata import Symbol

logger = logging.getLogger("kicad_interface")


class PinLocator:
    """Locate pins on symbol instances in KiCad schematics"""

    def __init__(self):
        """Initialize pin locator with empty cache"""
        self.pin_definition_cache = {}  # Cache: "lib_id:symbol_name" -> pin_data
        self._schematic_cache: Dict[str, object] = {}  # Cache: path -> loaded Schematic

    @staticmethod
    def parse_symbol_definition(symbol_def: list) -> Dict[str, Dict]:
        """
        Parse a symbol definition from lib_symbols to extract pin information

        Args:
            symbol_def: S-expression list representing symbol definition

        Returns:
            Dictionary mapping pin number -> pin data:
            {
                "1": {"x": 0, "y": 3.81, "angle": 270, "length": 1.27, "name": "~", "type": "passive"},
                "2": {"x": 0, "y": -3.81, "angle": 90, "length": 1.27, "name": "~", "type": "passive"}
            }
        """
        pins = []

        def extract_pins_recursive(sexp, unit=0, style=1):
            """Recursively search for pin definitions in one symbol unit."""
            if not isinstance(sexp, list):
                return

            if (
                len(sexp) > 1
                and sexp[0] == Symbol("symbol")
                and not isinstance(sexp[1], list)
            ):
                match = re.search(r"_(\d+)_(\d+)$", str(sexp[1]).strip('"'))
                if match:
                    unit = int(match.group(1))
                    style = int(match.group(2))

            # Check if this is a pin definition
            if len(sexp) > 0 and sexp[0] == Symbol("pin"):
                # Pin format: (pin type shape (at x y angle) (length len) (name "name") (number "num"))
                pin_data = {
                    "x": 0,
                    "y": 0,
                    "angle": 0,
                    "length": 0,
                    "name": "",
                    "number": "",
                    "type": str(sexp[1]) if len(sexp) > 1 else "passive",
                    "unit": unit,
                    "style": style,
                }

                # Extract pin attributes
                for item in sexp:
                    if isinstance(item, list) and len(item) > 0:
                        if item[0] == Symbol("at") and len(item) >= 3:
                            pin_data["x"] = float(item[1])
                            pin_data["y"] = float(item[2])
                            if len(item) >= 4:
                                pin_data["angle"] = float(item[3])

                        elif item[0] == Symbol("length") and len(item) >= 2:
                            pin_data["length"] = float(item[1])

                        elif item[0] == Symbol("name") and len(item) >= 2:
                            pin_data["name"] = str(item[1]).strip('"')

                        elif item[0] == Symbol("number") and len(item) >= 2:
                            pin_data["number"] = str(item[1]).strip('"')

                if pin_data["number"]:
                    pins.append(pin_data)
                return

            # Recurse into sublists
            for item in sexp:
                if isinstance(item, list):
                    extract_pins_recursive(item, unit, style)

        extract_pins_recursive(symbol_def)
        return pins

    def get_symbol_pins(
        self, schematic_path: Path, lib_id: str, unit: int = 1, style: int = 1
    ) -> Dict[str, Dict]:
        """
        Get pin definitions for a symbol from the schematic's lib_symbols section

        Args:
            schematic_path: Path to .kicad_sch file
            lib_id: Library identifier (e.g., "Device:R", "MCU_ST_STM32F1:STM32F103C8Tx")

        Returns:
            Dictionary mapping pin number -> pin data
        """
        # Check cache
        cache_key = f"{schematic_path}:{lib_id}:{unit}:{style}"
        if cache_key in self.pin_definition_cache:
            logger.debug(f"Using cached pin data for {lib_id}")
            return self.pin_definition_cache[cache_key]

        try:
            # Read schematic
            with open(schematic_path, "r", encoding="utf-8") as f:
                sch_content = f.read()

            sch_data = sexpdata.loads(sch_content)

            # Find lib_symbols section
            lib_symbols = None
            for item in sch_data:
                if (
                    isinstance(item, list)
                    and len(item) > 0
                    and item[0] == Symbol("lib_symbols")
                ):
                    lib_symbols = item
                    break

            if not lib_symbols:
                logger.error("No lib_symbols section found in schematic")
                return {}

            # Find the specific symbol definition
            for item in lib_symbols[1:]:  # Skip 'lib_symbols' itself
                if (
                    isinstance(item, list)
                    and len(item) > 1
                    and item[0] == Symbol("symbol")
                ):
                    symbol_name = str(item[1]).strip('"')
                    if symbol_name == lib_id:
                        # Found the symbol, parse pins
                        pins = self.pins_for_unit(
                            self.parse_symbol_definition(item), unit, style
                        )
                        self.pin_definition_cache[cache_key] = pins
                        logger.info(f"Extracted {len(pins)} pins from {lib_id}")
                        return pins

            logger.warning(f"Symbol {lib_id} not found in lib_symbols")
            return {}

        except Exception as e:
            logger.error(f"Error getting symbol pins: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {}

    @staticmethod
    def rotate_point(x: float, y: float, angle_degrees: float) -> Tuple[float, float]:
        """
        Rotate a point around the origin

        Args:
            x: X coordinate
            y: Y coordinate
            angle_degrees: Rotation angle in degrees (counterclockwise)

        Returns:
            (rotated_x, rotated_y)
        """
        if angle_degrees == 0:
            return (x, y)

        angle_rad = math.radians(angle_degrees)
        cos_a = math.cos(angle_rad)
        sin_a = math.sin(angle_rad)

        rotated_x = x * cos_a - y * sin_a
        rotated_y = x * sin_a + y * cos_a

        return (rotated_x, rotated_y)

    @staticmethod
    def pins_for_unit(pins, unit: int = 1, style: int = 1) -> Dict[str, Dict]:
        """Keep pins for one symbol unit. Unit 0 graphics apply to every unit."""
        selected = [
            pin for pin in pins
            if pin.get("unit") in (0, unit) and pin.get("style", 1) in (1, style)
        ]
        if not any(pin.get("unit") == unit for pin in selected):
            selected = [
                pin for pin in pins
                if pin.get("unit") in (0, unit)
            ]
        chosen: Dict[str, Dict] = {}
        for pin in selected:
            number = pin["number"]
            previous = chosen.get(number)
            if previous is None or pin.get("unit") == unit:
                chosen[number] = pin
        return chosen

    @staticmethod
    def _library_transform(x: float, y: float, rotation: float, mirror: Optional[str]):
        """Mirror and rotate a library point. Library Y increases upward."""
        if mirror == "x":
            y = -y
        elif mirror == "y":
            x = -x
        quarter = int(round(float(rotation or 0))) % 360
        if quarter == 0:
            return x, y
        if quarter == 90:
            return -y, x
        if quarter == 180:
            return -x, -y
        if quarter == 270:
            return y, -x
        radians = math.radians(quarter)
        cosine = math.cos(radians)
        sine = math.sin(radians)
        return x * cosine - y * sine, x * sine + y * cosine

    @staticmethod
    def sheet_pin_position(
        symbol_x: float,
        symbol_y: float,
        rotation: float,
        pin_x: float,
        pin_y: float,
        mirror: Optional[str] = None,
    ) -> Tuple[float, float]:
        """Map a library pin to schematic sheet coordinates.

        Library coordinates have Y upward. The schematic sheet has Y downward,
        so the transformed Y is subtracted from the symbol position. Rotation is
        counterclockwise in the library frame, which is counterclockwise on the
        sheet as well.
        """
        relative_x, relative_y = PinLocator._library_transform(
            float(pin_x), float(pin_y), rotation, mirror
        )
        return (
            round(float(symbol_x) + relative_x, 6),
            round(float(symbol_y) - relative_y, 6),
        )

    @staticmethod
    def sheet_outward_angle(
        pin_angle: float, rotation: float, mirror: Optional[str] = None
    ) -> float:
        """Direction a stub must leave the pin, with 0 = right and 90 = up."""
        outward = (float(pin_angle) + 180.0) % 360.0
        radians = math.radians(outward)
        dx, dy = PinLocator._library_transform(
            math.cos(radians), math.sin(radians), rotation, mirror
        )
        return math.degrees(math.atan2(dy, dx)) % 360.0

    def _load_schematic(self, schematic_path: Path):
        key = str(schematic_path)
        mtime = schematic_path.stat().st_mtime
        cached = self._schematic_cache.get(key)
        if cached and cached[0] == mtime:
            return cached[1]
        with open(schematic_path, "r", encoding="utf-8") as handle:
            data = sexpdata.loads(handle.read())
        self._schematic_cache[key] = (mtime, data)
        self.pin_definition_cache = {
            cache_key: value
            for cache_key, value in self.pin_definition_cache.items()
            if not str(cache_key).startswith(key + ":")
        }
        return data

    @staticmethod
    def _token(value) -> str:
        return str(value).strip('"')

    def _placed_symbol(self, schematic_path: Path, symbol_reference: str) -> Optional[dict]:
        """Read one placed symbol's position, rotation, mirror, and unit."""
        data = self._load_schematic(schematic_path)
        for item in data:
            if not (isinstance(item, list) and item and item[0] == Symbol("symbol")):
                continue
            if len(item) < 2 or not isinstance(item[1], list):
                continue
            info = {
                "lib_id": None,
                "reference": None,
                "x": 0.0,
                "y": 0.0,
                "rotation": 0.0,
                "mirror": None,
                "unit": 1,
                "style": 1,
            }
            for sub in item[1:]:
                if not isinstance(sub, list) or not sub:
                    continue
                if sub[0] == Symbol("lib_id") and len(sub) >= 2:
                    info["lib_id"] = self._token(sub[1])
                elif sub[0] == Symbol("at") and len(sub) >= 3:
                    info["x"] = float(sub[1])
                    info["y"] = float(sub[2])
                    info["rotation"] = float(sub[3]) if len(sub) >= 4 else 0.0
                elif sub[0] == Symbol("mirror") and len(sub) >= 2:
                    info["mirror"] = self._token(sub[1])
                elif sub[0] == Symbol("unit") and len(sub) >= 2:
                    info["unit"] = int(sub[1])
                elif sub[0] == Symbol("body_style") and len(sub) >= 2:
                    info["style"] = int(sub[1])
                elif (
                    sub[0] == Symbol("property")
                    and len(sub) >= 3
                    and self._token(sub[1]) == "Reference"
                ):
                    info["reference"] = self._token(sub[2])
            if info["reference"] == symbol_reference:
                return info
        return None

    def _resolve_pin(self, pins: Dict[str, Dict], pin_number: str) -> Optional[str]:
        if pin_number in pins:
            return pin_number
        return next(
            (num for num, data in pins.items() if data.get("name") == pin_number),
            None,
        )

    def _get_lib_id(self, schematic_path: Path, symbol_reference: str) -> Optional[str]:
        """Helper: return the lib_id string for a placed symbol"""
        placed = self._placed_symbol(schematic_path, symbol_reference)
        return placed.get("lib_id") if placed else None

    def get_pin_angle(
        self, schematic_path: Path, symbol_reference: str, pin_number: str
    ) -> Optional[float]:
        """
        Outward stub direction in degrees. 0 is right and 90 is up on the sheet.
        """
        try:
            placed = self._placed_symbol(schematic_path, symbol_reference)
            if not placed or not placed.get("lib_id"):
                return None
            pins = self.get_symbol_pins(
                schematic_path, placed["lib_id"], placed["unit"], placed["style"]
            )
            resolved = self._resolve_pin(pins, pin_number)
            if resolved is None:
                return None
            return self.sheet_outward_angle(
                pins[resolved].get("angle", 0),
                placed["rotation"],
                placed["mirror"],
            )
        except Exception:
            return None

    def get_pin_location(
        self, schematic_path: Path, symbol_reference: str, pin_number: str
    ) -> Optional[List[float]]:
        """
        Get the absolute location of a pin on a symbol instance

        Args:
            schematic_path: Path to .kicad_sch file
            symbol_reference: Symbol reference designator (e.g., "R1", "U1")
            pin_number: Pin number/identifier (e.g., "1", "2", "GND", "VCC")

        Returns:
            [x, y] absolute coordinates of the pin, or None if not found
        """
        try:
            placed = self._placed_symbol(schematic_path, symbol_reference)
            if not placed:
                logger.error(f"Symbol {symbol_reference} not found in schematic")
                return None
            lib_id = placed.get("lib_id")
            if not lib_id:
                logger.error(f"Symbol {symbol_reference} has no lib_id")
                return None

            pins = self.get_symbol_pins(
                schematic_path, lib_id, placed["unit"], placed["style"]
            )
            if not pins:
                logger.error(f"No pin definitions found for {lib_id}")
                return None

            resolved = self._resolve_pin(pins, pin_number)
            if resolved is None:
                logger.error(
                    f"Pin {pin_number} not found on {symbol_reference}. "
                    f"Available pins: {list(pins.keys())}"
                )
                return None

            pin_data = pins[resolved]
            abs_x, abs_y = self.sheet_pin_position(
                placed["x"],
                placed["y"],
                placed["rotation"],
                pin_data["x"],
                pin_data["y"],
                placed["mirror"],
            )
            logger.info(
                f"Pin {symbol_reference}/{resolved} located at ({abs_x}, {abs_y})"
            )
            return [abs_x, abs_y]

        except Exception as e:
            logger.error(f"Error getting pin location: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return None

    def get_all_symbol_pins(
        self, schematic_path: Path, symbol_reference: str
    ) -> Dict[str, List[float]]:
        """
        Get locations of all pins on a symbol instance

        Args:
            schematic_path: Path to .kicad_sch file
            symbol_reference: Symbol reference designator (e.g., "R1", "U1")

        Returns:
            Dictionary mapping pin number -> [x, y] coordinates
        """
        try:
            placed = self._placed_symbol(schematic_path, symbol_reference)
            if not placed or not placed.get("lib_id"):
                logger.error(f"Symbol {symbol_reference} not found")
                return {}

            pins = self.get_symbol_pins(
                schematic_path, placed["lib_id"], placed["unit"], placed["style"]
            )
            if not pins:
                return {}

            # Calculate location for each pin
            result = {}
            for pin_num in pins.keys():
                location = self.get_pin_location(
                    schematic_path, symbol_reference, pin_num
                )
                if location:
                    result[pin_num] = location

            logger.info(f"Located {len(result)} pins on {symbol_reference}")
            return result

        except Exception as e:
            logger.error(f"Error getting all symbol pins: {e}")
            return {}


if __name__ == "__main__":
    # Test pin location discovery
    import sys

    sys.path.insert(0, "/home/chris/MCP/KiCAD-MCP-Server/python")

    from pathlib import Path
    from commands.component_schematic import ComponentManager
    from commands.schematic import SchematicManager
    import shutil

    print("=" * 80)
    print("PIN LOCATOR TEST")
    print("=" * 80)

    # Create test schematic with components (cross-platform temp directory)
    test_path = Path(tempfile.gettempdir()) / "test_pin_locator.kicad_sch"
    template_path = Path(
        "/home/chris/MCP/KiCAD-MCP-Server/python/templates/template_with_symbols_expanded.kicad_sch"
    )

    shutil.copy(template_path, test_path)
    print(f"\n✓ Created test schematic: {test_path}")

    # Add some components
    print("\n[1/4] Adding test components...")
    sch = SchematicManager.load_schematic(str(test_path))

    # Add resistor at (100, 100), rotation 0
    r1_def = {
        "type": "R",
        "reference": "R1",
        "value": "10k",
        "x": 100,
        "y": 100,
        "rotation": 0,
    }
    ComponentManager.add_component(sch, r1_def, test_path)

    # Add capacitor at (150, 100), rotation 90
    c1_def = {
        "type": "C",
        "reference": "C1",
        "value": "100nF",
        "x": 150,
        "y": 100,
        "rotation": 90,
    }
    ComponentManager.add_component(sch, c1_def, test_path)

    SchematicManager.save_schematic(sch, str(test_path))
    print("  ✓ Added R1 and C1")

    # Test pin locator
    print("\n[2/4] Testing pin location discovery...")
    locator = PinLocator()

    # Find R1 pins
    r1_pin1 = locator.get_pin_location(test_path, "R1", "1")
    r1_pin2 = locator.get_pin_location(test_path, "R1", "2")

    print(f"  R1 pin 1: {r1_pin1}")
    print(f"  R1 pin 2: {r1_pin2}")

    # Find C1 pins (rotated 90 degrees)
    c1_pin1 = locator.get_pin_location(test_path, "C1", "1")
    c1_pin2 = locator.get_pin_location(test_path, "C1", "2")

    print(f"  C1 pin 1: {c1_pin1}")
    print(f"  C1 pin 2: {c1_pin2}")

    # Test get all pins
    print("\n[3/4] Testing get all pins...")
    r1_all_pins = locator.get_all_symbol_pins(test_path, "R1")
    print(f"  R1 all pins: {r1_all_pins}")

    c1_all_pins = locator.get_all_symbol_pins(test_path, "C1")
    print(f"  C1 all pins: {c1_all_pins}")

    # Verify results
    print("\n[4/4] Verification...")
    success = True

    if not r1_pin1 or not r1_pin2:
        print("  ✗ Failed to locate R1 pins")
        success = False
    else:
        print("  ✓ R1 pins located")

    if not c1_pin1 or not c1_pin2:
        print("  ✗ Failed to locate C1 pins")
        success = False
    else:
        print("  ✓ C1 pins located")

    # Check rotation (C1 pins should be rotated 90 degrees from R1)
    if r1_pin1 and c1_pin1:
        # R1 is not rotated, pins should be at y offset from symbol center
        # C1 is rotated 90°, pins should be at x offset from symbol center
        print(f"\n  Pin offset analysis:")
        print(f"    R1 (0°):  pin 1 y-offset = {r1_pin1[1] - 100}")
        print(f"    C1 (90°): pin 1 x-offset = {c1_pin1[0] - 150}")

    print("\n" + "=" * 80)
    if success:
        print("✅ PIN LOCATOR TEST PASSED!")
    else:
        print("❌ PIN LOCATOR TEST FAILED!")
    print("=" * 80)
    print(f"\nTest schematic saved: {test_path}")
