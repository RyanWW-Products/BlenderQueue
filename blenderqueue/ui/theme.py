"""Dark theme plus vector icons drawn at runtime.

Icons are painted with QPainter rather than loaded from files so the packaged
executable stays a single self-contained binary.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

# --------------------------------------------------------------------------
# palette
# --------------------------------------------------------------------------

BG = "#1e1f22"
PANEL = "#2b2d30"
PANEL_ALT = "#333539"
BORDER = "#43464d"
TEXT = "#d8d8d8"
TEXT_DIM = "#9a9da3"
ACCENT = "#e87d0d"
ACCENT_DIM = "#a75c0c"
OK = "#5fb85f"
FAIL = "#d9534f"
WARN = "#e0a30c"
INFO = "#4a9edd"

STATUS_COLORS = {
    "Pending": TEXT_DIM,
    "Rendering": ACCENT,
    "Done": OK,
    "Failed": FAIL,
    "Cancelled": WARN,
    "Skipped": TEXT_DIM,
}


# --------------------------------------------------------------------------
# icons
# --------------------------------------------------------------------------

def _pen(painter: QPainter, color: str, width: float = 1.7) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    return pen


def _triangle(painter, points, color):
    path = QPainterPath()
    path.moveTo(QPointF(*points[0]))
    for point in points[1:]:
        path.lineTo(QPointF(*point))
    path.closeSubpath()
    painter.fillPath(path, QColor(color))


def _draw(name: str, painter: QPainter, color: str):
    """Every icon is drawn inside a nominal 24x24 box."""
    c = color

    if name in ("add-file", "file"):
        _pen(painter, c)
        painter.drawPolyline([QPointF(6, 3), QPointF(14, 3), QPointF(19, 8),
                              QPointF(19, 21), QPointF(6, 21), QPointF(6, 3)])
        painter.drawPolyline([QPointF(14, 3), QPointF(14, 8), QPointF(19, 8)])
        if name == "add-file":
            _pen(painter, ACCENT, 2.2)
            painter.drawLine(QPointF(10, 15), QPointF(16, 15))
            painter.drawLine(QPointF(13, 12), QPointF(13, 18))

    elif name in ("add-folder", "folder", "folder-open"):
        _pen(painter, c)
        painter.drawPolyline([QPointF(3, 19), QPointF(3, 6), QPointF(10, 6),
                              QPointF(12, 9), QPointF(21, 9), QPointF(21, 19),
                              QPointF(3, 19)])
        if name == "add-folder":
            _pen(painter, ACCENT, 2.2)
            painter.drawLine(QPointF(9, 14), QPointF(15, 14))
            painter.drawLine(QPointF(12, 11), QPointF(12, 17))
        elif name == "folder-open":
            _pen(painter, ACCENT, 1.7)
            painter.drawPolyline([QPointF(3, 19), QPointF(7, 12), QPointF(23, 12),
                                  QPointF(21, 19)])

    elif name == "remove":
        _pen(painter, c, 1.8)
        painter.drawLine(QPointF(4, 7), QPointF(20, 7))
        painter.drawPolyline([QPointF(6, 7), QPointF(7, 21), QPointF(17, 21), QPointF(18, 7)])
        painter.drawPolyline([QPointF(9, 7), QPointF(9, 4), QPointF(15, 4), QPointF(15, 7)])
        painter.drawLine(QPointF(10, 11), QPointF(10, 17))
        painter.drawLine(QPointF(14, 11), QPointF(14, 17))

    elif name == "duplicate":
        _pen(painter, c)
        painter.drawRect(QRectF(3, 3, 12, 12))
        _pen(painter, ACCENT)
        painter.drawRect(QRectF(9, 9, 12, 12))

    elif name == "rename":
        _pen(painter, c)
        painter.drawPolyline([QPointF(4, 17), QPointF(4, 20), QPointF(7, 20)])
        painter.drawLine(QPointF(4, 17), QPointF(16, 5))
        painter.drawLine(QPointF(7, 20), QPointF(19, 8))
        _pen(painter, ACCENT)
        painter.drawLine(QPointF(16, 5), QPointF(19, 8))

    elif name in ("up", "down", "top", "bottom"):
        flip = name in ("down", "bottom")
        _pen(painter, c, 2.0)
        if flip:
            painter.drawPolyline([QPointF(7, 11), QPointF(12, 16), QPointF(17, 11)])
            painter.drawLine(QPointF(12, 16), QPointF(12, 5))
            if name == "bottom":
                painter.drawLine(QPointF(6, 20), QPointF(18, 20))
        else:
            painter.drawPolyline([QPointF(7, 13), QPointF(12, 8), QPointF(17, 13)])
            painter.drawLine(QPointF(12, 8), QPointF(12, 19))
            if name == "top":
                painter.drawLine(QPointF(6, 4), QPointF(18, 4))

    elif name == "play":
        _triangle(painter, [(7, 4), (20, 12), (7, 20)], OK)

    elif name == "pause":
        painter.fillRect(QRectF(7, 4, 4, 16), QColor(WARN))
        painter.fillRect(QRectF(14, 4, 4, 16), QColor(WARN))

    elif name == "stop":
        painter.fillRect(QRectF(6, 6, 12, 12), QColor(FAIL))

    elif name == "skip":
        _triangle(painter, [(6, 5), (15, 12), (6, 19)], c)
        painter.fillRect(QRectF(16, 5, 3, 14), QColor(c))

    elif name == "path":
        _pen(painter, c, 1.8)
        path = QPainterPath()
        path.moveTo(3, 18)
        path.cubicTo(8, 18, 8, 7, 13, 7)
        path.cubicTo(18, 7, 17, 16, 21, 16)
        painter.drawPath(path)
        painter.setBrush(QColor(ACCENT))
        _pen(painter, ACCENT, 1.0)
        painter.drawEllipse(QPointF(3, 18), 2.4, 2.4)
        painter.drawEllipse(QPointF(21, 16), 2.4, 2.4)
        painter.setBrush(Qt.NoBrush)

    elif name == "settings":
        _pen(painter, c, 1.7)
        painter.drawEllipse(QPointF(12, 12), 4.0, 4.0)
        for i in range(8):
            from math import cos, pi, sin
            angle = i * pi / 4
            painter.drawLine(QPointF(12 + 6.2 * cos(angle), 12 + 6.2 * sin(angle)),
                             QPointF(12 + 9.0 * cos(angle), 12 + 9.0 * sin(angle)))

    elif name == "refresh":
        _pen(painter, c, 1.9)
        rect = QRectF(4, 4, 16, 16)
        painter.drawArc(rect, 60 * 16, 260 * 16)
        _triangle(painter, [(17, 2), (21, 8), (14, 8)], c)

    elif name == "save":
        _pen(painter, c)
        painter.drawPolyline([QPointF(4, 4), QPointF(17, 4), QPointF(20, 7),
                              QPointF(20, 20), QPointF(4, 20), QPointF(4, 4)])
        painter.drawRect(QRectF(8, 4, 8, 6))
        _pen(painter, ACCENT)
        painter.drawRect(QRectF(7, 13, 10, 7))

    elif name == "open":
        _pen(painter, c)
        painter.drawPolyline([QPointF(3, 19), QPointF(3, 6), QPointF(10, 6),
                              QPointF(12, 9), QPointF(20, 9)])
        _pen(painter, ACCENT)
        painter.drawPolyline([QPointF(3, 19), QPointF(7, 12), QPointF(23, 12),
                              QPointF(19, 19), QPointF(3, 19)])

    elif name == "clear":
        _pen(painter, FAIL, 2.0)
        painter.drawLine(QPointF(6, 6), QPointF(18, 18))
        painter.drawLine(QPointF(18, 6), QPointF(6, 18))

    elif name == "check":
        _pen(painter, OK, 2.4)
        painter.drawPolyline([QPointF(5, 12), QPointF(10, 17), QPointF(19, 6)])

    elif name == "camera":
        _pen(painter, c)
        painter.drawRoundedRect(QRectF(3, 7, 14, 11), 2, 2)
        _triangle(painter, [(18, 10), (22, 7), (22, 18), (18, 15)], ACCENT)

    elif name == "engine":
        _pen(painter, c, 1.7)
        painter.drawEllipse(QPointF(12, 12), 8.0, 8.0)
        painter.drawEllipse(QPointF(12, 12), 3.0, 3.0)
        _pen(painter, ACCENT, 1.7)
        painter.drawLine(QPointF(12, 4), QPointF(12, 9))

    elif name == "output":
        _pen(painter, c)
        painter.drawRect(QRectF(4, 4, 16, 12))
        _pen(painter, ACCENT, 2.0)
        painter.drawLine(QPointF(12, 10), QPointF(12, 21))
        painter.drawPolyline([QPointF(8, 17), QPointF(12, 21), QPointF(16, 17)])

    elif name == "frames":
        _pen(painter, c)
        painter.drawRect(QRectF(3, 6, 18, 12))
        for x in (7, 11, 15):
            painter.drawLine(QPointF(x, 6), QPointF(x, 18))

    elif name == "info":
        _pen(painter, INFO, 1.8)
        painter.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        painter.drawLine(QPointF(12, 11), QPointF(12, 17))
        painter.drawPoint(QPointF(12, 7.5))

    elif name == "queue":
        _pen(painter, c, 1.8)
        for y in (6, 12, 18):
            painter.drawLine(QPointF(9, y), QPointF(21, y))
        _pen(painter, ACCENT, 1.8)
        for y in (6, 12, 18):
            painter.drawPoint(QPointF(4, y))
            painter.drawEllipse(QPointF(4, y), 1.4, 1.4)

    elif name == "app":
        _pen(painter, ACCENT, 2.0)
        painter.drawEllipse(QPointF(12, 12), 8.5, 8.5)
        _triangle(painter, [(9, 7), (18, 12), (9, 17)], ACCENT)


_ICON_CACHE: dict = {}


def icon(name: str, color: str = TEXT, size: int = 24) -> QIcon:
    key = (name, color, size)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(size / 24.0, size / 24.0)
    _draw(name, painter, color)
    painter.end()

    result = QIcon(pixmap)
    _ICON_CACHE[key] = result
    return result


def app_icon() -> QIcon:
    result = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.scale(size / 24.0, size / 24.0)
        painter.setBrush(QColor(PANEL))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(QRectF(1, 1, 22, 22), 5, 5)
        _draw("app", painter, ACCENT)
        painter.end()
        result.addPixmap(pixmap)
    return result


# --------------------------------------------------------------------------
# stylesheet
# --------------------------------------------------------------------------

STYLESHEET = f"""
QWidget {{
    background: {BG};
    color: {TEXT};
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 9.5pt;
}}
QMainWindow, QDialog {{ background: {BG}; }}

