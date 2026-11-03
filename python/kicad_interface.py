#!/usr/bin/env python3
"""
KiCAD Python Interface Script for Model Context Protocol

This script handles communication between the MCP TypeScript server
and KiCAD's Python API (pcbnew). It receives commands via stdin as
JSON and returns responses via stdout also as JSON.
"""

import sys
import json
import traceback
import logging
import os
from typing import Dict, Any, Optional

# Import tool schemas and resource definitions
from schemas.tool_schemas import TOOL_SCHEMAS
from resources.resource_definitions import RESOURCE_DEFINITIONS, handle_resource_read

# Configure logging
log_dir = os.path.join(os.path.expanduser("~"), ".kicad-mcp", "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "kicad_interface.log")

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(log_file)],
)
logger = logging.getLogger("kicad_interface")

# Log Python environment details
logger.info(f"Python version: {sys.version}")
logger.info(f"Python executable: {sys.executable}")
logger.info(f"Platform: {sys.platform}")
logger.info(f"Working directory: {os.getcwd()}")

# Windows-specific diagnostics
if sys.platform == "win32":
    logger.info("=== Windows Environment Diagnostics ===")
    logger.info(f"PYTHONPATH: {os.environ.get('PYTHONPATH', 'NOT SET')}")
    logger.info(f"PATH: {os.environ.get('PATH', 'NOT SET')[:200]}...")  # Truncate PATH

    # Check for common KiCAD installations
    common_kicad_paths = [r"C:\Program Files\KiCad", r"C:\Program Files (x86)\KiCad"]

    found_kicad = False
    for base_path in common_kicad_paths:
        if os.path.exists(base_path):
            logger.info(f"Found KiCAD installation at: {base_path}")
            # List versions
            try:
                versions = [
                    d
                    for d in os.listdir(base_path)
                    if os.path.isdir(os.path.join(base_path, d))
                ]
                logger.info(f"  Versions found: {', '.join(versions)}")
                for version in versions:
                    python_path = os.path.join(
                        base_path, version, "lib", "python3", "dist-packages"
                    )
                    if os.path.exists(python_path):
                        logger.info(f"  ✓ Python path exists: {python_path}")
                        found_kicad = True
                    else:
                        logger.warning(f"  ✗ Python path missing: {python_path}")
            except Exception as e:
                logger.warning(f"  Could not list versions: {e}")

    if not found_kicad:
        logger.warning("No KiCAD installations found in standard locations!")
        logger.warning(
            "Please ensure KiCAD 9.0+ is installed from https://www.kicad.org/download/windows/"
        )

    logger.info("========================================")

# Add utils directory to path for imports
utils_dir = os.path.join(os.path.dirname(__file__))
if utils_dir not in sys.path:
    sys.path.insert(0, utils_dir)

# Import platform helper and add KiCAD paths
from utils.platform_helper import PlatformHelper
from utils.kicad_process import check_and_launch_kicad, KiCADProcessManager

logger.info(f"Detecting KiCAD Python paths for {PlatformHelper.get_platform_name()}...")
paths_added = PlatformHelper.add_kicad_to_python_path()

if paths_added:
    logger.info("Successfully added KiCAD Python paths to sys.path")
else:
    logger.warning(
        "No KiCAD Python paths found - attempting to import pcbnew from system path"
    )

logger.info(f"Current Python path: {sys.path}")

# Check if auto-launch is enabled
AUTO_LAUNCH_KICAD = os.environ.get("KICAD_AUTO_LAUNCH", "false").lower() == "true"
if AUTO_LAUNCH_KICAD:
    logger.info("KiCAD auto-launch enabled")

# Check which backend to use
# KICAD_BACKEND can be: 'auto', 'ipc', or 'swig'
KICAD_BACKEND = os.environ.get("KICAD_BACKEND", "auto").lower()
logger.info(f"KiCAD backend preference: {KICAD_BACKEND}")

# Try to use IPC backend first if available and preferred
USE_IPC_BACKEND = False
ipc_backend = None

if KICAD_BACKEND in ("auto", "ipc"):
    try:
        logger.info("Checking IPC backend availability...")
        from kicad_api.ipc_backend import IPCBackend

        # Try to connect to running KiCAD
        ipc_backend = IPCBackend()
        if ipc_backend.connect():
            USE_IPC_BACKEND = True
            logger.info(f"✓ Using IPC backend - real-time UI sync enabled!")
            logger.info(f"  KiCAD version: {ipc_backend.get_version()}")
        else:
            logger.info("IPC backend available but KiCAD not running with IPC enabled")
            ipc_backend = None
    except ImportError:
        logger.info("IPC backend not available (kicad-python not installed)")
    except Exception as e:
        logger.info(f"IPC backend connection failed: {e}")
        ipc_backend = None

# Fall back to SWIG backend if IPC not available
if not USE_IPC_BACKEND and KICAD_BACKEND != "ipc":
    # Import KiCAD's Python API (SWIG)
    try:
        logger.info("Attempting to import pcbnew module (SWIG backend)...")
        import pcbnew  # type: ignore

        logger.info(f"Successfully imported pcbnew module from: {pcbnew.__file__}")
        logger.info(f"pcbnew version: {pcbnew.GetBuildVersion()}")
        logger.warning("Using SWIG backend - changes require manual reload in KiCAD UI")
    except ImportError as e:
        logger.error(f"Failed to import pcbnew module: {e}")
        logger.error(f"Current sys.path: {sys.path}")

        # Platform-specific help message
        help_message = ""
        if sys.platform == "win32":
            help_message = """
Windows Troubleshooting:
1. Verify KiCAD is installed: C:\\Program Files\\KiCad\\9.0
2. Check PYTHONPATH environment variable points to:
   C:\\Program Files\\KiCad\\9.0\\lib\\python3\\dist-packages
3. Test with: "C:\\Program Files\\KiCad\\9.0\\bin\\python.exe" -c "import pcbnew"
4. Log file location: %USERPROFILE%\\.kicad-mcp\\logs\\kicad_interface.log
5. Run setup-windows.ps1 for automatic configuration
"""
        elif sys.platform == "darwin":
            help_message = """
macOS Troubleshooting:
1. Verify KiCAD is installed: /Applications/KiCad/KiCad.app
2. Check PYTHONPATH points to KiCAD's Python packages
3. Run: python3 -c "import pcbnew" to test
"""
        else:  # Linux
            help_message = """
Linux Troubleshooting:
1. Verify KiCAD is installed: apt list --installed | grep kicad
2. Check: /usr/lib/kicad/lib/python3/dist-packages exists
3. Test: python3 -c "import pcbnew"
"""

        logger.error(help_message)

        error_response = {
            "success": False,
            "message": "Failed to import pcbnew module - KiCAD Python API not found",
            "errorDetails": f"Error: {str(e)}\n\n{help_message}\n\nPython sys.path:\n{chr(10).join(sys.path)}",
        }
        print(json.dumps(error_response))
        sys.exit(1)
    except Exception as e:
        logger.error(f"Unexpected error importing pcbnew: {e}")
        logger.error(traceback.format_exc())
        error_response = {
            "success": False,
            "message": "Error importing pcbnew module",
            "errorDetails": str(e),
        }
        print(json.dumps(error_response))
        sys.exit(1)

# If IPC-only mode requested but not available, exit with error
elif KICAD_BACKEND == "ipc" and not USE_IPC_BACKEND:
    error_response = {
        "success": False,
        "message": "IPC backend requested but not available",
        "errorDetails": "KiCAD must be running with IPC API enabled. Enable at: Preferences > Plugins > Enable IPC API Server",
    }
    print(json.dumps(error_response))
    sys.exit(1)

# Import command handlers
try:
    logger.info("Importing command handlers...")
    from commands.project import ProjectCommands
    from commands.board import BoardCommands
    from commands.component import ComponentCommands
    from commands.routing import RoutingCommands
    from commands.design_rules import DesignRuleCommands
    from commands.export import ExportCommands
    from commands.schematic import SchematicManager
    from commands.component_schematic import ComponentManager
    from commands.connection_schematic import ConnectionManager
    from commands.library_schematic import LibraryManager as SchematicLibraryManager
    from commands.library import (
        LibraryManager as FootprintLibraryManager,
        LibraryCommands,
    )
    from commands.library_symbol import SymbolLibraryManager, SymbolLibraryCommands
    from commands.jlcpcb import JLCPCBClient, test_jlcpcb_connection
    from commands.jlcpcb_parts import JLCPCBPartsManager
    from commands.datasheet_manager import DatasheetManager
    from commands.footprint import FootprintCreator
    from commands.symbol_creator import SymbolCreator
    from commands.freerouting import FreeroutingCommands

    logger.info("Successfully imported all command handlers")
except ImportError as e:
    logger.error(f"Failed to import command handlers: {e}")
    error_response = {
        "success": False,
        "message": "Failed to import command handlers",
        "errorDetails": str(e),
    }
    print(json.dumps(error_response))
    sys.exit(1)

from kicad_api.pcb_safety import (
    GUARDED_PCB_COMMANDS,
    access_purpose,
    evaluate_pcb_file_access,
    ipc_unavailable_result,
    lock_file_present,
    normalize_pcb_path,
    swig_target_paths,
)


