"""
CornVerter look: corn yellow on astro black, with a glass effect.

All the QSS lives here, so the look can be tuned in one place. The
"glass" (glassmorphism) effect is imitated with translucent surfaces, fine
borders and soft gradients, because Qt cannot blur the background.

The window is frameless (see `chrome.py`), so the own title bar and the
window body are styled here too - instead of the native blue Windows frame.
"""

# Base palette
CORN = "#FFC93C"          # corn yellow (primary accent)
CORN_DEEP = "#F5B301"     # deeper yellow (hover, emphasis)
CORN_SOFT = "#FFE08A"     # light yellow (subtle highlight)
BG = "#0B0B10"            # astro-black background
BG2 = "#101017"           # slightly lighter background
SURFACE = "#16161F"       # card surface
GLASS = "rgba(255, 255, 255, 0.045)"
GLASS_BORDER = "rgba(255, 255, 255, 0.10)"
GLASS_SOLID = "#22222C"   # solid counterpart of the glass surface
TEXT = "#F4F4EF"
TEXT_MUTED = "#9A9AA6"
DANGER = "#FF6B6B"
OK = "#5DD39E"
WARN = "#E0C060"

# Table and log surfaces. Solid colours: the widget's own base palette
# would show through an rgba() here.
TABLE_BG = "#0D0D13"
TABLE_ALT = "#12121A"
TABLE_HEADER = "#191922"
LOG_BG = "#08080C"

# The single accent colour of the theme. Everything accent-like (signature
# glow, focus ring, window buttons) uses it, so it changes in one place.
ACCENT = CORN

# Rounding of the window body - the same value as chrome.FRAME_RADIUS.
_FRAME_RADIUS = 16


