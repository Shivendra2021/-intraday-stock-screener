"""Runtime guards for long-running MarketMind processes."""

from __future__ import annotations

import atexit
import ctypes
import os
from dataclasses import dataclass


@dataclass
class SingleInstanceLock:
    name: str
    path: str
    handle: object | None = None
    mutex: object | None = None

    def acquire(self) -> bool:
        """Return True when this process owns the lock."""
        if os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            mutex_name = f"Global\\MarketMindPro_{self.name}"
            handle = kernel32.CreateMutexW(None, False, mutex_name)
            if not handle:
                return False
            already_exists = ctypes.get_last_error() == 183
            self.mutex = (kernel32, handle)
            if already_exists:
                self.close()
                return False
            atexit.register(self.close)
            return True

        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.handle = open(self.path, "a+", encoding="utf-8")
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.close()
            return False

        self.handle.seek(0)
        self.handle.truncate()
        self.handle.write(str(os.getpid()))
        self.handle.flush()
        atexit.register(self.close)
        return True

    def close(self) -> None:
        if self.mutex:
            kernel32, handle = self.mutex
            try:
                kernel32.CloseHandle(handle)
            except OSError:
                pass
            self.mutex = None

        if not self.handle:
            return
        try:
            import fcntl

            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self.handle.close()
        finally:
            self.handle = None


def acquire_single_instance(name: str) -> SingleInstanceLock | None:
    """Acquire a process-level lock under data/runtime."""
    lock = SingleInstanceLock(name=name, path=os.path.join("data", "runtime", f"{name}.lock"))
    return lock if lock.acquire() else None
