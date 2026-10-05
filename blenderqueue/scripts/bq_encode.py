"""Encode completed recovery frames using Blender, without rendering the scene again."""

import os
import sys
import traceback

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bq_render import apply_groups, arg, emit
from bq_video import encode_video, read_cache


if __name__ == "__main__":
    try:
        path = arg("manifest")
        manifest, _ = read_cache(path)
        scene = bpy.data.scenes.get(manifest["scene"])
        if scene is None:
            raise RuntimeError("The original render scene is no longer in the Blender file.")
        if bpy.context.window:
            bpy.context.window.scene = scene
        apply_groups(scene, manifest["config"])
        encode_video(scene, path, partial=True, emit=emit)
    except Exception:
        emit("error", msg=traceback.format_exc())
        traceback.print_exc()
        sys.exit(1)
