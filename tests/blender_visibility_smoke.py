"""Real Blender integration test; writes only generated fixtures under --out.

blender -b --factory-startup --python-exit-code 1 --python tests/blender_visibility_smoke.py -- --out build/visibility-smoke
"""

import json
from pathlib import Path
import runpy
import sys

import bpy

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "blenderqueue" / "scripts"))

from blenderqueue.models import Job
from bq_visibility import apply_visibility, datablock_key, describe_visibility, path_key


def main():
    output = Path(sys.argv[sys.argv.index("--out") + 1]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    scene = bpy.context.scene
    scene.name = "Visibility Test"
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    scene.cycles.device = "CPU"
    scene.render.resolution_x = scene.render.resolution_y = 48
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = True
    scene.frame_start = scene.frame_end = 1
    scene.view_settings.view_transform = "Standard"

    def collection(name, parent):
        block = bpy.data.collections.new(name)
        parent.children.link(block)
        return block

    set_a = collection("Set A", scene.collection)
    red_collection = collection("Red Props", set_a)
    set_b = collection("Set B", scene.collection)
    shared = collection("Shared", set_a)
    set_b.children.link(shared)

    def cube(name, x, color, owner):
        bpy.ops.mesh.primitive_cube_add(size=1.5, location=(x, 0, 0))
        obj = bpy.context.object
        obj.name = name
        for current in list(obj.users_collection):
            current.objects.unlink(obj)
        owner.objects.link(obj)
        material = bpy.data.materials.new(name)
        material.use_nodes = True
        material.node_tree.nodes.clear()
        emission = material.node_tree.nodes.new("ShaderNodeEmission")
        emission.inputs["Color"].default_value = (*color, 1)
        out = material.node_tree.nodes.new("ShaderNodeOutputMaterial")
        material.node_tree.links.new(emission.outputs[0], out.inputs["Surface"])
        obj.data.materials.append(material)
        return obj

    red = cube("Red Cube", -1, (1, 0, 0), red_collection)
    green = cube("Green Cube", 1, (0, 1, 0), set_b)
    camera_data = bpy.data.cameras.new("Camera")
    camera = bpy.data.objects.new("Camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0, 0, 8)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 5
    scene.camera = camera
    second = scene.view_layers.new("Other Layer")
    second.use = False
    layer_name = scene.view_layers[0].name
    a_path = path_key([datablock_key(set_a), datablock_key(shared)])
    b_path = path_key([datablock_key(set_b), datablock_key(shared)])
    snapshot = describe_visibility(scene)
    assert a_path in snapshot["view_layers"][0]["collections"]
    assert b_path in snapshot["view_layers"][0]["collections"]
    events = []
    apply_visibility(scene, {"view_layers": {layer_name: {"collections": {
        a_path: {"exclude": True}, b_path: {"holdout": True, "indirect_only": True},
    }}}}, lambda event, **payload: events.append((event, payload)))
    actual = describe_visibility(scene)["view_layers"][0]["collections"]
    assert actual[a_path]["exclude"] is True
    assert actual[b_path]["exclude"] is False
    assert actual[b_path]["holdout"] is True
    assert actual[b_path]["indirect_only"] is True
    apply_visibility(scene, {"view_layers": {layer_name: {"collections": {
        a_path: {"exclude": False}, b_path: {"holdout": False, "indirect_only": False},
    }}}}, lambda *a, **k: None)
    apply_visibility(scene, {"objects": {"missing": {"hide_render": True}}},
                     lambda event, **payload: events.append((event, payload)))
    assert any(event == "skip" for event, _ in events)

    fixture = output / "fixture.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(fixture))
    scene_name = scene.name
    red_key, green_key = datablock_key(red_collection), datablock_key(green)
    set_b_key = datablock_key(set_b)

    def script(name, arguments):
        old_argv = sys.argv
        try:
            sys.argv = [name, "--"] + arguments
            runpy.run_path(str(ROOT / "blenderqueue" / "scripts" / name), run_name="__main__")
        finally:
            sys.argv = old_argv

    inspected = output / "inspection.json"
    script("bq_inspect.py", ["--out", str(inspected)])
    info = json.loads(inspected.read_text(encoding="utf-8"))
    assert info["ok"] and info["scenes"][0]["visibility"]["objects"]

    cases = {
        "baseline": ({}, True, True),
        "hide-collection": ({"collections": {red_key: {"hide_render": True}}}, False, True),
        "hide-object": ({"objects": {green_key: {"hide_render": True}}}, True, False),
        "exclude-layer": ({"view_layers": {layer_name: {"collections": {
            path_key([set_b_key]): {"exclude": True}}}}}, True, False),
        "animated-show": ({"objects": {green_key: {"hide_render": False}}}, True, True),
        "animated-hide": ({"objects": {green_key: {"hide_render": True}}}, True, False),
    }
    results = {}
    for label, (overrides, expect_red, expect_green) in cases.items():
        bpy.ops.wm.open_mainfile(filepath=str(fixture))
        if label.startswith("animated-"):
            animated = bpy.data.objects["Green Cube"]
            animated.hide_render = label == "animated-show"
            animated.keyframe_insert(data_path="hide_render", frame=1)
            animated.keyframe_insert(data_path="hide_render", frame=2)
            bpy.context.scene.frame_end = 2
        job = Job(blend_path=str(fixture), name=label, info=info,
                  visibility_enabled=True, visibility={scene_name: overrides})
        job.use_overrides = True
        job.group("output").enabled = True
        job.group("output").values = {"output_dir": str(output), "file_prefix": label + "-"}
        config_path = output / (label + ".json")
        config_path.write_text(json.dumps(job.render_config()), encoding="utf-8")
        script("bq_render.py", ["--config", str(config_path)])
        for frame in range(1, bpy.context.scene.frame_end + 1):
            picture = bpy.data.images.load(str(output / (label + f"-{frame:04d}.png")))
            pixels = list(picture.pixels)
            red_pixels = sum(pixels[i] > 0.5 and pixels[i + 1] < 0.1 and pixels[i + 3] > 0.5
                             for i in range(0, len(pixels), 4))
            green_pixels = sum(pixels[i + 1] > 0.5 and pixels[i] < 0.1 and pixels[i + 3] > 0.5
                               for i in range(0, len(pixels), 4))
            assert (red_pixels > 20) == expect_red, (label, frame, red_pixels)
            assert (green_pixels > 20) == expect_green, (label, frame, green_pixels)
            results[f"{label}:{frame}"] = {"red_pixels": red_pixels, "green_pixels": green_pixels}

    bpy.ops.wm.open_mainfile(filepath=str(fixture))
    assert not bpy.data.collections["Red Props"].hide_render
    assert not bpy.data.objects["Green Cube"].hide_render
    assert not bpy.context.scene.view_layers[0].layer_collection.children["Set B"].exclude
    (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print("VISIBILITY_SMOKE_OK", json.dumps(results), flush=True)


if __name__ == "__main__":
    main()
