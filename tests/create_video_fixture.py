"""Create the small self-contained scene used by run_video_smoke.py."""

from pathlib import Path
import math
import struct
import sys
import wave

import bpy

folder = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = 8
scene.cycles.use_denoising = False
scene.render.resolution_x = scene.render.resolution_y = 64
scene.render.resolution_percentage = 100
scene.render.fps = 12
scene.frame_start = 1
scene.frame_end = 40
if hasattr(scene.render.image_settings, "media_type"):
    scene.render.image_settings.media_type = "VIDEO"
scene.render.image_settings.file_format = "FFMPEG"
scene.render.ffmpeg.format = "MPEG4"
scene.render.ffmpeg.codec = "H264"
scene.render.ffmpeg.constant_rate_factor = "HIGH"
scene.render.ffmpeg.audio_codec = "AAC"
scene.render.filepath = str(folder / "movie-")
scene.view_settings.exposure = 0.75
audio = folder / "tone.wav"
with wave.open(str(audio), "wb") as stream:
    stream.setnchannels(1)
    stream.setsampwidth(2)
    stream.setframerate(48000)
    stream.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i * 2 * math.pi * 440 / 48000)))
                               for i in range(4 * 48000)))
editor = scene.sequence_editor_create()
strips = getattr(editor, "strips", None)
if strips is None:
    strips = editor.sequences
strips.new_sound("Tone", str(audio), channel=1, frame_start=1)
bpy.ops.wm.save_as_mainfile(filepath=str(folder / "video.blend"))
scene.frame_end = 1
scene.render.filepath = str(folder / "reference-")
bpy.ops.render.render(animation=True)
