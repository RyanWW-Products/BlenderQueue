"""Recoverable movie rendering. Pure cache readers also run in the desktop app."""

import json
import os
import shutil
import tempfile
import uuid

FORMAT = "BlenderQueue video cache 1"


def set_file_format(settings, file_format):
    # Blender 5.x separates media type from the format enum.
    if hasattr(settings, "media_type"):
        settings.media_type = ("VIDEO" if file_format in ("FFMPEG", "AVI_RAW", "AVI_JPEG")
                               else "MULTI_LAYER_IMAGE" if file_format == "OPEN_EXR_MULTILAYER"
                               else "IMAGE")
    settings.file_format = file_format


def read_cache(manifest_path):
    with open(manifest_path, encoding="utf-8") as stream:
        manifest = json.load(stream)
    if manifest.get("format") != FORMAT:
        raise ValueError("Unknown video recovery format")
    directory = os.path.dirname(os.path.abspath(manifest_path))
    frames = []
    expected = manifest["frame_start"]
    try:
        with open(os.path.join(directory, "frames.jsonl"), encoding="utf-8") as stream:
            for line in stream:
                # A killed writer may leave an incomplete final journal entry.
                if not line.endswith("\n"):
                    break
                entry = json.loads(line)
                name = entry["file"]
                if (entry["frame"] != expected or os.path.basename(name) != name
                        or not name.endswith(".exr")):
                    break
                path = os.path.join(directory, name)
                if not os.path.isfile(path) or os.path.getsize(path) == 0:
                    break
                frames.append(entry)
                expected += manifest["frame_step"]
    except FileNotFoundError:
        pass
    return manifest, frames


def snapshot(owner):
    return {prop.identifier: getattr(owner, prop.identifier)
            for prop in owner.bl_rna.properties
            if not prop.is_readonly and prop.type in ("BOOLEAN", "INT", "FLOAT", "STRING", "ENUM")
            and not getattr(prop, "is_array", False)}


def prepare_video(scene, config, emit):
    """Keep scene-linear EXRs until a complete movie has been published."""
    import bpy

    if not scene.render.is_movie_format:
        return ""
    if scene.render.use_multiview:
        raise RuntimeError("Recovery-safe video needs single-view output. "
                           "For stereo/multiview renders, select an image sequence output.")
    final_path = bpy.path.abspath(scene.render.frame_path())
    directory = os.path.dirname(final_path)
    os.makedirs(directory, exist_ok=True)
    cache = tempfile.mkdtemp(prefix=".blenderqueue-frames-", dir=directory)
    manifest_path = os.path.join(cache, "manifest.json")
    manifest = {
        "format": FORMAT, "blend_file": bpy.data.filepath, "scene": scene.name,
        "config": config, "final_path": final_path,
        "frame_start": scene.frame_start, "frame_end": scene.frame_end,
        "frame_step": scene.frame_step,
        "fps": scene.render.fps, "fps_base": scene.render.fps_base,
        "image_settings": snapshot(scene.render.image_settings),
        "ffmpeg": snapshot(scene.render.ffmpeg),
        "audio": "audio.wav" if scene.render.ffmpeg.audio_codec != "NONE" else "",
    }
    with open(manifest_path, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream)
    emit("video_cache", manifest=manifest_path)
    if manifest["audio"]:
        result = bpy.ops.sound.mixdown(
            filepath=os.path.join(cache, manifest["audio"]), container="WAV", codec="PCM",
            format="S16", split_channels=False)
        if "FINISHED" not in result:
            raise RuntimeError("Could not prepare the scene audio for video encoding.")
    image = scene.render.image_settings
    set_file_format(image, "OPEN_EXR")
    image.color_mode = "RGBA"
    image.color_depth = "32"
    image.exr_codec = "ZIP"
    scene.render.filepath = os.path.join(cache, "frame-")
    scene.render.use_file_extension = True
    scene.render.use_overwrite = True
    scene.render.use_placeholder = False
    emit("info", msg="Saving recoverable video frames in " + cache)
    return manifest_path


