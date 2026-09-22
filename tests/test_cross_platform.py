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

    def test_darwin_app_data_dir_uses_application_support(self):
        with (
            patch.object(cross_platform.sys, "platform", "darwin"),
            patch.object(cross_platform.Path, "home", return_value=Path("/Users/tester")),
        ):
            result = cross_platform.get_app_data_dir()
        self.assertEqual(
            result.parts[-3:], ("Library", "Application Support", "Lazy_AMPR")
        )

    def test_image_mounting_is_only_supported_on_windows(self):
        with patch.object(osfmount.sys, "platform", "win32"):
            self.assertTrue(osfmount.supports_image_mounting())
        for platform in ("darwin", "linux"):
            with patch.object(osfmount.sys, "platform", platform):
                self.assertFalse(osfmount.supports_image_mounting(), platform)

    @unittest.skipIf(sys.platform == "win32", "symlink creation needs privileges on Windows")
    def test_frozen_worker_resolves_inside_macos_app_bundle(self):
        # Contract with build_macos.sh: workers live under Contents/Resources and
        # are reached through the Contents/MacOS/workers symlink.
        with tempfile.TemporaryDirectory() as temporary:
            contents = Path(temporary).resolve() / "Lazy_AMPR.app" / "Contents"
            executable = contents / "MacOS" / "Lazy_AMPR"
            worker = contents / "Resources" / "workers" / "ampr_pack" / "ampr_pack"
            executable.parent.mkdir(parents=True)
            executable.touch()
            worker.parent.mkdir(parents=True)
            worker.touch()
            os.symlink(Path("..") / "Resources" / "workers", contents / "MacOS" / "workers")

            with (
                patch.object(tool_runner.sys, "frozen", True, create=True),
                patch.object(tool_runner.sys, "executable", str(executable)),
                patch.object(tool_runner.sys, "platform", "darwin"),
            ):
                self.assertEqual(
                    tool_runner.command_for(Path("ampr_pack.py")),
                    [str(contents / "MacOS" / "workers" / "ampr_pack" / "ampr_pack")],
                )

    def test_frozen_worker_uses_platform_executable_suffix(self):
        with tempfile.TemporaryDirectory() as temporary:
            app = Path(temporary).resolve()
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
        for platform in ("linux", "darwin"):
            with (
                self.subTest(platform=platform),
                tempfile.NamedTemporaryFile(suffix=".exfat") as image,
                patch.object(osfmount.sys, "platform", platform),
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
