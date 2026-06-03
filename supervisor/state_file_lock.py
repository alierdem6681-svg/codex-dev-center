#!/usr/bin/env python3
from __future__ import annotations

from contextlib import contextmanager
import fcntl
from pathlib import Path


@contextmanager
def state_file_lock(path: str | Path):
    target = Path(path)
    lock_path = target.with_name(target.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
