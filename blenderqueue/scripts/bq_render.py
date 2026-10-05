"""Runs *inside* Blender to apply a job's overrides and render it.

    blender -b file.blend --factory-startup --python bq_render.py -- --config job.json

Progress is reported on stdout as single-line JSON prefixed with ``BQ>>`` so the
host application can follow along without parsing Blender's own log format.

Nothing in here may import from the BlenderQueue package: it runs under
Blender's own interpreter.
"""

import json
import os
import sys
import traceback

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bq_visibility import apply_visibility
from bq_video import encode_video, prepare_video, record_frame, set_file_format

MARKER = "BQ>>"


def emit(event, **payload):
    payload["e"] = event
    print(MARKER + json.dumps(payload), flush=True)


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    args = argv_after_ddash()
    flag = "--" + name
    return args[args.index(flag) + 1] if flag in args else default


# --------------------------------------------------------------------------
# add-ons / devices
# --------------------------------------------------------------------------

def enable_cycles():
    try:
        bpy.ops.preferences.addon_enable(module="cycles")
        return True
    except Exception as exc:
        emit("warn", msg="Could not enable Cycles: %s" % exc)
        return False


def configure_gpu(scene):
    """Point Cycles at real GPU devices; without this 'GPU' silently uses CPU."""
    try:
        prefs = bpy.context.preferences.addons["cycles"].preferences
    except Exception as exc:
        emit("warn", msg="Cycles preferences unavailable: %s" % exc)
        return

    chosen = None
    for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        try:
            prefs.compute_device_type = backend
        except Exception:
            continue
        try:
            prefs.get_devices()
        except Exception:
            pass
        usable = [d for d in getattr(prefs, "devices", []) if d.type == backend]
        if usable:
            chosen = backend
            for device in prefs.devices:
                device.use = device.type in (backend, "CPU")
            break

    if chosen:
        emit("info", msg="Cycles GPU backend: %s (%d device(s))"
             % (chosen, len([d for d in prefs.devices if d.type == chosen])))
        scene.cycles.device = "GPU"
    else:
        emit("warn", msg="No GPU compute device found - falling back to CPU")
        scene.cycles.device = "CPU"


# --------------------------------------------------------------------------
# applying overrides
# --------------------------------------------------------------------------

def assign_path(scene, path, value):
    """Set 'render.image_settings.file_format' on a scene."""
    owner = scene
    parts = path.split(".")
    for part in parts[:-1]:
        owner = getattr(owner, part)
    setattr(owner, parts[-1], value)


def apply_simple(scene, key, path, value):
    try:
        if path == "render.image_settings.file_format":
            set_file_format(scene.render.image_settings, value)
        else:
            assign_path(scene, path, value)
        return True
    except Exception as exc:
        emit("skip", key=key, msg="%s: %s" % (type(exc).__name__, exc))
        return False


def apply_specials(scene, values, config):
    """Handle every schema entry whose path starts with '@'."""
    # --- camera / world -------------------------------------------------
    if values.get("camera"):
        obj = bpy.data.objects.get(values["camera"])
        if obj and obj.type == "CAMERA":
            scene.camera = obj
        else:
            emit("skip", key="camera", msg="No camera object named %r" % values["camera"])

    if values.get("world"):
        world = bpy.data.worlds.get(values["world"])
        if world:
            scene.world = world
        else:
            emit("skip", key="world", msg="No world named %r" % values["world"])

    # --- view layers ----------------------------------------------------
    if values.get("use_single_view_layer") and values.get("view_layer"):
        wanted = values["view_layer"]
        names = [vl.name for vl in scene.view_layers]
        if wanted in names:
            for layer in scene.view_layers:
                layer.use = layer.name == wanted
        else:
            emit("skip", key="view_layer", msg="No view layer named %r" % wanted)

    # --- output path ----------------------------------------------------
    if "output_dir" in values or "file_prefix" in values:
        current = bpy.path.abspath(scene.render.filepath)
        cur_dir, cur_prefix = os.path.split(current)
        directory = values.get("output_dir") or cur_dir
        prefix = values.get("file_prefix", cur_prefix)
        if directory:
            try:
                os.makedirs(directory, exist_ok=True)
            except Exception as exc:
                emit("warn", msg="Could not create output folder: %s" % exc)
        scene.render.filepath = os.path.join(directory, prefix)

    # --- cycles device --------------------------------------------------
    if values.get("cycles_device"):
        if values["cycles_device"] == "GPU":
            configure_gpu(scene)
        else:
            try:
                scene.cycles.device = "CPU"
            except Exception:
                pass

    # --- frame mode -----------------------------------------------------
    if values.get("frame_mode") == "STILL":
        frame = int(values.get("frame_current", scene.frame_current))
        scene.frame_start = scene.frame_end = frame
        scene.frame_step = 1


def apply_groups(scene, config):
    """Apply every enabled group, engine first so engine-specific props exist."""
    groups = config.get("groups", {})
    paths = config.get("paths", {})
    order = ["scene", "engine", "frames", "dimensions", "output",
             "performance", "color", "stamp"]
    ordered = [k for k in order if k in groups] + [k for k in groups if k not in order]

    merged = {}
    for group_key in ordered:
        values = groups[group_key] or {}
        merged.update(values)
        for key, value in values.items():
            path = paths.get(key)
            if not path or path.startswith("@"):
                continue
            apply_simple(scene, key, path, value)
        emit("group", group=group_key, count=len(values))

    apply_specials(scene, merged, config)
    return merged


# --------------------------------------------------------------------------
# follow path retargeting
# --------------------------------------------------------------------------

FOLLOW_FIELDS = ("use_curve_follow", "use_fixed_location", "forward_axis",
                 "up_axis", "offset", "offset_factor", "influence", "mute")


