"""Exercise real stop/recovery and encoding using QProcess plus Blender/ffprobe.

python tests/run_video_smoke.py --blender "C:/.../blender.exe" --out build/video-smoke
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QTimer

from blenderqueue.models import Job, Status
from blenderqueue.runner import QueueRunner
from blenderqueue.scripts.bq_video import read_cache
from blenderqueue.store import AppSettings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--blender", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    folder = Path(args.out).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "fixture.log").open("w", encoding="utf-8") as log:
        subprocess.run([args.blender, "-b", "--factory-startup", "--python-exit-code", "1",
                        "--python", str(ROOT / "tests" / "create_video_fixture.py"),
                        "--", "--out", str(folder)], check=True, stdout=log, stderr=log, timeout=120)
    app = QCoreApplication([])
    results = {}
    for mode in ("complete", "step", "encode", "keep", "crash", "skip", "stop-encoding"):
        job = Job(name=mode, blend_path=str(folder / "video.blend"), use_overrides=True)
        job.group("output").enabled = True
        job.group("output").values = {"output_dir": str(folder), "file_prefix": mode + "-"}
        if mode in ("complete", "step"):
            job.group("frames").enabled = True
            job.group("frames").values = ({"frame_start": 5, "frame_end": 9, "frame_step": 2}
                                          if mode == "step" else
                                          {"frame_start": 1, "frame_end": 3, "frame_step": 1})
        runner = QueueRunner(AppSettings())
        lines, prompts, outcomes = [], [], []
        stopped = [False]
        runner.log.connect(lambda _, line: lines.append(line))

        def progress(_):
            ready = job.status == Status.ENCODING if mode == "stop-encoding" else job.frames_done >= 2
            if mode not in ("complete", "step") and ready and not stopped[0]:
                stopped[0] = True
                if mode == "crash":
                    runner._process.kill()
                elif mode == "skip":
                    runner.skip()
                else:
                    runner.stop()

        def recover(_job, count, directory):
            prompts.append((count, directory))
            runner.resolve_recovery(mode not in ("keep", "stop-encoding"))

        def finished(completed):
            outcomes.append(completed)
            app.quit()

        runner.jobProgress.connect(progress)
        runner.recoveryAvailable.connect(recover)
        runner.queueFinished.connect(finished)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(app.quit)
        timer.start(120000)
        runner.start([job], {job.id: args.blender})
        app.exec()
        timer.stop()
        (folder / (mode + ".log")).write_text("\n".join(lines), encoding="utf-8")
        assert outcomes, (mode, "timed out", lines[-8:])
        if mode in ("complete", "step"):
            assert job.status == Status.DONE and outcomes == [True] and not prompts, (mode, job.message, lines[-8:])
            assert not job.video_manifest
        else:
            assert len(prompts) == 1 and 0 < prompts[0][0] <= 40, (mode, job.message, prompts, lines[-8:])
            expected = Status.FAILED if mode == "crash" else Status.SKIPPED if mode == "skip" else Status.CANCELLED
            assert job.status == expected, job.message
            assert outcomes == [mode == "skip"]
            _, frames = read_cache(job.video_manifest)
            assert len(frames) == prompts[0][0]
        if mode in ("keep", "stop-encoding"):
            assert not job.last_output and not list(folder.glob(mode + "-*.mp4"))
        else:
            path = Path(job.last_output)
            assert path.is_file(), (mode, job.message, lines[-8:])
            probe = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(path)]))
            video = next(stream for stream in probe["streams"] if stream["codec_type"] == "video")
            assert int(video["nb_read_frames"]) == job.frames_done, (mode, video, job.frames_done)
            assert any(stream["codec_type"] == "audio" for stream in probe["streams"]), probe
            subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
                           check=True, capture_output=True, timeout=30)
            if mode == "complete":
                def pixels(path):
                    return subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(path),
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
                reference = pixels(next(folder.glob("reference-*.mp4")))
                actual = pixels(path)
                difference = sum(abs(a - b) for a, b in zip(reference, actual)) / len(actual)
                assert difference < 3, ("Video color changed", difference)
        results[mode] = {"status": job.status, "frames": job.frames_done, "output": job.last_output}
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
