import importlib
import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    from fastapi.testclient import TestClient
except ImportError:  # web extras are optional for the desktop build
    TestClient = None

import utils.state


@unittest.skipIf(TestClient is None, "fastapi/httpx not installed (pip install -r requirements-web.txt httpx)")
class WebApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp(prefix="lazy_ampr_web_test_"))
        cls.games = cls.root / "games"
        cls.output = cls.root / "output"
        cls.games.mkdir()
        cls.output.mkdir()
        data = cls.root / "config"
        cls.state_patch = patch.multiple(
            utils.state,
            DATA_DIR=data,
            TOML_DIR=data / "toml_profiles",
            STATE_FILE=data / "state.json",
        )
        cls.state_patch.start()
        cls.env_patch = patch.dict(os.environ, {
            "LAZY_AMPR_ROOTS": f"{cls.games},{cls.output}",
            "LAZY_AMPR_DEFAULT_OUTPUT": str(cls.output),
            "LAZY_AMPR_PASSWORD": "",
        })
        cls.env_patch.start()
        import web.app
        cls.web = importlib.reload(web.app)
        cls.client = TestClient(cls.web.app)

    @classmethod
    def tearDownClass(cls):
        cls.env_patch.stop()
        cls.state_patch.stop()
        shutil.rmtree(cls.root, ignore_errors=True)

    def make_game(self, name, title_id="PPSA00001"):
        game = self.games / name
        (game / "assets").mkdir(parents=True)
        (game / "sce_sys").mkdir()
        (game / "assets" / "world.uasset").write_bytes(b"compressible asset data\n" * 8192)
        (game / "sce_sys" / "param.json").write_text(json.dumps({
            "titleId": title_id,
            "contentVersion": "01.000.000",
            "localizedParameters": {"defaultLanguage": "en-US", "en-US": {"titleName": "Test Game"}},
        }), encoding="utf-8")
        return game

    def wait_for(self, job_id, timeout=120):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            job = self.client.get(f"/api/jobs/{job_id}").json()
            if job["state"] not in ("queued", "running"):
                return job
            time.sleep(0.2)
        self.fail(f"job {job_id} did not finish")

    def test_paths_outside_roots_are_rejected(self):
        self.assertEqual(self.client.get("/api/browse", params={"path": "/etc"}).status_code, 403)
        outside = self.client.get("/api/browse", params={"path": f"{self.games}/../.."})
        self.assertEqual(outside.status_code, 403)
        self.assertEqual(self.client.get("/api/browse", params={"path": "relative"}).status_code, 400)

    def test_browse_lists_roots_and_marks_games(self):
        self.make_game("BrowseGame", "PPSA00042")
        roots = self.client.get("/api/browse").json()
        self.assertEqual({e["path"] for e in roots["entries"]}, {str(self.games.resolve()), str(self.output.resolve())})
        listing = self.client.get("/api/browse", params={"path": str(self.games)}).json()
        entry = next(e for e in listing["entries"] if e["name"] == "BrowseGame")
        self.assertTrue(entry["is_game"])

    def test_toml_crud_validates_names_and_syntax(self):
        self.assertEqual(self.client.put("/api/tomls/bad.toml", json={"content": "[broken"}).status_code, 400)
        escape = self.client.put("/api/tomls/..%2Fescape.toml", json={"content": ""})
        self.assertGreaterEqual(escape.status_code, 400)
        self.assertFalse((utils.state.DATA_DIR / "escape.toml").exists())
        self.assertEqual(self.client.put("/api/tomls/x.txt", json={"content": ""}).status_code, 400)
        self.assertEqual(self.client.put("/api/tomls/ok.toml", json={"content": "[pack]\n"}).status_code, 200)
        names = [t["name"] for t in self.client.get("/api/tomls").json()["tomls"]]
        self.assertIn("ok.toml", names)
        self.assertEqual(self.client.get("/api/tomls/ok.toml").text, "[pack]\n")
        self.assertEqual(self.client.delete("/api/tomls/ok.toml").status_code, 200)

    def test_settings_roundtrip_is_normalized(self):
        saved = self.client.put("/api/settings", json={"lz4_level": 99, "workers": 2}).json()
        self.assertEqual(saved["lz4_level"], 12)
        self.assertEqual(saved["workers"], 2)
        self.assertEqual(self.client.put("/api/settings", json={"output_dir": "/etc"}).status_code, 403)
        self.client.put("/api/settings", json={"lz4_level": 9, "workers": None})

    def test_pack_then_extract_through_jobs(self):
        game = self.make_game("RoundTrip", "PPSA00077")
        games = self.client.get("/api/games", params={"path": str(self.games)}).json()["games"]
        payload = next(g for g in games if g["path"] == str(game.resolve()))
        self.assertEqual(payload["title"], "Test Game")
        self.assertEqual(payload["default_output"], str(self.output / "RoundTrip_AMPR"))

        response = self.client.post("/api/jobs/pack", json={
            "path": str(game), "lz4_level": 1, "use_linked_toml": False,
        })
        self.assertEqual(response.status_code, 200, response.text)
        job = self.wait_for(response.json()["id"])
        self.assertEqual(job["state"], "done", "\n".join(job["log"][-30:]))
        packed = self.output / "RoundTrip_AMPR"
        self.assertTrue((packed / "ampr_assets.index").is_file())
        self.assertTrue(any(packed.glob("ampr_assets-*.pak")))

        response = self.client.post("/api/jobs/extract", json={"path": str(packed)})
        self.assertEqual(response.status_code, 200, response.text)
        job = self.wait_for(response.json()["id"])
        self.assertEqual(job["state"], "done", "\n".join(job["log"][-30:]))
        extracted = self.output / "RoundTrip_AMPR_EXTRACTED"
        self.assertEqual((extracted / "assets" / "world.uasset").read_bytes(),
                         (game / "assets" / "world.uasset").read_bytes())

    def test_output_inside_source_is_rejected(self):
        game = self.make_game("Nested", "PPSA00078")
        response = self.client.post("/api/jobs/pack", json={"path": str(game), "output": str(game / "out")})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
