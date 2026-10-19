"""`python -m cornverter [path ...]`: the window, or the command line."""

import sys

from .entry import start

if __name__ == "__main__":
    sys.exit(start(sys.argv[1:]))
