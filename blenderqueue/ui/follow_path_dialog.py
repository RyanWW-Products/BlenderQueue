"""Retarget Follow Path constraints, and spin off one job per path.

The second part is the reason this exists: point the car at Path A, then at
Path B, and get two queued renders out of a single .blend.
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QDoubleSpinBox, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..models import FollowPathEdit, Job
from . import theme

FORWARD_AXES = (("FORWARD_X", "X"), ("FORWARD_Y", "Y"), ("FORWARD_Z", "Z"),
                ("TRACK_NEGATIVE_X", "-X"), ("TRACK_NEGATIVE_Y", "-Y"),
                ("TRACK_NEGATIVE_Z", "-Z"))
UP_AXES = (("UP_X", "X"), ("UP_Y", "Y"), ("UP_Z", "Z"))

HEADERS = ("Use", "Object", "Constraint", "In file", "Render with",
           "Follow curve", "Forward", "Offset factor", "Influence")


def _center(widget: QWidget) -> QWidget:
    wrapper = QWidget()
    layout = QHBoxLayout(wrapper)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setAlignment(Qt.AlignCenter)
    layout.addWidget(widget)
    return wrapper


class VariantDialog(QDialog):
    """Pick the curves to fan a job out across."""

    def __init__(self, constraints: list, curves: list, job_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create one job per path")
        self.setMinimumWidth(430)

        layout = QVBoxLayout(self)
        layout.setSpacing(9)

        intro = QLabel(
            "Duplicates this job once for each path you tick, retargeting the "
            "chosen constraint in every copy.")
        intro.setWordWrap(True)
        intro.setObjectName("Hint")
        layout.addWidget(intro)

        layout.addWidget(QLabel("Constraint to retarget"))
        self.constraint_box = QComboBox()
        for edit in constraints:
            self.constraint_box.addItem(edit.label, edit.key)
        layout.addWidget(self.constraint_box)

        layout.addWidget(QLabel("Paths"))
        self.curve_list = QListWidget()
        self.curve_list.setSelectionMode(QAbstractItemView.NoSelection)
        for curve in curves:
            item = QListWidgetItem(curve)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked)
            self.curve_list.addItem(item)
        self.curve_list.setMaximumHeight(170)
        layout.addWidget(self.curve_list)

        layout.addWidget(QLabel("Name each job"))
        self.pattern = QLineEdit("{job} - {path}")
        self.pattern.setToolTip("{job} is the current job name, {path} the curve name.")
        layout.addWidget(self.pattern)

        self.replace_box = QCheckBox("Remove the original job afterwards")
        layout.addWidget(self.replace_box)

        preview = QLabel()
        preview.setObjectName("Hint")
        layout.addWidget(preview)

        def update_preview():
            names = [self.pattern.text().replace("{job}", job_name).replace("{path}", c)
                     for c in self.checked_curves()[:3]]
            more = len(self.checked_curves()) - len(names)
            text = "  |  ".join(names) or "(nothing selected)"
            preview.setText("Creates: " + text + (f"  (+{more} more)" if more > 0 else ""))

        self.pattern.textChanged.connect(update_preview)
        self.curve_list.itemChanged.connect(lambda _i: update_preview())
        update_preview()

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Create jobs")
        buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def checked_curves(self) -> list:
        return [self.curve_list.item(i).text()
                for i in range(self.curve_list.count())
                if self.curve_list.item(i).checkState() == Qt.Checked]

    def constraint_key(self) -> tuple:
        return self.constraint_box.currentData()

    def name_for(self, job_name: str, curve: str) -> str:
        return self.pattern.text().replace("{job}", job_name).replace("{path}", curve)


class FollowPathDialog(QDialog):
    """Table of every Follow Path constraint in the job's scene."""

    def __init__(self, jobs: list, parent=None):
        super().__init__(parent)
        self.jobs = jobs
        self.primary: Job = jobs[0]
        self.variants = None            # (constraint_key, [curve names], pattern, replace)

        self.setWindowTitle("Follow Path Targets")
        self.setMinimumSize(940, 470)

        layout = QVBoxLayout(self)
        layout.setSpacing(9)

        scene = self.primary.scene_info()
        self.curves = [c.get("name", "") for c in scene.get("curves") or []]
        found = scene.get("follow_paths") or []

        title = QLabel(f"<b>{self.primary.name}</b>  -  scene "
                       f"<b>{scene.get('name', '?')}</b>")
        layout.addWidget(title)

        if len(jobs) > 1:
            note = QLabel(f"Changes apply to all {len(jobs)} selected jobs where the "
                          "same object and constraint exist.")
            note.setObjectName("Hint")
            note.setWordWrap(True)
            layout.addWidget(note)

        self.table = QTableWidget(0, len(HEADERS), self)
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        for col, width in ((0, 44), (3, 120), (4, 150), (5, 90), (6, 78), (7, 104), (8, 96)):
            self.table.setColumnWidth(col, width)
        layout.addWidget(self.table, 1)

        self._rows = []
        existing = {edit.key: edit for edit in self.primary.follow_paths}
        for entry in found:
            self._add_row(entry, existing)

        if not found:
            empty = QLabel(
                "No Follow Path constraints were found in this scene.\n\n"
                "In Blender these live on the object under Constraint Properties, "
                "not the modifier stack. Add one, save the file, then use "
                "Read File to refresh."
                if scene else
                "This file has not been read yet. Use Read File on the Queue tab first.")
            empty.setWordWrap(True)
            empty.setObjectName("Hint")
            empty.setAlignment(Qt.AlignCenter)
            layout.addWidget(empty)

        footer = QHBoxLayout()
        self.variant_button = QPushButton(
            theme.icon("duplicate", theme.TEXT, 20), "  Create one job per path...")
        self.variant_button.setIconSize(QSize(17, 17))
        self.variant_button.setEnabled(bool(found) and len(self.curves) > 1
                                       and len(jobs) == 1)
        self.variant_button.setToolTip(
            "Fan this job out into one queued render per path."
            if self.variant_button.isEnabled() else
            "Needs a single selected job with at least two curves in the scene.")
        self.variant_button.clicked.connect(self._open_variants)
        footer.addWidget(self.variant_button)

        reset = QPushButton("Reset to file")
        reset.setToolTip("Forget every retarget and use the targets saved in the file.")
        reset.clicked.connect(self._reset)
        footer.addWidget(reset)
        footer.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setObjectName("Primary")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        layout.addLayout(footer)

    # ------------------------------------------------------------------

    def _add_row(self, entry: dict, existing: dict):
        row = self.table.rowCount()
        self.table.insertRow(row)

        key = (entry.get("object", ""), entry.get("bone", ""), entry.get("constraint", ""))
        edit = existing.get(key)

        use = QCheckBox()
        use.setChecked(bool(edit and edit.enabled and edit.target))
        use.setToolTip("Apply this row when rendering")
        self.table.setCellWidget(row, 0, _center(use))

        name = entry.get("object", "")
        if entry.get("bone"):
            name += f"  ({entry['bone']})"
        for col, text in ((1, name), (2, entry.get("constraint", "")),
                          (3, entry.get("target") or "-")):
            item = QTableWidgetItem(text)
            if col == 3:
                item.setForeground(QColor(theme.TEXT_DIM))
            self.table.setItem(row, col, item)

        target = QComboBox()
        target.addItem("(keep file target)", "")
        for curve in self.curves:
            target.addItem(curve, curve)
        chosen = edit.target if edit else ""
        target.setCurrentIndex(max(0, target.findData(chosen)))
        target.currentIndexChanged.connect(
            lambda _i, box=use, combo=target: box.setChecked(bool(combo.currentData())))
        self.table.setCellWidget(row, 4, target)

        follow = QCheckBox()
        follow.setChecked(bool(entry.get("use_curve_follow")) if edit is None
                          else bool(edit.use_curve_follow))
        follow.setToolTip("Rotate the object to face along the curve")
        self.table.setCellWidget(row, 5, _center(follow))

        forward = QComboBox()
        for value, label in FORWARD_AXES:
            forward.addItem(label, value)
        current_axis = (edit.forward_axis if edit and edit.forward_axis
                        else entry.get("forward_axis", "FORWARD_Y"))
        forward.setCurrentIndex(max(0, forward.findData(current_axis)))
        forward.setToolTip("Which local axis points along the curve")
        self.table.setCellWidget(row, 6, forward)

        offset = QDoubleSpinBox()
        offset.setRange(-10.0, 10.0)
        offset.setSingleStep(0.05)
        offset.setDecimals(3)
        offset.setValue(float(edit.offset_factor) if edit and edit.offset_factor is not None
                        else float(entry.get("offset_factor") or 0.0))
        offset.setToolTip("Start position along the curve (0-1). Needs Fixed Position "
                          "in Blender to take effect.")
        self.table.setCellWidget(row, 7, offset)

        influence = QDoubleSpinBox()
        influence.setRange(0.0, 1.0)
        influence.setSingleStep(0.05)
        influence.setDecimals(3)
        influence.setValue(float(edit.influence) if edit and edit.influence is not None
                           else float(entry.get("influence") or 1.0))
        self.table.setCellWidget(row, 8, influence)

        self.table.setRowHeight(row, 32)
        self._rows.append({"entry": entry, "key": key, "use": use, "target": target,
                           "follow": follow, "forward": forward, "offset": offset,
                           "influence": influence})

    def _reset(self):
        for row in self._rows:
            row["use"].setChecked(False)
            row["target"].setCurrentIndex(0)
            row["follow"].setChecked(bool(row["entry"].get("use_curve_follow")))
            row["forward"].setCurrentIndex(
                max(0, row["forward"].findData(row["entry"].get("forward_axis", "FORWARD_Y"))))
            row["offset"].setValue(float(row["entry"].get("offset_factor") or 0.0))
            row["influence"].setValue(float(row["entry"].get("influence") or 1.0))

    def _open_variants(self):
        edits = [FollowPathEdit(object=r["entry"].get("object", ""),
                                bone=r["entry"].get("bone", ""),
                                constraint=r["entry"].get("constraint", ""))
                 for r in self._rows]
        dialog = VariantDialog(edits, self.curves, self.primary.name, self)
        if dialog.exec() != QDialog.Accepted:
            return
        curves = dialog.checked_curves()
        if not curves:
            return
        self.variants = (dialog.constraint_key(), curves, dialog.pattern.text(),
                         dialog.replace_box.isChecked())
        self.accept()

    # ------------------------------------------------------------------

    def collect(self) -> list:
        """Turn the table back into FollowPathEdit objects."""
        edits = []
        for row in self._rows:
            target = row["target"].currentData() or ""
            edit = FollowPathEdit(
                object=row["key"][0],
                bone=row["key"][1],
                constraint=row["key"][2],
                target=target,
                enabled=row["use"].isChecked() and bool(target),
                use_curve_follow=row["follow"].isChecked(),
                forward_axis=row["forward"].currentData(),
                offset_factor=row["offset"].value(),
                influence=row["influence"].value(),
            )
            if edit.target:
                edits.append(edit)
        return edits

    def apply_to_jobs(self):
        """Write the table back onto every job the dialog was opened for."""
        edits = self.collect()
        for job in self.jobs:
            keys = {e.key for e in edits}
            kept = [e for e in job.follow_paths if e.key not in keys]
            job.follow_paths = kept + [FollowPathEdit.from_dict(e.to_dict()) for e in edits]
