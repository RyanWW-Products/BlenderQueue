"""The override editor -- collapsible groups generated from ``schema.GROUPS``.

Each group has its own switch.  A group that is off leaves those settings
exactly as the .blend file saved them; a group that is on applies every value
it holds.  Turning a group on for the first time seeds it from the values read
out of the file, so you always start from something real.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QScrollArea, QSizePolicy, QSpinBox, QToolButton,
                               QVBoxLayout, QWidget)

from .. import schema
from ..models import TOKEN_HELP, Job
from . import theme


class CollapsibleGroup(QWidget):
    """Header with an on/off switch, plus a body that folds away."""

    toggled = Signal(bool)
    expandedChanged = Signal(bool)

    def __init__(self, group: schema.G, parent=None):
        super().__init__(parent)
        self.group = group

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 6)
        layout.setSpacing(0)

        header = QFrame(self)
        header.setObjectName("GroupHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(8, 0, 8, 0)
        header_layout.setSpacing(6)

        self.switch = QCheckBox(header)
        self.switch.setToolTip(f"Override {group.label.lower()} for this job")
        header_layout.addWidget(self.switch)

        self.arrow = QLabel("▸", header)
        self.arrow.setFixedWidth(12)
        header_layout.addWidget(self.arrow)

        self.title = QToolButton(header)
        self.title.setObjectName("GroupToggle")
        self.title.setText(group.label)
        self.title.setIcon(theme.icon(group.icon or "settings", theme.TEXT_DIM, 20))
        self.title.setIconSize(QSize(17, 17))
        self.title.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.title.setCursor(Qt.PointingHandCursor)
        self.title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        header_layout.addWidget(self.title, 1)

        self.reset_button = QToolButton(header)
        self.reset_button.setIcon(theme.icon("refresh", theme.TEXT_DIM, 18))
        self.reset_button.setIconSize(QSize(15, 15))
        self.reset_button.setToolTip("Reset these values to what the .blend file uses")
        header_layout.addWidget(self.reset_button)

        layout.addWidget(header)

        self.body = QFrame(self)
        self.body.setObjectName("GroupBody")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(12, 10, 12, 12)
        body_layout.setSpacing(8)

        if group.blurb:
            blurb = QLabel(group.blurb, self.body)
            blurb.setObjectName("GroupBlurb")
            blurb.setWordWrap(True)
            body_layout.addWidget(blurb)

        self.form = QFormLayout()
        self.form.setContentsMargins(0, 0, 0, 0)
        self.form.setSpacing(7)
        self.form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        body_layout.addLayout(self.form)

        self.footer = QLabel("", self.body)
        self.footer.setObjectName("Hint")
        self.footer.setWordWrap(True)
        self.footer.hide()
        body_layout.addWidget(self.footer)

        layout.addWidget(self.body)
        self.body.setVisible(False)

        self.title.clicked.connect(self.toggle_expanded)
        self.switch.toggled.connect(self._on_switch)

    def toggle_expanded(self):
        self.set_expanded(not self.body.isVisible())

    def set_expanded(self, expanded: bool):
        self.body.setVisible(expanded)
        self.arrow.setText("▾" if expanded else "▸")
        self.expandedChanged.emit(expanded)

    def _on_switch(self, checked: bool):
        self.body.setEnabled(checked)
        if checked and not self.body.isVisible():
            self.set_expanded(True)
        self.toggled.emit(checked)


class OverridesPanel(QScrollArea):
    """Everything under 'Override render settings' for the selected job."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)

        self._job: Job | None = None
        self._editors: dict = {}          # field key -> widget
        self._rows: dict = {}             # field key -> (label widget, editor widget)
        self._groups: dict = {}           # group key -> CollapsibleGroup
        self._loading = False

        container = QWidget(self)
        self._layout = QVBoxLayout(container)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(0)

        self.master = QCheckBox("Override the render settings saved in this file")
        self.master.setToolTip(
            "Off: render exactly as the .blend file is set up.\n"
            "On: apply the groups you switch on below.")
        self._layout.addWidget(self.master)

        self.hint = QLabel(
            "Switch on only the groups you want to change. Everything else stays "
            "as saved in the file.")
        self.hint.setObjectName("Hint")
        self.hint.setWordWrap(True)
        self._layout.addWidget(self.hint)
        self._layout.addSpacing(8)

        for group in schema.GROUPS:
            widget = CollapsibleGroup(group, container)
            self._groups[group.key] = widget
            self._build_fields(widget, group)
            widget.toggled.connect(
                lambda checked, key=group.key: self._on_group_toggled(key, checked))
            widget.reset_button.clicked.connect(
                lambda _=False, key=group.key: self.reset_group(key))
            self._layout.addWidget(widget)

        self._groups["output"].footer.setText("Tokens: " + TOKEN_HELP)
        self._groups["output"].footer.show()

        self._layout.addStretch(1)
        self.setWidget(container)

        self.locked_note = QLabel(
            "This job is rendering. Its settings are locked until it finishes, "
            "is skipped, or the queue is stopped.")
        self.locked_note.setWordWrap(True)
        self.locked_note.setStyleSheet(
            f"background: {theme.PANEL_ALT}; border: 1px solid {theme.ACCENT};"
            f" border-radius: 4px; padding: 8px; color: {theme.TEXT};")
        self.locked_note.hide()
        self._layout.insertWidget(0, self.locked_note)

        self.read_only = False
        self.master.toggled.connect(self._on_master)
        self.set_job(None)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def _build_fields(self, widget: CollapsibleGroup, group: schema.G):
        for field in group.fields:
            editor = self._make_editor(field)
            label = QLabel(field.label)
            if field.tip:
                label.setToolTip(field.tip)
                editor.setToolTip(field.tip)
            widget.form.addRow(label, editor)
            self._editors[field.key] = editor
            self._rows[field.key] = (label, editor)

    def _make_editor(self, field: schema.F) -> QWidget:
        if field.type == "bool":
            editor = QCheckBox()
            editor.toggled.connect(lambda _v, k=field.key: self._on_edit(k))
            return editor

        if field.type == "int":
            editor = QSpinBox()
            editor.setRange(int(field.minimum if field.minimum is not None else -2147483648),
                            int(field.maximum if field.maximum is not None else 2147483647))
            editor.setSuffix(field.suffix)
            editor.setKeyboardTracking(False)
            editor.valueChanged.connect(lambda _v, k=field.key: self._on_edit(k))
            return editor

        if field.type == "float":
            editor = QDoubleSpinBox()
            editor.setDecimals(field.decimals)
            editor.setRange(field.minimum if field.minimum is not None else -1e9,
                            field.maximum if field.maximum is not None else 1e9)
            editor.setSingleStep(field.step)
            editor.setSuffix(field.suffix)
            editor.setKeyboardTracking(False)
            editor.valueChanged.connect(lambda _v, k=field.key: self._on_edit(k))
            return editor

        if field.type == "enum":
            editor = QComboBox()
            editor.setEditable(False)
            for value, label in field.choices:
                editor.addItem(label, value)
            editor.currentIndexChanged.connect(lambda _v, k=field.key: self._on_edit(k))
            return editor

        if field.type in ("dir", "file"):
            wrapper = QWidget()
            row = QHBoxLayout(wrapper)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(4)
            line = QLineEdit()
            line.editingFinished.connect(lambda k=field.key: self._on_edit(k))
            browse = QPushButton("...")
            browse.setFixedWidth(30)
            browse.clicked.connect(lambda _=False, k=field.key: self._browse(k))
            row.addWidget(line, 1)
            row.addWidget(browse)
            wrapper.line = line                     # noqa: attach for convenience
            return wrapper

        editor = QLineEdit()
        editor.editingFinished.connect(lambda k=field.key: self._on_edit(k))
        return editor

    # ------------------------------------------------------------------
    # value access
    # ------------------------------------------------------------------

    def _read(self, key: str):
        field = schema.FIELD_BY_KEY[key]
        editor = self._editors[key]
        if field.type == "bool":
            return editor.isChecked()
        if field.type in ("int", "float"):
            return editor.value()
        if field.type == "enum":
            return editor.currentData()
        if field.type in ("dir", "file"):
            return editor.line.text().strip()
        return editor.text()

    def _write(self, key: str, value):
        field = schema.FIELD_BY_KEY[key]
        editor = self._editors[key]
        editor.blockSignals(True)
        try:
            if field.type == "bool":
                editor.setChecked(bool(value))
            elif field.type == "int":
                editor.setValue(int(value if value is not None else 0))
            elif field.type == "float":
                editor.setValue(float(value if value is not None else 0.0))
            elif field.type == "enum":
                index = editor.findData(value)
                if index < 0 and value not in (None, ""):
                    editor.addItem(str(value), value)
                    index = editor.findData(value)
                editor.setCurrentIndex(max(0, index))
            elif field.type in ("dir", "file"):
                editor.line.blockSignals(True)
                editor.line.setText(str(value or ""))
                editor.line.blockSignals(False)
            else:
                editor.setText(str(value or ""))
        finally:
            editor.blockSignals(False)

    def _populate_sources(self, job: Job | None):
        """Fill file-derived enums (scenes, cameras, worlds, view layers)."""
        info = job.info if job else {}
        scenes = info.get("scenes") or []
        scene_info = job.scene_info() if job else {}
        options = {
            "scenes": [s.get("name", "") for s in scenes],
            "cameras": list(scene_info.get("cameras") or []),
            "worlds": list(info.get("worlds") or []),
            "view_layers": list(scene_info.get("view_layers") or []),
        }
        for field in schema.FIELD_BY_KEY.values():
            if not field.source:
                continue
            editor = self._editors[field.key]
            current = editor.currentData()
            editor.blockSignals(True)
            editor.clear()
            for name in options.get(field.source, []):
                editor.addItem(name, name)
            if editor.count() == 0:
                editor.addItem("(read the file first)", "")
            index = editor.findData(current)
            editor.setCurrentIndex(max(0, index))
            editor.blockSignals(False)

    # ------------------------------------------------------------------
    # job binding
    # ------------------------------------------------------------------

    def set_job(self, job: Job | None, read_only: bool = False):
        self._loading = True
        self._job = job
        self.read_only = read_only
        enabled = job is not None and not read_only
        self.master.setEnabled(enabled)
        self.hint.setEnabled(enabled)

        self.locked_note.setVisible(bool(read_only and job is not None))
        self.master.blockSignals(True)
        self.master.setChecked(bool(job and job.use_overrides))
        self.master.blockSignals(False)

        self._populate_sources(job)

        for group in schema.GROUPS:
            widget = self._groups[group.key]
            override = job.group(group.key) if job else None
            widget.setEnabled(enabled and bool(job and job.use_overrides)
                              and not read_only)
            widget.switch.blockSignals(True)
            widget.switch.setChecked(bool(override and override.enabled))
            widget.switch.blockSignals(False)
            widget.body.setEnabled(bool(override and override.enabled))

            values = dict(override.values) if override else {}
            for field in group.fields:
                if field.key in values:
                    self._write(field.key, values[field.key])
                else:
                    self._write(field.key, self._file_value(job, field))

        self._loading = False
        self._refresh_visibility()

    def _file_value(self, job: Job | None, field: schema.F):
        """The value the .blend file itself uses, falling back to the default."""
        if job:
            settings = job.scene_info().get("settings") or {}
            if field.key in settings and settings[field.key] is not None:
                return settings[field.key]
        return field.default

    def reset_group(self, group_key: str):
        """Re-seed a group from the inspected file values."""
        if self._job is None or self.read_only:
            return
        group = schema.GROUP_BY_KEY[group_key]
        values = {f.key: self._file_value(self._job, f) for f in group.fields}
        self._job.group(group_key).values = values
        self._loading = True
        for key, value in values.items():
            self._write(key, value)
        self._loading = False
        self._refresh_visibility()
        self.changed.emit()

    # ------------------------------------------------------------------
    # reactions
    # ------------------------------------------------------------------

    def _on_master(self, checked: bool):
        if self._job is None or self._loading or self.read_only:
            return
        self._job.use_overrides = checked
        for group in schema.GROUPS:
            self._groups[group.key].setEnabled(checked)
        self.changed.emit()

    def _on_group_toggled(self, group_key: str, checked: bool):
        if self._job is None or self._loading or self.read_only:
            return
        override = self._job.group(group_key)
        override.enabled = checked
        if checked and not override.values:
            self.reset_group(group_key)
        else:
            self.changed.emit()

    def _on_edit(self, key: str):
        if self._job is None or self._loading or self.read_only:
            return
        field = schema.FIELD_BY_KEY[key]
        group_key = next(g.key for g in schema.GROUPS if field in g.fields)
        override = self._job.group(group_key)
        override.values[key] = self._read(key)

        if key == "scene":
            self._populate_sources(self._job)
        self._refresh_visibility()
        self.changed.emit()

    def _refresh_visibility(self):
        """Hide fields whose 'depends' conditions are not met."""
        current = {}
        for group in schema.GROUPS:
            for field in group.fields:
                current[field.key] = self._read(field.key)
        for group in schema.GROUPS:
            for field in group.fields:
                visible = field.visible_for(current)
                label, editor = self._rows[field.key]
                label.setVisible(visible)
                editor.setVisible(visible)

    def expand_group(self, group_key: str):
        widget = self._groups.get(group_key)
        if widget:
            widget.set_expanded(True)
            self.ensureWidgetVisible(widget)

    # ------------------------------------------------------------------

    def _browse(self, key: str):
        field = schema.FIELD_BY_KEY[key]
        editor = self._editors[key]
        start = editor.line.text().strip() or ""
        if field.type == "dir":
            chosen = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        else:
            chosen, _ = QFileDialog.getOpenFileName(self, "Choose file", start)
        if chosen:
            editor.line.setText(chosen.replace("/", "\\") if "\\" in start else chosen)
            self._on_edit(key)
