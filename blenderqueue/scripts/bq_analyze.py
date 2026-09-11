"""Runs *inside* Blender to measure everything that makes a render expensive.

    blender -b file.blend --factory-startup --python bq_analyze.py -- --out report.json

This only *collects* numbers.  Turning them into loads, ratings and suggestions
happens back in the application (``blenderqueue/analysis.py``) so the scoring
can be changed without re-reading every .blend.

Each section is guarded independently: a scene that upsets one collector still
produces a usable report for everything else.

Nothing in here may import from the BlenderQueue package: it runs under
Blender's own interpreter.
"""

import json
import os
import sys
import traceback

import bpy

# Modifiers that multiply how much geometry actually reaches the renderer.
# Values are (multiplier, note) resolved per modifier instance.
SUBDIV_TYPES = {"SUBSURF", "MULTIRES"}

EXPENSIVE_NODES = {
    "BSDF_GLASS": "glass",
    "BSDF_REFRACTION": "refraction",
    "BSDF_TRANSPARENT": "transparency",
    "SUBSURFACE_SCATTERING": "subsurface",
    "VOLUME_SCATTER": "volume scatter",
    "VOLUME_ABSORPTION": "volume absorption",
    "PRINCIPLED_VOLUME": "principled volume",
    "BSDF_HAIR": "hair",
    "BSDF_HAIR_PRINCIPLED": "principled hair",
    "TEX_MUSGRAVE": "musgrave texture",
    "TEX_NOISE": "noise texture",
    "TEX_VORONOI": "voronoi texture",
    "TEX_WAVE": "wave texture",
    "DISPLACEMENT": "displacement",
    "VECTOR_DISPLACEMENT": "vector displacement",
}

HEAVY_COMPOSITOR = {
    "DENOISE": "denoise",
    "GLARE": "glare",
    "BLUR": "blur",
    "DEFOCUS": "defocus",
    "BOKEHBLUR": "bokeh blur",
    "VECBLUR": "vector blur",
    "DILATEERODE": "dilate/erode",
}


def argv_after_ddash():
    return sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []


def arg(name, default=None):
    args = argv_after_ddash()
    flag = "--" + name
    return args[args.index(flag) + 1] if flag in args else default


def enable_cycles():
    try:
        bpy.ops.preferences.addon_enable(module="cycles")
    except Exception:
        pass


def safe(section, func, fallback):
    """Run one collector, and record the failure rather than losing the report."""
    try:
        return func()
    except Exception:
        return {"error": traceback.format_exc(limit=3), **fallback}


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------

def mesh_triangles(mesh):
    """Triangle count without walking every polygon in Python.

    An n-gon becomes n-2 triangles, and the loop count is the sum of every
    polygon's vertex count, so this is exact and O(1).
    """
    try:
        return max(0, len(mesh.loops) - 2 * len(mesh.polygons))
    except Exception:
        return 0


def modifier_multiplier(obj):
    """How much the render-time modifier stack inflates the base geometry."""
    multiplier = 1.0
    notes = []
    for mod in getattr(obj, "modifiers", []):
        if not mod.show_render:
            continue
        kind = mod.type
        if kind in SUBDIV_TYPES:
            levels = int(getattr(mod, "render_levels", 0) or 0)
            if levels > 0:
                multiplier *= 4.0 ** levels
                notes.append("%s render level %d" % (kind.lower(), levels))
        elif kind == "MIRROR":
            axes = sum(1 for use in getattr(mod, "use_axis", [False] * 3) if use)
            if axes:
                multiplier *= 2.0 ** axes
                notes.append("mirror x%d" % (2 ** axes))
        elif kind == "ARRAY":
            count = int(getattr(mod, "count", 1) or 1)
            if count > 1:
                multiplier *= count
                notes.append("array x%d" % count)
        elif kind == "SOLIDIFY":
            multiplier *= 2.0
            notes.append("solidify")
        elif kind == "SCREW":
            steps = int(getattr(mod, "render_steps", 1) or 1)
            if steps > 1:
                multiplier *= steps
                notes.append("screw x%d" % steps)
        elif kind == "DECIMATE":
            ratio = float(getattr(mod, "ratio", 1.0) or 1.0)
            multiplier *= max(0.01, ratio)
            notes.append("decimate %.2f" % ratio)
        elif kind in ("REMESH", "NODES", "SUBDIVIDE"):
            notes.append(kind.lower() + " (size not predictable)")
    return multiplier, notes


