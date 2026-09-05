#!/usr/bin/env python3
"""Ponto de entrada da CLI.

    python main.py collect
    python main.py check
    python main.py merge
    python main.py reconcile
    python main.py status
"""

from __future__ import annotations

import sys

from src.cli import main

if __name__ == "__main__":
    sys.exit(main())
