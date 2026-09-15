import os
import sys
from pathlib import Path


def get_app_data_dir() -> Path:
    """Returns a cross-platform directory for app settings/cache."""
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Lazy_AMPR"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Lazy_AMPR"
    else:
        return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "lazy_ampr"

def normalize_path(path: str) -> Path:
    """Normalize path for cross-platform consistency."""
    p = Path(path).expanduser().resolve()
    return p