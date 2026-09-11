"""The queue list: drag to reorder, double-click to rename, checkbox to skip."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QStyle,
                               QStyledItemDelegate, QTreeWidget, QTreeWidgetItem)

from ..models import Job, Status
from . import theme

ID_ROLE = Qt.UserRole + 1
PROGRESS_ROLE = Qt.UserRole + 2
STATUS_ROLE = Qt.UserRole + 3

COLUMNS = ("Job", "Status", "Progress", "Frames", "Per Frame", "ETA",
           "Analysis", "Scene", "Overrides", "Blender")


def short_duration(seconds: float) -> str:
    """Compact clock for table cells: 45s, 2m 05s, 1h 12m."""
    seconds = int(round(seconds))
    if seconds <= 0:
        return "-"
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _rating_color(overall: int) -> str:
    from ..analysis import RATINGS
    for ceiling, _name, color in RATINGS:
        if overall < ceiling:
            return color
    return theme.FAIL


class ProgressDelegate(QStyledItemDelegate):
    """Draws an inline bar for the Progress column."""

    def paint(self, painter: QPainter, option, index):
        fraction = index.data(PROGRESS_ROLE)
        status = index.data(STATUS_ROLE) or Status.PENDING

        # option.state is a QStyle.StateFlag; PySide6 will not compare it
        # against a bare int. An exception raised here escapes into whatever
        # is currently spinning the event loop -- a modal dialog, say -- and
        # breaks something entirely unrelated, so keep this exact.
        if option.state & QStyle.StateFlag.State_Selected:
            painter.fillRect(option.rect, QColor(theme.ACCENT_DIM))

        if fraction is None:
            super().paint(painter, option, index)
            return

        rect = QRectF(option.rect).adjusted(6, 6, -6, -6)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        painter.setPen(QPen(QColor(theme.BORDER), 1))
        painter.setBrush(QColor(theme.BG))
        painter.drawRoundedRect(rect, 3, 3)

        color = theme.STATUS_COLORS.get(status, theme.ACCENT)
        if fraction > 0:
            filled = QRectF(rect)
            filled.setWidth(max(3.0, rect.width() * min(1.0, fraction)))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(filled, 3, 3)

        painter.setPen(QColor(theme.TEXT if fraction < 0.55 else "#1a1a1a"))
        painter.drawText(option.rect, Qt.AlignCenter, f"{int(round(fraction * 100))}%")
        painter.restore()


class QueueView(QTreeWidget):
    """Presents the job list and reports edits back to the main window."""

    orderChanged = Signal(list)            # list of job ids, new order
    renamed = Signal(str, str)             # job_id, new name
    enabledToggled = Signal(str, bool)     # job_id, enabled
    activated_job = Signal(str)            # job_id (double click outside the name column)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(COLUMNS))
        self.setHeaderLabels(COLUMNS)
        self.setRootIsDecorated(False)
        self.setAlternatingRowColors(True)
        self.setUniformRowHeights(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setEditTriggers(QAbstractItemView.EditKeyPressed
                             | QAbstractItemView.SelectedClicked)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setItemDelegateForColumn(2, ProgressDelegate(self))

        header = self.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 92), (2, 96), (3, 104), (4, 86), (5, 84),
                           (6, 104), (7, 100), (8, 116), (9, 92)):
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            self.setColumnWidth(col, width)

        self._guard = False
        self.itemChanged.connect(self._on_item_changed)
        self.itemDoubleClicked.connect(self._on_double_click)

    # ------------------------------------------------------------------
    # population
    # ------------------------------------------------------------------

    def rebuild(self, jobs: list, blender_label):
        """Full refresh, preserving selection where possible."""
        selected = set(self.selected_ids())
        scroll = self.verticalScrollBar().value()

        self._guard = True
        self.clear()
        for index, job in enumerate(jobs):
            item = QTreeWidgetItem(self)
            item.setData(0, ID_ROLE, job.id)
            flags = item.flags() | Qt.ItemIsUserCheckable
            flags &= ~Qt.ItemIsDropEnabled
            if job.is_locked:
                # a job being rendered right now must not be renamed, dragged
                # or switched off underneath the running Blender process
                flags &= ~(Qt.ItemIsEditable | Qt.ItemIsDragEnabled
                           | Qt.ItemIsUserCheckable)
            else:
                flags |= Qt.ItemIsEditable | Qt.ItemIsDragEnabled
            item.setFlags(flags)
            self._fill(item, job, index, blender_label)
            if job.id in selected:
                item.setSelected(True)
        self._guard = False
        self.verticalScrollBar().setValue(scroll)

    def update_job(self, job: Job, index: int, blender_label):
        item = self._item_for(job.id)
        if item is None:
            return
        self._guard = True
        self._fill(item, job, index, blender_label)
        self._guard = False

    def _fill(self, item: QTreeWidgetItem, job: Job, index: int, blender_label):
        item.setCheckState(0, Qt.Checked if job.enabled else Qt.Unchecked)
        item.setText(0, job.name)
        missing = not job.exists
        item.setForeground(0, QColor(theme.FAIL if missing else theme.TEXT))
        tip = job.blend_path or "(no file)"
        if missing:
            tip += "\n\nThis file could not be found."
        if job.notes:
            tip += "\n\n" + job.notes
        item.setToolTip(0, tip)

        item.setText(1, job.status)
        item.setForeground(1, QColor(theme.STATUS_COLORS.get(job.status, theme.TEXT)))

        fraction = None
        if job.status == Status.RUNNING:
            fraction = (job.frames_done / job.frames_total) if job.frames_total else 0.0
        elif job.status == Status.DONE:
            fraction = 1.0
        elif job.status in (Status.FAILED, Status.CANCELLED) and job.frames_total:
            fraction = job.frames_done / job.frames_total
        item.setData(2, PROGRESS_ROLE, fraction)
        item.setData(2, STATUS_ROLE, job.status)
        item.setText(2, "" if fraction is not None else job.message)
        item.setToolTip(2, job.message)

        item.setText(3, self._frame_text(job))

        running = job.status == Status.RUNNING
        per_frame = job.seconds_per_frame
        item.setText(4, short_duration(per_frame) if per_frame else "-")
        item.setToolTip(4, "Average of the last 25 finished frames"
                        if len(job.frame_times) > 1 else "")
        item.setText(5, short_duration(job.eta_seconds) if running and job.eta_seconds
                     else ("-" if not job.frame_times else short_duration(0)))
        if running and job.eta_seconds:
            item.setToolTip(5, "{} frame(s) left at {} each".format(
                job.frames_remaining, short_duration(per_frame)))

        score = job.analysis_score()
        if score is None:
            item.setText(6, "-")
            item.setForeground(6, QColor(theme.TEXT_DIM))
        else:
            overall, rating = score
            item.setText(6, f"{overall}  {rating}")
            item.setForeground(6, QColor(_rating_color(overall)))
            item.setToolTip(6, f"Estimated render load {overall}/100")

        item.setText(7, job.selected_scene() or "-")
        item.setText(8, job.summary())
        item.setText(9, blender_label(job) or "Default")
        for col in (3, 4, 5, 7, 8, 9):
            item.setForeground(col, QColor(theme.TEXT_DIM))

    def _frame_text(self, job: Job) -> str:
        if job.status == Status.RUNNING and job.frames_total:
            return f"{job.frames_done}/{job.frames_total}  (f{job.current_frame})"
        values = job.group("frames").values if job.use_overrides else {}
        if job.use_overrides and job.group("frames").enabled:
            if values.get("frame_mode") == "STILL":
                return f"still  {values.get('frame_current', 1)}"
            start = values.get("frame_start", 1)
            end = values.get("frame_end", 1)
            step = values.get("frame_step", 1)
            return f"{start}-{end}" + (f" /{step}" if step and step != 1 else "")
        scene = job.scene_info()
        if scene:
            return f"{scene.get('frame_start', '?')}-{scene.get('frame_end', '?')}"
        return "-"

    # ------------------------------------------------------------------
    # queries
    # ------------------------------------------------------------------

    def _item_for(self, job_id: str):
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if item.data(0, ID_ROLE) == job_id:
                return item
        return None

    def selected_ids(self) -> list:
        return [i.data(0, ID_ROLE) for i in self.selectedItems()]

    def current_id(self) -> str:
        # setSelected() fires before setCurrentItem(), so fall back to the
        # selection rather than reporting "nothing selected" in between.
        item = self.currentItem()
        if item is None or not item.isSelected():
            chosen = self.selectedItems()
            item = chosen[0] if chosen else item
        return item.data(0, ID_ROLE) if item else ""

    def all_ids(self) -> list:
        return [self.topLevelItem(i).data(0, ID_ROLE)
                for i in range(self.topLevelItemCount())]

    def select_ids(self, ids: list):
        self.clearSelection()
        first = None
        for job_id in ids:
            item = self._item_for(job_id)
            if item is not None:
                item.setSelected(True)
                first = first or item
        if first is not None:
            self.setCurrentItem(first)
            self.scrollToItem(first)

    def edit_name(self, job_id: str):
        item = self._item_for(job_id)
        if item is not None:
            self.setCurrentItem(item)
            self.editItem(item, 0)

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------

    def dropEvent(self, event):
        super().dropEvent(event)
        self.orderChanged.emit(self.all_ids())

    def _on_item_changed(self, item, column):
        if self._guard or column != 0:
            return
        job_id = item.data(0, ID_ROLE)
        self.enabledToggled.emit(job_id, item.checkState(0) == Qt.Checked)
        self.renamed.emit(job_id, item.text(0).strip())

    def _on_double_click(self, item, column):
        if column != 0:
            self.activated_job.emit(item.data(0, ID_ROLE))
