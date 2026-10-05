"""Queue data model: jobs, their overrides, and JSON round-tripping."""

from __future__ import annotations

import datetime as _dt
import os
import re
import uuid
from copy import deepcopy
from dataclasses import dataclass, field

from . import schema

QUEUE_FORMAT_VERSION = 1


class Status:
    PENDING = "Pending"
    RUNNING = "Rendering"
    ENCODING = "Encoding"
    DONE = "Done"
    FAILED = "Failed"
    CANCELLED = "Cancelled"
    SKIPPED = "Skipped"

    TERMINAL = (DONE, FAILED, CANCELLED, SKIPPED)


@dataclass
class GroupOverride:
    """One schema group: whether it is active, and the values it would apply."""

    enabled: bool = False
    values: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"enabled": self.enabled, "values": dict(self.values)}

    @classmethod
    def from_dict(cls, data: dict) -> "GroupOverride":
        return cls(bool(data.get("enabled", False)), dict(data.get("values", {})))


@dataclass
class FollowPathEdit:
    """A retarget (and optional tweak) of one Follow Path constraint."""

    object: str = ""
    bone: str = ""
    constraint: str = ""
    target: str = ""
    use_curve_follow: bool | None = None
    use_fixed_location: bool | None = None
    forward_axis: str | None = None
    up_axis: str | None = None
    offset: float | None = None
    offset_factor: float | None = None
    influence: float | None = None
    mute: bool | None = None
    enabled: bool = True

    KEY_FIELDS = ("object", "bone", "constraint")
    OPTIONAL = ("use_curve_follow", "use_fixed_location", "forward_axis", "up_axis",
                "offset", "offset_factor", "influence", "mute")

    @property
    def key(self) -> tuple:
        return (self.object, self.bone, self.constraint)

    @property
    def label(self) -> str:
        if self.bone:
            return f"{self.object} / {self.bone} / {self.constraint}"
        return f"{self.object} / {self.constraint}"

    def to_dict(self) -> dict:
        data = {k: getattr(self, k) for k in self.KEY_FIELDS}
        data["target"] = self.target
        data["enabled"] = self.enabled
        for key in self.OPTIONAL:
            value = getattr(self, key)
            if value is not None:
                data[key] = value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "FollowPathEdit":
        edit = cls(
            object=data.get("object", ""),
            bone=data.get("bone", ""),
            constraint=data.get("constraint", ""),
            target=data.get("target", ""),
            enabled=bool(data.get("enabled", True)),
        )
        for key in cls.OPTIONAL:
            if key in data:
                setattr(edit, key, data[key])
        return edit

    def payload(self) -> dict:
        """What gets sent to bq_render.py (drops the UI-only 'enabled' flag)."""
        data = self.to_dict()
        data.pop("enabled", None)
        return data


