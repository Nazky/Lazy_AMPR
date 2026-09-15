from pathlib import Path

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRectF,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QEnterEvent, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
)

from gui import styles as S
from gui.icons import device_pixel_ratio, icon_pixmap
from gui.widgets import AnimatedButton

SIZES = {"Compact": (200, 76), "Comfortable": (224, 92), "Large": (244, 104)}

def rounded_pixmap(source, size, radius):
    dpr = device_pixel_ratio()
    physical_size = max(1, round(size * dpr))
    scaled = source.scaled(
        physical_size, physical_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
    )
    out = QPixmap(physical_size, physical_size)
    out.setDevicePixelRatio(dpr); out.fill(Qt.transparent)
    p = QPainter(out); p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath(); path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(QRectF(0, 0, size, size), scaled, QRectF(0, 0, physical_size, physical_size))
    p.end()
    return out


class GameCard(QFrame):
    start_requested = Signal()
    selection_changed = Signal(bool)
    
    def __init__(self, game_info, parent=None):
        super().__init__(parent)
        self.setObjectName("GameCard")
        self.game_info = game_info
        self.custom_config_path = None
        self.traces_dir = None
        self.selected_for_batch = False
        self.toml_name = None
        self.toml_auto = False
        self._icon_path = game_info.get("icon_path")
        self._icon_size = 132
        
        # Hover animation properties
        self._hover = 0.0
        self._hover_anim = QPropertyAnimation(self, b"hoverT", self)
        self._hover_anim.setDuration(200)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        
        self._init_ui()
        self.apply_size("Comfortable")

    def getHoverT(self):
        return self._hover

    def setHoverT(self, v):
        self._hover = v
        self.update()

    hoverT = Property(float, getHoverT, setHoverT)

    def _init_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)
        
        # Icon with better styling
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setObjectName("CardIcon")
        
        # Title
        self.title_label = QLabel(self.game_info.get("title", "Unknown"))
        self.title_label.setObjectName("CardTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setFixedHeight(38)
        self.title_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.title_label.setToolTip(self.game_info.get("title", "Unknown"))
        
        # Meta
        self.meta_label = QLabel(f"{self.game_info.get('title_id', '—')}  •  v{self.game_info.get('version', '?')}")
        self.meta_label.setObjectName("Subtitle")
        self.meta_label.setFixedHeight(18)
        
        self.batch_checkbox = QCheckBox("Include in batch")
        self.batch_checkbox.setChecked(False)
        self.batch_checkbox.toggled.connect(self._batch_selection_changed)
        
        # Status row
        st_row = QHBoxLayout()
        st_row.setSpacing(8)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("Subtitle")
        self.status_label.setMinimumWidth(0)
        self.eta_label = QLabel("")
        self.eta_label.setObjectName("Subtitle")
        self.eta_label.setMinimumWidth(0)
        st_row.addWidget(self.status_label, 1)
        st_row.addWidget(self.eta_label)
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setObjectName("CardProgress")
        
        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.start_btn = AnimatedButton("Start", "primary", icon="play")
        self.start_btn.setFixedHeight(40)
        self.start_btn.clicked.connect(self.start_requested.emit)
        
        self.traces_btn = AnimatedButton("", "icon", icon="chart")
        self.traces_btn.setFixedSize(40, 40)
        self.traces_btn.setToolTip("Import trace folder")
        self.traces_btn.setAccessibleName("Import trace folder")
        self.traces_btn.clicked.connect(self._import_traces)
        
        self.cfg_btn = AnimatedButton("", "icon", icon="download")
        self.cfg_btn.setFixedSize(40, 40)
        self.cfg_btn.setToolTip("Import TOML config")
        self.cfg_btn.setAccessibleName("Import TOML config")
        self.cfg_btn.clicked.connect(self._import_config)
        
        btn_row.addWidget(self.start_btn, 1)
        btn_row.addWidget(self.traces_btn)
        btn_row.addWidget(self.cfg_btn)
        
        lay.addWidget(self.icon_label, 0, Qt.AlignHCenter)
        lay.addWidget(self.title_label)
        lay.addWidget(self.meta_label)
        lay.addWidget(self.batch_checkbox)
        lay.addLayout(st_row)
        lay.addWidget(self.progress_bar)
        lay.addLayout(btn_row)

    def _batch_selection_changed(self, selected):
        self.selected_for_batch = bool(selected)
        self.selection_changed.emit(self.selected_for_batch)

    def enterEvent(self, event: QEnterEvent):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        
        super().leaveEvent(event)

    def paintEvent(self, event):
        t = S.CURRENT
        
        # Calculate colors based on hover state
        base_color = QColor(t["bg_card"])
        hover_color = QColor(t["bg_card_hover"]) if "bg_card_hover" in t else base_color.lighter(115)
        
        # Interpolate colors
        final_color = QColor(
            int(base_color.red() + (hover_color.red() - base_color.red()) * self._hover),
            int(base_color.green() + (hover_color.green() - base_color.green()) * self._hover),
            int(base_color.blue() + (hover_color.blue() - base_color.blue()) * self._hover),
            int(base_color.alpha() + (hover_color.alpha() - base_color.alpha()) * self._hover)
        )
        
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        
        # Draw rounded background
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.width()-1, self.height()-1), 12, 12)
        p.fillPath(path, final_color)
        
        # Draw border
        border_color = QColor(t["border"])
        if self._hover > 0:
            accent = QColor(t["accent"])
            border_color = QColor(
                int(border_color.red() + (accent.red() - border_color.red()) * self._hover * 0.3),
                int(border_color.green() + (accent.green() - border_color.green()) * self._hover * 0.3),
                int(border_color.blue() + (accent.blue() - border_color.blue()) * self._hover * 0.3)
            )
        p.setPen(QColor(border_color))
        p.drawPath(path)
        p.end()
        
        super().paintEvent(event)

    def apply_size(self, name):
        w, icon = SIZES.get(name, SIZES["Comfortable"])
        self._icon_size = icon
        self.setFixedWidth(w)
        self.setFixedHeight(icon + 234)
        self.icon_label.setFixedSize(icon, icon)
        self._render_icon()

    def _render_icon(self):
        if self._icon_path and Path(self._icon_path).exists():
            pm = QPixmap(str(self._icon_path))
            if not pm.isNull():
                self.icon_label.setPixmap(rounded_pixmap(pm, self._icon_size, max(10, self._icon_size // 10)))
                return
        self.icon_label.setPixmap(icon_pixmap("game", self._icon_size // 2, "#86868b"))

    def _import_traces(self):
        p = QFileDialog.getExistingDirectory(self, "Select folder containing traces")
        if p:
            self.traces_dir = Path(p)
            self.traces_btn.setToolTip(f"Traces: {Path(p).name}")

    def _import_config(self):
        p, _ = QFileDialog.getOpenFileName(self, "Select TOML config", "", "TOML Files (*.toml)")
        if not p:
            return
        if self.toml_auto and self.toml_name:
            if QMessageBox.question(self, "Override TOML",
                    f'Auto-linked to "{self.toml_name}".\nOverride with "{Path(p).name}"?',
                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                return
            self.toml_auto = False
        self.custom_config_path = Path(p)
        self.toml_name = Path(p).name
        self.cfg_btn.setToolTip(f"Config: {Path(p).name} (manual)")

    def set_progress(self, v):
        self.progress_bar.setValue(v)
        self.progress_bar.setProperty("error", False)
        self.progress_bar.setProperty("done", v >= 100)
        self._restyle()

    def set_eta(self, t):
        self.eta_label.setText(t)
        self.eta_label.setToolTip(t)

    def set_status(self, t):
        self.status_label.setText(t)
        self.status_label.setToolTip(t)
        self.status_label.setProperty("error", False)
        self._restyle()

    def set_error(self, msg):
        last = msg.strip().splitlines()[-1] if msg.strip() else "Unknown error"
        self.status_label.setText(last[:40])
        self.status_label.setProperty("error", True)
        self.status_label.setToolTip(msg)
        self.progress_bar.setProperty("error", True)
        self.progress_bar.setProperty("done", False)
        self._restyle()

    def set_running_state(self, running):
        self.start_btn.setEnabled(not running)
        self.batch_checkbox.setEnabled(not running)
        self.start_btn.set_icon("clock" if running else "play")
        self.start_btn.setText("Processing…" if running else "Start")
        if not running:
            self.eta_label.setText("")

    def _restyle(self):
        for w in (self.status_label, self.progress_bar):
            w.style().unpolish(w)
            w.style().polish(w)
