"""Allow `python -m cox` alongside the `cox` console script."""

import sys

from cox.cli import main

if __name__ == "__main__":
    sys.exit(main())
