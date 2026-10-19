"""Soft fades at the top and bottom edge of any scrolling widget.

Qt cannot mask a widget with a gradient, so two thin overlays sit on the
viewport's edges and paint the background colour fading into transparency.
Each one shows only while there is more content in its direction, so the
first and last lines are never dimmed when nothing is hidden. The overlays
ignore the mouse, clicks go straight through to the content. They cover the
viewport only, so a fixed header above it (a tree's column header) and the
scroll bar beside it stay untouched.

Works with every QAbstractScrollArea: QScrollArea, QPlainTextEdit, QTextEdit,
QTreeView, QTableView, QListView and their subclasses.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

FADE_HEIGHT = 26


class _EdgeFade(QWidget):
    def __init__(self, parent, color, top):
        super().__init__(parent)
        self._color = QColor(color)
        self._top = top
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.hide()

    def paintEvent(self, event):
        gradient = QLinearGradient(0, 0, 0, self.height())
        solid = QColor(self._color)
        clear = QColor(self._color)
        clear.setAlpha(0)
        gradient.setColorAt(0.0, solid if self._top else clear)
        gradient.setColorAt(1.0, clear if self._top else solid)
        painter = QPainter(self)
        painter.fillRect(self.rect(), gradient)
        painter.end()


class ScrollFade(QObject):
    """The two edge overlays of one scroll area; `top`/`bottom` are the overlay widgets."""

    def __init__(self, area, top_color, bottom_color=None):
        super().__init__(area)
        self._area = area
        self.top = _EdgeFade(area, top_color, top=True)
        self.bottom = _EdgeFade(area, bottom_color or top_color, top=False)
        bar = area.verticalScrollBar()
        bar.valueChanged.connect(self._update)
        bar.rangeChanged.connect(self._update)
        area.viewport().installEventFilter(self)
        self._place()

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Move):
            self._place()
        return False

    def _place(self):
        viewport = self._area.viewport().geometry()
        height = min(FADE_HEIGHT, viewport.height() // 3)
        self.top.setGeometry(viewport.x(), viewport.y(), viewport.width(), height)
        self.bottom.setGeometry(viewport.x(), viewport.bottom() - height + 1, viewport.width(), height)
        self._update()

    def _update(self, *_):
        bar = self._area.verticalScrollBar()
        self.top.setVisible(bar.value() > bar.minimum())
        self.bottom.setVisible(bar.value() < bar.maximum())
        self.top.raise_()
        self.bottom.raise_()


def attach_scroll_fade(area, top_color, bottom_color=None):
    """Fade `area`'s content out at its top and bottom edge. `top_color`/`bottom_color`
    are the colours behind the content there (the viewport's background); returns the
    ScrollFade, which lives as long as the area."""
    return ScrollFade(area, top_color, bottom_color)
