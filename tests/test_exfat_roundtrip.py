import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path

from FATtools import Volume
from FATtools.mkfat import exfat_mkfs

from utils.exfat_utils import cleanup_exfat_temp, extract_exfat_image, is_exfat_image


class ExfatRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.work_dir = Path(tempfile.mkdtemp(prefix="lazy_ampr_exfat_test_"))

    def tearDown(self):
        shutil.rmtree(self.work_dir, ignore_errors=True)

    @unittest.skipUnless(sys.platform == "darwin", "FATtools shim only applies on macOS")
    def test_fattools_sizes_regular_image_files_on_macos(self):
        from FATtools import disk as fattools_disk

        image = self.work_dir / "regular.img"
        image.write_bytes(b"\0" * 4096)
        self.assertEqual(fattools_disk.get_size(str(image)), 4096)

    def test_shadowmount_style_raw_image_extracts(self):
        source = self.work_dir / "source"
        (source / "sce_sys").mkdir(parents=True)
        (source / "sce_sys" / "param.json").write_text(
            '{"titleId":"PPSA00001","contentId":"TEST"}', encoding="utf-8"
        )
        (source / "eboot.bin").write_bytes(b"test-eboot")
        (source / "nested").mkdir()
        (source / "nested" / "asset.bin").write_bytes(bytes(range(256)) * 32)

        image = self.work_dir / "PPSA00001.exfat"
        with image.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024)

        disk = Volume.vopen(str(image), "r+b", "disk")
        try:
            self.assertEqual(
                exfat_mkfs(
                    disk,
                    disk.size,
                    512,
                    {"wanted_cluster": 32 * 1024, "show_info": 0},
                ),
                0,
            )
        finally:
            Volume.vclose(disk)

        volume = Volume.vopen(str(image), "r+b", "volume")
        try:
            Volume.copy_in([str(path) for path in source.iterdir()], volume)
        finally:
            Volume.vclose(volume)

        self.assertTrue(is_exfat_image(image))
        messages = []
        extracted = extract_exfat_image(image, messages.append)
        self.assertIsNotNone(extracted, "\n".join(messages))
        try:
            self.assertEqual(
                (extracted / "sce_sys" / "param.json").read_bytes(),
                (source / "sce_sys" / "param.json").read_bytes(),
            )
            self.assertEqual(
                (extracted / "nested" / "asset.bin").read_bytes(),
                (source / "nested" / "asset.bin").read_bytes(),
            )
            self.assertEqual(
                (extracted / "eboot.bin").read_bytes(),
                (source / "eboot.bin").read_bytes(),
            )
        finally:
            cleanup_exfat_temp(extracted)

    def test_unrelated_bin_is_not_misidentified(self):
        unrelated = self.work_dir / "not-a-filesystem.bin"
        unrelated.write_bytes(b"not exfat")
        self.assertFalse(is_exfat_image(unrelated))

    def test_mbr_partitioned_exfat_image_extracts(self):
        raw = self.work_dir / "volume.raw"
        with raw.open("wb") as stream:
            stream.truncate(64 * 1024 * 1024)
        disk = Volume.vopen(str(raw), "r+b", "disk")
        try:
            self.assertEqual(exfat_mkfs(disk, disk.size, 512, {"show_info": 0}), 0)
        finally:
            Volume.vclose(disk)
        volume = Volume.vopen(str(raw), "r+b", "volume")
        payload = self.work_dir / "partitioned.txt"
        payload.write_text("inside MBR exFAT", encoding="utf-8")
        try:
            Volume.copy_in([str(payload)], volume)
        finally:
            Volume.vclose(volume)

        first_lba = 2048
        partitioned = self.work_dir / "partitioned.img"
        raw_size = raw.stat().st_size
        with partitioned.open("wb") as target:
            target.truncate(first_lba * 512 + raw_size)
            mbr = bytearray(512)
            struct.pack_into(
                "<B3sB3sII",
                mbr,
                446,
                0,
                b"\x00\x02\x00",
                0x07,
                b"\xff\xff\xff",
                first_lba,
                raw_size // 512,
            )
            mbr[510:512] = b"\x55\xaa"
            target.seek(0)
            target.write(mbr)
            target.seek(first_lba * 512)
            with raw.open("rb") as source:
                shutil.copyfileobj(source, target, length=8 * 1024 * 1024)

        self.assertTrue(is_exfat_image(partitioned))
        extracted = extract_exfat_image(partitioned)
        self.assertIsNotNone(extracted)
        try:
            self.assertEqual(
                (extracted / payload.name).read_text("utf-8"), "inside MBR exFAT"
            )
        finally:
            cleanup_exfat_temp(extracted)


if __name__ == "__main__":
    unittest.main()
