"""Read-only OSFMount integration for ShadowMountPlus exFAT images."""

import ctypes
import shutil
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from utils.subprocess_utils import hidden_child_process_kwargs

OSFMOUNT_LOCATIONS = (
    Path(r"C:\Program Files\OSFMount\OSFMount.com"),
    Path(r"C:\Program Files (x86)\OSFMount\OSFMount.com"),
)
_EXFAT_OEM_NAME = b"EXFAT   "


@dataclass(frozen=True)
class MountedImage:
    image_path: Path
    drive_letter: str

    @property
    def root(self) -> Path:
        return Path(f"{self.drive_letter}:\\")


def supports_image_mounting() -> bool:
    """Direct exFAT image mounting is implemented with OSFMount, which is Windows-only."""
    return sys.platform == "win32"


def find_osfmount() -> Path | None:
    if sys.platform != "win32":
        return None
    found = shutil.which("OSFMount.com")
    if found:
        return Path(found)
    return next((path for path in OSFMOUNT_LOCATIONS if path.is_file()), None)


def is_administrator() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _used_drive_letters() -> set[str]:
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    return {chr(ord("A") + index) for index in range(26) if mask & (1 << index)}


def _free_drive_letter() -> str:
    used = _used_drive_letters()
    for letter in reversed("DEFGHIJKLMNOPQRSTUVWXYZ"):
        if letter not in used:
            return letter
    raise RuntimeError("No free drive letter is available for the exFAT image.")


def _exfat_partition_number(image_path: Path) -> int | None:
    """Return the 1-based MBR exFAT partition number, or None for a raw volume."""
    with image_path.open("rb") as image:
        first_sector = image.read(512)
        if len(first_sector) >= 11 and first_sector[3:11] == _EXFAT_OEM_NAME:
            return None
        if len(first_sector) != 512 or first_sector[510:512] != b"\x55\xaa":
            return None
        for index in range(4):
            entry = 446 + index * 16
            first_lba = struct.unpack_from("<I", first_sector, entry + 8)[0]
            if not first_lba:
                continue
            image.seek(first_lba * 512 + 3)
            if image.read(8) == _EXFAT_OEM_NAME:
                return index + 1
    return None


def mount_exfat_image(
    image_path: Path,
    progress_callback: Callable[[str], None] | None = None,
) -> MountedImage:
    image_path = Path(image_path).resolve()
    if not image_path.is_file():
        raise FileNotFoundError(f"exFAT image not found: {image_path}")
    if sys.platform != "win32":
        raise OSError(
            "Direct exFAT image mounting requires OSFMount on Windows. "
            "On this platform, select an already mounted or extracted PS5 game folder."
        )
    tool = find_osfmount()
    if tool is None:
        raise FileNotFoundError(
            "OSFMount was not found. Install OSFMount 3 from PassMark and try again."
        )
    if not is_administrator():
        raise PermissionError(
            "OSFMount requires administrator privileges. Restart Lazy_AMPR as administrator."
        )

    drive = _free_drive_letter()
    mount_point = f"{drive}:"
    args = [
        str(tool),
        "-a",
        "-t",
        "file",
        "-f",
        str(image_path),
        "-m",
        mount_point,
        "-o",
        "ro,logical",
    ]
    partition = _exfat_partition_number(image_path)
    if partition is not None:
        args.extend(["-v", str(partition)])

    if progress_callback:
        progress_callback(f"Mounting {image_path.name} read-only as {mount_point}…")
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **hidden_child_process_kwargs(),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()
        raise RuntimeError(
            detail or f"OSFMount failed with exit code {completed.returncode}."
        )

    handle = MountedImage(image_path, drive)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if handle.root.is_dir():
            if progress_callback:
                progress_callback(f"Mounted read-only at {handle.root}")
            return handle
        time.sleep(0.2)

    # Avoid leaving an untracked mount if Windows did not publish the drive.
    subprocess.run(
        [str(tool), "-d", "-m", mount_point],
        capture_output=True,
        check=False,
        **hidden_child_process_kwargs(),
    )
    raise RuntimeError(
        f"OSFMount did not make {mount_point} available within 10 seconds."
    )


def unmount_exfat_image(handle: MountedImage) -> None:
    tool = find_osfmount()
    if tool is None:
        raise FileNotFoundError(
            "OSFMount is no longer available, so the image cannot be unmounted."
        )
    normal = subprocess.run(
        [str(tool), "-d", "-m", f"{handle.drive_letter}:"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **hidden_child_process_kwargs(),
    )
    if normal.returncode == 0:
        return

    # Normal dismount requires an exclusive volume lock. OSFMount documents -D
    # for a volume that cannot be dismounted normally after processing ends.
    forced = subprocess.run(
        [str(tool), "-D", "-m", f"{handle.drive_letter}:"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        **hidden_child_process_kwargs(),
    )
    if forced.returncode != 0:
        normal_detail = (normal.stderr or normal.stdout).strip()
        forced_detail = (forced.stderr or forced.stdout).strip()
        detail = forced_detail or normal_detail
        raise RuntimeError(detail or f"Could not unmount {handle.drive_letter}:.")
