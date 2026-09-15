"""Legacy import shim.

All persistence now lives in utils.state (single file: state.json).
This module exists only so old `from utils.config import ...` imports
keep working and hit the same file.
"""
from utils.state import DEFAULT_SETTINGS, load_settings, save_settings  # noqa: F401