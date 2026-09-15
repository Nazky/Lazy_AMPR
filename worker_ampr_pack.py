"""Frozen entry point for the AMPR pack command-line helper."""

import sys

from ampr_pack import main

if __name__ == "__main__":
    # PyInstaller's interpreter may ignore PYTHONIOENCODING. The GUI reads
    # UTF-8; keep JSON paths lossless regardless of the Windows code page.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
