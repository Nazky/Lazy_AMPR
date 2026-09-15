import json
import os
import sys
from pathlib import Path

if sys.platform == "linux":
    if os.environ.get("XDG_SESSION_TYPE") == "wayland":
        os.environ["QT_QPA_PLATFORM"] = "wayland"
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
elif sys.platform == "darwin":
    os.environ["QT_MAC_WANTS_LAYER"] = "1"

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QLabel

from gui.main_window import MainWindow
from utils.logging_utils import setup_logging
from version import APP_NAME, VERSION


def _settle_ui(milliseconds=200):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def _run_release_ui_qa(app, window, output_dir, logger):
    """Exercise and capture the packaged UI without changing normal startup."""
    report = {
        "application": APP_NAME,
        "version": VERSION,
        "title": window.windowTitle(),
        "pages": [],
        "themes": [],
        "responsive_batch": [],
        "responsive_pages": [],
    }
    output_dir = Path(output_dir)
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        expected_pages = [
            "One Shot",
            "Batch",
            "Extract",
            "Toml list",
            "Settings",
            "Credits",
        ]
        buttons = window.nav_group.buttons()
        if [button.text() for button in buttons] != expected_pages:
            raise AssertionError(
                "Navigation labels do not match the release specification"
            )
        if window.windowTitle() != f"{APP_NAME} {VERSION}":
            raise AssertionError("Application title/version is inconsistent")

        labels = [label.text() for label in window.findChildren(QLabel)]
        if "Nazky & Deckerr97" not in labels:
            raise AssertionError("Sidebar attribution is missing")
        for credit in ("Nazky", "Deckerr97", "Pippo", "drakmor"):
            if labels.count(credit) != 1:
                raise AssertionError(
                    f"Credits entry is missing or duplicated: {credit}"
                )

        window.showNormal()
        window.resize(1500, 900)
        _settle_ui()
        for index, button in enumerate(buttons):
            button.click()
            _settle_ui()
            if window.stack.currentIndex() != index:
                raise AssertionError(f"Navigation failed for {button.text()}")
            filename = f"page-{index + 1}-{button.text().lower().replace(' ', '-')}.png"
            if not window.grab().save(str(output_dir / filename)):
                raise OSError(f"Could not save {filename}")
            report["pages"].append(
                {"name": button.text(), "index": index, "capture": filename}
            )

        window.log_toggle.setChecked(True)
        _settle_ui(50)
        if not window.console.isVisible():
            raise AssertionError("Log control did not open the log interface")
        window.log_toggle.setChecked(False)

        settings_button = window.nav_group.button(4)
        settings_button.click()
        for theme in ("Light", "Dark", "Auto"):
            window._apply_theme(theme)
            _settle_ui(100)
            filename = f"theme-{theme.lower()}.png"
            if not window.grab().save(str(output_dir / filename)):
                raise OSError(f"Could not save {filename}")
            report["themes"].append({"name": theme, "capture": filename})

        from gui.game_card import GameCard

        for card in window.batch.cards.values():
            card.setParent(None)
        window.batch.cards = {}
        for number in range(10):
            title = (
                "A long game title that must not shift controls"
                if number == 3
                else f"QA Game {number + 1}"
            )
            card = GameCard(
                {"title": title, "title_id": f"PPSA{number:05d}", "version": "1.00"}
            )
            card.batch_checkbox.setChecked(number % 2 == 0)
            window.batch.cards[f"qa:{number}"] = card
        window.batch._update_state()
        window.nav_group.button(1).click()

        responsive_sizes = (
            (1500, 900, 5),
            (1280, 800, 4),
            (1050, 760, 3),
            (820, 700, 2),
            (720, 640, 1),
        )
        for width, height, expected_columns in responsive_sizes:
            window.resize(width, height)
            _settle_ui(100)
            window.batch._reflow()
            _settle_ui(50)
            actual_columns = window.batch.column_count
            if actual_columns != expected_columns:
                raise AssertionError(
                    f"Batch at {width}x{height}: expected {expected_columns} columns, got {actual_columns}"
                )
            filename = f"batch-{width}x{height}-{actual_columns}col.png"
            if not window.grab().save(str(output_dir / filename)):
                raise OSError(f"Could not save {filename}")
            report["responsive_batch"].append(
                {
                    "window": [width, height],
                    "columns": actual_columns,
                    "rows": window.batch.grid.rowCount(),
                    "capture": filename,
                }
            )

        window.resize(720, 640)
        for index, page in ((4, window.settings_page), (5, window.credits_page)):
            buttons[index].click()
            _settle_ui(100)
            if page.scroll.horizontalScrollBar().maximum() != 0:
                raise AssertionError(
                    f"{buttons[index].text()} has horizontal overflow at 720x640"
                )
            filename = f"responsive-{buttons[index].text().lower()}-720x640.png"
            if not window.grab().save(str(output_dir / filename)):
                raise OSError(f"Could not save {filename}")
            report["responsive_pages"].append(
                {
                    "name": buttons[index].text(),
                    "window": [720, 640],
                    "capture": filename,
                }
            )

        report["status"] = "passed"
        (output_dir / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        logger.info("Packaged release UI QA passed: %s", output_dir)
        window.close()
        app.exit(0)
    except Exception as error:
        report["status"] = "failed"
        report["error"] = f"{type(error).__name__}: {error}"
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / "report.json").write_text(
                json.dumps(report, indent=2), encoding="utf-8"
            )
        except OSError:
            pass
        logger.exception("Packaged release UI QA failed")
        app.exit(2)


def main():
    logger = setup_logging()
    logger.info("Starting %s %s", APP_NAME, VERSION)
    smoke_test = "--smoke-test" in sys.argv
    if smoke_test:
        sys.argv.remove("--smoke-test")
    ui_qa_prefix = "--release-ui-qa="
    ui_qa_arg = next((arg for arg in sys.argv if arg.startswith(ui_qa_prefix)), None)
    if ui_qa_arg:
        sys.argv.remove(ui_qa_arg)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")  # Consistent base rendering on all OSes
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(VERSION)

    window = MainWindow()
    window.show()
    if smoke_test:
        QTimer.singleShot(1500, app.quit)
    elif ui_qa_arg:
        output_dir = ui_qa_arg[len(ui_qa_prefix) :]
        QTimer.singleShot(
            250, lambda: _run_release_ui_qa(app, window, output_dir, logger)
        )
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