@dataclass
class Job:
    """One .blend queued for rendering."""

    blend_path: str = ""
    name: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    enabled: bool = True
    use_overrides: bool = False
    blender_key: str = ""            # "" = use the application default install
    groups: dict = field(default_factory=dict)          # group_key -> GroupOverride
    follow_paths: list = field(default_factory=list)    # FollowPathEdit
    notes: str = ""
    visibility_enabled: bool = False
    visibility: dict = field(default_factory=dict)  # scene -> sparse outliner overrides
    video_manifest: str = ""          # retained recovery frames, also saved with the queue

    # --- populated by inspection / analysis (cached, not authoritative) --
    info: dict = field(default_factory=dict)
    analysis: dict = field(default_factory=dict)     # raw bq_analyze.py output

    # --- runtime state, reset on each run ------------------------------
    status: str = Status.PENDING
    message: str = ""
    frames_done: int = 0
    frames_total: int = 0
    current_frame: int = 0
    last_output: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    frame_times: list = field(default_factory=list)   # seconds per finished frame
    _score_cache: tuple = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        if not self.name:
            self.name = os.path.splitext(os.path.basename(self.blend_path))[0] or "Untitled"
        for group in schema.GROUPS:
            self.groups.setdefault(group.key, GroupOverride())

    # ------------------------------------------------------------------
    # convenience
    # ------------------------------------------------------------------

    @property
    def exists(self) -> bool:
        return bool(self.blend_path) and os.path.isfile(self.blend_path)

    @property
    def is_terminal(self) -> bool:
        return self.status in Status.TERMINAL

    @property
    def is_locked(self) -> bool:
        """A job being rendered right now must not be edited underneath it."""
        return self.status in (Status.RUNNING, Status.ENCODING)

    @property
    def duration(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.finished_at or _dt.datetime.now().timestamp()
        return max(0.0, end - self.started_at)

    @property
    def seconds_per_frame(self) -> float:
        """Average time per finished frame, favouring recent frames.

        Early frames often include one-off scene build cost, so a trailing
        window tracks a long render better than a lifetime average.
        """
        if self.frame_times:
            recent = self.frame_times[-25:]
            return sum(recent) / len(recent)
        if self.frames_done and self.duration:
            return self.duration / self.frames_done
        return 0.0

    @property
    def frames_remaining(self) -> int:
        if not self.frames_total:
            return 0
        return max(0, self.frames_total - self.frames_done)

    @property
    def eta_seconds(self) -> float:
        per_frame = self.seconds_per_frame
        if not per_frame or not self.frames_total:
            return 0.0
        return self.frames_remaining * per_frame

    def estimated_total_seconds(self) -> float:
        """Best guess at the whole job, for queues that have not started it."""
        if self.status == Status.DONE:
            return self.duration
        per_frame = self.seconds_per_frame
        if per_frame and self.frames_total:
            return self.duration + self.eta_seconds
        return 0.0

    def analysis_score(self):
        """(overall, rating) from the cached analysis, or None.

        Scoring walks the whole measurement, and the queue list repaints often,
        so the result is memoised against the analysis it came from.
        """
        if not self.analysis:
            return None
        stamp = id(self.analysis)
        if self._score_cache and self._score_cache[0] == stamp:
            return self._score_cache[1], self._score_cache[2]
        from .analysis import build_report
        report = build_report(self.analysis)
        if report.error:
            self._score_cache = (stamp, None, "")
            return None
        self._score_cache = (stamp, report.overall, report.rating)
        return report.overall, report.rating

    def group(self, key: str) -> GroupOverride:
        return self.groups.setdefault(key, GroupOverride())

    def active_group_keys(self) -> list:
        if not self.use_overrides:
            return []
        return [g.key for g in schema.GROUPS if self.group(g.key).enabled]

    def active_follow_paths(self) -> list:
        return [f for f in self.follow_paths if f.enabled and f.target]

    def scene_info(self, scene_name: str = "") -> dict:
        """Inspected description of a scene (defaults to the selected one)."""
        scenes = self.info.get("scenes") or []
        if not scenes:
            return {}
        wanted = scene_name or self.selected_scene()
        for scene in scenes:
            if scene.get("name") == wanted:
                return scene
        return scenes[0]

    def selected_scene(self) -> str:
        group = self.group("scene")
        chosen = group.values.get("scene") if self.use_overrides and group.enabled else ""
        if chosen:
            return chosen
        return self.info.get("active_scene") or ""

    def summary(self) -> str:
        """Short human description shown in the queue list."""
        visibility = self.visibility_enabled and bool(self.visibility)
        if not self.use_overrides:
            return "Visibility overrides" if visibility else "File settings"
        active = self.active_group_keys()
        bits = []
        if active:
            bits.append(f"{len(active)} override{'s' if len(active) != 1 else ''}")
        retargets = len(self.active_follow_paths())
        if retargets:
            bits.append(f"{retargets} path{'s' if retargets != 1 else ''}")
        if visibility:
            bits.append("visibility")
        return ", ".join(bits) or "File settings"

    def reset_runtime(self):
        self.status = Status.PENDING
        self.message = ""
        self.frames_done = 0
        self.frames_total = 0
        self.current_frame = 0
        self.last_output = ""
        self.started_at = 0.0
        self.finished_at = 0.0
        self.frame_times = []

    # ------------------------------------------------------------------
    # payload for the Blender-side runner
    # ------------------------------------------------------------------

    def render_config(self, index: int = 0, dry_run: bool = False) -> dict:
        groups = {}
        for key in self.active_group_keys():
            values = dict(self.group(key).values)
            values = {k: v for k, v in values.items() if k in schema.FIELD_BY_KEY}
            if key == "output":
                values = self._expand_output_tokens(values, index)
            groups[key] = values

        return {
            "job_id": self.id,
            "job_name": self.name,
            "blend_file": self.blend_path,
            "paths": {f.key: f.path for g in schema.GROUPS for f in g.fields if f.path},
            "groups": groups,
            "follow_paths": [f.payload() for f in self.active_follow_paths()],
            "curve_modifiers": [],
            "enable_cycles": True,
            "dry_run": dry_run,
            "visibility": deepcopy(self.visibility) if self.visibility_enabled else {},
        }

    def _expand_output_tokens(self, values: dict, index: int) -> dict:
        values = dict(values)
        for key in ("output_dir", "file_prefix"):
            if values.get(key):
                values[key] = expand_tokens(values[key], self, index)
        return values

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "blend_path": self.blend_path,
            "enabled": self.enabled,
            "use_overrides": self.use_overrides,
            "blender_key": self.blender_key,
            "notes": self.notes,
            "groups": {k: v.to_dict() for k, v in self.groups.items()},
            "follow_paths": [f.to_dict() for f in self.follow_paths],
            "info": self.info,
            "analysis": self.analysis,
            "visibility_enabled": self.visibility_enabled,
            "visibility": deepcopy(self.visibility),
            "video_manifest": self.video_manifest,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Job":
        job = cls(
            blend_path=data.get("blend_path", ""),
            name=data.get("name", ""),
            id=data.get("id") or uuid.uuid4().hex[:12],
            enabled=bool(data.get("enabled", True)),
            use_overrides=bool(data.get("use_overrides", False)),
            blender_key=data.get("blender_key", ""),
            notes=data.get("notes", ""),
            info=data.get("info") or {},
            analysis=data.get("analysis") or {},
            visibility_enabled=bool(data.get("visibility_enabled", False)),
            visibility=deepcopy(data.get("visibility") or {}),
            video_manifest=data.get("video_manifest") or "",
        )
        for key, raw in (data.get("groups") or {}).items():
            if key in schema.GROUP_BY_KEY:
                job.groups[key] = GroupOverride.from_dict(raw)
        job.follow_paths = [FollowPathEdit.from_dict(f) for f in data.get("follow_paths") or []]
        return job

    def duplicate(self, new_name: str = "") -> "Job":
        clone = Job.from_dict(self.to_dict())
        clone.id = uuid.uuid4().hex[:12]
        clone.name = new_name or next_copy_name(self.name)
        clone.reset_runtime()
        return clone


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

_COPY_RE = re.compile(r"^(?P<base>.*?)(?: \((?P<num>\d+)\))?$")


def next_copy_name(name: str) -> str:
    """'Shot' -> 'Shot (2)', 'Shot (2)' -> 'Shot (3)'."""
    match = _COPY_RE.match(name.strip())
    base = match.group("base") if match else name
    number = int(match.group("num")) if match and match.group("num") else 1
    return f"{base} ({number + 1})"


def unique_name(name: str, taken: set) -> str:
    candidate = name
    while candidate in taken:
        candidate = next_copy_name(candidate)
    return candidate


def sanitize(text: str) -> str:
    """Make a string safe to drop into a file or folder name."""
    cleaned = re.sub(r'[<>:"/\\|?*]+', "_", str(text)).strip(" .")
    return cleaned or "untitled"


def expand_tokens(text: str, job: "Job", index: int = 0) -> str:
    """Expand {job}, {blend}, {scene}, {date}, {time}, {index} in output paths."""
    now = _dt.datetime.now()
    blend_stem = os.path.splitext(os.path.basename(job.blend_path))[0]
    values = {
        "job": sanitize(job.name),
        "blend": sanitize(blend_stem),
        "scene": sanitize(job.selected_scene() or "Scene"),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H-%M-%S"),
        "index": f"{index + 1:02d}",
    }
    result = text
    for token, value in values.items():
        result = result.replace("{" + token + "}", value)
    return result


TOKEN_HELP = (
    "{job} job name    {blend} .blend file name    {scene} scene name\n"
    "{date} YYYY-MM-DD    {time} HH-MM-SS    {index} position in queue"
)
