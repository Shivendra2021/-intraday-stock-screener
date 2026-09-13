"""
bot_process.py — Background process manager for MarketMind Pro main.py.
Handles clean detached background startup, graceful shutdown, and PID monitoring.
"""

from __future__ import annotations

import ctypes
import datetime
import json
import logging
import os
import subprocess
import sys
from typing import Any

logger = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID_FILE = os.path.join(BASE_DIR, "data", "bot.pid")
STATE_FILE = os.path.join(BASE_DIR, "data", "system_state.json")
LOG_FILE = os.path.join(BASE_DIR, "logs", "bot.log")


def _is_pid_alive_win(pid: int) -> bool:
    """Check if process with given PID is still active on Windows."""
    try:
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        exit_code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return exit_code.value == 259  # STILL_ACTIVE = 259
    except Exception:
        return False


def find_bot_pid_ps() -> int | None:
    """Fallback: discover running main.py process ID using PowerShell."""
    try:
        ps_cmd = (
            "Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" | "
            "Where-Object { $_.CommandLine -like '*main.py*' } | "
            "Select-Object -ExpandProperty ProcessId -First 1"
        )
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=8,
        )
        out = res.stdout.strip()
        if out and out.isdigit():
            return int(out)
    except Exception as exc:
        logger.debug("PowerShell PID search error: %s", exc)
    return None


def get_bot_status() -> dict[str, Any]:
    """Check if main.py is running in the background and return detailed status."""
    pid = None

    # 1. Check PID file
    if os.path.exists(PID_FILE):
        try:
            with open(PID_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content.isdigit():
                    candidate_pid = int(content)
                    if _is_pid_alive_win(candidate_pid):
                        pid = candidate_pid
                    else:
                        # Stale PID file
                        try:
                            os.remove(PID_FILE)
                        except OSError:
                            pass
        except Exception:
            pass

    # 2. If PID not found via file, search running processes
    if not pid:
        pid = find_bot_pid_ps()
        if pid:
            try:
                os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
                with open(PID_FILE, "w", encoding="utf-8") as f:
                    f.write(str(pid))
            except Exception:
                pass

    is_running = pid is not None

    state = {
        "enabled": is_running,
        "running": is_running,
        "pid": pid,
        "mode": "ACTIVE" if is_running else "STANDBY",
        "label": "System Active" if is_running else "System Standby",
        "description": (
            f"Intraday AI screening and tracking running in background (PID {pid})"
            if is_running
            else "System is stopped. Click 'System Standby' button to turn ON in background."
        ),
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }

    # Save to state file for persistence
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp = f"{STATE_FILE}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception:
        pass

    return state


def start_bot() -> dict[str, Any]:
    """Launch main.py as a clean, detached background process."""
    current = get_bot_status()
    if current.get("running"):
        return {
            "ok": True,
            "running": True,
            "pid": current.get("pid"),
            "message": f"System core is already running in background (PID {current.get('pid')}).",
            "state": current,
        }

    python_exe = sys.executable
    venv_py = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
    if os.path.exists(venv_py):
        python_exe = venv_py
    main_script = os.path.join(BASE_DIR, "main.py")
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

    # Detached process flags on Windows
    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    creation_flags = DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP

    try:
        log_handle = open(LOG_FILE, "a", encoding="utf-8")
        proc = subprocess.Popen(
            [python_exe, main_script],
            cwd=BASE_DIR,
            stdout=log_handle,
            stderr=log_handle,
            creationflags=creation_flags,
            close_fds=True,
        )
        pid = proc.pid

        # Persist PID
        os.makedirs(os.path.dirname(PID_FILE), exist_ok=True)
        with open(PID_FILE, "w", encoding="utf-8") as f:
            f.write(str(pid))

        state = {
            "enabled": True,
            "running": True,
            "pid": pid,
            "mode": "ACTIVE",
            "label": "System Active",
            "description": f"Intraday AI screening running in background (PID {pid})",
            "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        }

        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception:
            pass

        logger.info("Started main.py in background with PID %s", pid)
        return {
            "ok": True,
            "running": True,
            "pid": pid,
            "message": f"System successfully turned ON in background (PID {pid}).",
            "state": state,
        }
    except Exception as exc:
        logger.error("Failed to start main.py in background: %s", exc)
        return {
            "ok": False,
            "running": False,
            "pid": None,
            "error": str(exc),
            "message": f"Failed to start system: {exc}",
        }


def stop_bot() -> dict[str, Any]:
    """Gracefully terminate main.py and any child processes."""
    current = get_bot_status()
    pid = current.get("pid")

    if not pid:
        return {
            "ok": True,
            "running": False,
            "pid": None,
            "message": "System is already stopped.",
            "state": current,
        }

    try:
        # Forcefully terminate process tree on Windows
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, text=True)
    except Exception as exc:
        logger.warning("taskkill error for PID %s: %s", pid, exc)

    if os.path.exists(PID_FILE):
        try:
            os.remove(PID_FILE)
        except OSError:
            pass

    state = {
        "enabled": False,
        "running": False,
        "pid": None,
        "mode": "STANDBY",
        "label": "System Standby",
        "description": "System core stopped by user. Click to turn ON.",
        "updated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    }

    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception:
        pass

    logger.info("Stopped main.py (PID %s)", pid)
    return {
        "ok": True,
        "running": False,
        "pid": None,
        "message": f"System (PID {pid}) stopped and set to standby.",
        "state": state,
    }


def toggle_bot(enable: bool | None = None) -> dict[str, Any]:
    """Toggle system state between running and stopped."""
    current = get_bot_status()
    is_currently_running = bool(current.get("running"))

    if enable is True:
        return start_bot()
    elif enable is False:
        return stop_bot()
    elif not is_currently_running:
        return start_bot()
    else:
        return stop_bot()
