#!/usr/bin/env python3
from __future__ import annotations

from contextlib import contextmanager
import fcntl
from pathlib import Path
import threading


_LOCAL_LOCK = threading.RLock()
_HELD_LOCKS: dict[Path, int] = {}


@contextmanager
def state_file_lock(path: str | Path):
    target = Path(path)
    lock_path = target.with_name(target.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    resolved = lock_path.resolve()
    nested = False
    with _LOCAL_LOCK:
        depth = _HELD_LOCKS.get(resolved, 0)
        if depth:
            _HELD_LOCKS[resolved] = depth + 1
            nested = True
    if nested:
        try:
            yield
        finally:
            with _LOCAL_LOCK:
                remaining = _HELD_LOCKS.get(resolved, 1) - 1
                if remaining > 0:
                    _HELD_LOCKS[resolved] = remaining
                else:
                    _HELD_LOCKS.pop(resolved, None)
        return
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        with _LOCAL_LOCK:
            _HELD_LOCKS[resolved] = 1
        try:
            yield
        finally:
            with _LOCAL_LOCK:
                _HELD_LOCKS.pop(resolved, None)
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