def record_frame(manifest_path, frame, path):
    directory = os.path.dirname(manifest_path)
    if os.path.dirname(os.path.abspath(path)) != os.path.abspath(directory):
        raise ValueError("Rendered frame is outside its recovery directory")
    with open(os.path.join(directory, "frames.jsonl"), "a", encoding="utf-8") as stream:
        stream.write(json.dumps({"frame": frame, "file": os.path.basename(path)}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def encode_video(scene, manifest_path, partial, emit):
    """Use Blender's encoder, publishing the file only after its trailer is written."""
    import bpy

    manifest, frames = read_cache(manifest_path)
    if not frames:
        raise RuntimeError("No complete frames are available to encode.")
    expected = len(range(manifest["frame_start"], manifest["frame_end"] + 1, manifest["frame_step"]))
    if not partial and len(frames) != expected:
        raise RuntimeError("Some video frames did not finish writing; complete frames have been retained.")
    directory = os.path.dirname(os.path.abspath(manifest_path))
    first = os.path.join(directory, frames[0]["file"])
    image = bpy.data.images.load(first, check_existing=False)
    width, height = image.size
    linear_space = image.colorspace_settings.name
    bpy.data.images.remove(image)
    # Replace the source sequencer with the already composited frame sequence.
    # Scene color management remains intact; EXRs have no baked view transform.
    scene.sequence_editor_clear()
    editor = scene.sequence_editor_create()
    strips = getattr(editor, "strips", None)
    if strips is None:  # Blender before 4.4
        strips = editor.sequences
    start, end, step = frames[0]["frame"], frames[-1]["frame"], manifest["frame_step"]
    if step == 1:
        strip = strips.new_image("Rendered frames", first, channel=1, frame_start=start)
        for entry in frames[1:]:
            strip.elements.append(entry["file"])
        strip.colorspace_settings.name = linear_space
    else:
        for entry in frames:
            strip = strips.new_image("Rendered frame", os.path.join(directory, entry["file"]),
                                     channel=1, frame_start=entry["frame"])
            strip.frame_final_duration = step
            strip.colorspace_settings.name = linear_space
    scene.sequencer_colorspace_settings.name = linear_space
    if manifest["audio"]:
        audio_path = os.path.join(directory, manifest["audio"])
        if not os.path.isfile(audio_path):
            raise RuntimeError("The cached audio is missing; rendered frames have been retained.")
        audio = strips.new_sound("Scene audio", audio_path, channel=2, frame_start=start)
        audio.frame_final_end = end + 1
    scene.frame_start = start
    scene.frame_end = end
    scene.frame_step = step
    render = scene.render
    render.fps = manifest["fps"]
    render.fps_base = manifest["fps_base"]
    render.resolution_x, render.resolution_y = width, height
    render.resolution_percentage = 100
    render.use_border = False
    render.use_sequencer = True
    render.use_compositing = False
    render.use_stamp = False
    render.use_file_extension = True
    render.filepath = os.path.join(directory, "encoding-")
    # Format and codec must be restored before dependent settings (RGBA, quality).
    set_file_format(render.image_settings, manifest["image_settings"]["file_format"])
    for key in ("format", "codec"):
        setattr(render.ffmpeg, key, manifest["ffmpeg"][key])
    for key, value in manifest["ffmpeg"].items():
        setattr(render.ffmpeg, key, value)
    render.ffmpeg.use_autosplit = False
    for key in ("color_mode", "color_depth"):
        try:
            setattr(render.image_settings, key, manifest["image_settings"][key])
        except TypeError:
            pass  # Video codecs may expose only their fixed bit depth.
    staging_path = bpy.path.abspath(render.frame_path())
    final_path = manifest["final_path"]
    if partial:
        stem, extension = os.path.splitext(final_path)
        final_path = "%s-partial-%s%s" % (stem, uuid.uuid4().hex[:8], extension)
    emit("encoding", frames=len(frames), partial=partial)
    result = bpy.ops.render.render(animation=True, scene=scene.name)
    if "FINISHED" not in result or not os.path.isfile(staging_path) or os.path.getsize(staging_path) == 0:
        raise RuntimeError("Video encoding did not finish; the rendered frames were retained.")
    os.replace(staging_path, final_path)
    emit("video_done", path=final_path, frames=len(frames), partial=partial)
    if not partial:
        # This directory was created solely for this run, beside the final video.
        # Refuse cleanup for an unexpected path instead of deleting arbitrary data.
        if (os.path.basename(directory).startswith(".blenderqueue-frames-")
                and os.path.dirname(directory) == os.path.dirname(os.path.abspath(final_path))):
            try:
                shutil.rmtree(directory)
            except OSError as exc:
                emit("warn", msg="Video saved; could not remove cached frames: %s" % exc)
    return final_path