QToolTip {{
    background: {PANEL_ALT};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 5px 7px;
}}

/* ---- ribbon ---- */
#RibbonBar {{ background: {PANEL}; border-bottom: 1px solid {BORDER}; }}
#RibbonTabs {{ background: {PANEL}; border: none; }}
#RibbonTabs::pane {{ border: none; background: {PANEL}; }}
#RibbonTabs::tab-bar {{ left: 8px; }}
#RibbonTabs QTabBar::tab {{
    background: transparent;
    color: {TEXT_DIM};
    padding: 7px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    margin-right: 2px;
}}
#RibbonTabs QTabBar::tab:hover {{ color: {TEXT}; }}
#RibbonTabs QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}
#RibbonGroup {{ background: transparent; }}
#RibbonGroupTitle {{ color: {TEXT_DIM}; font-size: 8pt; }}
#RibbonSeparator {{ background: {BORDER}; max-width: 1px; }}

QToolButton {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 4px;
    color: {TEXT};
}}
QToolButton:hover {{ background: {PANEL_ALT}; border: 1px solid {BORDER}; }}
QToolButton:pressed {{ background: {BORDER}; }}
QToolButton:disabled {{ color: {TEXT_DIM}; }}
QToolButton:checked {{ background: {ACCENT_DIM}; border: 1px solid {ACCENT}; }}

