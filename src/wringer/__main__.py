"""Allow `python -m wringer` alongside the `wring` console script."""

import sys

from wringer.cli import main

if __name__ == "__main__":
    sys.exit(main())
