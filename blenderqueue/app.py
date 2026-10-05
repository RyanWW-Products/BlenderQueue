"""Application bootstrap."""

from __future__ import annotations

import sys

import json
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .ui import theme
from .ui.main_window import MainWindow


def selftest(report_path: str) -> int:
    """Build the whole UI offscreen and confirm the packaged bits are present.

    Used to smoke-test the frozen executable, which has no console to print to.
    Run it with:  BlenderQueue.exe --selftest report.json
    """
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from . import blender, schema

    report = {"ok": False, "checks": {}}

    def record(name, value, ok=None):
        report["checks"][name] = {"value": value, "ok": bool(value if ok is None else ok)}

    try:
        app = QApplication([])
        app.setStyleSheet(theme.STYLESHEET)

        record("frozen", bool(getattr(sys, "frozen", False)))
        record("resource_dir", blender.resource_dir(),
               os.path.isdir(blender.resource_dir()))
        for name in ("bq_inspect.py", "bq_render.py", "bq_analyze.py", "bq_visibility.py",
                     "bq_video.py", "bq_encode.py"):
            path = blender.script_path(name)
            record("script:" + name, path, os.path.isfile(path))

        window = MainWindow()
        record("window", window.windowTitle())
        record("ribbon_tabs", window.ribbon.count(), window.ribbon.count() == 4)
        record("override_groups", len(window.overrides._groups),
               len(window.overrides._groups) == len(schema.GROUPS))
        record("override_fields", len(window.overrides._editors),
               len(window.overrides._editors) == len(schema.FIELD_BY_KEY))
        record("icons", not theme.icon("path", theme.ACCENT, 32).isNull())
        record("detail_tabs", window.detail.count(), window.detail.count() == 5)
        record("visibility_tab", window.detail.tabText(window.detail.indexOf(window.visibility_panel)),
               window.detail.indexOf(window.visibility_panel) >= 0)
        from .ui.update_dialog import UpdateDialog
        record("updates", UpdateDialog.__name__, window.act_updates.isEnabled())

        installs = blender.discover()
        record("blender_installs", [i.detail for i in installs], True)

        report["ok"] = all(c["ok"] for c in report["checks"].values())
    except Exception:
        import traceback
        report["error"] = traceback.format_exc()

    with open(report_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1)
    return 0 if report["ok"] else 1


def _install_excepthook(app):
    """Log unhandled exceptions instead of losing them.

    A packaged GUI app has no console. Worse, an exception raised inside a
    paint or event handler surfaces at whatever is spinning the event loop at
    the time -- a modal dialog, for instance -- so it can break a feature that
    has nothing to do with the actual fault. Recording them makes that kind of
    thing findable.
    """
    import traceback

    from . import diag

    def hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        diag.log("UNHANDLED EXCEPTION " + text)
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = hook


def run(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)

    if "--selftest" in argv:
        index = argv.index("--selftest")
        target = argv[index + 1] if index + 1 < len(argv) else "selftest.json"
        return selftest(target)

    QApplication.setAttribute(Qt.AA_DontUseNativeMenuBar, False)
    app = QApplication(argv)
    app.setApplicationName("BlenderQueue")
    app.setOrganizationName("BlenderQueue")
    app.setApplicationDisplayName("BlenderQueue")
    app.setStyle("Fusion")
    app.setStyleSheet(theme.STYLESHEET)
    app.setWindowIcon(theme.app_icon())

    from . import diag
    diag.reset()
    _install_excepthook(app)
    diag.log("creating main window")
    window = MainWindow()
    window.restore_geometry()
    window.show()
    diag.log("window shown")

    # .blend files passed on the command line (or via "Open with") get queued.
    files = [a for a in argv[1:] if a.lower().endswith((".blend", ".bqueue"))]
    if files:
        window.add_paths([f for f in files if f.lower().endswith(".blend")])

    return app.exec()
