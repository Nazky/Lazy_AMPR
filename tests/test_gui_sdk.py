import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gui.batch_page import BatchPage
from gui.game_card import GameCard
from gui.one_shot_page import OneShotPage
from gui.settings_page import SettingsPage
from utils.osfmount import MountedImage


class BatchSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_game_card_selection_is_explicit(self):
        card = GameCard({"title": "Test", "title_id": "PPSA00001", "version": "1.00"})
        selected = []
        card.selection_changed.connect(selected.append)
        self.assertFalse(card.selected_for_batch)
        card.batch_checkbox.setChecked(True)
        self.assertTrue(card.selected_for_batch)
        self.assertEqual(selected, [True])

    def test_batch_start_requires_a_selected_card(self):
        page = BatchPage()
        card = GameCard({"title": "Test", "title_id": "PPSA00001", "version": "1.00"})
        page.cards["test"] = card
        card.selection_changed.connect(page._selection_changed)
        requested = []
        page.start_all_requested.connect(lambda: requested.append(True))
        self.assertFalse(page.start_btn.isEnabled())
        card.batch_checkbox.setChecked(True)
        self.assertTrue(page.start_btn.isEnabled())
        page.start_btn.click()
        self.app.processEvents()
        self.assertEqual(requested, [True])

    def test_selected_cards_excludes_unticked_games(self):
        page = BatchPage()
        first = GameCard({"title": "First", "title_id": "PPSA00001", "version": "1.00"})
        second = GameCard({"title": "Second", "title_id": "PPSA00002", "version": "1.00"})
        page.cards.update({"first": first, "second": second})
        second.batch_checkbox.setChecked(True)
        self.assertEqual(page.selected_cards(), [("second", second)])

    def test_backport_controls_are_not_exposed(self):
        one_shot = OneShotPage()
        settings = SettingsPage({})
        self.assertFalse(hasattr(one_shot, "backport_cb"))
        self.assertFalse(hasattr(one_shot, "sdk_combo"))
        self.assertFalse(hasattr(one_shot, "fl_btn"))
        self.assertFalse(hasattr(settings, "backport_cb"))
        self.assertFalse(hasattr(settings, "fl_edit"))

    def test_one_shot_mounts_exfat_instead_of_extracting_it(self):
        page = OneShotPage()
        with tempfile.TemporaryDirectory() as temporary:
            image = Path(temporary) / "PPSA01467.exfat"
            image.write_bytes(b"image")
            mounted = MountedImage(image, "Z")
            game = Path(r"Z:\PPSA01467")
            with (
                patch("gui.one_shot_page.mount_exfat_image", return_value=mounted) as mount,
                patch("gui.one_shot_page.detect_games", return_value=[game]),
                patch.object(page, "set_folder") as set_folder,
            ):
                self.assertTrue(page._handle_exfat_image(image))

            mount.assert_called_once()
            set_folder.assert_called_once_with(game)
            self.assertEqual(page.input_path, image)
            self.assertEqual(page.mounted_image, mounted)

    def test_one_shot_cleanup_unmounts_the_tracked_image(self):
        page = OneShotPage()
        mounted = MountedImage(Path("PPSA01467.exfat"), "Z")
        page.mounted_image = mounted
        page.game_dir = Path(r"Z:\PPSA01467")
        with patch("gui.one_shot_page.unmount_exfat_image") as unmount:
            self.assertTrue(page.cleanup_mounted_image())
        unmount.assert_called_once_with(mounted)
        self.assertIsNone(page.mounted_image)
        self.assertFalse(page.start_btn.isEnabled())


if __name__ == "__main__":
    unittest.main()
