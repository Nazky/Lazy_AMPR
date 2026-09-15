import logging
import time
from pathlib import Path

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.batch_page import BatchPage
from gui.credits_page import CreditsPage
from gui.extract_page import ExtractPage
from gui.one_shot_page import OneShotPage
from gui.settings_page import SettingsPage
from gui.styles import apply_theme
from gui.toml_page import TomlPage
from gui.widgets import AnimatedButton, StatusBadge
from utils.cross_platform import normalize_path
from utils.process_manager import ExtractWorker, GameWorker, ProfileWorker
from utils.state import TOML_DIR, State
from version import APP_NAME, VERSION


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {VERSION}")
        self.resize(1500, 900)
        self.setMinimumSize(720, 640)
        self.setAcceptDrops(True)
        self.state = State()
        self.settings = self.state.settings
        self.workers = {}
        self.prof_workers = {}
        self._batch_queue = []
        self._batch_active = None
        self._closing = False

        self._init_ui()

        # Seed the One Shot page from saved settings (no duplicate page instance!)
        self.one_shot.level_slider.set_value(int(self.settings.get("lz4_level", 9)))
        skip_val = bool(self.settings.get("skip_lz4_verification", False))
        self.one_shot.skip_lz4_verification = skip_val
        if hasattr(self.one_shot, "skip_verify_cb"):
            self.one_shot.skip_verify_cb.setChecked(skip_val)

        self._apply_theme(self.settings.get("theme", "Auto"))
        try:
            self.styleHints().colorSchemeChanged.connect(
                lambda _: self._apply_theme(self.settings.get("theme"))
            )
        except (AttributeError, RuntimeError):
            pass
        self._restore_games()

    # ------------------------------------------------------------------ UI
    def _init_ui(self):
        central = QWidget()
        central.setObjectName("ContentBG")
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.setCentralWidget(central)

        # ---- Sidebar ----
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)
        sb = QVBoxLayout(sidebar)
        sb.setContentsMargins(14, 22, 14, 14)
        sb.setSpacing(4)
        brand = QLabel("Lazy AMPR")
        brand.setObjectName("Brand")
        brand.setAlignment(Qt.AlignCenter)
        sb.addWidget(brand)
        sb.addSpacing(16)

        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        for i, (txt, ico) in enumerate(
            [
                ("One Shot", "target"),
                ("Batch", "grid"),
                ("Extract", "download"),
                ("Toml list", "doc"),
                ("Settings", "gear"),
                ("Credits", "users"),
            ]
        ):
            b = AnimatedButton(txt, "nav", icon=ico)
            b.setCheckable(True)
            self.nav_group.addButton(b, i)
            sb.addWidget(b)
        self.nav_group.button(0).setChecked(True)
        sb.addStretch(1)

        self.log_toggle = AnimatedButton("Log", "nav", icon="log")
        self.log_toggle.setCheckable(True)
        self.log_toggle.toggled.connect(self._toggle_console)
        sb.addWidget(self.log_toggle)

        foot = QLabel("Nazky & Deckerr97")
        foot.setObjectName("SideFoot")
        foot.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        sb.addWidget(foot)
        root.addWidget(sidebar)

        # ---- Content ----
        content = QWidget()
        content.setObjectName("ContentBG")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(32, 28, 32, 20)
        cl.setSpacing(14)

        self.stack = QStackedWidget()
        self.nav_group.idClicked.connect(self._page)

        self.one_shot = OneShotPage()
        self.one_shot.start_requested.connect(self._start_one_shot)
        self.one_shot.cancel_requested.connect(
            lambda: self._cancel(self.one_shot.game_dir)
        )
        self.one_shot.folder_set.connect(self._on_folder_set)
        self.one_shot.traces_imported.connect(
            lambda p: self._gen_profile(
                self.one_shot.game_dir,
                None,
                p,
                getattr(self.one_shot, "game_info", None),
                state_path=self.one_shot.input_path,
            )
        )
        self.stack.addWidget(self.one_shot)

        self.batch = BatchPage()
        self.batch.game_added.connect(self._wire_card)
        self.batch.start_all_requested.connect(self._start_all)
        self.stack.addWidget(self.batch)

        self.extract = ExtractPage()
        self.extract.start_requested.connect(self._start_extract)
        self.extract.folder_set.connect(lambda p: self.log(f"📦 Extract source: {p}"))
        self.stack.addWidget(self.extract)

        self.toml_page = TomlPage(self.state)
        self.toml_page.changed.connect(self._on_toml_list_changed)
        self.stack.addWidget(self.toml_page)

        self.settings_page = SettingsPage(self.state)
        self.settings_page.theme_preview.connect(self._apply_theme)
        self.settings_page.save_requested.connect(self._on_save)
        self.stack.addWidget(self.settings_page)

        self.credits_page = CreditsPage()
        self.stack.addWidget(self.credits_page)

        cl.addWidget(self.stack, 1)

        self.console = QPlainTextEdit()
        self.console.setObjectName("Console")
        self.console.setReadOnly(True)
        self.console.setFixedHeight(150)
        self.console.setVisible(False)
        cl.addWidget(self.console)
        root.addWidget(content, 1)

    # ------------------------------------------------------------- pages/theme
    def _page(self, i):
        w = self.stack.widget(i)
        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
        a = QPropertyAnimation(eff, b"opacity", self)
        a.setDuration(150)
        a.setStartValue(0.0)
        a.setEndValue(1.0)
        a.finished.connect(lambda: w.setGraphicsEffect(None))
        self.stack.setCurrentIndex(i)
        a.start()
        if i == 3:
            self.toml_page.refresh()

    def _apply_theme(self, name):
        apply_theme(QApplication.instance(), name)
        from gui.widgets import CenteredComboBox, SegmentedControl

        for cb in self.findChildren(CenteredComboBox):
            cb._style_popup()
            cb.update()
        for selector in self.findChildren(SegmentedControl):
            selector.refresh_theme()
        for badge in self.findChildren(StatusBadge):
            badge.refresh_theme()
        self.one_shot.refresh_theme_icons()
        self.extract.refresh_theme_icons()
        self.credits_page.refresh_theme()

    def _on_save(self, new):
        previous = dict(self.state.settings)
        try:
            self.state.settings = dict(new)
            self.state.save()
        except Exception as error:
            self.state.settings = previous
            self.settings = self.state.settings
            logging.getLogger("lazy_ampr.ui").exception("Could not save settings")
            QMessageBox.critical(
                self,
                "Could not save settings",
                f"Lazy_AMPR could not save your settings:\n{error}",
            )
            return
        self.settings = self.state.settings

        skip_val = bool(new.get("skip_lz4_verification", False))
        self.one_shot.skip_lz4_verification = skip_val
        if hasattr(self.one_shot, "skip_verify_cb"):
            self.one_shot.skip_verify_cb.setChecked(skip_val)
        self.one_shot.level_slider.set_value(int(new.get("lz4_level", 9)))

        self._apply_theme(new.get("theme", "Auto"))
        self.settings_page.mark_saved()

    def _on_toml_list_changed(self):
        self._relink_all()
        self.toml_page.refresh()

    def _toggle_console(self, on):
        self.console.setVisible(on)

    def log(self, line):
        self.console.appendPlainText(line)
        logging.getLogger("lazy_ampr.ui").info("%s", line)

    # ------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e: QDropEvent):
        paths = [
            normalize_path(u.toLocalFile())
            for u in e.mimeData().urls()
            if u.isLocalFile()
        ]
        dirs = [path for path in paths if path.is_dir()]
        idx = self.stack.currentIndex()
        if idx == 3:
            return  # toml page handles its own drops
        if idx == 0:
            for path in paths:
                if self.one_shot.load_input(path):
                    e.acceptProposedAction()
                    return
        elif idx == 2 and dirs:
            self.extract.set_folder(dirs[0])
        elif idx == 1 and dirs:
            self.batch.add_paths(dirs)

    # ------------------------------------------------------- state / linking
    def _restore_games(self):
        for path_str in list(self.state.games.keys()):
            p = Path(path_str)
            if p.is_dir():
                self.batch.add_game(p)

    def _relink_all(self):
        for path_str, entry in list(self.state.games.items()):
            p = Path(path_str)
            if not p.exists():
                continue
            card = self.batch.cards.get(path_str)
            self._auto_link(p, entry, card)

    def _auto_link(self, path, info, card=None):
        entry = self.state.upsert_game(
            path,
            title=info.get("title"),
            title_id=info.get("title_id"),
            content_id=info.get("content_id"),
        )
        if entry.get("toml_src") != "manual":
            name = entry.get("toml")
            if not (name and (TOML_DIR / name).exists()):
                name = self.state.auto_toml_for(
                    info.get("title_id", ""), info.get("title", "")
                )
            if name:
                self.state.link_toml(path, name, "auto")
                if card is not None:
                    card.custom_config_path = TOML_DIR / name
                    card.toml_name, card.toml_auto = name, True
                return name
        elif entry.get("toml"):
            if card is not None:
                card.custom_config_path = TOML_DIR / entry["toml"]
                card.toml_name, card.toml_auto = entry["toml"], False
        return None

    def _on_folder_set(self, path, info):
        state_path = self.one_shot.input_path or path
        entry = self.state.upsert_game(
            state_path,
            title=info.get("title"),
            title_id=info.get("title_id"),
            content_id=info.get("content_id"),
        )
        self.one_shot.game_info = info
        if entry.get("traces"):
            self.one_shot.traces_dir = Path(entry["traces"])
        name = self._auto_link(state_path, info, None)
        if name:
            self.one_shot.custom_config_path = TOML_DIR / name
            self.one_shot.apply_link(name, True)
        traces = self.one_shot.traces_dir or (
            Path(path) / "traces" if (Path(path) / "traces").is_dir() else None
        )
        if traces and not self.one_shot.custom_config_path:
            self._gen_profile(path, None, traces, info, state_path=state_path)

    def _gen_profile(self, path, card, traces_dir, info=None, state_path=None):
        key = str(path)
        if not traces_dir or key in self.prof_workers:
            return
        info = info or (card.game_info if card else None)
        if not info:
            return
        w = ProfileWorker(
            traces_dir, TOML_DIR, info.get("title_id", ""), info.get("title", "")
        )
        w.profile_finished.connect(
            lambda ok, name, msg, p=path, c=card, sp=state_path: self._profile_done(
                p, c, ok, name, msg, state_path=sp
            )
        )
        self.prof_workers[key] = w
        self.log(f"⚙ Auto-generating TOML from traces for {Path(path).name}…")
        w.start()

    def _profile_done(self, path, card, ok, name, msg, state_path=None):
        self.prof_workers.pop(str(path), None)
        self.log(("✅ " if ok else "⚠️ ") + msg)
        if not ok:
            return
        self.state.link_toml(state_path or path, name, "auto")
        if card is not None:
            card.custom_config_path = TOML_DIR / name
            card.toml_name, card.toml_auto = name, True
        if self.one_shot.game_dir and str(self.one_shot.game_dir) == str(path):
            self.one_shot.custom_config_path = TOML_DIR / name
            self.one_shot.apply_link(name, True)
        self.toml_page.refresh()

    # ------------------------------------------------------------- processing
    def _wire_card(self, game_dir, card):
        info = card.game_info
        entry = self.state.upsert_game(
            game_dir,
            title=info.get("title"),
            title_id=info.get("title_id"),
            content_id=info.get("content_id"),
        )
        if entry.get("traces"):
            card.traces_dir = Path(entry["traces"])
        self._auto_link(game_dir, info, card)
        if not card.custom_config_path:
            tr = card.traces_dir or (
                game_dir / "traces" if (game_dir / "traces").is_dir() else None
            )
            if tr:
                self._gen_profile(game_dir, card, tr, info)
        card.start_requested.connect(
            lambda d=game_dir, c=card: self._launch(d, c, card=c)
        )
        if hasattr(card, "cancel_requested"):
            card.cancel_requested.connect(lambda d=game_dir: self._cancel(Path(d)))

    def _launch(self, game_dir, sink, page=None, card=None):
        key = str(game_dir)
        if key in self.workers and self.workers[key].isRunning():
            return
        if card is not None:
            cfg, traces = card.custom_config_path, card.traces_dir
            level = self.settings.get("lz4_level", 9)
            skip_verify = self.settings.get("skip_lz4_verification", False)
        else:
            cfg, traces = page.custom_config_path, page.traces_dir
            level = page.lz4_level or self.settings.get("lz4_level", 9)
            skip_verify = getattr(
                page,
                "skip_lz4_verification",
                self.settings.get("skip_lz4_verification", False),
            )

        if cfg and isinstance(cfg, str):
            cfg = Path(cfg)
        if traces and isinstance(traces, str):
            traces = Path(traces)

        workers = self.settings.get("workers")
        out = self.settings.get("output_dir", "").strip()
        original_input = getattr(page, "input_path", None) if page is not None else None
        if original_input and Path(original_input).is_file():
            original_input = Path(original_input)
            output = (
                Path(out) / original_input.stem
                if out
                else original_input.parent / f"{original_input.stem}_AMPR"
            )
        else:
            output = (
                Path(out) / game_dir.name
                if out
                else game_dir.parent / f"{game_dir.name}_AMPR"
            )
        source_read_only = bool(page is not None and page.mounted_image is not None)

        w = GameWorker(
            game_dir,
            output,
            self.settings,
            custom_config=cfg,
            traces_dir=traces,
            lz4_level=level,
            skip_verify=skip_verify,
            workers=workers,
            source_read_only=source_read_only,
            parent=self,
        )
        w.finished.connect(w.deleteLater)
        w.finished.connect(lambda s=sink: s.set_running_state(False))
        if page is not None and source_read_only:
            w.finished.connect(page.cleanup_mounted_image)
        w.progress_updated.connect(sink.set_progress)
        w.status_updated.connect(sink.set_status)
        if hasattr(sink, "set_eta"):
            w.eta_updated.connect(sink.set_eta)
        w.log_updated.connect(self.log)
        w.pipeline_finished.connect(
            lambda ok, msg, s=sink, k=key: self._on_finished(k, s, ok, msg)
        )
        self.workers[key] = w
        sink.set_running_state(True)
        sink.set_status("Queued…")
        sink.set_progress(0)
        w.start()

    def _start_extract(self):
        src = self.extract.source_dir
        if not src:
            return
        out = self.extract.output_dir or src.parent / f"{src.name}_EXTRACTED"
        key = "extract:" + str(src)
        if key in self.workers and self.workers[key].isRunning():
            return
        w = ExtractWorker(src, out, parent=self)
        w.finished.connect(w.deleteLater)
        w.finished.connect(lambda s=self.extract: s.set_running_state(False))
        w.progress_updated.connect(self.extract.set_progress)
        w.status_updated.connect(self.extract.set_status)
        w.log_updated.connect(self.log)
        w.finished.connect(
            lambda ok, msg, s=self.extract, k=key: self._on_finished(k, s, ok, msg)
        )
        self.workers[key] = w
        self.extract.set_running_state(True)
        self.extract.set_status("Queued…")
        self.extract.set_progress(0)
        w.start()

    def _cancel(self, game_dir):
        key = str(game_dir)
        w = self.workers.get(key)
        if w and w.isRunning():
            self.log(f"⏹ Cancelling {Path(key).name}…")
            w.cancel()

    def _start_one_shot(self):
        if self.one_shot.game_dir:
            self._launch(self.one_shot.game_dir, self.one_shot, page=self.one_shot)

    def _start_all(self):
        self._batch_queue = [
            (key, card)
            for key, card in self.batch.selected_cards()
            if key not in self.workers or not self.workers[key].isRunning()
        ]
        self._launch_next_batch()

    def _launch_next_batch(self):
        if self._closing or self._batch_active is not None or not self._batch_queue:
            return
        key, card = self._batch_queue.pop(0)
        self._batch_active = key
        self._launch(Path(key), card, card=card)

    def _on_finished(self, key, sink, ok, msg):
        cancelled = (not ok) and ("cancel" in msg.lower())
        sink.set_running_state(False)
        if hasattr(sink, "set_eta"):
            sink.set_eta("Done" if ok else ("Cancelled" if cancelled else ""))
        if ok:
            sink.set_progress(100)
            sink.set_status("Completed")
            self.log(f"[OK] {key}: {msg}")
        elif cancelled:
            sink.set_progress(0)
            sink.set_status("Cancelled")
            self.log(f"[CANCELLED] {key}")
        else:
            sink.set_error(msg)
            self.log(f"[ERROR] {Path(key).name}:\n{msg}\n")
            if not self.console.isVisible():
                self.log_toggle.setChecked(True)

        self.workers.pop(key, None)
        if key == self._batch_active:
            self._batch_active = None
            QTimer.singleShot(0, self._launch_next_batch)

    def closeEvent(self, event):
        active = [w for w in self.workers.values() if w.isRunning()]
        profiles = [w for w in self.prof_workers.values() if w.isRunning()]
        if not active and not profiles:
            if self.one_shot.cleanup_mounted_image():
                event.accept()
            else:
                event.ignore()
            return

        self._closing = True
        self._batch_queue.clear()
        for worker in active:
            if isinstance(worker, GameWorker):
                worker.cancel()

        deadline = time.monotonic() + 3.0
        for worker in [*active, *profiles]:
            remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
            if remaining_ms:
                worker.wait(remaining_ms)

        if any(w.isRunning() for w in [*active, *profiles]):
            QMessageBox.warning(
                self,
                "Processing is still active",
                "Lazy_AMPR is still finishing background work. Wait for it to stop, then close again.",
            )
            self._closing = False
            event.ignore()
            return
        if self.one_shot.cleanup_mounted_image():
            event.accept()
        else:
            self._closing = False
            event.ignore()
