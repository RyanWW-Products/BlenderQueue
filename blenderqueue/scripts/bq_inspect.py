"""Runs *inside* Blender to describe a .blend file.

    blender -b file.blend --factory-startup --python bq_inspect.py -- \
        --request request.json --out result.json

``request.json`` carries ``{"paths": {field_key: "render.resolution_x", ...}}``
generated from ``blenderqueue.schema`` so this script never has to know the
schema itself.  The result is written as JSON to ``--out``.

Nothing in here may import from the BlenderQueue package: it runs under
Blender's own interpreter.
"""

import json
import os
import sys
import traceback

import bpy


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    args = argv_after_ddash()
    flag = "--" + name
    return args[args.index(flag) + 1] if flag in args else default


def enable_cycles():
    """Cycles is a bundled add-on and is off under --factory-startup."""
    try:
        bpy.ops.preferences.addon_enable(module="cycles")
    except Exception:
        pass


def read_path(root, path):
    """Resolve 'render.image_settings.file_format' against a scene."""
    obj = root
    for part in path.split("."):
        obj = getattr(obj, part)
    return obj


def jsonable(value):
    """Blender returns its own vector/enum types; flatten them."""
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    try:
        return [jsonable(v) for v in value]
    except TypeError:
        return str(value)


def name_of(datablock):
    return datablock.name if datablock else ""


# --------------------------------------------------------------------------
# follow-path discovery
# --------------------------------------------------------------------------

def describe_follow_path(owner_name, bone_name, constraint):
    """One FOLLOW_PATH constraint, on an object or on a pose bone."""
    return {
        "object": owner_name,
        "bone": bone_name or "",
        "constraint": constraint.name,
        "target": name_of(constraint.target),
        "use_curve_follow": bool(getattr(constraint, "use_curve_follow", False)),
        "use_fixed_location": bool(getattr(constraint, "use_fixed_location", False)),
        "forward_axis": getattr(constraint, "forward_axis", "FORWARD_Y"),
        "up_axis": getattr(constraint, "up_axis", "UP_Z"),
        "offset": float(getattr(constraint, "offset", 0.0)),
        "offset_factor": float(getattr(constraint, "offset_factor", 0.0)),
        "influence": float(getattr(constraint, "influence", 1.0)),
        "mute": bool(constraint.mute),
    }


def collect_follow_paths(scene):
    """Every Follow Path constraint reachable from this scene."""
    found = []
    for obj in scene.objects:
        for con in obj.constraints:
            if con.type == "FOLLOW_PATH":
                found.append(describe_follow_path(obj.name, "", con))
        if obj.type == "ARMATURE" and obj.pose:
            for bone in obj.pose.bones:
                for con in bone.constraints:
                    if con.type == "FOLLOW_PATH":
                        found.append(describe_follow_path(obj.name, bone.name, con))
    return found


def collect_curve_modifiers(scene):
    """Curve *modifiers* also retarget along a curve; surface them too."""
    found = []
    for obj in scene.objects:
        for mod in getattr(obj, "modifiers", []):
            if mod.type == "CURVE":
                found.append({
                    "object": obj.name,
                    "modifier": mod.name,
                    "target": name_of(mod.object),
                    "deform_axis": getattr(mod, "deform_axis", "POS_X"),
                    "show_render": bool(mod.show_render),
                })
    return found


def collect_curves(scene):
    """Objects that can legally be a Follow Path target."""
    curves = []
    for obj in scene.objects:
        if obj.type != "CURVE":
            continue
        data = obj.data
        curves.append({
            "name": obj.name,
            "path_duration": int(getattr(data, "path_duration", 100)),
            "use_path": bool(getattr(data, "use_path", False)),
            "splines": len(getattr(data, "splines", [])),
        })
    return curves


# --------------------------------------------------------------------------
# scene description
# --------------------------------------------------------------------------

def describe_scene(scene, paths):
    settings = {}
    for key, path in paths.items():
        if path.startswith("@"):
            continue
        try:
            settings[key] = jsonable(read_path(scene, path))
        except Exception:
            pass  # property missing in this Blender version / engine

    # the "@" specials the UI still needs seed values for
    settings["scene"] = scene.name
    settings["camera"] = name_of(scene.camera)
    settings["world"] = name_of(scene.world)
    settings["frame_mode"] = "ANIMATION"
    settings["use_single_view_layer"] = False
    settings["view_layer"] = scene.view_layers[0].name if scene.view_layers else ""
    try:
        settings["cycles_device"] = scene.cycles.device
    except Exception:
        settings["cycles_device"] = "CPU"

    raw_output = scene.render.filepath
    abs_output = bpy.path.abspath(raw_output)
    head, tail = os.path.split(abs_output)
    settings["output_dir"] = head
    settings["file_prefix"] = tail

    return {
        "name": scene.name,
        "camera": name_of(scene.camera),
        "world": name_of(scene.world),
        "engine": scene.render.engine,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_step": scene.frame_step,
        "frame_current": scene.frame_current,
        "resolution_x": scene.render.resolution_x,
        "resolution_y": scene.render.resolution_y,
        "resolution_percentage": scene.render.resolution_percentage,
        "fps": scene.render.fps,
        "fps_base": round(scene.render.fps_base, 6),
        "file_format": scene.render.image_settings.file_format,
        "output_path": raw_output,
        "output_path_abs": abs_output,
        "cameras": sorted(o.name for o in scene.objects if o.type == "CAMERA"),
        "view_layers": [vl.name for vl in scene.view_layers],
        "curves": collect_curves(scene),
        "follow_paths": collect_follow_paths(scene),
        "curve_modifiers": collect_curve_modifiers(scene),
        "settings": settings,
    }


def main():
    out_file = arg("out")
    request_file = arg("request")
    paths = {}
    if request_file and os.path.isfile(request_file):
        with open(request_file, "r", encoding="utf-8") as fh:
            paths = json.load(fh).get("paths", {})

    enable_cycles()

    result = {
        "ok": True,
        "blend_file": bpy.data.filepath,
        "blender_version": bpy.app.version_string,
        "blender_version_tuple": list(bpy.app.version),
        "scenes": [describe_scene(sc, paths) for sc in bpy.data.scenes],
        "worlds": sorted(w.name for w in bpy.data.worlds),
        "active_scene": bpy.context.scene.name if bpy.context.scene else "",
        "markers": {},
    }

    for scene in bpy.data.scenes:
        result["markers"][scene.name] = [
            {"name": m.name, "frame": m.frame, "camera": name_of(m.camera)}
            for m in scene.timeline_markers
        ]

    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1)
    print("BQ_INSPECT_OK", out_file, flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        target = arg("out")
        if target:
            try:
                with open(target, "w", encoding="utf-8") as fh:
                    json.dump({"ok": False, "error": traceback.format_exc()}, fh)
            except Exception:
                pass
        sys.exit(1)
