#!/usr/bin/env python3
"""Compatibility launcher.

The implementation lives in the ``gesture_media_control`` package. This script
keeps ``python gesture-media-control.py`` working from the repository root.
"""

from __future__ import annotations

import sys

from gesture_media_control.cli import main

if __name__ == "__main__":
    sys.exit(main())
