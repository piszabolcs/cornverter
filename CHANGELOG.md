# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning: [SemVer](https://semver.org/).

## [1.0.0] - 2026-10-19

### Added
- PySide6 desktop app that converts mixed files to PDF with two workflows: **Single files** (drop or choose
  files, PDF next to each or in a chosen folder) and **Whole folder** (into a separate output folder with a
  mirrored tree, or in place with the originals moved to `<folder>_originals`).
- Command line on the same Qt-free engine (`python main.py <file-or-folder>`, `--out`, `--inplace`,
  `--backup`, `--overwrite`).
- LibreOffice route when installed (headless, own profile, time limit, process-tree kill on cancel) and
  built-in renderers otherwise; spreadsheets with content-wide columns and a `###` check.
- E-mails (`.msg`, `.eml`) with attachments converted and merged; images and multi-page TIFs without
  re-encoding where possible; archives (`.zip`, `.7z`, `.rar`, `.tar`, `.gz`) unpacked with path checks and
  size, ratio, file-count and depth limits.
- Safety: no silent overwrites, folder-pair checks, atomic writes with a PDF check, links and junctions not
  followed, long Windows paths supported.
- Timestamped CSV log and Markdown summary for every run, About card, offscreen pytest suite, third-party
  notices (extract-msg GPL-3.0).
