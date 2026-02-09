"""
Background QThread workers for recording, tool execution, and update checking.
"""
import json
import os
import signal
import subprocess
import threading
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Optional

from PyQt6.QtCore import QThread, pyqtSignal

from gui.constants import (
    APP_NAME, APP_VERSION, logger,
)
from version import GITHUB_OWNER, GITHUB_REPO


class RecordingWorker(QThread):
    """Background countdown timer that signals the main thread to capture.
    
    All capture and merge logic lives on the main thread so that manual
    and auto captures share a single code-path and a single snapshot
    counter.  This worker is only responsible for the timed countdown.
    """
    
    capture_requested = pyqtSignal()   # Emitted when the countdown expires
    countdown_tick = pyqtSignal(int)   # Seconds remaining until next capture
    
    def __init__(self, interval_seconds: int, parent=None):
        super().__init__(parent)
        self.interval_seconds = interval_seconds
        self._is_running = True
        
    def run(self):
        """Countdown loop — emits capture_requested each time the timer expires."""
        logger.info(f"Auto capture timer started (interval={self.interval_seconds}s)")
        
        try:
            while self._is_running:
                # Countdown
                for i in range(self.interval_seconds, 0, -1):
                    if not self._is_running:
                        break
                    self.countdown_tick.emit(i)
                    self.msleep(1000)
                
                if not self._is_running:
                    break
                
                # Request a capture on the main thread
                self.countdown_tick.emit(0)
                self.capture_requested.emit()
                
                # Brief pause so the main thread can begin the capture
                # before the next countdown restarts
                self.msleep(500)
        finally:
            logger.info("Auto capture timer stopped")
    
    def stop(self):
        """Signal the timer to stop."""
        logger.debug("Auto capture timer: stop requested")
        self._is_running = False


