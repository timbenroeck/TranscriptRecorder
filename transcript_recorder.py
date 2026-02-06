import re
import asyncio
import json
import logging
import psutil
import aiofiles
import functools
import collections
from typing import Any, Dict, List, Optional,TypeVar, Callable

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set, Union

# macOS specific accessibility functions
try:
    from ApplicationServices import (
        AXUIElementCreateApplication,
        AXUIElementCopyAttributeValue,
        kAXChildrenAttribute,
        kAXRowsAttribute,
        kAXTitleAttribute,
        kAXValueAttribute,
        kAXRoleAttribute,
        kAXSubroleAttribute,
        kAXDescriptionAttribute,
        AXIsProcessTrusted,
        # kAXErrorSuccess is 0, can be checked directly or defined
    )
    # Define kAXErrorSuccess if not directly available or for clarity
    kAXErrorSuccess = 0 # ax_error.h defines this as 0
except ImportError:
    # Allow an error or a stub for non-macOS development if needed,
    # but the class is fundamentally macOS-dependent.
    print("Warning: ApplicationServices not found. This class is macOS-specific.")
    AXUIElementCreateApplication = None # type: ignore
    AXUIElementCopyAttributeValue = None # type: ignore
    kAXChildrenAttribute = "" # type: ignore
    kAXTitleAttribute = "" # type: ignore
    kAXValueAttribute = "" # type: ignore
    kAXRoleAttribute = "" # type: ignore
    kAXSubroleAttribute = "" # type: ignore
    kAXDescriptionAttribute = "" # type: ignore
    AXIsProcessTrusted = lambda: False # type: ignore
    kAXErrorSuccess = 1 # type: ignore

AX_ATTRIBUTE_STRING_TO_OBJECT = {
        "kAXRoleAttribute":        kAXRoleAttribute,
        "kAXSubroleAttribute":     kAXSubroleAttribute,
        "kAXTitleAttribute":       kAXTitleAttribute,
        "kAXValueAttribute":       kAXValueAttribute,
        "kAXDescriptionAttribute": kAXDescriptionAttribute,
    }

CONFIG_KEY_TO_AX_ATTRIBUTE_MAP = {
    "role": kAXRoleAttribute,
    "subrole": kAXSubroleAttribute,
    "title": kAXTitleAttribute,
    "title_contains": kAXTitleAttribute,
    "title_matches_one_of": kAXTitleAttribute,
    "description": kAXDescriptionAttribute,
    "description_contains": kAXDescriptionAttribute,
}

