"""Resolve bundled AMPR command-line helpers in source and frozen builds."""

import sys
from pathlib import Path


def command_for(script: Path) -> list[str]:
    """Return the command prefix used to execute an AMPR tool script."""
    script = Path(script)
    if getattr(sys, "frozen", False):
        suffix = ".exe" if sys.platform == "win32" else ""
        worker = (
            Path(sys.executable).resolve().parent
            / "workers"
            / script.stem
            / f"{script.stem}{suffix}"
        )
        if not worker.is_file():
            raise FileNotFoundError(f"Bundled AMPR helper not found: {worker}")
        return [str(worker)]
    return [sys.executable, str(script)]
