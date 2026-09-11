"""A tiny startup trace.

A packaged GUI app has no console, so when something stalls before the window
is usable there is nowhere for a traceback to go.  This writes a few timestamped
lines to ``%APPDATA%\\BlenderQueue\\startup.log`` instead, which is enough to
tell where a slow or failed launch got stuck.
"""

from __future__ import annotations

import os
import time

_START = time.time()
_PATH = None


def _path() -> str:
    global _PATH
    if _PATH is None:
        from .blender import config_dir
        _PATH = os.path.join(config_dir(), "startup.log")
    return _PATH


def log(message: str) -> None:
    try:
        with open(_path(), "a", encoding="utf-8") as fh:
            fh.write(f"{time.time() - _START:8.3f}s  {message}\n")
    except OSError:
        pass


def reset() -> None:
    """Start a fresh log for this launch."""
    try:
        with open(_path(), "w", encoding="utf-8") as fh:
            fh.write(time.strftime("=== BlenderQueue launch %Y-%m-%d %H:%M:%S ===\n"))
    except OSError:
        pass
