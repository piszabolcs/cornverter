"""
Regenerate the README screenshots - offscreen, from neutral demo data.

    .venv\\Scripts\\python.exe tools\\make_screenshots.py

No window appears: Qt runs on the "offscreen" platform. A small demo tree is
built in a temporary folder, scanned and converted with the real app, and
every visible path is replaced by a neutral one (D:\\Demo\\...) before a
picture is taken. The PNGs go to docs/screenshots/.
"""

from __future__ import annotations

import datetime as dt
import email.message
import json
import os
import shutil
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "screenshots"
NEUTRAL = "D:\\Demo\\Projects"

_work = Path(tempfile.mkdtemp(prefix="cv_shots_"))
_cfg = _work / "screen.json"
_cfg.write_text(json.dumps({"screens": [{
    "name": "S1", "x": 0, "y": 0, "width": 1920, "height": 1080,
    "logicalDpi": 96, "logicalBaseDpi": 96, "dpr": 1}]}))
os.chdir(_work)
os.environ["QT_QPA_PLATFORM"] = f"offscreen:configfile={_cfg.name}"
os.environ.setdefault("QT_QPA_FONTDIR", "C:/Windows/Fonts")
os.environ.setdefault("CORNVERTER_LO_PROFILE", str(_work / "lo"))
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

DOCX_XML = (
    '<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://'
    'schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Quote '
    '2026-031</w:t></w:r></w:p><w:p><w:r><w:t>Spare parts for line 2, '
    'delivery in week 44.</w:t></w:r></w:p></w:body></w:document>')

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.'
    'openxmlformats.org/package/2006/content-types"><Default Extension="rels" '
    'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/><Override '
    'PartName="/word/document.xml" ContentType="application/vnd.'
    'openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '</Types>')
RELS = (
    '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://'
    'schemas.openxmlformats.org/package/2006/relationships"><Relationship '
    'Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
    'relationships/officeDocument" Target="word/document.xml"/>'
    '</Relationships>')


def build_demo(root: Path) -> None:
    import openpyxl
    from PIL import Image
    from reportlab.pdfgen import canvas

    (root / "Plant-A").mkdir(parents=True)
    (root / "Quotes").mkdir()
    (root / "Plant-A" / "inspection-notes.txt").write_text(
        "Inspection 2026-10-02\nAll guards in place. Next check: Q1.\n",
        encoding="utf-8")
    (root / "Plant-A" / "measurements.csv").write_text(
        "Point;Value;Unit\nA1;12.5;mm\nA2;12.7;mm\n", encoding="utf-8")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Parts"
    ws.append(["Part", "Delivered", "Qty"])
    ws.append(["Bearing 6204", dt.date(2026, 9, 14), 12])
    ws.append(["V-belt SPA 1250", dt.date(2026, 9, 21), 4])
    wb.save(root / "Plant-A" / "parts-list.xlsx")
    frames = [Image.new("RGB", (600, 800), c) for c in ("white", "#dddddd")]
    frames[0].save(root / "Plant-A" / "drawing-scan.tif", save_all=True,
                   append_images=frames[1:])
    with zipfile.ZipFile(root / "Quotes" / "quote-2026-031.docx", "w") as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("word/document.xml", DOCX_XML)
    mail = email.message.EmailMessage()
    mail["From"] = "supplier@example.com"
    mail["To"] = "purchasing@example.com"
    mail["Subject"] = "Re: quote 2026-031"
    mail.set_content("Please find the price list attached.")
    mail.add_attachment(b"Item;Price\nBearing;4.20\n", maintype="text",
                        subtype="csv", filename="prices.csv")
    (root / "Quotes" / "supplier-mail.eml").write_bytes(mail.as_bytes())
    with zipfile.ZipFile(root / "archive-2025.zip", "w") as z:
        z.writestr("2025/summary.txt", "Year summary 2025\n")
        z.writestr("2025/contacts.csv", "Name;Phone\nService;555-0100\n")
    Image.new("RGBA", (320, 200), (255, 201, 60, 255)).save(root / "logo.png")
    pdf = canvas.Canvas(str(root / "ready.pdf"))
    pdf.drawString(72, 720, "Already a PDF")
    pdf.save()
    (root / "Thumbs.db").write_bytes(b"x")


def main() -> None:
    from cornverter.app import MainWindow
    from cornverter.theme import apply_theme

    app = QApplication([])
    apply_theme(app)
    QMessageBox.information = lambda *a, **k: None
    OUT.mkdir(parents=True, exist_ok=True)

    demo = _work / "Projects"
    build_demo(demo)
    real = str(demo)

    def pump(seconds: float = 0.2) -> None:
        end = time.time() + seconds
        while time.time() < end:
            app.processEvents()
            time.sleep(0.01)

    def neutral(win) -> None:
        for edit in (win.in_edit, win.out_edit):
            edit.setText(edit.text().replace(real, NEUTRAL))
        win.log_view.setPlainText(
            win.log_view.toPlainText().replace(real, NEUTRAL))

    def shot(win, name: str) -> None:
        neutral(win)
        pump()
        win.grab().save(str(OUT / name))
        print("saved", OUT / name)

    win = MainWindow()
    win.resize(1180, 880)
    win.show()
    pump(0.4)
    from cornverter.app import PAGE_FOLDER
    win._show_page(PAGE_FOLDER)
    win.in_edit.setText(real)
    win.out_edit.setText(real + "_PDF")
    win._do_scan()
    shot(win, "01_scanned.png")

    win.in_edit.setText(real)
    win.out_edit.setText(real + "_PDF")
    win._do_convert()
    while win.worker.isRunning():
        pump(0.1)
    pump(0.3)
    shot(win, "02_converted.png")

    from cornverter.signature import AboutDialog

    about = AboutDialog(win)
    about.show()
    pump(0.3)
    about.grab().save(str(OUT / "03_about.png"))
    print("saved", OUT / "03_about.png")
    about.close()

    win._convert_files([demo / "Plant-A" / "inspection-notes.txt",
                        demo / "logo.png"])
    while win.worker.isRunning():
        pump(0.1)
    pump(0.3)
    shot(win, "04_quick_mode.png")
    win.close()


if __name__ == "__main__":
    try:
        main()
    finally:
        os.chdir(ROOT)
        shutil.rmtree(_work, ignore_errors=True)
