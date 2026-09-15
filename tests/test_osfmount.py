import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from utils.osfmount import (
    MountedImage,
    _exfat_partition_number,
    mount_exfat_image,
    unmount_exfat_image,
)
from utils.subprocess_utils import hidden_child_process_kwargs


class OSFMountTests(unittest.TestCase):
    def _raw_exfat(self, root: Path) -> Path:
        image = root / "game.exfat"
        header = bytearray(512)
        header[3:11] = b"EXFAT   "
        image.write_bytes(header)
        return image

    def test_raw_exfat_mount_is_read_only_hidden_and_has_no_partition_selector(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = self._raw_exfat(Path(temporary))
            completed = subprocess.CompletedProcess([], 0, "mounted", "")
            with (
                patch("utils.osfmount.sys", SimpleNamespace(platform="win32")),
                patch("utils.osfmount.find_osfmount", return_value=Path("OSFMount.com")),
                patch("utils.osfmount.is_administrator", return_value=True),
                patch("utils.osfmount._free_drive_letter", return_value="Z"),
                patch("utils.osfmount.subprocess.run", return_value=completed) as run,
                patch("pathlib.Path.is_dir", return_value=True),
            ):
                mounted = mount_exfat_image(image)

        self.assertEqual(mounted, MountedImage(image.resolve(), "Z"))
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ["OSFMount.com", "-a", "-t", "file"])
        self.assertIn("ro,logical", args)
        self.assertNotIn("-v", args)
        for key, value in hidden_child_process_kwargs().items():
            self.assertEqual(run.call_args.kwargs[key], value)

    def test_mbr_exfat_partition_is_detected(self):
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "partitioned.exfat"
            data = bytearray(1024)
            first_lba = 1
            struct.pack_into("<I", data, 446 + 8, first_lba)
            data[510:512] = b"\x55\xaa"
            data[first_lba * 512 + 3:first_lba * 512 + 11] = b"EXFAT   "
            image.write_bytes(data)
            self.assertEqual(_exfat_partition_number(image), 1)

            completed = subprocess.CompletedProcess([], 0, "mounted", "")
            with (
                patch("utils.osfmount.sys", SimpleNamespace(platform="win32")),
                patch("utils.osfmount.find_osfmount", return_value=Path("OSFMount.com")),
                patch("utils.osfmount.is_administrator", return_value=True),
                patch("utils.osfmount._free_drive_letter", return_value="Z"),
                patch("utils.osfmount.subprocess.run", return_value=completed) as run,
                patch("pathlib.Path.is_dir", return_value=True),
            ):
                mount_exfat_image(image)
            args = run.call_args.args[0]
            self.assertEqual(args[args.index("-v") + 1], "1")

    def test_unmount_uses_the_tracked_drive_without_a_console(self):
        completed = subprocess.CompletedProcess([], 0, "unmounted", "")
        handle = MountedImage(Path("game.exfat"), "Y")
        with (
            patch("utils.osfmount.find_osfmount", return_value=Path("OSFMount.com")),
            patch("utils.osfmount.subprocess.run", return_value=completed) as run,
        ):
            unmount_exfat_image(handle)

        self.assertEqual(run.call_args.args[0], ["OSFMount.com", "-d", "-m", "Y:"])
        for key, value in hidden_child_process_kwargs().items():
            self.assertEqual(run.call_args.kwargs[key], value)

    def test_access_denied_normal_dismount_retries_with_force(self):
        normal = subprocess.CompletedProcess([], 5, "", "Z: Access is denied.")
        forced = subprocess.CompletedProcess([], 0, "Done.", "")
        handle = MountedImage(Path("game.exfat"), "Z")
        with (
            patch("utils.osfmount.find_osfmount", return_value=Path("OSFMount.com")),
            patch("utils.osfmount.subprocess.run", side_effect=[normal, forced]) as run,
        ):
            unmount_exfat_image(handle)

        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], ["OSFMount.com", "-d", "-m", "Z:"])
        self.assertEqual(run.call_args_list[1].args[0], ["OSFMount.com", "-D", "-m", "Z:"])
        for call in run.call_args_list:
            for key, value in hidden_child_process_kwargs().items():
                self.assertEqual(call.kwargs[key], value)


if __name__ == "__main__":
    unittest.main()
