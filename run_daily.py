#!/usr/bin/env python3
"""Scheduled runner entry point: ``python run_daily.py --format shorts``."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from studio.daily import main

if __name__ == "__main__":
    raise SystemExit(main())