QSS = f"""
* {{
    font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
    font-size: 13px;
    color: {TEXT};
    outline: none;
}}

/* ------------------------------------------------- frameless window */
QMainWindow, QWidget#Shell {{
    background: transparent;
}}
QFrame#WindowFrame {{
    background-color: {BG};
    border: 1px solid rgba(255, 201, 60, 0.16);
    border-radius: {_FRAME_RADIUS}px;
}}
QFrame#WindowFrame[cvMaximized="true"] {{
    border: none;
    border-radius: 0;
}}
QWidget#Body {{
    background: transparent;
}}

/* Own title bar */
QFrame#TitleBar {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 rgba(255,201,60,0.13), stop:0.55 rgba(255,201,60,0.035),
        stop:1 rgba(255,201,60,0.01));
    border-bottom: 1px solid {GLASS_BORDER};
    border-top-left-radius: {_FRAME_RADIUS - 1}px;
    border-top-right-radius: {_FRAME_RADIUS - 1}px;
}}
QFrame#TitleBar[cvMaximized="true"] {{
    border-top-left-radius: 0;
    border-top-right-radius: 0;
}}
QLabel#Wordmark {{
    font-size: 17px;
    font-weight: 800;
    color: {CORN};
    letter-spacing: 0.4px;
}}
QFrame#TitleSep {{
    background-color: {GLASS_BORDER};
    border: none;
}}
QLabel#TitleSubtitle {{
    color: {TEXT_MUTED};
    font-size: 11.5px;
}}

/* Window buttons */
QPushButton#WinBtn, QPushButton#WinBtnClose {{
    background: transparent;
    border: none;
    border-radius: 7px;
    padding: 0;
}}
QPushButton#WinBtn:hover {{
    background-color: rgba(255, 201, 60, 0.14);
}}
QPushButton#WinBtn:pressed {{
    background-color: rgba(255, 201, 60, 0.22);
}}
QPushButton#WinBtnClose:hover {{
    background-color: {DANGER};
}}
QPushButton#WinBtnClose:pressed {{
    background-color: #D9534F;
}}

/* ------------------------------------------------------------ content */
QLabel#SectionTitle {{
    color: {CORN};
    font-size: 11.5px;
    font-weight: 700;
    letter-spacing: 0.7px;
}}
QLabel#Hint {{
    color: {TEXT_MUTED};
    font-size: 12px;
}}

/* Glass cards */
QFrame#Card {{
    background-color: {GLASS};
    border: 1px solid {GLASS_BORDER};
    border-radius: 14px;
}}

/* Input fields */
QLineEdit {{
    background-color: rgba(0,0,0,0.35);
    border: 1px solid {GLASS_BORDER};
    border-radius: 10px;
    padding: 8px 12px;
    selection-background-color: {CORN_DEEP};
    selection-color: #000;
}}
QLineEdit:focus {{
    border: 1px solid {ACCENT};
}}
QLineEdit::placeholder {{
    color: {TEXT_MUTED};
}}

/* Buttons */
QPushButton {{
    background-color: rgba(255,255,255,0.06);
    border: 1px solid {GLASS_BORDER};
    border-radius: 11px;
    padding: 9px 16px;
    font-weight: 600;
}}
QPushButton:hover {{
    background-color: rgba(255,255,255,0.10);
    border: 1px solid {ACCENT};
}}
QPushButton:pressed {{
    background-color: rgba(255,255,255,0.04);
}}
QPushButton:disabled {{
    color: {TEXT_MUTED};
    border: 1px solid rgba(255,255,255,0.05);
    background-color: rgba(255,255,255,0.02);
}}

/* Keyboard focus is always visible */
QPushButton:focus {{
    border: 1px solid {ACCENT};
    background-color: rgba(255, 201, 60, 0.12);
}}
QCheckBox:focus, QRadioButton:focus {{
    color: {CORN_SOFT};
}}
QCheckBox::indicator:focus, QRadioButton::indicator:focus {{
    border: 1px solid {ACCENT};
}}

/* Primary button (yellow) */
QPushButton#Primary {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {CORN}, stop:1 {CORN_DEEP});
    color: #1A1400;
    border: none;
    font-weight: 800;
    padding: 11px 22px;
}}
QPushButton#Primary:hover {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {CORN_SOFT}, stop:1 {CORN});
}}
QPushButton#Primary:focus {{
    border: 2px solid {TEXT};
}}
QPushButton#Primary:disabled {{
    background: rgba(255,201,60,0.22);
    color: rgba(26,20,0,0.45);
}}

/* Dangerous / cancel button */
QPushButton#Danger:hover {{
    border: 1px solid {DANGER};
    color: {DANGER};
}}

/* Check boxes */
QCheckBox {{
    spacing: 9px;
    padding: 3px 0;
}}
QCheckBox:hover {{
    color: {CORN_SOFT};
}}
QCheckBox::indicator {{
    width: 17px; height: 17px;
    border-radius: 5px;
    border: 1px solid {GLASS_BORDER};
    background-color: rgba(0,0,0,0.35);
}}
QCheckBox::indicator:hover {{
    border: 1px solid {ACCENT};
}}
QCheckBox::indicator:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {CORN}, stop:1 {CORN_DEEP});
    border: 1px solid {CORN_DEEP};
    image: none;
}}

/* Radio buttons (mode) */
QRadioButton {{
    spacing: 9px;
    padding: 3px 0;
}}
QRadioButton:hover {{
    color: {CORN_SOFT};
}}
QRadioButton::indicator {{
    width: 15px; height: 15px;
    border-radius: 9px;
    border: 1px solid {GLASS_BORDER};
    background-color: rgba(0,0,0,0.35);
}}
QRadioButton::indicator:hover {{
    border: 1px solid {ACCENT};
}}
/* Checked: ring + inner dot, so it stays round (a thick QSS border
   would give a rounded square). */
QRadioButton::indicator:checked {{
    border: 1px solid {CORN_DEEP};
    background-color: qradialgradient(cx:0.5, cy:0.5, radius:0.55,
        fx:0.5, fy:0.5,
        stop:0 {CORN}, stop:0.5 {CORN},
        stop:0.56 rgba(11,11,16,255), stop:1 rgba(11,11,16,255));
}}
QRadioButton:disabled {{
    color: {TEXT_MUTED};
}}

/* Segmented switch: single files | whole folder */
QFrame#SegmentBar {{
    background-color: rgba(0,0,0,0.35);
    border: 1px solid {GLASS_BORDER};
    border-radius: 14px;
}}
QPushButton#Segment {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 11px;
    color: {TEXT_MUTED};
    font-size: 14px;
    font-weight: 700;
}}
QPushButton#Segment:hover {{
    color: {CORN_SOFT};
    background-color: rgba(255,255,255,0.05);
}}
QPushButton#Segment:checked {{
    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
        stop:0 {CORN}, stop:1 {CORN_DEEP});
    color: #1A1400;
}}
QPushButton#Segment:focus {{
    border: 1px solid {ACCENT};
}}

/* Drop zone of the single-files page */
QFrame#DropZone {{
    background-color: rgba(255, 201, 60, 0.035);
    border: 2px dashed rgba(255, 201, 60, 0.35);
    border-radius: 14px;
}}
QLabel#DropTitle {{
    color: {CORN};
    font-size: 18px;
    font-weight: 800;
}}

/* Results card: the table sits inset inside it, so the square table and
   header never reach the rounded corners. */
QFrame#TableCard {{
    background-color: {TABLE_BG};
    border: 1px solid {GLASS_BORDER};
    border-radius: 14px;
}}
/* Table */
QTableWidget {{
    background-color: {TABLE_BG};
    border: none;
    border-radius: 0;
    gridline-color: rgba(255,255,255,0.05);
    selection-background-color: #3A3320;
    selection-color: {CORN_SOFT};
    alternate-background-color: {TABLE_ALT};
}}
/* The header background is solid on purpose: a translucent rgba would
   float over the widget's own (light) base palette. */
QHeaderView {{
    background-color: {TABLE_BG};
    border: none;
}}
QHeaderView::section {{
    background-color: {TABLE_BG};
    color: {CORN};
    padding: 8px;
    border: none;
    border-bottom: 1px solid {GLASS_BORDER};
    font-weight: 700;
    font-size: 11.5px;
    letter-spacing: 0.3px;
}}
QTableWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid rgba(255,255,255,0.035);
}}
QTableCornerButton::section {{
    background-color: {TABLE_HEADER};
    border: none;
}}

/* Log */
QPlainTextEdit#Log {{
    background-color: {LOG_BG};
    border: 1px solid {GLASS_BORDER};
    border-radius: 12px;
    padding: 10px;
    font-family: 'Cascadia Code', 'Consolas', monospace;
    font-size: 12px;
    color: {CORN_SOFT};
    selection-background-color: {CORN_DEEP};
    selection-color: #000;
}}

/* Progress bar */
QProgressBar {{
    background-color: rgba(0,0,0,0.4);
    border: 1px solid {GLASS_BORDER};
    border-radius: 10px;
    height: 20px;
    text-align: center;
    color: {TEXT};
    font-weight: 700;
    font-size: 12px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {CORN_DEEP}, stop:1 {CORN});
    border-radius: 9px;
    margin: 1px;
}}

/* Scroll bars; the vertical one keeps clear of the rounded corners */
QScrollBar:vertical {{
    background: transparent; width: 11px; margin: 10px 4px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255,255,255,0.14);
    border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {CORN_DEEP}; }}
QScrollBar:horizontal {{
    background: transparent; height: 11px; margin: 4px;
}}
QScrollBar::handle:horizontal {{
    background: rgba(255,255,255,0.14);
    border-radius: 5px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: {CORN_DEEP}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* Status line labels */
QLabel#StatLine {{
    color: {TEXT_MUTED};
    font-size: 12.5px;
}}
QLabel#StatCorn {{
    font-size: 13px; font-weight: 800; color: {CORN};
}}

/* Tooltip */
QToolTip {{
    background-color: {SURFACE};
    color: {TEXT};
    border: 1px solid {GLASS_BORDER};
    border-radius: 6px;
    padding: 5px 8px;
}}

/* Dialogs (message boxes) */
QMessageBox {{
    background-color: {BG2};
}}
QMessageBox QLabel {{
    color: {TEXT};
}}

/* ------------------------------------------------------------- footer */
QWidget#Footer {{
    background: transparent;
}}
QPushButton#Signature {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 2px 6px;
    font-size: 11px;
    font-weight: 500;
    letter-spacing: 0.3px;
    color: {TEXT_MUTED};
}}
QPushButton#Signature:hover {{
    color: {ACCENT};
}}
QPushButton#Signature:focus {{
    color: {ACCENT};
    border: none;
    background: transparent;
}}

/* The form cards scroll when the window is short */
QScrollArea#FormScroll, QScrollArea#FormScroll > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
"""


