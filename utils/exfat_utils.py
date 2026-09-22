"""exFAT image detection and extraction using FATtools."""

import logging
import os
import shutil
import struct
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)
_EXFAT_OEM_NAME = b"EXFAT   "


def _patch_fattools_macos_file_size() -> None:
    """Make FATtools open regular image files on macOS.

    FATtools 1.1.x sizes every non-Windows path with the DKIOCGETBLOCKCOUNT
    ioctl on macOS. That only works for block devices; for a plain image file
    the ioctl fails with ENOTTY before the volume is opened. Fall back to the
    file size for regular files and keep the original behaviour for devices.
    """
    if sys.platform != "darwin":
        return
    try:
        from FATtools import disk as fattools_disk
    except ImportError:
        return
    original = getattr(fattools_disk, "get_size", None)
    if original is None or getattr(original, "_lazy_ampr_patched", False):
        return

    def get_size(name):
        if os.path.isfile(name):
            return os.path.getsize(name)
        return original(name)

    get_size._lazy_ampr_patched = True
    fattools_disk.get_size = get_size


_patch_fattools_macos_file_size()


def _has_exfat_boot_sector(file_path: Path, offset: int = 0) -> bool:
    try:
        with file_path.open("rb") as image:
            image.seek(offset)
            sector = image.read(512)
        return len(sector) >= 11 and sector[3:11] == _EXFAT_OEM_NAME
    except (OSError, ValueError):
        return False


def is_exfat_image(file_path: Path) -> bool:
    """Return whether *file_path* is, or is intended to be, an exFAT image."""
    file_path = Path(file_path)
    if not file_path.is_file():
        return False

    # ShadowMountPlus uses the explicit .exfat extension for raw images. Keep
    # accepting that extension so a damaged image reaches the extractor and
    # produces a useful validation error instead of being silently ignored.
    if file_path.suffix.casefold() == ".exfat":
        return True

    if _has_exfat_boot_sector(file_path):
        return True

    # Also recognise a conventional MBR-partitioned exFAT disk image.
    try:
        with file_path.open("rb") as image:
            mbr = image.read(512)
        if len(mbr) != 512 or mbr[510:512] != b"\x55\xaa":
            return False
        for index in range(4):
            entry = 446 + index * 16
            first_lba = struct.unpack_from("<I", mbr, entry + 8)[0]
            if first_lba and _has_exfat_boot_sector(file_path, first_lba * 512):
                return True
    except (OSError, struct.error):
        return False

    return False


def extract_exfat_image(
    img_path: Path,
    progress_callback: Callable[[str], None] | None = None,
) -> Path | None:
    """Extract an exFAT image into a temporary directory.

    FATtools ``Volume.vopen`` returns the root ``Dirtable`` directly. The old
    implementation treated ``Volume`` as a class and attempted raw cluster
    reads, so it failed before copying the first file.
    """
    img_path = Path(img_path).resolve()
    temp_dir: Path | None = None
    volume = None

    def report(message: str) -> None:
        if progress_callback:
            progress_callback(message)

    try:
        from FATtools import Volume

        if not img_path.is_file():
            raise FileNotFoundError(f"exFAT image not found: {img_path}")

        report(f"Opening exFAT image: {img_path.name}")
        volume = Volume.vopen(str(img_path), "rb", "volume")
        if (
            isinstance(volume, str)
            or not hasattr(volume, "fat")
            or not getattr(volume.fat, "exfat", False)
        ):
            raise ValueError("The selected file does not contain a valid exFAT filesystem.")

        temp_dir = Path(tempfile.mkdtemp(prefix="lazy_ampr_exfat_"))

        file_count = sum(len(files) for _, _, files in volume.walk())
        if file_count == 0:
            raise ValueError("The exFAT image contains no files.")

        copied = 0
        last_percent = -1

        def on_copy(output_path: str) -> None:
            nonlocal copied, last_percent
            copied += 1
            percent = min(100, int(copied * 100 / file_count))
            if percent != last_percent:
                report(f"Extracting {Path(output_path).name}... ({percent}%)")
                last_percent = percent

        Volume.copy_tree_out(
            volume,
            str(temp_dir),
            callback=on_copy,
            chunk_size=8 * 1024 * 1024,
        )
        report(f"Extracted {copied} file(s) from {img_path.name}")
        return temp_dir
    except ImportError:
        message = "FATtools is not installed; reinstall Lazy_AMPR."
        logger.exception(message)
        report(message)
    except Exception as exc:
        message = f"Could not extract {img_path.name}: {exc}"
        logger.exception(message)
        report(message)
    finally:
        if volume is not None and not isinstance(volume, str):
            try:
                from FATtools import Volume

                Volume.vclose(volume)
            except BaseException:
                logger.debug("FATtools volume close failed", exc_info=True)

    if temp_dir is not None:
        cleanup_exfat_temp(temp_dir)
    return None


def cleanup_exfat_temp(temp_dir: Path | None) -> None:
    """Remove a temporary exFAT extraction directory."""
    if temp_dir and Path(temp_dir).exists():
        try:
            shutil.rmtree(Path(temp_dir))
            logger.info("Cleaned up temporary directory %s", temp_dir)
        except OSError:
            logger.warning("Failed to clean up %s", temp_dir, exc_info=True)