class KiCADInterface:
    """Main interface class to handle KiCAD operations"""

    def __init__(self):
        """Initialize the interface and command handlers"""
        self.board = None
        self.project_filename = None
        self.use_ipc = USE_IPC_BACKEND
        self.ipc_backend = ipc_backend
        self.ipc_board_api = None
        self._offline_owned_pcb_paths = set()
        self._live_paths_unknown = False

        if self.use_ipc:
            logger.info("Initializing with IPC backend (real-time UI sync enabled)")
            try:
                self.ipc_board_api = self.ipc_backend.get_board()
                logger.info("✓ Got IPC board API")
            except Exception as e:
                logger.warning(f"Could not get IPC board API: {e}")
        else:
            logger.info("Initializing with SWIG backend")

        logger.info("Initializing command handlers...")

        # Initialize footprint library manager
        self.footprint_library = FootprintLibraryManager()

        # Initialize command handlers
        self.project_commands = ProjectCommands(self.board)
        self.board_commands = BoardCommands(self.board)
        self.component_commands = ComponentCommands(self.board, self.footprint_library)
        self.routing_commands = RoutingCommands(self.board)
        self.freerouting_commands = FreeroutingCommands(self.board)
        self.design_rule_commands = DesignRuleCommands(self.board)
        self.export_commands = ExportCommands(self.board)
        self.library_commands = LibraryCommands(self.footprint_library)
        self._current_project_path: Optional[Path] = None  # set when boardPath is known

        # Initialize symbol library manager (for searching local KiCad symbol libraries)
        self.symbol_library_commands = SymbolLibraryCommands()

        # Initialize JLCPCB API integration
        self.jlcpcb_client = JLCPCBClient()  # Official API (requires auth)
        from commands.jlcsearch import JLCSearchClient

        self.jlcsearch_client = JLCSearchClient()  # Public API (no auth required)
        self.jlcpcb_parts = JLCPCBPartsManager()

        # Schematic-related classes don't need board reference
        # as they operate directly on schematic files

        # Command routing dictionary
        self.command_routes = {
            # Project commands
            "create_project": self._guarded_create_project,
            "open_project": self._guarded_open_project,
            "save_project": self._guarded_save_project,
            "snapshot_project": self._handle_snapshot_project,
            "get_project_info": self.project_commands.get_project_info,
            # Board commands
            "set_board_size": self.board_commands.set_board_size,
            "add_layer": self.board_commands.add_layer,
            "set_active_layer": self.board_commands.set_active_layer,
            "get_board_info": self.board_commands.get_board_info,
            "get_layer_list": self.board_commands.get_layer_list,
            "get_board_2d_view": self.board_commands.get_board_2d_view,
            "get_board_extents": self.board_commands.get_board_extents,
            "add_board_outline": self.board_commands.add_board_outline,
            "add_mounting_hole": self.board_commands.add_mounting_hole,
            "add_text": self.board_commands.add_text,
            "add_board_text": self.board_commands.add_text,  # Alias for TypeScript tool
            # Component commands
            "route_pad_to_pad": self._refuse_offline_route,
            "place_component": self._handle_place_component,
            "move_component": self.component_commands.move_component,
            "rotate_component": self.component_commands.rotate_component,
            "delete_component": self.component_commands.delete_component,
            "edit_component": self.component_commands.edit_component,
            "get_component_properties": self.component_commands.get_component_properties,
            "get_component_list": self.component_commands.get_component_list,
            "get_footprint_geometry": self._refuse_offline_placement,
            "check_placement": self._refuse_offline_placement,
            "apply_placement": self._refuse_offline_placement,
            "find_component": self.component_commands.find_component,
            "get_component_pads": self.component_commands.get_component_pads,
            "get_pad_position": self.component_commands.get_pad_position,
            "place_component_array": self.component_commands.place_component_array,
            "align_components": self.component_commands.align_components,
            "duplicate_component": self.component_commands.duplicate_component,
            # Routing commands
            "add_net": self.routing_commands.add_net,
            "route_trace": self.routing_commands.route_trace,
            "add_via": self.routing_commands.add_via,
            "delete_trace": self.routing_commands.delete_trace,
            "query_traces": self.routing_commands.query_traces,
            "modify_trace": self.routing_commands.modify_trace,
            "copy_routing_pattern": self.routing_commands.copy_routing_pattern,
            "get_nets_list": self.routing_commands.get_nets_list,
            "create_netclass": self.routing_commands.create_netclass,
            "add_copper_pour": self.routing_commands.add_copper_pour,
            "route_differential_pair": self.routing_commands.route_differential_pair,
            "refill_zones": self._handle_refill_zones,
            # Design rule commands
            "set_design_rules": self.design_rule_commands.set_design_rules,
            "get_design_rules": self.design_rule_commands.get_design_rules,
            "run_drc": self.design_rule_commands.run_drc,
            "get_drc_violations": self.design_rule_commands.get_drc_violations,
            # Export commands
            "export_gerber": self._phase5_export_gerber,
            "export_pdf": self.export_commands.export_pdf,
            "export_svg": self.export_commands.export_svg,
            "export_3d": self.export_commands.export_3d,
            "export_bom": self.export_commands.export_bom,
            # Library commands (footprint management)
            "list_libraries": self.library_commands.list_libraries,
            "search_footprints": self.library_commands.search_footprints,
            "list_library_footprints": self.library_commands.list_library_footprints,
            "get_footprint_info": self.library_commands.get_footprint_info,
            # Symbol library commands (local KiCad symbol library search)
            "list_symbol_libraries": self.symbol_library_commands.list_symbol_libraries,
            "search_symbols": self.symbol_library_commands.search_symbols,
            "list_library_symbols": self.symbol_library_commands.list_library_symbols,
            "get_symbol_info": self.symbol_library_commands.get_symbol_info,
            # JLCPCB API commands (complete parts catalog via API)
            "download_jlcpcb_database": self._handle_download_jlcpcb_database,
            "search_jlcpcb_parts": self._handle_search_jlcpcb_parts,
            "get_jlcpcb_part": self._handle_get_jlcpcb_part,
            "get_jlcpcb_database_stats": self._handle_get_jlcpcb_database_stats,
            "suggest_jlcpcb_alternatives": self._handle_suggest_jlcpcb_alternatives,
            # Datasheet commands
            "enrich_datasheets": self._handle_enrich_datasheets,
            "get_datasheet_url": self._handle_get_datasheet_url,
            # Schematic commands
            "create_schematic": self._handle_create_schematic,
            "load_schematic": self._handle_load_schematic,
            "add_schematic_component": self._handle_add_schematic_component,
            "delete_schematic_component": self._handle_delete_schematic_component,
            "edit_schematic_component": self._handle_edit_schematic_component,
            "get_schematic_component": self._handle_get_schematic_component,
            "add_schematic_wire": self._handle_add_schematic_wire,
            "add_schematic_connection": self._handle_add_schematic_connection,
            "add_schematic_net_label": self._handle_add_schematic_net_label,
            "connect_to_net": self._handle_connect_to_net,
            "connect_passthrough": self._handle_connect_passthrough,
            "get_schematic_pin_locations": self._handle_get_schematic_pin_locations,
            "get_net_connections": self._handle_get_net_connections,
            "run_erc": self._handle_run_erc,
            "generate_netlist": self._handle_generate_netlist,
            "sync_schematic_to_board": self._handle_sync_schematic_to_board,
            "list_schematic_libraries": self._handle_list_schematic_libraries,
            "get_schematic_view": self._handle_get_schematic_view,
            "list_schematic_components": self._handle_list_schematic_components,
            "list_schematic_nets": self._handle_list_schematic_nets,
            "list_schematic_wires": self._handle_list_schematic_wires,
            "list_schematic_labels": self._handle_list_schematic_labels,
            "move_schematic_component": self._handle_move_schematic_component,
            "rotate_schematic_component": self._handle_rotate_schematic_component,
            "annotate_schematic": self._handle_annotate_schematic,
            "delete_schematic_wire": self._handle_delete_schematic_wire,
            "delete_schematic_net_label": self._handle_delete_schematic_net_label,
            "export_schematic_pdf": self._handle_export_schematic_pdf,
            "export_schematic_svg": self._handle_export_schematic_svg,
            "import_svg_logo": self._handle_import_svg_logo,
            # UI/Process management commands
            "check_kicad_ui": self._handle_check_kicad_ui,
            "launch_kicad_ui": self._handle_launch_kicad_ui,
            # IPC-specific commands (real-time operations)
            "get_backend_info": self._handle_get_backend_info,
            "ipc_add_track": self._handle_ipc_add_track,
            "ipc_add_via": self._handle_ipc_add_via,
            "ipc_add_text": self._handle_ipc_add_text,
            "ipc_list_components": self._handle_ipc_list_components,
            "ipc_get_tracks": self._handle_ipc_get_tracks,
            "ipc_get_vias": self._handle_ipc_get_vias,
            "ipc_save_board": self._handle_ipc_save_board,
            # Footprint commands
            "create_footprint": self._handle_create_footprint,
            "edit_footprint_pad": self._handle_edit_footprint_pad,
            "list_footprint_libraries": self._handle_list_footprint_libraries,
            "register_footprint_library": self._handle_register_footprint_library,
            # Symbol creator commands
            "create_symbol": self._handle_create_symbol,
            "delete_symbol": self._handle_delete_symbol,
            "list_symbols_in_library": self._handle_list_symbols_in_library,
            "register_symbol_library": self._handle_register_symbol_library,
            # Freerouting autoroute commands
            "autoroute": self.freerouting_commands.autoroute,
            "export_dsn": self.freerouting_commands.export_dsn,
            "import_ses": self.freerouting_commands.import_ses,
            "check_freerouting": self.freerouting_commands.check_freerouting,
            "add_wire": self._phase5_add_wire,
            "add_net_class": self._phase5_add_net_class,
            "assign_net_to_class": self._phase5_assign_net_to_class,
            "check_clearance": self._phase5_check_clearance,
            "replace_component": self._phase5_replace_component,
            "set_layer_constraints": self._phase5_set_layer_constraints,
            "export_netlist": self._phase5_export_netlist,
            "export_vrml": self._phase5_export_vrml,
        }

        logger.info(
            f"KiCAD interface initialized (backend: {'IPC' if self.use_ipc else 'SWIG'})"
        )

    # Commands that can be handled via IPC for real-time updates
    IPC_CAPABLE_COMMANDS = {
        # Routing commands
        "route_trace": "_ipc_route_trace",
        "route_pad_to_pad": "_ipc_route_pad_to_pad",
        "add_via": "_ipc_add_via",
        "add_net": "_ipc_add_net",
        "delete_trace": "_ipc_delete_trace",
        "get_nets_list": "_ipc_get_nets_list",
        # Zone commands
        "add_copper_pour": "_ipc_add_copper_pour",
        "refill_zones": "_ipc_refill_zones",
        # Board commands
        "add_text": "_ipc_add_text",
        "add_board_text": "_ipc_add_text",
        "set_board_size": "_ipc_set_board_size",
        "get_board_info": "_ipc_get_board_info",
        "add_board_outline": "_ipc_add_board_outline",
        "add_mounting_hole": "_ipc_add_mounting_hole",
        "get_layer_list": "_ipc_get_layer_list",
        # Component commands
        "place_component": "_ipc_place_component",
        "move_component": "_ipc_move_component",
        "clone_component": "_ipc_clone_component",
        "rotate_component": "_ipc_rotate_component",
        "delete_component": "_ipc_delete_component",
        "get_component_list": "_ipc_get_component_list",
        "get_footprint_geometry": "_ipc_get_footprint_geometry",
        "check_placement": "_ipc_check_placement",
        "apply_placement": "_ipc_apply_placement",
        "get_component_properties": "_ipc_get_component_properties",
        # Save command
        "save_project": "_ipc_save_project",
        "add_zone": "_ipc_add_zone",
        "add_component_annotation": "_ipc_add_component_annotation",
        "group_components": "_ipc_group_components",
        "export_position_file": "_ipc_export_position_file",
    }

    def handle_command(self, command: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """Route a command. Live IPC commands never fall back to SWIG."""
        logger.info(f"Handling command: {command}")
        logger.debug(f"Command parameters: {params}")
        params = params or {}

        try:
            if self.use_ipc and command in self.IPC_CAPABLE_COMMANDS:
                ipc_handler_name = self.IPC_CAPABLE_COMMANDS[command]
                ipc_handler = getattr(self, ipc_handler_name, None)
                if not self.ipc_board_api or ipc_handler is None:
                    logger.warning(
                        "IPC is required for %s and is not connected. SWIG was not called.",
                        command,
                    )
                    return ipc_unavailable_result()

                logger.info(f"Using IPC backend for {command} (real-time sync)")
                result = self._label_ipc_result(ipc_handler(params))
                logger.debug(f"IPC command result: {result}")
                return result

            refusal = self._refuse_unsafe_pcb_file_access(command, params)
            if refusal is not None:
                return refusal

            handler = self.command_routes.get(command)
            if not handler:
                if command in self.IPC_CAPABLE_COMMANDS:
                    return {
                        "success": False,
                        "error": "IPC_REQUIRED",
                        "message": (
                            "This operation is only available through the KiCad IPC connection."
                        ),
                        "_backend": "unavailable",
                        "_realtime": False,
                    }
                logger.error(f"Unknown command: {command}")
                return {
                    "success": False,
                    "message": f"Unknown command: {command}",
                    "errorDetails": "The specified command is not supported",
                }

            result = handler(params)
            logger.debug(f"Command result: {result}")
            if isinstance(result, dict) and result.pop("_keep_backend", False):
                result["_realtime"] = False
                result.setdefault("_backend", "unavailable")
                return result
            if isinstance(result, dict):
                result["_backend"] = "swig"
                result["_realtime"] = False

            if isinstance(result, dict) and result.get("success", False):
                if command in ("create_project", "open_project"):
                    logger.info("Updating board reference...")
                    self.board = self.project_commands.board
                    self._update_command_handlers()
                    self._remember_offline_board()
                elif command in (
                    "place_component",
                    "sync_schematic_to_board",
                    "import_svg_logo",
                    "refill_zones",
                ):
                    self._remember_offline_board()
                if (
                    command in self._BOARD_MUTATING_COMMANDS
                    and command != "sync_schematic_to_board"
                ):
                    self._auto_save_board(result)
            return result

        except Exception as e:
            traceback_str = traceback.format_exc()
            logger.error(f"Error handling command {command}: {str(e)}\n{traceback_str}")
            return {
                "success": False,
                "message": f"Error handling command: {command}",
                "errorDetails": f"{str(e)}\n{traceback_str}",
            }

    # Board-mutating commands that trigger auto-save on SWIG path
    _BOARD_MUTATING_COMMANDS = {
        "place_component",
        "move_component",
        "rotate_component",
        "delete_component",
        "route_trace",
        "route_pad_to_pad",
        "add_via",
        "delete_trace",
        "add_net",
        "add_board_outline",
        "add_mounting_hole",
        "add_text",
        "add_board_text",
        "add_copper_pour",
        "refill_zones",
        "import_svg_logo",
        "sync_schematic_to_board",
        "connect_passthrough",
    }

    def _label_ipc_result(self, result: Any) -> Dict[str, Any]:
        """Mark an IPC result. A SWIG delegation is never reported as realtime IPC."""
        if not isinstance(result, dict):
            return {
                "success": False,
                "error": "IPC_PROTOCOL",
                "message": "IPC handler returned a non-object result",
                "_backend": "unavailable",
                "_realtime": False,
            }
        if result.pop("_delegated_to_swig", False):
            result["success"] = False
            result["error"] = "IPC_DELEGATION_BLOCKED"
            result["message"] = (
                "An IPC handler tried to modify the board through SWIG. The operation was rejected."
            )
            result["_backend"] = "unavailable"
            result["_realtime"] = False
            return result
        result["_backend"] = "ipc"
        result["_realtime"] = bool(result.get("success"))
        return result

    def _swig_board_path(self) -> str:
        board = getattr(self, "board", None)
        if not board:
            return ""
        try:
            return board.GetFileName() or ""
        except Exception:
            return ""

    def _live_editor_paths(self) -> list:
        api = getattr(self, "ipc_board_api", None)
        if not api or not hasattr(api, "_open_pcb_paths"):
            return []
        try:
            paths = [path for path in api._open_pcb_paths() if path]
            self._live_paths_unknown = False
            return paths
        except Exception as exc:
            logger.warning("Could not list open PCB documents: %s", exc)
            self._live_paths_unknown = True
            return []

    def _remember_offline_board(self) -> None:
        path = self._swig_board_path()
        if not path:
            return
        self._offline_owned_pcb_paths.add(normalize_pcb_path(path))

    def _path_is_owned(self, path: str) -> bool:
        if not path:
            return False
        try:
            return normalize_pcb_path(path) in self._offline_owned_pcb_paths
        except OSError:
            return False

    def _file_decision(self, path: str, purpose: str) -> Dict[str, Any]:
        return evaluate_pcb_file_access(
            path,
            live_paths=self._live_editor_paths(),
            locked=bool(lock_file_present(path)),
            use_ipc=bool(self.use_ipc),
            purpose=purpose,
            owned=self._path_is_owned(path),
            live_paths_unknown=bool(self._live_paths_unknown),
        )

    def _file_refusal(self, path: str, purpose: str) -> Optional[Dict[str, Any]]:
        decision = self._file_decision(path, purpose)
        if decision.get("allow"):
            return None
        return {
            "success": False,
            "error": decision.get("error", "EDITOR_OWNS_FILE"),
            "message": decision.get("message", "Refusing to load or overwrite the PCB file."),
            "_backend": "swig",
            "_realtime": False,
        }

    def _refuse_unsafe_pcb_file_access(
        self, command: str, params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        if command not in GUARDED_PCB_COMMANDS:
            return None
        paths = swig_target_paths(command, params, self._swig_board_path())
        if not paths:
            return None
        purpose = access_purpose(command)
        for path in paths:
            refusal = self._file_refusal(path, purpose)
            if refusal is not None:
                logger.warning(
                    "Refusing %s on %s: %s", command, path, refusal.get("message")
                )
                return refusal
        return None

    def _guarded_create_project(self, params):
        refusal = self._refuse_unsafe_pcb_file_access("create_project", params)
        if refusal is not None:
            return refusal
        return self.project_commands.create_project(params)

    def _guarded_open_project(self, params):
        refusal = self._refuse_unsafe_pcb_file_access("open_project", params)
        if refusal is not None:
            return refusal
        return self.project_commands.open_project(params)

    def _guarded_save_project(self, params):
        refusal = self._refuse_unsafe_pcb_file_access("save_project", params)
        if refusal is not None:
            return refusal
        return self.project_commands.save_project(params)

    def _auto_save_board(self, result: Optional[Dict[str, Any]] = None):
        """Save an offline SWIG board only when this process owns the file.

        A board that is open in the PCB editor is never written from here.
        """
        board_path = self._swig_board_path()
        if not board_path:
            return
        decision = self._file_decision(board_path, "autosave")
        if not decision.get("allow"):
            logger.warning("Auto-save skipped: %s", decision.get("reason"))
            if isinstance(result, dict):
                result["fileSaved"] = False
                result["fileSaveSkipped"] = decision.get("reason")
            return
        try:
            pcbnew.SaveBoard(board_path, self.board)
            logger.debug(f"Auto-saved offline board to: {board_path}")
            if isinstance(result, dict):
                result["fileSaved"] = True
        except Exception as e:
            logger.warning(f"Auto-save failed: {e}")
            if isinstance(result, dict):
                result["fileSaved"] = False
                result["fileSaveSkipped"] = str(e)

    def _update_command_handlers(self):
        """Update board reference in all command handlers"""
        logger.debug("Updating board reference in command handlers")
        self.project_commands.board = self.board
        self.board_commands.board = self.board
        self.component_commands.board = self.board
        self.routing_commands.board = self.board
        self.design_rule_commands.board = self.board
        self.export_commands.board = self.board
        self.freerouting_commands.board = self.board

    # Schematic command handlers
    def _handle_create_schematic(self, params):
        """Create a new schematic"""
        logger.info("Creating schematic")
        try:
            # Support multiple parameter naming conventions for compatibility:
            # - TypeScript tools use: name, path
            # - Python schema uses: filename, title
            # - Legacy uses: projectName, path, metadata
            project_name = (
                params.get("projectName") or params.get("name") or params.get("title")
            )

            # Handle filename parameter - it may contain full path
            filename = params.get("filename")
            if filename:
                # If filename provided, extract name and path from it
                if filename.endswith(".kicad_sch"):
                    filename = filename[:-10]  # Remove .kicad_sch extension
                path = os.path.dirname(filename) or "."
                project_name = project_name or os.path.basename(filename)
            else:
                path = params.get("path", ".")
            metadata = params.get("metadata", {})

            if not project_name:
                return {
                    "success": False,
                    "message": "Schematic name is required. Provide 'name', 'projectName', or 'filename' parameter.",
                }

            schematic = SchematicManager.create_schematic(project_name, metadata)
            file_path = f"{path}/{project_name}.kicad_sch"
            success = SchematicManager.save_schematic(schematic, file_path)

            return {"success": success, "file_path": file_path}
        except Exception as e:
            logger.error(f"Error creating schematic: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_load_schematic(self, params):
        """Load an existing schematic"""
        logger.info("Loading schematic")
        try:
            filename = params.get("filename")

            if not filename:
                return {"success": False, "message": "Filename is required"}

            schematic = SchematicManager.load_schematic(filename)
            success = schematic is not None

            if success:
                metadata = SchematicManager.get_schematic_metadata(schematic)
                return {"success": success, "metadata": metadata}
            else:
                return {"success": False, "message": "Failed to load schematic"}
        except Exception as e:
            logger.error(f"Error loading schematic: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_place_component(self, params):
        """Place a component on the PCB, with project-local fp-lib-table support.
        If boardPath is given and differs from the currently loaded board, the
        board is reloaded from boardPath before placing — prevents silent failures
        when Claude provides a boardPath that was not yet loaded.
        """
        from pathlib import Path

        board_path = params.get("boardPath")
        if board_path:
            refusal = self._file_refusal(board_path, "swig_load")
            if refusal is not None:
                return refusal
            board_path_norm = str(Path(board_path).resolve())
            current_board_file = (
                str(Path(self.board.GetFileName()).resolve()) if self.board else ""
            )
            if board_path_norm != current_board_file:
                logger.info(
                    f"boardPath differs from current board — reloading: {board_path}"
                )
                try:
                    self.board = pcbnew.LoadBoard(board_path)
                    self._update_command_handlers()
                    logger.info("Board reloaded from boardPath")
                except Exception as e:
                    logger.error(f"Failed to reload board from boardPath: {e}")
                    return {
                        "success": False,
                        "message": f"Could not load board from boardPath: {board_path}",
                        "errorDetails": str(e),
                    }

            project_path = Path(board_path).parent
            if project_path != getattr(self, "_current_project_path", None):
                self._current_project_path = project_path
                local_lib = FootprintLibraryManager(project_path=project_path)
                self.component_commands = ComponentCommands(self.board, local_lib)
                logger.info(
                    f"Reloaded FootprintLibraryManager with project_path={project_path}"
                )

        return self.component_commands.place_component(params)

    def _handle_add_schematic_component(self, params):
        """Add a component to a schematic using text-based injection (no sexpdata)"""
        logger.info("Adding component to schematic")
        try:
            from pathlib import Path
            from commands.dynamic_symbol_loader import DynamicSymbolLoader

            schematic_path = params.get("schematicPath")
            component = params.get("component", {})

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not component:
                return {"success": False, "message": "Component definition is required"}

            comp_type = component.get("type", "R")
            library = component.get("library", "Device")
            reference = component.get("reference", "X?")
            value = component.get("value", comp_type)
            footprint = component.get("footprint", "")
            x = component.get("x", 0)
            y = component.get("y", 0)
            rotation = component.get("rotation", 0)
            mirror = component.get("mirror")
            unit = component.get("unit", 1)

            # Derive project path from schematic path for project-local library resolution
            schematic_file = Path(schematic_path)
            derived_project_path = schematic_file.parent

            loader = DynamicSymbolLoader(project_path=derived_project_path)
            loader.add_component(
                schematic_file,
                library,
                comp_type,
                reference=reference,
                value=value,
                footprint=footprint,
                x=x,
                y=y,
                rotation=rotation,
                mirror=mirror,
                unit=unit,
                project_path=derived_project_path,
            )

            return {
                "success": True,
                "component_reference": reference,
                "symbol_source": f"{library}:{comp_type}",
            }
        except Exception as e:
            logger.error(f"Error adding component to schematic: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_component(self, params):
        """Remove a placed symbol from a schematic using text-based manipulation (no skip writes)"""
        logger.info("Deleting schematic component")
        try:
            from pathlib import Path
            import re

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            def find_matching_paren(s, start):
                """Find the closing paren matching the opening paren at start."""
                depth = 0
                i = start
                while i < len(s):
                    if s[i] == "(":
                        depth += 1
                    elif s[i] == ")":
                        depth -= 1
                        if depth == 0:
                            return i
                    i += 1
                return -1

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = (
                find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1
            )

            # Find ALL placed symbol blocks matching the reference (handles duplicates).
            # Use content-string search so multi-line KiCAD format is handled correctly:
            # KiCAD writes (symbol\n\t\t(lib_id "...") across two lines, which a
            # line-by-line regex would never match.
            blocks_to_delete = []  # list of (char_start, char_end) into content
            search_start = 0
            pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                # Skip blocks inside lib_symbols
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = find_matching_paren(content, pos)
                if end < 0:
                    search_start = pos + 1
                    continue
                block_text = content[pos : end + 1]
                if re.search(
                    r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                    block_text,
                ):
                    blocks_to_delete.append((pos, end))
                search_start = end + 1

            if not blocks_to_delete:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic (note: this tool removes schematic symbols, use delete_component for PCB footprints)",
                }

            # Delete from back to front to preserve character offsets
            for b_start, b_end in sorted(blocks_to_delete, reverse=True):
                # Include any leading newline/whitespace before the block
                trim_start = b_start
                while trim_start > 0 and content[trim_start - 1] in (" ", "\t"):
                    trim_start -= 1
                if trim_start > 0 and content[trim_start - 1] == "\n":
                    trim_start -= 1
                content = content[:trim_start] + content[b_end + 1:]

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)

            deleted_count = len(blocks_to_delete)
            logger.info(
                f"Deleted {deleted_count} instance(s) of {reference} from {sch_file.name}"
            )
            return {
                "success": True,
                "reference": reference,
                "deleted_count": deleted_count,
                "schematic": str(sch_file),
            }

        except Exception as e:
            logger.error(f"Error deleting schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_edit_schematic_component(self, params):
        """Update properties of a placed symbol in a schematic (footprint, value, reference).
        Uses text-based in-place editing – preserves position, UUID and all other fields.
        """
        logger.info("Editing schematic component")
        try:
            from pathlib import Path
            import re

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            new_footprint = params.get("footprint")
            new_value = params.get("value")
            new_reference = params.get("newReference")
            field_positions = params.get(
                "fieldPositions"
            )  # dict: {"Reference": {"x": 1, "y": 2, "angle": 0}}

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}
            if not any(
                [
                    new_footprint is not None,
                    new_value is not None,
                    new_reference is not None,
                    field_positions is not None,
                ]
            ):
                return {
                    "success": False,
                    "message": "At least one of footprint, value, newReference, or fieldPositions must be provided",
                }

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            def find_matching_paren(s, start):
                """Find the position of the closing paren matching the opening paren at start."""
                depth = 0
                i = start
                while i < len(s):
                    if s[i] == "(":
                        depth += 1
                    elif s[i] == ")":
                        depth -= 1
                        if depth == 0:
                            return i
                    i += 1
                return -1

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = (
                find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1
            )

            # Find placed symbol blocks that match the reference
            # Search for (symbol (lib_id "...") ... (property "Reference" "<ref>" ...) ...)
            block_start = block_end = None
            search_start = 0
            pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                # Skip if inside lib_symbols section
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = find_matching_paren(content, pos)
                if end < 0:
                    search_start = pos + 1
                    continue
                block_text = content[pos : end + 1]
                if re.search(
                    r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                    block_text,
                ):
                    block_start, block_end = pos, end
                    break
                search_start = end + 1

            if block_start is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            # Apply property replacements within the found block
            block_text = content[block_start : block_end + 1]
            if new_footprint is not None:
                block_text = re.sub(
                    r'(\(property\s+"Footprint"\s+)"[^"]*"',
                    rf'\1"{new_footprint}"',
                    block_text,
                )
            if new_value is not None:
                block_text = re.sub(
                    r'(\(property\s+"Value"\s+)"[^"]*"', rf'\1"{new_value}"', block_text
                )
            if new_reference is not None:
                block_text = re.sub(
                    r'(\(property\s+"Reference"\s+)"[^"]*"',
                    rf'\1"{new_reference}"',
                    block_text,
                )
            if field_positions is not None:
                for field_name, pos in field_positions.items():
                    x = pos.get("x", 0)
                    y = pos.get("y", 0)
                    angle = pos.get("angle", 0)
                    block_text = re.sub(
                        r'(\(property\s+"'
                        + re.escape(field_name)
                        + r'"\s+"[^"]*"\s+)\(at\s+[\d\.\-]+\s+[\d\.\-]+\s+[\d\.\-]+\s*\)',
                        rf"\1(at {x} {y} {angle})",
                        block_text,
                    )

            content = content[:block_start] + block_text + content[block_end + 1 :]

            with open(sch_file, "w", encoding="utf-8") as f:
                f.write(content)

            changes = {
                k: v
                for k, v in {
                    "footprint": new_footprint,
                    "value": new_value,
                    "reference": new_reference,
                }.items()
                if v is not None
            }
            if field_positions is not None:
                changes["fieldPositions"] = field_positions
            logger.info(f"Edited schematic component {reference}: {changes}")
            return {"success": True, "reference": reference, "updated": changes}

        except Exception as e:
            logger.error(f"Error editing schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_component(self, params):
        """Return full component info: position and all field values with their (at x y angle) positions."""
        logger.info("Getting schematic component info")
        try:
            from pathlib import Path
            import re

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}
            if not reference:
                return {"success": False, "message": "reference is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            with open(sch_file, "r", encoding="utf-8") as f:
                content = f.read()

            def find_matching_paren(s, start):
                depth = 0
                i = start
                while i < len(s):
                    if s[i] == "(":
                        depth += 1
                    elif s[i] == ")":
                        depth -= 1
                        if depth == 0:
                            return i
                    i += 1
                return -1

            # Skip lib_symbols section
            lib_sym_pos = content.find("(lib_symbols")
            lib_sym_end = (
                find_matching_paren(content, lib_sym_pos) if lib_sym_pos >= 0 else -1
            )

            # Find the placed symbol block for this reference
            block_start = block_end = None
            search_start = 0
            pattern = re.compile(r'\(symbol\s+\(lib_id\s+"')
            while True:
                m = pattern.search(content, search_start)
                if not m:
                    break
                pos = m.start()
                if lib_sym_pos >= 0 and lib_sym_pos <= pos <= lib_sym_end:
                    search_start = lib_sym_end + 1
                    continue
                end = find_matching_paren(content, pos)
                if end < 0:
                    search_start = pos + 1
                    continue
                block_text = content[pos : end + 1]
                if re.search(
                    r'\(property\s+"Reference"\s+"' + re.escape(reference) + r'"',
                    block_text,
                ):
                    block_start, block_end = pos, end
                    break
                search_start = end + 1

            if block_start is None:
                return {
                    "success": False,
                    "message": f"Component '{reference}' not found in schematic",
                }

            block_text = content[block_start : block_end + 1]

            # Extract component position: first (at x y angle) in the symbol header line
            comp_at = re.search(
                r'\(symbol\s+\(lib_id\s+"[^"]*"\s*\)\s+\(at\s+([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)',
                block_text,
            )
            if comp_at:
                comp_pos = {
                    "x": float(comp_at.group(1)),
                    "y": float(comp_at.group(2)),
                    "angle": float(comp_at.group(3)),
                }
            else:
                comp_pos = None

            # Extract all properties with their at positions
            prop_pattern = re.compile(
                r'\(property\s+"([^"]*)"\s+"([^"]*)"\s+\(at\s+([\d\.\-]+)\s+([\d\.\-]+)\s+([\d\.\-]+)\s*\)'
            )
            fields = {}
            for m in prop_pattern.finditer(block_text):
                name, value, x, y, angle = (
                    m.group(1),
                    m.group(2),
                    m.group(3),
                    m.group(4),
                    m.group(5),
                )
                fields[name] = {
                    "value": value,
                    "x": float(x),
                    "y": float(y),
                    "angle": float(angle),
                }

            return {
                "success": True,
                "reference": reference,
                "position": comp_pos,
                "fields": fields,
            }

        except Exception as e:
            logger.error(f"Error getting schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_wire(self, params):
        """Add a wire to a schematic using WireManager"""
        logger.info("Adding wire to schematic")
        try:
            from pathlib import Path
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            start_point = params.get("startPoint")
            end_point = params.get("endPoint")
            properties = params.get("properties", {})

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not start_point or not end_point:
                return {
                    "success": False,
                    "message": "Start and end points are required",
                }

            # Extract wire properties
            stroke_width = properties.get("stroke_width", 0)
            stroke_type = properties.get("stroke_type", "default")

            # Use WireManager for S-expression manipulation
            success = WireManager.add_wire(
                Path(schematic_path),
                start_point,
                end_point,
                stroke_width=stroke_width,
                stroke_type=stroke_type,
            )

            if success:
                return {"success": True, "message": "Wire added successfully"}
            else:
                return {"success": False, "message": "Failed to add wire"}
        except Exception as e:
            logger.error(f"Error adding wire to schematic: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_list_schematic_libraries(self, params):
        """List available symbol libraries"""
        logger.info("Listing schematic libraries")
        try:
            search_paths = params.get("searchPaths")

            libraries = LibraryManager.list_available_libraries(search_paths)
            return {"success": True, "libraries": libraries}
        except Exception as e:
            logger.error(f"Error listing schematic libraries: {str(e)}")
            return {"success": False, "message": str(e)}

    # ------------------------------------------------------------------ #
    #  Footprint handlers                                                  #
    # ------------------------------------------------------------------ #

    def _handle_create_footprint(self, params):
        """Create a new .kicad_mod footprint file in a .pretty library."""
        logger.info(
            f"create_footprint: {params.get('name')} in {params.get('libraryPath')}"
        )
        try:
            creator = FootprintCreator()
            return creator.create_footprint(
                library_path=params.get("libraryPath", ""),
                name=params.get("name", ""),
                description=params.get("description", ""),
                tags=params.get("tags", ""),
                pads=params.get("pads", []),
                courtyard=params.get("courtyard"),
                silkscreen=params.get("silkscreen"),
                fab_layer=params.get("fabLayer"),
                ref_position=params.get("refPosition"),
                value_position=params.get("valuePosition"),
                overwrite=params.get("overwrite", False),
            )
        except Exception as e:
            logger.error(f"create_footprint error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_edit_footprint_pad(self, params):
        """Edit an existing pad in a .kicad_mod file."""
        logger.info(
            f"edit_footprint_pad: pad {params.get('padNumber')} in {params.get('footprintPath')}"
        )
        try:
            creator = FootprintCreator()
            return creator.edit_footprint_pad(
                footprint_path=params.get("footprintPath", ""),
                pad_number=str(params.get("padNumber", "1")),
                size=params.get("size"),
                at=params.get("at"),
                drill=params.get("drill"),
                shape=params.get("shape"),
            )
        except Exception as e:
            logger.error(f"edit_footprint_pad error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_list_footprint_libraries(self, params):
        """List .pretty footprint libraries and their contents."""
        logger.info("list_footprint_libraries")
        try:
            creator = FootprintCreator()
            return creator.list_footprint_libraries(
                search_paths=params.get("searchPaths")
            )
        except Exception as e:
            logger.error(f"list_footprint_libraries error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_register_footprint_library(self, params):
        """Register a .pretty library in KiCAD's fp-lib-table."""
        logger.info(f"register_footprint_library: {params.get('libraryPath')}")
        try:
            creator = FootprintCreator()
            return creator.register_footprint_library(
                library_path=params.get("libraryPath", ""),
                library_name=params.get("libraryName"),
                description=params.get("description", ""),
                scope=params.get("scope", "project"),
                project_path=params.get("projectPath"),
            )
        except Exception as e:
            logger.error(f"register_footprint_library error: {e}")
            return {"success": False, "error": str(e)}

    # ------------------------------------------------------------------ #
    #  Symbol creator handlers                                             #
    # ------------------------------------------------------------------ #

    def _handle_create_symbol(self, params):
        """Create a new symbol in a .kicad_sym library."""
        logger.info(
            f"create_symbol: {params.get('name')} in {params.get('libraryPath')}"
        )
        try:
            creator = SymbolCreator()
            return creator.create_symbol(
                library_path=params.get("libraryPath", ""),
                name=params.get("name", ""),
                reference_prefix=params.get("referencePrefix", "U"),
                description=params.get("description", ""),
                keywords=params.get("keywords", ""),
                datasheet=params.get("datasheet", "~"),
                footprint=params.get("footprint", ""),
                in_bom=params.get("inBom", True),
                on_board=params.get("onBoard", True),
                pins=params.get("pins", []),
                rectangles=params.get("rectangles", []),
                polylines=params.get("polylines", []),
                overwrite=params.get("overwrite", False),
            )
        except Exception as e:
            logger.error(f"create_symbol error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_delete_symbol(self, params):
        """Delete a symbol from a .kicad_sym library."""
        logger.info(
            f"delete_symbol: {params.get('name')} from {params.get('libraryPath')}"
        )
        try:
            creator = SymbolCreator()
            return creator.delete_symbol(
                library_path=params.get("libraryPath", ""),
                name=params.get("name", ""),
            )
        except Exception as e:
            logger.error(f"delete_symbol error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_list_symbols_in_library(self, params):
        """List all symbols in a .kicad_sym file."""
        logger.info(f"list_symbols_in_library: {params.get('libraryPath')}")
        try:
            creator = SymbolCreator()
            return creator.list_symbols(
                library_path=params.get("libraryPath", ""),
            )
        except Exception as e:
            logger.error(f"list_symbols_in_library error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_register_symbol_library(self, params):
        """Register a .kicad_sym library in KiCAD's sym-lib-table."""
        logger.info(f"register_symbol_library: {params.get('libraryPath')}")
        try:
            creator = SymbolCreator()
            return creator.register_symbol_library(
                library_path=params.get("libraryPath", ""),
                library_name=params.get("libraryName"),
                description=params.get("description", ""),
                scope=params.get("scope", "project"),
                project_path=params.get("projectPath"),
            )
        except Exception as e:
            logger.error(f"register_symbol_library error: {e}")
            return {"success": False, "error": str(e)}

    def _handle_export_schematic_pdf(self, params):
        """Export schematic to PDF"""
        logger.info("Exporting schematic to PDF")
        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}
            if not output_path:
                return {"success": False, "message": "Output path is required"}

            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            import subprocess

            cmd = [
                "kicad-cli",
                "sch",
                "export",
                "pdf",
                "--output",
                output_path,
                schematic_path,
            ]

            if params.get("blackAndWhite"):
                cmd.insert(-1, "--black-and-white")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode == 0:
                return {"success": True, "file": {"path": output_path}}
            else:
                return {
                    "success": False,
                    "message": f"kicad-cli failed: {result.stderr}",
                }

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error exporting schematic to PDF: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_add_schematic_connection(self, params):
        """Add a pin-to-pin connection in schematic with automatic pin discovery and routing"""
        logger.info("Adding pin-to-pin connection in schematic")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            source_ref = params.get("sourceRef")
            source_pin = params.get("sourcePin")
            target_ref = params.get("targetRef")
            target_pin = params.get("targetPin")
            routing = params.get(
                "routing", "direct"
            )  # 'direct', 'orthogonal_h', 'orthogonal_v'

            if not all(
                [schematic_path, source_ref, source_pin, target_ref, target_pin]
            ):
                return {"success": False, "message": "Missing required parameters"}

            # Use ConnectionManager with new PinLocator and WireManager integration
            success = ConnectionManager.add_connection(
                Path(schematic_path),
                source_ref,
                source_pin,
                target_ref,
                target_pin,
                routing=routing,
            )

            if success:
                return {
                    "success": True,
                    "message": f"Connected {source_ref}/{source_pin} to {target_ref}/{target_pin} (routing: {routing})",
                }
            else:
                return {"success": False, "message": "Failed to add connection"}
        except Exception as e:
            logger.error(f"Error adding schematic connection: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_add_schematic_net_label(self, params):
        """Add a net label to schematic using WireManager"""
        logger.info("Adding net label to schematic")
        try:
            from pathlib import Path
            from commands.wire_manager import WireManager

            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            position = params.get("position")
            label_type = params.get(
                "labelType", "label"
            )  # 'label', 'global_label', 'hierarchical_label'
            orientation = params.get("orientation", 0)  # 0, 90, 180, 270

            if not all([schematic_path, net_name, position]):
                return {"success": False, "message": "Missing required parameters"}

            # Use WireManager for S-expression manipulation
            success = WireManager.add_label(
                Path(schematic_path),
                net_name,
                position,
                label_type=label_type,
                orientation=orientation,
            )

            if success:
                return {
                    "success": True,
                    "message": f"Added net label '{net_name}' at {position}",
                }
            else:
                return {"success": False, "message": "Failed to add net label"}
        except Exception as e:
            logger.error(f"Error adding net label: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_connect_to_net(self, params):
        """Connect a component pin to a named net using wire stub and label"""
        logger.info("Connecting component pin to net")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            component_ref = params.get("componentRef")
            pin_name = params.get("pinName")
            net_name = params.get("netName")

            if not all([schematic_path, component_ref, pin_name, net_name]):
                return {"success": False, "message": "Missing required parameters"}

            # Use ConnectionManager with new WireManager integration
            success = ConnectionManager.connect_to_net(
                Path(schematic_path), component_ref, pin_name, net_name
            )

            if success:
                return {
                    "success": True,
                    "message": f"Connected {component_ref}/{pin_name} to net '{net_name}'",
                }
            else:
                return {"success": False, "message": "Failed to connect to net"}
        except Exception as e:
            logger.error(f"Error connecting to net: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {
                "success": False,
                "message": str(e),
                "errorDetails": traceback.format_exc(),
            }

    def _handle_connect_passthrough(self, params):
        """Connect all pins of source connector to matching pins of target connector"""
        logger.info("Connecting passthrough between two connectors")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            source_ref = params.get("sourceRef")
            target_ref = params.get("targetRef")
            net_prefix = params.get("netPrefix", "PIN")
            pin_offset = int(params.get("pinOffset", 0))

            if not all([schematic_path, source_ref, target_ref]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, sourceRef, targetRef",
                }

            result = ConnectionManager.connect_passthrough(
                Path(schematic_path), source_ref, target_ref, net_prefix, pin_offset
            )

            n_ok = len(result["connected"])
            n_fail = len(result["failed"])
            return {
                "success": n_fail == 0,
                "message": f"Passthrough complete: {n_ok} connected, {n_fail} failed",
                "connected": result["connected"],
                "failed": result["failed"],
            }
        except Exception as e:
            logger.error(f"Error in connect_passthrough: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_pin_locations(self, params):
        """Return exact pin endpoint coordinates for a schematic component"""
        logger.info("Getting schematic pin locations")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            reference = params.get("reference")

            if not all([schematic_path, reference]):
                return {
                    "success": False,
                    "message": "Missing required parameters: schematicPath, reference",
                }

            locator = PinLocator()
            all_pins = locator.get_all_symbol_pins(Path(schematic_path), reference)

            if not all_pins:
                return {
                    "success": False,
                    "message": f"No pins found for {reference} — check reference and schematic path",
                }

            # Enrich with pin names and angles from the symbol definition
            pins_def = (
                locator.get_symbol_pins(
                    Path(schematic_path),
                    locator._get_lib_id(Path(schematic_path), reference),
                )
                if hasattr(locator, "_get_lib_id")
                else {}
            )

            result = {}
            for pin_num, coords in all_pins.items():
                entry = {"x": coords[0], "y": coords[1]}
                if pin_num in pins_def:
                    entry["name"] = pins_def[pin_num].get("name", pin_num)
                    entry["angle"] = (
                        locator.get_pin_angle(Path(schematic_path), reference, pin_num)
                        or 0
                    )
                result[pin_num] = entry

            return {"success": True, "reference": reference, "pins": result}

        except Exception as e:
            logger.error(f"Error getting pin locations: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_get_schematic_view(self, params):
        """Get a rasterised image of the schematic (SVG export → optional PNG conversion)"""
        logger.info("Getting schematic view")
        import subprocess
        import tempfile
        import base64

        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path or not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            fmt = params.get("format", "png")
            width = params.get("width", 1200)
            height = params.get("height", 900)

            # Step 1: Export schematic to SVG via kicad-cli
            with tempfile.TemporaryDirectory() as tmpdir:
                svg_path = os.path.join(tmpdir, "schematic.svg")
                cmd = [
                    "kicad-cli",
                    "sch",
                    "export",
                    "svg",
                    "--output",
                    tmpdir,
                    "--no-background-color",
                    schematic_path,
                ]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

                if result.returncode != 0:
                    return {
                        "success": False,
                        "message": f"kicad-cli SVG export failed: {result.stderr}",
                    }

                # kicad-cli may name the file after the schematic, find it
                import glob

                svg_files = glob.glob(os.path.join(tmpdir, "*.svg"))
                if not svg_files:
                    return {
                        "success": False,
                        "message": "No SVG file produced by kicad-cli",
                    }
                svg_path = svg_files[0]

                if fmt == "svg":
                    with open(svg_path, "r", encoding="utf-8") as f:
                        svg_data = f.read()
                    return {"success": True, "imageData": svg_data, "format": "svg"}

                # Step 2: Convert SVG to PNG using cairosvg
                try:
                    from cairosvg import svg2png
                except ImportError:
                    # Fallback: return SVG data with a note
                    with open(svg_path, "r", encoding="utf-8") as f:
                        svg_data = f.read()
                    return {
                        "success": True,
                        "imageData": svg_data,
                        "format": "svg",
                        "message": "cairosvg not installed — returning SVG instead of PNG. Install with: pip install cairosvg",
                    }

                png_data = svg2png(
                    url=svg_path, output_width=width, output_height=height
                )

                return {
                    "success": True,
                    "imageData": base64.b64encode(png_data).decode("utf-8"),
                    "format": "png",
                    "width": width,
                    "height": height,
                }

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error getting schematic view: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_components(self, params):
        """List all components in a schematic"""
        logger.info("Listing schematic components")
        try:
            from pathlib import Path
            from commands.pin_locator import PinLocator

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            sch_file = Path(schematic_path)
            if not sch_file.exists():
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Optional filters
            filter_params = params.get("filter", {})
            lib_id_filter = filter_params.get("libId", "")
            ref_prefix_filter = filter_params.get("referencePrefix", "")

            locator = PinLocator()
            components = []

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                # Skip template symbols
                if ref.startswith("_TEMPLATE"):
                    continue

                lib_id = symbol.lib_id.value if hasattr(symbol, "lib_id") else ""

                # Apply filters
                if lib_id_filter and lib_id_filter not in lib_id:
                    continue
                if ref_prefix_filter and not ref.startswith(ref_prefix_filter):
                    continue

                value = (
                    symbol.property.Value.value
                    if hasattr(symbol.property, "Value")
                    else ""
                )
                footprint = (
                    symbol.property.Footprint.value
                    if hasattr(symbol.property, "Footprint")
                    else ""
                )
                position = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                uuid_val = symbol.uuid.value if hasattr(symbol, "uuid") else ""

                comp = {
                    "reference": ref,
                    "libId": lib_id,
                    "value": value,
                    "footprint": footprint,
                    "position": {"x": float(position[0]), "y": float(position[1])},
                    "rotation": float(position[2]) if len(position) > 2 else 0,
                    "uuid": str(uuid_val),
                }

                # Get pins if available
                try:
                    all_pins = locator.get_all_symbol_pins(sch_file, ref)
                    if all_pins:
                        pins_def = locator.get_symbol_pins(sch_file, lib_id) or {}
                        pin_list = []
                        for pin_num, coords in all_pins.items():
                            pin_info = {
                                "number": pin_num,
                                "position": {"x": coords[0], "y": coords[1]},
                            }
                            if pin_num in pins_def:
                                pin_info["name"] = pins_def[pin_num].get(
                                    "name", pin_num
                                )
                            pin_list.append(pin_info)
                        comp["pins"] = pin_list
                except Exception:
                    pass  # Pin lookup is best-effort

                components.append(comp)

            return {"success": True, "components": components, "count": len(components)}

        except Exception as e:
            logger.error(f"Error listing schematic components: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_nets(self, params):
        """List all nets in a schematic with their connections"""
        logger.info("Listing schematic nets")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Get all net names from labels and global labels
            net_names = set()
            if hasattr(schematic, "label"):
                for label in schematic.label:
                    if hasattr(label, "value"):
                        net_names.add(label.value)
            if hasattr(schematic, "global_label"):
                for label in schematic.global_label:
                    if hasattr(label, "value"):
                        net_names.add(label.value)

            nets = []
            for net_name in sorted(net_names):
                connections = ConnectionManager.get_net_connections(
                    schematic, net_name, Path(schematic_path)
                )
                nets.append(
                    {
                        "name": net_name,
                        "connections": connections,
                    }
                )

            return {"success": True, "nets": nets, "count": len(nets)}

        except Exception as e:
            logger.error(f"Error listing schematic nets: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_wires(self, params):
        """List all wires in a schematic"""
        logger.info("Listing schematic wires")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            wires = []
            if hasattr(schematic, "wire"):
                for wire in schematic.wire:
                    if hasattr(wire, "pts") and hasattr(wire.pts, "xy"):
                        points = []
                        for point in wire.pts.xy:
                            if hasattr(point, "value"):
                                points.append(
                                    {
                                        "x": float(point.value[0]),
                                        "y": float(point.value[1]),
                                    }
                                )

                        if len(points) >= 2:
                            wires.append(
                                {
                                    "start": points[0],
                                    "end": points[-1],
                                }
                            )

            return {"success": True, "wires": wires, "count": len(wires)}

        except Exception as e:
            logger.error(f"Error listing schematic wires: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_list_schematic_labels(self, params):
        """List all net labels and power flags in a schematic"""
        logger.info("Listing schematic labels")
        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            labels = []

            # Regular labels
            if hasattr(schematic, "label"):
                for label in schematic.label:
                    if hasattr(label, "value"):
                        pos = (
                            label.at.value
                            if hasattr(label, "at") and hasattr(label.at, "value")
                            else [0, 0]
                        )
                        labels.append(
                            {
                                "name": label.value,
                                "type": "net",
                                "position": {"x": float(pos[0]), "y": float(pos[1])},
                            }
                        )

            # Global labels
            if hasattr(schematic, "global_label"):
                for label in schematic.global_label:
                    if hasattr(label, "value"):
                        pos = (
                            label.at.value
                            if hasattr(label, "at") and hasattr(label.at, "value")
                            else [0, 0]
                        )
                        labels.append(
                            {
                                "name": label.value,
                                "type": "global",
                                "position": {"x": float(pos[0]), "y": float(pos[1])},
                            }
                        )

            # Power symbols (components with power flag)
            if hasattr(schematic, "symbol"):
                for symbol in schematic.symbol:
                    if not hasattr(symbol.property, "Reference"):
                        continue
                    ref = symbol.property.Reference.value
                    if ref.startswith("_TEMPLATE"):
                        continue
                    if not ref.startswith("#PWR"):
                        continue
                    value = (
                        symbol.property.Value.value
                        if hasattr(symbol.property, "Value")
                        else ref
                    )
                    pos = symbol.at.value if hasattr(symbol, "at") else [0, 0, 0]
                    labels.append(
                        {
                            "name": value,
                            "type": "power",
                            "position": {"x": float(pos[0]), "y": float(pos[1])},
                        }
                    )

            return {"success": True, "labels": labels, "count": len(labels)}

        except Exception as e:
            logger.error(f"Error listing schematic labels: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_move_schematic_component(self, params):
        """Move a schematic component to a new position"""
        logger.info("Moving schematic component")
        try:
            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            position = params.get("position", {})
            new_x = position.get("x")
            new_y = position.get("y")

            if not schematic_path or not reference:
                return {
                    "success": False,
                    "message": "schematicPath and reference are required",
                }
            if new_x is None or new_y is None:
                return {
                    "success": False,
                    "message": "position with x and y is required",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Find the symbol
            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                if symbol.property.Reference.value == reference:
                    old_pos = list(symbol.at.value)
                    old_position = {"x": float(old_pos[0]), "y": float(old_pos[1])}

                    # Preserve rotation (third element)
                    rotation = float(old_pos[2]) if len(old_pos) > 2 else 0
                    symbol.at.value = [new_x, new_y, rotation]

                    SchematicManager.save_schematic(schematic, schematic_path)
                    return {
                        "success": True,
                        "oldPosition": old_position,
                        "newPosition": {"x": new_x, "y": new_y},
                    }

            return {"success": False, "message": f"Component {reference} not found"}

        except Exception as e:
            logger.error(f"Error moving schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_rotate_schematic_component(self, params):
        """Rotate a schematic component"""
        logger.info("Rotating schematic component")
        try:
            schematic_path = params.get("schematicPath")
            reference = params.get("reference")
            angle = params.get("angle", 0)
            mirror = params.get("mirror")

            if not schematic_path or not reference:
                return {
                    "success": False,
                    "message": "schematicPath and reference are required",
                }

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                if symbol.property.Reference.value == reference:
                    pos = list(symbol.at.value)
                    pos[2] = angle if len(pos) > 2 else angle
                    while len(pos) < 3:
                        pos.append(0)
                    pos[2] = angle
                    symbol.at.value = pos

                    # Handle mirror if specified
                    if mirror:
                        if hasattr(symbol, "mirror"):
                            symbol.mirror.value = mirror
                        else:
                            logger.warning(
                                f"Mirror '{mirror}' requested for {reference}, "
                                f"but symbol does not have a 'mirror' attribute; "
                                f"mirror not applied"
                            )

                    SchematicManager.save_schematic(schematic, schematic_path)
                    return {"success": True, "reference": reference, "angle": angle}

            return {"success": False, "message": f"Component {reference} not found"}

        except Exception as e:
            logger.error(f"Error rotating schematic component: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_annotate_schematic(self, params):
        """Annotate unannotated components in schematic (R? -> R1, R2, ...)"""
        logger.info("Annotating schematic")
        try:
            import re

            schematic_path = params.get("schematicPath")
            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            # Collect existing references by prefix
            existing_refs = {}  # prefix -> set of numbers
            unannotated = []  # (symbol, prefix)

            for symbol in schematic.symbol:
                if not hasattr(symbol.property, "Reference"):
                    continue
                ref = symbol.property.Reference.value
                if ref.startswith("_TEMPLATE"):
                    continue

                # Split reference into prefix and number
                match = re.match(r"^([A-Za-z_]+)(\d+)$", ref)
                if match:
                    prefix = match.group(1)
                    num = int(match.group(2))
                    if prefix not in existing_refs:
                        existing_refs[prefix] = set()
                    existing_refs[prefix].add(num)
                elif ref.endswith("?"):
                    prefix = ref[:-1]
                    unannotated.append((symbol, prefix))

            if not unannotated:
                return {
                    "success": True,
                    "annotated": [],
                    "message": "All components already annotated",
                }

            annotated = []
            for symbol, prefix in unannotated:
                if prefix not in existing_refs:
                    existing_refs[prefix] = set()

                # Find next available number
                next_num = 1
                while next_num in existing_refs[prefix]:
                    next_num += 1

                old_ref = symbol.property.Reference.value
                new_ref = f"{prefix}{next_num}"
                symbol.property.Reference.value = new_ref
                existing_refs[prefix].add(next_num)

                uuid_val = str(symbol.uuid.value) if hasattr(symbol, "uuid") else ""
                annotated.append(
                    {
                        "uuid": uuid_val,
                        "oldReference": old_ref,
                        "newReference": new_ref,
                    }
                )

            SchematicManager.save_schematic(schematic, schematic_path)
            return {"success": True, "annotated": annotated}

        except Exception as e:
            logger.error(f"Error annotating schematic: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_wire(self, params):
        """Delete a wire from the schematic matching start/end points"""
        logger.info("Deleting schematic wire")
        try:
            schematic_path = params.get("schematicPath")
            start = params.get("start", {})
            end = params.get("end", {})

            if not schematic_path:
                return {"success": False, "message": "schematicPath is required"}

            from pathlib import Path
            from commands.wire_manager import WireManager

            start_point = [start.get("x", 0), start.get("y", 0)]
            end_point = [end.get("x", 0), end.get("y", 0)]

            deleted = WireManager.delete_wire(
                Path(schematic_path), start_point, end_point
            )
            if deleted:
                return {"success": True}
            else:
                return {"success": False, "message": "No matching wire found"}

        except Exception as e:
            logger.error(f"Error deleting schematic wire: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_delete_schematic_net_label(self, params):
        """Delete a net label from the schematic"""
        logger.info("Deleting schematic net label")
        try:
            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")
            position = params.get("position")

            if not schematic_path or not net_name:
                return {
                    "success": False,
                    "message": "schematicPath and netName are required",
                }

            from pathlib import Path
            from commands.wire_manager import WireManager

            pos_list = None
            if position:
                pos_list = [position.get("x", 0), position.get("y", 0)]

            deleted = WireManager.delete_label(Path(schematic_path), net_name, pos_list)
            if deleted:
                return {"success": True}
            else:
                return {"success": False, "message": f"Label '{net_name}' not found"}

        except Exception as e:
            logger.error(f"Error deleting schematic net label: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_export_schematic_svg(self, params):
        """Export schematic to SVG using kicad-cli"""
        logger.info("Exporting schematic SVG")
        import subprocess
        import glob
        import shutil

        try:
            schematic_path = params.get("schematicPath")
            output_path = params.get("outputPath")

            if not schematic_path or not output_path:
                return {
                    "success": False,
                    "message": "schematicPath and outputPath are required",
                }

            if not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": f"Schematic not found: {schematic_path}",
                }

            # kicad-cli's --output flag for SVG export expects a directory, not a file path.
            # The output file is auto-named based on the schematic name.
            output_dir = os.path.dirname(output_path)
            if not output_dir:
                output_dir = "."

            os.makedirs(output_dir, exist_ok=True)

            cmd = [
                "kicad-cli",
                "sch",
                "export",
                "svg",
                schematic_path,
                "-o",
                output_dir,
            ]

            if params.get("blackAndWhite"):
                cmd.append("--black-and-white")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

            if result.returncode != 0:
                return {
                    "success": False,
                    "message": f"kicad-cli failed: {result.stderr}",
                }

            # kicad-cli names the file after the schematic, so find the generated SVG
            svg_files = glob.glob(os.path.join(output_dir, "*.svg"))
            if not svg_files:
                return {
                    "success": False,
                    "message": "No SVG file produced by kicad-cli",
                }

            generated_svg = svg_files[0]

            # Move/rename to the user-specified output path if it differs
            if os.path.abspath(generated_svg) != os.path.abspath(output_path):
                shutil.move(generated_svg, output_path)

            return {"success": True, "file": {"path": output_path}}

        except FileNotFoundError:
            return {"success": False, "message": "kicad-cli not found in PATH"}
        except Exception as e:
            logger.error(f"Error exporting schematic SVG: {e}")
            return {"success": False, "message": str(e)}

    def _handle_get_net_connections(self, params):
        """Get all connections for a named net"""
        logger.info("Getting net connections")
        try:
            schematic_path = params.get("schematicPath")
            net_name = params.get("netName")

            if not all([schematic_path, net_name]):
                return {"success": False, "message": "Missing required parameters"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            connections = ConnectionManager.get_net_connections(schematic, net_name)
            return {"success": True, "connections": connections}
        except Exception as e:
            logger.error(f"Error getting net connections: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_run_erc(self, params):
        """Run Electrical Rules Check on a schematic via kicad-cli"""
        logger.info("Running ERC on schematic")
        import subprocess
        import tempfile
        import os

        try:
            schematic_path = params.get("schematicPath")
            if not schematic_path or not os.path.exists(schematic_path):
                return {
                    "success": False,
                    "message": "Schematic file not found",
                    "errorDetails": f"Path does not exist: {schematic_path}",
                }

            kicad_cli = self.design_rule_commands._find_kicad_cli()
            if not kicad_cli:
                return {
                    "success": False,
                    "message": "kicad-cli not found",
                    "errorDetails": "Install KiCAD 8.0+ or add kicad-cli to PATH.",
                }

            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".json", delete=False
            ) as tmp:
                json_output = tmp.name

            try:
                cmd = [
                    kicad_cli,
                    "sch",
                    "erc",
                    "--format",
                    "json",
                    "--output",
                    json_output,
                    schematic_path,
                ]
                logger.info(f"Running ERC command: {' '.join(cmd)}")

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=120
                )

                if not os.path.exists(json_output) or os.path.getsize(json_output) == 0:
                    logger.error(f"ERC command failed: {result.stderr}")
                    return {
                        "success": False,
                        "ercPassed": False,
                        "message": "ERC command failed",
                        "errorDetails": result.stderr or result.stdout,
                        "exitCode": result.returncode,
                    }

                with open(json_output, "r", encoding="utf-8") as f:
                    erc_data = json.load(f)

                from commands.erc_report import parse_kicad_erc_report

                parsed = parse_kicad_erc_report(erc_data)
                parsed["exitCode"] = result.returncode
                return parsed

            finally:
                if os.path.exists(json_output):
                    os.unlink(json_output)

        except subprocess.TimeoutExpired:
            return {"success": False, "message": "ERC timed out after 120 seconds"}
        except Exception as e:
            logger.error(f"Error running ERC: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_generate_netlist(self, params):
        """Generate netlist from schematic"""
        logger.info("Generating netlist from schematic")
        try:
            schematic_path = params.get("schematicPath")

            if not schematic_path:
                return {"success": False, "message": "Schematic path is required"}

            schematic = SchematicManager.load_schematic(schematic_path)
            if not schematic:
                return {"success": False, "message": "Failed to load schematic"}

            netlist = ConnectionManager.generate_netlist(
                schematic, schematic_path=schematic_path
            )
            return {"success": True, "netlist": netlist}
        except Exception as e:
            logger.error(f"Error generating netlist: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_sync_schematic_to_board(self, params):
        """Create or update an offline PCB from the schematic.

        The KiCad netlist exported by kicad-cli is the authority. Library
        footprints are loaded and their pads are assigned those nets. The
        target is an explicit boardPath and is saved only by the offline
        workflow. This command does not write a board open in the editor.
        """
        logger.info("Syncing schematic to board")
        try:
            from pathlib import Path

            schematic_path = params.get("schematicPath")
            board_path = params.get("boardPath")
            if not board_path:
                return {
                    "success": False,
                    "error": "MISSING_PCB_TARGET",
                    "message": "boardPath is required. This command does not choose a board on its own.",
                }
            refusal = self._file_refusal(board_path, "explicit_file")
            if refusal is not None:
                return refusal
            if not schematic_path or not Path(schematic_path).exists():
                return {
                    "success": False,
                    "error": "SCHEMATIC_NOT_FOUND",
                    "message": f"Schematic not found: {schematic_path}",
                }

            internal_netlist = None
            schematic = SchematicManager.load_schematic(schematic_path)
            if schematic:
                internal_netlist = ConnectionManager.generate_netlist(
                    schematic, schematic_path=Path(schematic_path)
                )

            from kicad_api.schematic_sync import (
                SyncFailure,
                synchronize_schematic_to_pcb,
            )

            try:
                result = synchronize_schematic_to_pcb(
                    schematic_path, board_path, internal_netlist
                )
            except SyncFailure as failure:
                return {
                    "success": False,
                    "error": failure.code,
                    "message": failure.message,
                }
            if not self.use_ipc:
                import pcbnew

                self.board = pcbnew.LoadBoard(board_path)
                self._update_command_handlers()
                self._remember_offline_board()
            result["message"] = (
                f"Synchronised {len(result['footprints'])} footprints "
                f"({len(result['created'])} added, {len(result['updated'])} updated)."
            )
            return result

        except Exception as e:
            logger.error(f"Error in sync_schematic_to_board: {e}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_import_svg_logo(self, params):
        """Import an SVG file as PCB graphic polygons on the silkscreen"""
        logger.info("Importing SVG logo into PCB")
        try:
            from commands.svg_import import import_svg_to_pcb

            pcb_path = params.get("pcbPath")
            svg_path = params.get("svgPath")
            x = float(params.get("x", 0))
            y = float(params.get("y", 0))
            width = float(params.get("width", 10))
            layer = params.get("layer", "F.SilkS")
            stroke_width = float(params.get("strokeWidth", 0))
            filled = bool(params.get("filled", True))

            if not pcb_path or not svg_path:
                return {
                    "success": False,
                    "message": "Missing required parameters: pcbPath, svgPath",
                }

            refusal = self._file_refusal(pcb_path, "explicit_file")
            if refusal is not None:
                return refusal

            result = import_svg_to_pcb(
                pcb_path, svg_path, x, y, width, layer, stroke_width, filled
            )

            # import_svg_to_pcb writes gr_poly entries directly to the .kicad_pcb file,
            # bypassing the pcbnew in-memory board object.  Any subsequent board.Save()
            # call would overwrite the file with the stale in-memory state, erasing the
            # logo.  Reload the board from disk so pcbnew's memory matches the file.
            if result.get("success") and self.board:
                try:
                    self.board = pcbnew.LoadBoard(pcb_path)
                    # Propagate updated board reference to all command handlers
                    self._update_command_handlers()
                    logger.info("Reloaded board into pcbnew after SVG logo import")
                except Exception as reload_err:
                    logger.warning(
                        f"Board reload after SVG import failed (non-fatal): {reload_err}"
                    )

            return result

        except Exception as e:
            logger.error(f"Error importing SVG logo: {str(e)}")
            import traceback

            logger.error(traceback.format_exc())
            return {"success": False, "message": str(e)}

    def _handle_snapshot_project(self, params):
        """Copy the entire project folder to a snapshot directory for checkpoint/resume."""
        import shutil
        from datetime import datetime
        from pathlib import Path

        try:
            step = params.get("step", "")
            label = params.get("label", "")
            prompt_text = params.get("prompt", "")
            # Determine project directory from loaded board or explicit path
            project_dir = None
            if self.board:
                board_file = self.board.GetFileName()
                if board_file:
                    project_dir = str(Path(board_file).parent)
            if not project_dir:
                project_dir = params.get("projectPath")
            if not project_dir or not os.path.isdir(project_dir):
                return {
                    "success": False,
                    "message": "Could not determine project directory for snapshot",
                }

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Save prompt + log into logs/ subdirectory before snapshotting
            logs_dir = Path(project_dir) / "logs"
            logs_dir.mkdir(exist_ok=True)

            prompt_file = None
            if prompt_text:
                prompt_filename = (
                    f"PROMPT_step{step}_{ts}.md" if step else f"PROMPT_{ts}.md"
                )
                prompt_file = logs_dir / prompt_filename
                prompt_file.write_text(prompt_text, encoding="utf-8")
                logger.info(f"Prompt saved: {prompt_file}")

            # Copy current MCP session log into logs/ before snapshotting
            import platform

            system = platform.system()
            if system == "Windows":
                mcp_log_dir = os.path.join(
                    os.environ.get("APPDATA", ""), "Claude", "logs"
                )
            elif system == "Darwin":
                mcp_log_dir = os.path.expanduser("~/Library/Logs/Claude")
            else:
                mcp_log_dir = os.path.expanduser("~/.config/Claude/logs")
            mcp_log_src = os.path.join(mcp_log_dir, "mcp-server-kicad.log")
            mcp_log_dest = None
            if os.path.exists(mcp_log_src):
                with open(mcp_log_src, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
                session_start = 0
                for i, line in enumerate(all_lines):
                    if "Initializing server" in line:
                        session_start = i
                session_lines = all_lines[session_start:]
                log_filename = (
                    f"mcp_log_step{step}_{ts}.txt" if step else f"mcp_log_{ts}.txt"
                )
                mcp_log_dest = logs_dir / log_filename
                with open(mcp_log_dest, "w", encoding="utf-8") as f:
                    f.writelines(session_lines)
                logger.info(
                    f"MCP session log saved: {mcp_log_dest} ({len(session_lines)} lines)"
                )

            base_name = Path(project_dir).name
            suffix_parts = [p for p in [f"step{step}" if step else "", label, ts] if p]
            snapshot_name = base_name + "_snapshot_" + "_".join(suffix_parts)
            snapshots_base = Path(project_dir) / "snapshots"
            snapshots_base.mkdir(exist_ok=True)
            snapshot_dir = str(snapshots_base / snapshot_name)

            shutil.copytree(
                project_dir, snapshot_dir, ignore=shutil.ignore_patterns("snapshots")
            )
            logger.info(f"Project snapshot saved: {snapshot_dir}")
            return {
                "success": True,
                "message": f"Snapshot saved: {snapshot_name}",
                "snapshotPath": snapshot_dir,
                "sourceDir": project_dir,
                "promptSaved": str(prompt_file) if prompt_file else None,
                "mcpLogSaved": str(mcp_log_dest) if mcp_log_dest else None,
            }
        except Exception as e:
            logger.error(f"snapshot_project error: {e}")
            return {"success": False, "message": str(e)}

    def _handle_check_kicad_ui(self, params):
        """Check if KiCAD UI is running"""
        logger.info("Checking if KiCAD UI is running")
        try:
            manager = KiCADProcessManager()
            is_running = manager.is_running()
            processes = manager.get_process_info() if is_running else []

            return {
                "success": True,
                "running": is_running,
                "processes": processes,
                "message": "KiCAD is running" if is_running else "KiCAD is not running",
            }
        except Exception as e:
            logger.error(f"Error checking KiCAD UI status: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_launch_kicad_ui(self, params):
        """Launch KiCAD UI"""
        logger.info("Launching KiCAD UI")
        try:
            project_path = params.get("projectPath")
            auto_launch = params.get("autoLaunch", AUTO_LAUNCH_KICAD)

            # Convert project path to Path object if provided
            from pathlib import Path

            path_obj = Path(project_path) if project_path else None

            result = check_and_launch_kicad(path_obj, auto_launch)

            return {"success": True, **result}
        except Exception as e:
            logger.error(f"Error launching KiCAD UI: {str(e)}")
            return {"success": False, "message": str(e)}

    def _handle_refill_zones(self, params):
        """Refill all copper pour zones on the board.

        pcbnew.ZONE_FILLER.Fill() can cause a C++ access violation (0xC0000005)
        that crashes the entire Python process when called from SWIG outside KiCAD UI.
        To avoid killing the main process we run the fill in an isolated subprocess.
        If the subprocess crashes or times out, we return a non-fatal warning so the
        caller can continue — KiCAD Pcbnew will refill zones automatically when the
        board is opened (press B).
        """
        logger.info("Refilling zones (subprocess isolation)")
        try:
            if not self.board:
                return {
                    "success": False,
                    "message": "No board is loaded",
                    "errorDetails": "Load or create a board first",
                }

            # First save the board so the subprocess can load it fresh.
            # This stays on the offline path. A live editor document is refused.
            board_path = self.board.GetFileName()
            if not board_path:
                return {
                    "success": False,
                    "message": "Board has no file path — save first",
                }
            refusal = self._file_refusal(board_path, "explicit_file")
            if refusal is not None:
                return refusal
            self.board.Save(board_path)

            zone_count = (
                self.board.GetAreaCount() if hasattr(self.board, "GetAreaCount") else 0
            )

            # Run pcbnew zone fill in an isolated subprocess to prevent crashes
            import subprocess, sys, textwrap

            script = textwrap.dedent(f"""
import pcbnew, sys
board = pcbnew.LoadBoard({repr(board_path)})
filler = pcbnew.ZONE_FILLER(board)
filler.Fill(board.Zones())
board.Save({repr(board_path)})
print("ok")
""")
            try:
                result = subprocess.run(
                    [sys.executable, "-c", script],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if result.returncode == 0 and "ok" in result.stdout:
                    # Reload board after subprocess modified it
                    self.board = pcbnew.LoadBoard(board_path)
                    self._update_command_handlers()
                    logger.info("Zone fill subprocess succeeded")
                    return {
                        "success": True,
                        "message": f"Zones refilled successfully ({zone_count} zones)",
                        "zoneCount": zone_count,
                    }
                else:
                    logger.warning(
                        f"Zone fill subprocess failed: rc={result.returncode} stderr={result.stderr[:200]}"
                    )
                    return {
                        "success": False,
                        "message": "Zone fill failed in subprocess — zones are defined and will fill when opened in KiCAD (press B). Continuing is safe.",
                        "zoneCount": zone_count,
                        "details": (
                            result.stderr[:300]
                            if result.stderr
                            else result.stdout[:300]
                        ),
                    }
            except subprocess.TimeoutExpired:
                logger.warning("Zone fill subprocess timed out after 60s")
                return {
                    "success": False,
                    "message": "Zone fill timed out — zones are defined and will fill when opened in KiCAD (press B). Continuing is safe.",
                    "zoneCount": zone_count,
                }

        except Exception as e:
            logger.error(f"Error refilling zones: {str(e)}")
            return {"success": False, "message": str(e)}

    # =========================================================================
    # IPC Backend handlers - these provide real-time UI synchronization
    # These methods are called automatically when IPC is available
    # =========================================================================

    def _ipc_route_trace(self, params):
        """IPC handler for route_trace - adds track with real-time UI update"""
        try:
            # Extract parameters matching the existing route_trace interface
            start = params.get("start", {})
            end = params.get("end", {})
            layer = params.get("layer", "F.Cu")
            width = params.get("width", 0.25)
            net = params.get("net")

            # Handle both dict format and direct x/y
            start_x = (
                start.get("x", 0)
                if isinstance(start, dict)
                else params.get("startX", 0)
            )
            start_y = (
                start.get("y", 0)
                if isinstance(start, dict)
                else params.get("startY", 0)
            )
            end_x = end.get("x", 0) if isinstance(end, dict) else params.get("endX", 0)
            end_y = end.get("y", 0) if isinstance(end, dict) else params.get("endY", 0)

            if not isinstance(net, str) or not net.strip():
                return {
                    "success": False,
                    "error": "INVALID_ARGUMENT",
                    "message": "route_trace requires the name of an existing net.",
                }
            net = net.strip()

            result = self.ipc_board_api.add_track(
                start_x=start_x,
                start_y=start_y,
                end_x=end_x,
                end_y=end_y,
                width=width,
                layer=layer,
                net_name=net,
            )
            if not isinstance(result, dict):
                result = {
                    "success": False,
                    "error": "IPC_PROTOCOL",
                    "message": "Track creation did not return a result object.",
                }
            if not result.get("success") or result.get("net") != net:
                result["success"] = False
                result.setdefault("error", "NET_MISMATCH")
                result.setdefault(
                    "message",
                    f"The track net does not match '{net}'.",
                )
                return result

            return {
                "success": True,
                "message": "Added trace (visible in KiCAD UI)",
                "id": result.get("id", ""),
                "trace": {
                    "start": {"x": start_x, "y": start_y, "unit": "mm"},
                    "end": {"x": end_x, "y": end_y, "unit": "mm"},
                    "layer": layer,
                    "width": width,
                    "net": result.get("net", ""),
                },
            }
        except Exception as e:
            logger.error(f"IPC route_trace error: {e}")
            return {"success": False, "message": str(e)}

    def _refuse_offline_route(self, params):
        """Pad routing writes an open board only through IPC."""
        result = ipc_unavailable_result()
        result["_keep_backend"] = True
        result["message"] = (
            "Pad-to-pad routing requires an active KiCad IPC connection. "
            "The board file was not modified."
        )
        return result

    def _ipc_route_pad_to_pad(self, params):
        """Route one pair of pads on a named net. A failed check creates no track."""
        refusal = self._require_open_board(params.get("boardPath", ""))
        if refusal:
            return refusal
        request = {
            "sourceRef": params.get("sourceRef", params.get("fromRef")),
            "sourcePad": params.get("sourcePad", params.get("fromPad")),
            "destinationRef": params.get("destinationRef", params.get("toRef")),
            "destinationPad": params.get("destinationPad", params.get("toPad")),
            "net": params.get("net"),
            "width": params.get("width"),
            "layer": params.get("layer", "F.Cu"),
            "clearance": params.get("clearance", 0.2),
        }
        return self.ipc_board_api.route_pad_to_pad(request)

    def _ipc_add_via(self, params):
        """IPC handler for add_via - adds via with real-time UI update"""
        try:
            position = params.get("position", {})
            x = (
                position.get("x", 0)
                if isinstance(position, dict)
                else params.get("x", 0)
            )
            y = (
                position.get("y", 0)
                if isinstance(position, dict)
                else params.get("y", 0)
            )

            size = params.get("size", 0.8)
            drill = params.get("drill", 0.4)
            net = params.get("net")
            from_layer = params.get("from_layer", "F.Cu")
            to_layer = params.get("to_layer", "B.Cu")

            success = self.ipc_board_api.add_via(
                x=x, y=y, diameter=size, drill=drill, net_name=net, via_type="through"
            )

            return {
                "success": success,
                "message": (
                    "Added via (visible in KiCAD UI)"
                    if success
                    else "Failed to add via"
                ),
                "via": {
                    "position": {"x": x, "y": y, "unit": "mm"},
                    "size": size,
                    "drill": drill,
                    "from_layer": from_layer,
                    "to_layer": to_layer,
                    "net": net,
                },
            }
        except Exception as e:
            logger.error(f"IPC add_via error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_net(self, params):
        """IPC handler for add_net. KiCad 10 IPC cannot create a net."""
        try:
            name = params.get("name", "")
            net_class = params.get("netClass", params.get("net_class"))
            logger.info("IPC add_net requested: %s", name)
            return self.ipc_board_api.add_net(name, net_class)
        except Exception as e:
            logger.error(f"IPC add_net error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_copper_pour(self, params):
        """IPC handler for add_copper_pour - adds zone with real-time UI update"""
        try:
            layer = params.get("layer", "F.Cu")
            net = params.get("net")
            clearance = params.get("clearance", 0.5)
            min_width = params.get("minWidth", 0.25)
            points = params.get("points", [])
            priority = params.get("priority", 0)
            fill_type = params.get("fillType", "solid")
            name = params.get("name", "")

            if not points or len(points) < 3:
                return {
                    "success": False,
                    "message": "At least 3 points are required for copper pour outline",
                }

            # Convert points format if needed (handle both {x, y} and {x, y, unit})
            formatted_points = []
            for point in points:
                formatted_points.append(
                    {"x": point.get("x", 0), "y": point.get("y", 0)}
                )

            success = self.ipc_board_api.add_zone(
                points=formatted_points,
                layer=layer,
                net_name=net,
                clearance=clearance,
                min_thickness=min_width,
                priority=priority,
                fill_mode=fill_type,
                name=name,
            )

            return {
                "success": success,
                "message": (
                    "Added copper pour (visible in KiCAD UI)"
                    if success
                    else "Failed to add copper pour"
                ),
                "pour": {
                    "layer": layer,
                    "net": net,
                    "clearance": clearance,
                    "minWidth": min_width,
                    "priority": priority,
                    "fillType": fill_type,
                    "pointCount": len(points),
                },
            }
        except Exception as e:
            logger.error(f"IPC add_copper_pour error: {e}")
            return {"success": False, "message": str(e)}

    def _phase5_add_wire(self, params):
        from kicad_api.phase5 import add_wire_result

        return add_wire_result(params)

    def _phase5_add_net_class(self, params):
        from kicad_api.phase5 import add_net_class_result

        return add_net_class_result(params)

    def _phase5_assign_net_to_class(self, params):
        from kicad_api.phase5 import assign_net_to_class_result

        return assign_net_to_class_result(params)

    def _phase5_check_clearance(self, params):
        from kicad_api.phase5 import check_clearance_result

        return check_clearance_result(params)

    def _phase5_replace_component(self, params):
        from kicad_api.phase5 import replace_component_result

        return replace_component_result(params)

    def _phase5_set_layer_constraints(self, params):
        from kicad_api.phase5 import set_layer_constraints_result

        return set_layer_constraints_result(params)

    def _phase5_export_netlist(self, params):
        from kicad_api.pcb_safety import ipc_unavailable_result
        from kicad_api.phase5 import export_netlist

        paths = self.ipc_board_api._open_pcb_paths() if self.ipc_board_api else []
        if len(paths) != 1:
            result = ipc_unavailable_result()
            result["_keep_backend"] = True
            result["message"] = "Netlist export needs exactly one open PCB so the matching schematic can be identified."
            return result
        return export_netlist(paths[0], params)

    def _phase5_export_vrml(self, params):
        from kicad_api.pcb_safety import ipc_unavailable_result
        from kicad_api.phase5 import export_vrml

        paths = self.ipc_board_api._open_pcb_paths() if self.ipc_board_api else []
        if len(paths) != 1:
            result = ipc_unavailable_result()
            result["_keep_backend"] = True
            result["message"] = "VRML export needs exactly one open PCB."
            return result
        return export_vrml(paths[0], params)

    def _phase5_export_gerber(self, params):
        """Plot from a copy of the saved PCB with kicad-cli. SWIG PLOT_CONTROLLER is not used."""
        from kicad_api.pcb_safety import ipc_unavailable_result
        from kicad_api.phase5 import export_gerber

        paths = []
        if self.ipc_board_api:
            try:
                paths = self.ipc_board_api._open_pcb_paths()
            except Exception as exc:
                logger.warning("Could not list open PCBs for Gerber export: %s", exc)
                paths = []
        if len(paths) > 1:
            result = ipc_unavailable_result()
            result["_keep_backend"] = True
            result["message"] = "Gerber export needs exactly one open PCB."
            return result
        board_path = paths[0] if paths else self._swig_board_path()
        if not board_path:
            result = ipc_unavailable_result()
            result["_keep_backend"] = True
            result["message"] = "Gerber export needs an open PCB in the PCB editor or a saved loaded board."
            return result
        result = export_gerber(board_path, params)
        if result.get("success") and os.environ.get("KICAD_MCP_DEV") == "1":
            try:
                self.export_commands._dev_copy_mcp_log(result["outputDir"])
            except Exception as dev_err:
                logger.warning(f"[DEV] Could not copy MCP log: {dev_err}")
        return result

    def _ipc_add_zone(self, params):
        return self.ipc_board_api.create_verified_zone(params)

    def _ipc_add_component_annotation(self, params):
        return self.ipc_board_api.annotate_component(
            params.get("reference", ""),
            params.get("annotation", ""),
            params.get("visible"),
        )

    def _ipc_group_components(self, params):
        return self.ipc_board_api.group_components(
            params.get("references") or [],
            params.get("groupName", ""),
        )

    def _ipc_export_position_file(self, params):
        from kicad_api.phase5 import export_position_file

        payload = dict(params)
        payload["_open_paths"] = self.ipc_board_api._open_pcb_paths()
        return export_position_file(self.ipc_board_api.list_components(), payload)

    def _ipc_refill_zones(self, params):
        """IPC handler for refill_zones - refills all zones with real-time UI update"""
        try:
            success = self.ipc_board_api.refill_zones()

            return {
                "success": success,
                "message": (
                    "Zones refilled (visible in KiCAD UI)"
                    if success
                    else "Failed to refill zones"
                ),
            }
        except Exception as e:
            logger.error(f"IPC refill_zones error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_text(self, params):
        """IPC handler for add_text/add_board_text - adds text with real-time UI update"""
        try:
            text = params.get("text", "")
            position = params.get("position", {})
            x = (
                position.get("x", 0)
                if isinstance(position, dict)
                else params.get("x", 0)
            )
            y = (
                position.get("y", 0)
                if isinstance(position, dict)
                else params.get("y", 0)
            )
            layer = params.get("layer", "F.SilkS")
            size = params.get("size", 1.0)
            rotation = params.get("rotation", 0)

            success = self.ipc_board_api.add_text(
                text=text, x=x, y=y, layer=layer, size=size, rotation=rotation
            )

            return {
                "success": success,
                "message": (
                    f"Added text '{text}' (visible in KiCAD UI)"
                    if success
                    else "Failed to add text"
                ),
            }
        except Exception as e:
            logger.error(f"IPC add_text error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_set_board_size(self, params):
        """IPC handler for set_board_size"""
        try:
            width = params.get("width", 100)
            height = params.get("height", 100)
            unit = params.get("unit", "mm")

            success = self.ipc_board_api.set_size(width, height, unit)

            return {
                "success": success,
                "message": (
                    f"Board size set to {width}x{height} {unit} (visible in KiCAD UI)"
                    if success
                    else "Failed to set board size"
                ),
                "boardSize": {"width": width, "height": height, "unit": unit},
            }
        except Exception as e:
            logger.error(f"IPC set_board_size error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_get_board_info(self, params):
        """IPC handler for get_board_info"""
        try:
            size = self.ipc_board_api.get_size()
            components = self.ipc_board_api.list_components()
            tracks = self.ipc_board_api.get_tracks()
            vias = self.ipc_board_api.get_vias()
            nets = self.ipc_board_api.get_nets()

            return {
                "success": True,
                "boardInfo": {
                    "size": size,
                    "componentCount": len(components),
                    "trackCount": len(tracks),
                    "viaCount": len(vias),
                    "netCount": len(nets),
                    "backend": "ipc",
                    "realtime": True,
                },
            }
        except Exception as e:
            logger.error(f"IPC get_board_info error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_place_component(self, params):
        """IPC handler for place_component - clones an on-board footprint in real time."""
        try:
            import math

            reference = params.get("reference", params.get("componentId", ""))
            footprint = params.get("footprint", "")
            position = params.get("position")
            rotation = params.get("rotation", 0)
            layer = params.get("layer", "F.Cu")
            value = params.get("value", "")
            board_path = params.get("boardPath")

            if not isinstance(reference, str) or not reference.strip():
                return {"success": False, "message": "reference is required"}

            if not isinstance(footprint, str) or not footprint.strip():
                return {
                    "success": False,
                    "message": "footprint is required in Library:FootprintName format",
                }

            if not isinstance(position, dict):
                return {"success": False, "message": "position must be an object"}

            x = position.get("x")
            y = position.get("y")
            unit = position.get("unit", "mm")

            if unit not in ("mm", "inch"):
                return {"success": False, "message": "position.unit must be mm or inch"}

            if (
                isinstance(x, bool)
                or isinstance(y, bool)
                or not isinstance(x, (int, float))
                or not isinstance(y, (int, float))
                or not math.isfinite(x)
                or not math.isfinite(y)
            ):
                return {
                    "success": False,
                    "message": "position.x and position.y must be finite numbers",
                }

            if unit == "inch":
                x *= 25.4
                y *= 25.4

            if rotation is None:
                rotation = 0
            if (
                isinstance(rotation, bool)
                or not isinstance(rotation, (int, float))
                or not math.isfinite(rotation)
            ):
                return {"success": False, "message": "rotation must be a finite number"}

            if layer is None:
                layer = "F.Cu"

            result = self.ipc_board_api.place_component(
                reference=reference.strip(),
                footprint=footprint.strip(),
                x=float(x),
                y=float(y),
                rotation=float(rotation),
                layer=layer,
                value=value or "",
                board_path=board_path,
            )

            if isinstance(result, dict):
                if result.get("success") and "message" not in result:
                    result["message"] = (
                        f"Placed component {reference.strip()} (visible in KiCAD UI)"
                    )
                elif not result.get("success") and "message" not in result:
                    result["message"] = result.get("error", "Failed to place component")
                return result

            return {"success": False, "message": "Place handler returned no result"}
        except Exception as e:
            logger.error(f"IPC place_component error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_move_component(self, params):
        """IPC handler for move_component - moves component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            position = params.get("position", {})
            x = (
                position.get("x", 0)
                if isinstance(position, dict)
                else params.get("x", 0)
            )
            y = (
                position.get("y", 0)
                if isinstance(position, dict)
                else params.get("y", 0)
            )
            rotation = params.get("rotation")

            success = self.ipc_board_api.move_component(
                reference=reference, x=x, y=y, rotation=rotation
            )

            return {
                "success": success,
                "message": (
                    f"Moved component {reference} (visible in KiCAD UI)"
                    if success
                    else "Failed to move component"
                ),
            }
        except Exception as e:
            logger.error(f"IPC move_component error: {e}")
            return {"success": False, "message": str(e)}

    def _refuse_offline_placement(self, params):
        """Placement edits are live IPC operations. This path does not save a board."""
        result = ipc_unavailable_result()
        result["_keep_backend"] = True
        return result

    def _require_open_board(self, board_path: str):
        from kicad_api.pcb_safety import paths_refer_to_same_file

        if not board_path:
            return {
                "success": False,
                "error": "MISSING_PCB_TARGET",
                "message": "boardPath is required.",
            }
        try:
            open_paths = self.ipc_board_api._open_pcb_paths()
        except Exception as exc:
            return {
                "success": False,
                "error": "EDITOR_STATE_UNKNOWN",
                "message": f"Could not list the open PCB: {exc}",
            }
        if len(open_paths) != 1 or not paths_refer_to_same_file(open_paths[0], board_path):
            return {
                "success": False,
                "error": "BOARD_MISMATCH",
                "message": (
                    "The open PCB is "
                    + (", ".join(open_paths) if open_paths else "none")
                    + f". Expected {board_path}."
                ),
            }
        return None

    def _ipc_get_footprint_geometry(self, params):
        refusal = self._require_open_board(params.get("boardPath", ""))
        if refusal:
            return refusal
        return self.ipc_board_api.read_placement_geometry()

    def _ipc_check_placement(self, params):
        from kicad_api.placement import board_box, validate_placement

        refusal = self._require_open_board(params.get("boardPath", ""))
        if refusal:
            return refusal
        geometry = self.ipc_board_api.read_placement_geometry()
        outline = self.ipc_board_api.measure_edge_cuts()
        if not outline.get("present"):
            return {
                "success": False,
                "error": "MISSING_OUTLINE",
                "message": "The board has no Edge.Cuts outline.",
                "footprints": geometry.get("footprints", []),
            }
        parts = []
        for item in geometry.get("footprints", []):
            part = {
                "reference": item["reference"],
                "x": item["x"],
                "y": item["y"],
                "courtyard": item.get("courtyard"),
                "nets": item.get("nets", []),
            }
            if item.get("body"):
                part["body"] = item["body"]
            parts.append(part)
        width = outline["width"]
        height = outline["height"]
        center = outline["center"]
        board = board_box(width, height, center["x"], center["y"])
        checked = validate_placement(
            parts,
            board,
            edge_clearance_mm=float(params.get("edgeClearance", 0.5)),
            courtyard_gap_mm=float(params.get("courtyardGap", 0.25)),
            max_connected_span_mm=params.get("maxConnectedSpan", 25.0),
        )
        checked["outline"] = outline
        checked["footprints"] = geometry.get("footprints", [])
        return checked

    def _ipc_apply_placement(self, params):
        from kicad_api.placement import (
            PlacementError,
            board_box,
            plan_led_switch,
            placed_parts,
            validate_placement,
        )

        refusal = self._require_open_board(params.get("boardPath", ""))
        if refusal:
            return refusal
        strategy = params.get("strategy", "led_switch")
        if strategy != "led_switch":
            return {
                "success": False,
                "error": "UNSUPPORTED_PLACEMENT",
                "message": f"Placement strategy '{strategy}' is not implemented.",
            }
        width = float(params.get("width", 50.0))
        height = float(params.get("height", 40.0))
        # 1.5 mm keeps connector reference text, which sits outside the courtyard, on the board.
        edge = float(params.get("edgeClearance", 1.5))
        gap = float(params.get("courtyardGap", 1.0))
        geometry = self.ipc_board_api.read_placement_geometry()
        local = {}
        nets = {}
        bodies = {}
        before_pads = {}
        for item in geometry.get("footprints", []):
            if "localCourtyard" not in item:
                return {
                    "success": False,
                    "error": "MISSING_COURTYARD",
                    "message": f"{item.get('reference', '')} has no courtyard.",
                }
            local[item["reference"]] = item["localCourtyard"]
            nets[item["reference"]] = item.get("nets", [])
            if item.get("localBody"):
                bodies[item["reference"]] = item["localBody"]
            for pad in item.get("pads", []):
                before_pads[(item["reference"], pad["number"])] = pad["net"]
        try:
            plan = plan_led_switch(local, width, height, edge, gap)
        except PlacementError as failure:
            return {"success": False, "error": failure.code, "message": failure.message}
        preview = placed_parts(local, plan["placements"], nets, bodies or None)
        planned = validate_placement(
            preview,
            board_box(width, height),
            edge_clearance_mm=edge,
            courtyard_gap_mm=gap,
            max_connected_span_mm=25.0,
        )
        if not planned["success"]:
            return {
                "success": False,
                "error": "PLACEMENT_REJECTED",
                "message": "The planned positions fail the placement checks.",
                "problems": planned["problems"],
                "plan": plan,
            }
        outline_result = None
        if params.get("includeOutline", True):
            existing = self.ipc_board_api.measure_edge_cuts()
            expected = board_box(width, height)
            if existing.get("present"):
                box = existing["box"]
                same = all(
                    abs(box[key] - expected[key]) <= 0.05 for key in ("xmin", "ymin", "xmax", "ymax")
                )
                if not same:
                    return {
                        "success": False,
                        "error": "OUTLINE_CONFLICT",
                        "message": "An Edge.Cuts outline is already present and it is not the requested rectangle.",
                        "outline": existing,
                    }
            else:
                outline_result = self.ipc_board_api.add_board_outline(
                    {
                        "shape": "rectangle",
                        "x": expected["xmin"],
                        "y": expected["ymin"],
                        "width": width,
                        "height": height,
                        "unit": "mm",
                    }
                )
                if not outline_result.get("success"):
                    return outline_result
                measured = self.ipc_board_api.measure_edge_cuts()
                if (
                    not measured.get("present")
                    or abs(measured["width"] - width) > 0.05
                    or abs(measured["height"] - height) > 0.05
                    or abs(measured["center"]["x"]) > 0.05
                    or abs(measured["center"]["y"]) > 0.05
                ):
                    return {
                        "success": False,
                        "error": "IPC_VERIFY_FAILED",
                        "message": "The outline was not the requested rectangle after read-back.",
                        "outline": measured,
                    }
                outline_result["measured"] = measured
        placements = [
            {"reference": reference, **place}
            for reference, place in plan["placements"].items()
        ]
        moved = self.ipc_board_api.place_components(placements)
        if not moved.get("success"):
            moved["plan"] = plan
            return moved
        checked = self._ipc_check_placement(
            {
                "boardPath": params.get("boardPath"),
                "edgeClearance": edge,
                "courtyardGap": gap,
                "maxConnectedSpan": 25.0,
            }
        )
        after = self.ipc_board_api.read_placement_geometry()
        after_pads = {}
        for item in after.get("footprints", []):
            for pad in item.get("pads", []):
                after_pads[(item["reference"], pad["number"])] = pad["net"]
        if after_pads != before_pads:
            return {
                "success": False,
                "error": "NET_CHANGED",
                "message": "Pad nets changed. The placement was not left in that state if restore succeeded.",
                "plan": plan,
            }
        return {
            "success": bool(checked.get("success")),
            "message": "Placement applied." if checked.get("success") else "Placement read-back failed its checks.",
            "optimised": False,
            "strategy": plan["strategy"],
            "plan": plan,
            "outline": outline_result,
            "check": checked,
            "readBack": moved.get("readBack"),
        }

    def _ipc_clone_component(self, params):
        """Clone an existing PCB footprint using real-time IPC."""
        try:
            import math

            source_reference = params.get("sourceReference")
            new_reference = params.get("newReference")
            position = params.get("position")
            rotation = params.get("rotation")
            value = params.get("value")
            copy_nets = params.get("copyNets", False)

            if not isinstance(source_reference, str) or not source_reference.strip():
                return {
                    "success": False,
                    "message": "sourceReference is required",
                }

            if not isinstance(new_reference, str) or not new_reference.strip():
                return {
                    "success": False,
                    "message": "newReference is required",
                }

            if not isinstance(position, dict):
                return {
                    "success": False,
                    "message": "position must be an object",
                }

            x = position.get("x")
            y = position.get("y")
            unit = position.get("unit", "mm")

            if unit not in ("mm", "inch"):
                return {
                    "success": False,
                    "message": "position.unit must be mm or inch",
                }

            if (
                isinstance(x, bool)
                or isinstance(y, bool)
                or not isinstance(x, (int, float))
                or not isinstance(y, (int, float))
                or not math.isfinite(x)
                or not math.isfinite(y)
            ):
                return {
                    "success": False,
                    "message": "position.x and position.y must be finite numbers",
                }

            if unit == "inch":
                x *= 25.4
                y *= 25.4

            if rotation is not None and (
                isinstance(rotation, bool)
                or not isinstance(rotation, (int, float))
                or not math.isfinite(rotation)
            ):
                return {
                    "success": False,
                    "message": "rotation must be a finite number",
                }

            if not isinstance(copy_nets, bool):
                return {
                    "success": False,
                    "message": "copyNets must be a boolean",
                }

            # Same board API used by _ipc_move_component.
            result = self.ipc_board_api.clone_component(
                source_reference=source_reference.strip(),
                new_reference=new_reference.strip(),
                x=float(x),
                y=float(y),
                rotation=None if rotation is None else float(rotation),
                value=value,
                copy_nets=copy_nets,
            )

            if isinstance(result, dict):
                if result.get("success") and "message" not in result:
                    result["message"] = (
                        f"Cloned {source_reference.strip()} as {new_reference.strip()} "
                        "(visible in KiCAD UI)"
                    )
                elif not result.get("success") and "message" not in result:
                    result["message"] = result.get("error", "Failed to clone component")
                return result

            return {
                "success": False,
                "message": "Clone handler returned no result",
            }
        except Exception as e:
            logger.error(f"IPC clone_component error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_delete_component(self, params):
        """IPC handler for delete_component - deletes component with real-time UI update"""
        try:
            reference = params.get("reference", params.get("componentId", ""))

            success = self.ipc_board_api.delete_component(reference=reference)

            return {
                "success": success,
                "message": (
                    f"Deleted component {reference} (visible in KiCAD UI)"
                    if success
                    else "Failed to delete component"
                ),
            }
        except Exception as e:
            logger.error(f"IPC delete_component error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_get_component_list(self, params):
        """IPC handler for get_component_list"""
        try:
            components = self.ipc_board_api.list_components()

            return {"success": True, "components": components, "count": len(components)}
        except Exception as e:
            logger.error(f"IPC get_component_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_save_project(self, params):
        """IPC handler for save_project"""
        try:
            success = self.ipc_board_api.save()

            return {
                "success": success,
                "message": "Project saved" if success else "Failed to save project",
            }
        except Exception as e:
            logger.error(f"IPC save_project error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_delete_trace(self, params):
        """Delete traces through IPC. This handler does not call the SWIG board."""
        return self.ipc_board_api.delete_traces(params)

    def _ipc_get_nets_list(self, params):
        """IPC handler for get_nets_list - gets nets with real-time data"""
        try:
            nets = self.ipc_board_api.get_nets()

            return {"success": True, "nets": nets, "count": len(nets)}
        except Exception as e:
            logger.error(f"IPC get_nets_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_add_board_outline(self, params):
        """Add an outline through IPC. Rectangles are not delegated to SWIG."""
        return self.ipc_board_api.add_board_outline(params)

    def _ipc_add_mounting_hole(self, params):
        """IPC handler for add_mounting_hole - adds mounting hole with real-time UI update"""
        try:
            from kipy.board_types import BoardCircle
            from kipy.geometry import Vector2
            from kipy.util.units import from_mm
            from kipy.proto.board.board_types_pb2 import BoardLayer

            board = self.ipc_board_api._get_board()

            x = params.get("x", 0)
            y = params.get("y", 0)
            diameter = params.get("diameter", 3.2)  # M3 hole default

            commit = board.begin_commit()

            # Create circle on Edge.Cuts layer for the hole
            circle = BoardCircle()
            circle.center = Vector2.from_xy(from_mm(x), from_mm(y))
            circle.radius = from_mm(diameter / 2)
            circle.layer = BoardLayer.BL_Edge_Cuts
            circle.attributes.stroke.width = from_mm(0.1)

            board.create_items(circle)
            board.push_commit(commit, f"Added mounting hole at ({x}, {y})")

            return {
                "success": True,
                "message": f"Added mounting hole at ({x}, {y}) mm (visible in KiCAD UI)",
                "hole": {"position": {"x": x, "y": y}, "diameter": diameter},
            }
        except Exception as e:
            logger.error(f"IPC add_mounting_hole error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_get_layer_list(self, params):
        """IPC handler for get_layer_list - gets enabled layers"""
        try:
            layers = self.ipc_board_api.get_enabled_layers()

            return {"success": True, "layers": layers, "count": len(layers)}
        except Exception as e:
            logger.error(f"IPC get_layer_list error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_rotate_component(self, params):
        """Set a component's absolute rotation and read it back."""
        try:
            reference = params.get("reference", params.get("componentId", ""))
            if "angle" in params:
                angle = params.get("angle")
            elif "rotation" in params:
                angle = params.get("rotation")
            else:
                return {
                    "success": False,
                    "error": "INVALID_ARGUMENT",
                    "message": "angle is required and is an absolute rotation in degrees.",
                }
            if isinstance(angle, bool) or not isinstance(angle, (int, float)):
                return {
                    "success": False,
                    "error": "INVALID_ARGUMENT",
                    "message": "angle must be a number of degrees.",
                }
            if angle != angle or angle in (float("inf"), float("-inf")):
                return {
                    "success": False,
                    "error": "INVALID_ARGUMENT",
                    "message": "angle must be a finite number of degrees.",
                }
            target_angle = float(angle) % 360.0

            components = self.ipc_board_api.list_components()
            target = None
            for comp in components:
                if comp.get("reference") == reference:
                    target = comp
                    break

            if not target:
                return {"success": False, "message": f"Component {reference} not found"}

            position = target.get("position") or {}
            previous = target.get("rotation", 0)
            moved = self.ipc_board_api.move_component(
                reference=reference,
                x=position.get("x", 0),
                y=position.get("y", 0),
                rotation=target_angle,
            )

            after = None
            for comp in self.ipc_board_api.list_components():
                if comp.get("reference") == reference:
                    after = comp
                    break

            actual = None if after is None else after.get("rotation")
            same_part = (
                after is not None
                and after.get("id") == target.get("id")
                and after.get("footprint") == target.get("footprint")
            )

            def close_enough(value):
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    return False
                delta = (float(value) - target_angle) % 360.0
                if delta > 180.0:
                    delta = 360.0 - delta
                return delta <= 0.05

            if not moved or not same_part or not close_enough(actual):
                if moved and after is not None and not close_enough(actual):
                    self.ipc_board_api.move_component(
                        reference=reference,
                        x=position.get("x", 0),
                        y=position.get("y", 0),
                        rotation=previous,
                    )
                return {
                    "success": False,
                    "error": "ROTATION_MISMATCH" if moved else "IPC_ERROR",
                    "message": (
                        f"Component {reference} is not at {target_angle:g} degrees "
                        "after the IPC transaction."
                    ),
                    "reference": reference,
                    "requestedRotation": target_angle,
                    "actualRotation": actual,
                }

            return {
                "success": True,
                "message": f"Rotated component {reference} to {target_angle:g}°",
                "reference": reference,
                "id": after.get("id"),
                "footprint": after.get("footprint"),
                "newRotation": actual,
                "requestedRotation": target_angle,
            }
        except Exception as e:
            logger.error(f"IPC rotate_component error: {e}")
            return {"success": False, "message": str(e)}

    def _ipc_get_component_properties(self, params):
        """IPC handler for get_component_properties - gets detailed component info"""
        try:
            reference = params.get("reference", params.get("componentId", ""))

            components = self.ipc_board_api.list_components()
            target = None
            for comp in components:
                if comp.get("reference") == reference:
                    target = comp
                    break

            if not target:
                return {"success": False, "message": f"Component {reference} not found"}

            return {"success": True, "component": target}
        except Exception as e:
            logger.error(f"IPC get_component_properties error: {e}")
            return {"success": False, "message": str(e)}

    # =========================================================================
    # Legacy IPC command handlers (explicit ipc_* commands)
    # =========================================================================

    def _handle_get_backend_info(self, params):
        """Get information about the current backend"""
        return {
            "success": True,
            "backend": "ipc" if self.use_ipc else "swig",
            "realtime_sync": self.use_ipc,
            "ipc_connected": (
                self.ipc_backend.is_connected() if self.ipc_backend else False
            ),
            "version": self.ipc_backend.get_version() if self.ipc_backend else "N/A",
            "message": (
                "Using IPC backend with real-time UI sync"
                if self.use_ipc
                else "Using SWIG backend (requires manual reload)"
            ),
        }

    def _handle_ipc_add_track(self, params):
        """Add a track using IPC backend (real-time)"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            result = self.ipc_board_api.add_track(
                start_x=params.get("startX", 0),
                start_y=params.get("startY", 0),
                end_x=params.get("endX", 0),
                end_y=params.get("endY", 0),
                width=params.get("width", 0.25),
                layer=params.get("layer", "F.Cu"),
                net_name=params.get("net"),
            )
            if not isinstance(result, dict):
                result = {
                    "success": False,
                    "message": "Track creation did not return a result object.",
                }
            accepted = bool(result.get("success"))
            requested = params.get("net")
            if accepted and isinstance(requested, str) and requested.strip():
                accepted = result.get("net") == requested.strip()
            return {
                "success": accepted,
                "message": result.get("message")
                or ("Track added (visible in KiCAD UI)" if accepted else "Failed to add track"),
                "id": result.get("id", ""),
                "net": result.get("net", ""),
                "error": result.get("error"),
                "realtime": accepted,
            }
        except Exception as e:
            logger.error(f"Error adding track via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_add_via(self, params):
        """Add a via using IPC backend (real-time)"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.add_via(
                x=params.get("x", 0),
                y=params.get("y", 0),
                diameter=params.get("diameter", 0.8),
                drill=params.get("drill", 0.4),
                net_name=params.get("net"),
                via_type=params.get("type", "through"),
            )
            return {
                "success": success,
                "message": (
                    "Via added (visible in KiCAD UI)"
                    if success
                    else "Failed to add via"
                ),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding via via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_add_text(self, params):
        """Add text using IPC backend (real-time)"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.add_text(
                text=params.get("text", ""),
                x=params.get("x", 0),
                y=params.get("y", 0),
                layer=params.get("layer", "F.SilkS"),
                size=params.get("size", 1.0),
                rotation=params.get("rotation", 0),
            )
            return {
                "success": success,
                "message": (
                    "Text added (visible in KiCAD UI)"
                    if success
                    else "Failed to add text"
                ),
                "realtime": True,
            }
        except Exception as e:
            logger.error(f"Error adding text via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_list_components(self, params):
        """List components using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            components = self.ipc_board_api.list_components()
            return {"success": True, "components": components, "count": len(components)}
        except Exception as e:
            logger.error(f"Error listing components via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_get_tracks(self, params):
        """Get tracks using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            tracks = self.ipc_board_api.get_tracks()
            return {"success": True, "tracks": tracks, "count": len(tracks)}
        except Exception as e:
            logger.error(f"Error getting tracks via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_get_vias(self, params):
        """Get vias using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            vias = self.ipc_board_api.get_vias()
            return {"success": True, "vias": vias, "count": len(vias)}
        except Exception as e:
            logger.error(f"Error getting vias via IPC: {e}")
            return {"success": False, "message": str(e)}

    def _handle_ipc_save_board(self, params):
        """Save board using IPC backend"""
        if not self.use_ipc or not self.ipc_board_api:
            return {"success": False, "message": "IPC backend not available"}

        try:
            success = self.ipc_board_api.save()
            return {
                "success": success,
                "message": "Board saved" if success else "Failed to save board",
            }
        except Exception as e:
            logger.error(f"Error saving board via IPC: {e}")
            return {"success": False, "message": str(e)}

    # JLCPCB API handlers

    def _handle_download_jlcpcb_database(self, params):
        """Download JLCPCB parts database from JLCSearch API"""
        try:
            force = params.get("force", False)

            # Check if database exists
            import os

            stats = self.jlcpcb_parts.get_database_stats()
            if stats["total_parts"] > 0 and not force:
                return {
                    "success": False,
                    "message": "Database already exists. Use force=true to re-download.",
                    "stats": stats,
                }

            logger.info("Downloading JLCPCB parts database from JLCSearch...")

            # Download parts from JLCSearch public API (no auth required)
            parts = self.jlcsearch_client.download_all_components(
                callback=lambda total, msg: logger.info(f"{msg}")
            )

            # Import into database
            logger.info(f"Importing {len(parts)} parts into database...")
            self.jlcpcb_parts.import_jlcsearch_parts(
                parts, progress_callback=lambda curr, total, msg: logger.info(msg)
            )

            # Get final stats
            stats = self.jlcpcb_parts.get_database_stats()

            # Calculate database size
            db_size_mb = os.path.getsize(self.jlcpcb_parts.db_path) / (1024 * 1024)

            return {
                "success": True,
                "total_parts": stats["total_parts"],
                "basic_parts": stats["basic_parts"],
                "extended_parts": stats["extended_parts"],
                "db_size_mb": round(db_size_mb, 2),
                "db_path": stats["db_path"],
            }

        except Exception as e:
            logger.error(f"Error downloading JLCPCB database: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to download database: {str(e)}",
            }

    def _handle_search_jlcpcb_parts(self, params):
        """Search JLCPCB parts database"""
        try:
            query = params.get("query")
            category = params.get("category")
            package = params.get("package")
            library_type = params.get("library_type", "All")
            manufacturer = params.get("manufacturer")
            in_stock = params.get("in_stock", True)
            limit = params.get("limit", 20)

            # Adjust library_type filter
            if library_type == "All":
                library_type = None

            parts = self.jlcpcb_parts.search_parts(
                query=query,
                category=category,
                package=package,
                library_type=library_type,
                manufacturer=manufacturer,
                in_stock=in_stock,
                limit=limit,
            )

            # Add price breaks and footprints to each part
            for part in parts:
                if part.get("price_json"):
                    try:
                        part["price_breaks"] = json.loads(part["price_json"])
                    except:
                        part["price_breaks"] = []

            return {"success": True, "parts": parts, "count": len(parts)}

        except Exception as e:
            logger.error(f"Error searching JLCPCB parts: {e}", exc_info=True)
            return {"success": False, "message": f"Search failed: {str(e)}"}

    def _handle_get_jlcpcb_part(self, params):
        """Get detailed information for a specific JLCPCB part"""
        try:
            lcsc_number = params.get("lcsc_number")
            if not lcsc_number:
                return {"success": False, "message": "Missing lcsc_number parameter"}

            part = self.jlcpcb_parts.get_part_info(lcsc_number)
            if not part:
                return {"success": False, "message": f"Part not found: {lcsc_number}"}

            # Get suggested KiCAD footprints
            footprints = self.jlcpcb_parts.map_package_to_footprint(
                part.get("package", "")
            )

            return {"success": True, "part": part, "footprints": footprints}

        except Exception as e:
            logger.error(f"Error getting JLCPCB part: {e}", exc_info=True)
            return {"success": False, "message": f"Failed to get part info: {str(e)}"}

    def _handle_get_jlcpcb_database_stats(self, params):
        """Get statistics about JLCPCB database"""
        try:
            stats = self.jlcpcb_parts.get_database_stats()
            return {"success": True, "stats": stats}

        except Exception as e:
            logger.error(f"Error getting database stats: {e}", exc_info=True)
            return {"success": False, "message": f"Failed to get stats: {str(e)}"}

    def _handle_suggest_jlcpcb_alternatives(self, params):
        """Suggest alternative JLCPCB parts"""
        try:
            lcsc_number = params.get("lcsc_number")
            limit = params.get("limit", 5)

            if not lcsc_number:
                return {"success": False, "message": "Missing lcsc_number parameter"}

            # Get original part for price comparison
            original_part = self.jlcpcb_parts.get_part_info(lcsc_number)
            reference_price = None
            if original_part and original_part.get("price_breaks"):
                try:
                    reference_price = float(
                        original_part["price_breaks"][0].get("price", 0)
                    )
                except:
                    pass

            alternatives = self.jlcpcb_parts.suggest_alternatives(lcsc_number, limit)

            # Add price breaks to alternatives
            for part in alternatives:
                if part.get("price_json"):
                    try:
                        part["price_breaks"] = json.loads(part["price_json"])
                    except:
                        part["price_breaks"] = []

            return {
                "success": True,
                "alternatives": alternatives,
                "reference_price": reference_price,
            }

        except Exception as e:
            logger.error(f"Error suggesting alternatives: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to suggest alternatives: {str(e)}",
            }

    def _handle_enrich_datasheets(self, params):
        """Enrich schematic Datasheet fields from LCSC numbers"""
        try:
            from pathlib import Path

            schematic_path = params.get("schematic_path")
            if not schematic_path:
                return {"success": False, "message": "Missing schematic_path parameter"}
            dry_run = params.get("dry_run", False)
            manager = DatasheetManager()
            return manager.enrich_schematic(Path(schematic_path), dry_run=dry_run)
        except Exception as e:
            logger.error(f"Error enriching datasheets: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to enrich datasheets: {str(e)}",
            }

    def _handle_get_datasheet_url(self, params):
        """Return LCSC datasheet and product URLs for a part number"""
        try:
            lcsc = params.get("lcsc", "")
            if not lcsc:
                return {"success": False, "message": "Missing lcsc parameter"}
            manager = DatasheetManager()
            datasheet_url = manager.get_datasheet_url(lcsc)
            product_url = manager.get_product_url(lcsc)
            if not datasheet_url:
                return {"success": False, "message": f"Invalid LCSC number: {lcsc}"}
            norm = manager._normalize_lcsc(lcsc)
            return {
                "success": True,
                "lcsc": norm,
                "datasheet_url": datasheet_url,
                "product_url": product_url,
            }
        except Exception as e:
            logger.error(f"Error getting datasheet URL: {e}", exc_info=True)
            return {
                "success": False,
                "message": f"Failed to get datasheet URL: {str(e)}",
            }


def main():
    """Main entry point"""
    logger.info("Starting KiCAD interface...")
    interface = KiCADInterface()

    try:
        logger.info("Processing commands from stdin...")
        # Process commands from stdin
        for line in sys.stdin:
            try:
                # Parse command
                logger.debug(f"Received input: {line.strip()}")
                command_data = json.loads(line)

                # Check if this is JSON-RPC 2.0 format
                if "jsonrpc" in command_data and command_data["jsonrpc"] == "2.0":
                    logger.info("Detected JSON-RPC 2.0 format message")
                    method = command_data.get("method")
                    params = command_data.get("params", {})
                    request_id = command_data.get("id")

                    # Handle MCP protocol methods
                    if method == "initialize":
                        logger.info("Handling MCP initialize")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "protocolVersion": "2025-06-18",
                                "capabilities": {
                                    "tools": {"listChanged": True},
                                    "resources": {
                                        "subscribe": False,
                                        "listChanged": True,
                                    },
                                },
                                "serverInfo": {
                                    "name": "kicad-mcp-server",
                                    "title": "KiCAD PCB Design Assistant",
                                    "version": "2.1.0-alpha",
                                },
                                "instructions": "AI-assisted PCB design with KiCAD. Use tools to create projects, design boards, place components, route traces, and export manufacturing files.",
                            },
                        }
                    elif method == "tools/list":
                        logger.info("Handling MCP tools/list")
                        # Return list of available tools with proper schemas
                        tools = []
                        for cmd_name in interface.command_routes.keys():
                            # Get schema from TOOL_SCHEMAS if available
                            if cmd_name in TOOL_SCHEMAS:
                                tool_def = TOOL_SCHEMAS[cmd_name].copy()
                                tools.append(tool_def)
                            else:
                                # Fallback for tools without schemas
                                logger.warning(
                                    f"No schema defined for tool: {cmd_name}"
                                )
                                tools.append(
                                    {
                                        "name": cmd_name,
                                        "description": f"KiCAD command: {cmd_name}",
                                        "inputSchema": {
                                            "type": "object",
                                            "properties": {},
                                        },
                                    }
                                )

                        logger.info(f"Returning {len(tools)} tools")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"tools": tools},
                        }
                    elif method == "tools/call":
                        logger.info("Handling MCP tools/call")
                        tool_name = params.get("name")
                        tool_params = params.get("arguments", {})

                        # Execute the command
                        result = interface.handle_command(tool_name, tool_params)

                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [
                                    {"type": "text", "text": json.dumps(result)}
                                ]
                            },
                        }
                    elif method == "resources/list":
                        logger.info("Handling MCP resources/list")
                        # Return list of available resources
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {"resources": RESOURCE_DEFINITIONS},
                        }
                    elif method == "resources/read":
                        logger.info("Handling MCP resources/read")
                        resource_uri = params.get("uri")

                        if not resource_uri:
                            response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "error": {
                                    "code": -32602,
                                    "message": "Missing required parameter: uri",
                                },
                            }
                        else:
                            # Read the resource
                            resource_data = handle_resource_read(
                                resource_uri, interface
                            )

                            response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": resource_data,
                            }
                    else:
                        logger.error(f"Unknown JSON-RPC method: {method}")
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32601,
                                "message": f"Method not found: {method}",
                            },
                        }
                else:
                    # Handle legacy custom format
                    logger.info("Detected custom format message")
                    command = command_data.get("command")
                    params = command_data.get("params", {})

                    if not command:
                        logger.error("Missing command field")
                        response = {
                            "success": False,
                            "message": "Missing command",
                            "errorDetails": "The command field is required",
                        }
                    else:
                        # Handle command
                        response = interface.handle_command(command, params)

                # Send response
                logger.debug(f"Sending response: {response}")
                print(json.dumps(response))
                sys.stdout.flush()

            except json.JSONDecodeError as e:
                logger.error(f"Invalid JSON input: {str(e)}")
                response = {
                    "success": False,
                    "message": "Invalid JSON input",
                    "errorDetails": str(e),
                }
                print(json.dumps(response))
                sys.stdout.flush()

    except KeyboardInterrupt:
        logger.info("KiCAD interface stopped")
        sys.exit(0)

    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}\n{traceback.format_exc()}")
        sys.exit(1)


if __name__ == "__main__":
    main()