def collect_geometry(scene):
    items = []
    base_total = 0
    render_total = 0
    rendered = 0

    for obj in scene.objects:
        if obj.type != "MESH" or obj.data is None:
            continue
        hidden = bool(obj.hide_render)
        base = mesh_triangles(obj.data)
        multiplier, notes = modifier_multiplier(obj)
        render_tris = int(base * multiplier)
        base_total += 0 if hidden else base
        if not hidden:
            render_total += render_tris
            rendered += 1
        items.append({
            "name": obj.name,
            "base_tris": base,
            "render_tris": render_tris,
            "multiplier": round(multiplier, 3),
            "modifiers": notes,
            "hide_render": hidden,
            "data_users": obj.data.users,
        })

    items.sort(key=lambda e: e["render_tris"], reverse=True)
    return {
        "objects_total": len(scene.objects),
        "mesh_objects": len(items),
        "rendered_mesh_objects": rendered,
        "base_tris": base_total,
        "render_tris": render_total,
        "items": items[:40],
        "curves": sum(1 for o in scene.objects if o.type == "CURVE"),
        "instancers": sum(1 for o in scene.objects if o.is_instancer),
    }


# --------------------------------------------------------------------------
# textures
# --------------------------------------------------------------------------

def collect_textures():
    images = []
    total = 0
    missing = 0
    for img in bpy.data.images:
        if img.source in ("VIEWER", "GENERATED") and img.name in ("Render Result", "Viewer Node"):
            continue
        try:
            width, height = int(img.size[0]), int(img.size[1])
        except Exception:
            width = height = 0
        depth = int(getattr(img, "depth", 32) or 32)
        # depth is bits per pixel across all channels; mipmaps add roughly a third
        nbytes = int(width * height * (depth / 8.0) * 1.33)
        packed = bool(img.packed_file)
        path = ""
        gone = False
        if img.source == "FILE" and not packed:
            try:
                path = bpy.path.abspath(img.filepath)
                gone = bool(path) and not os.path.exists(path)
            except Exception:
                pass
        if gone:
            missing += 1
        if img.users:
            total += nbytes
        images.append({
            "name": img.name,
            "width": width,
            "height": height,
            "depth": depth,
            "is_float": bool(getattr(img, "is_float", False)),
            "bytes": nbytes,
            "packed": packed,
            "missing": gone,
            "users": img.users,
            "source": img.source,
            "filepath": path,
        })
    images.sort(key=lambda e: e["bytes"], reverse=True)
    return {
        "count": len(images),
        "total_bytes": total,
        "missing": missing,
        "at_4k": sum(1 for i in images if max(i["width"], i["height"]) >= 4096),
        "at_8k": sum(1 for i in images if max(i["width"], i["height"]) >= 8192),
        "float_images": sum(1 for i in images if i["is_float"] and i["users"]),
        "items": images[:30],
    }


# --------------------------------------------------------------------------
# lighting and world
# --------------------------------------------------------------------------

def world_info(scene):
    world = scene.world
    if world is None:
        return {"name": "", "env_image": "", "env_width": 0, "env_height": 0,
                "strength": 0.0, "has_volume": False}
    info = {"name": world.name, "env_image": "", "env_width": 0, "env_height": 0,
            "strength": 0.0, "has_volume": False}
    if world.use_nodes and world.node_tree:
        for node in world.node_tree.nodes:
            if node.type == "TEX_ENVIRONMENT" and getattr(node, "image", None):
                info["env_image"] = node.image.name
                try:
                    info["env_width"] = int(node.image.size[0])
                    info["env_height"] = int(node.image.size[1])
                except Exception:
                    pass
            elif node.type == "BACKGROUND":
                try:
                    info["strength"] = float(node.inputs["Strength"].default_value)
                except Exception:
                    pass
            elif node.type in ("VOLUME_SCATTER", "VOLUME_ABSORPTION", "PRINCIPLED_VOLUME"):
                info["has_volume"] = True
    return info


def collect_lights(scene):
    items = []
    for obj in scene.objects:
        if obj.type != "LIGHT" or obj.data is None:
            continue
        light = obj.data
        size = 0.0
        if light.type == "AREA":
            size = float(max(getattr(light, "size", 0.0), getattr(light, "size_y", 0.0)))
        else:
            size = float(getattr(light, "shadow_soft_size", 0.0))
        items.append({
            "name": obj.name,
            "type": light.type,
            "energy": float(getattr(light, "energy", 0.0)),
            "size": round(size, 4),
            "hide_render": bool(obj.hide_render),
            "use_shadow": bool(getattr(light, "use_shadow", True)),
        })
    active = [i for i in items if not i["hide_render"]]
    return {
        "count": len(items),
        "rendered": len(active),
        "area_lights": sum(1 for i in active if i["type"] == "AREA"),
        "large_soft": sum(1 for i in active if i["size"] > 1.0),
        "items": items[:25],
        "world": world_info(scene),
    }


