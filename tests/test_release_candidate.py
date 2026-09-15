import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.ampr_index import _build_index_local
from core.lz4_packer import TOOLS_DIR, run_lz4_pack
from utils.process_manager import ExtractWorker, GameWorker
from utils.subprocess_utils import hidden_child_process_kwargs


def _tree_snapshot(root: Path):
    directories = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_dir()
    }
    files = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file()
    }
    return directories, files


class ReleaseCandidatePackTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="lazy_ampr_rc_"))
        self.source = self.root / "Game 🎮 テスト"
        self.source.mkdir()
        (self.source / "empty directory" / "nested empty").mkdir(parents=True)
        (self.source / "sce_sys").mkdir()
        (self.source / "sce_sys" / "note.txt").write_text("source-safe", encoding="utf-8")
        (self.source / "assets" / "zone_a").mkdir(parents=True)
        (self.source / "assets" / "zone_b").mkdir(parents=True)
        (self.source / "assets" / "zone_a" / "same.uasset").write_bytes(b"A" * 131_072)
        (self.source / "assets" / "zone_b" / "same.uasset").write_bytes(b"B" * 131_072)
        (self.source / "assets" / "café 日本語 🚀.uasset").write_bytes(b"unicode" * 4096)
        (self.source / "assets" / "café.uasset").write_bytes(b"normalized" * 4096)
        (self.source / "assets" / "zero.uasset").write_bytes(b"")
        (self.source / "assets" / "one-byte.uasset").write_bytes(b"x")
        (self.source / "assets" / "name with spaces & [brackets].uasset").write_bytes(
            b"punctuation" * 4096
        )
        deep = self.source
        for number in range(14):
            deep = deep / f"deep_{number:02d}_segment"
        deep.mkdir(parents=True)
        (deep / "last.uasset").write_bytes(b"deep" * 8192)
        (self.source / "assets" / "large-compressible.uasset").write_bytes(
            b"large synthetic asset\n" * 400_000
        )

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _pack_extract(self, label, block_size, workers, decoded, physical):
        packed = self.root / f"packed-{label}"
        settings = {
            "lz4_level": 9,
            "auto_loose_large": False,
            "decoded_cache_mib": decoded,
            "physical_cache_mib": physical,
            "use_hardlinks": False,
        }
        run_lz4_pack(
            self.source,
            packed,
            settings,
            workers=workers,
            block_size_kib=block_size,
        )
        diagnostics = list(packed.with_name(packed.name + '.build-diagnostics').glob('build-*'))
        self.assertEqual(len(diagnostics), 1)
        evidence = diagnostics[0]
        for name in ('source-tree.sha256', 'ampr-index.sha256', 'profile.toml',
                     'profile.sha256', 'pack-inspect.txt', 'pack-list.json',
                     'packed-files.txt', 'loose-files.txt', 'output-files.sha256',
                     'build-environment.txt'):
            self.assertTrue((evidence / name).is_file(), name)
        self.assertTrue((evidence / 'status.txt').read_text().startswith('Complete.'))
        environment = json.loads((evidence / 'build-environment.txt').read_text())
        self.assertEqual(environment['worker_count'], workers)
        self.assertIn('ampr_pack_format_header', environment)
        rows = json.loads((evidence / 'pack-list.json').read_text(encoding='utf-8'))
        self.assertTrue(any('café' in row['path'] for row in rows))
        self.assertEqual((evidence / 'profile.sha256').read_text().strip(),
                         hashlib.sha256((evidence / 'profile.toml').read_bytes()).hexdigest())
        extracted = self.root / f"extracted-{label}"
        outcomes = []
        worker = ExtractWorker(packed, extracted)
        worker.finished.connect(lambda ok, message: outcomes.append((ok, message)))
        worker.run()
        self.assertTrue(outcomes and outcomes[-1][0], outcomes[-1][1] if outcomes else "no result")
        self.assertEqual(_tree_snapshot(self.source), _tree_snapshot(extracted))
        return packed

    def test_stress_round_trip_across_two_configs_and_is_deterministic(self):
        first = self._pack_extract("small", 16, 1, 0, 0)
        self._pack_extract("large", 128, 2, 256, 64)

        repeat = self.root / "packed-repeat"
        run_lz4_pack(
            self.source,
            repeat,
            {
                "lz4_level": 9,
                "auto_loose_large": False,
                "decoded_cache_mib": 0,
                "physical_cache_mib": 0,
                "use_hardlinks": False,
            },
            workers=1,
            block_size_kib=16,
        )
        deterministic_names = ["ampr_emu.index", "ampr_assets.index"]
        deterministic_names.extend(path.name for path in sorted(first.glob("ampr_assets-*.pak")))
        self.assertGreater(len(deterministic_names), 2)
        for name in deterministic_names:
            self.assertEqual((first / name).read_bytes(), (repeat / name).read_bytes(), name)

    def test_loose_outputs_are_independent_by_default_and_hardlinks_are_opt_in(self):
        safe = self.root / "safe-output"
        run_lz4_pack(
            self.source,
            safe,
            {"lz4_level": 1, "auto_loose_large": False},
            workers=1,
        )
        safe_note = safe / "sce_sys" / "note.txt"
        self.assertFalse(os.path.samefile(self.source / "sce_sys" / "note.txt", safe_note))
        safe_note.write_text("output edit", encoding="utf-8")
        self.assertEqual((self.source / "sce_sys" / "note.txt").read_text("utf-8"), "source-safe")

        linked = self.root / "linked-output"
        run_lz4_pack(
            self.source,
            linked,
            {"lz4_level": 1, "auto_loose_large": False, "use_hardlinks": True},
            workers=1,
        )
        self.assertTrue(os.path.samefile(
            self.source / "sce_sys" / "note.txt", linked / "sce_sys" / "note.txt"
        ))

    def test_corrupt_pack_and_stale_source_metadata_are_rejected(self):
        packed = self.root / "packed-corrupt"
        run_lz4_pack(
            self.source,
            packed,
            {"lz4_level": 1, "auto_loose_large": False},
            workers=1,
        )
        pak = next(packed.glob("ampr_assets-*.pak"))
        with pak.open("r+b") as stream:
            stream.truncate(max(1, pak.stat().st_size // 2))
        verify = subprocess.run(
            [
                sys.executable,
                str(TOOLS_DIR / "ampr_pack.py"),
                "verify",
                "--index",
                str(packed / "ampr_assets.index"),
                "--root",
                str(self.source),
            ],
            cwd=TOOLS_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(verify.returncode, 0, verify.stdout + verify.stderr)

        stale_index = self.root / "stale.index"
        _build_index_local(self.source, stale_index)
        target = self.source / "assets" / "zone_a" / "same.uasset"
        target.write_bytes(target.read_bytes() + b"changed")
        config = self.root / "pack.toml"
        config.write_text(
            '[[rule]]\naction = "pack"\ninclude = ["**/*.uasset"]\n', encoding="utf-8"
        )
        stale = subprocess.run(
            [
                sys.executable,
                str(TOOLS_DIR / "ampr_pack.py"),
                "pack",
                "--root",
                str(self.source),
                "--ampr-index",
                str(stale_index),
                "--output",
                str(self.root / "stale-output"),
                "--config",
                str(config),
            ],
            cwd=TOOLS_DIR,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(stale.returncode, 0, stale.stdout + stale.stderr)


class ReleaseCandidateWorkerTests(unittest.TestCase):
    def test_windows_child_helpers_are_launched_without_a_console_window(self):
        kwargs = hidden_child_process_kwargs()
        if sys.platform == "win32":
            self.assertEqual(kwargs, {"creationflags": subprocess.CREATE_NO_WINDOW})
        else:
            self.assertEqual(kwargs, {})

    def test_pack_launch_passes_hidden_window_flags_to_popen(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "game"
            (source / "sce_sys").mkdir(parents=True)
            (source / "sce_sys" / "note.txt").write_text("loose", encoding="utf-8")

            process = unittest.mock.MagicMock()
            process.__enter__.return_value = process
            process.stdout = iter(['{"loose_paths": ["sce_sys/note.txt"]}\n'])
            process.returncode = 0
            with patch("core.lz4_packer.subprocess.Popen", return_value=process) as popen, \
                    patch("core.build_diagnostics.BuildDiagnostics"):
                run_lz4_pack(
                    source,
                    root / "output",
                    {"lz4_level": 1, "auto_loose_large": False},
                    skip_verify=True,
                    workers=1,
                )

            expected = hidden_child_process_kwargs()
            for key, value in expected.items():
                self.assertEqual(popen.call_args.kwargs[key], value)

    def test_cancel_race_terminates_a_process_registered_after_cancel(self):
        worker = GameWorker("missing", "output", {})
        process = unittest.mock.MagicMock()
        process.poll.return_value = None
        worker.cancel()
        worker._set_active_process(process)
        process.terminate.assert_called_once_with()

    def test_game_worker_only_runs_ampr_packing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "game"
            source.mkdir()
            outcomes = []
            worker = GameWorker(source, root / "output", {}, source_read_only=True)
            worker.pipeline_finished.connect(lambda ok, message: outcomes.append((ok, message)))
            with patch("utils.process_manager.run_lz4_pack") as pack:
                worker.run()
            self.assertTrue(outcomes)
            self.assertTrue(outcomes[-1][0])
            self.assertIn("AMPR packing completed", outcomes[-1][1])
            pack.assert_called_once()
            self.assertNotIn("do_backport", pack.call_args.kwargs)
            self.assertTrue(pack.call_args.kwargs["source_read_only"])

    def test_subprocess_start_failure_is_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "game"
            (source / "assets").mkdir(parents=True)
            (source / "assets" / "file.uasset").write_bytes(b"data")
            with (
                patch("core.lz4_packer.subprocess.Popen", side_effect=OSError("startup failed")),
                self.assertRaisesRegex(OSError, "startup failed"),
            ):
                run_lz4_pack(
                    source,
                    root / "output",
                    {"lz4_level": 1, "auto_loose_large": False},
                    workers=1,
                )


if __name__ == "__main__":
    unittest.main()
