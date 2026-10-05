import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QProcess
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from blenderqueue.models import Job, Status
from blenderqueue.runner import QueueRunner
from blenderqueue.scripts.bq_video import FORMAT, read_cache
from blenderqueue.store import AppSettings, load_queue, save_queue
from blenderqueue.ui.main_window import MainWindow


def make_cache(folder):
    folder = Path(folder)
    manifest = folder / "manifest.json"
    manifest.write_text(json.dumps({"format": FORMAT, "frame_start": 5,
        "frame_end": 15, "frame_step": 2}), encoding="utf-8")
    entries = []
    for frame in (5, 7):
        filename = f"frame-{frame:04d}.exr"
        (folder / filename).write_bytes(b"completed fixture frame")
        entries.append(json.dumps({"frame": frame, "file": filename}) + "\n")
    (folder / "frames.jsonl").write_text("".join(entries), encoding="utf-8")
    return str(manifest)


class CacheTests(unittest.TestCase):
    def test_only_committed_contiguous_frames_are_recovered(self):
        with tempfile.TemporaryDirectory() as directory:
            path = make_cache(directory)
            with open(Path(directory) / "frames.jsonl", "a", encoding="utf-8") as stream:
                stream.write('{"frame": 9')
            _, frames = read_cache(path)
            self.assertEqual([frame["frame"] for frame in frames], [5, 7])
            (Path(directory) / "frame-0007.exr").write_bytes(b"")
            self.assertEqual(len(read_cache(path)[1]), 1)

    def test_recovery_path_survives_queue_save_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            job = Job(video_manifest=make_cache(directory))
            job.reset_runtime()
            path = str(Path(directory) / "queue.bqueue")
            save_queue(path, [job])
            restored = load_queue(path)[0]
            self.assertEqual(len(read_cache(restored.video_manifest)[1]), 2)


class RunnerControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.job = Job(name="Video", status=Status.RUNNING)
        self.job.video_manifest = make_cache(self.temp.name)
        self.runner = QueueRunner(AppSettings())
        self.runner._current = self.job
        self.runner._video_manifest = self.job.video_manifest
        self.runner._exe_for = {self.job.id: "blender.exe"}
        self.prompts, self.results = [], []
        self.runner.recoveryAvailable.connect(lambda *args: self.prompts.append(args))
        self.runner.queueFinished.connect(self.results.append)

    def tearDown(self):
        self.temp.cleanup()

    def interrupt(self):
        self.runner._stopping = True
        self.runner._on_process_finished(1, QProcess.CrashExit)
        self.assertTrue(self.runner.waiting_recovery)
        self.assertTrue(self.job.is_locked)
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.prompts[0][1], 2)
        self.assertEqual(self.results, [])

    def test_stop_then_keep_frames_finishes_queue_without_movie(self):
        self.interrupt()
        self.runner.resolve_recovery(False)
        self.assertEqual(self.results, [False])
        self.assertEqual(self.job.status, Status.CANCELLED)
        self.assertEqual(self.job.last_output, "")
        self.assertTrue(Path(self.job.video_manifest).exists())

    def test_partial_encode_keeps_job_locked_until_video_is_complete(self):
        self.interrupt()
        with patch.object(self.runner, "_launch") as launch:
            self.runner.resolve_recovery(True)
        self.assertTrue(launch.called)
        self.assertEqual(self.job.status, Status.ENCODING)
        self.assertTrue(self.job.is_locked)
        self.assertEqual(self.results, [])
        self.runner._handle_event(self.job, {"e": "video_done", "path": "partial.mp4", "partial": True})
        self.runner._on_process_finished(0, QProcess.NormalExit)
        self.assertEqual(self.results, [False])
        self.assertEqual(self.job.status, Status.CANCELLED)
        self.assertEqual(self.job.last_output, "partial.mp4")

    def test_encoder_failure_preserves_frames_and_does_not_loop_prompt(self):
        self.interrupt()
        with patch.object(self.runner, "_launch"):
            self.runner.resolve_recovery(True)
        self.runner._on_process_finished(1, QProcess.CrashExit)
        self.assertEqual(self.job.status, Status.FAILED)
        self.assertTrue(Path(self.job.video_manifest).exists())
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.results, [False])

    def test_stop_before_first_frame_has_no_recovery_prompt(self):
        (Path(self.temp.name) / "frames.jsonl").unlink()
        self.runner._stopping = True
        self.runner._on_process_finished(1, QProcess.CrashExit)
        self.assertEqual(self.prompts, [])
        self.assertEqual(self.results, [False])

    def test_start_does_not_reset_previously_finished_jobs(self):
        runner = QueueRunner(AppSettings())
        done = Job(status=Status.DONE, frames_done=7)
        pending = Job()
        disabled = Job(enabled=False)
        with patch.object(runner, "_next"):
            runner.start([done, pending, disabled], {})
        self.assertEqual(runner._jobs, [pending])
        self.assertEqual(done.frames_done, 7)
        self.assertEqual(done.status, Status.DONE)

    def test_failed_process_start_finishes_instead_of_hanging(self):
        self.runner._video_manifest = ""
        process = Mock()
        process.readAllStandardOutput.return_value = b""
        process.errorString.return_value = "Cannot launch Blender"
        self.runner._process = process
        self.runner._on_process_error(QProcess.FailedToStart)
        self.assertFalse(self.runner.running)
        self.assertEqual(self.job.status, Status.FAILED)
        self.assertEqual(self.results, [False])

    def test_retry_preserves_original_queue_index_in_output_tokens(self):
        blend = Path(self.temp.name) / "fixture.blend"
        blend.write_bytes(b"fixture")
        done = Job(status=Status.DONE)
        pending = Job(blend_path=str(blend), use_overrides=True)
        pending.group("output").enabled = True
        pending.group("output").values = {"file_prefix": "{index}"}
        runner = QueueRunner(AppSettings())
        with patch.object(runner, "_launch"):
            runner.start([done, pending], {pending.id: str(blend)})
        with open(runner._config_file, encoding="utf-8") as stream:
            config = json.load(stream)
        self.assertEqual(config["groups"]["output"]["file_prefix"], "02")
        runner.stop()

    def test_last_buffered_video_event_is_read_before_completion(self):
        process = Mock()
        process.readAllStandardOutput.return_value = b'BQ>>{"e":"video_done","path":"movie.mp4","partial":false}\n'
        self.runner._process = process
        self.runner._on_process_finished(0, QProcess.NormalExit)
        self.assertEqual(self.job.status, Status.DONE)
        self.assertEqual(self.job.last_output, "movie.mp4")
        self.assertEqual(self.prompts, [])


class WindowControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.patches = [patch.object(MainWindow, "_first_run"),
                        patch("blenderqueue.store.load_settings", return_value=AppSettings()),
                        patch("blenderqueue.store.save_settings"),
                        patch.object(MainWindow, "autosave")]
        for item in self.patches:
            item.start()
        self.window = MainWindow()

    def tearDown(self):
        self.window.runner._current = None
        self.window.deleteLater()
        self.app.processEvents()
        for item in reversed(self.patches):
            item.stop()

    def test_reset_preserves_settings_and_only_resets_selected_jobs(self):
        selected = Job(status=Status.FAILED, frames_done=12, frames_total=100,
                       message="Error", enabled=False, started_at=1, finished_at=2,
                       use_overrides=True, visibility_enabled=True,
                       visibility={"Scene": {"objects": {"Cube": {"hide_render": True}}}},
                       video_manifest="retained/manifest.json")
        selected.group("engine").values = {"cycles_samples": 64}
        selected.group("engine").enabled = True
        untouched = Job(status=Status.DONE, frames_done=10)
        active = Job(status=Status.ENCODING, frames_done=4)
        before = copy.deepcopy(selected.to_dict())
        self.window.jobs = [selected, untouched, active]
        with patch.object(self.window, "selected_jobs", return_value=[selected, active]):
            self.window.reset_selected()
        self.assertEqual(selected.status, Status.PENDING)
        self.assertEqual(selected.frames_done, 0)
        self.assertEqual(selected.frames_total, 0)
        self.assertEqual(selected.message, "")
        self.assertTrue(selected.enabled)
        after = selected.to_dict()
        before["enabled"] = True
        self.assertEqual(before, after)
        self.assertEqual(untouched.status, Status.DONE)
        self.assertEqual(active.status, Status.ENCODING)

    def test_recovery_prompt_passes_encode_and_keep_choices_to_runner(self):
        job = Job()
        self.window.jobs = [job]
        for choice in (True, False):
            with patch.object(self.window, "_ask_encode_frames", return_value=choice), patch.object(self.window.runner, "resolve_recovery") as resolve:
                self.window._on_recovery_available(job.id, 4, "frames")
                resolve.assert_called_once_with(choice)

    def test_close_waits_for_stop_and_optional_encoding(self):
        job = Job(status=Status.RUNNING)
        self.window.jobs = [job]
        self.window.runner._current = job
        event = QCloseEvent()
        with patch("blenderqueue.ui.main_window.QMessageBox.question", return_value=QMessageBox.Yes), patch.object(self.window.runner, "stop") as stop:
            self.window.closeEvent(event)
        self.assertFalse(event.isAccepted())
        self.assertTrue(self.window._close_after_run)
        stop.assert_called_once()
        self.window.runner._current = None
        with patch.object(self.window, "close") as close:
            self.window._on_queue_finished(False)
            self.app.processEvents()
            close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
