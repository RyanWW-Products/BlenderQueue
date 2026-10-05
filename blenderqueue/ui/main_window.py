"""The application window: ribbon, queue, detail panel, status bar."""

from __future__ import annotations

import os
import subprocess

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog,
                               QFrame, QHBoxLayout, QLabel, QLineEdit, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit, QProgressBar,
                               QSplitter, QTabWidget, QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from .. import blender, diag, store
from ..models import Job, Status, unique_name
from ..runner import Analyzer, Inspector, QueueRunner, format_duration
from . import theme
from .analysis_panel import AnalysisPanel
from .follow_path_dialog import FollowPathDialog
from .overrides_panel import OverridesPanel
from .queue_view import QueueView
from .ribbon import Ribbon, make_action
from .visibility_panel import VisibilityPanel

BLEND_FILTER = "Blender files (*.blend);;All files (*)"
QUEUE_FILTER = "BlenderQueue files (*.bqueue);;All files (*)"


class MainWindow(QMainWindow):
    """Everything the user sees."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("BlenderQueue")
        self.setWindowIcon(theme.app_icon())
        self.resize(1420, 880)
        self.setAcceptDrops(True)

        self.settings = store.load_settings()
        self.jobs: list = []
        self.logs: dict = {}
        self.installs: list = []
        self._current_queue_path = self.settings.last_queue_path
        self._close_after_run = False

        self.inspector = Inspector(self)
        self.inspector.finished.connect(self._on_inspected)
        self.inspector.progress.connect(self._on_inspect_progress)

        self.analyzer = Analyzer(self)
        self.analyzer.finished.connect(self._on_analyzed)
        self.analyzer.progress.connect(self._on_inspect_progress)

        self.runner = QueueRunner(self.settings, self)
        self.runner.jobStarted.connect(self._on_job_started)
        self.runner.jobProgress.connect(self._on_job_progress)
        self.runner.jobFinished.connect(self._on_job_finished)
        self.runner.queueFinished.connect(self._on_queue_finished)
        self.runner.log.connect(self._append_log)
        self.runner.stateChanged.connect(self._sync_actions)
        self.runner.recoveryAvailable.connect(self._on_recovery_available)

        self._build_actions()
        self._build_ui()
        self._sync_actions()

        QTimer.singleShot(0, self._first_run)

    # ==================================================================
    # construction
    # ==================================================================

    def _build_actions(self):
        A = lambda *a, **k: make_action(self, *a, **k)  # noqa: E731

        self.act_add_files = A("Add Files", "add-file", "Queue one or more .blend files", "Ctrl+O")
        self.act_add_folder = A("Add Folder", "add-folder", "Queue every .blend in a folder")
        self.act_remove = A("Remove", "remove", "Remove the selected jobs", "Del")
        self.act_duplicate = A("Duplicate", "duplicate", "Copy the selected jobs", "Ctrl+D")
        self.act_rename = A("Rename", "rename", "Rename the selected job", "F2")
        self.act_clear = A("Clear", "clear", "Remove every job from the queue")

        self.act_up = A("Up", "up", "", "Ctrl+Up")
        self.act_down = A("Down", "down", "", "Ctrl+Down")
        self.act_top = A("To Top", "top", "", "Ctrl+Home")
        self.act_bottom = A("To Bottom", "bottom", "", "Ctrl+End")

        self.act_enable_all = A("Enable All", "check", "Include every job in the next run")
        self.act_disable_all = A("Disable All", "clear", "Exclude every job")
        self.act_toggle = A("Toggle", "queue", "Flip the selected jobs on or off", "Space")

        self.act_new_queue = A("New", "file", "Start an empty queue", "Ctrl+N")
        self.act_open_queue = A("Open", "open", "Load a saved queue", "Ctrl+Shift+O")
        self.act_save_queue = A("Save As", "save", "Save this queue to a file", "Ctrl+S")

        self.act_start = A("Start", "play", "Render enabled Pending jobs in order", "F5")
        self.act_reset = A("Reset Selected", "refresh", "Reset selected jobs to Pending and render them again")
        self.act_pause = A("Pause", "pause", "Stop after the current job finishes",
                           checkable=True)
        self.act_stop = A("Stop", "stop", "Abandon the queue now", "Shift+F5")
        self.act_skip = A("Skip Job", "skip", "Give up on the current job and move on")
        self.act_validate = A("Dry Run", "check",
                              "Apply the overrides without rendering, to check them")

        self.act_follow = A("Follow Paths", "path",
                            "Change which curve each object follows", "Ctrl+P")
        self.act_variants = A("Per-Path Jobs", "duplicate",
                              "Fan a job out into one render per path")
        self.act_inspect = A("Read File", "refresh",
                             "Re-read scenes, cameras and paths from the .blend", "F6")
        self.act_open_output = A("Output", "folder-open",
                                 "Open where this job writes its frames")
        self.act_open_blender = A("In Blender", "app", "Open this .blend in Blender")
        self.act_copy_settings = A("Copy Settings", "duplicate",
                                   "Copy the first selected job's overrides onto the rest")
        self.act_about = A("About", "info", "Version and help")
        self.act_updates = A("Updates", "refresh", "Check GitHub for the latest BlenderQueue release")

        self.act_analyze = A("Analyse", "engine",
                             "Measure what will make this file slow to render", "F7")
        self.act_analyze_all = A("Analyse All", "engine",
                                 "Analyse every job in the queue")
        self.act_add_analyze = A("Add and Analyse", "add-file",
                                 "Add .blend files and analyse them straight away")
        self.act_export_report = A("Export Report", "save",
                                   "Save this analysis as a text file")

        # Ribbon buttons live on tab pages, and a QAction only answers its
        # shortcut while the widget holding it is visible.  Registering every
        # action on the window keeps the shortcuts working whichever ribbon
        # tab happens to be open.
        for name in dir(self):
            if name.startswith("act_"):
                action = getattr(self, name)
                action.setShortcutContext(Qt.WindowShortcut)
                self.addAction(action)

    def _build_ui(self):
        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        ribbon_host = QFrame(central)
        ribbon_host.setObjectName("RibbonBar")
        ribbon_layout = QVBoxLayout(ribbon_host)
        ribbon_layout.setContentsMargins(0, 0, 0, 0)
        self.ribbon = Ribbon(ribbon_host)
        ribbon_layout.addWidget(self.ribbon)
        layout.addWidget(ribbon_host)

        self._build_ribbon()

        splitter = QSplitter(Qt.Horizontal, central)
        splitter.setChildrenCollapsible(False)

        self.queue_view = QueueView(splitter)
        self.queue_view.orderChanged.connect(self._on_reordered)
        self.queue_view.renamed.connect(self._on_renamed)
        self.queue_view.enabledToggled.connect(self._on_enabled_toggled)
        self.queue_view.itemSelectionChanged.connect(self._on_selection)
        self.queue_view.currentItemChanged.connect(lambda *_: self._on_selection())
        self.queue_view.activated_job.connect(lambda _id: self.detail.setCurrentIndex(0))
        self.queue_view.customContextMenuRequested.connect(self._context_menu)
        splitter.addWidget(self.queue_view)

        splitter.addWidget(self._build_detail(splitter))
        splitter.setSizes([840, 560])
        self.splitter = splitter
        layout.addWidget(splitter, 1)

        self.setCentralWidget(central)
        self._build_status_bar()

    def _build_ribbon(self):
        # ---- Queue -------------------------------------------------
        tab = self.ribbon.add_tab("Queue")
        group = tab.add_group("Add")
        group.add_big(self.act_add_files)
        group.add_big(self.act_add_folder)

        group = tab.add_group("Order")
        group.add_big(self.act_up, 62)
        group.add_big(self.act_down, 62)
        group.add_stack(self.act_top, self.act_bottom)

        group = tab.add_group("Edit")
        group.add_big(self.act_rename)
        group.add_big(self.act_duplicate)
        group.add_big(self.act_remove)

        group = tab.add_group("Include")
        group.add_stack(self.act_enable_all, self.act_disable_all, self.act_toggle)

        group = tab.add_group("Queue File")
        group.add_stack(self.act_new_queue, self.act_open_queue, self.act_save_queue)
        group.add_big(self.act_clear)

        # ---- Render ------------------------------------------------
        tab = self.ribbon.add_tab("Render")
        group = tab.add_group("Run")
        group.add_big(self.act_start)
        group.add_big(self.act_pause)
        group.add_big(self.act_stop)
        group.add_big(self.act_skip)

        group = tab.add_group("Restart")
        group.add_big(self.act_reset, 105)

        group = tab.add_group("Blender")
        picker = QWidget()
        picker_layout = QVBoxLayout(picker)
        picker_layout.setContentsMargins(0, 2, 0, 0)
        picker_layout.setSpacing(4)
        self.version_box = QComboBox()
        self.version_box.setMinimumWidth(210)
        self.version_box.setToolTip("Which Blender build renders jobs that do not "
                                    "pick their own")
        self.version_box.currentIndexChanged.connect(self._on_default_blender_changed)
        picker_layout.addWidget(self.version_box)
        self.factory_box = QCheckBox("Ignore add-ons and preferences")
        self.factory_box.setChecked(self.settings.factory_startup)
        self.factory_box.setToolTip(blender.FACTORY_STARTUP_HELP)
        self.factory_box.toggled.connect(self._on_factory_toggled)
        picker_layout.addWidget(self.factory_box)
        browse = QToolButton()
        browse.setText("Add a Blender build...")
        browse.setToolButtonStyle(Qt.ToolButtonTextOnly)
        browse.clicked.connect(self._browse_blender)
        picker_layout.addWidget(browse)
        picker_layout.addStretch(1)
        group.add_widget(picker)

        group = tab.add_group("When Finished")
        options = QWidget()
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(0, 2, 0, 0)
        options_layout.setSpacing(4)
        self.stop_on_error_box = QCheckBox("Stop the queue on an error")
        self.stop_on_error_box.setChecked(self.settings.stop_on_error)
        self.stop_on_error_box.toggled.connect(self._on_stop_on_error)
        options_layout.addWidget(self.stop_on_error_box)
        self.open_output_box = QCheckBox("Open the output folder")
        self.open_output_box.setChecked(self.settings.auto_open_output)
        self.open_output_box.toggled.connect(self._on_auto_open)
        options_layout.addWidget(self.open_output_box)
        self.shutdown_box = QCheckBox("Shut down this PC")
        self.shutdown_box.setChecked(False)
        self.shutdown_box.setToolTip("Shuts down 60 seconds after the queue finishes, "
                                     "with a chance to cancel.")
        options_layout.addWidget(self.shutdown_box)
        options_layout.addStretch(1)
        group.add_widget(options)

        group = tab.add_group("Check")
        group.add_big(self.act_validate)

        # ---- Tools -------------------------------------------------
        tab = self.ribbon.add_tab("Tools")
        group = tab.add_group("Follow Path")
        group.add_big(self.act_follow, 100)
        group.add_big(self.act_variants, 100)

        group = tab.add_group("File")
        group.add_big(self.act_inspect)
        group.add_big(self.act_open_output, 82)
        group.add_big(self.act_open_blender, 82)

        group = tab.add_group("Batch")
        group.add_big(self.act_copy_settings, 100)

        group = tab.add_group("Help")
        group.add_big(self.act_about)
        group.add_big(self.act_updates)

        # ---- Analysis ----------------------------------------------
        tab = self.ribbon.add_tab("Analysis")
        group = tab.add_group("Measure")
        group.add_big(self.act_analyze)
        group.add_big(self.act_analyze_all, 92)

        group = tab.add_group("Add")
        group.add_big(self.act_add_analyze, 100)

        group = tab.add_group("Report")
        group.add_big(self.act_export_report, 92)

        group = tab.add_group("What this does")
        legend = QLabel(
            "Opens the .blend read-only and measures sampling, geometry,\n"
            "textures, lighting, shading, effects and output settings,\n"
            "then rates the load and suggests what to change.")
        legend.setObjectName("Hint")
        group.add_widget(legend)

        # ---- wiring ------------------------------------------------
        self.act_add_files.triggered.connect(self.add_files)
        self.act_add_folder.triggered.connect(self.add_folder)
        self.act_remove.triggered.connect(self.remove_selected)
        self.act_duplicate.triggered.connect(self.duplicate_selected)
        self.act_rename.triggered.connect(self.rename_selected)
        self.act_clear.triggered.connect(self.clear_queue)
        self.act_up.triggered.connect(lambda: self.move_selected(-1))
        self.act_down.triggered.connect(lambda: self.move_selected(1))
        self.act_top.triggered.connect(lambda: self.move_selected(-10 ** 6))
        self.act_bottom.triggered.connect(lambda: self.move_selected(10 ** 6))
        self.act_enable_all.triggered.connect(lambda: self.set_all_enabled(True))
        self.act_disable_all.triggered.connect(lambda: self.set_all_enabled(False))
        self.act_toggle.triggered.connect(self.toggle_selected)
        self.act_new_queue.triggered.connect(self.new_queue)
        self.act_open_queue.triggered.connect(self.open_queue)
        self.act_save_queue.triggered.connect(self.save_queue_as)
        self.act_start.triggered.connect(self.start_render)
        self.act_reset.triggered.connect(self.reset_selected)
        self.act_pause.toggled.connect(self.runner.set_paused)
        self.act_stop.triggered.connect(self.stop_render)
        self.act_skip.triggered.connect(self.runner.skip)
        self.act_validate.triggered.connect(self.dry_run)
        self.act_follow.triggered.connect(self.open_follow_paths)
        self.act_variants.triggered.connect(self.open_follow_paths)
        self.act_inspect.triggered.connect(self.inspect_selected)
        self.act_open_output.triggered.connect(self.open_output_folder)
        self.act_open_blender.triggered.connect(self.open_in_blender)
        self.act_copy_settings.triggered.connect(self.copy_overrides)
        self.act_about.triggered.connect(self.show_about)
        self.act_updates.triggered.connect(self.show_updates)
        self.act_analyze.triggered.connect(self.analyze_selected)
        self.act_analyze_all.triggered.connect(self.analyze_all)
        self.act_add_analyze.triggered.connect(self.add_and_analyze)
        self.act_export_report.triggered.connect(self.export_report)

    def _build_detail(self, parent) -> QWidget:
        panel = QWidget(parent)
        panel.setObjectName("DetailPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget(panel)
        header.setObjectName("PanelHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(10, 8, 10, 8)
        header_layout.setSpacing(3)

        self.detail_title = QLabel("No job selected")
        self.detail_title.setStyleSheet("font-weight:600; font-size:11pt;")
        header_layout.addWidget(self.detail_title)

        self.detail_path = QLabel("")
        self.detail_path.setObjectName("Hint")
        self.detail_path.setWordWrap(True)
        header_layout.addWidget(self.detail_path)

        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(QLabel("Render with"))
        self.job_version_box = QComboBox()
        self.job_version_box.setToolTip("Use a specific Blender build for this job")
        self.job_version_box.currentIndexChanged.connect(self._on_job_blender_changed)
        row.addWidget(self.job_version_box, 1)
        header_layout.addLayout(row)

        self.notes_edit = QLineEdit()
        self.notes_edit.setPlaceholderText("Notes for this job (optional)")
        self.notes_edit.editingFinished.connect(self._on_notes_changed)
        header_layout.addWidget(self.notes_edit)

        layout.addWidget(header)

        self.detail = QTabWidget(panel)
        self.overrides = OverridesPanel(self.detail)
        self.overrides.changed.connect(self._on_overrides_changed)
        self.detail.addTab(self.overrides, "Render Settings")

        self.visibility_panel = VisibilityPanel(self.detail)
        self.visibility_panel.changed.connect(self._on_visibility_changed)
        self.visibility_panel.inspectRequested.connect(self._inspect_visibility)
        self.detail.addTab(self.visibility_panel, "Per Job Visibility")

        self.analysis_panel = AnalysisPanel(self.detail)
        self.analysis_panel.analyzeRequested.connect(self.analyze_selected)
        self.detail.addTab(self.analysis_panel, "Analysis")

        self.info_tree = QTreeWidget(self.detail)
        self.info_tree.setHeaderLabels(("Property", "Value"))
        self.info_tree.setAlternatingRowColors(True)
        self.info_tree.setColumnWidth(0, 200)
        self.detail.addTab(self.info_tree, "File Contents")

        self.log_view = QPlainTextEdit(self.detail)
        self.log_view.setObjectName("LogView")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(self.settings.keep_log_lines)
        self.detail.addTab(self.log_view, "Log")

        layout.addWidget(self.detail, 1)
        return panel

    def _build_status_bar(self):
        bar = self.statusBar()
        self.status_label = QLabel("Ready")
        bar.addWidget(self.status_label, 1)

        self.overall_bar = QProgressBar()
        self.overall_bar.setFixedWidth(190)
        self.overall_bar.setRange(0, 100)
        self.overall_bar.setValue(0)
        self.overall_bar.setVisible(False)
        bar.addPermanentWidget(self.overall_bar)

        self.eta_label = QLabel("")
        self.eta_label.setToolTip("Estimated time left for the job being rendered")
        bar.addPermanentWidget(self.eta_label)

        self.counts_label = QLabel("")
        bar.addPermanentWidget(self.counts_label)

    # ==================================================================
    # startup
    # ==================================================================

    def _first_run(self):
        """Paint the window first, then go looking for Blender.

        Discovery shells out to every blender.exe it can find, so it must not
        run inline here: the window would sit unpainted until it finished.
        A second deferred call lets Qt finish its own startup work first.
        """
        diag.log("_first_run: begin")
        self.status_label.setText("Looking for Blender...")
        QTimer.singleShot(30, self._discover_then_load)

    def _discover_then_load(self):
        diag.log("_discover: begin")
        try:
            self.refresh_installs()
        except Exception as exc:
            diag.log(f"_discover: FAILED {exc!r}")
            self.status_label.setText(f"Could not look for Blender: {exc}")
            return
        diag.log(f"_discover: found {len(self.installs)} install(s)")

        # Files passed on the command line are already queued by this point;
        # only fall back to the autosave when nothing is loaded.
        restored = [] if self.jobs else store.try_load_autosave()
        if restored:
            self.jobs = restored
            self.refresh_list()
            self.queue_view.select_ids([restored[0].id])
            self.status_label.setText(f"Restored {len(restored)} job(s) from the last session")
        elif self.jobs:
            diag.log("_first_run: refreshing list for command-line jobs")
            self.refresh_list()
            self.queue_view.select_ids([self.jobs[0].id])
            diag.log("_first_run: queueing inspection")
            for job in self.jobs:
                self.queue_job_inspection(job)
            self.status_label.setText(f"{len(self.jobs)} job(s) queued")
        elif not self.installs:
            self.status_label.setText("No Blender installation found - add one on the Render tab")
        else:
            self.status_label.setText("Ready - add .blend files to get started")
        self._update_counts()
        diag.log("_first_run: complete")

    def refresh_installs(self):
        self.installs = blender.discover(self.settings.custom_blender_paths)
        keys = {i.key for i in self.installs}
        if self.settings.default_blender not in keys:
            self.settings.default_blender = self.installs[0].key if self.installs else ""

        for box, include_default in ((self.version_box, False), (self.job_version_box, True)):
            box.blockSignals(True)
            box.clear()
            if include_default:
                box.addItem("Application default", "")
            for install in self.installs:
                box.addItem(f"{install.label}   ({install.source})", install.key)
            box.blockSignals(False)

        index = self.version_box.findData(self.settings.default_blender)
        self.version_box.blockSignals(True)
        self.version_box.setCurrentIndex(max(0, index))
        self.version_box.blockSignals(False)
        self._sync_actions()

    def exe_for(self, job: Job) -> str:
        key = job.blender_key or self.settings.default_blender
        for install in self.installs:
            if install.key == key:
                return install.path
        return self.installs[0].path if self.installs else ""

    def _blender_label(self, job: Job) -> str:
        if not job.blender_key:
            return ""
        for install in self.installs:
            if install.key == job.blender_key:
                return install.label
        return "missing"

    # ==================================================================
    # queue editing
    # ==================================================================

    def refresh_list(self):
        self.queue_view.rebuild(self.jobs, self._blender_label)
        self._update_counts()
        self._sync_actions()
        self.autosave()

    def refresh_row(self, job: Job):
        try:
            index = self.jobs.index(job)
        except ValueError:
            return
        self.queue_view.update_job(job, index, self._blender_label)

    def job_by_id(self, job_id: str):
        for job in self.jobs:
            if job.id == job_id:
                return job
        return None

    def selected_jobs(self) -> list:
        ids = self.queue_view.selected_ids()
        return [j for j in self.jobs if j.id in ids]

    def current_job(self):
        return self.job_by_id(self.queue_view.current_id())

    def add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Add Blender files", self.settings.last_browse_dir, BLEND_FILTER)
        if paths:
            self.settings.last_browse_dir = os.path.dirname(paths[0])
            self.add_paths(paths)

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Add every .blend in a folder", self.settings.last_browse_dir)
        if not folder:
            return
        self.settings.last_browse_dir = folder
        found = []
        for root, _dirs, files in os.walk(folder):
            found += [os.path.join(root, f) for f in sorted(files)
                      if f.lower().endswith(".blend")]
        if not found:
            QMessageBox.information(self, "Nothing found",
                                    "No .blend files in that folder.")
            return
        self.add_paths(found)

    def add_paths(self, paths: list):
        taken = {job.name for job in self.jobs}
        added = []
        for path in paths:
            if not path.lower().endswith(".blend"):
                continue
            job = Job(blend_path=os.path.abspath(path))
            job.name = unique_name(job.name, taken)
            taken.add(job.name)
            self.jobs.append(job)
            added.append(job)

        if not added:
            return
        self.refresh_list()
        self.queue_view.select_ids([added[-1].id])
        for job in added:
            self.queue_job_inspection(job)
        self.status_label.setText(f"Added {len(added)} job(s)")

    def remove_selected(self):
        jobs = self.selected_jobs()
        if not jobs:
            return
        if self.settings.confirm_delete:
            names = "\n".join("  " + j.name for j in jobs[:8])
            if len(jobs) > 8:
                names += f"\n  ... and {len(jobs) - 8} more"
            box = QMessageBox(QMessageBox.Question, "Remove jobs",
                              f"Remove {len(jobs)} job(s) from the queue?\n\n{names}",
                              QMessageBox.Yes | QMessageBox.No, self)
            skip = QCheckBox("Do not ask again")
            box.setCheckBox(skip)
            if box.exec() != QMessageBox.Yes:
                return
            if skip.isChecked():
                self.settings.confirm_delete = False
        running = self.runner.current_job
        for job in jobs:
            if running is not None and job.id == running.id:
                continue
            self.jobs.remove(job)
            self.logs.pop(job.id, None)
        self.refresh_list()
        self._on_selection()

    def duplicate_selected(self):
        jobs = self.selected_jobs()
        if not jobs:
            return
        taken = {j.name for j in self.jobs}
        created = []
        for job in jobs:
            clone = job.duplicate()
            clone.name = unique_name(clone.name, taken)
            taken.add(clone.name)
            self.jobs.insert(self.jobs.index(job) + 1, clone)
            created.append(clone)
        self.refresh_list()
        self.queue_view.select_ids([c.id for c in created])
        self.status_label.setText(f"Duplicated {len(created)} job(s)")

    def rename_selected(self):
        job = self.current_job()
        if job:
            self.queue_view.edit_name(job.id)

    def clear_queue(self):
        if not self.jobs:
            return
        if QMessageBox.question(self, "Clear queue",
                                f"Remove all {len(self.jobs)} jobs?") != QMessageBox.Yes:
            return
        self.jobs = []
        self.logs = {}
        self.refresh_list()
        self._on_selection()

    def move_selected(self, delta: int):
        jobs = self.selected_jobs()
        if not jobs:
            return
        indices = sorted(self.jobs.index(j) for j in jobs)
        order = list(self.jobs)
        if delta < 0:
            for index in indices:
                target = max(0, index + delta) if delta > -10 ** 5 else 0
                while target < index and order[target] in jobs:
                    target += 1
                if target < index:
                    order.insert(target, order.pop(index))
        else:
            for index in reversed(indices):
                target = min(len(order) - 1, index + delta) if delta < 10 ** 5 else len(order) - 1
                while target > index and order[target] in jobs:
                    target -= 1
                if target > index:
                    order.insert(target, order.pop(index))
        self.jobs = order
        self.refresh_list()
        self.queue_view.select_ids([j.id for j in jobs])

    def set_all_enabled(self, enabled: bool):
        for job in self.jobs:
            job.enabled = enabled
        self.refresh_list()

    def toggle_selected(self):
        for job in self.selected_jobs():
            job.enabled = not job.enabled
        self.refresh_list()

    # ==================================================================
    # queue files
    # ==================================================================

    def new_queue(self):
        if self.jobs and QMessageBox.question(
                self, "New queue", "Discard the current queue?") != QMessageBox.Yes:
            return
        self.jobs = []
        self.logs = {}
        self._current_queue_path = ""
        self.refresh_list()
        self._on_selection()

    def open_queue(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open queue",
                                              self.settings.last_browse_dir, QUEUE_FILTER)
        if not path:
            return
        try:
            self.jobs = store.load_queue(path)
        except Exception as exc:
            QMessageBox.critical(self, "Could not open", str(exc))
            return
        self._current_queue_path = path
        self.settings.last_queue_path = path
        self.refresh_list()
        self.status_label.setText(f"Loaded {len(self.jobs)} job(s) from {os.path.basename(path)}")

    def save_queue_as(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save queue", self._current_queue_path or self.settings.last_browse_dir,
            QUEUE_FILTER)
        if not path:
            return
        if not path.lower().endswith(store.QUEUE_SUFFIX):
            path += store.QUEUE_SUFFIX
        try:
            store.save_queue(path, self.jobs)
        except Exception as exc:
            QMessageBox.critical(self, "Could not save", str(exc))
            return
        self._current_queue_path = path
        self.settings.last_queue_path = path
        self.status_label.setText("Saved " + os.path.basename(path))

    def autosave(self):
        try:
            store.save_queue(store.autosave_path(), self.jobs)
        except Exception:
            pass

    # ==================================================================
    # inspection
    # ==================================================================

    def queue_job_inspection(self, job: Job):
        exe = self.exe_for(job)
        if not exe or not job.exists:
                return
        self.inspector.request(job.id, exe, job.blend_path, self.settings.factory_startup)

    def inspect_selected(self):
        jobs = self.selected_jobs() or self.jobs
        for job in jobs:
            self.queue_job_inspection(job)
        if jobs:
            self.status_label.setText(f"Reading {len(jobs)} file(s)...")

    def _on_inspect_progress(self, job_id: str, message: str):
        job = self.job_by_id(job_id)
        if job:
            self.status_label.setText(f"{job.name}: {message}")

    def _on_inspected(self, job_id: str, result: dict):
        job = self.job_by_id(job_id)
        if job is None:
            return
        if not result.get("ok"):
            job.message = "Could not read file"
            self._append_log(job_id, "Inspection failed:\n" + str(result.get("error", "")))
            self.status_label.setText(f"{job.name}: could not read the file")
        else:
            job.info = result
            scene = job.scene_info()
            found = len(scene.get("follow_paths") or [])
            self.status_label.setText(
                "{}: {} scene(s), {} camera(s), {} Follow Path constraint(s)".format(
                    job.name, len(result.get("scenes") or []),
                    len(scene.get("cameras") or []), found))
        self.refresh_row(job)
        if job.id == self.queue_view.current_id():
            self._show_details(job)
        self._sync_actions()

    # ==================================================================
    # rendering
    # ==================================================================

    def start_render(self):
        if self.runner.running:
            return
        pending = [j for j in self.jobs if j.enabled and j.status == Status.PENDING]
        if not pending:
            QMessageBox.information(self, "Nothing to render",
                                    "Enable a Pending job, or use Reset Selected to render a finished job again.")
            return
        missing = [j for j in pending if not j.exists]
        if missing:
            QMessageBox.warning(
                self, "Files missing",
                "These jobs point at files that no longer exist:\n\n"
                + "\n".join("  " + j.name for j in missing[:10]))
            return
        if not self.installs:
            QMessageBox.warning(self, "No Blender found",
                                "Add a Blender build on the Render tab first.")
            return

        self.act_pause.setChecked(False)
        self.log_view.clear()
        self.logs = {}
        exe_map = {job.id: self.exe_for(job) for job in self.jobs}
        self.runner.start(self.jobs, exe_map)
        self.overall_bar.setVisible(True)
        self.detail.setCurrentWidget(self.log_view)

    def stop_render(self):
        if not self.runner.running and not self.runner.paused:
            return
        self.runner.stop()

    def reset_selected(self):
        jobs = [job for job in self.selected_jobs() if not job.is_locked]
        for job in jobs:
            job.reset_runtime()
            job.enabled = True
            self.logs.pop(job.id, None)
        if jobs:
            self.refresh_list()
            self.queue_view.select_ids([job.id for job in jobs])
            self._show_details(self.current_job())
            self.status_label.setText(f"Reset {len(jobs)} job(s) — ready to render again")

    def _ask_encode_frames(self, job, frames, directory):
        box = QMessageBox(self)
        box.setWindowTitle("Save the rendered frames as a video?")
        box.setTextFormat(Qt.PlainText)
        box.setText(f"{job.name}: {frames} complete frame(s) are ready.\n\n"
                    "Encode them into a playable video now, or keep the frames without encoding?\n\n"
                    "Frames are kept in:\n" + directory)
        encode = box.addButton("Encode Rendered Frames", QMessageBox.AcceptRole)
        box.addButton("Keep Frames Only", QMessageBox.RejectRole)
        box.setDefaultButton(encode)
        box.exec()
        return box.clickedButton() == encode

    def _on_recovery_available(self, job_id, frames, directory):
        self.autosave()
        job = self.job_by_id(job_id)
        encode = bool(job and self._ask_encode_frames(job, frames, directory))
        self.runner.resolve_recovery(encode)

    def dry_run(self):
        job = self.current_job()
        if job is None:
            return
        exe = self.exe_for(job)
        if not exe:
            return
        import json
        import tempfile
        handle, path = tempfile.mkstemp(prefix="bq_dry_", suffix=".json")
        os.close(handle)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(job.render_config(dry_run=True), fh, indent=1)
        command = blender.render_command(exe, job.blend_path, path,
                                         self.settings.factory_startup)
        try:
            proc = subprocess.run(command, capture_output=True, text=True, timeout=300,
                                  stdin=subprocess.DEVNULL,
                                  creationflags=blender.CREATE_NO_WINDOW)
        except Exception as exc:
            QMessageBox.critical(self, "Dry run failed", str(exc))
            return
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

        lines = [ln for ln in (proc.stdout or "").splitlines() if ln.startswith("BQ>>")]
        report = []
        for line in lines:
            import json as _json
            try:
                event = _json.loads(line[4:])
            except ValueError:
                continue
            if event.get("e") == "start":
                report.append(
                    "Scene: {}\nEngine: {}\nFrames: {} to {} step {}  ({} frames)\n"
                    "Resolution: {}x{} at {}%\nFormat: {}\nOutput: {}".format(
                        event.get("scene"), event.get("engine"), event.get("frame_start"),
                        event.get("frame_end"), event.get("frame_step"), event.get("total"),
                        *event.get("resolution", [0, 0, 0]),
                        event.get("file_format"), event.get("output")))
            elif event.get("e") == "retarget":
                report.append("Follow Path: {} -> {}".format(
                    event.get("object"), event.get("target")))
            elif event.get("e") in ("skip", "warn"):
                report.append("! {}".format(event.get("msg")))

        self._append_log(job.id, proc.stdout or "")
        QMessageBox.information(self, "Dry run - " + job.name,
                                "\n\n".join(report) or "Blender returned nothing to report.")

    def _on_job_started(self, job_id: str):
        job = self.job_by_id(job_id)
        if job:
            # rebuild so the running row loses its editable / draggable flags
            self.refresh_list()
            self.status_label.setText(f"Rendering {job.name}")
            self.queue_view.select_ids([job_id])
        self._sync_actions()

    def _on_job_progress(self, job_id: str):
        job = self.job_by_id(job_id)
        if job is None:
            return
        self.refresh_row(job)
        if job.status == Status.ENCODING or self.runner.waiting_recovery:
            self.status_label.setText(f"{job.name}: {job.message}")
            self.eta_label.setText("")
            self._update_overall()
            return
        if job.frames_total:
            per_frame = job.seconds_per_frame
            detail = ""
            if per_frame:
                detail = "  -  {} per frame".format(format_duration(per_frame))
            self.status_label.setText(
                f"{job.name} - frame {job.current_frame} "
                f"({job.frames_done}/{job.frames_total})"
                f"  {format_duration(job.duration)}{detail}")
        self._update_overall()
        self._update_eta()

    def _on_job_finished(self, job_id: str, ok: bool, message: str):
        job = self.job_by_id(job_id)
        if job:
            self.refresh_list()          # the row becomes editable again
            if job.id == self.queue_view.current_id():
                self._show_details(job)
        self._update_overall()
        self._update_counts()
        if job and job.status == Status.FAILED and message.startswith("Encoding failed"):
            QMessageBox.warning(self, "Video was not saved", message)

    def _on_queue_finished(self, completed: bool):
        self.overall_bar.setVisible(False)
        self.eta_label.setText("")
        self.act_pause.setChecked(False)
        done = sum(1 for j in self.jobs if j.status == Status.DONE)
        failed = sum(1 for j in self.jobs if j.status == Status.FAILED)
        stopped = sum(1 for j in self.jobs if j.status == Status.CANCELLED)
        summary = f"Finished - {done} rendered"
        if failed:
            summary += f", {failed} failed"
        if stopped:
            summary += f", {stopped} stopped"
        self.status_label.setText(summary)
        self._sync_actions()
        self._update_counts()

        if self._close_after_run:
            self._close_after_run = False
            QTimer.singleShot(0, self.close)
            return

        if self.settings.auto_open_output:
            for job in self.jobs:
                if job.status == Status.DONE and job.last_output:
                    self._reveal(os.path.dirname(job.last_output))
                    break
        if self.shutdown_box.isChecked() and completed:
            self._offer_shutdown()

    def _offer_shutdown(self):
        try:
            subprocess.run(["shutdown", "/s", "/t", "60", "/c",
                            "BlenderQueue finished rendering."],
                           stdin=subprocess.DEVNULL,
                           creationflags=blender.CREATE_NO_WINDOW, check=False)
        except Exception as exc:
            QMessageBox.warning(self, "Shutdown failed", str(exc))
            return
        answer = QMessageBox.question(
            self, "Shutting down",
            "The queue is finished and this PC will shut down in 60 seconds.\n\n"
            "Cancel the shutdown?", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
        if answer == QMessageBox.Yes:
            subprocess.run(["shutdown", "/a"], stdin=subprocess.DEVNULL,
                           creationflags=blender.CREATE_NO_WINDOW, check=False)
            self.status_label.setText("Shutdown cancelled")

    def _update_eta(self):
        job = self.runner.current_job
        if job is None or job.status == Status.ENCODING or not job.eta_seconds:
            self.eta_label.setText("")
            return
        waiting = sum(1 for j in self.jobs
                      if j.enabled and j.status == Status.PENDING)
        text = "ETA {}".format(format_duration(job.eta_seconds))
        if waiting:
            text += f"  (+{waiting} queued)"
        self.eta_label.setText(text)

    def _update_overall(self):
        enabled = [j for j in self.jobs if j.enabled]
        if not enabled:
            return
        total = 0.0
        for job in enabled:
            if job.status == Status.DONE:
                total += 1.0
            elif job.is_locked and job.frames_total:
                total += job.frames_done / job.frames_total
        self.overall_bar.setValue(int(round(100 * total / len(enabled))))

    # ==================================================================
    # analysis
    # ==================================================================

    def queue_analysis(self, job: Job):
        exe = self.exe_for(job)
        if not exe or not job.exists:
            return False
        self.analyzer.request(job.id, exe, job.blend_path, self.settings.factory_startup)
        return True

    def analyze_selected(self):
        jobs = self.selected_jobs()
        if not jobs:
            QMessageBox.information(self, "Select a job",
                                    "Pick a job in the queue to analyse.")
            return
        self._analyze(jobs)

    def analyze_all(self):
        self._analyze(list(self.jobs))

    def _analyze(self, jobs: list):
        started = [job for job in jobs if self.queue_analysis(job)]
        if not started:
            QMessageBox.information(
                self, "Nothing to analyse",
                "Those jobs point at files that could not be found.")
            return
        self.detail.setCurrentWidget(self.analysis_panel)
        self.status_label.setText(
            "Analysing {} file(s)...".format(len(started)))

    def add_and_analyze(self):
        before = {job.id for job in self.jobs}
        self.add_files()
        fresh = [job for job in self.jobs if job.id not in before]
        if fresh:
            self._analyze(fresh)

    def _on_analyzed(self, job_id: str, result: dict):
        job = self.job_by_id(job_id)
        if job is None:
            return
        if not result.get("ok"):
            self._append_log(job_id, "Analysis failed:\n" + str(result.get("error", "")))
            self.status_label.setText(f"{job.name}: analysis failed")
        else:
            job.analysis = result
            job._score_cache = None
            score = job.analysis_score()
            if score:
                overall, rating = score
                self.status_label.setText(
                    f"{job.name}: render load {overall}/100 ({rating})")
        self.refresh_row(job)
        if job.id == self.queue_view.current_id():
            self.analysis_panel.set_job(job)
        self._sync_actions()

    def export_report(self):
        job = self.current_job()
        if job is None or not job.analysis:
            return
        default = os.path.join(self.settings.last_browse_dir or "",
                               f"{job.name} - render analysis.txt")
        path, _ = QFileDialog.getSaveFileName(
            self, "Export analysis", default, "Text files (*.txt);;All files (*)")
        if not path:
            return
        self.analysis_panel.set_job(job)
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(self.analysis_panel.report_text())
        except OSError as exc:
            QMessageBox.critical(self, "Could not save", str(exc))
            return
        self.status_label.setText("Saved " + os.path.basename(path))

    # ==================================================================
    # follow paths
    # ==================================================================

    def open_follow_paths(self):
        jobs = self.selected_jobs()
        if not jobs:
            QMessageBox.information(self, "Select a job",
                                    "Pick a job in the queue first.")
            return
        locked = [j for j in jobs if j.is_locked]
        if locked:
            QMessageBox.information(
                self, "Job is rendering",
                "{} is being rendered right now, so its Follow Path targets "
                "cannot be changed.".format(locked[0].name))
            return
        if not jobs[0].info:
            answer = QMessageBox.question(
                self, "Read the file first",
                f"{jobs[0].name} has not been read yet.\n\nRead it now?")
            if answer == QMessageBox.Yes:
                self.queue_job_inspection(jobs[0])
            return

        dialog = FollowPathDialog(jobs, self)
        if dialog.exec() != FollowPathDialog.Accepted:
            return
        dialog.apply_to_jobs()
        if dialog.variants:
            self._make_variants(jobs[0], *dialog.variants)
        self.refresh_list()
        self._show_details(self.current_job())

    def _make_variants(self, job: Job, constraint_key, curves: list, pattern: str,
                       replace: bool):
        from ..models import FollowPathEdit

        taken = {j.name for j in self.jobs}
        anchor = self.jobs.index(job)
        created = []
        for offset, curve in enumerate(curves):
            clone = job.duplicate()
            clone.name = unique_name(
                pattern.replace("{job}", job.name).replace("{path}", curve), taken)
            taken.add(clone.name)
            clone.follow_paths = [e for e in clone.follow_paths if e.key != constraint_key]
            clone.follow_paths.append(FollowPathEdit(
                object=constraint_key[0], bone=constraint_key[1],
                constraint=constraint_key[2], target=curve, enabled=True))
            self.jobs.insert(anchor + 1 + offset, clone)
            created.append(clone)

        if replace:
            self.jobs.remove(job)
        self.refresh_list()
        self.queue_view.select_ids([c.id for c in created])
        self.status_label.setText(
            f"Created {len(created)} job(s), one per path")

    # ==================================================================
    # detail panel
    # ==================================================================

    def _on_selection(self):
        job = self.current_job()
        self._show_details(job)
        self._sync_actions()

    def _show_details(self, job):
        locked = bool(job and job.is_locked)
        self.overrides.set_job(job, read_only=locked)
        self.visibility_panel.set_job(job, read_only=locked)
        self.analysis_panel.set_job(job)
        if job is None:
            self.detail_title.setText("No job selected")
            self.detail_path.setText("")
            self.notes_edit.clear()
            self.notes_edit.setEnabled(False)
            self.job_version_box.setEnabled(False)
            self.info_tree.clear()
            self.log_view.clear()
            self.analysis_panel.set_job(None)
            return

        self.detail_title.setText(job.name)
        self.detail_path.setText(job.blend_path if job.exists
                                 else job.blend_path + "   (file not found)")
        self.notes_edit.setEnabled(not locked)
        self.notes_edit.blockSignals(True)
        self.notes_edit.setText(job.notes)
        self.notes_edit.blockSignals(False)

        self.job_version_box.setEnabled(not locked)
        self.job_version_box.blockSignals(True)
        self.job_version_box.setCurrentIndex(max(0, self.job_version_box.findData(job.blender_key)))
        self.job_version_box.blockSignals(False)

        self._fill_info(job)
        self.log_view.setPlainText("\n".join(self.logs.get(job.id, [])))
        self.log_view.verticalScrollBar().setValue(
            self.log_view.verticalScrollBar().maximum())

    def _fill_info(self, job: Job):
        self.info_tree.clear()
        if not job.info:
            root = QTreeWidgetItem(self.info_tree, ["Not read yet",
                                                    "Use Read File on the Tools tab"])
            root.setFirstColumnSpanned(False)
            return

        def add(parent, name, value=""):
            return QTreeWidgetItem(parent, [str(name), str(value)])

        add(self.info_tree, "Blender", job.info.get("blender_version", "?"))
        for scene in job.info.get("scenes") or []:
            node = add(self.info_tree, "Scene", scene.get("name", ""))
            node.setExpanded(scene.get("name") == job.selected_scene())
            add(node, "Engine", scene.get("engine", ""))
            add(node, "Camera", scene.get("camera") or "(none)")
            add(node, "Frames", "{} - {}  step {}".format(
                scene.get("frame_start"), scene.get("frame_end"), scene.get("frame_step")))
            add(node, "Resolution", "{} x {} at {}%".format(
                scene.get("resolution_x"), scene.get("resolution_y"),
                scene.get("resolution_percentage")))
            add(node, "Frame rate", scene.get("fps"))
            add(node, "Output", scene.get("output_path_abs", ""))
            add(node, "Format", scene.get("file_format", ""))

            curves = scene.get("curves") or []
            curve_node = add(node, "Curves / paths", len(curves))
            for curve in curves:
                add(curve_node, curve.get("name", ""),
                    "duration {} frames".format(curve.get("path_duration")))

            follows = scene.get("follow_paths") or []
            follow_node = add(node, "Follow Path constraints", len(follows))
            follow_node.setExpanded(bool(follows))
            for entry in follows:
                label = entry.get("object", "")
                if entry.get("bone"):
                    label += f" ({entry['bone']})"
                add(follow_node, label, "{}  ->  {}".format(
                    entry.get("constraint", ""), entry.get("target") or "(none)"))

            cameras = scene.get("cameras") or []
            camera_node = add(node, "Cameras", len(cameras))
            for name in cameras:
                add(camera_node, name, "")
        self.info_tree.resizeColumnToContents(0)

    def _append_log(self, job_id: str, text: str):
        if not text:
            return
        lines = self.logs.setdefault(job_id, [])
        for line in str(text).splitlines():
            lines.append(line)
        limit = self.settings.keep_log_lines
        if len(lines) > limit:
            del lines[:len(lines) - limit]
        if job_id == self.queue_view.current_id():
            self.log_view.appendPlainText(str(text).rstrip("\n"))

    # ==================================================================
    # small handlers
    # ==================================================================

    def _on_reordered(self, ids: list):
        if self.runner.running:
            # keep the running job where it is; rebuild from the model instead
            self.refresh_list()
            return
        order = {job_id: i for i, job_id in enumerate(ids)}
        self.jobs.sort(key=lambda j: order.get(j.id, 10 ** 6))
        self.refresh_list()

    def _on_renamed(self, job_id: str, name: str):
        job = self.job_by_id(job_id)
        if job and job.is_locked:
            return
        if job and name and name != job.name:
            job.name = name
            self.detail_title.setText(name)
            self.autosave()

    def _on_enabled_toggled(self, job_id: str, enabled: bool):
        job = self.job_by_id(job_id)
        if job and job.is_locked:
            return
        if job and job.enabled != enabled:
            job.enabled = enabled
            self._update_counts()
            self.autosave()

    def _on_overrides_changed(self):
        job = self.current_job()
        if job and job.is_locked:
            return
        if job:
            self.refresh_row(job)
            self.visibility_panel.set_job(job)
            self.autosave()

    def _on_visibility_changed(self):
        job = self.current_job()
        if job and not job.is_locked:
            self.refresh_row(job)
            self.autosave()

    def _inspect_visibility(self):
        job = self.current_job()
        if job and not job.is_locked:
            self.queue_job_inspection(job)

    def _on_notes_changed(self):
        job = self.current_job()
        if job and job.is_locked:
            return
        if job:
            job.notes = self.notes_edit.text()
            self.refresh_row(job)
            self.autosave()

    def _on_job_blender_changed(self, _index):
        job = self.current_job()
        if job and job.is_locked:
            return
        if job:
            job.blender_key = self.job_version_box.currentData() or ""
            self.refresh_row(job)
            self.autosave()

    def _on_default_blender_changed(self, _index):
        self.settings.default_blender = self.version_box.currentData() or ""
        self.refresh_list()

    def _on_factory_toggled(self, checked: bool):
        self.settings.factory_startup = checked

    def _on_stop_on_error(self, checked: bool):
        self.settings.stop_on_error = checked

    def _on_auto_open(self, checked: bool):
        self.settings.auto_open_output = checked

    def _browse_blender(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Locate blender.exe", "",
            "Blender executable (blender.exe);;All files (*)"
            if os.name == "nt" else "All files (*)")
        if not path:
            return
        if path not in self.settings.custom_blender_paths:
            self.settings.custom_blender_paths.append(path)
        self.refresh_installs()
        index = self.version_box.findData(os.path.normcase(os.path.abspath(path)))
        if index >= 0:
            self.version_box.setCurrentIndex(index)

    def copy_overrides(self):
        jobs = self.selected_jobs()
        if len(jobs) < 2:
            QMessageBox.information(
                self, "Select more jobs",
                "Select the job to copy from first, then the jobs to copy onto.")
            return
        source, targets = jobs[0], jobs[1:]
        targets = [job for job in targets if not job.is_locked]
        payload = source.to_dict()
        for job in targets:
            job.use_overrides = source.use_overrides
            copied = Job.from_dict(payload)
            job.groups = copied.groups
            job.visibility_enabled = copied.visibility_enabled
            job.visibility = copied.visibility
        self.refresh_list()
        self.status_label.setText(
            f"Copied overrides from {source.name} onto {len(targets)} job(s)")

    def open_output_folder(self):
        job = self.current_job()
        if job is None:
            return
        folder = ""
        if job.last_output:
            folder = os.path.dirname(job.last_output)
        elif job.video_manifest and os.path.isfile(job.video_manifest):
            folder = os.path.dirname(job.video_manifest)
        elif job.use_overrides and job.group("output").enabled:
            folder = job.group("output").values.get("output_dir", "")
        if not folder:
            folder = (job.scene_info().get("settings") or {}).get("output_dir", "")
        if not folder or not os.path.isdir(folder):
            QMessageBox.information(self, "No output folder yet",
                                    "This job has not written any frames, and its output "
                                    "folder does not exist yet.")
            return
        self._reveal(folder)

    def _reveal(self, folder: str):
        QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    def open_in_blender(self):
        job = self.current_job()
        if job is None or not job.exists:
            return
        exe = self.exe_for(job)
        if exe:
            from PySide6.QtCore import QProcess
            QProcess.startDetached(exe, [job.blend_path])

    def show_about(self):
        QMessageBox.about(
            self, "About BlenderQueue",
            "<h3>BlenderQueue</h3>"
            "<p>Queue Blender files and render them one after another.</p>"
            "<p>Each job can render with the settings saved in the file, or override "
            "them per group. Follow Path constraints can be retargeted per job, so one "
            "scene can produce a render for every path in it.</p>"
            f"<p style='color:{theme.TEXT_DIM}'>Blender builds found: "
            f"{len(self.installs)}</p>")

    def show_updates(self):
        from .update_dialog import UpdateDialog
        UpdateDialog(self).exec()

    def _context_menu(self, point):
        if not self.jobs:
            return
        menu = QMenu(self)
        menu.addAction(self.act_rename)
        menu.addAction(self.act_duplicate)
        menu.addAction(self.act_reset)
        menu.addAction(self.act_remove)
        menu.addSeparator()
        menu.addAction(self.act_follow)
        menu.addAction(self.act_inspect)
        menu.addSeparator()
        menu.addAction(self.act_toggle)
        menu.addAction(self.act_open_output)
        menu.addAction(self.act_open_blender)
        menu.exec(self.queue_view.viewport().mapToGlobal(point))

    def _update_counts(self):
        enabled = sum(1 for j in self.jobs if j.enabled)
        self.counts_label.setText(f"{enabled} of {len(self.jobs)} queued")

    def _sync_actions(self):
        running = self.runner.running or self.runner.paused
        has_jobs = bool(self.jobs)
        chosen = self.selected_jobs()
        selected = bool(chosen)
        single = len(chosen) == 1
        locked = any(job.is_locked for job in chosen)
        editable = selected and not locked

        self.act_start.setEnabled(has_jobs and not running and bool(self.installs))
        self.act_pause.setEnabled(running)
        self.act_stop.setEnabled(running and not self.runner.waiting_recovery)
        self.act_skip.setEnabled(self.runner.running and not self.runner.waiting_recovery)
        self.act_reset.setEnabled(editable)

        for action in (self.act_remove, self.act_up, self.act_down,
                       self.act_top, self.act_bottom, self.act_toggle):
            action.setEnabled(editable and not running)
        self.act_duplicate.setEnabled(editable)
        self.act_inspect.setEnabled(editable)
        self.act_rename.setEnabled(single and not locked)
        self.act_follow.setEnabled(single and not locked)
        self.act_variants.setEnabled(single and not locked and not running)
        self.act_validate.setEnabled(single and not locked and bool(self.installs))

        analysable = bool(chosen) and bool(self.installs)
        self.act_analyze.setEnabled(analysable)
        self.act_analyze_all.setEnabled(has_jobs and bool(self.installs))
        self.act_add_analyze.setEnabled(bool(self.installs))
        self.act_export_report.setEnabled(single and bool(chosen[0].analysis))
        self.act_open_output.setEnabled(single)
        self.act_open_blender.setEnabled(single)
        self.act_copy_settings.setEnabled(len(self.queue_view.selected_ids()) > 1)
        self.act_clear.setEnabled(has_jobs and not running)
        self.act_new_queue.setEnabled(not running)
        self.act_open_queue.setEnabled(not running)
        self.act_save_queue.setEnabled(has_jobs)
        self.act_enable_all.setEnabled(has_jobs)
        self.act_disable_all.setEnabled(has_jobs)

    # ==================================================================
    # window events
    # ==================================================================

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        paths = [u.toLocalFile() for u in event.mimeData().urls()]
        blends, queues = [], []
        for path in paths:
            if path.lower().endswith(".blend"):
                blends.append(path)
            elif path.lower().endswith(store.QUEUE_SUFFIX):
                queues.append(path)
            elif os.path.isdir(path):
                for root, _dirs, files in os.walk(path):
                    blends += [os.path.join(root, f) for f in sorted(files)
                               if f.lower().endswith(".blend")]
        if blends:
            self.add_paths(blends)
        for queue_file in queues:
            try:
                self.jobs += store.load_queue(queue_file)
            except Exception:
                pass
        if queues:
            self.refresh_list()
        event.acceptProposedAction()

    def closeEvent(self, event):
        if self.runner.running or self.runner.paused:
            if self._close_after_run or self.runner.waiting_recovery:
                event.ignore()
                return
            answer = QMessageBox.question(
                self, "Rendering in progress",
                "Stop the queue and close?\n\nIf video frames are available, "
                "you can encode them before the window closes.")
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self._close_after_run = True
            self.runner.stop()
            event.ignore()
            return
        self.inspector.cancel_all()
        self.analyzer.cancel_all()
        self.settings.window_geometry = bytes(self.saveGeometry().toBase64()).decode()
        self.settings.splitter_state = bytes(self.splitter.saveState().toBase64()).decode()
        store.save_settings(self.settings)
        self.autosave()
        event.accept()

    def restore_geometry(self):
        from PySide6.QtCore import QByteArray
        if self.settings.window_geometry:
            self.restoreGeometry(QByteArray.fromBase64(
                self.settings.window_geometry.encode()))
        if self.settings.splitter_state:
            self.splitter.restoreState(QByteArray.fromBase64(
                self.settings.splitter_state.encode()))
