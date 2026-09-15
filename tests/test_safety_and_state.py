import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import utils.state as state_module
from utils import net
from utils.file_ops import validate_separate_trees


class SeparateTreeTests(unittest.TestCase):
    def test_rejects_same_nested_and_parent_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "game"
            source.mkdir()
            for output in (source, source / "output", root):
                with self.subTest(output=output), self.assertRaises(ValueError):
                    validate_separate_trees(source, output)

    def test_accepts_sibling_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "game"
            source.mkdir()
            validate_separate_trees(source, root / "game_AMPR")


class StateTests(unittest.TestCase):
    def test_uses_data_directory_and_copies_bundled_profiles_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "bundle"
            profiles = bundle / "toml_profiles"
            profiles.mkdir(parents=True)
            (profiles / "game.toml").write_text("original", encoding="utf-8")
            data = root / "data"

            with patch.multiple(
                state_module,
                BUNDLE_ROOT=bundle,
                DATA_DIR=data,
                TOML_DIR=data / "toml_profiles",
                STATE_FILE=data / "state.json",
            ):
                state_module.State()
                installed = data / "toml_profiles" / "game.toml"
                self.assertEqual(installed.read_text("utf-8"), "original")
                installed.write_text("user edit", encoding="utf-8")
                state_module.State()
                self.assertEqual(installed.read_text("utf-8"), "user edit")
                saved = json.loads((data / "state.json").read_text("utf-8"))
                self.assertEqual(saved["games"], [])

    def test_malformed_state_falls_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            state_file = data / "state.json"
            state_file.write_text("[]", encoding="utf-8")
            with patch.multiple(
                state_module,
                BUNDLE_ROOT=data / "missing",
                DATA_DIR=data,
                TOML_DIR=data / "toml_profiles",
                STATE_FILE=state_file,
            ):
                state = state_module.State()
                self.assertEqual(state.settings["lz4_level"], 9)

    def test_invalid_setting_types_are_normalized(self):
        normalized = state_module._normalized_settings({
            "lz4_level": "999",
            "workers": "bad",
            "theme": "Neon",
            "skip_lz4_verification": "false",
            "block_size_kib": "not-a-size",
            "decoded_cache_mib": -50,
            "physical_cache_mib": 99999999,
            "use_hardlinks": "yes",
        })
        self.assertEqual(normalized["lz4_level"], 12)
        self.assertIsNone(normalized["workers"])
        self.assertEqual(normalized["theme"], "Auto")
        self.assertFalse(normalized["skip_lz4_verification"])
        self.assertEqual(normalized["block_size_kib"], 128)
        self.assertEqual(normalized["decoded_cache_mib"], 0)
        self.assertEqual(normalized["physical_cache_mib"], 1024 * 1024)
        self.assertFalse(normalized["use_hardlinks"])

    def test_removed_backport_settings_are_discarded(self):
        normalized = state_module._normalized_settings({
            "backport_games": True,
            "fakelib_path": "C:/old-fakelib",
            "sdk_pair": 4,
        })
        self.assertNotIn("backport_games", normalized)
        self.assertNotIn("fakelib_path", normalized)
        self.assertNotIn("sdk_pair", normalized)

    def test_schema_upgrade_does_not_reset_a_current_lz4_choice(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            state_file = data / "state.json"
            state_file.write_text(json.dumps({
                "settings_version": 2,
                "settings": {"lz4_level": 7, "backport_games": True},
                "games": [],
            }), encoding="utf-8")
            with patch.multiple(
                state_module,
                BUNDLE_ROOT=data / "missing",
                DATA_DIR=data,
                TOML_DIR=data / "toml_profiles",
                STATE_FILE=state_file,
            ):
                state = state_module.State()
                self.assertEqual(state.settings["lz4_level"], 7)
                self.assertNotIn("backport_games", state.settings)

    def test_missing_game_paths_are_not_deleted_from_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            state_file = data / "state.json"
            missing = data / "disconnected-drive" / "game"
            state_file.write_text(json.dumps({
                "settings_version": state_module.SETTINGS_VERSION,
                "settings": {},
                "games": [{"path": str(missing), "title": "Saved game"}],
            }), encoding="utf-8")
            with patch.multiple(
                state_module,
                BUNDLE_ROOT=data / "missing",
                DATA_DIR=data,
                TOML_DIR=data / "toml_profiles",
                STATE_FILE=state_file,
            ):
                state = state_module.State()
                self.assertIn(str(missing), state.games)
                saved = json.loads(state_file.read_text("utf-8"))
                self.assertEqual(saved["games"][0]["title"], "Saved game")


class DownloadSafetyTests(unittest.TestCase):
    def test_rejects_non_http_url_before_opening(self):
        with patch("urllib.request.urlopen") as opener, self.assertRaises(ValueError):
            net._get("file:///etc/passwd")
        opener.assert_not_called()

    def test_rejects_path_traversal_filename(self):
        with tempfile.TemporaryDirectory() as temporary, self.assertRaises(ValueError):
            net.download_toml("../outside.toml", "https://example.test/a.toml", Path(temporary))

    def test_enforces_download_size_limit(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.geturl.return_value = "https://example.test/game.toml"
        response.headers = {"Content-Length": str(net.MAX_DOWNLOAD_BYTES + 1)}
        with patch("urllib.request.urlopen", return_value=response), self.assertRaises(ValueError):
            net._get("https://example.test/game.toml")

    def test_rejects_invalid_toml_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary)
            with (
                patch.object(net, "_get", return_value=b"[broken"),
                self.assertRaisesRegex(ValueError, "invalid syntax"),
            ):
                net.download_toml(
                    "game.toml", "https://example.test/game.toml", destination
                )
            self.assertFalse((destination / "game.toml").exists())


if __name__ == "__main__":
    unittest.main()
