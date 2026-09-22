from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtGui import QDropEvent, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.param_parser import parse_game_info
from gui import styles as S
from gui.game_card import rounded_pixmap
from gui.icons import icon_pixmap
from gui.widgets import AnimatedButton, LevelSlider, SectionCard
from utils.cross_platform import normalize_path
from utils.exfat_utils import is_exfat_image
from utils.file_ops import detect_games
from utils.osfmount import mount_exfat_image, supports_image_mounting, unmount_exfat_image


def _w(layout):
    w = QWidget(); w.setLayout(layout); return w


def _short(p, n=42):
    p = str(p); return p if len(p) <= n else "…" + p[-(n-1):]


class OneShotPage(QWidget):
    start_requested = Signal()
    cancel_requested = Signal()
    folder_set = Signal(object, object)      # (path, info)
    traces_imported = Signal(object)         # path  → main window auto-generates a TOML

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentBG")
        self.game_dir = None
        self.game_info = None
        self.custom_config_path = None
        self.traces_dir = None
        self.lz4_level = 9
        self.skip_lz4_verification = False
        self.toml_name = None
        self.toml_auto = False
        self.input_path = None
        self.mounted_image = None
        self._loaded = False
        self._pct = 0
        self._eta = ""
        self._init_ui()

    # ------------------------------------------------------------------ UI
    def _init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(16)

        # ---- Drop zone ----
        self.drop_area = QFrame()
        self.drop_area.setObjectName("DropArea")
        self.setAcceptDrops(True)            # <--- ADD: page accepts drops
        self.drop_area.setAcceptDrops(True)  # <--- ADD: drop zone accepts drops
        self.drop_area.setMinimumHeight(300)
        self._drop_anim = QPropertyAnimation(self.drop_area, b"maximumHeight", self)
        self._drop_anim.setDuration(220)
        self._drop_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.empty_w = QWidget()
        ew = QVBoxLayout(self.empty_w)
        ew.setAlignment(Qt.AlignCenter)
        ew.setSpacing(10)
        self.drop_icon = QLabel()
        self.drop_icon.setAlignment(Qt.AlignCenter)
        t1 = QLabel(
            "Drop a PS5 game folder or .exFAT file"
            if supports_image_mounting()
            else "Drop a PS5 game folder"
        )
        t1.setAlignment(Qt.AlignCenter)
        t1.setStyleSheet("font-size: 20px; font-weight: 700;")
        t2 = QLabel("or click anywhere in this area to browse")
        t2.setObjectName("SubHeader")
        t2.setAlignment(Qt.AlignCenter)
        ew.addWidget(self.drop_icon)
        ew.addWidget(t1)
        ew.addWidget(t2)

        self.bar_w = QWidget()
        self.bar_w.setVisible(False)
        bw = QHBoxLayout(self.bar_w)
        bw.setContentsMargins(16, 0, 12, 0)
        bw.setSpacing(12)
        self.bar_icon = QLabel()
        self.bar_title = QLabel("—")
        self.bar_title.setObjectName("CardTitle")
        self.bar_meta = QLabel("")
        self.bar_meta.setObjectName("Subtitle")
        self.switch_btn = AnimatedButton("Switch", "ghost", icon="folder")
        self.switch_btn.clicked.connect(self.browse)
        bw.addWidget(self.bar_icon)
        bw.addWidget(self.bar_title)
        bw.addWidget(self.bar_meta, 1)
        bw.addWidget(self.switch_btn)

        dl = QVBoxLayout(self.drop_area)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.setSpacing(0)
        dl.addWidget(self.empty_w)
        dl.addWidget(self.bar_w)
        self.drop_area.mousePressEvent = lambda e: self.browse()
        lay.addWidget(self.drop_area, 1)

        # ---- Content (hidden until loaded) ----
        self.content = QWidget()
        self.content.setVisible(False)
        cv = QVBoxLayout(self.content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        inner = QWidget()
        inner.setObjectName("ContentBG")
        inner.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 0, 0, 0)
        iv.setSpacing(16)

        # Game info card
        self.info = SectionCard("Game information")
        self.info_body = QWidget()
        self.info_grid = QGridLayout(self.info_body)
        self.info_grid.setSpacing(10)
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(150, 150)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.fields = {}
        self.field_labels = []
        self._info_compact = None
        for key in ["Title", "Title ID", "Version", "SDK", "Content ID", "Path"]:
            label = QLabel(key); label.setObjectName("InfoKey")
            value = QLabel("—"); value.setObjectName("InfoVal"); value.setWordWrap(True)
            self.field_labels.append((label, value)); self.fields[key] = value
        self._reflow_info(False)
        self.info.add_widget(self.info_body)
        iv.addWidget(self.info)

        # Config card
        self.cfg = SectionCard("Configuration")

        # Traces
        self.traces_btn = AnimatedButton("Import traces", "secondary", icon="chart")
        self.traces_btn.clicked.connect(self._import_traces)
        self.traces_lbl = QLabel("No trace profile — blind packing will be used")
        self.traces_lbl.setObjectName("Subtitle")
        tw = QHBoxLayout()
        tw.setSpacing(10)
        tw.addWidget(self.traces_btn)
        tw.addWidget(self.traces_lbl, 1)
        self.cfg.add_row("Trace profile", _w(tw))

        # Config
        self.cfg_btn = AnimatedButton("Import config", "secondary", icon="download")
        self.cfg_btn.clicked.connect(self._import_config)
        self.cfg_lbl = QLabel("Auto-detect from Toml list")
        self.cfg_lbl.setObjectName("Subtitle")
        cw = QHBoxLayout()
        cw.setSpacing(10)
        cw.addWidget(self.cfg_btn)
        cw.addWidget(self.cfg_lbl, 1)
        self.cfg.add_row("Pack config", _w(cw))

        # LZ4 level
        self.level_slider = LevelSlider(9)
        self.level_slider.value_changed.connect(lambda v: setattr(self, "lz4_level", v))
        self.cfg.add_row("LZ4 compression", self.level_slider)

        # Skip verification
        self.skip_verify_cb = QCheckBox("Skip LZ4 integrity check")
        self.skip_verify_cb.setChecked(self.skip_lz4_verification)
        self.skip_verify_cb.toggled.connect(lambda v: setattr(self, "skip_lz4_verification", v))
        self.cfg.add_row("LZ4 verification", self.skip_verify_cb)
        iv.addWidget(self.cfg)
        iv.addStretch(1)
        scroll.setWidget(inner)
        cv.addWidget(scroll)
        lay.addWidget(self.content)

        # ---- Footer ----
        self.footer = QWidget()
        self.footer.setVisible(False)
        fv = QVBoxLayout(self.footer)
        fv.setContentsMargins(0, 4, 0, 0)
        fv.setSpacing(10)
        fr = QHBoxLayout()
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("Subtitle")
        self.pct_label = QLabel("")
        self.pct_label.setObjectName("Subtitle")
        fr.addWidget(self.status_label, 1)
        fr.addWidget(self.pct_label)
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        fb = QHBoxLayout()
        fb.addStretch(1)
        self.cancel_btn = AnimatedButton("Cancel", "secondary", icon="stop")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        fb.addWidget(self.cancel_btn)
        self.start_btn = AnimatedButton("Start processing", "big", icon="play")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_requested.emit)
        fb.addWidget(self.start_btn)
        fv.addLayout(fr)
        fv.addWidget(self.progress_bar)
        fv.addLayout(fb)
        lay.addWidget(self.footer)

        self.refresh_theme_icons()

    def _reflow_info(self, compact):
        if compact == self._info_compact:
            return
        self._info_compact = compact
        while self.info_grid.count():
            self.info_grid.takeAt(0)
        if compact:
            self.info_grid.addWidget(self.icon_label, 0, 0, 1, 2, Qt.AlignHCenter | Qt.AlignTop)
            row = 1
            for label, value in self.field_labels:
                self.info_grid.addWidget(label, row, 0, 1, 2)
                self.info_grid.addWidget(value, row + 1, 0, 1, 2)
                row += 2
        else:
            self.info_grid.addWidget(self.icon_label, 0, 0, len(self.field_labels), 1, Qt.AlignTop)
            for row, (label, value) in enumerate(self.field_labels):
                self.info_grid.addWidget(label, row, 1)
                self.info_grid.addWidget(value, row, 2)
        self.info_grid.setColumnStretch(2 if not compact else 1, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 700
        self.cfg.set_compact(compact)
        self._reflow_info(compact)

    def refresh_theme_icons(self):
        c = S.CURRENT["text_sub"]
        self.drop_icon.setPixmap(icon_pixmap("download", 44, c))
        self.bar_icon.setPixmap(icon_pixmap("folder", 18, c))

    # ------------------------------------------------------- drop-zone state
    def _set_drop_loaded(self, loaded: bool):
        if loaded == self._loaded:
            return
        self._loaded = loaded
        self.empty_w.setVisible(not loaded)
        self.bar_w.setVisible(loaded)
        self._drop_anim.stop()
        if loaded:
            self.drop_area.setMinimumHeight(0)
            self.drop_area.setMaximumHeight(16777215)
            self._drop_anim.setStartValue(self.drop_area.height())
            self._drop_anim.setEndValue(76)
            self._drop_anim.finished.connect(self._lock_bar_height, Qt.UniqueConnection)
            self._drop_anim.start()
            _fade_in(self.content)
            _fade_in(self.footer)
        else:
            self.drop_area.setMinimumHeight(300)
            self.drop_area.setMaximumHeight(16777215)
            self.content.setVisible(False)
            self.footer.setVisible(False)

    def _lock_bar_height(self):
        if self._loaded:
            self.drop_area.setMinimumHeight(76)
            self.drop_area.setMaximumHeight(76)

    # ---------------------------------------------------------- drag & drop
    def _set_drag_over(self, on):
        self.drop_area.setProperty("drag", on)
        self.drop_area.style().unpolish(self.drop_area)
        self.drop_area.style().polish(self.drop_area)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._set_drag_over(True)

    def dragLeaveEvent(self, e):
        self._set_drag_over(False)

    def dropEvent(self, e: QDropEvent):
        self._set_drag_over(False)
        for url in e.mimeData().urls():
            p = normalize_path(url.toLocalFile())
            if self.load_input(p):
                e.acceptProposedAction()
                return
        e.ignore()

    def load_input(self, path: Path) -> bool:
        """Load a game folder or exFAT image selected by either drop target."""
        path = normalize_path(str(path))
        if path.is_file() and is_exfat_image(path):
            return self._handle_exfat_image(path)
        if path.is_dir():
            if not self.cleanup_mounted_image():
                return False
            games = detect_games(path)
            if games:
                self.input_path = path
                self.set_folder(games[0])
                return True
        return False

    def _handle_exfat_image(self, img_path: Path) -> bool:
        """Mount an exFAT image read-only and use its game tree directly."""
        last_message = ""

        def progress(msg):
            nonlocal last_message
            last_message = msg
            self.set_status(msg)
        
        if not self.cleanup_mounted_image():
            return False

        mounted = None
        try:
            mounted = mount_exfat_image(img_path, progress)
            self.mounted_image = mounted
            games = detect_games(mounted.root, max_depth=3)
            if not games:
                raise FileNotFoundError(
                    "No PS5 game folder containing sce_sys/param.json was found in the image."
                )
        except Exception as exc:  # noqa: BLE001 - present mount failures in the GUI
            unmount_error = ""
            if mounted is not None:
                try:
                    unmount_exfat_image(mounted)
                    self.mounted_image = None
                except Exception as cleanup_exc:  # noqa: BLE001 - include cleanup failure
                    unmount_error = f"\n\nThe image also could not be unmounted: {cleanup_exc}"
            QMessageBox.warning(
                self,
                "Could not mount exFAT image",
                (str(exc) or last_message or "The selected image could not be mounted.")
                + unmount_error,
            )
            return False

        self.input_path = img_path
        self.set_folder(games[0])
        return True

    def cleanup_mounted_image(self) -> bool:
        """Unmount the current image. Return False when it must remain tracked."""
        if self.mounted_image is None:
            return True
        try:
            unmount_exfat_image(self.mounted_image)
        except Exception as exc:  # noqa: BLE001 - do not lose track of a live mount
            QMessageBox.warning(self, "Could not unmount exFAT image", str(exc))
            return False
        drive = self.mounted_image.drive_letter
        self.mounted_image = None
        if self.game_dir is not None and Path(self.game_dir).drive.upper() == f"{drive}:".upper():
            self.start_btn.setEnabled(False)
        return True

    # ------------------------------------------------------------ public API
    def browse(self):
        if not supports_image_mounting():
            # Image mounting is Windows-only (OSFMount); a folder is the only choice.
            self._browse_folder()
            return

        choice = QMessageBox(self)
        choice.setWindowTitle("Select input")
        choice.setText("Choose a PS5 game folder or a ShadowMountPlus exFAT image.")
        folder_btn = choice.addButton("Game folder", QMessageBox.ButtonRole.AcceptRole)
        image_btn = choice.addButton("exFAT image", QMessageBox.ButtonRole.AcceptRole)
        choice.addButton(QMessageBox.StandardButton.Cancel)
        choice.exec()

        if choice.clickedButton() is folder_btn:
            self._browse_folder()
        elif choice.clickedButton() is image_btn:
            p, _ = QFileDialog.getOpenFileName(
                self,
                "Select a ShadowMountPlus exFAT image",
                "",
                "exFAT images (*.exfat *.img);;All files (*)",
            )
            if p:
                path = Path(p)
                if not is_exfat_image(path):
                    QMessageBox.warning(
                        self,
                        "Not an exFAT image",
                        f"No exFAT filesystem was detected in:\n{path}",
                    )
                else:
                    self.load_input(path)

    def _browse_folder(self):
        p = QFileDialog.getExistingDirectory(self, "Select a PS5 game folder")
        if p:
            self.load_input(Path(p))

    def set_folder(self, path: Path):
        self.game_dir = path
        info = parse_game_info(path)
        self.game_info = info
        self.fields["Title"].setText(info["title"])
        self.fields["Title ID"].setText(info["title_id"])
        self.fields["Version"].setText(info["version"])
        self.fields["SDK"].setText(info["sdk_version"])
        self.fields["Content ID"].setText(info["content_id"])
        self.fields["Path"].setText(str(path))
        if info.get("icon_path") and Path(info["icon_path"]).exists():
            pm = QPixmap(str(info["icon_path"]))
            if not pm.isNull():
                self.icon_label.setPixmap(rounded_pixmap(pm, 150, 15))
        self.bar_title.setText(info["title"])
        self.bar_meta.setText(f"{info['title_id']}  •  v{info['version']}")
        self._set_drop_loaded(True)
        self.start_btn.setEnabled(True)
        self.set_status("Ready to process.")
        self.folder_set.emit(path, info)

    # ------------------------------------------------------- config handlers
    def _import_traces(self):
        p = QFileDialog.getExistingDirectory(self, "Select folder containing traces")
        if p:
            self.traces_dir = Path(p)
            self.traces_lbl.setText(_short(Path(p).name))
            self.traces_lbl.setToolTip(str(p))
            self.traces_imported.emit(Path(p))

    def _import_config(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select TOML config", "", "TOML Files (*.toml)")
        if not p:
            return
        if self.toml_auto and self.toml_name:
            if QMessageBox.question(self, "Override TOML",
                    f"Auto-linked to “{self.toml_name}”.\nOverride with “{Path(p).name}”?",
                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
            self.toml_auto = False
        self.custom_config_path = Path(p)
        self.toml_name = Path(p).name
        self.cfg_lbl.setText(f"{Path(p).name} (manual)")

    def apply_link(self, toml_name, auto):
        self.toml_name, self.toml_auto = toml_name, auto
        if toml_name:
            self.cfg_lbl.setText(f"{toml_name} ({'auto' if auto else 'manual'})")

    # ------------------------------------------------------------- sink API
    def _refresh_pct(self):
        self.pct_label.setText(f"{self._pct}% · {self._eta}" if self._eta
                               else (f"{self._pct}%" if self._pct else ""))

    def set_progress(self, v):
        self._pct = v
        self._refresh_pct()
        self.progress_bar.setValue(v)
        self.progress_bar.setProperty("error", False)
        self.progress_bar.setProperty("done", v >= 100)
        self._restyle()

    def set_eta(self, t):
        self._eta = t
        self._refresh_pct()

    def set_status(self, t):
        self.status_label.setText(t)
        self.status_label.setProperty("error", False)
        self._restyle()

    def set_error(self, msg):
        last = msg.strip().splitlines()[-1] if msg.strip() else "Unknown error"
        self.status_label.setText(last[:80])
        self.status_label.setProperty("error", True)
        self.status_label.setToolTip(msg)
        self.progress_bar.setProperty("error", True)
        self.progress_bar.setProperty("done", False)
        self._restyle()

    def set_running_state(self, running):
        self.start_btn.setEnabled(not running)
        self.start_btn.set_icon("clock" if running else "play")
        self.start_btn.setText("Processing…" if running else "Start processing")
        self.switch_btn.setEnabled(not running)
        if not running:
            self._eta = ""
            self._refresh_pct()

    def _restyle(self):
        for w in (self.status_label, self.progress_bar):
            w.style().unpolish(w)
            w.style().polish(w)


def _fade_in(widget, duration=180):
    widget.show()
    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"opacity", widget)
    a.setDuration(duration)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.finished.connect(lambda: widget.setGraphicsEffect(None))
    a.start()
