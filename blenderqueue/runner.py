"""Driving Blender: file inspection and sequential queue rendering.

Both use ``QProcess`` so the UI keeps repainting while Blender works, and so a
render can be cancelled mid-frame.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import time

from PySide6.QtCore import QObject, QProcess, Signal

from . import blender, schema
from .models import Job, Status
from .scripts.bq_video import read_cache

MARKER = "BQ>>"

# Blender's own per-frame chatter, used as a fallback progress source.
_STATS_RE = re.compile(r"Fra:(\d+).*?(?:Sample\s+(\d+)/(\d+))?", re.I)
_TIME_RE = re.compile(r"Time:([0-9:.]+)", re.I)


def schema_paths() -> dict:
    return {f.key: f.path for g in schema.GROUPS for f in g.fields if f.path}


def _temp_file(suffix: str) -> str:
    handle, path = tempfile.mkstemp(prefix="bq_", suffix=suffix)
    os.close(handle)
    return path


# --------------------------------------------------------------------------
# inspection
# --------------------------------------------------------------------------

class ScriptQueue(QObject):
    """Runs one background Blender script at a time and returns its JSON.

    File inspection and scene analysis work the same way -- launch Blender
    headless, let a script write a JSON file, read it back -- so the plumbing
    lives here and subclasses only supply the command line.
    """

    finished = Signal(str, dict)      # job_id, result ({"ok": False, "error": ...} on failure)
    progress = Signal(str, str)       # job_id, human status

    busy_message = "Working..."
    failure_message = "Blender did not return any information."

    def __init__(self, parent=None):
        super().__init__(parent)
        self._process: QProcess | None = None
        self._queue: list = []
        self._current: tuple | None = None

    @property
    def busy(self) -> bool:
        return self._current is not None

    @property
    def pending(self) -> int:
        return len(self._queue) + (1 if self._current else 0)

    def build_command(self, exe, blend_file, factory_startup, out_file, temps):
        raise NotImplementedError

    def extra_files(self):
        """Temporary input files to write now and delete afterwards."""
        return []

    def request(self, job_id: str, exe: str, blend_file: str, factory_startup: bool):
        self._queue.append((job_id, exe, blend_file, factory_startup))
        self._pump()

    def cancel_all(self):
        self._queue.clear()
        if self._process is not None:
            self._process.kill()

    def _pump(self):
        if self._current is not None or not self._queue:
            return
        job_id, exe, blend_file, factory_startup = self._queue.pop(0)
        out_file = _temp_file(".res.json")
        temps = self.extra_files()

        self._current = (job_id, out_file, temps)
        self.progress.emit(job_id, self.busy_message)

        command = self.build_command(exe, blend_file, factory_startup, out_file, temps)
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._process.start(command[0], command[1:])

    def _on_error(self, _error):
        if self._current is None:
            return
        job_id, *_ = self._current
        self._cleanup()
        self.finished.emit(job_id, {"ok": False, "error": "Could not start Blender."})
        self._pump()

    def _on_finished(self, _code, _status):
        if self._current is None:
            return
        job_id, out_file, temps = self._current
        output = ""
        if self._process is not None:
            output = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")

        result = {"ok": False, "error": self.failure_message}
        try:
            with open(out_file, "r", encoding="utf-8") as fh:
                result = json.load(fh)
        except Exception:
            tail = "\n".join(output.strip().splitlines()[-12:])
            if tail:
                result["error"] += "\n\n" + tail

        for path in [out_file] + list(temps):
            try:
                os.remove(path)
            except OSError:
                pass

        self._cleanup()
        self.finished.emit(job_id, result)
        self._pump()

    def _cleanup(self):
        if self._process is not None:
            self._process.deleteLater()
        self._process = None
        self._current = None


class Inspector(ScriptQueue):
    """Reads scenes, cameras, curves and Follow Path constraints from a .blend."""

    busy_message = "Reading file..."

    def extra_files(self):
        request_file = _temp_file(".req.json")
        with open(request_file, "w", encoding="utf-8") as fh:
            json.dump({"paths": schema_paths()}, fh)
        return [request_file]

    def build_command(self, exe, blend_file, factory_startup, out_file, temps):
        return blender.inspect_command(exe, blend_file, temps[0], out_file,
                                       factory_startup)


class Analyzer(ScriptQueue):
    """Measures what makes a scene expensive to render."""

    busy_message = "Analysing scene..."
    failure_message = "Blender did not return an analysis."

    def build_command(self, exe, blend_file, factory_startup, out_file, temps):
        return blender.analyze_command(exe, blend_file, out_file, "", factory_startup)


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------

class QueueRunner(QObject):
    """Renders enabled jobs one after another."""

    jobStarted = Signal(str)                  # job_id
    jobProgress = Signal(str)                 # job_id
    jobFinished = Signal(str, bool, str)      # job_id, ok, message
    queueFinished = Signal(bool)              # completed_everything
    log = Signal(str, str)                    # job_id, line
    stateChanged = Signal()
    recoveryAvailable = Signal(str, int, str)  # job_id, complete frames, folder

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._process: QProcess | None = None
        self._jobs: list = []
        self._index = -1
        self._current: Job | None = None
        self._config_file = ""
        self._buffer = ""
        self._paused = False
        self._stopping = False
        self._skipping = False
        self._exe_for = {}
        self._queue_positions = {}
        self._had_error = False
        self._frame_started = 0.0
        self._video_manifest = ""
        self._video_saved = ""
        self._waiting_recovery = False
        self._recovering = False
        self._interrupted = (1, QProcess.CrashExit)

    # ---- state ------------------------------------------------------

    @property
    def running(self) -> bool:
        return self._current is not None

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def current_job(self) -> Job | None:
        return self._current

    @property
    def waiting_recovery(self) -> bool:
        return self._waiting_recovery

    def remaining(self) -> int:
        return max(0, len(self._jobs) - self._index - 1)

    # ---- control ----------------------------------------------------

    def start(self, jobs: list, exe_for: dict):
        if self.running:
            return
        self._jobs = [job for job in jobs if job.enabled and job.status == Status.PENDING]
        self._queue_positions = {job.id: index for index, job in enumerate(jobs)}
        self._exe_for = dict(exe_for)
        self._index = -1
        self._paused = False
        self._stopping = False
        self._had_error = False
        for job in self._jobs:
            job.reset_runtime()
        self.stateChanged.emit()
        self._next()

    def stop(self):
        """Stop rendering now; offer recovery of committed video frames afterwards."""
        self._stopping = True
        self._paused = False
        if self._waiting_recovery:
            return
        if self._process is not None:
            self._process.kill()
        else:
            self._finish_queue(False)
        self.stateChanged.emit()

    def skip(self):
        """Drop the current job and move to the next one."""
        if self._process is not None:
            self._skipping = True
            self._process.kill()

    def set_paused(self, paused: bool):
        """Pausing takes effect at the next job boundary, not mid-frame."""
        self._paused = paused
        self.stateChanged.emit()
        if not paused and not self.running and not self._stopping:
            self._next()

    # ---- execution --------------------------------------------------

    def _next(self):
        if self._stopping:
            self._finish_queue(False)
            return
        if self._paused:
            self._current = None
            self.stateChanged.emit()
            return

        self._index += 1
        while self._index < len(self._jobs) and not self._jobs[self._index].enabled:
            self._jobs[self._index].status = Status.SKIPPED
            self.jobFinished.emit(self._jobs[self._index].id, True, "Disabled")
            self._index += 1

        if self._index >= len(self._jobs):
            self._finish_queue(True)
            return

        job = self._jobs[self._index]
        exe = self._exe_for.get(job.id)
        if not exe or not os.path.isfile(exe):
            self._fail(job, "No Blender executable configured for this job.")
            return
        if not job.exists:
            self._fail(job, f"File not found: {job.blend_path}")
            return

        self._current = job
        self._buffer = ""
        self._video_manifest = ""
        self._video_saved = ""
        self._recovering = False
        self._waiting_recovery = False
        job.reset_runtime()
        job.status = Status.RUNNING
        job.started_at = time.time()

        self._frame_started = 0.0
        self._config_file = _temp_file(".job.json")
        with open(self._config_file, "w", encoding="utf-8") as fh:
            json.dump(job.render_config(index=self._queue_positions.get(job.id, self._index)), fh, indent=1)

        command = blender.render_command(exe, job.blend_path, self._config_file,
                                         self.settings.factory_startup)
        self.jobStarted.emit(job.id)
        self._launch(command)

    def _launch(self, command):
        job = self._current
        self._process = QProcess(self)
        self._process.setProcessChannelMode(QProcess.MergedChannels)
        self._process.readyReadStandardOutput.connect(self._on_output)
        self._process.finished.connect(self._on_process_finished)
        self._process.errorOccurred.connect(self._on_process_error)

        self.log.emit(job.id, "> " + " ".join(f'"{c}"' if " " in c else c for c in command))
        self.stateChanged.emit()
        self._process.start(command[0], command[1:])

    def resolve_recovery(self, encode: bool):
        """Answer the recovery prompt while keeping the current job locked."""
        if not self._waiting_recovery or self._current is None:
            return
        self._waiting_recovery = False
        job = self._current
        if not encode:
            job.message = "Rendered frames kept in " + os.path.dirname(self._video_manifest)
            self.log.emit(job.id, job.message)
            self._complete_job(*self._interrupted)
            return
        self._recovering = True
        job.status = Status.ENCODING
        job.message = f"Encoding {job.frames_done} rendered frames…"
        self.jobProgress.emit(job.id)
        command = blender.encode_command(self._exe_for[job.id], job.blend_path,
                                         self._video_manifest, self.settings.factory_startup)
        self._launch(command)

    def _fail(self, job: Job, message: str):
        job.status = Status.FAILED
        job.message = message
        job.finished_at = time.time()
        self._had_error = True
        self.log.emit(job.id, "ERROR: " + message)
        self.jobFinished.emit(job.id, False, message)
        if self.settings.stop_on_error:
            self._finish_queue(False)
        else:
            self._next()

    # ---- output parsing ---------------------------------------------

    def _on_output(self):
        if self._process is None:
            return
        chunk = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace")
        self._buffer += chunk
        *lines, self._buffer = self._buffer.split("\n")
        for line in lines:
            self._handle_line(line.rstrip("\r"))

    def _handle_line(self, line: str):
        job = self._current
        if job is None or not line.strip():
            return

        if line.startswith(MARKER):
            try:
                event = json.loads(line[len(MARKER):])
            except json.JSONDecodeError:
                return
            self._handle_event(job, event)
            return

        self.log.emit(job.id, line)

        # fall back to Blender's own "Fra:12 ... Sample 7/64" chatter
        if line.startswith("Fra:"):
            match = _STATS_RE.match(line)
            if match:
                job.current_frame = int(match.group(1))
                self.jobProgress.emit(job.id)

    def _handle_event(self, job: Job, event: dict):
        kind = event.get("e")
        if kind == "start":
            job.frames_total = int(event.get("total") or 0)
            job.message = "{} - {} frames".format(event.get("engine", ""), job.frames_total)
            self.log.emit(job.id, "Rendering scene '{}' frames {}-{} step {} -> {}".format(
                event.get("scene"), event.get("frame_start"), event.get("frame_end"),
                event.get("frame_step"), event.get("output")))
        elif kind == "pre":
            job.current_frame = int(event.get("frame") or 0)
            self._frame_started = time.time()
        elif kind == "write":
            job.frames_done = int(event.get("written") or job.frames_done + 1)
            if not event.get("cached"):
                job.last_output = event.get("path", "")
            if self._frame_started:
                job.frame_times.append(max(0.0, time.time() - self._frame_started))
                self._frame_started = 0.0
        elif kind == "video_cache":
            self._video_manifest = event["manifest"]
            job.video_manifest = self._video_manifest
            self.log.emit(job.id, "Video recovery frames: " + os.path.dirname(self._video_manifest))
        elif kind == "encoding":
            job.status = Status.ENCODING
            job.message = "Encoding {} rendered frames…".format(event["frames"])
            self.log.emit(job.id, job.message)
        elif kind == "video_done":
            self._video_saved = event["path"]
            job.last_output = self._video_saved
            if not event.get("partial"):
                job.video_manifest = ""
            self.log.emit(job.id, "Video saved: " + self._video_saved)
        elif kind == "retarget":
            self.log.emit(job.id, "Follow Path: {} -> {}".format(
                event.get("object"), event.get("target")))
        elif kind == "skip":
            self.log.emit(job.id, "Skipped {}: {}".format(event.get("key"), event.get("msg")))
        elif kind in ("warn", "info"):
            self.log.emit(job.id, event.get("msg", ""))
        elif kind == "error":
            detail = (event.get("msg") or "").strip().splitlines()
            job.message = detail[-1] if detail else "Render failed"
            self.log.emit(job.id, event.get("msg", ""))
        self.jobProgress.emit(job.id)

    # ---- completion --------------------------------------------------

    def _on_process_error(self, _error):
        if self._current is not None and self._process is not None:
            self.log.emit(self._current.id, "Process error: " + self._process.errorString())
            if _error == QProcess.FailedToStart:
                self._current.message = self._process.errorString()
                self._on_process_finished(1, QProcess.NormalExit)

    def _on_process_finished(self, code: int, status):
        self._on_output()  # finished can arrive with final progress still buffered
        self._dispose_process()
        job = self._current
        if job is None:
            return
        if self._recovering:
            if code == 0 and status != QProcess.CrashExit and self._video_saved:
                job.message = f"Saved {job.frames_done} frames to {self._video_saved}"
                self._complete_job(*self._interrupted)
            else:
                job.message = "Encoding failed or was stopped. Frames kept in " + os.path.dirname(self._video_manifest)
                self.log.emit(job.id, job.message)
                self._complete_job(1, QProcess.CrashExit, recovery_error=True)
            return
        interrupted = self._stopping or self._skipping or code != 0 or status == QProcess.CrashExit
        if self._video_manifest and not self._video_saved:
            # A clean process exit alone is not proof that an encoded file exists.
            interrupted = True
            if code == 0:
                code = 1
        if interrupted and self._video_manifest and not self._video_saved:
            try:
                _, frames = read_cache(self._video_manifest)
            except (OSError, ValueError, KeyError) as exc:
                self.log.emit(job.id, "Could not read recovery data: " + str(exc))
                frames = []
            if frames:
                self._interrupted = (code, status)
                self._waiting_recovery = True
                job.frames_done = len(frames)
                job.message = f"{len(frames)} rendered frames available to encode"
                self.jobProgress.emit(job.id)
                self.stateChanged.emit()
                self.recoveryAvailable.emit(job.id, len(frames), os.path.dirname(self._video_manifest))
                return
        self._complete_job(code, status)

    def _complete_job(self, code: int, status, recovery_error=False):
        job = self._current
        self._teardown_process()
        if job is None:
            return

        job.finished_at = time.time()
        killed = status == QProcess.CrashExit

        if recovery_error:
            self._skipping = False
            job.status = Status.FAILED
            self._had_error = True
            self.jobFinished.emit(job.id, False, job.message)
            if self._stopping or self.settings.stop_on_error:
                self._finish_queue(False)
                return
        elif self._skipping:
            self._skipping = False
            job.status = Status.SKIPPED
            job.message = "Skipped" + (" — " + job.message if job.video_manifest or job.last_output else "")
            self.jobFinished.emit(job.id, True, job.message)
        elif self._stopping:
            job.status = Status.CANCELLED
            job.message = "Stopped" + (" — " + job.message if job.video_manifest or job.last_output else "")
            self.jobFinished.emit(job.id, False, job.message)
            self._finish_queue(False)
            return
        elif code == 0 and not killed:
            job.status = Status.DONE
            job.message = "{} frame{} in {}".format(
                job.frames_done, "" if job.frames_done == 1 else "s",
                format_duration(job.duration))
            self.jobFinished.emit(job.id, True, job.message)
        else:
            job.status = Status.FAILED
            job.message = job.message or f"Blender exited with code {code}"
            self._had_error = True
            self.jobFinished.emit(job.id, False, job.message)
            if self.settings.stop_on_error:
                self._finish_queue(False)
                return

        self._next()

    def _dispose_process(self):
        if self._buffer.strip():
            self._handle_line(self._buffer.rstrip("\r"))
        self._buffer = ""
        if self._process is not None:
            self._process.deleteLater()
        self._process = None

    def _teardown_process(self):
        self._dispose_process()
        self._current = None
        self._waiting_recovery = False
        self._recovering = False
        if self._config_file:
            try:
                os.remove(self._config_file)
            except OSError:
                pass
            self._config_file = ""

    def _finish_queue(self, completed: bool):
        self._teardown_process()
        self._jobs = []
        self._index = -1
        self._stopping = False
        self._paused = False
        self._skipping = False
        self.stateChanged.emit()
        self.queueFinished.emit(completed and not self._had_error)


def format_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {secs:02d}s"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"
