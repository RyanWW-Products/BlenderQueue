"""Declarative schema for render overrides.

Everything the override editor shows, everything the Blender-side runner
applies, and everything that gets persisted to disk is derived from the
``GROUPS`` table below.  Adding a new render setting means adding one
``F(...)`` entry here -- the UI, the JSON payload and the apply step all pick
it up automatically.

``path`` is an attribute path resolved against the target ``bpy.types.Scene``.
A path starting with ``@`` is a special case handled explicitly by
``scripts/bq_render.py`` (things that are not a simple attribute assignment,
such as picking the camera or splitting an output directory + file prefix).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# --------------------------------------------------------------------------
# field / group primitives
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class F:
    """One editable render setting."""

    key: str
    label: str
    type: str                       # bool int float enum str dir file
    default: Any = None
    path: str | None = None         # bpy attribute path, or "@special"
    choices: tuple = ()             # enum: ((value, label), ...)
    source: str | None = None       # enum populated from the inspected file
    minimum: float | None = None
    maximum: float | None = None
    step: float = 1.0
    decimals: int = 3
    suffix: str = ""
    tip: str = ""
    depends: tuple = ()             # ((other_key, (allowed, values)), ...)

    def visible_for(self, values: dict) -> bool:
        for other, allowed in self.depends:
            if values.get(other) not in allowed:
                return False
        return True


@dataclass(frozen=True)
class G:
    """A collapsible group of settings with its own on/off switch."""

    key: str
    label: str
    icon: str = ""
    blurb: str = ""
    fields: tuple = field(default_factory=tuple)


# --------------------------------------------------------------------------
# shared choice tables
# --------------------------------------------------------------------------

ENGINES = (
    ("CYCLES", "Cycles"),
    ("BLENDER_EEVEE_NEXT", "EEVEE (4.2+)"),
    ("BLENDER_EEVEE", "EEVEE (Legacy)"),
    ("BLENDER_WORKBENCH", "Workbench"),
)

IMAGE_FORMATS = (
    ("PNG", "PNG"),
    ("JPEG", "JPEG"),
    ("OPEN_EXR", "OpenEXR"),
    ("OPEN_EXR_MULTILAYER", "OpenEXR MultiLayer"),
    ("TIFF", "TIFF"),
    ("WEBP", "WebP"),
    ("TARGA", "Targa"),
    ("BMP", "BMP"),
    ("FFMPEG", "FFmpeg Video"),
)

COLOR_MODES = (("BW", "BW"), ("RGB", "RGB"), ("RGBA", "RGBA"))
COLOR_DEPTHS = (("8", "8-bit"), ("16", "16-bit"), ("32", "32-bit"))

FFMPEG_CONTAINERS = (
    ("MPEG4", "MPEG-4 (.mp4)"),
    ("QUICKTIME", "QuickTime (.mov)"),
    ("MKV", "Matroska (.mkv)"),
    ("AVI", "AVI (.avi)"),
    ("WEBM", "WebM (.webm)"),
)

FFMPEG_CODECS = (
    ("H264", "H.264"),
    ("HEVC", "H.265 / HEVC"),
    ("MPEG4", "MPEG-4"),
    ("WEBM", "WebM / VP9"),
    ("PNG", "PNG (lossless)"),
    ("QTRLE", "QuickTime RLE (lossless)"),
    ("FFV1", "FFV1 (lossless)"),
)

FFMPEG_CRF = (
    ("LOSSLESS", "Lossless"),
    ("PERC_LOSSLESS", "Perceptually Lossless"),
    ("HIGH", "High Quality"),
    ("MEDIUM", "Medium Quality"),
    ("LOW", "Low Quality"),
    ("VERYLOW", "Very Low Quality"),
)

AUDIO_CODECS = (
    ("NONE", "No Audio"),
    ("AAC", "AAC"),
    ("MP3", "MP3"),
    ("PCM", "PCM"),
    ("VORBIS", "Vorbis"),
    ("FLAC", "FLAC"),
)

CYCLES_DEVICES = (("CPU", "CPU"), ("GPU", "GPU Compute"))
DENOISERS = (("OPENIMAGEDENOISE", "OpenImageDenoise"), ("OPTIX", "OptiX"))
DENOISE_PASSES = (
    ("RGB_ALBEDO_NORMAL", "Albedo + Normal"),
    ("RGB_ALBEDO", "Albedo"),
    ("RGB", "None"),
)

VIEW_TRANSFORMS = (
    ("AgX", "AgX"),
    ("Filmic", "Filmic"),
    ("Standard", "Standard"),
    ("Khronos PBR Neutral", "Khronos PBR Neutral"),
    ("Raw", "Raw"),
    ("False Color", "False Color"),
)

LOOKS = (
    ("None", "None"),
    ("AgX - Punchy", "AgX - Punchy"),
    ("AgX - Greyscale", "AgX - Greyscale"),
    ("AgX - Very High Contrast", "AgX - Very High Contrast"),
    ("AgX - High Contrast", "AgX - High Contrast"),
    ("AgX - Medium High Contrast", "AgX - Medium High Contrast"),
    ("AgX - Base Contrast", "AgX - Base Contrast"),
    ("AgX - Medium Low Contrast", "AgX - Medium Low Contrast"),
    ("AgX - Low Contrast", "AgX - Low Contrast"),
    ("AgX - Very Low Contrast", "AgX - Very Low Contrast"),
)

FRAME_MODES = (("ANIMATION", "Animation (frame range)"), ("STILL", "Single frame"))
THREAD_MODES = (("AUTO", "Auto-detect"), ("FIXED", "Fixed count"))

_IS_FFMPEG = (("file_format", ("FFMPEG",)),)
_IS_CYCLES = (("engine", ("CYCLES",)),)
_IS_EEVEE = (("engine", ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE")),)


# --------------------------------------------------------------------------
# the schema
# --------------------------------------------------------------------------

GROUPS: tuple[G, ...] = (
    G(
        key="scene",
        label="Scene and Camera",
        icon="scene",
        blurb="Choose which scene, camera and world the job renders with.",
        fields=(
            F("scene", "Scene", "enum", "", "@scene", source="scenes",
              tip="Which scene inside the .blend to render."),
            F("camera", "Camera", "enum", "", "@camera", source="cameras",
              tip="Override the active camera of the scene."),
            F("world", "World", "enum", "", "@world", source="worlds",
              tip="Swap the world / environment lighting."),
            F("use_single_view_layer", "Render one view layer only", "bool", False,
              "@single_view_layer"),
            F("view_layer", "View Layer", "enum", "", "@view_layer", source="view_layers",
              depends=(("use_single_view_layer", (True,)),)),
        ),
    ),
    G(
        key="frames",
        label="Frame Range",
        icon="frames",
        blurb="Render the whole animation or a single still.",
        fields=(
            F("frame_mode", "Mode", "enum", "ANIMATION", "@frame_mode", choices=FRAME_MODES),
            F("frame_start", "Start Frame", "int", 1, "frame_start",
              minimum=-1048574, maximum=1048574, depends=(("frame_mode", ("ANIMATION",)),)),
            F("frame_end", "End Frame", "int", 250, "frame_end",
              minimum=-1048574, maximum=1048574, depends=(("frame_mode", ("ANIMATION",)),)),
            F("frame_step", "Frame Step", "int", 1, "frame_step",
              minimum=1, maximum=10000, depends=(("frame_mode", ("ANIMATION",)),),
              tip="Render every Nth frame."),
            F("frame_current", "Frame", "int", 1, "frame_current",
              minimum=-1048574, maximum=1048574, depends=(("frame_mode", ("STILL",)),)),
        ),
    ),
    G(
        key="output",
        label="Output",
        icon="output",
        blurb="Where frames are written and in what file format.",
        fields=(
            F("output_dir", "Output Folder", "dir", "", "@output_dir"),
            F("file_prefix", "File Name", "str", "", "@file_prefix",
              tip="Prefix for each frame. Blender appends the frame number."),
            F("file_format", "File Format", "enum", "PNG",
              "render.image_settings.file_format", choices=IMAGE_FORMATS),
            F("color_mode", "Color", "enum", "RGBA",
              "render.image_settings.color_mode", choices=COLOR_MODES),
            F("color_depth", "Color Depth", "enum", "8",
              "render.image_settings.color_depth", choices=COLOR_DEPTHS),
            F("compression", "PNG Compression", "int", 15,
              "render.image_settings.compression", minimum=0, maximum=100, suffix=" %",
              depends=(("file_format", ("PNG",)),)),
            F("quality", "Quality", "int", 90, "render.image_settings.quality",
              minimum=0, maximum=100, suffix=" %",
              depends=(("file_format", ("JPEG", "WEBP", "FFMPEG")),)),
            F("film_transparent", "Transparent Background", "bool", False,
              "render.film_transparent"),
            F("use_overwrite", "Overwrite Existing Frames", "bool", True,
              "render.use_overwrite"),
            F("use_placeholder", "Write Placeholder Frames", "bool", False,
              "render.use_placeholder",
              tip="Useful when several machines render the same range."),
            F("use_file_extension", "Add File Extension", "bool", True,
              "render.use_file_extension"),
            F("ffmpeg_format", "Container", "enum", "MPEG4", "render.ffmpeg.format",
              choices=FFMPEG_CONTAINERS, depends=_IS_FFMPEG),
            F("ffmpeg_codec", "Video Codec", "enum", "H264", "render.ffmpeg.codec",
              choices=FFMPEG_CODECS, depends=_IS_FFMPEG),
            F("ffmpeg_crf", "Output Quality", "enum", "MEDIUM",
              "render.ffmpeg.constant_rate_factor", choices=FFMPEG_CRF, depends=_IS_FFMPEG),
            F("ffmpeg_audio", "Audio Codec", "enum", "NONE", "render.ffmpeg.audio_codec",
              choices=AUDIO_CODECS, depends=_IS_FFMPEG),
        ),
    ),
    G(
        key="dimensions",
        label="Format and Dimensions",
        icon="dimensions",
        blurb="Resolution, scale and frame rate.",
        fields=(
            F("resolution_x", "Resolution X", "int", 1920, "render.resolution_x",
              minimum=4, maximum=65536, suffix=" px"),
            F("resolution_y", "Resolution Y", "int", 1080, "render.resolution_y",
              minimum=4, maximum=65536, suffix=" px"),
            F("resolution_percentage", "Resolution Scale", "int", 100,
              "render.resolution_percentage", minimum=1, maximum=32767, suffix=" %",
              tip="Drop to 25-50% for quick preview renders."),
            F("fps", "Frame Rate", "int", 24, "render.fps",
              minimum=1, maximum=32767, suffix=" fps"),
            F("fps_base", "FPS Base", "float", 1.0, "render.fps_base",
              minimum=1e-5, maximum=1e6, step=0.001, decimals=5,
              tip="Set to 1.001 for NTSC rates such as 23.976."),
            F("pixel_aspect_x", "Pixel Aspect X", "float", 1.0, "render.pixel_aspect_x",
              minimum=0.01, maximum=200.0, step=0.01),
            F("pixel_aspect_y", "Pixel Aspect Y", "float", 1.0, "render.pixel_aspect_y",
              minimum=0.01, maximum=200.0, step=0.01),
        ),
    ),
    G(
        key="engine",
        label="Render Engine",
        icon="engine",
        blurb="Engine, sampling and denoising.",
        fields=(
            F("engine", "Engine", "enum", "CYCLES", "render.engine", choices=ENGINES),
            F("cycles_device", "Device", "enum", "GPU", "@cycles_device",
              choices=CYCLES_DEVICES, depends=_IS_CYCLES),
            F("cycles_samples", "Max Samples", "int", 128, "cycles.samples",
              minimum=1, maximum=16777216, depends=_IS_CYCLES),
            F("cycles_adaptive", "Adaptive Sampling", "bool", True,
              "cycles.use_adaptive_sampling", depends=_IS_CYCLES),
            F("cycles_threshold", "Noise Threshold", "float", 0.01,
              "cycles.adaptive_threshold", minimum=0.0, maximum=1.0, step=0.001, decimals=4,
              depends=_IS_CYCLES + (("cycles_adaptive", (True,)),)),
            F("cycles_time_limit", "Time Limit / Frame", "float", 0.0, "cycles.time_limit",
              minimum=0.0, maximum=1e6, step=1.0, decimals=1, suffix=" s",
              tip="0 disables the limit.", depends=_IS_CYCLES),
            F("cycles_denoise", "Denoise", "bool", True, "cycles.use_denoising",
              depends=_IS_CYCLES),
            F("cycles_denoiser", "Denoiser", "enum", "OPENIMAGEDENOISE", "cycles.denoiser",
              choices=DENOISERS, depends=_IS_CYCLES + (("cycles_denoise", (True,)),)),
            F("cycles_denoise_input", "Denoise Passes", "enum", "RGB_ALBEDO_NORMAL",
              "cycles.denoising_input_passes", choices=DENOISE_PASSES,
              depends=_IS_CYCLES + (("cycles_denoise", (True,)),)),
            F("cycles_max_bounces", "Max Light Bounces", "int", 12, "cycles.max_bounces",
              minimum=0, maximum=1024, depends=_IS_CYCLES),
            F("cycles_transparent_bounces", "Transparent Bounces", "int", 8,
              "cycles.transparent_max_bounces", minimum=0, maximum=1024, depends=_IS_CYCLES),
            F("eevee_samples", "Render Samples", "int", 64, "eevee.taa_render_samples",
              minimum=1, maximum=1048576, depends=_IS_EEVEE),
            F("use_motion_blur", "Motion Blur", "bool", False, "render.use_motion_blur"),
            F("motion_blur_shutter", "Shutter", "float", 0.5, "render.motion_blur_shutter",
              minimum=0.0, maximum=100.0, step=0.05, decimals=3,
              depends=(("use_motion_blur", (True,)),)),
        ),
    ),
    G(
        key="performance",
        label="Performance and Simplify",
        icon="performance",
        blurb="CPU threads, memory reuse and quality cutbacks.",
        fields=(
            F("threads_mode", "Threads", "enum", "AUTO", "render.threads_mode",
              choices=THREAD_MODES),
            F("threads", "Thread Count", "int", 8, "render.threads",
              minimum=1, maximum=1024, depends=(("threads_mode", ("FIXED",)),)),
            F("use_persistent_data", "Persistent Data", "bool", False,
              "render.use_persistent_data",
              tip="Keeps the scene in memory between frames. Faster, uses more RAM."),
            F("cycles_tile_size", "Tile Size", "int", 2048, "cycles.tile_size",
              minimum=8, maximum=16384, suffix=" px", depends=_IS_CYCLES),
            F("use_simplify", "Simplify", "bool", False, "render.use_simplify"),
            F("simplify_subdivision_render", "Max Subdivision", "int", 6,
              "render.simplify_subdivision_render", minimum=0, maximum=32,
              depends=(("use_simplify", (True,)),)),
            F("simplify_child_particles_render", "Max Child Particles", "float", 1.0,
              "render.simplify_child_particles_render", minimum=0.0, maximum=1.0,
              step=0.05, depends=(("use_simplify", (True,)),)),
        ),
    ),
    G(
        key="color",
        label="Color Management",
        icon="color",
        blurb="View transform, look and exposure applied to the render.",
        fields=(
            F("view_transform", "View Transform", "enum", "AgX",
              "view_settings.view_transform", choices=VIEW_TRANSFORMS),
            F("look", "Look", "enum", "None", "view_settings.look", choices=LOOKS),
            F("exposure", "Exposure", "float", 0.0, "view_settings.exposure",
              minimum=-32.0, maximum=32.0, step=0.1),
            F("gamma", "Gamma", "float", 1.0, "view_settings.gamma",
              minimum=0.0, maximum=5.0, step=0.05),
        ),
    ),
    G(
        key="stamp",
        label="Metadata Stamp",
        icon="stamp",
        blurb="Burn frame numbers, notes and timing into the image.",
        fields=(
            F("use_stamp", "Burn Into Image", "bool", False, "render.use_stamp"),
            F("use_stamp_frame", "Include Frame Number", "bool", True,
              "render.use_stamp_frame"),
            F("use_stamp_date", "Include Date", "bool", True, "render.use_stamp_date"),
            F("use_stamp_render_time", "Include Render Time", "bool", False,
              "render.use_stamp_render_time"),
            F("use_stamp_camera", "Include Camera", "bool", True, "render.use_stamp_camera"),
            F("use_stamp_note", "Include Note", "bool", False, "render.use_stamp_note"),
            F("stamp_note_text", "Note", "str", "", "render.stamp_note_text",
              depends=(("use_stamp_note", (True,)),)),
            F("stamp_font_size", "Font Size", "int", 12, "render.stamp_font_size",
              minimum=8, maximum=64, suffix=" px"),
        ),
    ),
)

GROUP_BY_KEY = {g.key: g for g in GROUPS}
FIELD_BY_KEY = {f.key: f for g in GROUPS for f in g.fields}


def group_defaults(group_key: str) -> dict:
    """Fallback values for a group, used when the .blend could not be read."""
    return {f.key: f.default for f in GROUP_BY_KEY[group_key].fields}


def all_defaults() -> dict:
    return {g.key: group_defaults(g.key) for g in GROUPS}
