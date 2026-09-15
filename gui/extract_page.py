from pathlib import Path

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from gui import styles as S
from gui.icons import icon_pixmap
from gui.widgets import AnimatedButton, SectionCard


def _w(layout):
    w = QWidget(); w.setLayout(layout); return w


def _fmt_bytes(n):
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}"
        n /= 1024


class ExtractPage(QWidget):
    start_requested = Signal()
    folder_set = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentBG")
        self.source_dir = None
        self.output_dir = None
        self._loaded = False
        self._pct = 0
        self._init_ui()

    def _init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)

        # ---- Drop zone: full page when empty, compact bar when loaded ----
        self.drop_area = QFrame(); self.drop_area.setObjectName("DropArea")
        self.drop_area.setMinimumHeight(300)
        self.drop_area.setAcceptDrops(True)
        self._drop_anim = QPropertyAnimation(self.drop_area, b"maximumHeight", self)
        self._drop_anim.setDuration(220); self._drop_anim.setEasingCurve(QEasingCurve.InOutCubic)

        self.empty_w = QWidget()
        ew = QVBoxLayout(self.empty_w); ew.setAlignment(Qt.AlignCenter); ew.setSpacing(8)
        self.drop_icon = QLabel(); self.drop_icon.setAlignment(Qt.AlignCenter)
        t1 = QLabel("Drop an AMPR-packed game folder"); t1.setAlignment(Qt.AlignCenter)
        t1.setStyleSheet("font-size: 20px; font-weight: 700;")
        t2 = QLabel("must contain ampr_assets.index / ampr_assets-*.pak — or click to browse")
        t2.setObjectName("SubHeader"); t2.setAlignment(Qt.AlignCenter); t2.setWordWrap(True)
        ew.addWidget(self.drop_icon); ew.addWidget(t1); ew.addWidget(t2)

        self.bar_w = QWidget(); self.bar_w.setVisible(False)
        bw = QHBoxLayout(self.bar_w); bw.setContentsMargins(16, 0, 12, 0); bw.setSpacing(12)
        self.bar_icon = QLabel()
        self.bar_title = QLabel("—"); self.bar_title.setObjectName("CardTitle")
        self.bar_meta = QLabel(""); self.bar_meta.setObjectName("Subtitle")
        self.switch_btn = AnimatedButton("Switch", "ghost", icon="folder")
        self.switch_btn.clicked.connect(self.browse)
        bw.addWidget(self.bar_icon); bw.addWidget(self.bar_title)
        bw.addWidget(self.bar_meta, 1); bw.addWidget(self.switch_btn)

        dl = QVBoxLayout(self.drop_area); dl.setContentsMargins(0, 0, 0, 0); dl.setSpacing(0)
        dl.addWidget(self.empty_w); dl.addWidget(self.bar_w)
        self.drop_area.mousePressEvent = lambda e: self.browse()
        lay.addWidget(self.drop_area, 1)

        # ---- Content (hidden until loaded) ----
        self.content = QWidget(); self.content.setVisible(False)
        cv = QVBoxLayout(self.content); cv.setContentsMargins(0, 0, 0, 0); cv.setSpacing(14)

        src_card = SectionCard("Packed source")
        self.src_lbl = QLabel("—"); self.src_lbl.setObjectName("InfoVal"); self.src_lbl.setWordWrap(True)
        self.manifest_lbl = QLabel("—"); self.manifest_lbl.setObjectName("InfoVal")
        self.packs_lbl = QLabel("—"); self.packs_lbl.setObjectName("InfoVal")
        src_card.add_row("Folder", self.src_lbl)
        src_card.add_row("Manifest", self.manifest_lbl)
        src_card.add_row("Pack volumes", self.packs_lbl)
        cv.addWidget(src_card)

        dst_card = SectionCard("Destination")
        self.out_btn = AnimatedButton("Browse…", "secondary", icon="folder")
        self.out_btn.clicked.connect(self._browse_output)
        self.out_lbl = QLabel("Default: next to source (…_EXTRACTED)")
        self.out_lbl.setObjectName("Subtitle"); self.out_lbl.setWordWrap(True)
        dst_card.add_row("Output folder", self.out_btn, self.out_lbl)
        cv.addWidget(dst_card)
        cv.addStretch(1)
        lay.addWidget(self.content)

        # ---- Footer pinned at the bottom ----
        self.footer = QWidget(); self.footer.setVisible(False)
        fv = QVBoxLayout(self.footer); fv.setContentsMargins(0, 4, 0, 0); fv.setSpacing(8)
        fr = QHBoxLayout()
        self.status_label = QLabel("Ready"); self.status_label.setObjectName("Subtitle")
        self.pct_label = QLabel(""); self.pct_label.setObjectName("Subtitle")
        fr.addWidget(self.status_label, 1); fr.addWidget(self.pct_label)
        self.progress_bar = QProgressBar(); self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        fb = QHBoxLayout(); fb.addStretch(1)
        self.start_btn = AnimatedButton("Start extraction", "big", icon="extract")
        self.start_btn.setEnabled(False); self.start_btn.clicked.connect(self.start_requested.emit)
        fb.addWidget(self.start_btn)
        fv.addLayout(fr); fv.addWidget(self.progress_bar); fv.addLayout(fb)
        lay.addWidget(self.footer)

        self.refresh_theme_icons()

    def refresh_theme_icons(self):
        c = S.CURRENT["text_sub"]
        self.drop_icon.setPixmap(icon_pixmap("extract", 44, c))
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
            self.content.show(); self.footer.show()
        else:
            self.drop_area.setMinimumHeight(300)
            self.drop_area.setMaximumHeight(16777215)
            self.content.setVisible(False); self.footer.setVisible(False)

    def _lock_bar_height(self):
        if self._loaded:
            self.drop_area.setMinimumHeight(76); self.drop_area.setMaximumHeight(76)

    # ------------------------------------------------------------ drag & drop
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.drop_area.setProperty("drag", True); self._restyle_drop()

    def dragLeaveEvent(self, e):
        self.drop_area.setProperty("drag", False); self._restyle_drop()

    def dropEvent(self, e):
        self.drop_area.setProperty("drag", False); self._restyle_drop()
        for u in e.mimeData().urls():
            p = Path(u.toLocalFile())
            if p.is_dir():
                self.set_folder(p); e.acceptProposedAction(); return
        e.ignore()

    def _restyle_drop(self):
        self.drop_area.style().unpolish(self.drop_area); self.drop_area.style().polish(self.drop_area)

    # ------------------------------------------------------------ public API
    def browse(self):
        p = QFileDialog.getExistingDirectory(self, "Select an AMPR-packed game folder")
        if p: self.set_folder(Path(p))

    def _browse_output(self):
        p = QFileDialog.getExistingDirectory(self, "Select extraction output folder")
        if p:
            self.output_dir = Path(p)
            self.out_lbl.setText(str(self.output_dir))

    def set_folder(self, path):
        path = Path(path)
        idx = path / "ampr_assets.index"
        packs = sorted(path.glob("ampr_assets-*.pak"))
        if not idx.is_file() and not packs:
            QMessageBox.warning(self, "Not an AMPR packed folder",
                              f"No ampr_assets.index or ampr_assets-*.pak found in:\n{path}")
            return
        self.source_dir = path
        self.output_dir = None
        self.out_lbl.setText("Default: next to source (…_EXTRACTED)")
        total = sum(p.stat().st_size for p in packs)
        self.src_lbl.setText(str(path))
        self.manifest_lbl.setText("ampr_assets.index" if idx.is_file() else "missing (packs only)")
        self.packs_lbl.setText(f"{len(packs)} volume(s) · {_fmt_bytes(total)}")
        self.bar_title.setText(path.name)
        self.bar_meta.setText(f"{len(packs)} pack(s) · {_fmt_bytes(total)}")
        self._set_drop_loaded(True)
        self.start_btn.setEnabled(True)
        self.set_status("Ready to extract.")
        self.folder_set.emit(path)

    # ------------------------------------------------------------- sink API
    def set_progress(self, v):
        self._pct = v
        self.pct_label.setText(f"{self._pct}%")
        self.progress_bar.setValue(v)
        self.progress_bar.setProperty("error", False)
        self.progress_bar.setProperty("done", v >= 100)
        self._restyle()

    def set_status(self, t):
        self.status_label.setText(t)
        self.status_label.setProperty("error", False); self._restyle()

    def set_error(self, msg):
        last = msg.strip().splitlines()[-1] if msg.strip() else "Unknown error"
        self.status_label.setText(last[:80])
        self.status_label.setProperty("error", True)
        self.status_label.setToolTip(msg)
        self.progress_bar.setProperty("error", True)
        self.progress_bar.setProperty("done", False); self._restyle()

    def set_running_state(self, running):
        self.start_btn.setEnabled(not running)
        self.start_btn.set_icon("clock" if running else "extract")
        self.start_btn.setText("Extracting…" if running else "Start extraction")
        self.switch_btn.setEnabled(not running)

    def _restyle(self):
        for w in (self.status_label, self.progress_bar):
            w.style().unpolish(w); w.style().polish(w)