def find_constraint(spec):
    obj = bpy.data.objects.get(spec.get("object", ""))
    if obj is None:
        return None, "No object named %r" % spec.get("object")
    holder = obj
    bone_name = spec.get("bone") or ""
    if bone_name:
        if not obj.pose or bone_name not in obj.pose.bones:
            return None, "No pose bone %r on %r" % (bone_name, obj.name)
        holder = obj.pose.bones[bone_name]
    con = holder.constraints.get(spec.get("constraint", ""))
    if con is None:
        return None, "No constraint %r on %r" % (spec.get("constraint"), obj.name)
    if con.type != "FOLLOW_PATH":
        return None, "%r is not a Follow Path constraint" % con.name
    return con, None


def apply_follow_paths(config):
    specs = config.get("follow_paths") or []
    for spec in specs:
        con, error = find_constraint(spec)
        if con is None:
            emit("skip", key="follow_path", msg=error)
            continue

        target_name = spec.get("target")
        if target_name:
            target = bpy.data.objects.get(target_name)
            if target is None:
                emit("skip", key="follow_path",
                     msg="No target object named %r" % target_name)
            elif target.type != "CURVE":
                emit("skip", key="follow_path",
                     msg="Target %r is a %s, not a curve" % (target_name, target.type))
            else:
                con.target = target
                emit("retarget", object=spec.get("object"), bone=spec.get("bone", ""),
                     constraint=con.name, target=target_name)

        for field in FOLLOW_FIELDS:
            if field in spec and spec[field] is not None:
                try:
                    setattr(con, field, spec[field])
                except Exception as exc:
                    emit("skip", key="follow_path.%s" % field, msg=str(exc))

    for spec in config.get("curve_modifiers") or []:
        obj = bpy.data.objects.get(spec.get("object", ""))
        if obj is None:
            continue
        mod = obj.modifiers.get(spec.get("modifier", ""))
        if mod is None or mod.type != "CURVE":
            continue
        target_name = spec.get("target")
        if target_name:
            target = bpy.data.objects.get(target_name)
            if target is not None and target.type == "CURVE":
                mod.object = target
                emit("retarget", object=obj.name, modifier=mod.name, target=target_name)


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------

class Progress:
    """Authoritative frame events, straight from Blender's render handlers."""

    def __init__(self, scene, video_manifest=""):
        self.scene = scene
        self.video_manifest = video_manifest
        self.written = 0
        self.cancelled = False

    def install(self):
        h = bpy.app.handlers
        h.render_pre.append(self.on_pre)
        h.render_post.append(self.on_post)
        h.render_write.append(self.on_write)
        h.render_cancel.append(self.on_cancel)

    def uninstall(self):
        h = bpy.app.handlers
        for handlers, callback in ((h.render_pre, self.on_pre), (h.render_post, self.on_post),
                                   (h.render_write, self.on_write), (h.render_cancel, self.on_cancel)):
            if callback in handlers:
                handlers.remove(callback)

    def on_pre(self, scene, *_):
        emit("pre", frame=scene.frame_current)

    def on_post(self, scene, *_):
        emit("post", frame=scene.frame_current)

    def on_write(self, scene, *_):
        if scene != self.scene:
            return
        self.written += 1
        try:
            path = scene.render.frame_path(frame=scene.frame_current)
        except Exception:
            path = scene.render.filepath
        if self.video_manifest:
            record_frame(self.video_manifest, scene.frame_current, path)
        emit("write", frame=scene.frame_current, path=path, written=self.written,
             cached=bool(self.video_manifest))

    def on_cancel(self, scene, *_):
        self.cancelled = True
        emit("cancel", frame=scene.frame_current)


def resolve_scene(config):
    wanted = (config.get("groups", {}).get("scene") or {}).get("scene")
    if wanted and wanted in bpy.data.scenes:
        scene = bpy.data.scenes[wanted]
    else:
        if wanted:
            emit("skip", key="scene", msg="No scene named %r - using active" % wanted)
        scene = bpy.context.scene
    bpy.context.window.scene = scene if bpy.context.window else scene
    return scene


def main():
    config_file = arg("config")
    with open(config_file, "r", encoding="utf-8") as fh:
        config = json.load(fh)

    if config.get("enable_cycles", True):
        enable_cycles()

    scene = resolve_scene(config)
    apply_groups(scene, config)
    apply_follow_paths(config)
    apply_visibility(scene, config.get("visibility", {}).get(scene.name, {}), emit)

    total = 0
    if scene.frame_step > 0:
        total = len(range(scene.frame_start, scene.frame_end + 1, scene.frame_step))

    emit("start",
         scene=scene.name,
         engine=scene.render.engine,
         frame_start=scene.frame_start,
         frame_end=scene.frame_end,
         frame_step=scene.frame_step,
         total=total,
         output=bpy.path.abspath(scene.render.filepath),
         file_format=scene.render.image_settings.file_format,
         resolution=[scene.render.resolution_x, scene.render.resolution_y,
                     scene.render.resolution_percentage])

    if config.get("dry_run"):
        emit("done", rendered=0, dry_run=True)
        return

    video_manifest = prepare_video(scene, config, emit)
    progress = Progress(scene, video_manifest)
    progress.install()
    try:
        bpy.ops.render.render(animation=True, scene=scene.name)
    finally:
        progress.uninstall()
    if video_manifest:
        if progress.cancelled:
            raise RuntimeError("Render cancelled; complete frames are available for recovery.")
        encode_video(scene, video_manifest, partial=False, emit=emit)
    emit("done", rendered=progress.written, cancelled=progress.cancelled)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        emit("error", msg=traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)
