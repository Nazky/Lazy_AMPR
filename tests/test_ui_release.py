import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

from gui import icons
from gui.batch_page import BatchPage
from gui.credits_page import CONTRIBUTORS, ContributorCard, CreditsPage
from gui.game_card import GameCard
from gui.main_window import MainWindow
from gui.one_shot_page import OneShotPage
from gui.settings_page import SettingsPage
from gui.styles import get_stylesheet, resolve_theme
from gui.toml_page import TomlPage, TomlRow
from gui.widgets import AnimatedButton
from utils.state import DEFAULT_SETTINGS
from version import VERSION


class FakeState:
    def __init__(self, tomls=()):
        self.settings = dict(DEFAULT_SETTINGS)
        self.games = {}
        self._tomls = list(tomls)
        self.links = []

    def save(self):
        pass

    def tomls(self):
        return self._tomls

    def games_using(self, name):
        return [value for value in self.games.values() if value.get("toml") == name]

    def link_toml(self, path, name, source):
        self.links.append((path, name, source))
        self.games[path]["toml"] = name


class UiReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _batch(self, width):
        page = BatchPage()
        page.setFixedSize(width, 760)
        page.show()
        for number in range(10):
            card = GameCard(
                {
                    "title": f"Game {number}",
                    "title_id": f"PPSA{number:05d}",
                    "version": "1.00",
                }
            )
            page.cards[str(number)] = card
        page._update_state()
        self.app.processEvents()
        page._reflow()
        self.app.processEvents()
        return page

    def test_batch_reflows_five_to_one_and_centers_grid(self):
        expected = ((1600, 5), (1000, 4), (760, 3), (520, 2), (300, 1))
        for width, columns in expected:
            with self.subTest(width=width):
                page = self._batch(width)
                self.assertEqual(page.column_count, columns)
                self.assertTrue(page.grid.alignment() & Qt.AlignHCenter)
                self.assertEqual(page.host.width(), page.scroll.viewport().width())
                if columns == 5:
                    self.assertEqual(page.grid.rowCount(), 2)
                page.close()

    def test_game_card_actions_and_processing_state_keep_fixed_geometry(self):
        card = GameCard(
            {
                "title": "A very long game title that must not move the controls",
                "title_id": "PPSA00001",
                "version": "1.00",
            }
        )
        before = (
            card.sizeHint(),
            card.start_btn.sizeHint(),
            card.traces_btn.size(),
            card.cfg_btn.size(),
        )
        card.set_running_state(True)
        after = (
            card.sizeHint(),
            card.start_btn.sizeHint(),
            card.traces_btn.size(),
            card.cfg_btn.size(),
        )
        self.assertEqual(before[0], after[0])
        self.assertEqual(before[2:], after[2:])
        self.assertEqual(card.start_btn.height(), 40)
        self.assertEqual(card.traces_btn.size(), card.cfg_btn.size())
        self.assertEqual(card.traces_btn.focusPolicy(), Qt.StrongFocus)
        self.assertIsNone(card.graphicsEffect())

    def test_settings_dirty_state_and_responsive_form(self):
        page = SettingsPage(dict(DEFAULT_SETTINGS))
        self.assertFalse(page.save_btn.isEnabled())
        page.out_edit.setText("C:/output")
        self.assertTrue(page.save_btn.isEnabled())
        saved = []
        page.save_requested.connect(
            lambda value: (saved.append(value), page.mark_saved())
        )
        page.save_btn.click()
        self.app.processEvents()
        self.assertEqual(saved[-1]["output_dir"], "C:/output")
        self.assertFalse(page.save_btn.isEnabled())
        page.resize(600, 700)
        page.show()
        self.app.processEvents()
        self.assertTrue(page.processing._compact)
        self.assertTrue(page.appearance._compact)
        self.assertTrue(page.toml_path.isReadOnly())
        self.assertEqual(page.level_slider.slider.width(), 180)
        self.assertEqual(page.worker_slider.slider.width(), 180)

        page.resize(1500, 800)
        self.app.processEvents()
        self.assertFalse(page.processing._compact)
        self.assertEqual(page.level_slider.slider.width(), 240)
        self.assertEqual(page.worker_slider.slider.width(), 240)
        self.assertEqual(page.processing._rows.columnStretch(0), 0)
        self.assertEqual(
            page.level_slider.slider.width(), page.worker_slider.slider.width()
        )
        self.assertEqual(page.hardlink_cb.text(), "Use hardlinks for loose files")
        self.assertGreaterEqual(
            page.hardlink_cb.width(), page.hardlink_cb.sizeHint().width()
        )
        self.assertEqual(page.advanced_badge.label.text(), "Advanced")

    def test_settings_toml_folder_uses_system_file_manager(self):
        page = SettingsPage(dict(DEFAULT_SETTINGS))
        with patch(
            "gui.settings_page.QDesktopServices.openUrl", return_value=True
        ) as opened:
            page.open_toml_btn.click()
        self.assertEqual(opened.call_count, 1)
        self.assertTrue(opened.call_args.args[0].isLocalFile())

    def test_main_window_marks_settings_saved_only_after_persistence(self):
        with patch("gui.main_window.State", FakeState):
            window = MainWindow()
        window.settings_page.out_edit.setText("C:/saved-output")
        self.assertTrue(window.settings_page.save_btn.isEnabled())
        window.settings_page.save_btn.click()
        self.app.processEvents()
        self.assertEqual(window.state.settings["output_dir"], "C:/saved-output")
        self.assertFalse(window.settings_page.save_btn.isEnabled())
        window.close()

    def test_failed_settings_persistence_keeps_unsaved_state_visible(self):
        class FailingState(FakeState):
            def save(self):
                raise OSError("read-only settings folder")

        with patch("gui.main_window.State", FailingState):
            window = MainWindow()
        window.settings_page.out_edit.setText("C:/not-saved")
        with patch("gui.main_window.QMessageBox.critical") as message:
            window.settings_page.save_btn.click()
            self.app.processEvents()
        self.assertEqual(window.state.settings["output_dir"], "")
        self.assertTrue(window.settings_page.save_btn.isEnabled())
        message.assert_called_once()
        window.close()

    def test_credits_have_valid_clickable_github_actions(self):
        page = CreditsPage()
        self.assertEqual(len(page.cards), 4)
        self.assertEqual(
            [entry[1] for entry in CONTRIBUTORS],
            [
                "https://github.com/Nazky",
                "https://github.com/kerrdec97",
                "https://github.com/Pippo26442999",
                "https://github.com/drakmor",
            ],
        )
        self.assertTrue(all(isinstance(card, ContributorCard) for card in page.cards))
        with patch(
            "gui.credits_page.QDesktopServices.openUrl", return_value=True
        ) as opened:
            page.cards[0].link_button.click()
            page.cards[-1].external_button.click()
        self.assertEqual(opened.call_count, 2)
        self.assertTrue(
            all(call.args[0].host() == "github.com" for call in opened.call_args_list)
        )
        self.assertTrue(
            all(card.link_button.focusPolicy() == Qt.StrongFocus for card in page.cards)
        )

    def test_icons_render_at_device_pixel_ratio(self):
        icons._CACHE.clear()
        with patch("gui.icons.device_pixel_ratio", return_value=1.5):
            pixmap = icons.icon_pixmap("game", 16, "#ffffff")
        self.assertEqual(pixmap.width(), 24)
        self.assertEqual(pixmap.devicePixelRatio(), 1.5)

    def test_toml_page_has_drag_state_responsive_rows_and_real_link_action(self):
        with tempfile.TemporaryDirectory() as temporary:
            toml = Path(temporary) / ("long-profile-name-" * 10 + ".toml")
            toml.write_text("[pack]\n")
            state = FakeState([toml])
            state.games["C:/game"] = {
                "path": "C:/game",
                "title": "A Game",
                "title_id": "PPSA00001",
            }
            page = TomlPage(state)
            page._set_drag_over(True)
            self.assertTrue(page.container.property("drag"))
            page._set_drag_over(False)
            row = page.findChild(TomlRow)
            self.assertEqual(row.layout_mode_for_width(400), 2)
            row._reflow(row.layout_mode_for_width(400))
            with patch(
                "gui.toml_page.QInputDialog.getItem",
                return_value=("A Game  ·  PPSA00001", True),
            ):
                page._link_game(toml)
            self.assertEqual(state.links, [("C:/game", toml.name, "manual")])

    def test_navigation_credits_attribution_version_and_themes(self):
        with patch("gui.main_window.State", FakeState):
            window = MainWindow()
        labels = [button.text() for button in window.nav_group.buttons()]
        self.assertEqual(
            labels, ["One Shot", "Batch", "Extract", "Toml list", "Settings", "Credits"]
        )
        self.assertEqual(window.windowTitle(), "Lazy_AMPR 0.0.1")
        self.assertEqual(VERSION, "0.0.1")
        side_text = [label.text() for label in window.findChildren(QLabel)]
        self.assertIn("Nazky & Deckerr97", side_text)
        for name in ("Nazky", "Deckerr97", "Pippo", "drakmor"):
            self.assertEqual(side_text.count(name), 1)
        for theme in ("Light", "Dark", "Auto"):
            self.assertTrue(get_stylesheet(theme))
            self.assertIn(resolve_theme(theme), {"light", "dark"})
        window.close()

    def test_shared_buttons_retain_keyboard_focus(self):
        for kind in ("primary", "secondary", "icon", "nav", "link"):
            self.assertEqual(
                AnimatedButton("Action", kind, "play").focusPolicy(), Qt.StrongFocus
            )

    def test_one_shot_compacts_information_and_configuration(self):
        page = OneShotPage()
        page.setFixedSize(436, 700)
        page.show()
        self.app.processEvents()
        self.assertTrue(page._info_compact)
        self.assertTrue(page.cfg._compact)
        for index, (label, value) in enumerate(page.field_labels):
            label_row, label_col, _, label_span = page.info_grid.getItemPosition(
                page.info_grid.indexOf(label)
            )
            value_row, value_col, _, value_span = page.info_grid.getItemPosition(
                page.info_grid.indexOf(value)
            )
            self.assertEqual((label_row, label_col, label_span), (index * 2 + 1, 0, 2))
            self.assertEqual((value_row, value_col, value_span), (index * 2 + 2, 0, 2))
        page.close()


if __name__ == "__main__":
    unittest.main()
