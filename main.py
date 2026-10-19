"""
CornVerter entry point.

    python main.py                      the window
    python main.py <file-or-folder>     command line (see --help)

On Windows, run_cornverter.bat creates the virtual environment, installs the
dependencies and then calls this file.
"""

import sys

from cornverter.entry import start

if __name__ == "__main__":
    sys.exit(start(sys.argv[1:]))
