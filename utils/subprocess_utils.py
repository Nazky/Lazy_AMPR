import subprocess
import sys


def hidden_child_process_kwargs() -> dict:
    """Prevent bundled console helpers from opening a terminal on Windows."""
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