class ToolRunnerWorker(QThread):
    """Background worker for executing tool scripts without blocking the UI.
    
    Uses ``subprocess.Popen`` so the process can be cancelled mid-run via
    ``cancel()``.  The child is spawned in its own session/process-group so
    that ``cancel()`` can tear down the entire tree (bash + cortex, etc.).
    """
    
    output_ready = pyqtSignal(str, str, int)  # stdout, stderr, exit_code
    
    def __init__(self, command: List[str], cwd: str = None, parent=None):
        super().__init__(parent)
        self.command = command
        self.cwd = cwd
        self._process: Optional[subprocess.Popen] = None
        self._cancelled = False
    
    @staticmethod
    def _get_user_env() -> dict:
        """Return an environment dict with the user's full login-shell PATH.
        
        GUI applications on macOS inherit a minimal system PATH that often
        lacks user-specific directories (e.g. ``~/.local/bin``).  This method
        spawns a one-shot login shell to capture the real PATH and merges it
        into the current process environment.
        """
        env = os.environ.copy()
        try:
            shell = os.environ.get("SHELL", "/bin/zsh")
            logger.debug(f"ToolRunnerWorker._get_user_env: resolving PATH via login shell: {shell}")
            result = subprocess.run(
                [shell, "-l", "-c", "echo $PATH"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                env["PATH"] = result.stdout.strip()
                logger.debug(f"ToolRunnerWorker._get_user_env: resolved PATH ({len(env['PATH'])} chars)")
            else:
                logger.warning(f"ToolRunnerWorker._get_user_env: login shell returned "
                               f"rc={result.returncode}, stdout empty={not result.stdout.strip()}")
        except subprocess.TimeoutExpired:
            logger.warning("ToolRunnerWorker._get_user_env: login shell timed out after 5s")
        except Exception as exc:
            logger.warning(f"ToolRunnerWorker._get_user_env: failed to resolve user PATH: {exc}")
        return env
    
    def run(self):
        logger.debug(f"ToolRunnerWorker.run: starting — command={self.command}, cwd={self.cwd}")
        try:
            env = self._get_user_env()
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.DEVNULL,   # close stdin so child exits cleanly
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.cwd,
                env=env,
                start_new_session=True,  # own process group for clean cancel
            )
            pid = self._process.pid
            logger.info(f"ToolRunnerWorker.run: spawned pid={pid}")
            
            stdout, stderr = self._process.communicate()
            rc = self._process.returncode
            logger.debug(f"ToolRunnerWorker.run: communicate() returned — "
                         f"pid={pid}, rc={rc}, cancelled={self._cancelled}, "
                         f"stdout_len={len(stdout or '')}, stderr_len={len(stderr or '')}")
            
            if self._cancelled:
                self.output_ready.emit(stdout or "", "Cancelled by user.", -2)
            else:
                self.output_ready.emit(stdout or "", stderr or "", rc)
        except Exception as e:
            logger.error(f"ToolRunnerWorker.run: exception — {type(e).__name__}: {e}", exc_info=True)
            if self._cancelled:
                self.output_ready.emit("", "Cancelled by user.", -2)
            else:
                self.output_ready.emit("", f"Error running tool: {e}", -1)
    
    def cancel(self):
        """Kill the running subprocess and its entire process group."""
        self._cancelled = True
        proc = self._process
        if proc is None:
            logger.warning("ToolRunnerWorker.cancel: no process to cancel")
            return
        
        pid = proc.pid
        poll = proc.poll()
        if poll is not None:
            logger.info(f"ToolRunnerWorker.cancel: process already exited (pid={pid}, rc={poll})")
            return
        
        # Kill the whole process group (bash + cortex + any children)
        try:
            pgid = os.getpgid(pid)
            logger.info(f"ToolRunnerWorker.cancel: sending SIGTERM to process group "
                        f"pgid={pgid} (pid={pid})")
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            logger.info(f"ToolRunnerWorker.cancel: process group already gone (pid={pid})")
            return
        except Exception as exc:
            logger.warning(f"ToolRunnerWorker.cancel: SIGTERM to pgid failed: {exc}, "
                           f"falling back to proc.kill()")
            proc.kill()
            return
        
        # Give the group a moment to exit gracefully, then force-kill
        try:
            proc.wait(timeout=3)
            logger.info(f"ToolRunnerWorker.cancel: process exited after SIGTERM (pid={pid})")
        except subprocess.TimeoutExpired:
            logger.warning(f"ToolRunnerWorker.cancel: SIGTERM timed out, sending SIGKILL "
                           f"to pgid={pgid}")
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as exc:
                logger.error(f"ToolRunnerWorker.cancel: SIGKILL failed: {exc}")
            logger.info(f"ToolRunnerWorker.cancel: SIGKILL sent (pid={pid})")


# ---------------------------------------------------------------------------
# Stream parsers — each is a callable: (raw_line: str) -> Optional[str]
# ---------------------------------------------------------------------------

def _stream_parser_raw(raw_line: str) -> Optional[str]:
    """Pass every line through as-is."""
    return raw_line.rstrip("\n")


def _stream_parser_cortex_json(raw_line: str) -> Optional[str]:
    """Parse cortex ``--output-format stream-json`` lines into human-readable status."""
    line = raw_line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return line  # fall back to raw

    msg = obj.get("message", {})
    content_list = msg.get("content", [])

    parts: List[str] = []
    for block in content_list:
        block_type = block.get("type", "")
        if block_type == "text":
            text = block.get("text", "").strip()
            if text:
                parts.append(text)
        elif block_type == "thinking":
            thinking = block.get("thinking", "").strip()
            if thinking:
                # Show first 120 chars of thinking to keep it brief
                preview = thinking[:120] + ("..." if len(thinking) > 120 else "")
                parts.append(f"[Thinking] {preview}")
        elif block_type == "tool_use":
            name = block.get("name", "unknown")
            tool_input = block.get("input", {})
            if name == "read":
                path = tool_input.get("file_path", "")
                parts.append(f"[Reading] {path}")
            elif name == "write":
                path = tool_input.get("file_path", "")
                parts.append(f"[Writing] {path}")
            elif name in ("bash", "shell"):
                cmd = tool_input.get("command", tool_input.get("description", ""))
                parts.append(f"[Running] {cmd}")
            elif name == "skill":
                skill_cmd = tool_input.get("command", "")
                parts.append(f"[Skill] {skill_cmd}")
            else:
                parts.append(f"[Tool: {name}]")
        elif block_type == "tool_result":
            # Tool results can be very long; show a brief summary
            content = block.get("content", "")
            if isinstance(content, str):
                preview = content[:200] + ("..." if len(content) > 200 else "")
                parts.append(f"  result: {preview}")
    
    if parts:
        return "\n".join(parts)
    return None


STREAM_PARSERS = {
    "raw": _stream_parser_raw,
    "cortex_json": _stream_parser_cortex_json,
}


class StreamingToolRunnerWorker(QThread):
    """Background worker that reads stdout line-by-line for real-time output.
    
    Emits ``output_line`` for each parsed line so the UI can display progress
    incrementally.  Also emits ``output_ready`` on completion for compatibility
    with ``_on_tool_finished``.
    """
    
    output_line = pyqtSignal(str)               # each parsed line (real-time)
    output_ready = pyqtSignal(str, str, int)     # full stdout, stderr, exit_code
    
    def __init__(self, command: List[str], cwd: str = None,
                 parser_fn=None, parent=None):
        super().__init__(parent)
        self.command = command
        self.cwd = cwd
        self._parser_fn = parser_fn or _stream_parser_raw
        self._process: Optional[subprocess.Popen] = None
        self._cancelled = False
        self._last_output_time = time.time()
    
    @property
    def last_output_time(self) -> float:
        """Timestamp of the most recent stdout line (thread-safe read)."""
        return self._last_output_time
    
    def run(self):
        logger.debug(f"StreamingToolRunnerWorker.run: starting — "
                     f"command={self.command}, cwd={self.cwd}")
        try:
            env = ToolRunnerWorker._get_user_env()
            self._process = subprocess.Popen(
                self.command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.cwd,
                env=env,
                start_new_session=True,
            )
            pid = self._process.pid
            self._last_output_time = time.time()
            logger.info(f"StreamingToolRunnerWorker.run: spawned pid={pid}")
            
            # Read stderr in a daemon thread to avoid pipe deadlock
            stderr_lines: List[str] = []
            
            def _read_stderr():
                try:
                    for err_line in self._process.stderr:
                        stderr_lines.append(err_line)
                except Exception:
                    pass
            
            stderr_thread = threading.Thread(target=_read_stderr, daemon=True)
            stderr_thread.start()
            
            # Read stdout line-by-line, emitting parsed output in real-time
            stdout_lines: List[str] = []
            for line in self._process.stdout:
                stdout_lines.append(line)
                self._last_output_time = time.time()
                try:
                    parsed = self._parser_fn(line)
                    if parsed is not None:
                        self.output_line.emit(parsed)
                except Exception as exc:
                    logger.debug(f"StreamingToolRunnerWorker: parser error: {exc}")
                    self.output_line.emit(line.rstrip("\n"))
            
            # stdout EOF — wait for process and stderr thread
            self._process.wait()
            stderr_thread.join(timeout=5)
            
            rc = self._process.returncode
            stdout_full = "".join(stdout_lines)
            stderr_full = "".join(stderr_lines)
            
            logger.debug(f"StreamingToolRunnerWorker.run: finished — "
                         f"pid={pid}, rc={rc}, cancelled={self._cancelled}, "
                         f"stdout_lines={len(stdout_lines)}, stderr_lines={len(stderr_lines)}")
            
            if self._cancelled:
                self.output_ready.emit(stdout_full, "Cancelled by user.", -2)
            else:
                self.output_ready.emit(stdout_full, stderr_full, rc)
        except Exception as e:
            logger.error(f"StreamingToolRunnerWorker.run: exception — "
                         f"{type(e).__name__}: {e}", exc_info=True)
            if self._cancelled:
                self.output_ready.emit("", "Cancelled by user.", -2)
            else:
                self.output_ready.emit("", f"Error running tool: {e}", -1)
    
    def cancel(self):
        """Kill the running subprocess and its entire process group."""
        self._cancelled = True
        proc = self._process
        if proc is None:
            logger.warning("StreamingToolRunnerWorker.cancel: no process to cancel")
            return
        
        pid = proc.pid
        poll = proc.poll()
        if poll is not None:
            logger.info(f"StreamingToolRunnerWorker.cancel: process already exited "
                        f"(pid={pid}, rc={poll})")
            return
        
        try:
            pgid = os.getpgid(pid)
            logger.info(f"StreamingToolRunnerWorker.cancel: sending SIGTERM to pgid={pgid}")
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            logger.info(f"StreamingToolRunnerWorker.cancel: process group already gone")
            return
        except Exception as exc:
            logger.warning(f"StreamingToolRunnerWorker.cancel: SIGTERM failed: {exc}, "
                           f"falling back to proc.kill()")
            proc.kill()
            return
        
        try:
            proc.wait(timeout=3)
            logger.info(f"StreamingToolRunnerWorker.cancel: process exited after SIGTERM")
        except subprocess.TimeoutExpired:
            logger.warning(f"StreamingToolRunnerWorker.cancel: SIGTERM timed out, "
                           f"sending SIGKILL to pgid={pgid}")
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception as exc:
                logger.error(f"StreamingToolRunnerWorker.cancel: SIGKILL failed: {exc}")


class UpdateCheckWorker(QThread):
    """Background worker to check for application updates without blocking the UI."""
    
    update_available = pyqtSignal(str, str, str, list)  # version, release_url, notes, assets
    check_finished = pyqtSignal()  # emitted when check completes (no update or error)
    
    def run(self):
        """Check GitHub releases for a newer version."""
        try:
            if GITHUB_OWNER == "YOUR_GITHUB_USERNAME":
                logger.debug("Startup update check: skipped (GITHUB_OWNER not configured)")
                self.check_finished.emit()
                return
            
            url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
            logger.debug(f"Startup update check: querying GitHub API")
            
            request = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"{APP_NAME}/{APP_VERSION}",
                }
            )
            
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
            
            latest_version = data.get("tag_name", "").lstrip("v")
            release_url = data.get("html_url", "")
            release_notes = data.get("body", "No release notes available.")
            assets = data.get("assets", [])
            
            # Compare versions
            current_parts = [int(x) for x in APP_VERSION.split(".")]
            latest_parts = [int(x) for x in latest_version.split(".")]
            
            while len(current_parts) < len(latest_parts):
                current_parts.append(0)
            while len(latest_parts) < len(current_parts):
                latest_parts.append(0)
            
            if latest_parts > current_parts:
                logger.info(f"Startup update check: new version available ({latest_version}, current {APP_VERSION})")
                self.update_available.emit(latest_version, release_url, release_notes, assets)
            else:
                logger.debug(f"Startup update check: already on latest version ({APP_VERSION})")
                self.check_finished.emit()
                
        except Exception as e:
            logger.debug(f"Startup update check failed silently: {e}")
            self.check_finished.emit()


