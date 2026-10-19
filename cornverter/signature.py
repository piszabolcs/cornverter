"""
Author signature in the footer and the "app info" card behind it.

The footer's right end holds a small, muted `psz // v<version>` button with
no border or box. On hover or keyboard focus it glows in the theme accent
(not a hard-coded colour); a click opens a compact release card: name and
version, purpose, architecture layers, what it is built with, repositories.

The glow is a `QGraphicsDropShadowEffect` animated by `QPropertyAnimation`.
The animation is decoration only: the brighter text alone marks the active
state. The version comes from `cornverter.__version__` - the single source
of truth - and is printed nowhere else.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from . import __app_name__, __version__
from .chrome import CLOSE, WindowButton
from .scroll_fade import attach_scroll_fade
from .theme import ACCENT, SIGNATURE_QSS, SURFACE

AUTHOR_LABEL = f"psz // v{__version__}"

ABOUT_TITLE = __app_name__
ABOUT_SUBTITLE = f"v{__version__}"


def _link(url: str, text: str) -> str:
    return f'<a href="https://{url}">{text}</a>'


# The card lists only what the program really uses.
ABOUT_SECTIONS: list[tuple[str, list[str]]] = [
    ("What it does", [
        "Turns a folder of mixed files - spreadsheets, documents, e-mails, "
        "images, archives - into PDFs in one run: into a separate folder, or "
        "in place with the originals moved to a backup folder. No OCR.",
    ]),
    ("Architecture", [
        "GUI - PySide6 window with its own frame, conversion on a worker "
        "thread",
        "Engine - folder scan, task list, atomic writes, backups and reports; "
        "Qt-free, shared with the command line",
        "Converters - one per file type: LibreOffice when installed, built-in "
        "reportlab renderers otherwise",
    ]),
    ("Built with", [
        "Python 3.12 · PySide6 (Qt) · reportlab · pypdf",
        "img2pdf + Pillow · openpyxl · xlrd · extract-msg · py7zr · rarfile",
        "LibreOffice (optional, external)",
    ]),
    ("Repositories", [
        "CornVerter - github.com/piszabolcs/CornVerter",
        "Upstream: " + ", ".join([
            _link("github.com/py-pdf/pypdf", "pypdf"),
            _link("github.com/python-pillow/Pillow", "Pillow"),
            _link("github.com/TeamMsgExtractor/msg-extractor", "extract-msg"),
            _link("github.com/miurahr/py7zr", "py7zr"),
            _link("github.com/markokr/rarfile", "rarfile"),
            _link("github.com/LibreOffice/core", "LibreOffice"),
        ]),
    ]),
]


class AboutDialog(QDialog):
    """Compact release card; closes on X, Esc or a click outside."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setModal(True)
        self.setObjectName("AboutDialog")
        self.setStyleSheet(SIGNATURE_QSS)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QWidget()
        card.setObjectName("AboutCard")
        outer.addWidget(card)

        lay = QVBoxLayout(card)
        lay.setContentsMargins(24, 20, 24, 18)
        lay.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        title = QLabel(ABOUT_TITLE)
        title.setObjectName("AboutTitle")
        subtitle = QLabel(ABOUT_SUBTITLE)
        subtitle.setObjectName("AboutSubtitle")
        head.addWidget(title)
        head.addWidget(subtitle)
        head.addStretch(1)

        # The same hand-drawn X as the window's close button - no reliance on
        # a "✕" glyph in the system font.
        close = WindowButton(CLOSE, self)
        close.setObjectName("AboutClose")
        close.setFixedSize(28, 28)
        close.setCursor(Qt.PointingHandCursor)
        close.setToolTip("Close (Esc)")
        close.clicked.connect(self.reject)
        head.addWidget(close)
        lay.addLayout(head)

        rule = QWidget()
        rule.setObjectName("AboutRule")
        rule.setFixedHeight(1)
        lay.addWidget(rule)

        body = QWidget()
        body_lay = QVBoxLayout(body)
        body_lay.setContentsMargins(0, 2, 8, 2)
        body_lay.setSpacing(4)
        for heading, items in ABOUT_SECTIONS:
            h = QLabel(heading)
            h.setObjectName("AboutHeading")
            body_lay.addWidget(h)
            for item in items:
                row = QLabel(f"•  {item}")
                row.setObjectName("AboutItem")
                row.setWordWrap(True)
                row.setTextFormat(Qt.RichText)
                row.setOpenExternalLinks(True)
                body_lay.addWidget(row)
            body_lay.addSpacing(6)
        body_lay.addStretch(1)

        # Scrollable body, so the card fits small screens too.
        scroll = QScrollArea()
        scroll.setObjectName("AboutScroll")
        scroll.setWidget(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_fade = attach_scroll_fade(scroll, SURFACE)
        lay.addWidget(scroll, stretch=1)

        self.setFixedWidth(520)
        self.setMinimumHeight(380)
        self.setMaximumHeight(560)

    # A click outside the card closes it.
    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._center_on_parent()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def hideEvent(self, event):  # noqa: N802
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        super().hideEvent(event)

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Type.MouseButtonPress and self.isVisible():
            local = self.mapFromGlobal(event.globalPosition().toPoint())
            if not self.rect().contains(local):
                self.reject()
                return True
        return super().eventFilter(obj, event)

    def _center_on_parent(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        ref = parent.window().frameGeometry()
        self.move(ref.center().x() - self.width() // 2,
                  ref.center().y() - self.height() // 2)


class SignatureButton(QPushButton):
    """Footer signature: quiet text, accent glow, opens the release card."""

    GLOW_MAX = 22

    def __init__(self, label: str = AUTHOR_LABEL, accent: str = ACCENT,
                 parent=None):
        super().__init__(label, parent)
        self.setObjectName("Signature")
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)
        self.setToolTip("About CornVerter")

        self._glow = QGraphicsDropShadowEffect(self)
        self._glow.setOffset(0, 0)
        self._glow.setBlurRadius(0)
        self._glow.setColor(QColor(accent))
        self.setGraphicsEffect(self._glow)

        self._anim = QPropertyAnimation(self._glow, b"blurRadius", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)

        self.clicked.connect(self.show_about)

    def _glow_to(self, value: int) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._glow.blurRadius())
        self._anim.setEndValue(value)
        self._anim.start()

    def enterEvent(self, event):  # noqa: N802
        self._glow_to(self.GLOW_MAX)
        super().enterEvent(event)

    def leaveEvent(self, event):  # noqa: N802
        if not self.hasFocus():
            self._glow_to(0)
        super().leaveEvent(event)

    def focusInEvent(self, event):  # noqa: N802
        self._glow_to(self.GLOW_MAX)
        super().focusInEvent(event)

    def focusOutEvent(self, event):  # noqa: N802
        if not self.underMouse():
            self._glow_to(0)
        super().focusOutEvent(event)

    def show_about(self) -> AboutDialog:
        dlg = AboutDialog(self)
        dlg.exec()
        return dlg


def build_footer(parent: QWidget | None = None) -> QWidget:
    """The footer row: room on the left, the signature on the right."""
    row = QWidget(parent)
    row.setObjectName("Footer")
    lay = QHBoxLayout(row)
    lay.setContentsMargins(2, 0, 2, 0)
    lay.setSpacing(8)
    lay.addStretch(1)
    lay.addWidget(SignatureButton(parent=row))
    return row
