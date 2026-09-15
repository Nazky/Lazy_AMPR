import json
import re
import shutil
from pathlib import Path

from utils.cross_platform import get_app_data_dir

BUNDLE_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = get_app_data_dir()
TOML_DIR = DATA_DIR / "toml_profiles"
STATE_FILE = DATA_DIR / "state.json"

SETTINGS_VERSION = 3   # bump this whenever the saved settings schema changes

DEFAULT_SETTINGS = {
    "output_dir": "",
    "lz4_level": 9,
    "skip_lz4_verification": False,
    "block_size_kib": 128,
    "decoded_cache_mib": 256,
    "physical_cache_mib": 64,
    "workers": None,
    "auto_loose_large": True,
    "use_hardlinks": False,
    "theme": "Auto",
}


def _normalized_settings(saved):
    settings = {**DEFAULT_SETTINGS, **saved}
    for obsolete in ("backport_games", "fakelib_path", "sdk_pair"):
        settings.pop(obsolete, None)
    limits = {
        "lz4_level": (1, 12),
        "block_size_kib": (16, 1024),
        "decoded_cache_mib": (0, 1024 * 1024),
        "physical_cache_mib": (0, 1024 * 1024),
    }
    for key, (minimum, maximum) in limits.items():
        try:
            settings[key] = max(minimum, min(maximum, int(settings[key])))
        except (TypeError, ValueError):
            settings[key] = DEFAULT_SETTINGS[key]
    workers = settings.get("workers")
    if workers is not None:
        try:
            settings["workers"] = max(1, min(256, int(workers)))
        except (TypeError, ValueError):
            settings["workers"] = None
    for key in ("skip_lz4_verification", "auto_loose_large", "use_hardlinks"):
        if not isinstance(settings.get(key), bool):
            settings[key] = DEFAULT_SETTINGS[key]
    if settings.get("theme") not in {"Light", "Dark", "Auto"}:
        settings["theme"] = DEFAULT_SETTINGS["theme"]
    for key in ("output_dir",):
        if not isinstance(settings.get(key), str):
            settings[key] = DEFAULT_SETTINGS[key]
    return settings

def slug(s): return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")

class State:
    def __init__(self):
        TOML_DIR.mkdir(parents=True, exist_ok=True)
        bundled_tomls = BUNDLE_ROOT / "toml_profiles"
        if bundled_tomls.is_dir() and bundled_tomls.resolve() != TOML_DIR.resolve():
            for profile in bundled_tomls.glob("*.toml"):
                destination = TOML_DIR / profile.name
                if not destination.exists():
                    shutil.copy2(profile, destination)

        raw = {}
        state_source = STATE_FILE
        legacy_state = BUNDLE_ROOT / "state.json"
        if not state_source.exists() and legacy_state.is_file():
            state_source = legacy_state
        if state_source.exists():
            try:
                loaded = json.loads(state_source.read_text("utf-8"))
                if isinstance(loaded, dict):
                    raw = loaded
            except (OSError, UnicodeError, json.JSONDecodeError):
                raw = {}
        saved_settings = raw.get("settings", {})
        if not isinstance(saved_settings, dict):
            saved_settings = {}
        self.settings = _normalized_settings(saved_settings)

        # One-time migration: builds before SETTINGS_VERSION 2 stored lz4_level=12
        # as the old default, so the saved 12 keeps overriding the new default 9.
        try:
            saved_version = int(raw.get("settings_version", 1))
        except (TypeError, ValueError):
            saved_version = 1
        if saved_version < 2:
            self.settings["lz4_level"] = 9

        self.games = {}
        saved_games = raw.get("games", [])
        if not isinstance(saved_games, list):
            saved_games = []
        for e in saved_games:
            if not isinstance(e, dict):
                continue
            p = e.get("path", "")
            # Keep entries for temporarily disconnected/removable drives.
            # The UI decides whether an entry can be displayed right now.
            if isinstance(p, str) and p:
                self.games[p] = e
        self.save()

    def save(self):
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "settings": self.settings,
            "settings_version": SETTINGS_VERSION,
            "games": list(self.games.values()),
        }, indent=2)
        temporary = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
        temporary.write_text(payload, "utf-8")
        temporary.replace(STATE_FILE)

    def upsert_game(self, path, **kw):
        e = self.games.setdefault(str(path), {"path": str(path)})
        e.update(kw); self.save(); return e
    def get_game(self, path): return self.games.get(str(path))
    def tomls(self): return sorted(TOML_DIR.glob("*.toml"))
    def auto_toml_for(self, title_id, title, content_id=""):
        """Match TOML files to games using flexible name matching."""
        # Normalize all inputs: remove separators and lowercase
        def normalize(s):
            if not s:
                return ""
            return re.sub(r"[^a-z0-9]", "", str(s).lower())
        
        # Build normalized keys from game metadata
        keys = [normalize(title_id), normalize(title), normalize(content_id)]
        keys = [k for k in keys if k]  # Remove empty strings
        
        # Also create a version without underscores for exact matches
        keys.extend([k.replace("_", "") for k in keys])
        
        for t in self.tomls():
            stem = normalize(t.stem)
            if not stem:
                continue
            
            # Check if TOML name matches any game key
            for k in keys:
                if not k:
                    continue
                # Match if: exact match, TOML contains game name, or game name contains TOML
                if stem == k or stem in k or k in stem:
                    return t.name
        
        return None
    def games_using(self, toml_name):
        return [e for e in self.games.values() if e.get("toml") == toml_name]
    def link_toml(self, path, name, src="auto"):
        self.upsert_game(path, toml=name, toml_src=src)


def load_settings():
    """Compatibility helper retained for older callers."""
    return dict(State().settings)


def save_settings(settings):
    """Compatibility helper retained for older callers."""
    state = State()
    state.settings = _normalized_settings(dict(settings))
    state.save()
