"""Finding Blender installations and building the command lines we run."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass

APP_NAME = "BlenderQueue"

# Windows: keep spawned console windows hidden.
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def resource_dir() -> str:
    """Where bundled data lives, whether frozen by PyInstaller or run from source."""
    if getattr(sys, "frozen", False):
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def script_path(name: str) -> str:
    """Absolute path to one of our Blender-side scripts."""
    base = resource_dir()
    for candidate in (os.path.join(base, "scripts", name),
                      os.path.join(base, "blenderqueue", "scripts", name)):
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(base, "scripts", name)


PORTABLE_MARKER = "portable.txt"
PORTABLE_DATA = "BlenderQueueData"


def app_dir() -> str:
    """The folder the application itself lives in."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def is_portable() -> bool:
    """Portable builds ship a marker file and keep their data beside the exe."""
    return os.path.isfile(os.path.join(app_dir(), PORTABLE_MARKER))


def config_dir() -> str:
    if is_portable():
        path = os.path.join(app_dir(), PORTABLE_DATA)
    else:
        root = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(root, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


# --------------------------------------------------------------------------
# installations
# --------------------------------------------------------------------------

@dataclass
class BlenderInstall:
    path: str
    version: str = ""
    source: str = ""

    @property
    def key(self) -> str:
        return os.path.normcase(os.path.abspath(self.path))

    @property
    def label(self) -> str:
        if self.version:
            return f"Blender {self.version}"
        return os.path.basename(os.path.dirname(self.path)) or self.path

    @property
    def detail(self) -> str:
        return f"{self.label}  -  {self.path}"


_VERSION_RE = re.compile(r"Blender\s+(\d+\.\d+(?:\.\d+)?)", re.I)


def probe_version(exe: str, timeout: float = 25.0) -> str:
    """`blender --version` returns without loading add-ons, so this stays quick."""
    try:
        proc = subprocess.run(
            [exe, "--version"],
            capture_output=True, text=True, timeout=timeout,
            # stdin must be redirected explicitly: a windowed build has no
            # console, so the child would inherit an invalid handle and hang.
            stdin=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
        )
    except Exception:
        return ""
    match = _VERSION_RE.search(proc.stdout or "")
    return match.group(1) if match else ""


def _candidate_paths() -> list:
    found = []

    def add(path, source):
        if path and os.path.isfile(path):
            found.append((os.path.normcase(os.path.abspath(path)), path, source))

    if os.name == "nt":
        for root in (os.environ.get("PROGRAMFILES", r"C:\Program Files"),
                     os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")):
            base = os.path.join(root, "Blender Foundation")
            if os.path.isdir(base):
                for entry in sorted(os.listdir(base)):
                    add(os.path.join(base, entry, "blender.exe"), "Program Files")
            steam = os.path.join(root, "Steam", "steamapps", "common", "Blender", "blender.exe")
            add(steam, "Steam")

        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"SOFTWARE\Classes\blendfile\shell\open\command") as key:
                command = winreg.QueryValueEx(key, "")[0]
            match = re.search(r'"([^"]+)"', command)
            if match:
                exe = match.group(1).replace("blender-launcher.exe", "blender.exe")
                add(exe, "Registry")
        except Exception:
            pass

    exe_name = "blender.exe" if os.name == "nt" else "blender"
    for directory in (os.environ.get("PATH") or "").split(os.pathsep):
        if directory.strip():
            add(os.path.join(directory.strip(), exe_name), "PATH")

    if os.name != "nt":
        for path in ("/usr/bin/blender", "/usr/local/bin/blender",
                     "/Applications/Blender.app/Contents/MacOS/Blender"):
            add(path, "System")

    seen, unique = set(), []
    for norm, path, source in found:
        if norm not in seen:
            seen.add(norm)
            unique.append((path, source))
    return unique


def discover(extra_paths=()) -> list:
    """All Blender installations we can find, newest version first."""
    installs = []
    for path, source in _candidate_paths():
        installs.append(BlenderInstall(path, probe_version(path), source))
    for path in extra_paths:
        if os.path.isfile(path) and not any(
                i.key == os.path.normcase(os.path.abspath(path)) for i in installs):
            installs.append(BlenderInstall(path, probe_version(path), "Custom"))

    def sort_key(install):
        parts = [int(p) for p in install.version.split(".")] if install.version else [0]
        return tuple(parts + [0, 0])[:3]

    installs.sort(key=sort_key, reverse=True)
    return installs


# --------------------------------------------------------------------------
# command lines
# --------------------------------------------------------------------------

def inspect_command(exe: str, blend_file: str, request_file: str, out_file: str,
                    factory_startup: bool = True) -> list:
    command = [exe, "-b", blend_file]
    if factory_startup:
        command.append("--factory-startup")
    command += ["--python", script_path("bq_inspect.py"), "--",
                "--request", request_file, "--out", out_file]
    return command


def analyze_command(exe: str, blend_file: str, out_file: str,
                    scene: str = "", factory_startup: bool = True) -> list:
    command = [exe, "-b", blend_file]
    if factory_startup:
        command.append("--factory-startup")
    command += ["--python", script_path("bq_analyze.py"), "--", "--out", out_file]
    if scene:
        command += ["--scene", scene]
    return command


def render_command(exe: str, blend_file: str, config_file: str,
                   factory_startup: bool = True, extra_args=()) -> list:
    command = [exe, "-b", blend_file]
    if factory_startup:
        command.append("--factory-startup")
    command += ["--python", script_path("bq_render.py")]
    command += list(extra_args)
    command += ["--", "--config", config_file]
    return command


def encode_command(exe: str, blend_file: str, manifest: str,
                   factory_startup: bool = True) -> list:
    command = [exe, "-b", blend_file]
    if factory_startup:
        command.append("--factory-startup")
    return command + ["--python-exit-code", "1", "--python", script_path("bq_encode.py"),
                      "--", "--manifest", manifest]


FACTORY_STARTUP_HELP = (
    "Runs Blender with --factory-startup, ignoring your user preferences and "
    "add-ons.\n\nLeave this on unless a scene needs an add-on to render. Some "
    "add-ons (BlenderKit and MCP bridges in particular) stall or slow down "
    "background renders badly."
)
