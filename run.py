#!/usr/bin/env python3
"""Entry point kept for compatibility: ``python run.py <command>``.

The implementation lives in :mod:`studio.cli`; ``python -m studio`` works too.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from studio.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
