"""Application settings and queue files on disk."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from .blender import config_dir
from .models import QUEUE_FORMAT_VERSION, Job

SETTINGS_FILE = "settings.json"
AUTOSAVE_FILE = "queue.autosave.bqueue"
QUEUE_SUFFIX = ".bqueue"


@dataclass
class AppSettings:
    default_blender: str = ""             # BlenderInstall.key
    custom_blender_paths: list = field(default_factory=list)
    factory_startup: bool = True
    stop_on_error: bool = False
    auto_open_output: bool = False
    confirm_delete: bool = True
    shutdown_when_done: bool = False
    keep_log_lines: int = 4000
    last_queue_path: str = ""
    last_browse_dir: str = ""
    window_geometry: str = ""
    splitter_state: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "AppSettings":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in (data or {}).items() if k in known})


def settings_path() -> str:
    return os.path.join(config_dir(), SETTINGS_FILE)


def load_settings() -> AppSettings:
    try:
        # utf-8-sig: a settings.json edited in Notepad picks up a BOM
        with open(settings_path(), "r", encoding="utf-8-sig") as fh:
            return AppSettings.from_dict(json.load(fh))
    except Exception:
        return AppSettings()


def save_settings(settings: AppSettings) -> None:
    try:
        with open(settings_path(), "w", encoding="utf-8") as fh:
            json.dump(settings.to_dict(), fh, indent=1)
    except OSError:
        pass


# --------------------------------------------------------------------------
# queues
# --------------------------------------------------------------------------

def autosave_path() -> str:
    return os.path.join(config_dir(), AUTOSAVE_FILE)


def save_queue(path: str, jobs: list) -> None:
    payload = {
        "format": QUEUE_FORMAT_VERSION,
        "jobs": [job.to_dict() for job in jobs],
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, path)


def load_queue(path: str) -> list:
    with open(path, "r", encoding="utf-8-sig") as fh:
        payload = json.load(fh)
    if isinstance(payload, list):          # tolerate a bare list of jobs
        raw_jobs = payload
    else:
        raw_jobs = payload.get("jobs") or []
    return [Job.from_dict(entry) for entry in raw_jobs]


def try_load_autosave() -> list:
    try:
        return load_queue(autosave_path())
    except Exception:
        return []