# The about card has its own style sheet: it is a separate, translucent window.
SIGNATURE_QSS = f"""
#AboutDialog {{ background: transparent; border: none; }}
* {{
    font-family: 'Segoe UI', 'Inter', Arial, sans-serif;
    color: {TEXT};
}}
QWidget#AboutCard {{
    background-color: {SURFACE};
    border: 1px solid rgba(255, 201, 60, 0.22);
    border-radius: 16px;
}}
QLabel#AboutTitle {{
    font-size: 18px;
    font-weight: 800;
    color: {ACCENT};
    letter-spacing: 0.3px;
}}
QLabel#AboutSubtitle {{
    font-size: 12px;
    color: {TEXT_MUTED};
    padding-top: 5px;
}}
QPushButton#AboutClose {{
    background: transparent;
    border: none;
    border-radius: 13px;
    color: {TEXT_MUTED};
    font-size: 13px;
    font-weight: 700;
}}
QPushButton#AboutClose:hover {{
    background-color: {DANGER};
    color: #FFFFFF;
}}
QWidget#AboutRule {{
    background-color: {GLASS_BORDER};
}}
QScrollArea#AboutScroll, QScrollArea#AboutScroll > QWidget > QWidget {{
    background: transparent;
    border: none;
}}
QLabel#AboutHeading {{
    color: {ACCENT};
    font-size: 12px;
    font-weight: 800;
    letter-spacing: 0.5px;
    padding-top: 4px;
}}
QLabel#AboutItem {{
    color: {TEXT};
    font-size: 12px;
    line-height: 150%;
    padding-left: 2px;
}}
QLabel#AboutFoot {{
    color: {TEXT_MUTED};
    font-size: 10.5px;
    padding-top: 4px;
}}
QScrollBar:vertical {{
    background: transparent; width: 9px; margin: 10px 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(255,255,255,0.16);
    border-radius: 4px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {CORN_DEEP}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def apply_theme(app) -> None:
    """Dark base palette and style engine for the application.

    The QSS only repaints the surfaces it has rules for. The base of the
    file dialog, the message boxes and the scroll views comes from the
    palette - without it light grey patches would remain in the dark theme.

    The Fusion style also lets the QSS apply the same way on every
    platform, whereas the native Windows style overrides a few rules
    (progress bar, check box).
    """
    from PySide6.QtGui import QColor, QPalette

    app.setStyle("Fusion")

    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(TABLE_BG))
    pal.setColor(QPalette.AlternateBase, QColor(TABLE_ALT))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_MUTED))
    pal.setColor(QPalette.Button, QColor(SURFACE))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.BrightText, QColor(DANGER))
    pal.setColor(QPalette.Highlight, QColor(CORN_DEEP))
    pal.setColor(QPalette.HighlightedText, QColor("#101017"))
    pal.setColor(QPalette.ToolTipBase, QColor(SURFACE))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.Link, QColor(CORN))
    pal.setColor(QPalette.Mid, QColor(GLASS_SOLID))

    for group in (QPalette.Disabled,):
        pal.setColor(group, QPalette.WindowText, QColor(TEXT_MUTED))
        pal.setColor(group, QPalette.Text, QColor(TEXT_MUTED))
        pal.setColor(group, QPalette.ButtonText, QColor(TEXT_MUTED))

    app.setPalette(pal)
