"""
IPC API Backend (KiCAD 9.0+)

Uses the official kicad-python library for inter-process communication
with a running KiCAD instance. This enables REAL-TIME UI synchronization.

Note: Requires KiCAD to be running with IPC server enabled:
    Preferences > Plugins > Enable IPC API Server

Key Benefits over SWIG:
- Changes appear instantly in KiCAD UI (no reload needed)
- Transaction support for undo/redo
- Stable API that won't break between versions
- Multi-language support
"""
import logging
import math
import os
import platform
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable

from kicad_api.base import (
    KiCADBackend,
    BoardAPI,
    ConnectionError,
    APINotAvailableError
)

logger = logging.getLogger(__name__)


def _distance_to_segment(
    px: float, py: float, x1: float, y1: float, x2: float, y2: float
) -> float:
    dx = x2 - x1
    dy = y2 - y1
    length_sq = dx * dx + dy * dy
    if length_sq == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / length_sq))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


# Unit conversion constant: KiCAD IPC uses nanometers internally
MM_TO_NM = 1_000_000
INCH_TO_NM = 25_400_000


class IPCBackend(KiCADBackend):
    """
    KiCAD IPC API backend for real-time UI synchronization.

    Communicates with KiCAD via Protocol Buffers over UNIX sockets.
    Requires KiCAD 9.0+ to be running with IPC enabled.

    Changes made through this backend appear immediately in the KiCAD UI
    without requiring manual reload.
    """

    def __init__(self):
        self._kicad = None
        self._connected = False
        self._version = None
        self._on_change_callbacks: List[Callable] = []

    def connect(self, socket_path: Optional[str] = None) -> bool:
        """
        Connect to running KiCAD instance via IPC.

        Args:
            socket_path: Optional socket path. If not provided, will try common locations.
                        Use format: ipc:///tmp/kicad/api.sock

        Returns:
            True if connection successful

        Raises:
            ConnectionError: If connection fails
        """
        try:
            # Import here to allow module to load even without kicad-python
            from kipy import KiCad

            logger.info("Connecting to KiCAD via IPC...")

            # Try to connect with provided path or auto-detect
            socket_paths_to_try = []
            if socket_path:
                socket_paths_to_try.append(socket_path)
            else:
                # Common socket locations (Unix-like systems only)
                # Windows uses named pipes, handled by auto-detect
                if platform.system() != "Windows":
                    socket_paths_to_try.append('ipc:///tmp/kicad/api.sock')  # Linux default
                    # XDG runtime directory (requires getuid, Unix only)
                    if hasattr(os, 'getuid'):
                        socket_paths_to_try.append(f'ipc:///run/user/{os.getuid()}/kicad/api.sock')

                # Auto-detect for all platforms (Windows uses named pipes, Unix uses sockets)
                socket_paths_to_try.append(None)

            last_error = None
            for path in socket_paths_to_try:
                try:
                    if path:
                        logger.debug(f"Trying socket path: {path}")
                        self._kicad = KiCad(socket_path=path, timeout_ms=20000)
                    else:
                        logger.debug("Trying auto-detection")
                        self._kicad = KiCad(timeout_ms=20000)

                    # Verify connection with ping (ping returns None on success)
                    self._kicad.ping()
                    logger.info(f"Connected via socket: {path or 'auto-detected'}")
                    break
                except Exception as e:
                    last_error = e
                    logger.debug(f"Failed to connect via {path}: {e}")
                    continue
            else:
                # None of the paths worked
                raise ConnectionError(f"Could not connect to KiCAD IPC: {last_error}")

            # Get version info
            self._version = self._get_kicad_version()
            logger.info(f"Connected to KiCAD {self._version} via IPC")
            self._connected = True
            return True

        except ImportError as e:
            logger.error("kicad-python library not found")
            raise APINotAvailableError(
                "IPC backend requires kicad-python. "
                "Install with: pip install kicad-python"
            ) from e
        except Exception as e:
            logger.error(f"Failed to connect via IPC: {e}")
            logger.info(
                "Ensure KiCAD is running with IPC enabled: "
                "Preferences > Plugins > Enable IPC API Server"
            )
            raise ConnectionError(f"IPC connection failed: {e}") from e

    def _get_kicad_version(self) -> str:
        """Get KiCAD version string."""
        try:
            if self._kicad.check_version():
                return self._kicad.get_api_version()
            return "9.0+ (version mismatch)"
        except Exception:
            return "unknown"

    def disconnect(self) -> None:
        """Disconnect from KiCAD."""
        if self._kicad:
            self._kicad = None
            self._connected = False
            logger.info("Disconnected from KiCAD IPC")

    def is_connected(self) -> bool:
        """Check if connected to KiCAD."""
        if not self._connected or not self._kicad:
            return False
        try:
            # ping() returns None on success, raises on failure
            self._kicad.ping()
            return True
        except Exception:
            self._connected = False
            return False

    def get_version(self) -> str:
        """Get KiCAD version."""
        return self._version or "unknown"

    def register_change_callback(self, callback: Callable) -> None:
        """Register a callback to be called when changes are made."""
        self._on_change_callbacks.append(callback)

    def _notify_change(self, change_type: str, details: Dict[str, Any]) -> None:
        """Notify registered callbacks of a change."""
        for callback in self._on_change_callbacks:
            try:
                callback(change_type, details)
            except Exception as e:
                logger.warning(f"Change callback error: {e}")

    # Project Operations
    def create_project(self, path: Path, name: str) -> Dict[str, Any]:
        """
        Create a new KiCAD project.

        Note: The IPC API doesn't directly create projects.
        Projects must be created through the UI or file system.
        """
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        # IPC API doesn't have project creation - use file-based approach
        logger.warning("Project creation via IPC not fully supported - using hybrid approach")

        # For now, we'll return info about what needs to happen
        return {
            "success": False,
            "message": "Direct project creation not supported via IPC",
            "suggestion": "Open KiCAD and create a new project, or use SWIG backend"
        }

    def open_project(self, path: Path) -> Dict[str, Any]:
        """Open existing project via IPC."""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        try:
            # Check for open documents
            documents = self._kicad.get_open_documents()

            # Look for matching project
            path_str = str(path)
            for doc in documents:
                if path_str in str(doc):
                    return {
                        "success": True,
                        "message": f"Project already open: {path}",
                        "path": str(path)
                    }

            return {
                "success": False,
                "message": "Project not currently open in KiCAD",
                "suggestion": "Open the project in KiCAD first, then connect via IPC"
            }

        except Exception as e:
            logger.error(f"Failed to check project: {e}")
            return {
                "success": False,
                "message": "Failed to check project",
                "errorDetails": str(e)
            }

    def save_project(self, path: Optional[Path] = None) -> Dict[str, Any]:
        """Save current project via IPC."""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        try:
            board = self._kicad.get_board()
            if path:
                board.save_as(str(path))
            else:
                board.save()

            self._notify_change("save", {"path": str(path) if path else "current"})

            return {
                "success": True,
                "message": "Project saved successfully"
            }
        except Exception as e:
            logger.error(f"Failed to save project: {e}")
            return {
                "success": False,
                "message": "Failed to save project",
                "errorDetails": str(e)
            }

    def close_project(self) -> None:
        """Close current project (not supported via IPC)."""
        logger.warning("Closing projects via IPC is not supported")

    # Board Operations
    def get_board(self) -> BoardAPI:
        """Get board API for real-time manipulation."""
        if not self.is_connected():
            raise ConnectionError("Not connected to KiCAD")

        return IPCBoardAPI(self._kicad, self._notify_change)


