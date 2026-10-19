# Third-party notices

CornVerter's own code is MIT-licensed (see `LICENSE`). It uses the following
components, installed from PyPI by `requirements.txt` (nothing is bundled in
this repository). Their licences apply to them.

| Component | Used for | Licence |
|---|---|---|
| PySide6 / shiboken6 (Qt for Python) | GUI | LGPL-3.0-only (or GPL-2.0/3.0) |
| reportlab | rendering PDFs | BSD |
| pypdf | merging and checking PDFs | BSD-3-Clause |
| Pillow | images | MIT-CMU (HPND) |
| img2pdf | images into PDF without re-encoding | LGPL-3.0 |
| openpyxl (+ et-xmlfile) | .xlsx / .xlsm | MIT |
| xlrd | .xls | BSD |
| **extract-msg** | Outlook .msg e-mails | **GPL-3.0** |
| extract-msg dependencies: RTFDE | | LGPL-3.0 |
| … olefile, ebcdic, oletools, pycryptodomex | | BSD |
| … compressed-rtf, beautifulsoup4, tzlocal, red-black-tree-mod, lark | | MIT |
| py7zr | .7z | LGPL-2.1-or-later |
| py7zr dependencies: pyppmd, pybcj, inflate64, multivolumefile | | LGPL-2.1-or-later |
| … brotli, texttable | | MIT |
| rarfile | .rar | ISC |
| pikepdf (dependency of img2pdf) | | MPL-2.0 |

The table lists the direct dependencies and the main packages they bring in;
`pip show <package>` (or a tool such as pip-licenses) lists the complete set
installed in `.venv`.

External programs, used when present and never shipped with CornVerter:

| Program | Used for | Licence |
|---|---|---|
| LibreOffice | Office/ODF to PDF with formatting | MPL-2.0 |
| bsdtar (`tar.exe` in Windows 10/11) / unrar | compressed .rar members | BSD / unrar licence |

Fonts: the PDFs use the operating system's fonts (Arial, Consolas, DejaVu…)
or, as a fallback, Bitstream Vera shipped inside the reportlab package. No
font file is part of this repository.

## Note on extract-msg (GPL-3.0)

`cornverter/converters/msg.py` imports `extract-msg`, which is licensed under
the GNU GPL version 3. The MIT licence of CornVerter's source is compatible
with that, but anyone who **distributes** CornVerter together with
extract-msg (for example as a packaged executable) must follow the GPL's
terms for that distribution. Without extract-msg installed, everything except
`.msg` conversion keeps working.
