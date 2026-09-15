import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.ampr_index import (
    _build_index_local,
    build_hash_slots,
    ensure_ampr_index,
    fnv1a64_path_hash,
    key_for,
)


def runtime_hash(path):
    value = 1469598103934665603
    raw = path.replace("\\", "/").encode("utf-8")
    for byte in raw:
        if 0x41 <= byte <= 0x5A:
            byte += 0x20
        value ^= byte
        value = (value * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return value or 1


class AmprIndexCompatibilityTests(unittest.TestCase):
    def test_hash_matches_runtime_for_non_ascii_path(self):
        path = "/app0/Ässets/CAFÉ.BIN"
        self.assertEqual(key_for(path), b"/app0/\xc3\x84ssets/caf\xc3\x89.bin")
        self.assertEqual(fnv1a64_path_hash(path), runtime_hash(path))

    def test_duplicate_hash_marks_both_slots(self):
        rows = [(1, 0, "/app0/A.bin"), (2, 0, "/app0/a.BIN")]
        occupied = [slot for slot in build_hash_slots(rows) if slot[1]]
        self.assertEqual(len(occupied), 2)
        self.assertEqual({slot[2] for slot in occupied}, {1})

    def test_case_insensitive_path_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "Asset.bin"
            first.write_bytes(b"one")
            # On a case-sensitive filesystem this creates the second real
            # entry. On Windows it aliases the first file, while the patched
            # listing still exercises the same runtime-incompatible names.
            (root / "asset.BIN").write_bytes(b"two")
            with (
                patch(
                    "core.ampr_index.os.walk",
                    return_value=[(str(root), [], ["Asset.bin", "asset.BIN"])],
                ),
                self.assertRaises(ValueError),
            ):
                _build_index_local(root, root.parent / "index.bin")

    def test_fakelib_marker_regenerates_existing_source_index(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "fakelib").mkdir()
            (root / "fakelib" / "libSceAmpr.sprx").write_bytes(b"sprx")
            asset = root / "assets.bin"
            asset.write_bytes(b"first")
            index = root / "ampr_emu.index"
            index.write_bytes(b"stale")

            self.assertEqual(ensure_ampr_index(root), index)
            first = index.read_bytes()
            self.assertTrue(first.startswith(b"AMPRIDX3"))

            asset.write_bytes(b"second-version")
            self.assertEqual(ensure_ampr_index(root), index)
            self.assertNotEqual(index.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