# Helper for running blocking ApplicationServices calls in async context
T = TypeVar("T")
async def _run_blocking_io(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Runs a blocking function in a thread, returning its result."""
    loop = asyncio.get_running_loop()
    pfunc = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(None, pfunc)

class TranscriptRecorder:
    """
    Records transcripts by finding a specified UI element in an application,
    serializing its accessibility tree, and managing snapshots of this data.
    """

    def __init__(self, app_config: Dict[str, Any], logger: Optional[logging.Logger] = None):
        """
        Initializes the TranscriptRecorder.

        Args:
            app_config: An application-specific configuration dictionary.
                        Must include 'base_transcript_directory' (str),
                        and typically 'rules_to_find_transcript_table' (list),
                        'traversal_roles_to_skip' (list),
                        'serialization_text_element_roles' (list).
                        May include 'name' (str) for app identification in logs/filenames,
                        'command_paths' (list) or 'app_names' (list) for process lookup.
            logger: Optional custom logger instance. If None, a new logger
                    for this module is created.
        """
        self.app_config = app_config
        # text_element_roles = self.app_config.get("serialization_text_element_roles", [])
        # for role, attr_name in list(text_element_roles.items()):
        #     text_element_roles[role] = AX_ATTRIBUTE_STRING_TO_OBJECT.get(attr_name)

        self._transcript_element: Optional[Any] = None  # Stores the found AXUIElementRef
        self._transcript_table_export_row: Optional[Any] = None
        self._snapshots_info: List[Dict[str, Union[str, int]]] = []

        _base_dir_str = self.app_config.get("base_transcript_directory")
        if not _base_dir_str or not isinstance(_base_dir_str, str):
            raise ValueError("app_config must contain 'base_transcript_directory' as a string path.")
        self._transcript_base_dir = Path(_base_dir_str).expanduser()

        if logger:
            self.logger = logger
        else:
            self.logger = logging.getLogger(__name__)
            if not self.logger.hasHandlers():
                self.logger.addHandler(logging.NullHandler())

        self.app_identifier = self.app_config.get("name", "UnknownApp")


    @property
    def transcript_base_dir(self) -> Path:
        """The base directory where transcripts and snapshots for this app are stored."""
        return self._transcript_base_dir

    @property
    def transcript_element(self) -> Optional[Any]:
        """The currently found transcript AXUIElement. None if not found or not searched yet."""
        return self._transcript_element

    @property
    def transcript_table_export_row(self) -> Optional[Any]:
        """The currently found transcript table's last exported row"""
        return self._transcript_table_export_row

    @property
    def snapshots(self) -> List[Dict[str, Union[str, int]]]:
        """A list of dictionaries, each containing info about an exported snapshot."""
        return list(self._snapshots_info) # Return a copy

    async def _get_ax_attribute(self, element: Any, attr_name: str) -> Optional[Any]:
        """Safely retrieves an accessibility attribute value asynchronously."""
        if not element or not attr_name or AXUIElementCopyAttributeValue is None:
            return None
        # AXUIElementCopyAttributeValue is blocking
        result, value = await _run_blocking_io(AXUIElementCopyAttributeValue, element, attr_name, None)
        return value if result == kAXErrorSuccess else None

    async def _get_element_descriptor(self, ax_element: Any) -> str:
        """Provides a descriptive string for an AXUIElementRef."""
        if not ax_element:
            return "Invalid Element"
        role = await self._get_ax_attribute(ax_element, kAXRoleAttribute) or "UnknownRole"
        title = await self._get_ax_attribute(ax_element, kAXTitleAttribute)
        description = await self._get_ax_attribute(ax_element, kAXDescriptionAttribute)

        identifier = ""
        if title and isinstance(title, str) and title.strip():
            identifier = f"\"{title.strip()}\""
        elif description and isinstance(description, str) and description.strip():
            identifier = f"\"{description.strip()}\""

        if identifier:
            return f'{role} "{identifier}"'
        return role

    async def _get_running_app_pids(self) -> List[int]:
        """Finds PIDs of the target application based on app_config."""
        command_paths = self.app_config.get("command_paths", [])
        app_names = self.app_config.get("app_names", [])

        if isinstance(command_paths, str): command_paths = [command_paths]
        if isinstance(app_names, str): app_names = [app_names]
        lower_app_names = [name.lower() for name in app_names]

        def find_pids_sync() -> List[int]:
            _pids: Set[int] = set()
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cmdline']):
                try:
                    proc_info = proc.info
                    pid, exe_path, name, cmdline = proc_info['pid'], proc_info['exe'], proc_info['name'], proc_info['cmdline']

                    # Normalize for comparison
                    current_name_lower = name.lower() if name else ""
                    current_exe_path = str(Path(exe_path).resolve()) if exe_path else "" # Resolve symlinks

                    # Check against command_paths (resolved)
                    if command_paths and current_exe_path:
                        for cmd_path_str in command_paths:
                            if str(Path(cmd_path_str).resolve()) == current_exe_path:
                                self.logger.debug(f"PID {pid}: Matched by command_path '{cmd_path_str}'.")
                                _pids.add(pid)
                                continue # Next proc

                    # Check against app_names (process name)
                    if app_names and current_name_lower:
                        for lower_app_name in lower_app_names:
                            if lower_app_name in current_name_lower:
                                if cmdline:
                                    self.logger.debug(f"PID {pid}: Matched by app_name '{lower_app_name}' in process name '{current_name_lower} with cmdline '{cmdline}'.")
                                else:
                                    self.logger.debug(f"PID {pid}: Matched by app_name '{lower_app_name}' in process name '{current_name_lower}.")

                                _pids.add(pid)
                                continue # Next proc

                    # Fallback: Check app_names within the command line arguments
                    if app_names and cmdline:
                        full_cmd_line_lower = ' '.join(cmdline).lower()
                        for app_name_original, lower_app_name in zip(app_names, lower_app_names):
                            if lower_app_name in full_cmd_line_lower:
                                self.logger.debug(f"PID {pid}: Matched by app_name '{app_name_original}' with cmdline '{cmdline}'.")
                                _pids.add(pid)
                                break # Found by one of the app_names in cmdline for this proc
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
                except Exception as e:
                    self.logger.warning(f"Error inspecting process {getattr(proc, 'pid', 'N/A')}: {e}")
            return list(_pids)

        found_pids_list = await _run_blocking_io(find_pids_sync)
        if not found_pids_list:
            self.logger.debug(f"No running processes found for '{self.app_identifier}'.")
        else:
            self.logger.debug(f"Found {len(found_pids_list)} candidate process(es) for '{self.app_identifier}': {found_pids_list}")
        return found_pids_list

    async def _check_ax_match(self, element: Any, rule_criteria: Dict[str, Any]) -> bool:
        """Checks if an element matches all criteria in rule_criteria."""
        if not element: return False
        for key, expected_value in rule_criteria.items():
            if key in ["search_scope", "index"]: continue # Handled by caller

            actual_value = None
            attribute = CONFIG_KEY_TO_AX_ATTRIBUTE_MAP.get(key)

            if attribute:
                actual_value = await self._get_ax_attribute(element, attribute)

            if key in ["role", "subrole", "title", "description"]:
                if actual_value != expected_value: return False
            elif key == "title_contains":
                if not (actual_value and isinstance(actual_value, str) and expected_value.lower() in actual_value.lower()): return False
            elif key == "title_matches_one_of": # Ensure expected_value is a list
                if not (actual_value and isinstance(actual_value, str) and isinstance(expected_value, list) and \
                        any(opt.lower() in actual_value.lower() for opt in expected_value)): return False
            elif key == "description_contains":
                # Re-fetch or use actual_value if key was "description"
                desc_val = actual_value if key == "description" else await self._get_ax_attribute(element, kAXDescriptionAttribute)
                if not (desc_val and isinstance(desc_val, str) and expected_value.lower() in desc_val.lower()): return False
        return True

    async def _search_descendants_for_matches(self, start_node: Any, criteria_rule: Dict[str, Any], levels_to_search: int, roles_to_skip: Optional[List[str]] = None) -> List[Any]:
        """Performs a BFS to find descendants matching criteria_rule."""
        matches: List[Any] = []
        if not start_node: return matches

        effective_levels = levels_to_search if levels_to_search > 0 else 50 # Default search depth
        queue = collections.deque([(start_node, 0)]) # (element, depth)
        # Visited set is tricky with AXUIElementRefs if they aren't consistently hashable/comparable across calls.
        # For deep trees, this could be an issue. Assuming they are reference-stable during a single search.
        # If not, could lead to re-processing or cycles if the hierarchy is complex.
        # The original code used a set, suggesting it worked.
        visited_elements: Set[Any] = {start_node}

        while queue:
            current_ax_element, current_depth = queue.popleft()

            if current_depth > effective_levels: continue

            if await self._check_ax_match(current_ax_element, criteria_rule):
                matches.append(current_ax_element)

            if current_depth < effective_levels: # Only get children if we can go deeper
                # Check if we should skip traversal for this element based on its role
                role = await self._get_ax_attribute(current_ax_element, kAXRoleAttribute)
                if role and roles_to_skip and role in roles_to_skip and current_depth > 0:
                    continue  # Don't descend into children of this element

                children = await self._get_ax_attribute(current_ax_element, kAXChildrenAttribute)
                if children:
                    for child in children:
                        if child not in visited_elements: # Relies on AXUIElementRef hashability
                             visited_elements.add(child)
                             queue.append((child, current_depth + 1))
        return matches

    async def find_transcript_element(self) -> bool:
        """
        Attempts to find the transcript element based on rules in app_config.
        Sets self.transcript_element if found.

        Returns:
            True if the element is found, False otherwise.
        """
        self.logger.info(f"Attempting to find transcript element for '{self.app_identifier}'.")
        if not await _run_blocking_io(AXIsProcessTrusted):
            self.logger.error("Accessibility permissions are not enabled. Cannot find transcript element.")
            self._transcript_element = None
            return False

        pids = await self._get_running_app_pids()
        if not pids:
            self._transcript_element = None
            return False # App not running

        rules_path_options = self.app_config.get("rules_to_find_transcript_table", [])
        if not rules_path_options:
            self.logger.warning(f"No 'rules_to_find_transcript_table' in app_config for '{self.app_identifier}'.")
            self._transcript_element = None
            return False

        roles_to_skip = self.app_config.get("traversal_roles_to_skip", [])

        for pid in pids:
            self.logger.debug(f"Checking PID: {pid} for '{self.app_identifier}'.")
            app_ref = await _run_blocking_io(AXUIElementCreateApplication, pid)
            if not app_ref:
                self.logger.warning(f"Could not create AXUIElement for PID: {pid}.")
                continue

            self.logger.debug(f"Created AXUIElement for PID {pid}: {await self._get_element_descriptor(app_ref)}")

            for path_idx, path_option in enumerate(rules_path_options):
                path_name = path_option.get("path_name", f"PathOption-{path_idx+1}")
                self.logger.debug(f"Trying rule path '{path_name}' for PID {pid}.")
                current_elements_to_search = [app_ref] # Start search from the app root

                for step_idx, step_rule in enumerate(path_option.get("steps", [])):
                    self.logger.debug(f"Path '{path_name}', Step {step_idx+1}: {step_rule}")
                    elements_found_this_step: List[Any] = []
                    search_scope = step_rule.get("search_scope", {})
                    levels_deep = search_scope.get("levels_deep", 1) # Default depth
                    index_to_select = step_rule.get("index") # Optional index
                    criteria_for_match = {k: v for k, v in step_rule.items() if k not in ["search_scope", "index"]}

                    for parent_element in current_elements_to_search:
                        discovered_matches = await self._search_descendants_for_matches(parent_element, criteria_for_match, levels_deep, roles_to_skip)
                        elements_found_this_step.extend(discovered_matches)

                    if not elements_found_this_step:
                        self.logger.debug(f"Path '{path_name}', Step {step_idx+1}: No elements found. Path failed.")
                        current_elements_to_search = [] # Empty list to break outer loop for this path_option
                        break # Move to next path_option

                    # Apply index if specified
                    if index_to_select is not None:
                        if 0 <= index_to_select < len(elements_found_this_step):
                            self.logger.debug(f"Path '{path_name}', Step {step_idx+1}: Applying index {index_to_select} from {len(elements_found_this_step)} matches.")
                            current_elements_to_search = [elements_found_this_step[index_to_select]]
                        else:
                            self.logger.warning(f"Path '{path_name}', Step {step_idx+1}: Index {index_to_select} out of bounds for {len(elements_found_this_step)} matches. Path failed.")
                            current_elements_to_search = []
                            break # Move to next path_option
                    else:
                        # No index, continue with all found elements for the next step
                        current_elements_to_search = elements_found_this_step

                if current_elements_to_search: # If loop completed and elements remain
                    final_target = current_elements_to_search[0] # Take the first one if multiple survived all steps
                    self.logger.debug(f"SUCCESS: Path '{path_name}' found target element for PID {pid}: {await self._get_element_descriptor(final_target)}")
                    self._transcript_element = final_target
                    return True
            self.logger.debug(f"All rule paths exhausted for PID {pid}.")

        self.logger.warning(f"Transcript element not found after checking all PIDs and rule paths for '{self.app_identifier}'.")
        self._transcript_element = None
        return False

    async def _serialize_recursive(self, element: Any, current_depth: int = 0, max_depth: int = 10,
                                   roles_to_skip: List[str] = []) -> Optional[Dict[str, Any]]:
        """Recursively serializes an AX element, counting text roles."""
        if not element: return None, 0
        if current_depth > max_depth:
            return {"_info_": f"<Max serialization depth {max_depth} reached>"}, 0

        data: Dict[str, Any] = {"_depth_": current_depth} # Using _depth_ to avoid potential clashes

        attrs_to_get = {
            "role": kAXRoleAttribute, "subrole": kAXSubroleAttribute,
            "title": kAXTitleAttribute, "value": kAXValueAttribute,
            "description": kAXDescriptionAttribute
        }
        current_role: Optional[str] = None

        for key, attr_const in attrs_to_get.items():
            val = await self._get_ax_attribute(element, attr_const)
            if val is not None:
                if key == "role": current_role = str(val) # Ensure role is string
                if isinstance(val, str) and val.strip(): data[key] = val
                elif isinstance(val, (int, float, bool)): data[key] = val


        if current_role:
            if current_role in roles_to_skip and current_depth > 0: # Skip if in skip list (and not root)
                return None

        if current_depth < max_depth:
            children = await self._get_ax_attribute(element, kAXChildrenAttribute)
            if children:
                child_data_list: List[Dict[str, Any]] = []
                for child_ax in children:
                    s_child_data = await self._serialize_recursive(
                        child_ax, current_depth + 1, max_depth, roles_to_skip
                    )
                    if s_child_data: # Only add if child serialization returned data
                        child_data_list.append(s_child_data)
                if child_data_list:
                    data["children"] = child_data_list

        return (data if len(data) > 1 else None)

    async def _collect_text_values(
        self,
        start_node: Any,
        levels_to_search: int,
        roles_to_include: Dict[str, str],
        roles_to_skip: Optional[List[str]] = None,
        traversal_mode: str = "bfs",
        exclude_pattern: Optional[str] = None,
        incremental_export: Optional[bool] = False
    ) -> List[str]:
        """
        Walk the AX tree from start_node up to levels_to_search deep,
        collecting text out of whichever attribute you specify per role.
        Optionally strips out any substring matching exclude_pattern.
        """
        values: List[str] = []

        if not start_node:
            return values

        effective_levels = levels_to_search if levels_to_search > 0 else 50

        prev_row_count = 0
        if self._transcript_table_export_row and isinstance(self._transcript_table_export_row , int):
            prev_row_count = self._transcript_table_export_row

        exclude_re = None
        if exclude_pattern:
            try:
                exclude_re = re.compile(exclude_pattern)
            except Exception as e:
                self.logger.error("Failed to parse the exclude_pattern. Error: %s", e)

        async def process_node(node: Any):
            role = await self._get_ax_attribute(node, kAXRoleAttribute)
            if role in roles_to_include:
                text_attr = roles_to_include[role]
                raw = await self._get_ax_attribute(node, text_attr)
                if isinstance(raw, str) and raw.strip():
                    text = raw.strip()
                    if exclude_re:
                        text = exclude_re.sub("", text).strip()
                    if text:
                        values.append(text)

        if traversal_mode.lower() == "dfs":
            self.logger.debug(f"traversal mode is dfs")
            async def dfs(node: Any, depth: int):
                if depth > effective_levels:
                    return
                await process_node(node)

                role = await self._get_ax_attribute(node, kAXRoleAttribute)
                if role and roles_to_skip and role in roles_to_skip and depth > 0:
                    return

                children = await self._get_ax_attribute(node, kAXChildrenAttribute) or []
                for child in children:
                    await dfs(child, depth + 1)

            await dfs(start_node, 0)

        elif traversal_mode.lower() == "bfs":
            self.logger.debug(f"traversal mode is bfs")
            queue = collections.deque([(start_node, 0)])
            while queue:
                node, depth = queue.popleft()
                if depth > effective_levels:
                    continue
                await process_node(node)

                if depth < effective_levels:
                    role = await self._get_ax_attribute(node, kAXRoleAttribute)
                    if role and roles_to_skip and role in roles_to_skip and depth > 0:
                        continue

                    children = await self._get_ax_attribute(node, kAXChildrenAttribute) or []
                    children_count = len(children)

                    if incremental_export and depth == 0 and role == "AXTable":
                        try:
                            if children_count > 0:
                                overlap = 10 #needs greater than the meaningful overlap in the merge function
                                first_new_index = max(0, prev_row_count - overlap)
                                if first_new_index <= children_count:
                                    for idx in range(first_new_index, children_count):
                                        row = children[idx]
                                        queue.append((row, depth + 1))
                                self._transcript_table_export_row = children_count
                                self.logger.debug(f"Setting export row to {children_count}")
                        except Exception as e:
                            self.logger.error("Failed to retrieve AXRows from transcript: %s", e)
                    else:
                        for child in children:
                            queue.append((child, depth + 1))
        else:
            raise ValueError(f"Unsupported traversal_mode: {traversal_mode}")

        return values

    async def export_transcript_text(self, filename: Optional[str] = None) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Find (if needed) the transcript element and then
        write out each matching-role.value on its own line in a .txt file.

        Args:
            filename: optional override (default: transcript_<appname>_YYYYMMDD_HHMMSS.txt)

        Returns:
            (success, path_to_txt_or_None, count_of_lines_or_None)
        """
        # ensure we have a root to walk
        if not self._transcript_element:
            ok = await self.find_transcript_element()
            if not ok:
                self.logger.error("Cannot export text: no transcript element found.")
                return False, None, None

        serialization_export_depth = self.app_config.get("serialization_export_depth", 15)
        serialization_save_json = self.app_config.get("serialization_save_json", False)
        text_element_roles = self.app_config.get("serialization_text_element_roles", {"AXTextArea": "AXValue","AXStaticText": "AXValue"})
        roles_to_skip = self.app_config.get("traversal_roles_to_skip", [])
        traversal_mode = self.app_config.get("traversal_mode", 'bfs')
        incremental_export = self.app_config.get("incremental_export", False)
        exclude_pattern = self.app_config.get("exclude_pattern", None)

        # 1) collect all the lines
        lines = await self._collect_text_values(self._transcript_element, levels_to_search=serialization_export_depth, roles_to_include=text_element_roles, roles_to_skip=roles_to_skip, traversal_mode=traversal_mode, exclude_pattern=exclude_pattern, incremental_export=incremental_export )

        if not lines:
            self.logger.debug("No text values found for roles %s", text_element_roles)
            ok = await self.find_transcript_element()
            if not ok:
                self.logger.error("Cannot export text: no transcript element found.")
            return False, None, None

        # 2) build output path
        timestamp = datetime.now()
        slug = "".join(c if c.isalnum() else "_" for c in self.app_identifier).lower()
        fname = filename or f"transcript_{slug}_{timestamp.strftime('%Y%m%d_%H%M%S')}"

        out_dir = self.transcript_base_dir
        full_path_text = out_dir / f"{fname}.txt"

        # 3) ensure directory exists
        try:
            await _run_blocking_io(out_dir.mkdir, parents=True, exist_ok=True)
        except Exception as e:
            self.logger.error("Failed to create directory %s: %s", out_dir, e)
            return False, None, None

        # 4) write it out
        text_count = 0
        try:
            async with aiofiles.open(full_path_text, "w", encoding="utf-8") as f:
                for line in lines:
                    await f.write(line + "\n")
                    text_count += 1
            self.logger.info("Transcript text exported to %s", full_path_text)
            snapshot_info: Dict[str, Union[str, int]] = {
                "file_path": str(full_path_text),
                "timestamp": timestamp.isoformat(), # Storing full ISO timestamp
                "text_element_count": text_count
            }
            self._snapshots_info.append(snapshot_info)

            if serialization_save_json:
                try:
                    self.logger.debug("Starting serialization to JSON")
                    out_dir_json = Path(f"{out_dir}/json").expanduser()
                    full_path_json = f"{out_dir_json}/{fname}.json"

                    await _run_blocking_io(out_dir_json.mkdir, parents=True, exist_ok=True)

                    sdata = await self._serialize_recursive(self._transcript_element, current_depth=0, max_depth=serialization_export_depth, roles_to_skip=roles_to_skip)
                    async with aiofiles.open(full_path_json, 'w', encoding='utf-8') as f:
                        await f.write(json.dumps(sdata, indent=2))
                except IOError as e:
                    self.logger.error(f"IOError writing json file to {full_path_json}: {e}")
                except Exception as e: # Catch other potential errors
                    self.logger.error(f"Unexpected error during snapshot export to {full_path_json}: {e}")

            return True, str(full_path_text), text_count

        except Exception as e:
            self.logger.error("Failed to write transcript text file: %s", e)
            return False, None, None

    async def export_snapshots_index(self, filename: str = "snapshots_index.json") -> Tuple[bool, Optional[str]]:
        """
        Exports the list of collected snapshot information to a JSON file
        in the transcript_base_dir.

        Args:
            filename: The name for the index file.

        Returns:
            A tuple: (success_bool, file_path_str_or_None).
        """
        if not self._snapshots_info:
            self.logger.warning("No snapshots recorded; index will be empty or not written.")
            # Decide if an empty index file should be written. Let's write it.

        index_file_path = self.transcript_base_dir / filename
        try:
            # Ensure base directory exists (it should if snapshots were made, but good practice)
            await _run_blocking_io(self.transcript_base_dir.mkdir, parents=True, exist_ok=True)

            async with aiofiles.open(index_file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(self._snapshots_info, indent=2))
            self.logger.info(f"Snapshots index exported to: {index_file_path}")
            return True, str(index_file_path)
        except IOError as e:
            self.logger.error(f"IOError writing snapshots index to {index_file_path}: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error during index export to {index_file_path}: {e}")

        return False, None

    def clear_snapshots_list(self):
        """Clears the internal list of snapshot information."""
        self._snapshots_info = []
        self.logger.debug("Internal snapshots list has been cleared.")

    async def merge_snapshots(self, output_filename: str = "transcript_merged.txt", 
                              min_match_length: int = 5) -> Tuple[bool, Optional[str], int]:
        """
        Merges all recorded snapshots into a single transcript file.
        
        Uses intelligent overlap detection to avoid duplicating content that
        appears in multiple consecutive snapshots.
        
        Args:
            output_filename: Name for the merged output file
            min_match_length: Minimum matching lines to consider as overlap
            
        Returns:
            Tuple of (success, output_path_or_none, total_overlap_count)
        """
        import difflib
        
        if not self._snapshots_info:
            self.logger.warning("No snapshots to merge")
            return False, None, 0
            
        if len(self._snapshots_info) == 1:
            # Only one snapshot, just return its path
            return True, self._snapshots_info[0]["file_path"], 0
        
        output_path = self.transcript_base_dir / output_filename
        total_overlap = 0
        
        try:
            # Start with first snapshot
            first_path = self._snapshots_info[0]["file_path"]
            async with aiofiles.open(first_path, 'r', encoding='utf-8') as f:
                merged_lines = (await f.read()).splitlines(keepends=True)
            
            # Merge each subsequent snapshot
            for i, snapshot_info in enumerate(self._snapshots_info[1:], start=1):
                snapshot_path = snapshot_info["file_path"]
                
                async with aiofiles.open(snapshot_path, 'r', encoding='utf-8') as f:
                    new_lines = (await f.read()).splitlines(keepends=True)
                
                # Use difflib for intelligent merging
                matcher = difflib.SequenceMatcher(None, merged_lines, new_lines)
                opcodes = matcher.get_opcodes()
                
                found_meaningful_overlap = any(
                    tag == 'equal' and (i2 - i1) >= min_match_length
                    for tag, i1, i2, j1, j2 in opcodes
                )
                
                if not found_meaningful_overlap:
                    # No overlap, append
                    merged_lines.extend(new_lines)
                else:
                    # Intelligent merge
                    result_lines = []
                    for tag, i1, i2, j1, j2 in opcodes:
                        block_length = (i2 - i1)
                        if tag == 'equal' and block_length >= min_match_length:
                            total_overlap += block_length
                            result_lines.extend(new_lines[j1:j2])
                        elif tag == 'equal':
                            result_lines.extend(new_lines[j1:j2])
                        elif tag in ('replace', 'insert'):
                            result_lines.extend(new_lines[j1:j2])
                        elif tag == 'delete':
                            result_lines.extend(merged_lines[i1:i2])
                    merged_lines = result_lines
            
            # Write merged output
            async with aiofiles.open(output_path, 'w', encoding='utf-8') as f:
                await f.writelines(merged_lines)
            
            self.logger.info(f"Merged {len(self._snapshots_info)} snapshots to {output_path}")
            return True, str(output_path), total_overlap
            
        except Exception as e:
            self.logger.error(f"Error merging snapshots: {e}", exc_info=True)
            return False, None, 0