/* ---- panels ---- */
#SidePanel, #DetailPanel {{ background: {PANEL}; }}
#PanelHeader {{
    background: {PANEL_ALT};
    border-bottom: 1px solid {BORDER};
    padding: 6px 10px;
    font-weight: 600;
}}
#Hint {{ color: {TEXT_DIM}; font-size: 8.5pt; }}
#GroupBlurb {{ color: {TEXT_DIM}; font-size: 8.5pt; }}
#BigStat {{ font-size: 15pt; font-weight: 600; color: {TEXT}; }}
#StatLabel {{ color: {TEXT_DIM}; font-size: 8pt; }}

/* ---- collapsible override groups ---- */
#GroupHeader {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
}}
#GroupHeader:hover {{ background: {BORDER}; }}
#GroupToggle {{
    background: transparent;
    border: none;
    text-align: left;
    padding: 7px 8px;
    font-weight: 600;
    color: {TEXT};
}}
#GroupBody {{
    background: {PANEL};
    border: 1px solid {BORDER};
    border-top: none;
    border-radius: 0 0 4px 4px;
}}

/* ---- inputs ---- */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 3px;
    padding: 4px 6px;
    selection-background-color: {ACCENT_DIM};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled,
QComboBox:disabled, QCheckBox:disabled {{ color: {TEXT_DIM}; }}
QComboBox::drop-down {{ border: none; width: 18px; }}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {TEXT_DIM};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DIM};
    outline: none;
}}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    background: {PANEL_ALT};
    border: none;
    width: 14px;
}}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {{ background: {BORDER}; }}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    border-left: 3px solid transparent; border-right: 3px solid transparent;
    border-bottom: 4px solid {TEXT_DIM};
}}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    border-left: 3px solid transparent; border-right: 3px solid transparent;
    border-top: 4px solid {TEXT_DIM};
}}

