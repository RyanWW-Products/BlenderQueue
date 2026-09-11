"""Turn a raw scene measurement into loads, ratings and suggestions.

``scripts/bq_analyze.py`` measures; this module judges.  Keeping the two apart
means the scoring can be retuned without re-reading every .blend.

The scale is anchored on a deliberately ordinary job -- 1920x1080, 100 frames,
128 Cycles samples -- which scores 50.  Everything is relative to that, so a
number here means "compared with a normal render", not "seconds".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# The reference render that scores 50/100.
REF_PIXELS = 1920 * 1080
REF_FRAMES = 100
REF_SAMPLES = 128
REF_WORK = REF_PIXELS * REF_FRAMES * REF_SAMPLES

# EEVEE samples cost far less than Cycles samples.
EEVEE_SAMPLE_COST = 0.15

RATINGS = (
    (25, "Light", "#5fb85f"),
    (45, "Moderate", "#9acd32"),
    (65, "Heavy", "#e0a30c"),
    (85, "Very Heavy", "#e8853b"),
    (101, "Extreme", "#d9534f"),
)

SEVERITY_ORDER = {"critical": 0, "warn": 1, "notice": 2, "info": 3}


@dataclass
class Finding:
    """One observation, with a load share and -- where useful -- what to do."""

    label: str
    value: str
    load: int = 0
    severity: str = "info"          # info | notice | warn | critical
    suggestion: str = ""


@dataclass
class Category:
    key: str
    label: str
    icon: str = "settings"
    load: int = 0
    headline: str = ""
    findings: list = field(default_factory=list)
    stats: list = field(default_factory=list)     # (label, value) pairs

    def sorted_findings(self) -> list:
        return sorted(self.findings,
                      key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), -f.load))


@dataclass
class Report:
    overall: int = 0
    rating: str = "Light"
    color: str = "#5fb85f"
    summary: str = ""
    relative: float = 1.0           # multiple of the reference render
    categories: list = field(default_factory=list)
    error: str = ""

    def category(self, key: str):
        for cat in self.categories:
            if cat.key == key:
                return cat
        return None


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def log_scale(value: float, floor: float, ceiling: float) -> float:
    """0 at or below `floor`, 1 at or above `ceiling`, log-spaced between."""
    if value <= floor:
        return 0.0
    if value >= ceiling:
        return 1.0
    return clamp01(math.log(value / floor) / math.log(ceiling / floor))


def pct(fraction: float) -> int:
    return int(round(clamp01(fraction) * 100))


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:,.0f} {unit}" if unit in ("B", "KB") else f"{n:,.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def human_count(n: float) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:,.1f} M"
    if n >= 1_000:
        return f"{n / 1_000:,.1f} K"
    return f"{n:,.0f}"


# --------------------------------------------------------------------------
# per-category scoring
# --------------------------------------------------------------------------

def _sampling(raw: dict) -> Category:
    sampling = raw.get("sampling") or {}
    engine = sampling.get("engine") or (raw.get("render") or {}).get("engine", "")
    cat = Category("sampling", "Sampling", "engine")

    if engine == "CYCLES":
        samples = int(sampling.get("samples") or 0)
        adaptive = bool(sampling.get("use_adaptive_sampling"))
        threshold = float(sampling.get("adaptive_threshold") or 0.0)
        denoise = bool(sampling.get("use_denoising"))
        time_limit = float(sampling.get("time_limit") or 0.0)

        load = log_scale(samples, 64, 4096)
        if adaptive and threshold > 0:
            load *= 0.75           # the sample count becomes a ceiling, not a cost
        cat.load = pct(load)

        suggestion = ""
        severity = "info"
        if samples >= 1500 and not (adaptive and denoise):
            severity = "warn"
            suggestion = ("Consider 256-512 samples with Adaptive Sampling and "
                          "Denoising on. Beyond a few hundred samples the noise "
                          "drops very slowly for a linear increase in time.")
        elif samples >= 800:
            severity = "notice"
            suggestion = ("Try halving this and letting the denoiser finish the "
                          "image - the difference is usually invisible.")
        cat.findings.append(Finding("Max samples", f"{samples:,}", cat.load,
                                    severity, suggestion))

        if not adaptive and samples > 128:
            cat.findings.append(Finding(
                "Adaptive sampling", "Off", pct(load * 0.4), "warn",
                "Turning this on lets Cycles stop early on areas that have "
                "already resolved. It is usually a large saving for no visible "
                "change."))
        elif adaptive and threshold and threshold < 0.005:
            cat.findings.append(Finding(
                "Noise threshold", f"{threshold:g}", pct(log_scale(0.01 / max(threshold, 1e-6), 1, 20)),
                "notice",
                "A very low threshold makes adaptive sampling give up its "
                "advantage. 0.01 is the usual starting point."))

        if not denoise:
            cat.findings.append(Finding(
                "Denoising", "Off", pct(load * 0.35), "notice",
                "With denoising on you can usually cut samples by 4x or more "
                "for the same apparent quality."))

        bounces = int(sampling.get("max_bounces") or 0)
        if bounces > 12:
            cat.findings.append(Finding(
                "Max light bounces", str(bounces),
                pct(log_scale(bounces, 12, 64)), "notice",
                "Most scenes are indistinguishable at 8-12 bounces. Interiors "
                "and glass need more; open exteriors rarely do."))

        if sampling.get("caustics_reflective") or sampling.get("caustics_refractive"):
            cat.findings.append(Finding(
                "Caustics", "Enabled", 30, "notice",
                "Caustics are one of the slowest things to resolve and are the "
                "usual source of stubborn fireflies. Turn them off unless the "
                "shot needs them."))

        if time_limit:
            cat.findings.append(Finding(
                "Time limit per frame", f"{time_limit:g} s", 0, "info",
                "This caps render time, so the sample count above is an upper "
                "bound rather than the real cost."))

        cat.stats = [
            ("Engine", "Cycles"),
            ("Device", sampling.get("device", "CPU")),
            ("Max samples", f"{samples:,}"),
            ("Adaptive sampling", "On" if adaptive else "Off"),
            ("Noise threshold", f"{threshold:g}" if adaptive else "-"),
            ("Denoising", (sampling.get("denoiser") or "On") if denoise else "Off"),
            ("Max bounces", str(bounces)),
            ("Diffuse / glossy / transmission",
             "{} / {} / {}".format(sampling.get("diffuse_bounces", "?"),
                                   sampling.get("glossy_bounces", "?"),
                                   sampling.get("transmission_bounces", "?"))),
            ("Light tree", "On" if sampling.get("use_light_tree") else "Off"),
        ]
        cat.headline = "{:,} samples, adaptive {}, denoise {}".format(
            samples, "on" if adaptive else "off", "on" if denoise else "off")

        if sampling.get("device") == "CPU":
            cat.findings.append(Finding(
                "Render device", "CPU", 0, "notice",
                "If this machine has a supported GPU, switching to GPU Compute "
                "is usually the single biggest speed-up available."))
    else:
        samples = int(sampling.get("eevee_samples") or 0)
        cat.load = pct(log_scale(samples, 16, 1024))
        cat.headline = f"EEVEE, {samples:,} render samples"
        suggestion = ""
        if samples > 256:
            suggestion = ("EEVEE converges quickly; above ~128 samples the "
                          "returns are very small.")
        cat.findings.append(Finding("Render samples", f"{samples:,}", cat.load,
                                    "notice" if samples > 256 else "info", suggestion))
        cat.stats = [
            ("Engine", engine.replace("BLENDER_", "").replace("_", " ").title()),
            ("Render samples", f"{samples:,}"),
            ("Ambient occlusion", "On" if sampling.get("use_gtao") else "Off"),
            ("Screen space reflections", "On" if sampling.get("use_ssr") else "Off"),
            ("Ray tracing", "On" if sampling.get("use_raytracing") else "Off"),
        ]
    return cat


def _geometry(raw: dict) -> Category:
    geo = raw.get("geometry") or {}
    tris = int(geo.get("render_tris") or 0)
    items = geo.get("items") or []
    cat = Category("geometry", "Geometry", "frames")
    cat.load = pct(log_scale(tris, 100_000, 100_000_000))
    cat.headline = "{} triangles at render time across {} object(s)".format(
        human_count(tris), geo.get("rendered_mesh_objects", 0))

    visible = [i for i in items if not i.get("hide_render")]

    # one object dominating the scene is worth calling out by name
    if visible and tris > 250_000:
        top = visible[0]
        share = top["render_tris"] / tris if tris else 0
        if share >= 0.45 and top["render_tris"] >= 250_000:
            cat.findings.append(Finding(
                f"Heaviest object: {top['name']}",
                "{} tris ({:.0f}% of the scene)".format(
                    human_count(top["render_tris"]), share * 100),
                pct(share), "warn" if share > 0.7 else "notice",
                "This single object carries most of the scene's geometry. A "
                "Decimate modifier, or a lower subdivision level, would cut "
                "memory and build time noticeably."))

    # modifiers that quietly multiply geometry at render time only
    for item in visible[:12]:
        multiplier = float(item.get("multiplier") or 1.0)
        if multiplier >= 64 and item["render_tris"] >= 100_000:
            cat.findings.append(Finding(
                f"Subdivision on {item['name']}",
                "{} -> {} tris ({})".format(human_count(item["base_tris"]),
                                            human_count(item["render_tris"]),
                                            ", ".join(item.get("modifiers") or [])),
                pct(log_scale(multiplier, 16, 4096)), "notice",
                "Render-time subdivision multiplies geometry by 4x per level. "
                "Dropping one level quarters it, and is often invisible."))

    if geo.get("instancers"):
        cat.findings.append(Finding(
            "Instancers", str(geo["instancers"]), 0, "info",
            "Instanced geometry is counted once here, so the real triangle "
            "count may be higher than shown."))

    cat.stats = [
        ("Triangles at render time", f"{tris:,}"),
        ("Triangles before modifiers", f"{geo.get('base_tris', 0):,}"),
        ("Mesh objects rendered", str(geo.get("rendered_mesh_objects", 0))),
        ("Objects in scene", str(geo.get("objects_total", 0))),
        ("Curves", str(geo.get("curves", 0))),
    ]
    for item in visible[:8]:
        cat.stats.append((
            "   " + item["name"],
            "{} tris{}".format(human_count(item["render_tris"]),
                               "  (" + ", ".join(item["modifiers"]) + ")"
                               if item.get("modifiers") else "")))
    return cat


def _textures(raw: dict) -> Category:
    tex = raw.get("textures") or {}
    total = int(tex.get("total_bytes") or 0)
    cat = Category("textures", "Textures", "output")
    cat.load = pct(log_scale(total, 64 * 1024 ** 2, 8 * 1024 ** 3))
    cat.headline = "{} of image data across {} image(s)".format(
        human_bytes(total), tex.get("count", 0))

    if tex.get("missing"):
        cat.findings.append(Finding(
            "Missing image files", str(tex["missing"]), 0, "critical",
            "These will render as solid magenta. Repath them, or pack them "
            "into the .blend, before queueing this job."))

    if tex.get("at_8k"):
        cat.findings.append(Finding(
            "8K or larger textures", str(tex["at_8k"]),
            pct(log_scale(tex["at_8k"], 1, 24)), "notice",
            "An 8K texture costs 4x the memory of a 4K one. Unless something "
            "fills the frame, 2K-4K is usually indistinguishable."))

    if total > 2 * 1024 ** 3:
        cat.findings.append(Finding(
            "Total texture memory", human_bytes(total), cat.load, "warn",
            "This may not fit in VRAM. If it spills, Cycles falls back to "
            "host memory and slows down sharply."))

    if tex.get("float_images"):
        cat.findings.append(Finding(
            "32-bit float images", str(tex["float_images"]), 0, "info",
            "Float images use 4x the memory of 8-bit ones. Worth it for HDRIs, "
            "rarely for colour maps."))

    cat.stats = [
        ("Total image memory", human_bytes(total)),
        ("Images", str(tex.get("count", 0))),
        ("4K or larger", str(tex.get("at_4k", 0))),
        ("8K or larger", str(tex.get("at_8k", 0))),
        ("Missing files", str(tex.get("missing", 0))),
    ]
    for item in (tex.get("items") or [])[:8]:
        if not item.get("users"):
            continue
        cat.stats.append((
            "   " + item["name"],
            "{}x{}  {}{}".format(item["width"], item["height"],
                                 human_bytes(item["bytes"]),
                                 "  MISSING" if item.get("missing") else "")))
    return cat


def _lighting(raw: dict) -> Category:
    lights = raw.get("lights") or {}
    world = lights.get("world") or {}
    cat = Category("lighting", "Lighting", "camera")

    count = int(lights.get("rendered") or 0)
    soft = int(lights.get("large_soft") or 0)
    env_pixels = int(world.get("env_width") or 0) * int(world.get("env_height") or 0)

    load = max(log_scale(count, 1, 48) * 0.8,
               log_scale(soft, 1, 12) * 0.7,
               log_scale(env_pixels, 2048 * 1024, 16384 * 8192) * 0.6)
    if world.get("has_volume"):
        load = max(load, 0.75)
    cat.load = pct(load)
    cat.headline = "{} light(s){}".format(
        count, f", {world.get('env_image')} environment" if world.get("env_image") else "")

    if soft >= 3:
        cat.findings.append(Finding(
            "Large soft-shadow lights", str(soft), pct(log_scale(soft, 1, 12)),
            "notice",
            "Big area lights need more samples to resolve cleanly. Shrinking "
            "them, or using fewer, reduces noise at the same sample count."))

    if count >= 16:
        cat.findings.append(Finding(
            "Light count", str(count), pct(log_scale(count, 4, 64)), "notice",
            "Many lights means more shadow rays per sample. Check that Light "
            "Tree is on, and consider baking or merging distant lights."))

    if env_pixels >= 8192 * 4096:
        cat.findings.append(Finding(
            "Environment texture", "{}x{}".format(world.get("env_width"),
                                                  world.get("env_height")),
            pct(log_scale(env_pixels, 2048 * 1024, 16384 * 8192)), "notice",
            "A 4K HDRI is plenty for lighting unless it appears sharply in "
            "the background."))

    if world.get("has_volume"):
        cat.findings.append(Finding(
            "World volume", "Enabled", 75, "warn",
            "A world volume makes every ray march through the whole scene. "
            "This is one of the most expensive things you can enable."))

    cat.stats = [
        ("Lights rendered", str(count)),
        ("Area lights", str(lights.get("area_lights", 0))),
        ("Large soft lights", str(soft)),
        ("World", world.get("name") or "(none)"),
        ("Environment texture", world.get("env_image") or "(none)"),
    ]
    for item in (lights.get("items") or [])[:8]:
        if item.get("hide_render"):
            continue
        cat.stats.append(("   " + item["name"],
                          "{}  energy {:g}  size {:g}".format(
                              item["type"].title(), item["energy"], item["size"])))
    return cat


def _output(raw: dict) -> Category:
    render = raw.get("render") or {}
    cat = Category("output", "Output Settings", "output")

    pixels = int(render.get("pixels") or 0)
    frames = int(render.get("frames") or 0)
    layers = max(1, int(render.get("view_layers") or 1))
    work = pixels * max(frames, 1) * layers

    cat.load = pct(log_scale(work, REF_PIXELS * 24, REF_PIXELS * 4 * 3000))
    cat.headline = "{}x{} at {}%, {} frame(s)".format(
        render.get("resolution_x", 0), render.get("resolution_y", 0),
        render.get("resolution_percentage", 100), frames)

    if render.get("resolution_percentage", 100) < 100:
        cat.findings.append(Finding(
            "Resolution scale", "{}%".format(render["resolution_percentage"]),
            0, "info",
            "Output is scaled down, so the real pixel count is lower than the "
            "resolution suggests."))

    if pixels >= 3840 * 2160:
        cat.findings.append(Finding(
            "Frame size", "{}x{}".format(render.get("resolution_x"),
                                         render.get("resolution_y")),
            pct(log_scale(pixels, REF_PIXELS, REF_PIXELS * 16)), "notice",
            "Cost scales directly with pixel count: 4K is four times the work "
            "of 1080p. Rendering at 50% for review passes is a cheap win."))

    if frames >= 500:
        cat.findings.append(Finding(
            "Frame count", f"{frames:,}", pct(log_scale(frames, 100, 5000)),
            "notice",
            "Every saving per frame is multiplied by this number, so tuning "
            "the settings above pays off the most here."))

    if layers > 1:
        cat.findings.append(Finding(
            "Active view layers", str(layers), pct(log_scale(layers, 1, 8)),
            "warn",
            "Each active view layer renders the scene again. Disable the ones "
            "this job does not need."))

    if render.get("use_motion_blur"):
        cat.findings.append(Finding(
            "Motion blur", "On (shutter {:g})".format(
                render.get("motion_blur_shutter", 0.5)), 35, "notice",
            "Motion blur multiplies the geometry Cycles has to consider per "
            "frame. It is often cheaper to add it in post for previews."))

    if render.get("film_transparent"):
        cat.findings.append(Finding("Transparent film", "On", 0, "info", ""))

    if render.get("use_simplify"):
        cat.findings.append(Finding(
            "Simplify", "On (max subdivision {})".format(
                render.get("simplify_subdivision_render", 0)), 0, "info",
            "Simplify is capping render subdivision, so the geometry figure "
            "may be lower in practice."))

    if not render.get("use_persistent_data") and frames > 50:
        cat.findings.append(Finding(
            "Persistent data", "Off", 0, "notice",
            "For a long animation on a static scene this can save the whole "
            "scene-build cost on every frame after the first. It uses more "
            "memory in exchange."))

    cat.stats = [
        ("Resolution", "{}x{} at {}%".format(render.get("resolution_x"),
                                             render.get("resolution_y"),
                                             render.get("resolution_percentage"))),
        ("Pixels per frame", f"{pixels:,}"),
        ("Frame range", "{} - {} step {}".format(render.get("frame_start"),
                                                 render.get("frame_end"),
                                                 render.get("frame_step"))),
        ("Frames", f"{frames:,}"),
        ("File format", render.get("file_format", "")),
        ("Colour depth", render.get("color_depth", "")),
        ("Active view layers", "{} of {}".format(render.get("view_layers", 1),
                                                 render.get("total_view_layers", 1))),
        ("Motion blur", "On" if render.get("use_motion_blur") else "Off"),
        ("Persistent data", "On" if render.get("use_persistent_data") else "Off"),
    ]
    return cat


def _shading(raw: dict) -> Category:
    materials = raw.get("materials") or {}
    items = materials.get("items") or []
    cat = Category("shading", "Materials and Shading", "settings")

    weights = {
        "glass": 0.8, "refraction": 0.8, "transmission": 0.7,
        "subsurface": 0.7, "volume scatter": 1.0, "volume absorption": 0.9,
        "principled volume": 1.0, "true displacement": 0.9,
        "hair": 0.6, "principled hair": 0.6,
        "musgrave texture": 0.3, "noise texture": 0.2,
        "voronoi texture": 0.25, "wave texture": 0.2,
        "displacement": 0.4, "vector displacement": 0.6, "transparency": 0.4,
    }
    tally = {}
    for item in items:
        for feature in item.get("features") or []:
            tally[feature] = tally.get(feature, 0) + 1

    pressure = 0.0
    for feature, count in tally.items():
        pressure += weights.get(feature, 0.2) * min(1.0, 0.4 + 0.15 * count)
    cat.load = pct(clamp01(pressure / 3.0))

    named = ", ".join(sorted(tally)) if tally else "nothing unusual"
    cat.headline = "{} material(s); {}".format(materials.get("count", 0), named)

    for feature, tip in (
        ("volume scatter", "Volumetrics are the most expensive shader type in "
                           "Cycles. Reduce step rate or volume bounces if it is slow."),
        ("principled volume", "Volumetrics are the most expensive shader type "
                              "in Cycles. Reduce step rate or volume bounces if it is slow."),
        ("true displacement", "True displacement generates real geometry at "
                              "render time. Bump or a lower displacement scale is far cheaper."),
        ("subsurface", "Subsurface scattering needs more samples to clear up. "
                       "Denoising helps a lot here."),
        ("glass", "Glass needs enough transmission bounces to look right, and "
                  "each one costs time. It also pairs badly with caustics."),
    ):
        if feature in tally:
            cat.findings.append(Finding(
                feature.title(), "{} material(s)".format(tally[feature]),
                pct(weights.get(feature, 0.3)), "notice", tip))

    cat.stats = [("Materials in use", str(materials.get("count", 0))),
                 ("Total shader nodes", str(materials.get("total_nodes", 0)))]
    for item in items[:8]:
        cat.stats.append(("   " + item["name"],
                          "{} nodes{}".format(item["nodes"],
                                              "  (" + ", ".join(item["features"]) + ")"
                                              if item["features"] else "")))
    return cat


def _effects(raw: dict) -> Category:
    volumes = raw.get("volumes") or {}
    particles = raw.get("particles") or {}
    compositor = raw.get("compositor") or {}
    render = raw.get("render") or {}
    cat = Category("effects", "Effects and Simulation", "path")

    parts = int(particles.get("estimated_particles") or 0)
    load = max(
        log_scale(volumes.get("count", 0), 1, 8) * 0.9,
        log_scale(parts, 10_000, 5_000_000) * 0.8,
        0.35 if render.get("use_motion_blur") else 0.0,
        log_scale(len(compositor.get("heavy") or []), 1, 8) * 0.4,
    )
    cat.load = pct(load)

    bits = []
    if volumes.get("count"):
        bits.append(f"{volumes['count']} volume(s)")
    if particles.get("systems"):
        bits.append(f"{particles['systems']} particle system(s)")
    if compositor.get("enabled"):
        bits.append(f"{compositor.get('nodes', 0)} compositor node(s)")
    cat.headline = ", ".join(bits) if bits else "no simulation or compositing"

    for item in (volumes.get("items") or [])[:6]:
        detail = item.get("kind", "volume")
        if item.get("resolution"):
            detail += f", resolution {item['resolution']}"
        cat.findings.append(Finding(
            f"Volume: {item['name']}", detail,
            pct(log_scale(item.get("resolution") or 64, 64, 512)), "warn",
            "Volumes are ray-marched and scale with resolution. Lowering the "
            "domain resolution is the most effective control."))

    if parts >= 500_000:
        cat.findings.append(Finding(
            "Particles / hair", human_count(parts),
            pct(log_scale(parts, 10_000, 5_000_000)), "notice",
            "Large hair and particle counts cost both memory and build time. "
            "Reduce render children rather than the parent count."))

    heavy = compositor.get("heavy") or []
    if heavy:
        cat.findings.append(Finding(
            "Compositor", ", ".join(heavy), pct(log_scale(len(heavy), 1, 8)),
            "info",
            "These run once per frame after rendering. Usually minor, but "
            "Defocus and Vector Blur can be slow at high resolution."))

    cat.stats = [
        ("Volumes", str(volumes.get("count", 0))),
        ("Particle systems", str(particles.get("systems", 0))),
        ("Estimated particles", human_count(parts)),
        ("Compositor", "On, {} nodes".format(compositor.get("nodes", 0))
         if compositor.get("enabled") else "Off"),
        ("Motion blur", "On" if render.get("use_motion_blur") else "Off"),
    ]
    return cat


# --------------------------------------------------------------------------
# overall
# --------------------------------------------------------------------------

def build_report(raw: dict) -> Report:
    """Score a raw measurement from ``bq_analyze.py``."""
    if not raw or not raw.get("ok"):
        return Report(error=(raw or {}).get("error") or "No analysis data.")

    categories = [_sampling(raw), _geometry(raw), _output(raw), _textures(raw),
                  _lighting(raw), _shading(raw), _effects(raw)]
    report = Report(categories=categories)

    render = raw.get("render") or {}
    sampling = raw.get("sampling") or {}
    engine = render.get("engine", "")

    pixels = int(render.get("pixels") or 0) or REF_PIXELS
    frames = max(1, int(render.get("frames") or 1))
    layers = max(1, int(render.get("view_layers") or 1))

    if engine == "CYCLES":
        samples = max(1, int(sampling.get("samples") or REF_SAMPLES))
        if sampling.get("use_adaptive_sampling") and sampling.get("adaptive_threshold"):
            samples *= 0.6
        if sampling.get("time_limit"):
            samples = min(samples, REF_SAMPLES)     # the limit caps real cost
    else:
        samples = max(1, int(sampling.get("eevee_samples") or 64)) * EEVEE_SAMPLE_COST

    work = pixels * frames * samples * layers

    def load_of(key):
        cat = report.category(key)
        return (cat.load / 100.0) if cat else 0.0

    complexity = (1.0
                  + 0.50 * load_of("geometry")
                  + 0.30 * load_of("textures")
                  + 0.40 * load_of("lighting")
                  + 0.70 * load_of("shading")
                  + 0.90 * load_of("effects"))

    cost = work * complexity
    report.relative = cost / REF_WORK if REF_WORK else 1.0

    # 1x the reference render sits at 50; each 1000x is another half the scale.
    position = 0.5 + math.log(max(report.relative, 1e-9)) / math.log(1000.0) * 0.5
    report.overall = pct(position)

    for ceiling, name, color in RATINGS:
        if report.overall < ceiling:
            report.rating = name
            report.color = color
            break

    if report.relative >= 1:
        comparison = f"about {report.relative:,.0f}x"
    else:
        comparison = f"about {report.relative:.2f}x"
    report.summary = (
        "{} render - {} the work of a typical 1080p, 128-sample, "
        "100-frame job.".format(report.rating, comparison))
    return report


def top_suggestions(report: Report, limit: int = 5) -> list:
    """The findings most worth acting on, across every category."""
    scored = []
    for cat in report.categories:
        for finding in cat.findings:
            if not finding.suggestion:
                continue
            weight = (3 - SEVERITY_ORDER.get(finding.severity, 3)) * 100 + finding.load
            scored.append((weight, cat, finding))
    scored.sort(key=lambda entry: entry[0], reverse=True)
    return [(cat, finding) for _w, cat, finding in scored[:limit]]
