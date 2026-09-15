import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import cross_platform, osfmount, tool_runner


class CrossPlatformTests(unittest.TestCase):
    def test_xdg_config_location_is_used_on_linux(self):
        with (
            patch.object(cross_platform.sys, "platform", "linux"),
            patch.dict(os.environ, {"XDG_CONFIG_HOME": "/tmp/lazy-ampr-xdg"}),
        ):
            result = cross_platform.get_app_data_dir()
        self.assertEqual(result.parts[-2:], ("lazy-ampr-xdg", "lazy_ampr"))

    def test_frozen_worker_uses_platform_executable_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary)
            script = app / "ampr_pack.py"
            linux_worker = app / "workers" / "ampr_pack" / "ampr_pack"
            windows_worker = linux_worker.with_suffix(".exe")
            linux_worker.parent.mkdir(parents=True)
            linux_worker.touch()
            windows_worker.touch()

            with (
                patch.object(tool_runner.sys, "frozen", True, create=True),
                patch.object(tool_runner.sys, "executable", str(app / "Lazy_AMPR")),
                patch.object(tool_runner.sys, "platform", "linux"),
            ):
                self.assertEqual(tool_runner.command_for(script), [str(linux_worker)])

            with (
                patch.object(tool_runner.sys, "frozen", True, create=True),
                patch.object(tool_runner.sys, "executable", str(app / "Lazy_AMPR.exe")),
                patch.object(tool_runner.sys, "platform", "win32"),
            ):
                self.assertEqual(tool_runner.command_for(script), [str(windows_worker)])

    def test_non_windows_exfat_mount_reports_supported_workflow(self):
        with (
            tempfile.NamedTemporaryFile(suffix=".exfat") as image,
            patch.object(osfmount.sys, "platform", "linux"),
            self.assertRaisesRegex(
                OSError, "already mounted or extracted PS5 game folder"
            ),
        ):
            osfmount.mount_exfat_image(Path(image.name))

    def test_source_worker_uses_current_python_on_every_platform(self):
        script = Path("tools") / "ampr_pack.py"
        with patch.object(tool_runner.sys, "frozen", False, create=True):
            self.assertEqual(
                tool_runner.command_for(script), [sys.executable, str(script)]
            )


if __name__ == "__main__":
    unittest.main()