# --------------------------------------------------------------------------
# materials and volumes
# --------------------------------------------------------------------------

def collect_materials():
    items = []
    total_nodes = 0
    for mat in bpy.data.materials:
        if not mat.users:
            continue
        features = set()
        nodes = 0
        if mat.use_nodes and mat.node_tree:
            for node in mat.node_tree.nodes:
                nodes += 1
                label = EXPENSIVE_NODES.get(node.type)
                if label:
                    features.add(label)
                if node.type == "BSDF_PRINCIPLED":
                    for socket, tag in (("Subsurface Weight", "subsurface"),
                                        ("Transmission Weight", "transmission")):
                        inp = node.inputs.get(socket)
                        if inp is not None and not inp.is_linked:
                            try:
                                if float(inp.default_value) > 0.0:
                                    features.add(tag)
                            except Exception:
                                pass
        total_nodes += nodes
        if getattr(mat, "displacement_method", "BUMP") != "BUMP":
            features.add("true displacement")
        items.append({
            "name": mat.name,
            "nodes": nodes,
            "features": sorted(features),
            "users": mat.users,
        })
    items.sort(key=lambda e: (len(e["features"]), e["nodes"]), reverse=True)
    return {
        "count": len(items),
        "total_nodes": total_nodes,
        "items": items[:25],
    }


def collect_volumes(scene):
    items = []
    for obj in scene.objects:
        if obj.hide_render:
            continue
        if obj.type == "VOLUME":
            items.append({"name": obj.name, "kind": "volume object", "resolution": 0})
        for mod in getattr(obj, "modifiers", []):
            if mod.type == "FLUID" and getattr(mod, "fluid_type", "") == "DOMAIN":
                settings = getattr(mod, "domain_settings", None)
                res = int(getattr(settings, "resolution_max", 0) or 0) if settings else 0
                items.append({"name": obj.name, "kind": "fluid domain", "resolution": res})
    return {"count": len(items), "items": items[:20]}


def collect_particles(scene):
    items = []
    for obj in scene.objects:
        if obj.hide_render:
            continue
        for psys in getattr(obj, "particle_systems", []):
            settings = psys.settings
            children = int(getattr(settings, "rendered_child_count", 0) or 0)
            items.append({
                "object": obj.name,
                "name": psys.name,
                "type": getattr(settings, "type", ""),
                "count": int(getattr(settings, "count", 0) or 0),
                "render_children": children,
                "child_type": getattr(settings, "child_type", "NONE"),
            })
    total = sum(i["count"] + (i["render_children"] * i["count"]
                              if i["child_type"] != "NONE" else 0) for i in items)
    return {"systems": len(items), "estimated_particles": total, "items": items[:20]}


# --------------------------------------------------------------------------
# render / sampling settings
# --------------------------------------------------------------------------

def collect_render(scene):
    render = scene.render
    frames = 0
    if render.fps and scene.frame_step > 0:
        frames = len(range(scene.frame_start, scene.frame_end + 1, scene.frame_step))
    scale = render.resolution_percentage / 100.0
    return {
        "engine": render.engine,
        "resolution_x": render.resolution_x,
        "resolution_y": render.resolution_y,
        "resolution_percentage": render.resolution_percentage,
        "pixels": int(render.resolution_x * scale) * int(render.resolution_y * scale),
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_step": scene.frame_step,
        "frames": frames,
        "fps": render.fps,
        "file_format": render.image_settings.file_format,
        "color_depth": render.image_settings.color_depth,
        "film_transparent": bool(render.film_transparent),
        "use_motion_blur": bool(getattr(render, "use_motion_blur", False)),
        "motion_blur_shutter": float(getattr(render, "motion_blur_shutter", 0.5)),
        "use_simplify": bool(render.use_simplify),
        "simplify_subdivision_render": int(getattr(render, "simplify_subdivision_render", 0)),
        "use_persistent_data": bool(getattr(render, "use_persistent_data", False)),
        "threads_mode": getattr(render, "threads_mode", "AUTO"),
        "view_layers": len([vl for vl in scene.view_layers if vl.use]),
        "total_view_layers": len(scene.view_layers),
        "use_compositing": bool(render.use_compositing),
    }


