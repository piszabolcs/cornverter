"""
Frameless window chrome that matches the theme.

The blue/grey native Windows frame clashes with CornVerter's corn-on-black
look, so it is switched off (`Qt.FramelessWindowHint`) and drawn here:

* `TitleBar` - corn badge, wordmark, subtitle and three window buttons
  (minimise / maximise / close). The button icons are painted with QPainter,
  so they do not depend on symbol glyphs in the system font.
* `ShadowShell` - paints a soft shadow around the window body. Deliberately
  not a QGraphicsDropShadowEffect: that would render the whole content into
  an offscreen pixmap, blurring the text and slowing scrolling down.
* `FramelessWindow` - rounded window body; handles dragging by the title
  bar, double click, and resizing along all eight edges.

When maximised, the rounding and the shadow margin are dropped, otherwise an
ugly gap would remain between the screen edge and the window.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .theme import CORN, TEXT_MUTED

# Window button kinds (the painting depends on them).
MIN, MAX, RESTORE, CLOSE = "min", "max", "restore", "close"

# Corner rounding of the window body (the QSS uses the same value).
FRAME_RADIUS = 16

_TOOLTIPS = {MIN: "Minimise", MAX: "Maximise", RESTORE: "Restore",
             CLOSE: "Close"}


class WindowButton(QPushButton):
    """Title bar button with a hand-painted icon."""

    def __init__(self, kind: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(38, 28)
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setObjectName("WinBtnClose" if kind == CLOSE else "WinBtn")
        self.setToolTip(_TOOLTIPS.get(kind, ""))

    def set_kind(self, kind: str) -> None:
        self.kind = kind
        self.setToolTip(_TOOLTIPS[RESTORE if kind == RESTORE else MAX])
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        hot = self.underMouse()
        if self.kind == CLOSE:
            color = QColor("#FFFFFF") if hot else QColor(TEXT_MUTED)
        else:
            color = QColor(CORN) if hot else QColor(TEXT_MUTED)
        p.setPen(QPen(color, 1.3, Qt.SolidLine, Qt.RoundCap))

        c = self.rect().center()
        cx, cy = c.x() + 1, c.y() + 1
        r = 4  # half the icon size

        if self.kind == MIN:
            p.drawLine(cx - r, cy, cx + r, cy)
        elif self.kind == MAX:
            p.drawRect(QRect(cx - r, cy - r, 2 * r, 2 * r))
        elif self.kind == RESTORE:
            p.drawRect(QRect(cx - r, cy - r + 2, 2 * r - 2, 2 * r - 2))
            p.drawLine(cx - r + 2, cy - r, cx + r, cy - r)
            p.drawLine(cx + r, cy - r, cx + r, cy + r - 2)
        elif self.kind == CLOSE:
            p.drawLine(cx - r, cy - r, cx + r, cy + r)
            p.drawLine(cx + r, cy - r, cx - r, cy + r)
        p.end()

    def enterEvent(self, event):  # noqa: N802
        super().enterEvent(event)
        self.update()

    def leaveEvent(self, event):  # noqa: N802
        super().leaveEvent(event)
        self.update()


class TitleBar(QFrame):
    """The top strip of the window: badge, title, subtitle, window buttons."""

    HEIGHT = 54

    def __init__(self, window: "FramelessWindow", title: str, subtitle: str,
                 badge=None, parent=None):
        super().__init__(parent)
        self._window = window
        self._drag_offset: QPoint | None = None
        self.setObjectName("TitleBar")
        self.setFixedHeight(self.HEIGHT)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 10, 0)
        lay.setSpacing(11)

        if badge is not None:
            mark = QLabel()
            mark.setPixmap(badge)
            mark.setFixedSize(badge.size())
            lay.addWidget(mark)

        wordmark = QLabel(title)
        wordmark.setObjectName("Wordmark")
        lay.addWidget(wordmark)

        if subtitle:
            sep = QFrame()
            sep.setObjectName("TitleSep")
            sep.setFixedSize(1, 20)
            lay.addWidget(sep)

            sub = QLabel(subtitle)
            sub.setObjectName("TitleSubtitle")
            lay.addWidget(sub)

        lay.addStretch(1)

        self.btn_min = WindowButton(MIN, self)
        self.btn_max = WindowButton(MAX, self)
        self.btn_close = WindowButton(CLOSE, self)
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max.clicked.connect(window.toggle_maximized)
        self.btn_close.clicked.connect(window.close)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)

    def sync_max_button(self, maximized: bool) -> None:
        self.btn_max.set_kind(RESTORE if maximized else MAX)

    # -------------------------------------------------- drag / double click
    def _on_button(self, pos: QPoint) -> bool:
        return any(b.geometry().contains(pos)
                   for b in (self.btn_min, self.btn_max, self.btn_close))

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and not self._on_button(
                event.position().toPoint()):
            self._drag_offset = (event.globalPosition().toPoint()
                                 - self._window.frameGeometry().topLeft())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._drag_offset is None or not (event.buttons() & Qt.LeftButton):
            super().mouseMoveEvent(event)
            return
        if self._window.isMaximized():
            # Dragged out of the maximised state: restore and keep the window
            # under the cursor so it does not "jump away".
            ratio = event.position().x() / max(self.width(), 1)
            self._window.toggle_maximized()
            self._drag_offset = QPoint(int(self._window.width() * ratio),
                                       self._drag_offset.y())
        self._window.move(event.globalPosition().toPoint() - self._drag_offset)
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and not self._on_button(
                event.position().toPoint()):
            self._window.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class ShadowShell(QWidget):
    """Transparent outer widget that paints a soft shadow round the body."""

    def __init__(self, margin: int, radius: int, parent=None):
        super().__init__(parent)
        self._margin = margin
        self._radius = radius
        self._enabled = True
        self.setObjectName("Shell")
        self.setMouseTracking(True)

    def set_shadow_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self.update()

    def paintEvent(self, event):  # noqa: N802
        if not self._enabled or self._margin <= 0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(Qt.NoBrush)
        m = self._margin
        inner = self.rect().adjusted(m, m, -m, -m)
        # Concentric, fading outlines - the innermost is the strongest.
        for i in range(m, 0, -1):
            t = 1.0 - (i - 1) / m
            alpha = int(64 * t ** 3)
            if alpha <= 0:
                continue
            p.setPen(QPen(QColor(0, 0, 0, alpha), 1))
            p.drawRoundedRect(
                inner.adjusted(-i, -i + 2, i, i + 2),
                self._radius + i, self._radius + i,
            )
        p.end()


class FramelessWindow(QMainWindow):
    """Frameless main window with its own title bar and manual resizing."""

    # Resizing is caught in a band this wide along the window edge.
    RESIZE_MARGIN = 14
    # Transparent margin around the window that the soft shadow needs.
    SHADOW_MARGIN = 14

    def __init__(self, title: str, subtitle: str = "", badge=None):
        super().__init__()
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self._resize_edges = Qt.Edges()
        self._resize_start_geo: QRect | None = None
        self._resize_start_pos: QPoint | None = None

        self._shell = ShadowShell(self.SHADOW_MARGIN, FRAME_RADIUS)
        self._shell_layout = QVBoxLayout(self._shell)
        self._shell_layout.setContentsMargins(*([self.SHADOW_MARGIN] * 4))
        self._shell_layout.setSpacing(0)

        self._frame = QFrame()
        self._frame.setObjectName("WindowFrame")
        self._frame.setMouseTracking(True)
        self._shell_layout.addWidget(self._frame)

        frame_layout = QVBoxLayout(self._frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(0)

        self.title_bar = TitleBar(self, title, subtitle, badge)
        frame_layout.addWidget(self.title_bar)

        self._body = QWidget()
        self._body.setObjectName("Body")
        frame_layout.addWidget(self._body, stretch=1)

        super().setCentralWidget(self._shell)

    # ------------------------------------------------------------------ API
    def body(self) -> QWidget:
        """The application content goes into this widget."""
        return self._body

    def toggle_maximized(self) -> None:
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    # ------------------------------------------------------------- internal
    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange:
            maximized = self.isMaximized()
            m = 0 if maximized else self.SHADOW_MARGIN
            self._shell_layout.setContentsMargins(m, m, m, m)
            self._shell.set_shadow_enabled(not maximized)
            # The rounding changes on the body and the title bar, so both are
            # re-polished for the QSS to apply. The property must NOT be
            # called "maximized": QWidget already owns that (read-only) name,
            # and setProperty would silently fail.
            for w in (self._frame, self.title_bar):
                w.setProperty("cvMaximized", maximized)
                w.style().unpolish(w)
                w.style().polish(w)
            self.title_bar.sync_max_button(maximized)

    def _edges_at(self, pos: QPoint) -> Qt.Edges:
        """Which window edges the cursor is close to.

        Only within the shadow margin (where the main window, not a child,
        gets the mouse moves), and never when maximised.
        """
        if self.isMaximized():
            return Qt.Edges()
        m = min(self.RESIZE_MARGIN, self.SHADOW_MARGIN)
        edges = Qt.Edges()
        if pos.x() <= m:
            edges |= Qt.LeftEdge
        if pos.x() >= self.width() - m:
            edges |= Qt.RightEdge
        if pos.y() <= m:
            edges |= Qt.TopEdge
        if pos.y() >= self.height() - m:
            edges |= Qt.BottomEdge
        return edges

    @staticmethod
    def _cursor_for(edges: Qt.Edges):
        left, right = bool(edges & Qt.LeftEdge), bool(edges & Qt.RightEdge)
        top, bottom = bool(edges & Qt.TopEdge), bool(edges & Qt.BottomEdge)
        if (left and top) or (right and bottom):
            return Qt.SizeFDiagCursor
        if (right and top) or (left and bottom):
            return Qt.SizeBDiagCursor
        if left or right:
            return Qt.SizeHorCursor
        if top or bottom:
            return Qt.SizeVerCursor
        return Qt.ArrowCursor

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                self._resize_edges = edges
                self._resize_start_geo = self.geometry()
                self._resize_start_pos = event.globalPosition().toPoint()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802
        if self._resize_edges and (event.buttons() & Qt.LeftButton):
            self._apply_resize(event.globalPosition().toPoint())
            event.accept()
            return
        self.setCursor(self._cursor_for(
            self._edges_at(event.position().toPoint())))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._resize_edges = Qt.Edges()
        self._resize_start_geo = None
        self._resize_start_pos = None
        self.unsetCursor()
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        if not self._resize_edges:
            self.unsetCursor()
        super().leaveEvent(event)

    def _apply_resize(self, global_pos: QPoint) -> None:
        if self._resize_start_geo is None or self._resize_start_pos is None:
            return
        delta = global_pos - self._resize_start_pos
        geo = QRect(self._resize_start_geo)
        min_w = max(self.minimumWidth(), 320)
        min_h = max(self.minimumHeight(), 240)

        if self._resize_edges & Qt.LeftEdge:
            geo.setLeft(min(geo.left() + delta.x(), geo.right() - min_w))
        if self._resize_edges & Qt.RightEdge:
            geo.setRight(max(geo.right() + delta.x(), geo.left() + min_w))
        if self._resize_edges & Qt.TopEdge:
            geo.setTop(min(geo.top() + delta.y(), geo.bottom() - min_h))
        if self._resize_edges & Qt.BottomEdge:
            geo.setBottom(max(geo.bottom() + delta.y(), geo.top() + min_h))
        self.setGeometry(geo)
