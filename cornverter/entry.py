"""Start-up switch shared by main.py and `python -m cornverter`."""

from __future__ import annotations


def start(argv: list[str]) -> int:
    """Arguments -> command line (no Qt is imported); none -> the window."""
    if argv:
        from .cli import main

        return main(argv)
    from .app import run

    run()
    return 0
