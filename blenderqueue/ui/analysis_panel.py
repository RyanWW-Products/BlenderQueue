"""The Analysis tab: how expensive this render looks, and what is driving it."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSizePolicy, QToolButton,
                               QVBoxLayout, QWidget)

from ..analysis import RATINGS, Report, build_report, top_suggestions
from . import theme

SEVERITY_COLOR = {
    "critical": theme.FAIL,
    "warn": theme.ACCENT,
    "notice": theme.WARN,
    "info": theme.INFO,
}

CATEGORY_ICONS = {
    "sampling": "engine",
    "geometry": "frames",
    "output": "output",
    "textures": "output",
    "lighting": "camera",
    "shading": "settings",
    "effects": "path",
}


def load_color(load: int) -> str:
    for ceiling, _name, color in RATINGS:
        if load < ceiling:
            return color
    return theme.FAIL


class LoadBar(QWidget):
    """A slim horizontal meter, coloured by how hot the value is."""

    def __init__(self, load: int = 0, width: int = 140, height: int = 14, parent=None):
        super().__init__(parent)
        self.load = max(0, min(100, int(load)))
        self.setFixedSize(width, height)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        rect = self.rect().adjusted(0, 2, -1, -2)

        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.setBrush(QColor(theme.BG))
        painter.drawRoundedRect(rect, 3, 3)

        if self.load > 0:
            filled = rect.adjusted(1, 1, -1, -1)
            filled.setWidth(max(2, int((rect.width() - 2) * self.load / 100.0)))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(load_color(self.load)))
            painter.drawRoundedRect(filled, 2, 2)
        painter.end()


class FindingRow(QFrame):
    """One observation, with its load and any suggestion."""

    def __init__(self, finding, parent=None):
        super().__init__(parent)
        color = SEVERITY_COLOR.get(finding.severity, theme.INFO)
        self.setStyleSheet(
            f"QFrame {{ background: {theme.PANEL_ALT}; border: none;"
            f" border-left: 3px solid {color}; border-radius: 3px; }}")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 6, 9, 7)
        layout.setSpacing(3)

        head = QHBoxLayout()
        head.setSpacing(8)

        label = QLabel(f"<b>{finding.label}</b>")
        label.setStyleSheet("border: none;")
        head.addWidget(label)

        value = QLabel(finding.value)
        value.setStyleSheet(f"color: {theme.TEXT}; border: none;")
        head.addWidget(value)
        head.addStretch(1)

        if finding.load > 0:
            meter = QLabel(f"Render load: {finding.load}%")
            meter.setStyleSheet(
                f"color: {load_color(finding.load)}; font-weight: 600; border: none;")
            head.addWidget(meter)
            head.addWidget(LoadBar(finding.load, 70, 12))

        layout.addLayout(head)

        if finding.suggestion:
            tip = QLabel(finding.suggestion)
            tip.setWordWrap(True)
            tip.setStyleSheet(f"color: {theme.TEXT_DIM}; border: none;")
            layout.addWidget(tip)


class CategoryBlock(QWidget):
    """A collapsible category: load meter, findings, then the raw numbers."""

    def __init__(self, category, parent=None):
        super().__init__(parent)
        self.category = category

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 7)
        outer.setSpacing(0)

        header = QFrame(self)
        header.setObjectName("GroupHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(8, 0, 10, 0)
        row.setSpacing(8)

        self.arrow = QLabel("▸", header)
        self.arrow.setFixedWidth(12)
        row.addWidget(self.arrow)

        self.title = QToolButton(header)
        self.title.setObjectName("GroupToggle")
        self.title.setText(category.label)
        self.title.setIcon(theme.icon(CATEGORY_ICONS.get(category.key, "settings"),
                                      theme.TEXT_DIM, 20))
        self.title.setIconSize(QSize(17, 17))
        self.title.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.title.setCursor(Qt.PointingHandCursor)
        self.title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row.addWidget(self.title, 1)

        count = len(category.findings)
        if count:
            flag = QLabel(f"{count} note{'s' if count != 1 else ''}")
            flag.setObjectName("Hint")
            row.addWidget(flag)

        self.percent = QLabel(f"{category.load}%")
        self.percent.setStyleSheet(
            f"color: {load_color(category.load)}; font-weight: 600;")
        self.percent.setFixedWidth(40)
        self.percent.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        row.addWidget(self.percent)
        row.addWidget(LoadBar(category.load, 110, 14))

        outer.addWidget(header)

        self.body = QFrame(self)
        self.body.setObjectName("GroupBody")
        body = QVBoxLayout(self.body)
        body.setContentsMargins(12, 10, 12, 12)
        body.setSpacing(7)

        if category.headline:
            headline = QLabel(category.headline)
            headline.setWordWrap(True)
            headline.setObjectName("GroupBlurb")
            body.addWidget(headline)

        for finding in category.sorted_findings():
            body.addWidget(FindingRow(finding, self.body))

        if category.stats:
            table = QFrame(self.body)
            table.setStyleSheet("QFrame { background: transparent; border: none; }")
            grid = QGridLayout(table)
            grid.setContentsMargins(0, 6, 0, 0)
            grid.setHorizontalSpacing(14)
            grid.setVerticalSpacing(3)
            grid.setColumnStretch(1, 1)
            for index, (label, value) in enumerate(category.stats):
                left = QLabel(label)
                left.setStyleSheet(f"color: {theme.TEXT_DIM};")
                right = QLabel(str(value))
                right.setWordWrap(True)
                grid.addWidget(left, index, 0, Qt.AlignTop | Qt.AlignLeft)
                grid.addWidget(right, index, 1, Qt.AlignTop | Qt.AlignLeft)
            body.addWidget(table)

        outer.addWidget(self.body)
        self.body.setVisible(False)
        self.title.clicked.connect(self.toggle)

    def toggle(self):
        self.set_expanded(not self.body.isVisible())

    def set_expanded(self, expanded: bool):
        self.body.setVisible(expanded)
        self.arrow.setText("▾" if expanded else "▸")


class AnalysisPanel(QScrollArea):
    """Shows the render-cost report for the selected job."""

    analyzeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self._job = None
        self._build()

    def _build(self):
        self.container = QWidget(self)
        self.layout_ = QVBoxLayout(self.container)
        self.layout_.setContentsMargins(10, 10, 10, 10)
        self.layout_.setSpacing(0)
        self.setWidget(self.container)

    def _clear(self):
        while self.layout_.count():
            item = self.layout_.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    # ------------------------------------------------------------------

    def set_job(self, job):
        self._job = job
        self._clear()

        if job is None:
            self._message("Select a job to analyse it.")
            return
        if not job.analysis:
            self._empty_state(job)
            return

        report = build_report(job.analysis)
        if report.error:
            self._message("The analysis failed:\n\n" + report.error)
            return
        self._show_report(job, report)

    def _message(self, text: str):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("Hint")
        label.setAlignment(Qt.AlignCenter)
        self.layout_.addWidget(label)
        self.layout_.addStretch(1)

    def _empty_state(self, job):
        title = QLabel("<b>Not analysed yet</b>")
        title.setAlignment(Qt.AlignCenter)
        self.layout_.addWidget(title)

        blurb = QLabel(
            "Analysis opens the .blend and measures what will make it slow: "
            "sampling, geometry, textures, lighting, shading, effects and "
            "output settings. It rates the overall load and suggests what to "
            "change.\n\nNothing is modified in your file.")
        blurb.setWordWrap(True)
        blurb.setObjectName("Hint")
        blurb.setAlignment(Qt.AlignCenter)
        self.layout_.addSpacing(8)
        self.layout_.addWidget(blurb)
        self.layout_.addSpacing(14)

        button = QPushButton(theme.icon("engine", theme.TEXT, 20),
                             "  Analyse this file")
        button.setObjectName("Primary")
        button.setIconSize(QSize(18, 18))
        button.setEnabled(job.exists)
        button.clicked.connect(self.analyzeRequested.emit)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(button)
        row.addStretch(1)
        holder = QWidget()
        holder.setLayout(row)
        self.layout_.addWidget(holder)
        self.layout_.addStretch(1)

    def _show_report(self, job, report: Report):
        # ---- headline score ------------------------------------------
        head = QFrame(self.container)
        head.setStyleSheet(
            f"QFrame {{ background: {theme.PANEL_ALT}; border: 1px solid {theme.BORDER};"
            " border-radius: 5px; }")
        head_layout = QHBoxLayout(head)
        head_layout.setContentsMargins(16, 12, 16, 12)
        head_layout.setSpacing(16)

        score = QLabel(str(report.overall))
        score.setStyleSheet(
            f"color: {report.color}; font-size: 34pt; font-weight: 700; border: none;")
        head_layout.addWidget(score)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)
        rating = QLabel(f"<b>{report.rating} render</b>  <span style='color:"
                        f"{theme.TEXT_DIM}'>&nbsp;{report.overall}/100</span>")
        rating.setStyleSheet("border: none; font-size: 12pt;")
        text_col.addWidget(rating)

        detail = QLabel(report.summary.split(" - ", 1)[-1])
        detail.setWordWrap(True)
        detail.setStyleSheet(f"color: {theme.TEXT_DIM}; border: none;")
        text_col.addWidget(detail)
        text_col.addWidget(LoadBar(report.overall, 300, 12))
        head_layout.addLayout(text_col, 1)
        self.layout_.addWidget(head)
        self.layout_.addSpacing(10)

        # ---- what to do about it -------------------------------------
        suggestions = top_suggestions(report, 5)
        if suggestions:
            box = QFrame(self.container)
            box.setStyleSheet(
                f"QFrame {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER};"
                " border-radius: 5px; }")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(12, 10, 12, 11)
            box_layout.setSpacing(5)
            caption = QLabel("<b>Worth changing first</b>")
            caption.setStyleSheet("border: none;")
            box_layout.addWidget(caption)
            for cat, finding in suggestions:
                line = QLabel(
                    f"<span style='color:{load_color(finding.load)}'>&#9679;</span> "
                    f"<b>{finding.label}</b> &mdash; {finding.value} "
                    f"<span style='color:{theme.TEXT_DIM}'>({cat.label})</span>")
                line.setWordWrap(True)
                line.setStyleSheet("border: none;")
                box_layout.addWidget(line)
            self.layout_.addWidget(box)
            self.layout_.addSpacing(10)

        # ---- per-category dropdowns ----------------------------------
        heading = QLabel("<b>Where the time goes</b>")
        self.layout_.addWidget(heading)
        self.layout_.addSpacing(6)

        ordered = sorted(report.categories, key=lambda c: c.load, reverse=True)
        for category in ordered:
            block = CategoryBlock(category, self.container)
            if category.load >= 60 or any(f.severity in ("warn", "critical")
                                          for f in category.findings):
                block.set_expanded(True)
            self.layout_.addWidget(block)

        stamp = QLabel(
            "Measured from {} using Blender {}.".format(
                job.analysis.get("scene", "?"),
                job.analysis.get("blender_version", "?")))
        stamp.setObjectName("Hint")
        self.layout_.addSpacing(6)
        self.layout_.addWidget(stamp)
        self.layout_.addStretch(1)

    # ------------------------------------------------------------------

    def report_text(self) -> str:
        """Plain-text version of the current report, for export."""
        if self._job is None or not self._job.analysis:
            return ""
        report = build_report(self._job.analysis)
        lines = [
            f"BlenderQueue analysis - {self._job.name}",
            self._job.blend_path,
            "",
            f"Overall: {report.overall}/100  ({report.rating})",
            report.summary,
            "",
        ]
        for cat in sorted(report.categories, key=lambda c: c.load, reverse=True):
            lines.append(f"{cat.label}  -  load {cat.load}%")
            if cat.headline:
                lines.append(f"    {cat.headline}")
            for finding in cat.sorted_findings():
                lines.append(f"    [{finding.severity}] {finding.label}: {finding.value}"
                             + (f"  (load {finding.load}%)" if finding.load else ""))
                if finding.suggestion:
                    lines.append(f"        -> {finding.suggestion}")
            for label, value in cat.stats:
                lines.append(f"        {label}: {value}")
            lines.append("")
        return "\n".join(lines)
