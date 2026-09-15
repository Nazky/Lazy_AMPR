import json
from pathlib import Path
from typing import Any

from utils.sdk_utils import sdk_to_human


def parse_game_info(game_dir: Path) -> dict[str, Any]:
    info = {"title": game_dir.name, "title_id": "Unknown", "version": "1.00",
            "sdk_version": "Unknown", "content_id": "Unknown", "icon_path": None}

    icon_path = game_dir / "sce_sys" / "icon0.png"
    if icon_path.exists():
        info["icon_path"] = icon_path

    for candidate in (game_dir / "param.json", game_dir / "sce_sys" / "param.json"):
        if not candidate.exists():
            continue
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            info["title_id"] = str(data.get("titleId") or info["title_id"])
            info["version"] = str(data.get("contentVersion") or info["version"])
            info["sdk_version"] = sdk_to_human(data.get("sdkVersion", info["sdk_version"]))
            info["content_id"] = str(data.get("contentId") or info["content_id"])
            localized = data.get("localizedParameters", {})
            if not isinstance(localized, dict):
                localized = {}
            lang = localized.get("defaultLanguage", "en-GB")
            language_data = localized.get(lang, {})
            title = language_data.get("titleName") if isinstance(language_data, dict) else None
            if not title:
                for v in localized.values():
                    if isinstance(v, dict) and v.get("titleName"):
                        title = v["titleName"]; break
            if title:
                info["title"] = str(title)
            break
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            continue
    return info
