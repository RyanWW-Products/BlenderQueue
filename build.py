"""Build both distributions.

    python build.py              # everything
    python build.py --portable   # portable folder + zip only
    python build.py --installer  # setup .exe only
    python build.py --skip-checks

Produces, in dist/:
    BlenderQueue/                         the raw PyInstaller build
    BlenderQueue-<ver>-portable/          same, plus a portable.txt marker
    BlenderQueue-<ver>-portable.zip       that folder, zipped
    BlenderQueue-<ver>-Setup.exe          Inno Setup installer

The portable build keeps its settings in BlenderQueueData next to the exe, so
it leaves nothing behind on the machine it runs on. The installed build uses
%APPDATA%\\BlenderQueue like a normal Windows application.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST = os.path.join(ROOT, "dist")
BUILD_NAME = "BlenderQueue"
RAW_DIST = os.path.join(DIST, BUILD_NAME)

INNO_CANDIDATES = (
    r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    r"C:\Program Files\Inno Setup 6\ISCC.exe",
)

PORTABLE_README = """BlenderQueue - portable build
=============================

Run BlenderQueue.exe from this folder. Nothing is installed.

Settings, the autosaved queue and the startup log are kept in the
BlenderQueueData folder next to the executable, so you can carry the whole
thing on a USB stick and leave no trace on the host machine.

Delete portable.txt to make this build behave like a normal installation and
store its settings in %APPDATA%\\BlenderQueue instead.

Keep the _internal folder next to the executable.

Blender itself is not included. BlenderQueue finds your existing installs, or
you can point it at any blender.exe from the Render tab.
"""


def version() -> str:
    scope = {}
    with open(os.path.join(ROOT, "blenderqueue", "__init__.py"), encoding="utf-8") as fh:
        exec(fh.read(), scope)
    return scope.get("__version__", "0.0.0")


def run(command, **kwargs):
    print("  $", " ".join(str(c) for c in command))
    result = subprocess.run(command, cwd=ROOT, **kwargs)
    if result.returncode != 0:
        raise SystemExit(f"command failed with {result.returncode}")
    return result


def step(text: str):
    print("\n" + "=" * 66)
    print(text)
    print("=" * 66)


# --------------------------------------------------------------------------

def check_sources():
    """Never package something that does not import."""
    step("Checking sources")
    run([sys.executable, "-m", "compileall", "-q", "blenderqueue", "main.py"])
    result = subprocess.run([sys.executable, "-m", "pyflakes", "blenderqueue", "main.py"],
                            cwd=ROOT, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
        raise SystemExit("pyflakes reported problems; fix them before building")
    print("  sources compile cleanly")


def build_exe():
    step("Running PyInstaller")
    run([sys.executable, "-m", "PyInstaller", "BlenderQueue.spec",
         "--noconfirm", "--log-level", "WARN"])
    exe = os.path.join(RAW_DIST, "BlenderQueue.exe")
    if not os.path.isfile(exe):
        raise SystemExit("PyInstaller did not produce " + exe)
    print("  built", exe)


def verify_build():
    """Run the packaged executable's own self-test before shipping it."""
    step("Verifying the packaged build")
    handle, report = tempfile.mkstemp(prefix="bq_selftest_", suffix=".json")
    os.close(handle)
    exe = os.path.join(RAW_DIST, "BlenderQueue.exe")
    result = subprocess.run([exe, "--selftest", report], cwd=ROOT)
    ok = False
    try:
        import json
        with open(report, encoding="utf-8") as fh:
            data = json.load(fh)
        ok = bool(data.get("ok"))
        for name, entry in (data.get("checks") or {}).items():
            print("  {} {}".format("ok  " if entry["ok"] else "FAIL", name))
        if data.get("error"):
            print(data["error"])
    except Exception as exc:
        print("  could not read the self-test report:", exc)
    finally:
        try:
            os.remove(report)
        except OSError:
            pass
    if result.returncode != 0 or not ok:
        raise SystemExit("the packaged build failed its self-test")
    print("  self-test passed")


def build_portable(ver: str) -> str:
    step("Building the portable distribution")
    target = os.path.join(DIST, f"BlenderQueue-{ver}-portable")
    if os.path.isdir(target):
        shutil.rmtree(target)
    shutil.copytree(RAW_DIST, target)

    with open(os.path.join(target, "portable.txt"), "w", encoding="utf-8") as fh:
        fh.write("Settings live in BlenderQueueData next to this file.\n"
                 "Delete this marker to use %APPDATA% instead.\n")
    with open(os.path.join(target, "README.txt"), "w", encoding="utf-8") as fh:
        fh.write(PORTABLE_README)
    for extra in ("README.md",):
        source = os.path.join(ROOT, extra)
        if os.path.isfile(source):
            shutil.copy2(source, target)

    archive = target + ".zip"
    if os.path.isfile(archive):
        os.remove(archive)
    print("  zipping...")
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for folder, _dirs, files in os.walk(target):
            for name in files:
                full = os.path.join(folder, name)
                zf.write(full, os.path.join(
                    os.path.basename(target), os.path.relpath(full, target)))
    print("  portable folder:", target)
    print("  portable zip   :", archive,
          f"({os.path.getsize(archive) / 1048576:.1f} MB)")
    return archive


def find_inno() -> str:
    for path in INNO_CANDIDATES:
        if os.path.isfile(path):
            return path
    found = shutil.which("ISCC.exe") or shutil.which("iscc")
    return found or ""


def build_installer(ver: str) -> str:
    step("Building the installer")
    iscc = find_inno()
    if not iscc:
        print("  Inno Setup (ISCC.exe) was not found - skipping the installer.")
        print("  Install it from https://jrsoftware.org/isdl.php and re-run.")
        return ""
    run([iscc, f"/DMyAppVersion={ver}", "installer.iss"])
    setup = os.path.join(DIST, f"BlenderQueue-{ver}-Setup.exe")
    if not os.path.isfile(setup):
        raise SystemExit("Inno Setup did not produce " + setup)
    print("  installer:", setup,
          f"({os.path.getsize(setup) / 1048576:.1f} MB)")
    return setup


# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Build BlenderQueue distributions")
    parser.add_argument("--portable", action="store_true", help="portable build only")
    parser.add_argument("--installer", action="store_true", help="installer only")
    parser.add_argument("--skip-checks", action="store_true",
                        help="skip the compile and self-test gates")
    parser.add_argument("--no-build", action="store_true",
                        help="reuse the existing dist/BlenderQueue folder")
    args = parser.parse_args()

    both = not (args.portable or args.installer)
    ver = version()
    print(f"BlenderQueue {ver}")

    if not args.no_build:
        if not args.skip_checks:
            check_sources()
        build_exe()
        if not args.skip_checks:
            verify_build()
    elif not os.path.isdir(RAW_DIST):
        raise SystemExit("--no-build needs an existing " + RAW_DIST)

    made = []
    if both or args.portable:
        made.append(build_portable(ver))
    if both or args.installer:
        setup = build_installer(ver)
        if setup:
            made.append(setup)

    step("Done")
    for path in made:
        print("  ", path)
    if not made:
        print("  nothing was produced")


if __name__ == "__main__":
    main()