# ---------------------------------------------------------------------------
# Tool Import / Management
# ---------------------------------------------------------------------------

class ToolFetchWorker(QThread):
    """Background worker to list available tools from a GitHub repo's tools/ directory.

    Uses the GitHub Contents API to enumerate sub-directories, then for each
    directory fetches its file listing so we know what will be downloaded.
    """

    # Signals
    listing_ready = pyqtSignal(list)     # list of dicts: [{name, url, files_url, ...}, ...]
    error = pyqtSignal(str)              # error message
    download_progress = pyqtSignal(str)  # status string while downloading
    download_finished = pyqtSignal(list, list)  # (installed_names, error_messages)

    def __init__(self, api_url: str, parent=None):
        super().__init__(parent)
        self.api_url = api_url
        self._tools_to_download: List[dict] = []
        self._local_tools_dir: Optional[Path] = None
        self._mode = "list"  # "list" or "download"

    # -- public helpers to configure a download pass --
    def start_download(self, tools: List[dict], local_tools_dir: Path):
        """Configure and start a download run."""
        self._tools_to_download = tools
        self._local_tools_dir = local_tools_dir
        self._mode = "download"
        self.start()

    def run(self):
        if self._mode == "download":
            self._run_download()
        else:
            self._run_list()

    # -- listing --
    def _run_list(self):
        try:
            req = urllib.request.Request(
                self.api_url,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"{APP_NAME}/{APP_VERSION}",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if not isinstance(data, list):
                self.error.emit("Unexpected response from GitHub API (expected a list).")
                return

            tool_dirs = [
                {
                    "name": item["name"],
                    "url": item["url"],          # API URL for the directory contents
                    "html_url": item.get("html_url", ""),
                }
                for item in data
                if item.get("type") == "dir"
            ]
            self.listing_ready.emit(tool_dirs)

        except urllib.error.HTTPError as e:
            self.error.emit(f"HTTP {e.code}: {e.reason}\n\nURL: {self.api_url}")
        except urllib.error.URLError as e:
            self.error.emit(f"Connection error: {e.reason}")
        except Exception as e:
            self.error.emit(str(e))

    # -- downloading --
    def _run_download(self):
        installed: List[str] = []
        errors: List[str] = []

        for tool in self._tools_to_download:
            name = tool["name"]
            self.download_progress.emit(f"Downloading {name}...")
            try:
                self._download_tool(tool)
                installed.append(name)
            except Exception as e:
                logger.error(f"Tool import: failed to download {name}: {e}", exc_info=True)
                errors.append(f"{name}: {e}")

        self.download_finished.emit(installed, errors)

    def _download_tool(self, tool: dict):
        """Download all files for a single tool directory, including subdirectories."""
        from gui.tool_dialogs import _backup_tool_json

        name = tool["name"]
        contents_url = tool["url"]

        local_dir = self._local_tools_dir / name
        local_dir.mkdir(parents=True, exist_ok=True)

        # Backup existing tool.json before overwriting
        local_tool_json = local_dir / "tool.json"
        if local_tool_json.exists():
            _backup_tool_json(local_tool_json)

        self._download_directory(contents_url, local_dir, name)

    def _download_directory(self, contents_url: str, local_dir: Path, display_prefix: str):
        """Recursively download all files from a GitHub directory."""
        req = urllib.request.Request(
            contents_url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"{APP_NAME}/{APP_VERSION}",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            items = json.loads(resp.read().decode("utf-8"))

        if not isinstance(items, list):
            raise ValueError(f"Unexpected response listing files for {display_prefix}")

        for item in items:
            item_type = item.get("type")
            item_name = item.get("name", "")

            if item_type == "dir":
                # Recurse into subdirectory
                sub_url = item.get("url")
                if not sub_url:
                    continue
                sub_dir = local_dir / item_name
                sub_dir.mkdir(parents=True, exist_ok=True)
                sub_prefix = f"{display_prefix}/{item_name}"
                self.download_progress.emit(f"  {sub_prefix}/")
                self._download_directory(sub_url, sub_dir, sub_prefix)

            elif item_type == "file":
                download_url = item.get("download_url")
                if not download_url:
                    continue

                self.download_progress.emit(f"  {display_prefix}/{item_name}")

                file_req = urllib.request.Request(
                    download_url,
                    headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"},
                )
                with urllib.request.urlopen(file_req, timeout=30) as file_resp:
                    content = file_resp.read()

                dest = local_dir / item_name
                with open(dest, "wb") as f:
                    f.write(content)

                # Make scripts executable
                if item_name.endswith(".sh"):
                    dest.chmod(dest.stat().st_mode | 0o111)


# ---------------------------------------------------------------------------
# Rule Import / Management
# ---------------------------------------------------------------------------

class RuleFetchWorker(QThread):
    """Background worker to list and download rules from a GitHub repo's rules/ directory.

    Mirrors ``ToolFetchWorker`` but targets rules (``rule.json`` + ``rule.json.sha256``).
    """

    listing_ready = pyqtSignal(list)        # [{name, url, ...}, ...]
    error = pyqtSignal(str)
    download_progress = pyqtSignal(str)
    download_finished = pyqtSignal(list, list)  # (installed_names, error_messages)

    def __init__(self, api_url: str, parent=None):
        super().__init__(parent)
        self.api_url = api_url
        self._rules_to_download: List[dict] = []
        self._local_rules_dir: Optional[Path] = None
        self._mode = "list"

    def start_download(self, rules: List[dict], local_rules_dir: Path):
        self._rules_to_download = rules
        self._local_rules_dir = local_rules_dir
        self._mode = "download"
        self.start()

    def run(self):
        if self._mode == "download":
            self._run_download()
        else:
            self._run_list()

    def _run_list(self):
        try:
            req = urllib.request.Request(
                self.api_url,
                headers={
                    "Accept": "application/vnd.github.v3+json",
                    "User-Agent": f"{APP_NAME}/{APP_VERSION}",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            if not isinstance(data, list):
                self.error.emit("Unexpected response from GitHub API (expected a list).")
                return

            rule_dirs = [
                {
                    "name": item["name"],
                    "url": item["url"],
                    "html_url": item.get("html_url", ""),
                }
                for item in data
                if item.get("type") == "dir"
            ]
            self.listing_ready.emit(rule_dirs)

        except urllib.error.HTTPError as e:
            self.error.emit(f"HTTP {e.code}: {e.reason}\n\nURL: {self.api_url}")
        except urllib.error.URLError as e:
            self.error.emit(f"Connection error: {e.reason}")
        except Exception as e:
            self.error.emit(str(e))

    def _run_download(self):
        installed: List[str] = []
        errors: List[str] = []

        for rule in self._rules_to_download:
            name = rule["name"]
            self.download_progress.emit(f"Downloading {name}...")
            try:
                self._download_rule(rule)
                installed.append(name)
            except Exception as e:
                logger.error(f"Rule import: failed to download {name}: {e}", exc_info=True)
                errors.append(f"{name}: {e}")

        self.download_finished.emit(installed, errors)

    def _download_rule(self, rule: dict):
        """Download all files for a single rule directory."""
        from gui.versioning import backup_json_file

        name = rule["name"]
        contents_url = rule["url"]

        req = urllib.request.Request(
            contents_url,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": f"{APP_NAME}/{APP_VERSION}",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            files = json.loads(resp.read().decode("utf-8"))

        if not isinstance(files, list):
            raise ValueError(f"Unexpected response listing files for {name}")

        local_dir = self._local_rules_dir / name
        local_dir.mkdir(parents=True, exist_ok=True)

        # Backup existing rule.json before overwriting
        local_rule_json = local_dir / "rule.json"
        if local_rule_json.exists():
            backup_json_file(local_rule_json)

        for item in files:
            if item.get("type") != "file":
                continue
            download_url = item.get("download_url")
            if not download_url:
                continue

            file_name = item["name"]
            self.download_progress.emit(f"  {name}/{file_name}")

            file_req = urllib.request.Request(
                download_url,
                headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"},
            )
            with urllib.request.urlopen(file_req, timeout=30) as file_resp:
                content = file_resp.read()

            dest = local_dir / file_name
            with open(dest, "wb") as f:
                f.write(content)
