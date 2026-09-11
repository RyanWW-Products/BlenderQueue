"""An Office-style ribbon: tabs of labelled button groups."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QSizePolicy, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from . import theme


class RibbonGroup(QWidget):
    """A titled cluster of buttons inside a ribbon tab."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonGroup")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 2)
        outer.setSpacing(2)

        self.body = QHBoxLayout()
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(3)
        outer.addLayout(self.body, 1)

        caption = QLabel(title)
        caption.setObjectName("RibbonGroupTitle")
        caption.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        outer.addWidget(caption)

    # -- buttons ------------------------------------------------------

    def add_big(self, action, width: int = 86) -> QToolButton:
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        button.setIconSize(QSize(28, 28))
        button.setFixedSize(width, 74)
        button.setCursor(Qt.PointingHandCursor)
        self.body.addWidget(button, 0, Qt.AlignTop)
        return button

    def add_small(self, action) -> QToolButton:
        button = QToolButton(self)
        button.setDefaultAction(action)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setIconSize(QSize(17, 17))
        button.setFixedHeight(23)
        button.setCursor(Qt.PointingHandCursor)
        button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return button

    def add_stack(self, *actions) -> QWidget:
        """Up to three small buttons stacked vertically in one ribbon slot."""
        column = QWidget(self)
        layout = QVBoxLayout(column)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        for action in actions:
            layout.addWidget(self.add_small(action))
        layout.addStretch(1)
        self.body.addWidget(column, 0, Qt.AlignTop)
        return column

    def add_widget(self, widget: QWidget) -> QWidget:
        self.body.addWidget(widget, 0, Qt.AlignTop)
        return widget


class RibbonTab(QWidget):
    """One ribbon page."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(4, 4, 4, 2)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)

    def add_group(self, title: str) -> RibbonGroup:
        group = RibbonGroup(title, self)
        index = self._layout.count() - 1          # keep the trailing stretch last
        if index > 0:
            separator = QFrame(self)
            separator.setObjectName("RibbonSeparator")
            separator.setFrameShape(QFrame.VLine)
            separator.setFixedWidth(1)
            self._layout.insertWidget(index, separator)
            index += 1
        self._layout.insertWidget(index, group)
        return group


class Ribbon(QTabWidget):
    """The ribbon bar itself."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RibbonTabs")
        self.setDocumentMode(True)
        self.setFixedHeight(146)

    def add_tab(self, title: str) -> RibbonTab:
        tab = RibbonTab(self)
        self.addTab(tab, title)
        return tab


def make_action(parent, text: str, icon_name: str, tip: str = "",
                shortcut: str = "", checkable: bool = False,
                color: str = theme.TEXT):
    """Convenience wrapper so the main window stays readable."""
    from PySide6.QtGui import QAction, QKeySequence

    action = QAction(text, parent)
    if icon_name:
        action.setIcon(theme.icon(icon_name, color, 32))
    if shortcut:
        action.setShortcut(QKeySequence(shortcut))
        tip = f"{tip}  ({shortcut})" if tip else shortcut
    if tip:
        action.setToolTip(tip)
        action.setStatusTip(tip)
    action.setCheckable(checkable)
    return action
