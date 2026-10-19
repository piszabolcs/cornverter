"""
CornVerter main window (PySide6).

Turns the mixed files of a folder (spreadsheets, documents, e-mails, images,
archives) into PDF, keeping the folder structure - into a separate output
folder or in place. There is no OCR: scans become image PDFs, a searchable
text layer is left to a dedicated OCR tool.

The window is frameless: `chrome.py` draws a title bar and window buttons
that match the theme instead of the native Windows frame.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QIcon,
    QPainter,
    QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .chrome import FramelessWindow
from .converters import Options
from .converters.base import (
    ConversionResult,
    Status,
    human_size,
    soffice_available,
)
from .engine import RunOutcome, single_file_tasks, write_reports
from .scanner import (
    ScanSummary,
    Task,
    default_backup_dir,
    scan,
    scan_in_place,
    validate_paths,
)
from .scroll_fade import attach_scroll_fade
from .signature import build_footer
from .theme import (
    BG, CORN, DANGER, LOG_BG, OK, QSS, TABLE_BG, TEXT_MUTED, WARN, apply_theme,
)
from .worker import ConvertWorker

APP_TITLE = "CornVerter"
APP_SUBTITLE = ("Anything to PDF - spreadsheets, documents, e-mails, images, "
                "archives")

# Status -> label in the table (the CSV keeps the machine value).
_STATUS_LABEL = {
    Status.SUCCESS: "converted",
    Status.FAILED: "failed",
    Status.SKIPPED: "skipped",
    Status.UNSUPPORTED: "unsupported",
    Status.CANCELLED: "cancelled",
}

_STATUS_COLOR = {
    Status.SUCCESS: OK,
    Status.FAILED: DANGER,
    Status.SKIPPED: WARN,
    Status.UNSUPPORTED: TEXT_MUTED,
    Status.CANCELLED: TEXT_MUTED,
}

# Category -> label in the "Type" column.
_CATEGORY_LABEL = {
    "text": "text",
    "office": "document",
    "msg": "e-mail",
    "image": "image",
    "archive": "archive",
    "accepted": "document",
}

# The category is coarse ("office" covers spreadsheets and documents), so the
# extension names the type first.
_EXT_LABEL = {
    ".xlsx": "spreadsheet", ".xls": "spreadsheet", ".xlsm": "spreadsheet",
    ".xlsb": "spreadsheet", ".ods": "spreadsheet", ".csv": "spreadsheet",
    ".tsv": "spreadsheet",
    ".doc": "document", ".docx": "document", ".docm": "document",
    ".odt": "document", ".rtf": "document",
    ".ppt": "presentation", ".pptx": "presentation", ".pptm": "presentation",
    ".odp": "presentation",
    ".pdf": "PDF",
}


def _type_label(category: str, suffix: str) -> str:
    label = _EXT_LABEL.get(suffix.lower())
    if label:
        return label
    return _CATEGORY_LABEL.get(category, category)


def make_corn_icon(size: int = 64) -> QIcon:
    """The stylised corn badge as an icon (drawn in code, no image file)."""
    return QIcon(make_corn_pixmap(size))


def make_corn_pixmap(size: int = 64) -> QPixmap:
    """The corn badge (used by the title bar and the window icon)."""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    # Yellow rounded square
    p.setBrush(QBrush(QColor(CORN)))
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(2, 2, size - 4, size - 4, size * 0.28, size * 0.28)
    # A grid of dark "kernels"
    p.setBrush(QBrush(QColor(BG)))
    cols, rows = 4, 5
    m = size * 0.22
    gw = (size - 2 * m) / cols
    gh = (size - 2 * m) / rows
    r = min(gw, gh) * 0.30
    for i in range(cols):
        for j in range(rows):
            cx = m + gw * (i + 0.5)
            cy = m + gh * (j + 0.5)
            p.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))
    p.end()
    return pm


PAGE_FILES, PAGE_FOLDER = 0, 1


class FormScroll(QScrollArea):
    """Scroll area that asks for its whole content height when there is room
    (QScrollArea caps its size hint at 24 text lines)."""

    def sizeHint(self):  # noqa: N802
        hint = super().sizeHint()
        if self.widget() is not None:
            hint.setHeight(self.widget().sizeHint().height()
                           + 2 * self.frameWidth())
        return hint


class CardFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")


class MainWindow(FramelessWindow):
    def __init__(self):
        super().__init__(APP_TITLE, APP_SUBTITLE, badge=make_corn_pixmap(30))
        self.setWindowTitle(f"{APP_TITLE} - anything to PDF")
        self.setWindowIcon(make_corn_icon())
        self.resize(1180, 880)

        self.summary: ScanSummary | None = None
        self.worker: ConvertWorker | None = None
        self.results: list[ConversionResult] = []
        self._row_by_source: dict[str, int] = {}
        self._output_by_row: dict[int, Path] = {}
        self._close_requested = False
        self._single_run = False      # quick mode: no report, no scan
        self._last_folder: Path | None = None
        self.setAcceptDrops(True)

        layout = QVBoxLayout(self.body())
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(12)
        layout.addWidget(self._build_switch())
        layout.addWidget(self._build_form())
        layout.addWidget(self._build_results(), stretch=5)
        layout.addWidget(self._build_run_row())
        layout.addWidget(self._build_log(), stretch=2)
        layout.addWidget(build_footer(self))

        self.setStyleSheet(QSS)
        self._min_size_set = False
        self._show_page(PAGE_FILES)

        self._log("CornVerter started. Single files: drop them or choose "
                  "them - each becomes a PDF. Whole folder: pick the folder, "
                  "scan, then convert.")
        if not soffice_available():
            self._log("Note: LibreOffice is not installed. Spreadsheets, Word, "
                      "PowerPoint and RTF files are converted by the built-in "
                      "renderer (the content, without formatting); .doc, "
                      ".ppt, .odt, .ods, .odp and .xlsb need LibreOffice.")

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        if not self._min_size_set:
            # Never smaller than the content needs (measured once the styles
            # are applied): the form scrolls instead of squashing controls.
            self._min_size_set = True
            # The form's height wish changes once the styles are applied;
            # the layout must not keep the earlier, smaller one.
            self._form_scroll.updateGeometry()
            self.body().layout().activate()
            hint = self.minimumSizeHint()
            self.setMinimumSize(max(hint.width(), 760), max(hint.height(), 560))

    # ---------------------------------------------------------------- UI
    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("SectionTitle")
        return lbl

    def _build_switch(self) -> QWidget:
        """Two big choices at the top: a few files, or a whole folder."""
        bar = QFrame()
        bar.setObjectName("SegmentBar")
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self.page_files_btn = QPushButton("Single files")
        self.page_files_btn.setToolTip("Convert one or a few files - each PDF "
                                       "goes next to its file")
        self.page_folder_btn = QPushButton("Whole folder")
        self.page_folder_btn.setToolTip("Convert every file in a folder tree "
                                        "(thousands at once)")
        self.page_group = QButtonGroup(self)
        self.page_group.setExclusive(True)
        for page, btn in ((PAGE_FILES, self.page_files_btn),
                          (PAGE_FOLDER, self.page_folder_btn)):
            btn.setObjectName("Segment")
            btn.setCheckable(True)
            btn.setFixedHeight(38)
            btn.setAutoDefault(True)
            btn.clicked.connect(lambda _=False, p=page: self._show_page(p))
            self.page_group.addButton(btn)
            lay.addWidget(btn, stretch=1)
        return bar

    def _show_page(self, page: int) -> None:
        self.stack.setCurrentIndex(page)
        (self.page_files_btn if page == PAGE_FILES
         else self.page_folder_btn).setChecked(True)
        self._fit_stack(page)

    def _build_form(self) -> QWidget:
        """The page of the chosen workflow - scrollable when the window is
        short."""
        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_files_page())
        self.stack.addWidget(self._build_folder_page())
        # The stack is only as tall as the visible page.
        self.stack.currentChanged.connect(self._fit_stack)

        scroll = FormScroll()
        scroll.setObjectName("FormScroll")
        scroll.setWidget(self.stack)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        scroll.setMinimumHeight(130)
        self.form_fade = attach_scroll_fade(scroll, BG)
        self._form_scroll = scroll
        return scroll

    def _fit_stack(self, index: int) -> None:
        for i in range(self.stack.count()):
            self.stack.widget(i).setSizePolicy(
                QSizePolicy.Preferred,
                QSizePolicy.Preferred if i == index else QSizePolicy.Ignored)
        self.stack.adjustSize()
        self._form_scroll.updateGeometry()

    # -------------------------------------------------------- files page
    def _build_files_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        drop = QFrame()
        drop.setObjectName("DropZone")
        drop.setMinimumHeight(118)
        d = QVBoxLayout(drop)
        d.setContentsMargins(18, 16, 18, 16)
        d.setSpacing(6)
        title = QLabel("Drop files here")
        title.setObjectName("DropTitle")
        title.setAlignment(Qt.AlignCenter)
        hint = QLabel("Excel, Word, PowerPoint, e-mails, images, text, "
                      "archives … each file becomes one PDF. "
                      "Nothing is ever overwritten.")
        hint.setObjectName("Hint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        self.files_btn = QPushButton("Choose &files…")
        self.files_btn.setObjectName("Primary")
        self.files_btn.setToolTip("Choose one or more files to convert now")
        self.files_btn.setAutoDefault(True)
        self.files_btn.clicked.connect(self._pick_files)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(self.files_btn)
        btn_row.addStretch(1)
        d.addWidget(title)
        d.addWidget(hint)
        d.addLayout(btn_row)
        lay.addWidget(drop)

        where = CardFrame()
        w = QVBoxLayout(where)
        w.setContentsMargins(18, 12, 18, 14)
        w.setSpacing(6)
        w.addWidget(self._section_label("WHERE SHOULD THE PDF GO?"))
        self.rb_files_beside = QRadioButton("Next to each file")
        self.rb_files_folder = QRadioButton("Into this folder:")
        self.rb_files_beside.setChecked(True)
        self.files_where = QButtonGroup(self)
        self.files_where.addButton(self.rb_files_beside)
        self.files_where.addButton(self.rb_files_folder)
        self.files_out_edit = QLineEdit()
        self.files_out_edit.setPlaceholderText("Folder for the PDFs")
        self.files_out_edit.setClearButtonEnabled(True)
        self.files_out_btn = QPushButton("Browse…")
        self.files_out_btn.setFixedWidth(118)
        self.files_out_btn.clicked.connect(self._pick_files_output)
        row = QHBoxLayout()
        row.setSpacing(8)
        row.addWidget(self.rb_files_folder)
        row.addWidget(self.files_out_edit, stretch=1)
        row.addWidget(self.files_out_btn)
        w.addWidget(self.rb_files_beside)
        w.addLayout(row)
        self.rb_files_folder.toggled.connect(self._sync_files_where)
        self._sync_files_where(False)
        lay.addWidget(where)
        lay.addStretch(1)
        return page

    def _sync_files_where(self, into_folder: bool) -> None:
        self.files_out_edit.setEnabled(into_folder)
        self.files_out_btn.setEnabled(into_folder)

    def _pick_files_output(self):
        d = QFileDialog.getExistingDirectory(self, "Choose the folder for the PDFs")
        if d:
            self.files_out_edit.setText(d)
            self.rb_files_folder.setChecked(True)

    # ------------------------------------------------------- folder page
    def _build_folder_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self._build_input_card())
        lay.addWidget(self._build_where_card())
        lay.addWidget(self._build_actions())
        self.options_card = self._build_options()
        self.options_card.setVisible(False)
        lay.addWidget(self.options_card)
        lay.addStretch(1)
        return page

    def _path_row(self, placeholder: str, button: str):
        row = QHBoxLayout()
        row.setSpacing(8)
        edit = QLineEdit()
        edit.setPlaceholderText(placeholder)
        edit.setClearButtonEnabled(True)
        edit.returnPressed.connect(self._do_scan)
        btn = QPushButton(button)
        btn.setAutoDefault(True)
        btn.setFixedWidth(118)
        row.addWidget(edit, stretch=1)
        row.addWidget(btn)
        return row, edit, btn

    def _build_input_card(self) -> QWidget:
        card = CardFrame()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 12, 18, 14)
        lay.setSpacing(6)
        lay.addWidget(self._section_label("1   FOLDER TO CONVERT"))
        row, self.in_edit, in_btn = self._path_row(
            "Folder with the mixed files (subfolders included)", "&Browse…")
        in_btn.setToolTip("Choose the input folder")
        in_btn.clicked.connect(self._pick_input)
        lay.addLayout(row)
        return card

    def _build_where_card(self) -> QWidget:
        card = CardFrame()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 12, 18, 14)
        lay.setSpacing(5)
        lay.addWidget(self._section_label("2   WHERE SHOULD THE PDFs GO?"))

        self.rb_target = QRadioButton(
            "Into a new folder (originals untouched)")
        self.rb_inplace = QRadioButton(
            "Next to the originals (originals move to a backup folder)")
        self.rb_target.setChecked(True)
        self.rb_target.setToolTip(
            "The input folder stays as it is; the PDFs go into the output\n"
            "folder, mirroring the folder structure.")
        self.rb_inplace.setToolTip(
            "The PDF is written next to the source as '<name>_from_<ext>.pdf'\n"
            "and the original moves to the backup folder, keeping its\n"
            "relative path. Existing PDFs are never touched.")
        self.mode_group = QButtonGroup(self)
        self.mode_group.addButton(self.rb_target)
        self.mode_group.addButton(self.rb_inplace)
        self.rb_inplace.toggled.connect(self._on_mode_changed)
        radios = QHBoxLayout()
        radios.setSpacing(28)
        radios.addWidget(self.rb_target)
        radios.addWidget(self.rb_inplace)
        radios.addStretch(1)
        lay.addLayout(radios)

        self.out_label = QLabel("Output folder")
        self.out_label.setObjectName("Hint")
        row, self.out_edit, out_btn = self._path_row(
            "The PDFs go here (folder structure kept)", "Br&owse…")
        out_btn.setToolTip("Choose the output (or backup) folder")
        out_btn.clicked.connect(self._pick_output)
        lay.addSpacing(2)
        lay.addWidget(self.out_label)
        lay.addLayout(row)
        return card

    def _on_mode_changed(self, in_place: bool):
        """The second folder field means something else in each mode."""
        self.out_label.setText(
            "Backup folder for the originals" if in_place else "Output folder")
        self.out_edit.setPlaceholderText(
            "The moved originals go here" if in_place
            else "The PDFs go here (folder structure kept)")
        self.cb_overwrite.setEnabled(not in_place)

        # Never carry a backup path over as an output folder (or back).
        in_dir = self.in_edit.text().strip()
        self.out_edit.setText(
            str(self._default_second(Path(in_dir))) if in_dir else "")
        self._reset_scan()

    def _default_second(self, in_dir: Path) -> Path:
        """Default output (or backup) folder, next to the input folder."""
        if self.in_place:
            return default_backup_dir(in_dir)
        return in_dir.parent / f"{in_dir.name}_PDF"

    def _reset_scan(self):
        """After a mode or folder change the old task list is invalid."""
        self.summary = None
        self.table.setRowCount(0)
        self._row_by_source.clear()
        self.convert_btn.setEnabled(False)
        self.stat_lbl.setText("Not scanned yet.")
        self.progress.setValue(0)
        self.progress.setFormat("Ready")

    @property
    def in_place(self) -> bool:
        return self.rb_inplace.isChecked()

    def _build_options(self) -> QWidget:
        card = CardFrame()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(18, 10, 18, 10)
        lay.setSpacing(6)
        lay.addWidget(self._section_label("WHAT TO CONVERT"))

        grid = QGridLayout()
        grid.setHorizontalSpacing(30)
        grid.setVerticalSpacing(2)

        defaults = Options()
        self.cb_excel = QCheckBox("Spreadsheets (all sheets)")
        self.cb_msg = QCheckBox("E-mails with attachments")
        self.cb_img = QCheckBox("Images and scans (no OCR)")
        self.cb_arc = QCheckBox("Archives (unpacked)")
        self.cb_accepted = QCheckBox("PDF, Word and PowerPoint files too")
        self.cb_overwrite = QCheckBox("Overwrite existing PDFs")
        self.cb_excel.setChecked(defaults.convert_excel)
        self.cb_msg.setChecked(defaults.convert_msg)
        self.cb_img.setChecked(defaults.convert_images)
        self.cb_arc.setChecked(defaults.expand_archives)
        self.cb_accepted.setChecked(defaults.convert_accepted)
        self.cb_overwrite.setChecked(defaults.overwrite)

        self.cb_img.setToolTip(
            "The image goes into the PDF as it is, without a searchable\n"
            "text layer - run a dedicated OCR tool on the PDFs for that.")
        self.cb_accepted.setToolTip(
            "On: PDFs are copied to the output folder and .doc/.docx/.ppt/.pptx\n"
            "files are converted (in place, existing PDFs are never touched).\n"
            "Off: these files are left as they are.")
        self.cb_overwrite.setToolTip(
            "Off: a PDF that already exists in the output folder is left\n"
            "untouched and the file is skipped. On: it is replaced.")
        self.cb_arc.setToolTip(
            "Archives are unpacked with safety limits (size, file count,\n"
            "nesting depth); their content is merged into one PDF.")

        grid.addWidget(self.cb_excel, 0, 0)
        grid.addWidget(self.cb_msg, 0, 1)
        grid.addWidget(self.cb_img, 0, 2)
        grid.addWidget(self.cb_arc, 1, 0)
        grid.addWidget(self.cb_accepted, 1, 1)
        grid.addWidget(self.cb_overwrite, 1, 2)
        for col in range(3):
            grid.setColumnStretch(col, 1)
        lay.addLayout(grid)
        return card

    def _build_actions(self) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setSpacing(10)

        self.scan_btn = QPushButton("&Scan folder")
        self.scan_btn.setToolTip("List what will be converted (Enter in a "
                                 "folder field does the same)")
        self.scan_btn.clicked.connect(self._do_scan)

        self.convert_btn = QPushButton("&Convert")
        self.convert_btn.setObjectName("Primary")
        self.convert_btn.setToolTip("Convert the listed files")
        self.convert_btn.setEnabled(False)
        self.convert_btn.clicked.connect(self._do_convert)

        self.options_btn = QPushButton("Options  ▸")
        self.options_btn.setObjectName("Toggle")
        self.options_btn.setCheckable(True)
        self.options_btn.setToolTip("Which file types to convert, overwrite")
        self.options_btn.setFixedHeight(42)
        self.options_btn.toggled.connect(self._toggle_options)
        lay.addWidget(self.options_btn)
        hint = QLabel("Scan first to see what will be converted.")
        hint.setObjectName("Hint")
        lay.addWidget(hint, stretch=1)
        for btn in (self.scan_btn, self.convert_btn):
            btn.setFixedHeight(42)
            btn.setMinimumWidth(140)
            btn.setAutoDefault(True)  # Enter on a focused button presses it
            lay.addWidget(btn)
        return wrap

    def _toggle_options(self, shown: bool) -> None:
        self.options_card.setVisible(shown)
        self.options_btn.setText("Options  ▾" if shown else "Options  ▸")
        self._fit_stack(self.stack.currentIndex())

    # ------------------------------------------------------ shared parts
    def _build_results(self) -> QWidget:
        """Results list in a rounded card. The table sits inset by a few
        pixels, so its square header never reaches the rounded corners."""
        card = QFrame()
        card.setObjectName("TableCard")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)

        head = QHBoxLayout()
        head.setContentsMargins(8, 2, 8, 0)
        head.addWidget(self._section_label("FILES"))
        self.stat_lbl = QLabel("Not scanned yet.")
        self.stat_lbl.setObjectName("StatLine")
        self.stat_lbl.setWordWrap(True)
        self.stat_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(self.stat_lbl, stretch=1)
        lay.addLayout(head)
        lay.addWidget(self._build_table(), stretch=1)
        card.setMinimumHeight(150)
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        return card

    def _build_run_row(self) -> QWidget:
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self._build_progress(), stretch=1)

        self.cancel_btn = QPushButton("Ca&ncel")
        self.cancel_btn.setObjectName("Danger")
        self.cancel_btn.setToolTip("Stop after the current file")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._do_cancel)

        self.open_btn = QPushButton("&Open folder")
        self.open_btn.setToolTip("Open the folder of the last results "
                                 "(double-click a row to open its PDF)")
        self.open_btn.setEnabled(False)
        self.open_btn.clicked.connect(self._open_folder)
        for btn in (self.cancel_btn, self.open_btn):
            btn.setFixedHeight(36)
            btn.setAutoDefault(True)
            lay.addWidget(btn)
        return wrap

    def _build_table(self) -> QWidget:
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["FILE", "TYPE", "SIZE", "STATUS", "ENGINE / MESSAGE"])
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.Stretch)
        hdr.setHighlightSections(False)
        # The header centres by default while the cells align left - both
        # align left to stay in line (the size column aligns right).
        hdr.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(28)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(90)
        self.table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.table.cellDoubleClicked.connect(self._open_row)
        self.table_fade = attach_scroll_fade(self.table, TABLE_BG)
        return self.table

    def _build_progress(self) -> QWidget:
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setFormat("Ready")
        return self.progress

    def _build_log(self) -> QWidget:
        self.log_view = QPlainTextEdit()
        self.log_view.setObjectName("Log")
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(5000)
        # The log must not eat the room of the file list.
        self.log_view.setMinimumHeight(56)
        self.log_view.setMaximumHeight(180)
        self.log_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.log_fade = attach_scroll_fade(self.log_view, LOG_BG)
        return self.log_view

    # ------------------------------------------------------------- logic
    def _log(self, msg: str):
        self.log_view.appendPlainText(
            f"{datetime.now().strftime('%H:%M:%S')}  {msg}")

    def _pick_input(self):
        d = QFileDialog.getExistingDirectory(self, "Choose the input folder")
        if not d:
            return
        self.in_edit.setText(d)
        self._reset_scan()
        # Offer the second folder for the mode, next to the chosen one.
        if self.in_place or not self.out_edit.text().strip():
            self.out_edit.setText(str(self._default_second(Path(d))))

    def _pick_output(self):
        title = ("Choose the backup folder for the originals" if self.in_place
                 else "Choose the output folder")
        d = QFileDialog.getExistingDirectory(self, title)
        if d:
            self.out_edit.setText(d)
            self._reset_scan()

    def _current_options(self) -> Options:
        return Options(
            convert_msg=self.cb_msg.isChecked(),
            convert_excel=self.cb_excel.isChecked(),
            convert_images=self.cb_img.isChecked(),
            expand_archives=self.cb_arc.isChecked(),
            convert_accepted=self.cb_accepted.isChecked(),
            overwrite=self.cb_overwrite.isChecked() and not self.in_place,
        )

    def _do_scan(self):
        if self.worker is not None and self.worker.isRunning():
            return
        in_text = self.in_edit.text().strip()
        out_text = self.out_edit.text().strip()
        error = validate_paths(in_text, out_text, self.in_place)
        if error:
            QMessageBox.warning(self, "Check the folders", error)
            return
        in_dir, out_dir = Path(in_text), Path(out_text)

        self._log(f"Scanning: {in_dir}")
        self.scan_btn.setEnabled(False)
        QApplication.processEvents()

        opts = self._current_options()
        try:
            if self.in_place:
                self.summary = scan_in_place(in_dir, out_dir, opts)
            else:
                self.summary = scan(in_dir, out_dir, opts)
        except Exception as exc:  # noqa: BLE001
            self.scan_btn.setEnabled(True)
            QMessageBox.critical(self, "Scan failed", str(exc))
            return

        self._fill_table_from_scan()
        self._show_scan_summary(self.summary)
        self.scan_btn.setEnabled(True)
        self.convert_btn.setEnabled(len(self.summary.tasks) > 0)
        self.progress.setValue(0)
        self.progress.setFormat("Ready")

    def _show_scan_summary(self, s: ScanSummary) -> None:
        parts = [f"To convert: {len(s.tasks)} ({s.human_total()})",
                 f"skipped: {s.skipped_accepted + s.skipped_by_option}"]
        if s.skipped_already_done:
            parts.append(f"already converted: {s.skipped_already_done}")
        if s.skipped_existing:
            parts.append(f"PDF exists: {s.skipped_existing}")
        parts += [f"junk: {s.skipped_junk}", f"unknown: {s.unknown}"]
        self.stat_lbl.setText("   ·   ".join(parts))
        self._log(f"Scan finished. Files: {s.total_files}, to convert: "
                  f"{len(s.tasks)}. Categories: {s.by_category}")
        if s.skipped_existing:
            self._log(f"{s.skipped_existing} file(s) skipped: the target PDF "
                      f"already exists (tick 'Overwrite existing PDFs' to "
                      f"replace them).")
        if s.skipped_links:
            self._log(f"{len(s.skipped_links)} link(s)/junction(s) not "
                      f"followed, e.g. {s.skipped_links[0]}")
        if not s.tasks:
            self._log("Nothing to convert with these settings.")

    def _fill_table_from_scan(self):
        self._fill_table(self.summary.tasks)

    def _fill_table(self, tasks: list[Task]):
        self.table.setRowCount(0)
        self._row_by_source.clear()
        self._output_by_row.clear()
        for t in tasks:
            row = self.table.rowCount()
            self.table.insertRow(row)
            name_item = QTableWidgetItem(t.source.name)
            name_item.setToolTip(str(t.source))
            self.table.setItem(row, 0, name_item)
            self.table.setItem(row, 1, QTableWidgetItem(
                _type_label(t.category, t.source.suffix)))
            size_item = QTableWidgetItem(human_size(t.size))
            size_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 2, size_item)
            state = QTableWidgetItem("waiting")
            state.setForeground(QColor(TEXT_MUTED))
            self.table.setItem(row, 3, state)
            self.table.setItem(row, 4, QTableWidgetItem(""))
            self._row_by_source[str(t.source)] = row

    def _do_convert(self):
        if not self.summary or not self.summary.tasks:
            return
        if self.in_place and not self._confirm_in_place():
            return
        self._start_worker(self.summary.tasks, self._current_options(),
                           single=False)

    def _start_worker(self, tasks: list[Task], options: Options,
                      single: bool) -> None:
        self._single_run = single
        self.results = []
        for btn in (self.convert_btn, self.scan_btn, self.files_btn,
                    self.open_btn):
            btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.progress.setValue(0)
        self.progress.setMaximum(len(tasks))

        self.worker = ConvertWorker(tasks, options)
        self.worker.progress.connect(self._on_progress)
        self.worker.file_done.connect(self._on_file_done)
        self.worker.log.connect(self._log)
        self.worker.finished_all.connect(self._on_finished)
        self.worker.start()

    # ------------------------------------------------- quick mode (files)
    def _busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def _pick_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "Choose files to convert")
        if files:
            self._convert_files([Path(f) for f in files])

    def _quick_output_dir(self) -> Path | None:
        """Single files go next to each file, or into the chosen folder."""
        text = self.files_out_edit.text().strip()
        return Path(text) if self.rb_files_folder.isChecked() and text else None

    def _convert_files(self, files: list[Path]) -> None:
        """Convert single files at once - no scan, nothing overwritten."""
        if self._busy():
            self._log("A conversion is running - wait for it to finish.")
            return
        self._show_page(PAGE_FILES)
        if self.rb_files_folder.isChecked() and not self.files_out_edit.text().strip():
            QMessageBox.warning(self, "Choose a folder",
                                "Choose the folder for the PDFs, or pick "
                                "'Next to each file'.")
            return
        out_dir = self._quick_output_dir()
        tasks, already_pdf = single_file_tasks(files, out_dir)
        for pdf in already_pdf:
            self._log(f"{pdf.name} is already a PDF - left as it is.")
        if not tasks:
            return
        self.summary = None
        self._fill_table(tasks)
        self.stat_lbl.setText(f"Converting {len(tasks)} file(s)")
        self._log(f"Converting {len(tasks)} file(s) -> "
                  f"{out_dir if out_dir else 'next to each file'}")
        self._start_worker(tasks, Options(), single=True)

    def _handle_paths(self, paths: list[Path]) -> None:
        """Dropped items: files convert at once, one folder is scanned."""
        folders = [p for p in paths if p.is_dir()]
        files = [p for p in paths if p.is_file()]
        if files:
            self._convert_files(files)
        elif len(folders) == 1 and not self._busy():
            self._show_page(PAGE_FOLDER)
            self.in_edit.setText(str(folders[0]))
            self.out_edit.setText(str(self._default_second(folders[0])))
            self._reset_scan()
            self._do_scan()
        elif folders:
            self._log("Drop one folder at a time.")

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasUrls() and any(
                u.isLocalFile() for u in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls()
                 if u.isLocalFile()]
        event.acceptProposedAction()
        self._handle_paths(paths)

    def _open_folder(self):
        if self._last_folder is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._last_folder)))

    def _open_row(self, row: int, _column: int):
        pdf = self._output_by_row.get(row)
        if pdf is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(pdf)))

    def _confirm_in_place(self) -> bool:
        """Confirm before converting in place: the input folder will change."""
        n = len(self.summary.tasks)
        answer = QMessageBox.question(
            self, "Convert in place?",
            f"This changes the INPUT folder:\n\n"
            f"• a PDF is made next to each of the {n} files "
            f"(..._from_<ext>.pdf),\n"
            f"• then the {n} originals move to:\n"
            f"    {self.out_edit.text().strip()}\n\n"
            f"Nothing is deleted: the originals keep their relative folders "
            f"and can be put back at any time. Existing PDFs are not "
            f"touched.\n\nStart?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        return answer == QMessageBox.Yes

    def _do_cancel(self):
        if self.worker:
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)

    def _on_progress(self, done: int, total: int):
        self.progress.setValue(done)
        self.progress.setFormat(
            f"{done} / {total}  ({done * 100 // max(total, 1)}%)")

    def _set_state(self, row: int, status: Status) -> None:
        state = QTableWidgetItem(_STATUS_LABEL.get(status, status.value))
        state.setForeground(QColor(_STATUS_COLOR.get(status, TEXT_MUTED)))
        self.table.setItem(row, 3, state)

    def _on_file_done(self, result: ConversionResult):
        self.results.append(result)
        row = self._row_by_source.get(str(result.source))
        if row is None:
            return
        self._set_state(row, result.status)
        if result.output is not None:
            self._output_by_row[row] = result.output
        info = result.engine + (f" - {result.message}" if result.message else "")
        info_item = QTableWidgetItem(info)
        info_item.setToolTip(info)
        self.table.setItem(row, 4, info_item)
        self.table.scrollToItem(info_item)

    def _on_finished(self, outcome: RunOutcome):
        results = outcome.results
        self.cancel_btn.setEnabled(False)
        self.scan_btn.setEnabled(True)
        self.files_btn.setEnabled(True)
        # The task list is used up (PDFs exist, originals may have moved):
        # another run needs a fresh scan.
        self.convert_btn.setEnabled(False)
        self.summary = None
        outputs = [r.output for r in results if r.output is not None]
        for task in outcome.cancelled:
            row = self._row_by_source.get(str(task.source))
            if row is not None:
                self._set_state(row, Status.CANCELLED)
        ok = sum(1 for r in results if r.status is Status.SUCCESS)
        failed = sum(1 for r in results if r.status is Status.FAILED)
        skipped = sum(1 for r in results if r.status is Status.SKIPPED)
        total = len(results) + len(outcome.cancelled)
        head = (f"Cancelled - {len(results)}/{total} done" if outcome.cancelled
                else "Done")
        summary = f"{head} - {ok} converted, {failed} failed, {skipped} skipped"
        self.progress.setFormat(summary)

        report_note = ""
        if self._single_run:
            self.stat_lbl.setText("Done - double-click a row to open its PDF.")
            self._last_folder = outputs[0].parent if outputs else None
            for pdf in outputs:
                self._log(f"PDF: {pdf}")
        else:
            self.stat_lbl.setText("Run finished - scan again for a new run.")
            out_dir = Path(self.out_edit.text().strip())
            # In place the PDFs sit in the input folder; the report in the
            # backup folder.
            self._last_folder = (Path(self.in_edit.text().strip())
                                 if self.in_place else out_dir)
            try:
                md_path = write_reports(outcome, out_dir,
                                        Path(self.in_edit.text().strip()),
                                        out_dir)
                self._log(f"Report written: {md_path} (+ .csv)")
                report_note = f"\n\nReport: {md_path.name} (+ .csv) in {out_dir}"
            except Exception as exc:  # noqa: BLE001
                self._log(f"Could not write the report: {exc}")
                report_note = f"\n\nThe report could not be written: {exc}"
        self.open_btn.setEnabled(self._last_folder is not None)

        if self._close_requested:
            # The user asked to quit during the run: finish quitting now.
            self.worker.wait()
            self.close()
            return
        if self._single_run:
            return  # the table and the log show the result
        QMessageBox.information(
            self, "Conversion cancelled" if outcome.cancelled
            else "Conversion finished", summary + report_note)

    def closeEvent(self, event):  # noqa: N802
        """While a run is going: ask, cancel, and close once it has stopped.

        The window never closes under a running thread (that would abort the
        process mid-write); the cancel kills a running LibreOffice call, so
        the wait is short.
        """
        if self.worker is not None and self.worker.isRunning():
            if not self._close_requested:
                answer = QMessageBox.question(
                    self, "Conversion running",
                    "A conversion is still running. Stop it and quit?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if answer != QMessageBox.Yes:
                    event.ignore()
                    return
                self._close_requested = True
                self.worker.cancel()
                self.body().setEnabled(False)
                self.progress.setFormat("Stopping...")
            event.ignore()  # _on_finished closes the window
            return
        super().closeEvent(event)


def run():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setApplicationDisplayName(APP_TITLE)
    apply_theme(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())