QCheckBox {{ spacing: 7px; }}
QCheckBox::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {BORDER};
    border-radius: 3px;
    background: {BG};
}}
QCheckBox::indicator:hover {{ border: 1px solid {ACCENT}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}

QPushButton {{
    background: {PANEL_ALT};
    border: 1px solid {BORDER};
    border-radius: 4px;
    padding: 6px 14px;
}}
QPushButton:hover {{ background: {BORDER}; }}
QPushButton:pressed {{ background: {ACCENT_DIM}; }}
QPushButton:disabled {{ color: {TEXT_DIM}; background: {PANEL}; }}
QPushButton#Primary {{
    background: {ACCENT}; border: 1px solid {ACCENT}; color: #1a1a1a; font-weight: 600;
}}
QPushButton#Primary:hover {{ background: #f28c1c; }}
QPushButton#Primary:disabled {{ background: {PANEL}; color: {TEXT_DIM}; border: 1px solid {BORDER}; }}

/* ---- lists / trees ---- */
QTreeWidget, QTreeView, QListWidget, QTableWidget {{
    background: {BG};
    border: 1px solid {BORDER};
    alternate-background-color: #232427;
    outline: none;
}}
QTreeWidget::item, QListWidget::item {{ padding: 5px 2px; border: none; }}
QTreeWidget::item:hover, QListWidget::item:hover {{ background: {PANEL_ALT}; }}
QTreeWidget::item:selected, QListWidget::item:selected,
QTableWidget::item:selected {{ background: {ACCENT_DIM}; color: #fff; }}
QHeaderView::section {{
    background: {PANEL_ALT};
    color: {TEXT_DIM};
    border: none;
    border-right: 1px solid {BORDER};
    border-bottom: 1px solid {BORDER};
    padding: 5px 6px;
}}
QTreeWidget::branch {{ background: transparent; }}

/* ---- misc ---- */
QProgressBar {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 3px;
    text-align: center;
    height: 16px;
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 2px; }}

QSplitter::handle {{ background: {BORDER}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}

QScrollBar:vertical {{ background: {BG}; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 5px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {TEXT_DIM}; }}
QScrollBar:horizontal {{ background: {BG}; height: 11px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {BORDER}; border-radius: 5px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QStatusBar {{ background: {PANEL}; border-top: 1px solid {BORDER}; color: {TEXT_DIM}; }}
QStatusBar::item {{ border: none; }}

QMenu {{ background: {PANEL_ALT}; border: 1px solid {BORDER}; padding: 4px; }}
QMenu::item {{ padding: 6px 26px 6px 12px; border-radius: 3px; }}
QMenu::item:selected {{ background: {ACCENT_DIM}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

QTabWidget::pane {{ border: 1px solid {BORDER}; background: {PANEL}; }}
QTabBar::tab {{
    background: {PANEL}; color: {TEXT_DIM};
    padding: 6px 14px; border: 1px solid {BORDER}; border-bottom: none;
}}
QTabBar::tab:selected {{ background: {PANEL_ALT}; color: {TEXT}; }}

#LogView {{
    background: #17181a;
    font-family: "Cascadia Mono", "Consolas", monospace;
    font-size: 8.5pt;
    border: 1px solid {BORDER};
}}
"""