def collect_sampling(scene):
    data = {"engine": scene.render.engine}
    try:
        cycles = scene.cycles
    except Exception:
        cycles = None
    if cycles is not None and scene.render.engine == "CYCLES":
        data.update({
            "samples": int(getattr(cycles, "samples", 0) or 0),
            "preview_samples": int(getattr(cycles, "preview_samples", 0) or 0),
            "use_adaptive_sampling": bool(getattr(cycles, "use_adaptive_sampling", False)),
            "adaptive_threshold": float(getattr(cycles, "adaptive_threshold", 0.0) or 0.0),
            "adaptive_min_samples": int(getattr(cycles, "adaptive_min_samples", 0) or 0),
            "time_limit": float(getattr(cycles, "time_limit", 0.0) or 0.0),
            "use_denoising": bool(getattr(cycles, "use_denoising", False)),
            "denoiser": getattr(cycles, "denoiser", ""),
            "max_bounces": int(getattr(cycles, "max_bounces", 0) or 0),
            "diffuse_bounces": int(getattr(cycles, "diffuse_bounces", 0) or 0),
            "glossy_bounces": int(getattr(cycles, "glossy_bounces", 0) or 0),
            "transmission_bounces": int(getattr(cycles, "transmission_bounces", 0) or 0),
            "volume_bounces": int(getattr(cycles, "volume_bounces", 0) or 0),
            "transparent_max_bounces": int(getattr(cycles, "transparent_max_bounces", 0) or 0),
            "caustics_reflective": bool(getattr(cycles, "caustics_reflective", False)),
            "caustics_refractive": bool(getattr(cycles, "caustics_refractive", False)),
            "sample_clamp_indirect": float(getattr(cycles, "sample_clamp_indirect", 0.0) or 0.0),
            "device": getattr(cycles, "device", "CPU"),
            "tile_size": int(getattr(cycles, "tile_size", 0) or 0),
            "use_light_tree": bool(getattr(cycles, "use_light_tree", True)),
        })
    else:
        eevee = getattr(scene, "eevee", None)
        data.update({
            "eevee_samples": int(getattr(eevee, "taa_render_samples", 0) or 0),
            "use_gtao": bool(getattr(eevee, "use_gtao", False)),
            "use_bloom": bool(getattr(eevee, "use_bloom", False)),
            "use_ssr": bool(getattr(eevee, "use_ssr", False)),
            "use_motion_blur": bool(getattr(eevee, "use_motion_blur", False)),
            "shadow_cube_size": getattr(eevee, "shadow_cube_size", ""),
            "use_raytracing": bool(getattr(eevee, "use_raytracing", False)),
        })
    return data


def collect_compositor(scene):
    if not scene.use_nodes or scene.node_tree is None:
        return {"enabled": False, "nodes": 0, "heavy": []}
    heavy = []
    count = 0
    for node in scene.node_tree.nodes:
        count += 1
        label = HEAVY_COMPOSITOR.get(node.type)
        if label:
            heavy.append(label)
    return {"enabled": True, "nodes": count, "heavy": sorted(set(heavy))}


# --------------------------------------------------------------------------

def main():
    out_file = arg("out")
    scene_name = arg("scene", "")

    enable_cycles()
    scene = bpy.data.scenes.get(scene_name) or bpy.context.scene

    report = {
        "ok": True,
        "blend_file": bpy.data.filepath,
        "blender_version": bpy.app.version_string,
        "scene": scene.name,
        "scenes": [s.name for s in bpy.data.scenes],
        "render": safe("render", lambda: collect_render(scene), {}),
        "sampling": safe("sampling", lambda: collect_sampling(scene), {}),
        "geometry": safe("geometry", lambda: collect_geometry(scene),
                         {"render_tris": 0, "items": []}),
        "textures": safe("textures", collect_textures, {"total_bytes": 0, "items": []}),
        "lights": safe("lights", lambda: collect_lights(scene), {"count": 0, "items": []}),
        "materials": safe("materials", collect_materials, {"count": 0, "items": []}),
        "volumes": safe("volumes", lambda: collect_volumes(scene), {"count": 0, "items": []}),
        "particles": safe("particles", lambda: collect_particles(scene),
                          {"systems": 0, "items": []}),
        "compositor": safe("compositor", lambda: collect_compositor(scene), {"enabled": False}),
    }

    with open(out_file, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    print("BQ_ANALYZE_OK", out_file, flush=True)


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