class IPCBoardAPI(BoardAPI):
    """
    Board API implementation for IPC backend.

    All changes made through this API appear immediately in the KiCAD UI.
    Uses transactions for proper undo/redo support.
    """

    def __init__(self, kicad_instance, notify_callback: Callable):
        self._kicad = kicad_instance
        self._board = None
        self._notify = notify_callback
        self._current_commit = None

    def _get_board(self):
        """Get board instance, connecting if needed."""
        if self._board is None:
            try:
                self._board = self._kicad.get_board()
            except Exception as e:
                logger.error(f"Failed to get board: {e}")
                raise ConnectionError(f"No board open in KiCAD: {e}")
        return self._board

    def begin_transaction(self, description: str = "MCP Operation") -> None:
        """Begin a transaction for grouping operations into a single undo step."""
        board = self._get_board()
        self._current_commit = board.begin_commit()
        logger.debug(f"Started transaction: {description}")

    def commit_transaction(self, description: str = "MCP Operation") -> None:
        """Commit the current transaction."""
        if self._current_commit:
            board = self._get_board()
            board.push_commit(self._current_commit, description)
            self._current_commit = None
            logger.debug(f"Committed transaction: {description}")

    def rollback_transaction(self) -> None:
        """Roll back the current transaction."""
        if self._current_commit:
            board = self._get_board()
            board.drop_commit(self._current_commit)
            self._current_commit = None
            logger.debug("Rolled back transaction")

    def save(self) -> bool:
        """Save the board immediately."""
        try:
            board = self._get_board()
            board.save()
            self._notify("save", {})
            return True
        except Exception as e:
            logger.error(f"Failed to save board: {e}")
            return False

    def set_size(self, width: float, height: float, unit: str = "mm") -> bool:
        """
        Set board size.

        Note: Board size in KiCAD is typically defined by the board outline,
        not a direct size property. This method may need to create/modify
        the board outline.
        """
        try:
            from kipy.board_types import BoardRectangle
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self._get_board()

            # Convert to nm
            if unit == "mm":
                w = from_mm(width)
                h = from_mm(height)
            else:
                w = int(width * INCH_TO_NM)
                h = int(height * INCH_TO_NM)

            # Create board outline rectangle on Edge.Cuts layer
            rect = BoardRectangle()
            rect.start = Vector2.from_xy(0, 0)
            rect.end = Vector2.from_xy(w, h)
            rect.layer = BoardLayer.BL_Edge_Cuts
            rect.width = from_mm(0.1)  # Standard edge cut width

            # Begin transaction for undo support
            commit = board.begin_commit()
            board.create_items(rect)
            board.push_commit(commit, f"Set board size to {width}x{height} {unit}")

            self._notify("board_size", {"width": width, "height": height, "unit": unit})

            return True

        except Exception as e:
            logger.error(f"Failed to set board size: {e}")
            return False

    def get_size(self) -> Dict[str, float]:
        """Get current board size from bounding box."""
        try:
            board = self._get_board()

            # Get shapes on Edge.Cuts layer to determine board size
            shapes = board.get_shapes()

            if not shapes:
                return {"width": 0, "height": 0, "unit": "mm"}

            # Find bounding box of edge cuts
            from kipy.util.units import to_mm

            min_x = min_y = float('inf')
            max_x = max_y = float('-inf')

            for shape in shapes:
                # Check if on Edge.Cuts layer
                bbox = board.get_item_bounding_box(shape)
                if bbox:
                    min_x = min(min_x, bbox.pos.x)
                    min_y = min(min_y, bbox.pos.y)
                    max_x = max(max_x, (bbox.pos.x + bbox.size.x))
                    max_y = max(max_y, (bbox.pos.y + bbox.size.y))

            if min_x == float('inf'):
                return {"width": 0, "height": 0, "unit": "mm"}

            return {
                "width": to_mm(max_x - min_x),
                "height": to_mm(max_y - min_y),
                "unit": "mm"
            }

        except Exception as e:
            logger.error(f"Failed to get board size: {e}")
            return {"width": 0, "height": 0, "unit": "mm", "error": str(e)}

    def add_layer(self, layer_name: str, layer_type: str) -> bool:
        """Add layer to the board (layers are typically predefined in KiCAD)."""
        logger.warning("Layer management via IPC is limited - layers are predefined")
        return False

    def get_enabled_layers(self) -> List[str]:
        """Get list of enabled layers."""
        try:
            board = self._get_board()
            layers = board.get_enabled_layers()
            return [str(layer) for layer in layers]
        except Exception as e:
            logger.error(f"Failed to get enabled layers: {e}")
            return []

    def list_components(self) -> List[Dict[str, Any]]:
        """List all components (footprints) on the board."""
        try:
            from kipy.util.units import to_mm

            board = self._get_board()
            footprints = board.get_footprints()

            components = []
            for fp in footprints:
                try:
                    pos = fp.position
                    components.append({
                        "reference": fp.reference_field.text.value if fp.reference_field else "",
                        "value": fp.value_field.text.value if fp.value_field else "",
                        "footprint": str(fp.definition.id) if fp.definition else "",
                        "position": {
                            "x": to_mm(pos.x) if pos else 0,
                            "y": to_mm(pos.y) if pos else 0,
                            "unit": "mm"
                        },
                        "rotation": fp.orientation.degrees if fp.orientation else 0,
                        "layer": {
                              3: "F.Cu",
                            34: "B.Cu"
                                  }.get(fp.layer, str(fp.layer)),
                        "id": fp.id.value if fp.id else ""
                        
                    })
                except Exception as e:
                    logger.warning(f"Error processing footprint: {e}")
                    continue

            return components

        except Exception as e:
            logger.error(f"Failed to list components: {e}")
            return []

    def _footprint_library_id(self, fp) -> str:
        """Return the Library:FootprintName id exposed by an IPC footprint."""
        try:
            if not fp.definition:
                return ""
            return str(fp.definition.id)
        except Exception:
            return ""

    def _copper_side_name(self, layer_value) -> Optional[str]:
        """Map a footprint copper side to F.Cu or B.Cu."""
        from kipy.proto.board.board_types_pb2 import BoardLayer

        if layer_value == BoardLayer.BL_F_Cu:
            return "F.Cu"
        if layer_value == BoardLayer.BL_B_Cu:
            return "B.Cu"
        return None

    def _find_footprint_by_reference(self, reference: str):
        board = self._get_board()
        for fp in board.get_footprints():
            if fp.reference_field and fp.reference_field.text.value == reference:
                return fp
        return None

    def _open_pcb_paths(self) -> List[str]:
        from pathlib import Path
        from kipy.proto.common.types import DocumentType

        paths = []
        for doc in self._kicad.get_open_documents(DocumentType.DOCTYPE_PCB):
            filename = getattr(doc, "board_filename", "") or ""
            project = getattr(doc, "project", None)
            project_path = getattr(project, "path", "") if project else ""
            if filename and project_path:
                paths.append(str((Path(project_path) / filename).resolve()))
            elif filename:
                paths.append(str(Path(filename).resolve()))
        return paths

    def place_component(
        self,
        reference: str,
        footprint: str,
        x: float,
        y: float,
        rotation: float = 0,
        layer: str = "F.Cu",
        value: str = "",
        board_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Place a footprint that is already on the open PCB.

        The new instance is a full IPC clone of an existing footprint with the
        same Library:FootprintName. Library footprints that are not already on
        the board are rejected. This method does not write the PCB file.
        """
        try:
            import math
            from pathlib import Path

            if not isinstance(reference, str) or not reference.strip():
                return {"success": False, "error": "reference is required"}
            reference = reference.strip()

            if not isinstance(footprint, str) or not footprint.strip():
                return {
                    "success": False,
                    "error": "footprint is required in Library:FootprintName format",
                }
            footprint = footprint.strip()

            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (x, y, rotation)):
                return {
                    "success": False,
                    "error": "Position and rotation must be finite numbers",
                }

            if layer not in ("F.Cu", "B.Cu"):
                return {
                    "success": False,
                    "error": "layer must be F.Cu or B.Cu",
                }

            if board_path:
                requested = str(Path(board_path).resolve())
                open_paths = self._open_pcb_paths()
                if requested.lower() not in {path.lower() for path in open_paths}:
                    return {
                        "success": False,
                        "error": (
                            "boardPath is not the PCB currently open in KiCad. "
                            "Refusing to load or overwrite another board file."
                        ),
                    }

            board = self._get_board()
            footprints = list(board.get_footprints())

            if any(
                fp.reference_field and fp.reference_field.text.value == reference
                for fp in footprints
            ):
                return {
                    "success": False,
                    "error": f"Reference already exists: {reference}",
                }

            matches = [
                fp for fp in footprints
                if self._footprint_library_id(fp) == footprint
            ]
            if not matches:
                loaded = self._load_footprint_from_library(footprint)
                if loaded is None:
                    return {
                        "success": False,
                        "error": f"Footprint not found: {footprint}",
                    }
                return {
                    "success": False,
                    "error": (
                        f"Footprint {footprint} is not on the open PCB. "
                        "Importing a library footprint that is not already on the board "
                        "is unsupported with KiCad 10 IPC."
                    ),
                }

            same_side = [
                fp for fp in matches
                if self._copper_side_name(fp.layer) == layer
            ]
            if not same_side:
                return {
                    "success": False,
                    "error": (
                        f"No {layer} instance of {footprint} is on the open PCB. "
                        "This KiCad installation has no FlipItems handler, so a footprint "
                        "cannot be moved to the opposite copper side."
                    ),
                }

            source = same_side[0]
            source_reference = source.reference_field.text.value
            source_pads = len(source.definition.pads)

            result = self.clone_component(
                source_reference=source_reference,
                new_reference=reference,
                x=float(x),
                y=float(y),
                rotation=float(rotation),
                value=value if value else None,
            )
            if not result.get("success"):
                return result

            created = self._find_footprint_by_reference(reference)
            created_side = self._copper_side_name(created.layer) if created else None
            if (
                created is None
                or self._footprint_library_id(created) != footprint
                or created_side != layer
            ):
                self.delete_component(reference)
                return {
                    "success": False,
                    "error": "Placed footprint identity or layer did not match the request",
                }

            created_pads = len(created.definition.pads)
            if created_pads != source_pads:
                self.delete_component(reference)
                return {
                    "success": False,
                    "error": (
                        f"Placed pad count {created_pads} does not match "
                        f"source pad count {source_pads}"
                    ),
                }

            if any(pad.net.name for pad in created.definition.pads):
                self.delete_component(reference)
                return {
                    "success": False,
                    "error": "Could not leave the new footprint unconnected",
                }

            result["layer"] = layer
            result["source_reference"] = source_reference
            result["placement"] = "existing_footprint"
            self._notify("component_placed", {
                "reference": reference,
                "footprint": footprint,
                "position": {"x": x, "y": y},
                "rotation": rotation,
                "layer": layer,
                "loaded_from_library": False,
            })
            return result

        except Exception as e:
            logger.error("Failed to place component: %s", e)
            return {"success": False, "error": str(e)}

    def _load_footprint_from_library(self, footprint_path: str):
        """Load a footprint from a standard KiCad library."""
        try:
            import pcbnew
            from pathlib import Path

            if ":" not in footprint_path:
                logger.error(
                    "Footprint must use Library:FootprintName format: %s",
                    footprint_path
                )
                return None

            lib_name, fp_name = footprint_path.split(":", 1)

            if not lib_name or not fp_name:
                logger.error("Invalid footprint identifier: %s", footprint_path)
                return None

            import sys
            kicad_root = Path(sys.executable).resolve().parent.parent
            lib_path = (
                kicad_root
                / "share"
                / "kicad"
                / "footprints"
                / f"{lib_name}.pretty"
            )

            if not lib_path.is_dir():
                logger.error("Footprint library not found: %s", lib_path)
                return None

            loaded_fp = pcbnew.FootprintLoad(
                str(lib_path),
                fp_name
            )

            if loaded_fp is None:
                logger.error("Footprint not found: %s", footprint_path)
                return None

            logger.info("Loaded footprint: %s", footprint_path)
            return loaded_fp

        except Exception as e:
            logger.error("Error loading footprint: %s", e)
            return None

    def _place_loaded_footprint(
        self,
        loaded_fp,
        reference: str,
        x: float,
        y: float,
        rotation: float,
        layer: str,
        value: str
    ) -> bool:
        """Disabled. Saving a SWIG board over an open PCB is not a safe IPC edit."""
        logger.error(
            "Refusing to place %s by saving the PCB file over the open editor",
            reference,
        )
        return False

    def _place_placeholder_footprint(
        self,
        reference: str,
        footprint: str,
        x: float,
        y: float,
        rotation: float,
        layer: str,
        value: str
    ) -> bool:
        """Disabled. A placeholder is not the requested footprint."""
        logger.error(
            "Refusing to create a placeholder for %s (%s)",
            reference,
            footprint,
        )
        return False

    def move_component(self, reference: str, x: float, y: float, rotation: Optional[float] = None) -> bool:
        """Move a component to a new position (updates UI immediately)."""
        try:
            from kipy.geometry import Vector2, Angle
            from kipy.util.units import from_mm

            board = self._get_board()
            footprints = board.get_footprints()

            # Find the footprint by reference
            target_fp = None
            for fp in footprints:
                if fp.reference_field and fp.reference_field.text.value == reference:
                    target_fp = fp
                    break

            if not target_fp:
                logger.error(f"Component not found: {reference}")
                return False

            # Start a transaction before applying changes
            commit = board.begin_commit()

            try:
                # Update position
                target_fp.position = Vector2.from_xy(
                    from_mm(x),
                    from_mm(y)
                )

                # Update rotation if specified
                if rotation is not None:
                    target_fp.orientation = Angle.from_degrees(rotation)

                # Apply changes to KiCad
                board.update_items([target_fp])

                # Commit changes for undo/redo
                board.push_commit(
                    commit,
                    f"Moved component {reference}"
                )

            except Exception:
                board.drop_commit(commit)
                raise

            self._notify("component_moved", {
                "reference": reference,
                "position": {"x": x, "y": y},
                "rotation": rotation
            })

            checked = self._read_back_placement(reference, x, y, rotation)
            if not checked["success"]:
                logger.error("Move read-back failed for %s: %s", reference, checked["message"])
                return False
            return True

        except Exception as e:
            logger.error(f"Failed to move component: {e}")
            return False

    @staticmethod
    def _angles_match(actual, target, tolerance: float = 0.05) -> bool:
        if actual is None or target is None:
            return target is None
        delta = (float(actual) - float(target)) % 360.0
        if delta > 180.0:
            delta = 360.0 - delta
        return delta <= tolerance

    def _read_back_placement(self, reference: str, x: float, y: float, rotation: Optional[float]) -> Dict[str, Any]:
        from kipy.util.units import to_mm

        for footprint in self._get_board().get_footprints():
            if not footprint.reference_field or footprint.reference_field.text.value != reference:
                continue
            actual_x = to_mm(footprint.position.x)
            actual_y = to_mm(footprint.position.y)
            actual_rotation = footprint.orientation.degrees if footprint.orientation else 0.0
            position_ok = abs(actual_x - x) <= 0.01 and abs(actual_y - y) <= 0.01
            rotation_ok = rotation is None or self._angles_match(actual_rotation, rotation)
            if position_ok and rotation_ok:
                return {
                    "success": True,
                    "x": actual_x,
                    "y": actual_y,
                    "rotation": actual_rotation,
                }
            return {
                "success": False,
                "message": (
                    f"{reference} read back at ({actual_x:.3f}, {actual_y:.3f}) "
                    f"rotation {actual_rotation}, expected ({x:.3f}, {y:.3f}) {rotation}"
                ),
            }
        return {"success": False, "message": f"{reference} was not on the board after the move"}

    def _shape_points_mm(self, shape) -> List[tuple]:
        from kipy.util.units import to_mm

        kind = type(shape).__name__
        if kind == "BoardSegment":
            return [
                (to_mm(shape.start.x), to_mm(shape.start.y)),
                (to_mm(shape.end.x), to_mm(shape.end.y)),
            ]
        if kind == "BoardRectangle":
            return [
                (to_mm(shape.top_left.x), to_mm(shape.top_left.y)),
                (to_mm(shape.bottom_right.x), to_mm(shape.bottom_right.y)),
            ]
        if kind == "BoardArc":
            return [
                (to_mm(shape.start.x), to_mm(shape.start.y)),
                (to_mm(shape.end.x), to_mm(shape.end.y)),
                (to_mm(shape.mid.x), to_mm(shape.mid.y)),
            ]
        return []

    def read_placement_geometry(self) -> Dict[str, Any]:
        """Read footprint anchors, courtyards, and pad nets. Nothing is modified."""
        from kipy.proto.board.board_types_pb2 import BoardLayer
        from kipy.util.units import to_mm

        from kicad_api.placement import aabb_from_points, local_box

        courtyard_layer = int(BoardLayer.BL_F_CrtYd)
        footprints = []
        for footprint in self._get_board().get_footprints():
            reference = footprint.reference_field.text.value if footprint.reference_field else ""
            origin_x = to_mm(footprint.position.x)
            origin_y = to_mm(footprint.position.y)
            rotation = footprint.orientation.degrees if footprint.orientation else 0.0
            court_points = []
            for shape in footprint.definition.shapes:
                if int(shape.layer) == courtyard_layer:
                    court_points.extend(self._shape_points_mm(shape))
            pad_points = []
            pads = []
            for pad in footprint.definition.pads:
                px = to_mm(pad.position.x)
                py = to_mm(pad.position.y)
                pad_points.append((px, py))
                pads.append(
                    {
                        "number": str(pad.number),
                        "net": pad.net.name if pad.net else "",
                        "x": px,
                        "y": py,
                    }
                )
            item = {
                "reference": reference,
                "value": footprint.value_field.text.value if footprint.value_field else "",
                "footprint": str(footprint.definition.id) if footprint.definition else "",
                "x": origin_x,
                "y": origin_y,
                "rotation": rotation,
                "pads": pads,
                "nets": sorted({pad["net"] for pad in pads if pad["net"]}),
            }
            if court_points:
                item["courtyard"] = aabb_from_points(court_points)
                item["localCourtyard"] = local_box(court_points, origin_x, origin_y, rotation)
            if pad_points:
                item["body"] = aabb_from_points(pad_points)
                item["localBody"] = local_box(pad_points, origin_x, origin_y, rotation)
            footprints.append(item)
        return {"success": True, "footprints": footprints}

    def measure_edge_cuts(self) -> Dict[str, Any]:
        """Return the Edge.Cuts bounding box in millimetres."""
        from kipy.proto.board.board_types_pb2 import BoardLayer

        from kicad_api.placement import aabb_from_points

        layer = int(BoardLayer.BL_Edge_Cuts)
        points = []
        count = 0
        for shape in self._get_board().get_shapes():
            if int(getattr(shape, "layer", -1)) != layer:
                continue
            count += 1
            points.extend(self._shape_points_mm(shape))
        if not points:
            return {"success": True, "present": False, "count": 0}
        box = aabb_from_points(points)
        return {
            "success": True,
            "present": True,
            "count": count,
            "box": box,
            "width": box["xmax"] - box["xmin"],
            "height": box["ymax"] - box["ymin"],
            "center": {
                "x": (box["xmin"] + box["xmax"]) / 2.0,
                "y": (box["ymin"] + box["ymax"]) / 2.0,
            },
        }

    def place_components(self, placements: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Move several footprints in one undoable commit and read them back.

        Pad nets are compared before and after. A mismatch restores the
        previous anchors.
        """
        from kipy.geometry import Angle, Vector2
        from kipy.util.units import from_mm, to_mm

        board = self._get_board()
        by_ref = {}
        for footprint in board.get_footprints():
            reference = footprint.reference_field.text.value if footprint.reference_field else ""
            if reference in by_ref:
                return {
                    "success": False,
                    "error": "DUPLICATE_REFERENCE",
                    "message": f"The board has more than one {reference}.",
                }
            by_ref[reference] = footprint
        missing = [item.get("reference", "") for item in placements if item.get("reference") not in by_ref]
        if missing:
            return {
                "success": False,
                "error": "COMPONENT_NOT_FOUND",
                "message": "Not on the board: " + ", ".join(missing),
            }

        def pad_nets(footprints) -> Dict[tuple, str]:
            found = {}
            for footprint in footprints:
                reference = footprint.reference_field.text.value if footprint.reference_field else ""
                for pad in footprint.definition.pads:
                    found[(reference, str(pad.number))] = pad.net.name if pad.net else ""
            return found

        before_nets = pad_nets(by_ref.values())
        previous = {
            reference: (
                to_mm(footprint.position.x),
                to_mm(footprint.position.y),
                footprint.orientation.degrees if footprint.orientation else 0.0,
            )
            for reference, footprint in by_ref.items()
        }
        commit = board.begin_commit()
        try:
            updated = []
            for item in placements:
                footprint = by_ref[item["reference"]]
                footprint.position = Vector2.from_xy(from_mm(float(item["x"])), from_mm(float(item["y"])))
                footprint.orientation = Angle.from_degrees(float(item.get("rotation", 0.0)))
                updated.append(footprint)
            board.update_items(updated)
            board.push_commit(commit, "Place components")
        except Exception as exc:
            try:
                board.drop_commit(commit)
            except Exception:
                logger.warning("Failed to drop placement commit: %s", exc)
            return {"success": False, "error": "IPC_ERROR", "message": str(exc)}

        problems = []
        read_back = []
        for item in placements:
            checked = self._read_back_placement(
                item["reference"], float(item["x"]), float(item["y"]), float(item.get("rotation", 0.0))
            )
            read_back.append({"reference": item["reference"], **checked})
            if not checked["success"]:
                problems.append(checked["message"])
        after = list(self._get_board().get_footprints())
        after_nets = pad_nets(after)
        if before_nets != after_nets:
            problems.append("Pad net assignments changed during placement.")
        if problems:
            self._restore_placements(previous)
            return {
                "success": False,
                "error": "IPC_VERIFY_FAILED",
                "message": "; ".join(problems),
                "readBack": read_back,
            }
        return {"success": True, "message": f"Placed {len(placements)} footprints.", "readBack": read_back}

    def _restore_placements(self, previous: Dict[str, tuple]) -> None:
        from kipy.geometry import Angle, Vector2
        from kipy.util.units import from_mm

        board = self._get_board()
        commit = board.begin_commit()
        try:
            updated = []
            for footprint in board.get_footprints():
                reference = footprint.reference_field.text.value if footprint.reference_field else ""
                if reference not in previous:
                    continue
                x, y, rotation = previous[reference]
                footprint.position = Vector2.from_xy(from_mm(x), from_mm(y))
                footprint.orientation = Angle.from_degrees(rotation)
                updated.append(footprint)
            board.update_items(updated)
            board.push_commit(commit, "Restore placement after failed verification")
        except Exception as exc:
            try:
                board.drop_commit(commit)
            except Exception:
                pass
            logger.error("Could not restore the previous placement: %s", exc)

    def clone_component(
        self,
        source_reference: str,
        new_reference: str,
        x: float,
        y: float,
        rotation: Optional[float] = None,
        value: Optional[str] = None,
        copy_nets: bool = False
    ) -> Dict[str, Any]:
        """Clone an existing footprint using the KiCad IPC API.

        Pad nets are cleared unless copy_nets is true.
        """

        try:
            import math
            from kipy.geometry import Vector2, Angle
            from kipy.util.units import from_mm, to_mm

            board = self._get_board()
            footprints = board.get_footprints()

            if not source_reference or not new_reference:
                return {
                    "success": False,
                    "error": "Source and new references are required"
                }

            if not all(math.isfinite(v) for v in (x, y)):
                return {
                    "success": False,
                    "error": "Coordinates must be finite numbers"
                }

            if rotation is not None and not math.isfinite(rotation):
                return {
                    "success": False,
                    "error": "Rotation must be a finite number"
                }

            source = next(
                (
                    fp for fp in footprints
                    if fp.reference_field
                    and fp.reference_field.text.value == source_reference
                ),
                None
            )

            if source is None:
                return {
                    "success": False,
                    "error": f"Source component not found: {source_reference}"
                }

            if any(
                fp.reference_field
                and fp.reference_field.text.value == new_reference
                for fp in footprints
            ):
                return {
                    "success": False,
                    "error": f"Reference already exists: {new_reference}"
                }

            clone = source.clone()

            clone.reference_field.text.value = new_reference

            if value is not None:
                clone.value_field.text.value = value

            clone.position = Vector2.from_xy(
                from_mm(x),
                from_mm(y)
            )

            if rotation is not None:
                clone.orientation = Angle.from_degrees(rotation)

            if not copy_nets:
                from kipy.board_types import Net

                for pad in clone.definition.pads:
                    pad.net = Net()

            commit = board.begin_commit()

            try:
                board.create_items(clone)
                board.push_commit(
                    commit,
                    f"Clone {source_reference} as {new_reference}"
                )
            except Exception:
                board.drop_commit(commit)
                raise

            created = next(
                (
                    fp for fp in board.get_footprints()
                    if fp.reference_field
                    and fp.reference_field.text.value == new_reference
                ),
                None
            )

            if created is None:
                return {
                    "success": False,
                    "error": "Commit completed but component was not found"
                }

            if not copy_nets and any(pad.net.name for pad in created.definition.pads):
                self.delete_component(new_reference)
                return {
                    "success": False,
                    "error": "Could not leave the cloned footprint unconnected"
                }

            self._notify("component_cloned", {
                "source_reference": source_reference,
                "reference": new_reference
            })

            return {
                "success": True,
                "reference": new_reference,
                "source_reference": source_reference,
                "footprint": str(created.definition.id),
                "pads": len(created.definition.pads),
                "uuid": created.id.value,
                "position": {
                    "x": to_mm(created.position.x),
                    "y": to_mm(created.position.y),
                    "unit": "mm"
                },
                "rotation": created.orientation.degrees,
                "nets_copied": bool(copy_nets)
            }

        except Exception as e:
            logger.error("Failed to clone component: %s", e)

            return {
                "success": False,
                "error": str(e)
            }

    def delete_component(self, reference: str) -> bool:
        """Delete a component from the board."""
        try:
            board = self._get_board()
            footprints = board.get_footprints()

            # Find the footprint by reference
            target_fp = None
            for fp in footprints:
                if fp.reference_field and fp.reference_field.text.value == reference:
                    target_fp = fp
                    break

            if not target_fp:
                logger.error(f"Component not found: {reference}")
                return False

            # Remove component
            commit = board.begin_commit()
            board.remove_items([target_fp])
            board.push_commit(commit, f"Deleted component {reference}")

            self._notify("component_deleted", {"reference": reference})

            return True

        except Exception as e:
            logger.error(f"Failed to delete component: {e}")
            return False

    def delete_traces(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Delete tracks or vias through the KiCad IPC API.

        The board file is not loaded or saved. A failed match does not open a commit.
        """
        try:
            trace_uuid = params.get("traceUuid")
            position = params.get("position")
            net_name = params.get("net")
            layer = params.get("layer")
            include_vias = params.get("includeVias", False)

            if not isinstance(include_vias, bool):
                return {
                    "success": False,
                    "error": "INVALID_ARGUMENT",
                    "message": "includeVias must be a boolean",
                }
            if not trace_uuid and not position and not net_name:
                return {
                    "success": False,
                    "error": "INVALID_ARGUMENT",
                    "message": "One of traceUuid, position, or net is required",
                }

            board = self._get_board()
            tracks = list(board.get_tracks())
            vias = list(board.get_vias()) if (include_vias or trace_uuid or position) else []
            selected = self._select_traces(tracks, vias, trace_uuid, position, net_name, layer, include_vias)
            if not selected:
                return {
                    "success": False,
                    "error": "NOT_FOUND",
                    "message": "No matching trace was found",
                }

            selected_ids = [self._item_id(item) for item in selected]
            commit = board.begin_commit()
            try:
                board.remove_items(selected)
                board.push_commit(commit, f"Deleted {len(selected)} trace(s)")
            except Exception:
                board.drop_commit(commit)
                raise

            remaining = {
                self._item_id(item)
                for item in list(board.get_tracks()) + list(board.get_vias())
            }
            still_present = [item_id for item_id in selected_ids if not item_id or item_id in remaining]
            if still_present:
                return {
                    "success": False,
                    "error": "IPC_VERIFY_FAILED",
                    "message": "The trace delete was not visible on the board after the commit",
                    "deletedCount": 0,
                }

            self._notify("traces_deleted", {"count": len(selected_ids)})
            return {
                "success": True,
                "message": f"Deleted {len(selected_ids)} trace(s)",
                "deletedCount": len(selected_ids),
                "deletedIds": selected_ids,
            }
        except Exception as e:
            logger.error("IPC delete_traces failed: %s", e)
            message = str(e)
            if "no handler" in message.lower():
                return {
                    "success": False,
                    "error": "UNSUPPORTED_OPERATION",
                    "message": f"This KiCad build cannot delete traces through IPC: {message}",
                }
            return {"success": False, "error": "IPC_ERROR", "message": message}

    def add_board_outline(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add an Edge.Cuts outline through IPC. The PCB file is not written."""
        from kicad_api.pcb_safety import outline_primitives

        geometry = outline_primitives(params)
        if not geometry.get("success"):
            return geometry

        try:
            from kipy.board_types import BoardArc, BoardCircle, BoardRectangle, BoardSegment
            from kipy.geometry import Vector2
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm
        except Exception as exc:
            return {
                "success": False,
                "error": "UNSUPPORTED_OPERATION",
                "message": f"This KiCad Python build cannot create board outlines through IPC: {exc}",
            }

        board = None
        commit = None
        try:
            board = self._get_board()
            items = []
            for primitive in geometry["primitives"]:
                kind = primitive["type"]
                if kind == "rectangle":
                    shape = BoardRectangle()
                    shape.top_left = Vector2.from_xy(
                        from_mm(primitive["x"]), from_mm(primitive["y"])
                    )
                    shape.bottom_right = Vector2.from_xy(
                        from_mm(primitive["x"] + primitive["width"]),
                        from_mm(primitive["y"] + primitive["height"]),
                    )
                elif kind == "segment":
                    shape = BoardSegment()
                    shape.start = Vector2.from_xy(from_mm(primitive["x1"]), from_mm(primitive["y1"]))
                    shape.end = Vector2.from_xy(from_mm(primitive["x2"]), from_mm(primitive["y2"]))
                elif kind == "arc":
                    shape = BoardArc()
                    shape.start = Vector2.from_xy(from_mm(primitive["x1"]), from_mm(primitive["y1"]))
                    shape.mid = Vector2.from_xy(from_mm(primitive["mx"]), from_mm(primitive["my"]))
                    shape.end = Vector2.from_xy(from_mm(primitive["x2"]), from_mm(primitive["y2"]))
                elif kind == "circle":
                    shape = BoardCircle()
                    shape.center = Vector2.from_xy(from_mm(primitive["cx"]), from_mm(primitive["cy"]))
                    shape.radius_point = Vector2.from_xy(
                        from_mm(primitive["cx"] + primitive["radius"]),
                        from_mm(primitive["cy"]),
                    )
                else:
                    return {
                        "success": False,
                        "error": "UNSUPPORTED_OPERATION",
                        "message": f"Outline primitive '{kind}' is not supported through IPC.",
                    }
                shape.layer = BoardLayer.BL_Edge_Cuts
                shape.attributes.stroke.width = from_mm(0.1)
                items.append(shape)

            commit = board.begin_commit()
            created = board.create_items(items)
            if not created or len(created) != len(items):
                board.drop_commit(commit)
                commit = None
                return {
                    "success": False,
                    "error": "IPC_VERIFY_FAILED",
                    "message": "KiCad did not create the requested outline items",
                }
            board.push_commit(commit, f"Added {geometry['shape']} board outline")
            commit = None

            created_ids = [self._item_id(item) for item in created]
            visible = {self._item_id(item) for item in board.get_shapes()}
            if any(not item_id or item_id not in visible for item_id in created_ids):
                repair = board.begin_commit()
                try:
                    board.remove_items(created)
                    board.push_commit(repair, "Remove unverified board outline")
                except Exception:
                    board.drop_commit(repair)
                return {
                    "success": False,
                    "error": "IPC_VERIFY_FAILED",
                    "message": "The outline commit completed but the items were not on the board",
                }

            self._notify("board_outline", {"shape": geometry["shape"], "count": len(created_ids)})
            return {
                "success": True,
                "message": f"Added {geometry['shape']} board outline through IPC",
                "shape": geometry["shape"],
                "segments": len(created_ids),
                "ids": created_ids,
            }
        except Exception as exc:
            if board is not None and commit is not None:
                try:
                    board.drop_commit(commit)
                except Exception:
                    logger.warning("Failed to drop outline commit: %s", exc)
            message = str(exc)
            logger.error("IPC add_board_outline failed: %s", message)
            if "no handler" in message.lower():
                return {
                    "success": False,
                    "error": "UNSUPPORTED_OPERATION",
                    "message": f"This KiCad build cannot add that outline through IPC: {message}",
                }
            return {"success": False, "error": "IPC_ERROR", "message": message}

    @staticmethod
    def _item_id(item: Any) -> str:
        ident = getattr(item, "id", None)
        if ident is None:
            return ""
        return str(getattr(ident, "value", ident))

    @staticmethod
    def _net_name(item: Any) -> str:
        net = getattr(item, "net", None)
        if net is None:
            return ""
        return str(getattr(net, "name", "") or "")

    @staticmethod
    def _layer_name(value: Any) -> str:
        if isinstance(value, str):
            return value
        try:
            from kipy.proto.board.board_types_pb2 import BoardLayer

            raw = BoardLayer.Name(int(value))
        except Exception:
            return str(value)
        if raw.startswith("BL_"):
            raw = raw[3:]
        return raw.replace("_", ".")

    @staticmethod
    def _point_mm(point: Any) -> tuple:
        return (float(getattr(point, "x", 0)) / 1_000_000.0, float(getattr(point, "y", 0)) / 1_000_000.0)

    def _select_traces(self, tracks, vias, trace_uuid, position, net_name, layer, include_vias):
        if trace_uuid:
            wanted = str(trace_uuid).lower()
            for item in list(tracks) + list(vias):
                if self._item_id(item).lower() == wanted:
                    return [item]
            return []

        if net_name:
            matched = []
            for track in tracks:
                if self._net_name(track) != net_name:
                    continue
                if layer and self._layer_name(getattr(track, "layer", "")) != layer:
                    continue
                matched.append(track)
            if include_vias:
                for via in vias:
                    if self._net_name(via) == net_name:
                        matched.append(via)
            return matched

        if not isinstance(position, dict):
            return []
        unit = position.get("unit", "mm")
        if unit not in ("mm", "inch"):
            return []
        x = position.get("x")
        y = position.get("y")
        if isinstance(x, bool) or isinstance(y, bool):
            return []
        try:
            x_mm = float(x) * (25.4 if unit == "inch" else 1.0)
            y_mm = float(y) * (25.4 if unit == "inch" else 1.0)
        except (TypeError, ValueError):
            return []
        if not math.isfinite(x_mm) or not math.isfinite(y_mm):
            return []

        nearest = None
        nearest_distance = float("inf")
        for track in tracks:
            start = self._point_mm(track.start)
            end = self._point_mm(track.end)
            distance = _distance_to_segment(x_mm, y_mm, start[0], start[1], end[0], end[1])
            if distance < nearest_distance:
                nearest = track
                nearest_distance = distance
        for via in vias:
            point = self._point_mm(via.position)
            distance = math.hypot(x_mm - point[0], y_mm - point[1])
            if distance < nearest_distance:
                nearest = via
                nearest_distance = distance
        if nearest is not None and nearest_distance <= 1.0:
            return [nearest]
        return []

    def _find_existing_net(self, name: str):
        for net in self._get_board().get_nets():
            if getattr(net, "name", None) == name:
                return net
        return None

    @staticmethod
    def _net_record(net: Any) -> Dict[str, Any]:
        record: Dict[str, Any] = {
            "name": getattr(net, "name", ""),
            "identifier": getattr(net, "name", ""),
        }
        try:
            import warnings

            with warnings.catch_warnings():
                warnings.simplefilter("ignore", DeprecationWarning)
                code = getattr(net, "code", None)
            if isinstance(code, int):
                record["code"] = code
        except Exception:
            pass
        return record

    def add_net(self, name: str, net_class: Optional[str] = None) -> Dict[str, Any]:
        """Report whether a net can be created. KiCad 10 IPC cannot create one."""
        cleaned = name.strip() if isinstance(name, str) else ""
        if not cleaned:
            return {
                "success": False,
                "error": "INVALID_ARGUMENT",
                "message": "A net name is required.",
            }

        existing = self._find_existing_net(cleaned)
        if existing is not None:
            return {
                "success": False,
                "error": "ALREADY_EXISTS",
                "message": f"Net '{cleaned}' already exists and was not modified.",
                "net": self._net_record(existing),
            }

        from kipy.board import Board

        if getattr(Board, "create_net", None) is None:
            detail = (
                "KiCad 10 IPC can list nets with GetNets but has no command to create one. "
                "No net was created and the open PCB was not edited."
            )
            if net_class:
                detail += " The requested net class was not applied."
            return {
                "success": False,
                "error": "UNSUPPORTED_OPERATION",
                "message": detail,
                "net": {"name": cleaned},
            }

        return {
            "success": False,
            "error": "UNSUPPORTED_OPERATION",
            "message": (
                "This kicad-python build exposes a net creator that this server does not call "
                "until its result can be read back from the board. No net was created."
            ),
            "net": {"name": cleaned},
        }

    def _drop_commit(self, board: Any, commit: Any) -> None:
        if commit is None:
            return
        try:
            board.drop_commit(commit)
        except Exception:
            logger.exception("Failed to drop an IPC commit")

    def _remove_committed_item(self, board: Any, item: Any, reason: str) -> bool:
        repair = None
        try:
            repair = board.begin_commit()
            board.remove_items([item])
            board.push_commit(repair, reason)
            return True
        except Exception:
            logger.exception("Failed to remove an unverified board item")
            self._drop_commit(board, repair)
            return False

    def add_track(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        width: float = 0.25,
        layer: str = "F.Cu",
        net_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Add a track and verify its net.

        A named net must already exist. A missing net does not create a track.
        """
        assigned = None
        requested = None
        if net_name is not None:
            if not isinstance(net_name, str) or not net_name.strip():
                return {
                    "success": False,
                    "error": "INVALID_ARGUMENT",
                    "message": "A track net name cannot be blank.",
                }
            requested = net_name.strip()
            assigned = self._find_existing_net(requested)
            if assigned is None:
                return {
                    "success": False,
                    "error": "NET_NOT_FOUND",
                    "message": (
                        f"Net '{requested}' does not exist. KiCad 10 IPC cannot create it, "
                        "so no track was added."
                    ),
                    "net": "",
                }

        commit = None
        board = None
        try:
            from kipy.board_types import Track
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self._get_board()
            track = Track()
            track.start = Vector2.from_xy(from_mm(start_x), from_mm(start_y))
            track.end = Vector2.from_xy(from_mm(end_x), from_mm(end_y))
            track.width = from_mm(width)

            layer_map = {
                "F.Cu": BoardLayer.BL_F_Cu,
                "B.Cu": BoardLayer.BL_B_Cu,
                "In1.Cu": BoardLayer.BL_In1_Cu,
                "In2.Cu": BoardLayer.BL_In2_Cu,
            }
            track.layer = layer_map.get(layer, BoardLayer.BL_F_Cu)
            if assigned is not None:
                track.net = assigned

            commit = board.begin_commit()
            created_raw = board.create_items(track)
            created_list = (
                list(created_raw)
                if isinstance(created_raw, (list, tuple))
                else [created_raw]
            )
            created_item = created_list[0] if created_list else None
            created_id = self._item_id(created_item) if created_item is not None else ""
            if not created_id:
                self._drop_commit(board, commit)
                commit = None
                return {
                    "success": False,
                    "error": "IPC_ERROR",
                    "message": "KiCad did not return an id for the new track. The commit was dropped.",
                }

            preview = self._net_name(created_item)
            if assigned is not None and preview and preview != assigned.name:
                self._drop_commit(board, commit)
                commit = None
                return {
                    "success": False,
                    "error": "NET_MISMATCH",
                    "message": (
                        f"The new track was assigned net '{preview}' instead of '{assigned.name}'. "
                        "The commit was dropped."
                    ),
                    "net": preview,
                }

            board.push_commit(commit, "Added track")
            commit = None

            found = None
            for item in board.get_tracks():
                if self._item_id(item) == created_id:
                    found = item
                    break
            actual = self._net_name(found) if found is not None else ""
            if found is None or (assigned is not None and actual != assigned.name):
                removed = False
                if found is not None:
                    removed = self._remove_committed_item(
                        board,
                        found,
                        "Remove track whose net did not match",
                    )
                elif created_item is not None:
                    removed = self._remove_committed_item(
                        board,
                        created_item,
                        "Remove unverified track",
                    )
                return {
                    "success": False,
                    "error": "NET_MISMATCH" if assigned is not None else "IPC_ERROR",
                    "message": (
                        f"Track '{created_id}' was not verified"
                        + (f" on net '{requested}'" if requested else "")
                        + (" and was removed." if removed else ". Removal failed.")
                    ),
                    "id": created_id,
                    "net": actual,
                    "removed": removed,
                }

            self._notify("track_added", {
                "start": {"x": start_x, "y": start_y},
                "end": {"x": end_x, "y": end_y},
                "width": width,
                "layer": layer,
                "net": actual,
                "id": created_id,
            })
            logger.info(
                "Added track %s from (%s, %s) to (%s, %s) mm on net '%s'",
                created_id,
                start_x,
                start_y,
                end_x,
                end_y,
                actual,
            )
            return {
                "success": True,
                "id": created_id,
                "net": actual,
                "message": f"Added track on net '{actual}'" if actual else "Added track",
            }

        except Exception as e:
            self._drop_commit(board, commit)
            logger.error(f"Failed to add track: {e}")
            return {
                "success": False,
                "error": "IPC_ERROR",
                "message": str(e),
            }

    def _routing_pads(self) -> List[Dict[str, Any]]:
        """Pad centres, copper size, and nets. Does not modify the board."""
        from kipy.proto.board.board_types_pb2 import BoardLayer
        from kipy.util.units import to_mm

        pads = []
        for footprint in self._get_board().get_footprints():
            reference = footprint.reference_field.text.value
            for pad in footprint.definition.pads:
                copper = pad.padstack.copper_layer(BoardLayer.BL_F_Cu)
                if copper is None:
                    layers = list(pad.padstack.copper_layers())
                    copper = layers[0] if layers else None
                width = to_mm(copper.size.x) if copper is not None else 0.0
                height = to_mm(copper.size.y) if copper is not None else 0.0
                pads.append({
                    "reference": reference,
                    "number": str(pad.number),
                    "net": pad.net.name if pad.net else "",
                    "x": to_mm(pad.position.x),
                    "y": to_mm(pad.position.y),
                    "width": width,
                    "height": height,
                })
        return pads

    def route_pad_to_pad(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Create one same-net route through IPC, or reject it before the commit."""
        from kicad_api.routing_checks import validate_connection

        try:
            pads = self._routing_pads()
        except Exception as exc:
            return {"success": False, "error": "IPC_ERROR", "message": str(exc), "segments": []}
        missing_size = [
            f"{pad['reference']}.{pad['number']}"
            for pad in pads
            if pad["width"] <= 0 or pad["height"] <= 0
        ]
        if missing_size:
            return {
                "success": False,
                "error": "PAD_SIZE_UNKNOWN",
                "message": "Pad copper size was not available for " + ", ".join(missing_size) + ".",
                "segments": [],
            }
        outline = self.measure_edge_cuts()
        board_box = outline.get("box") if outline.get("present") else None
        before_nets = {(pad["reference"], pad["number"]): pad["net"] for pad in pads}
        plan = validate_connection(request, pads, self.get_tracks(), board_box)
        plan["optimised"] = False
        if not plan.get("success"):
            return plan
        created = self._commit_route(plan["segments"])
        if not created.get("success"):
            created["optimised"] = False
            created["kind"] = plan.get("kind")
            return created
        try:
            after = {(pad["reference"], pad["number"]): pad["net"] for pad in self._routing_pads()}
        except Exception as exc:
            return {"success": False, "error": "IPC_ERROR", "message": str(exc), "segments": []}
        if after != before_nets:
            return {
                "success": False,
                "error": "NET_CHANGED",
                "message": "Pad nets changed while the route was committed.",
                "segments": created.get("segments", []),
            }
        created.update({
            "optimised": False,
            "kind": plan.get("kind"),
            "length": plan.get("length"),
            "net": plan.get("net"),
            "message": f"Routed {plan.get('net')} with {len(created.get('segments', []))} track(s).",
        })
        return created

    def route_from_pad_nets(self, layer: str = "F.Cu", clearance: float = 0.2) -> Dict[str, Any]:
        """Route the open board from pad nets. A duplicate or a rejected link creates no track."""
        from kicad_api.routing_checks import route_requests_from_pads

        try:
            pads = self._routing_pads()
        except Exception as exc:
            return {"success": False, "error": "IPC_ERROR", "message": str(exc), "results": []}
        requests = route_requests_from_pads(pads, layer=layer, clearance=clearance)
        results = []
        for request in requests:
            outcome = self.route_pad_to_pad(request)
            results.append({
                "sourceRef": request["sourceRef"],
                "sourcePad": request["sourcePad"],
                "destinationRef": request["destinationRef"],
                "destinationPad": request["destinationPad"],
                "net": request["net"],
                "width": request["width"],
                "success": bool(outcome.get("success")),
                "error": outcome.get("error", ""),
                "kind": outcome.get("kind", ""),
                "length": outcome.get("length"),
                "message": outcome.get("message", ""),
            })
        failures = [
            item for item in results
            if not item["success"] and item["error"] != "DUPLICATE_CONNECTION"
        ]
        return {
            "success": not failures,
            "created": sum(1 for item in results if item["success"]),
            "duplicates": sum(1 for item in results if item["error"] == "DUPLICATE_CONNECTION"),
            "links": len(results),
            "results": results,
        }

    def _commit_route(self, segments: List[Dict[str, Any]]) -> Dict[str, Any]:
        """One undoable commit. A failed read-back removes every track from that commit."""
        from kipy.board_types import Track
        from kipy.geometry import Vector2
        from kipy.proto.board.board_types_pb2 import BoardLayer
        from kipy.util.units import from_mm, to_mm

        layer_map = {
            "F.Cu": BoardLayer.BL_F_Cu,
            "B.Cu": BoardLayer.BL_B_Cu,
        }
        board = None
        commit = None
        try:
            board = self._get_board()
            items = []
            for segment in segments:
                layer = segment["layer"]
                if layer not in layer_map:
                    return {
                        "success": False,
                        "error": "UNSUPPORTED_LAYER",
                        "message": f"Layer '{layer}' cannot be created through this IPC path.",
                        "segments": [],
                    }
                assigned = self._find_existing_net(segment["net"])
                if assigned is None:
                    return {
                        "success": False,
                        "error": "NET_NOT_FOUND",
                        "message": f"Net '{segment['net']}' does not exist. No track was added.",
                        "segments": [],
                    }
                track = Track()
                track.start = Vector2.from_xy(from_mm(segment["start"]["x"]), from_mm(segment["start"]["y"]))
                track.end = Vector2.from_xy(from_mm(segment["end"]["x"]), from_mm(segment["end"]["y"]))
                track.width = from_mm(segment["width"])
                track.layer = layer_map[layer]
                track.net = assigned
                items.append(track)

            commit = board.begin_commit()
            created_raw = board.create_items(items)
            created_list = list(created_raw) if isinstance(created_raw, (list, tuple)) else [created_raw]
            if len(created_list) != len(items) or any(not self._item_id(item) for item in created_list):
                self._drop_commit(board, commit)
                commit = None
                return {
                    "success": False,
                    "error": "IPC_ERROR",
                    "message": "KiCad did not return an id for every track. The commit was dropped.",
                    "segments": [],
                }
            for item, segment in zip(created_list, segments):
                preview = self._net_name(item)
                if preview and preview != segment["net"]:
                    self._drop_commit(board, commit)
                    commit = None
                    return {
                        "success": False,
                        "error": "NET_MISMATCH",
                        "message": f"A new track was assigned '{preview}' instead of '{segment['net']}'. The commit was dropped.",
                        "segments": [],
                    }
            board.push_commit(commit, f"Routed {segments[0]['net']}")
            commit = None

            found = {self._item_id(item): item for item in board.get_tracks()}
            read_back = []
            verified = []
            for item, segment in zip(created_list, segments):
                ident = self._item_id(item)
                live = found.get(ident)
                if live is None:
                    self._remove_route(board, verified or created_list)
                    return {
                        "success": False,
                        "error": "IPC_VERIFY_FAILED",
                        "message": f"Track {ident} was not on the board after the commit.",
                        "segments": [],
                    }
                actual_net = self._net_name(live)
                start = (to_mm(live.start.x), to_mm(live.start.y))
                end = (to_mm(live.end.x), to_mm(live.end.y))
                expected_start = (segment["start"]["x"], segment["start"]["y"])
                expected_end = (segment["end"]["x"], segment["end"]["y"])
                width = to_mm(live.width)
                if (
                    actual_net != segment["net"]
                    or abs(width - segment["width"]) > 0.01
                    or not self._points_match(start, expected_start)
                    or not self._points_match(end, expected_end)
                ):
                    self._remove_route(board, list(found[self._item_id(piece)] for piece in created_list if self._item_id(piece) in found))
                    return {
                        "success": False,
                        "error": "IPC_VERIFY_FAILED",
                        "message": "A committed track did not match the requested end, width, or net and was removed.",
                        "segments": [],
                    }
                verified.append(live)
                read_back.append({
                    "id": ident,
                    "net": actual_net,
                    "width": width,
                    "layer": segment["layer"],
                    "start": {"x": start[0], "y": start[1]},
                    "end": {"x": end[0], "y": end[1]},
                })
            return {"success": True, "segments": read_back}
        except Exception as exc:
            self._drop_commit(board, commit)
            return {"success": False, "error": "IPC_ERROR", "message": str(exc), "segments": []}

    @staticmethod
    def _points_match(actual, expected, tolerance: float = 0.02) -> bool:
        return abs(actual[0] - expected[0]) <= tolerance and abs(actual[1] - expected[1]) <= tolerance

    def _remove_route(self, board: Any, items: List[Any]) -> None:
        if not items:
            return
        repair = None
        try:
            repair = board.begin_commit()
            board.remove_items(items)
            board.push_commit(repair, "Remove route that failed read-back")
        except Exception:
            logger.exception("Failed to remove an unverified route")
            self._drop_commit(board, repair)

    def delete_tracks(self, idents: List[str]) -> Dict[str, Any]:
        """Remove tracks by id in one commit and read the board back."""
        wanted = {str(ident) for ident in idents}
        board = None
        commit = None
        try:
            board = self._get_board()
            chosen = [track for track in board.get_tracks() if self._item_id(track) in wanted]
            if len(chosen) != len(wanted):
                return {
                    "success": False,
                    "error": "MISSING_TRACK",
                    "message": "Not every requested track is on the board. Nothing was deleted.",
                }
            commit = board.begin_commit()
            board.remove_items(chosen)
            board.push_commit(commit, "Remove crossing route")
            commit = None
            remaining = {self._item_id(track) for track in board.get_tracks()}
            if wanted & remaining:
                return {
                    "success": False,
                    "error": "IPC_VERIFY_FAILED",
                    "message": "A track was still present after the delete commit.",
                }
            return {"success": True, "deleted": sorted(wanted)}
        except Exception as exc:
            self._drop_commit(board, commit)
            return {"success": False, "error": "IPC_ERROR", "message": str(exc)}

    def add_via(
        self,
        x: float,
        y: float,
        diameter: float = 0.8,
        drill: float = 0.4,
        net_name: Optional[str] = None,
        via_type: str = "through"
    ) -> bool:
        """
        Add a via to the board.

        The via appears immediately in the KiCAD UI.
        """
        try:
            from kipy.board_types import Via
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import ViaType

            board = self._get_board()

            # Create via
            via = Via()
            via.position = Vector2.from_xy(from_mm(x), from_mm(y))
            via.diameter = from_mm(diameter)
            via.drill_diameter = from_mm(drill)

            # Set via type (enum values: VT_THROUGH=1, VT_BLIND_BURIED=2, VT_MICRO=3)
            type_map = {
                "through": ViaType.VT_THROUGH,
                "blind": ViaType.VT_BLIND_BURIED,
                "micro": ViaType.VT_MICRO,
            }
            via.type = type_map.get(via_type, ViaType.VT_THROUGH)

            # Set net if specified
            if net_name:
                nets = board.get_nets()
                for net in nets:
                    if net.name == net_name:
                        via.net = net
                        break

            # Add via with transaction
            commit = board.begin_commit()
            board.create_items(via)
            board.push_commit(commit, "Added via")

            self._notify("via_added", {
                "position": {"x": x, "y": y},
                "diameter": diameter,
                "drill": drill,
                "net": net_name,
                "type": via_type
            })

            logger.info(f"Added via at ({x}, {y}) mm")
            return True

        except Exception as e:
            logger.error(f"Failed to add via: {e}")
            return False

    def add_text(
        self,
        text: str,
        x: float,
        y: float,
        layer: str = "F.SilkS",
        size: float = 1.0,
        rotation: float = 0
    ) -> bool:
        """Add text to the board."""
        try:
            from kipy.board_types import BoardText
            from kipy.geometry import Vector2, Angle
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self._get_board()

            # Create text
            board_text = BoardText()
            board_text.value = text
            board_text.position = Vector2.from_xy(from_mm(x), from_mm(y))
            board_text.angle = Angle.from_degrees(rotation)

            # Set layer
            layer_map = {
                "F.SilkS": BoardLayer.BL_F_SilkS,
                "B.SilkS": BoardLayer.BL_B_SilkS,
                "F.Cu": BoardLayer.BL_F_Cu,
                "B.Cu": BoardLayer.BL_B_Cu,
            }
            board_text.layer = layer_map.get(layer, BoardLayer.BL_F_SilkS)

            # Add text with transaction
            commit = board.begin_commit()
            board.create_items(board_text)
            board.push_commit(commit, f"Added text: {text}")

            self._notify("text_added", {
                "text": text,
                "position": {"x": x, "y": y},
                "layer": layer
            })

            return True

        except Exception as e:
            logger.error(f"Failed to add text: {e}")
            return False

    def get_tracks(self) -> List[Dict[str, Any]]:
        """Get all tracks on the board."""
        try:
            from kipy.util.units import to_mm

            board = self._get_board()
            tracks = board.get_tracks()

            result = []
            for track in tracks:
                try:
                    result.append({
                        "start": {
                            "x": to_mm(track.start.x),
                            "y": to_mm(track.start.y)
                        },
                        "end": {
                            "x": to_mm(track.end.x),
                            "y": to_mm(track.end.y)
                        },
                        "width": to_mm(track.width),
                        "layer": str(track.layer),
                        "net": track.net.name if track.net else "",
                        "id": self._item_id(track)
                    })
                except Exception as e:
                    logger.warning(f"Error processing track: {e}")
                    continue

            return result

        except Exception as e:
            logger.error(f"Failed to get tracks: {e}")
            return []

    def get_vias(self) -> List[Dict[str, Any]]:
        """Get all vias on the board."""
        try:
            from kipy.util.units import to_mm

            board = self._get_board()
            vias = board.get_vias()

            result = []
            for via in vias:
                try:
                    result.append({
                        "position": {
                            "x": to_mm(via.position.x),
                            "y": to_mm(via.position.y)
                        },
                        "diameter": to_mm(via.diameter),
                        "drill": to_mm(via.drill_diameter),
                        "net": via.net.name if via.net else "",
                        "type": str(via.type),
                        "id": self._item_id(via)
                    })
                except Exception as e:
                    logger.warning(f"Error processing via: {e}")
                    continue

            return result

        except Exception as e:
            logger.error(f"Failed to get vias: {e}")
            return []

    def get_nets(self) -> List[Dict[str, Any]]:
        """Get all nets on the board."""
        try:
            board = self._get_board()
            nets = board.get_nets()

            result = []
            for net in nets:
                try:
                    result.append({
                        "name": net.name,
                        "code": net.code if hasattr(net, 'code') else 0
                    })
                except Exception as e:
                    logger.warning(f"Error processing net: {e}")
                    continue

            return result

        except Exception as e:
            logger.error(f"Failed to get nets: {e}")
            return []

    def add_zone(
        self,
        points: List[Dict[str, float]],
        layer: str = "F.Cu",
        net_name: Optional[str] = None,
        clearance: float = 0.5,
        min_thickness: float = 0.25,
        priority: int = 0,
        fill_mode: str = "solid",
        name: str = ""
    ) -> bool:
        """
        Add a copper pour zone to the board.

        The zone appears immediately in the KiCAD UI.

        Args:
            points: List of points defining the zone outline, e.g. [{"x": 0, "y": 0}, ...]
            layer: Layer name (F.Cu, B.Cu, etc.)
            net_name: Net to connect the zone to (e.g., "GND")
            clearance: Clearance from other copper in mm
            min_thickness: Minimum copper thickness in mm
            priority: Zone priority (higher = fills first)
            fill_mode: "solid" or "hatched"
            name: Optional zone name
        """
        try:
            from kipy.board_types import Zone, ZoneFillMode, ZoneType
            from kipy.geometry import PolyLine, PolyLineNode, Vector2
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self._get_board()

            if len(points) < 3:
                logger.error("Zone requires at least 3 points")
                return False

            # Create zone
            zone = Zone()
            zone.type = ZoneType.ZT_COPPER

            # Set layer
            layer_map = {
                "F.Cu": BoardLayer.BL_F_Cu,
                "B.Cu": BoardLayer.BL_B_Cu,
                "In1.Cu": BoardLayer.BL_In1_Cu,
                "In2.Cu": BoardLayer.BL_In2_Cu,
                "In3.Cu": BoardLayer.BL_In3_Cu,
                "In4.Cu": BoardLayer.BL_In4_Cu,
            }
            zone.layers = [layer_map.get(layer, BoardLayer.BL_F_Cu)]

            # Set net if specified
            if net_name:
                nets = board.get_nets()
                for net in nets:
                    if net.name == net_name:
                        zone.net = net
                        break

            # Set zone properties
            zone.clearance = from_mm(clearance)
            zone.min_thickness = from_mm(min_thickness)
            zone.priority = priority

            if name:
                zone.name = name

            # Set fill mode
            if fill_mode == "hatched":
                zone.fill_mode = ZoneFillMode.ZFM_HATCHED
            else:
                zone.fill_mode = ZoneFillMode.ZFM_SOLID

            # Create outline polyline
            outline = PolyLine()
            outline.closed = True

            for point in points:
                x = point.get("x", 0)
                y = point.get("y", 0)
                node = PolyLineNode.from_xy(from_mm(x), from_mm(y))
                outline.append(node)

            # Set the outline on the zone
            # Note: Zone outline is set via the proto directly since kipy
            # doesn't expose a direct setter for creating new zones
            zone._proto.outline.polygons.add()
            zone._proto.outline.polygons[0].outline.CopyFrom(outline._proto)

            # Add zone with transaction
            commit = board.begin_commit()
            board.create_items(zone)
            board.push_commit(commit, f"Added copper zone on {layer}")

            self._notify("zone_added", {
                "layer": layer,
                "net": net_name,
                "points": len(points),
                "priority": priority
            })

            logger.info(f"Added zone on {layer} with {len(points)} points")
            return True

        except Exception as e:
            logger.error(f"Failed to add zone: {e}")
            return False

    def get_zones(self) -> List[Dict[str, Any]]:
        """Get all zones on the board."""
        try:
            from kipy.util.units import to_mm

            board = self._get_board()
            zones = board.get_zones()

            result = []
            for zone in zones:
                try:
                    result.append({
                        "name": zone.name if hasattr(zone, 'name') else "",
                        "net": zone.net.name if zone.net else "",
                        "priority": zone.priority if hasattr(zone, 'priority') else 0,
                        "layers": [str(l) for l in zone.layers] if hasattr(zone, 'layers') else [],
                        "filled": zone.filled if hasattr(zone, 'filled') else False,
                        "id": self._item_id(zone)
                    })
                except Exception as e:
                    logger.warning(f"Error processing zone: {e}")
                    continue

            return result

        except Exception as e:
            logger.error(f"Failed to get zones: {e}")
            return []

    def refill_zones(self) -> bool:
        """Refill all copper pour zones."""
        try:
            board = self._get_board()
            board.refill_zones()
            self._notify("zones_refilled", {})
            return True
        except Exception as e:
            logger.error(f"Failed to refill zones: {e}")
            return False

    def create_verified_zone(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Create one copper zone and read its net back. A missing net creates nothing."""
        layer = params.get("layer")
        net_name = params.get("net")
        points = params.get("points")
        unit = params.get("unit", "mm")
        if not isinstance(layer, str) or not layer.strip():
            return {"success": False, "error": "INVALID_ARGUMENT", "message": "layer is required."}
        if not isinstance(net_name, str) or not net_name.strip():
            return {"success": False, "error": "INVALID_ARGUMENT", "message": "net is required."}
        if unit not in ("mm", "inch"):
            return {"success": False, "error": "INVALID_ARGUMENT", "message": "unit must be mm or inch."}
        if not isinstance(points, list) or len(points) < 3:
            return {
                "success": False,
                "error": "INVALID_ARGUMENT",
                "message": "A zone outline needs at least 3 points.",
            }
        pad_connection = params.get("padConnection")
        connection_map = {"thermal": "ZCS_THERMAL", "solid": "ZCS_FULL", "none": "ZCS_NONE"}
        if pad_connection is not None and pad_connection not in connection_map:
            return {
                "success": False,
                "error": "INVALID_ARGUMENT",
                "message": "padConnection must be thermal, solid, or none.",
            }

        scale = 25.4 if unit == "inch" else 1.0
        outline = []
        for point in points:
            if not isinstance(point, dict):
                return {"success": False, "error": "INVALID_ARGUMENT", "message": "Each point needs x and y."}
            try:
                outline.append((float(point["x"]) * scale, float(point["y"]) * scale))
            except (KeyError, TypeError, ValueError):
                return {"success": False, "error": "INVALID_ARGUMENT", "message": "Each point needs numeric x and y."}

        def length(value):
            if value is None:
                return None
            return float(value) * scale

        try:
            clearance = length(params.get("clearance"))
            min_width = length(params.get("minWidth"))
        except (TypeError, ValueError):
            return {"success": False, "error": "INVALID_ARGUMENT", "message": "clearance and minWidth must be numbers."}

        net_name = net_name.strip()
        assigned = self._find_existing_net(net_name)
        if assigned is None:
            return {
                "success": False,
                "error": "NET_NOT_FOUND",
                "message": f"Net '{net_name}' does not exist, so no zone was created.",
            }

        commit = None
        board = None
        try:
            from kipy.board_types import Zone, ZoneConnectionStyle, ZoneType
            from kipy.geometry import PolyLine, PolyLineNode
            from kipy.proto.board.board_types_pb2 import BoardLayer
            from kipy.util.units import from_mm, to_mm

            board = self._get_board()
            standard_layers = {
                "F.Cu": BoardLayer.BL_F_Cu,
                "B.Cu": BoardLayer.BL_B_Cu,
                "In1.Cu": BoardLayer.BL_In1_Cu,
                "In2.Cu": BoardLayer.BL_In2_Cu,
                "In3.Cu": BoardLayer.BL_In3_Cu,
                "In4.Cu": BoardLayer.BL_In4_Cu,
            }
            if layer.strip() in standard_layers:
                layer_id = standard_layers[layer.strip()]
            else:
                layer_id = board.get_layer_by_name(layer.strip())
                if layer_id == BoardLayer.BL_UNDEFINED:
                    return {
                        "success": False,
                        "error": "INVALID_ARGUMENT",
                        "message": f"Layer '{layer}' is not a layer on this board.",
                    }

            zone = Zone()
            zone.type = ZoneType.ZT_COPPER
            zone.layers = [layer_id]
            zone.net = assigned
            if clearance is not None:
                zone.clearance = from_mm(clearance)
            if min_width is not None:
                zone.min_thickness = from_mm(min_width)
            if pad_connection is not None:
                zone.connection.zone_connection = getattr(ZoneConnectionStyle, connection_map[pad_connection])

            polyline = PolyLine()
            polyline.closed = True
            for x_mm, y_mm in outline:
                polyline.append(PolyLineNode.from_xy(from_mm(x_mm), from_mm(y_mm)))
            zone._proto.outline.polygons.add()
            zone._proto.outline.polygons[0].outline.CopyFrom(polyline._proto)

            commit = board.begin_commit()
            created_raw = board.create_items(zone)
            created_list = list(created_raw) if isinstance(created_raw, (list, tuple)) else [created_raw]
            created = created_list[0] if created_list else None
            created_id = self._item_id(created) if created is not None else ""
            if not created_id:
                self._drop_commit(board, commit)
                commit = None
                return {
                    "success": False,
                    "error": "IPC_ERROR",
                    "message": "KiCad did not return an id for the new zone. The commit was dropped.",
                }
            board.push_commit(commit, f"Added zone on {net_name}")
            commit = None

            found = None
            for item in board.get_zones():
                if self._item_id(item) == created_id:
                    found = item
                    break
            actual_net = self._net_name(found) if found is not None else ""
            actual_connection = None
            if found is not None and pad_connection is not None:
                try:
                    actual_connection = ZoneConnectionStyle.Name(found.connection.zone_connection)
                except Exception:
                    actual_connection = ""
            expected_connection = connection_map.get(pad_connection) if pad_connection else None
            mismatch = (
                found is None
                or actual_net != net_name
                or (expected_connection is not None and actual_connection != expected_connection)
            )
            if mismatch:
                removed = False
                if found is not None:
                    removed = self._remove_committed_item(board, found, "Remove zone that failed verification")
                return {
                    "success": False,
                    "error": "NET_MISMATCH" if actual_net != net_name else "IPC_ERROR",
                    "message": "The new zone did not match the request and was not left as a successful edit.",
                    "id": created_id,
                    "net": actual_net,
                    "removed": removed,
                }
            return {
                "success": True,
                "id": created_id,
                "net": actual_net,
                "layer": layer.strip(),
                "pointCount": len(outline),
                "padConnection": pad_connection,
                "clearance": None if found.clearance is None else to_mm(found.clearance),
                "message": f"Added zone {created_id} on net '{actual_net}'.",
            }
        except Exception as exc:
            self._drop_commit(board, commit)
            logger.error("Failed to add zone: %s", exc)
            return {"success": False, "error": "IPC_ERROR", "message": str(exc)}

    def annotate_component(self, reference: str, annotation: str, visible: Optional[bool]) -> Dict[str, Any]:
        """Append text to a footprint description and read it back."""
        if not isinstance(reference, str) or not reference.strip():
            return {"success": False, "error": "INVALID_ARGUMENT", "message": "reference is required."}
        if not isinstance(annotation, str) or not annotation.strip():
            return {"success": False, "error": "INVALID_ARGUMENT", "message": "annotation is required."}
        if visible is not None and not isinstance(visible, bool):
            return {"success": False, "error": "INVALID_ARGUMENT", "message": "visible must be a boolean."}
        reference = reference.strip()
        annotation = annotation.strip()
        show = True if visible is None else visible

        commit = None
        board = None
        try:
            board = self._get_board()
            target = None
            for footprint in board.get_footprints():
                if footprint.reference_field and footprint.reference_field.text.value == reference:
                    target = footprint
                    break
            if target is None:
                return {"success": False, "error": "NOT_FOUND", "message": f"Component {reference} was not found."}

            previous = target.description_field.text.value or ""
            previous_visible = bool(target.description_field.visible)
            lines = [line for line in previous.splitlines() if line]
            updated = previous if annotation in lines else (annotation if not previous else previous + "\n" + annotation)
            target.description_field.text.value = updated
            target.description_field.visible = show
            footprint_id = self._item_id(target)

            commit = board.begin_commit()
            board.update_items([target])
            board.push_commit(commit, f"Annotated {reference}")
            commit = None

            confirmed = None
            for footprint in board.get_footprints():
                if self._item_id(footprint) == footprint_id:
                    confirmed = footprint
                    break
            confirmed_text = "" if confirmed is None else (confirmed.description_field.text.value or "")
            confirmed_visible = None if confirmed is None else bool(confirmed.description_field.visible)
            same_reference = (
                confirmed is not None
                and confirmed.reference_field.text.value == reference
            )
            if not same_reference or annotation not in confirmed_text.splitlines() or confirmed_visible is not show:
                if confirmed is not None:
                    confirmed.description_field.text.value = previous
                    confirmed.description_field.visible = previous_visible
                    repair = board.begin_commit()
                    try:
                        board.update_items([confirmed])
                        board.push_commit(repair, f"Restore description of {reference}")
                    except Exception:
                        self._drop_commit(board, repair)
                return {
                    "success": False,
                    "error": "IPC_ERROR",
                    "message": f"The annotation was not readable on {reference} after the commit.",
                    "reference": reference,
                    "id": footprint_id,
                }
            return {
                "success": True,
                "reference": reference,
                "id": footprint_id,
                "annotation": annotation,
                "description": confirmed_text,
                "visible": confirmed_visible,
                "message": f"Annotated {reference}.",
            }
        except Exception as exc:
            self._drop_commit(board, commit)
            logger.error("Failed to annotate %s: %s", reference, exc)
            return {"success": False, "error": "IPC_ERROR", "message": str(exc)}

    def group_components(self, references: List[str], group_name: str) -> Dict[str, Any]:
        """Create a named group around existing footprints and read the members back."""
        if not isinstance(group_name, str) or not group_name.strip():
            return {"success": False, "error": "INVALID_ARGUMENT", "message": "groupName is required."}
        if not isinstance(references, list) or not references:
            return {"success": False, "error": "INVALID_ARGUMENT", "message": "references must list at least one component."}
        cleaned = []
        for reference in references:
            if not isinstance(reference, str) or not reference.strip():
                return {"success": False, "error": "INVALID_ARGUMENT", "message": "Every reference must be a non-empty string."}
            if reference.strip() not in cleaned:
                cleaned.append(reference.strip())
        group_name = group_name.strip()

        commit = None
        board = None
        try:
            from kipy.board_types import Group

            board = self._get_board()
            for existing in board.get_groups():
                if existing.name == group_name:
                    return {
                        "success": False,
                        "error": "ALREADY_EXISTS",
                        "message": f"Group '{group_name}' already exists and was not modified.",
                        "id": self._item_id(existing),
                    }
            found = []
            missing = []
            for reference in cleaned:
                match = None
                for footprint in board.get_footprints():
                    if footprint.reference_field and footprint.reference_field.text.value == reference:
                        match = footprint
                        break
                if match is None:
                    missing.append(reference)
                else:
                    found.append(match)
            if missing:
                return {
                    "success": False,
                    "error": "NOT_FOUND",
                    "message": "These components were not found: " + ", ".join(missing),
                }

            member_ids = [self._item_id(item) for item in found]
            group = Group()
            group._proto.name = group_name
            group.items = found
            commit = board.begin_commit()
            created_raw = board.create_items(group)
            created_list = list(created_raw) if isinstance(created_raw, (list, tuple)) else [created_raw]
            created = created_list[0] if created_list else None
            created_id = self._item_id(created) if created is not None else ""
            if not created_id:
                self._drop_commit(board, commit)
                commit = None
                return {
                    "success": False,
                    "error": "IPC_ERROR",
                    "message": "KiCad did not return an id for the new group. The commit was dropped.",
                }
            board.push_commit(commit, f"Grouped {group_name}")
            commit = None

            confirmed = None
            for item in board.get_groups():
                if self._item_id(item) == created_id or item.name == group_name:
                    confirmed = item
                    break
            confirmed_ids = []
            if confirmed is not None:
                confirmed_ids = [self._item_id(item) for item in confirmed.items]
                if not confirmed_ids:
                    confirmed_ids = [str(getattr(ident, "value", ident)) for ident in confirmed._item_ids]
            if confirmed is None or confirmed.name != group_name or set(confirmed_ids) != set(member_ids):
                removed = False
                if confirmed is not None:
                    removed = self._remove_committed_item(board, confirmed, "Remove group that failed verification")
                return {
                    "success": False,
                    "error": "IPC_ERROR",
                    "message": "The group members did not match the request.",
                    "id": created_id,
                    "removed": removed,
                }
            return {
                "success": True,
                "id": self._item_id(confirmed),
                "groupName": confirmed.name,
                "references": cleaned,
                "memberIds": member_ids,
                "message": f"Grouped {len(cleaned)} component(s) as {group_name}.",
            }
        except Exception as exc:
            self._drop_commit(board, commit)
            logger.error("Failed to group components: %s", exc)
            return {"success": False, "error": "IPC_ERROR", "message": str(exc)}

    def get_selection(self) -> List[Dict[str, Any]]:
        """Get currently selected items in the KiCAD UI."""
        try:
            board = self._get_board()
            selection = board.get_selection()

            result = []
            for item in selection:
                result.append({
                    "type": type(item).__name__,
                    "id": self._item_id(item)
                })

            return result
        except Exception as e:
            logger.error(f"Failed to get selection: {e}")
            return []

    def clear_selection(self) -> bool:
        """Clear the current selection in KiCAD UI."""
        try:
            board = self._get_board()
            board.clear_selection()
            return True
        except Exception as e:
            logger.error(f"Failed to clear selection: {e}")
            return False


# Export for factory
__all__ = ['IPCBackend', 'IPCBoardAPI']



