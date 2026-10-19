"""
GUI and end-to-end tests.

The window runs on the offscreen Qt platform, so nothing appears on the
screen. What matters here:

* the frameless window with its own title bar works,
* the signature and the about panel are in place,
* Scan -> Convert really produces the PDFs and the report, keeping the
  folder structure, and the window stays consistent afterwards.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

# The Qt platform must be set before the first QApplication.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from conftest import (  # noqa: E402
    assert_valid_pdf,
    make_csv,
    make_png,
    make_txt,
    make_xlsx,
)

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    from cornverter.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    yield app


@pytest.fixture
def window(qapp):
    from cornverter.app import MainWindow

    win = MainWindow()
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


def _pump_until(qapp, predicate, timeout_s: float = 120):
    end = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()


def _wait_for_worker(window, qapp):
    assert window.worker is not None
    _pump_until(qapp, lambda: not window.worker.isRunning())
    assert not window.worker.isRunning(), "the conversion did not finish"


# ------------------------------------------------------------ window frame
def test_the_window_is_frameless(window):
    assert window.windowFlags() & Qt.FramelessWindowHint
    assert window.testAttribute(Qt.WA_TranslucentBackground)


def test_own_title_bar_with_three_window_buttons(window):
    bar = window.title_bar
    assert (bar.btn_min.kind, bar.btn_max.kind, bar.btn_close.kind) == \
        ("min", "max", "close")
    assert bar.height() == bar.HEIGHT


def test_maximize_toggle_updates_the_frame(window, qapp):
    window.show()
    qapp.processEvents()

    window.toggle_maximized()
    qapp.processEvents()
    assert window.isMaximized()
    assert window._frame.property("cvMaximized") is True
    assert window._shell_layout.contentsMargins().left() == 0
    assert window.title_bar.btn_max.kind == "restore"

    window.toggle_maximized()
    qapp.processEvents()
    assert not window.isMaximized()
    assert window._shell_layout.contentsMargins().left() == \
        window.SHADOW_MARGIN
    assert window.title_bar.btn_max.kind == "max"


def test_resizing_starts_at_the_edges_only(window):
    from PySide6.QtCore import QPoint

    window.resize(1000, 700)
    assert window._edges_at(QPoint(2, 2)) == (Qt.LeftEdge | Qt.TopEdge)
    assert window._edges_at(QPoint(500, 698)) == Qt.BottomEdge
    assert window._edges_at(QPoint(998, 350)) == Qt.RightEdge
    assert not window._edges_at(QPoint(500, 350))


def test_resizing_stops_at_the_content_minimum(window, qapp):
    from PySide6.QtCore import QPoint

    window.show()
    qapp.processEvents()
    hint = window.minimumSizeHint()
    window.setGeometry(100, 100, 1000, 700)
    window._resize_edges = Qt.RightEdge | Qt.BottomEdge
    window._resize_start_geo = window.geometry()
    window._resize_start_pos = QPoint(1100, 800)
    window._apply_resize(QPoint(-5000, -5000))
    assert window.width() >= hint.width()
    assert window.height() >= hint.height()


# --------------------------------------------------------------- signature
def test_signature_sits_in_the_footer(window):
    from cornverter.signature import AUTHOR_LABEL, SignatureButton

    import cornverter

    buttons = window.findChildren(SignatureButton)
    assert len(buttons) == 1
    assert buttons[0].text() == AUTHOR_LABEL
    assert AUTHOR_LABEL == f"psz // v{cornverter.__version__}"


def test_the_version_has_a_single_source():
    import cornverter

    package = Path(cornverter.__file__).parent
    hits = [p.name for p in package.rglob("*.py")
            if cornverter.__version__ in p.read_text(encoding="utf-8")]
    assert hits == ["__init__.py"]


def test_signature_glow_uses_the_theme_accent(window):
    from cornverter.signature import SignatureButton
    from cornverter.theme import ACCENT

    btn = window.findChildren(SignatureButton)[0]
    effect = btn.graphicsEffect()
    assert effect.color().name().lower() == ACCENT.lower()
    assert effect.blurRadius() == 0           # no glow until hover / focus
    btn._glow_to(btn.GLOW_MAX)
    assert btn._anim.endValue() == btn.GLOW_MAX


def test_about_panel_shows_its_content(qapp, window):
    from PySide6.QtWidgets import QLabel

    from cornverter.signature import ABOUT_SECTIONS, AboutDialog

    dlg = AboutDialog(window)
    joined = "\n".join(lbl.text() for lbl in dlg.findChildren(QLabel))
    for heading, items in ABOUT_SECTIONS:
        assert heading in joined
        for item in items:
            assert item[:40] in joined
    assert "PySide6" in joined and "reportlab" in joined
    dlg.deleteLater()


def test_about_panel_closes_on_escape(qapp, window):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    from cornverter.signature import AboutDialog

    dlg = AboutDialog(window)
    dlg.show()
    qapp.processEvents()
    dlg.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key_Escape,
                                Qt.NoModifier))
    qapp.processEvents()
    assert not dlg.isVisible()
    dlg.deleteLater()


# ---------------------------------------------------------------- keyboard
def test_keyboard_focus_is_visible_and_enter_presses(window, qapp,
                                                     monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a[2]))
    window.show()
    window.activateWindow()
    qapp.processEvents()

    for widget in (window.scan_btn, window.cb_excel, window.rb_target):
        window.table.setFocus()
        qapp.processEvents()
        plain = widget.grab().toImage()
        widget.setFocus(Qt.TabFocusReason)
        qapp.processEvents()
        assert widget.grab().toImage() != plain, widget.text()

    from PySide6.QtTest import QTest

    window.scan_btn.setFocus(Qt.TabFocusReason)
    QTest.keyClick(window.scan_btn, Qt.Key_Return)
    assert warnings, "Enter on the focused Scan button did nothing"


# ------------------------------------------------------------ full workflow
def test_scan_fills_the_table(window, qapp, tmp_path):
    src = tmp_path / "in"
    (src / "deeper").mkdir(parents=True)
    make_txt(src / "first.txt")
    make_csv(src / "deeper" / "data.csv")

    window.in_edit.setText(str(src))
    window.out_edit.setText(str(tmp_path / "out"))
    window._do_scan()
    qapp.processEvents()

    assert window.table.rowCount() == 2
    assert window.convert_btn.isEnabled()
    assert "To convert: 2" in window.stat_lbl.text()


def test_missing_input_folder_does_not_scan(window, qapp, monkeypatch):
    warnings: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warnings.append(a[2]))

    window.in_edit.setText("Z:/no/such/folder")
    window.out_edit.setText("Z:/out")
    window._do_scan()
    qapp.processEvents()

    assert warnings and "does not exist" in warnings[0]
    assert window.table.rowCount() == 0
    assert not window.convert_btn.isEnabled()


def test_full_conversion_writes_pdfs_and_a_report(window, qapp, tmp_path,
                                                  monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    src = tmp_path / "in"
    (src / "sub").mkdir(parents=True)
    make_txt(src / "text.txt")
    make_csv(src / "sub" / "data.csv")
    make_png(src / "picture.png")
    make_xlsx(src / "table.xlsx", sheets=2, with_empty=False)
    (src / "junk.tmp").write_bytes(b"x")
    out = tmp_path / "out"

    window.in_edit.setText(str(src))
    window.out_edit.setText(str(out))
    window._do_scan()
    assert window.table.rowCount() == 4

    window._do_convert()
    _wait_for_worker(window, qapp)

    assert len(window.results) == 4
    assert all(r.ok for r in window.results), \
        [(r.source.name, r.message) for r in window.results if not r.ok]
    for rel in ("text.pdf", "sub/data.pdf", "picture.pdf", "table.pdf"):
        assert_valid_pdf(out / rel)
    assert len(list(out.glob("cornverter_report_*.csv"))) == 1
    report = next(out.glob("cornverter_report_*.md")).read_text("utf-8")
    assert "Converted: 4" in report
    assert "Done - 4 converted" in window.progress.format()
    # The task list is used up: a second click cannot re-run it.
    assert not window.convert_btn.isEnabled()


def test_cancel_stops_the_run(window, qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    src = tmp_path / "in"
    src.mkdir()
    for i in range(25):
        make_txt(src / f"f{i:02d}.txt", "line\n" * 200)

    window.in_edit.setText(str(src))
    window.out_edit.setText(str(tmp_path / "out"))
    window._do_scan()
    window._do_convert()
    window._do_cancel()
    _wait_for_worker(window, qapp)

    assert len(window.results) < 25
    assert not window.cancel_btn.isEnabled()
    assert window.progress.format().startswith("Cancelled")
    assert not window.convert_btn.isEnabled()


def test_closing_during_a_run_waits_for_the_worker(window, qapp, tmp_path,
                                                   monkeypatch):
    import cornverter.engine as engine

    real = engine.convert_file

    def slow(*a, **k):
        time.sleep(0.3)
        return real(*a, **k)

    monkeypatch.setattr(engine, "convert_file", slow)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    src = tmp_path / "in"
    src.mkdir()
    for i in range(6):
        make_txt(src / f"f{i}.txt")
    window.in_edit.setText(str(src))
    window.out_edit.setText(str(tmp_path / "out"))
    window.show()
    window._do_scan()
    window._do_convert()

    window.close()
    assert window.isVisible(), "closed under a running thread"
    _pump_until(qapp, lambda: not window.isVisible(), timeout_s=60)

    assert not window.worker.isRunning()
    assert not window.isVisible()
    assert len(window.results) < 6
    assert not list((tmp_path / "out").glob("*.cvtmp"))


# ------------------------------------------------------------------- modes
def test_separate_output_folder_is_the_default_mode(window):
    assert window.rb_target.isChecked()
    assert not window.in_place
    assert window.out_label.text() == "Output folder"


def test_switching_mode_resets_the_second_folder(window, qapp, tmp_path):
    src = tmp_path / "Docs"
    src.mkdir()
    window.in_edit.setText(str(src))

    window.rb_inplace.setChecked(True)
    qapp.processEvents()
    assert window.out_label.text() == "Backup folder for the originals"
    assert window.out_edit.text() == str(tmp_path / "Docs_originals")
    assert not window.cb_overwrite.isEnabled()

    window.rb_target.setChecked(True)
    qapp.processEvents()
    assert window.out_edit.text() == str(tmp_path / "Docs_PDF")
    assert window.cb_overwrite.isEnabled()


def test_mode_change_invalidates_the_old_scan(window, qapp, tmp_path):
    src = tmp_path / "in"
    src.mkdir()
    make_txt(src / "a.txt")
    window.in_edit.setText(str(src))
    window.out_edit.setText(str(tmp_path / "out"))
    window._do_scan()
    assert window.table.rowCount() == 1

    window.rb_inplace.setChecked(True)
    qapp.processEvents()

    assert window.table.rowCount() == 0
    assert window.summary is None
    assert not window.convert_btn.isEnabled()


def test_in_place_conversion_from_the_gui(window, qapp, tmp_path,
                                          monkeypatch):
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.Yes)
    src = tmp_path / "Docs"
    (src / "Plant" / "Drawings").mkdir(parents=True)
    make_txt(src / "Plant" / "Drawings" / "notes.txt")
    make_csv(src / "list.csv")
    (src / "ready.pdf").write_bytes(b"%PDF-1.4\n")

    window.in_edit.setText(str(src))
    window.rb_inplace.setChecked(True)
    qapp.processEvents()
    backup = Path(window.out_edit.text())
    window._do_scan()
    assert window.table.rowCount() == 2   # the .pdf is left alone

    window._do_convert()
    _wait_for_worker(window, qapp)

    assert all(r.ok for r in window.results), \
        [(r.source.name, r.message) for r in window.results if not r.ok]
    assert (src / "Plant" / "Drawings" / "notes_from_txt.pdf").exists()
    assert (src / "list_from_csv.pdf").exists()
    assert (backup / "Plant" / "Drawings" / "notes.txt").exists()
    assert (backup / "list.csv").exists()
    assert (src / "ready.pdf").exists()
    assert len(list(backup.glob("cornverter_report_*.md"))) == 1


def test_in_place_asks_first_and_no_stops_it(window, qapp, tmp_path,
                                            monkeypatch):
    asked: list[str] = []

    def fake_question(parent, title, text, *a, **k):
        asked.append(text)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", fake_question)
    src = tmp_path / "in"
    src.mkdir()
    make_txt(src / "a.txt")
    window.in_edit.setText(str(src))
    window.rb_inplace.setChecked(True)
    qapp.processEvents()
    window._do_scan()
    window._do_convert()
    qapp.processEvents()

    assert asked and "INPUT" in asked[0]
    assert window.worker is None
    assert (src / "a.txt").exists()
    assert not (src / "a_from_txt.pdf").exists()


def test_there_is_no_ocr_option(window):
    from PySide6.QtWidgets import QCheckBox, QComboBox

    texts = " ".join(cb.text().lower() for cb in window.findChildren(QCheckBox))
    assert "ocr" not in texts.replace("(no ocr)", "")
    assert not window.findChildren(QComboBox)
    assert not hasattr(window._current_options(), "ocr_enabled")


# -------------------------------------------------------------- quick mode
def _drop(window, paths):
    from PySide6.QtCore import QMimeData, QPointF, QUrl
    from PySide6.QtGui import QDropEvent

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(p)) for p in paths])
    event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime, Qt.LeftButton,
                       Qt.NoModifier)
    window.dropEvent(event)


def test_a_dropped_file_converts_next_to_itself(window, qapp, tmp_path,
                                                monkeypatch):
    import cornverter.app as app_module

    opened: list[str] = []
    monkeypatch.setattr(app_module.QDesktopServices, "openUrl",
                        lambda url: opened.append(url.toLocalFile()))
    src = make_txt(tmp_path / "notes.txt")
    (tmp_path / "notes.pdf").write_bytes(b"%PDF-1.4 keep me")

    _drop(window, [src])
    _wait_for_worker(window, qapp)

    pdf = tmp_path / "notes_from_txt.pdf"
    assert_valid_pdf(pdf)
    assert (tmp_path / "notes.pdf").read_bytes() == b"%PDF-1.4 keep me"
    assert window.table.item(0, 3).text() == "converted"
    window._open_row(0, 0)
    window._open_folder()
    assert [Path(p) for p in opened] == [pdf, tmp_path]


def test_a_dropped_folder_fills_the_input_and_scans(window, qapp, tmp_path):
    src = tmp_path / "Docs"
    src.mkdir()
    make_txt(src / "a.txt")

    _drop(window, [src])

    assert window.in_edit.text() == str(src)
    assert window.out_edit.text() == str(tmp_path / "Docs_PDF")
    assert window.table.rowCount() == 1
    assert window.worker is None      # a folder is never converted unasked


def test_single_files_page_is_the_default_and_folder_drop_switches(window, qapp, tmp_path):
    from cornverter.app import PAGE_FILES, PAGE_FOLDER
    assert window.stack.currentIndex() == PAGE_FILES
    assert window.page_files_btn.isChecked()
    src = tmp_path / "Docs"
    src.mkdir()
    (src / "a.txt").write_text("hello", encoding="utf-8")
    window._handle_paths([src])
    qapp.processEvents()
    assert window.stack.currentIndex() == PAGE_FOLDER
    assert window.page_folder_btn.isChecked()


def test_options_are_folded_away_until_asked_for(window, qapp):
    from cornverter.app import PAGE_FOLDER
    window._show_page(PAGE_FOLDER)
    qapp.processEvents()
    assert not window.options_card.isVisibleTo(window)
    window.options_btn.setChecked(True)
    qapp.processEvents()
    assert window.options_card.isVisibleTo(window)


def test_single_files_into_a_folder_needs_the_folder(window, qapp, tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr("cornverter.app.QMessageBox.warning",
                        lambda *a, **k: warnings.append(a))
    f = tmp_path / "a.txt"
    f.write_text("hello", encoding="utf-8")
    window.rb_files_folder.setChecked(True)
    window._convert_files([f])
    assert warnings and window.table.rowCount() == 0


def test_the_log_fades_only_towards_hidden_lines(window, qapp):
    window.show()
    for line in range(200):
        window._log(f"line {line}")
    qapp.processEvents()
    bar = window.log_view.verticalScrollBar()
    assert bar.maximum() > 0  # the log must really scroll, or the checks pass vacuously
    fades = window.log_fade

    bar.setValue(bar.minimum())
    assert (fades.top.isVisible(), fades.bottom.isVisible()) == (False, True)
    bar.setValue(bar.maximum() // 2)
    assert (fades.top.isVisible(), fades.bottom.isVisible()) == (True, True)
    bar.setValue(bar.maximum())
    assert (fades.top.isVisible(), fades.bottom.isVisible()) == (True, False)
