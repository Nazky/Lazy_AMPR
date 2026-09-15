from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.widgets import (
    AnimatedButton,
    LevelSlider,
    SectionCard,
    SegmentedControl,
    StatusBadge,
    WorkerSlider,
)
from utils.state import TOML_DIR


def _fill_row(*widgets):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(10)
    for index, child in enumerate(widgets):
        layout.addWidget(child, 1 if index == 0 else 0)
    return container


def _inline_row(*widgets):
    container = QWidget()
    layout = QHBoxLayout(container)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(8)
    for child in widgets:
        layout.addWidget(child)
    layout.addStretch(1)
    return container


def _help_button(text):
    button = AnimatedButton("", "ghost", icon="help")
    button.setFixedSize(26, 26)
    button.setToolTip(text)
    button.setAccessibleName(text)
    return button


class AppearanceCard(QFrame):
    """Compact responsive header and theme selector used by Settings."""

    def __init__(self, theme_selector, parent=None):
        super().__init__(parent)
        self.setObjectName("Section")
        self.theme_selector = theme_selector
        self._compact = None
        self.layout = QGridLayout(self)
        self.layout.setContentsMargins(22, 20, 22, 20)
        self.layout.setHorizontalSpacing(24)
        self.layout.setVerticalSpacing(14)

        self.intro = QWidget()
        intro_layout = QVBoxLayout(self.intro)
        intro_layout.setContentsMargins(0, 0, 0, 0)
        intro_layout.setSpacing(4)
        title = QLabel("Appearance")
        title.setObjectName("SectionTitle")
        description = QLabel("Choose the application theme.")
        description.setObjectName("SubHeader")
        intro_layout.addWidget(title)
        intro_layout.addWidget(description)

        self.theme_selector.setMinimumWidth(320)
        self.theme_selector.setMaximumWidth(600)
        self.theme_selector.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.set_compact(False)

    def set_compact(self, compact):
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        while self.layout.count():
            self.layout.takeAt(0)
        self.layout.setColumnStretch(0, 0)
        self.layout.setColumnStretch(1, 0)
        if compact:
            self.layout.addWidget(self.intro, 0, 0, 1, 2)
            self.layout.addWidget(self.theme_selector, 1, 0, 1, 2)
            self.layout.setColumnStretch(0, 1)
        else:
            self.layout.addWidget(self.intro, 0, 0)
            self.layout.addWidget(self.theme_selector, 0, 1, Qt.AlignVCenter)
            self.layout.setColumnStretch(0, 1)
            self.layout.setColumnStretch(1, 1)


class SettingsPage(QWidget):
    save_requested = Signal(dict)
    theme_preview = Signal(str)

    def __init__(self, settings_or_state, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentBG")
        source = (
            settings_or_state.settings
            if hasattr(settings_or_state, "settings")
            else settings_or_state
        )
        self.pending = dict(source)
        self._saved = {}
        self._compact = None
        self._init_ui()

    def _init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QWidget()
        host.setObjectName("ContentBG")
        host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        host_layout = QHBoxLayout(host)
        host_layout.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        content.setObjectName("ContentBG")
        content.setMaximumWidth(1120)
        content.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        root = QVBoxLayout(content)
        root.setContentsMargins(0, 0, 0, 8)
        root.setSpacing(16)
        root.setAlignment(Qt.AlignTop)
        host_layout.addStretch(1)
        host_layout.addWidget(content, 100)
        host_layout.addStretch(1)
        self.scroll.setWidget(host)
        outer.addWidget(self.scroll)

        title = QLabel("Settings")
        title.setObjectName("Header")
        subtitle = QLabel("Configure how Lazy_AMPR looks and processes your games.")
        subtitle.setObjectName("SubHeader")
        root.addWidget(title)
        root.addWidget(subtitle)

        self.theme_seg = SegmentedControl(
            ["Light", "Dark", "Auto"],
            self.pending.get("theme", "Auto"),
            icons={"Light": "sun", "Dark": "moon", "Auto": "monitor"},
        )
        self.theme_seg.value_changed.connect(self._theme_changed)
        self.appearance = AppearanceCard(self.theme_seg)
        root.addWidget(self.appearance)

        self.processing = SectionCard(
            "Processing",
            "Configure how games are processed and where output files are saved.",
            label_width=220,
        )

        self.out_edit = QLineEdit(self.pending.get("output_dir", ""))
        self.out_edit.setPlaceholderText("Leave empty to output next to each game…")
        self.out_edit.textChanged.connect(
            lambda value: self._set_pending("output_dir", value)
        )
        self.browse_btn = AnimatedButton("Browse…", "secondary", icon="folder")
        self.browse_btn.setFixedWidth(140)
        self.browse_btn.clicked.connect(lambda: self._browse(self.out_edit))
        self.processing.add_row(
            "Default output directory", _fill_row(self.out_edit, self.browse_btn)
        )

        self.level_slider = LevelSlider(int(self.pending.get("lz4_level", 9)))
        self.level_slider.value_changed.connect(
            lambda value: self._set_pending("lz4_level", value)
        )
        self.level_help = _help_button(
            "Higher LZ4 levels may improve compression but take longer to process."
        )
        self.processing.add_row(
            "LZ4 compression", _inline_row(self.level_slider, self.level_help)
        )

        self.worker_slider = WorkerSlider(self.pending.get("workers"))
        self.pending["workers"] = self.worker_slider.value()
        self.worker_slider.value_changed.connect(
            lambda value: self._set_pending("workers", value)
        )
        self.worker_help = _help_button(
            "Controls parallel compression. Lazy_AMPR leaves one CPU thread free."
        )
        self.processing.add_row(
            "Compression workers", _inline_row(self.worker_slider, self.worker_help)
        )

        self.skip_verify_cb = QCheckBox("Skip LZ4 integrity check")
        self.skip_verify_cb.setChecked(
            bool(self.pending.get("skip_lz4_verification", False))
        )
        verification_tip = "Faster, but packed data will not be reconstructed and checked against the source."
        self.skip_verify_cb.setToolTip(verification_tip)
        self.skip_verify_cb.toggled.connect(
            lambda value: self._set_pending("skip_lz4_verification", value)
        )
        self.verify_help = _help_button(verification_tip)
        self.processing.add_row(
            "LZ4 verification", _inline_row(self.skip_verify_cb, self.verify_help)
        )

        self.hardlink_cb = QCheckBox("Use hardlinks for loose files")
        self.hardlink_cb.setMinimumWidth(0)
        self.hardlink_cb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.hardlink_cb.setChecked(bool(self.pending.get("use_hardlinks", False)))
        hardlink_tip = "Advanced: output edits also change the source files because hardlinks share the same data."
        self.hardlink_cb.setToolTip(hardlink_tip)
        self.hardlink_cb.toggled.connect(
            lambda value: self._set_pending("use_hardlinks", value)
        )
        self.hardlink_help = _help_button(hardlink_tip)
        warning = QLabel("Changes to output hardlinks also change your source files.")
        warning.setObjectName("Subtitle")
        warning.setWordWrap(True)
        warning.setMinimumWidth(0)
        warning.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.advanced_badge = StatusBadge("Advanced")
        self.advanced_badge.setProperty("warning", True)
        self.advanced_badge.label.setProperty("warning", True)
        warning_row = QHBoxLayout()
        warning_row.setContentsMargins(25, 2, 0, 0)
        warning_row.setSpacing(8)
        warning_row.addWidget(self.advanced_badge)
        warning_row.addWidget(warning, 1)
        hardlink = QWidget()
        hardlink_layout = QVBoxLayout(hardlink)
        hardlink_layout.setContentsMargins(0, 0, 0, 0)
        hardlink_layout.setSpacing(3)
        hardlink_layout.addWidget(_inline_row(self.hardlink_cb, self.hardlink_help))
        hardlink_layout.addLayout(warning_row)
        self.processing.add_row("Loose-file placement", hardlink)

        self.toml_path = QLineEdit(str(TOML_DIR))
        self.toml_path.setReadOnly(True)
        self.toml_path.setToolTip(str(TOML_DIR))
        self.toml_path.setAccessibleName("TOML profiles folder")
        self.open_toml_btn = AnimatedButton("Open folder", "secondary", icon="folder")
        self.open_toml_btn.setFixedWidth(150)
        self.open_toml_btn.clicked.connect(self._open_toml_folder)
        self.processing.add_row(
            "TOML profiles folder", _fill_row(self.toml_path, self.open_toml_btn)
        )
        root.addWidget(self.processing)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.saved_lbl = QLabel("No changes to save")
        self.saved_lbl.setObjectName("Subtitle")
        self.save_btn = AnimatedButton("Save settings", "big", icon="save")
        self.save_btn.clicked.connect(self._save)
        footer.addWidget(self.saved_lbl)
        footer.addWidget(self.save_btn)
        root.addLayout(footer)
        root.addStretch(1)
        self._saved = dict(self.pending)
        self._update_dirty()

    def _set_pending(self, key, value):
        self.pending[key] = value
        self._update_dirty()

    def _theme_changed(self, value):
        self._set_pending("theme", value)
        self.theme_preview.emit(value)

    def _update_dirty(self):
        dirty = self.pending != self._saved
        self.save_btn.setEnabled(dirty)
        self.saved_lbl.setText("Unsaved changes" if dirty else "No changes to save")

    def _browse(self, edit):
        path = QFileDialog.getExistingDirectory(self, "Select output directory")
        if path:
            edit.setText(path)

    def _open_toml_folder(self):
        path = Path(TOML_DIR)
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            QMessageBox.warning(self, "Could not open TOML folder", str(error))
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve()))):
            QMessageBox.warning(
                self,
                "Could not open TOML folder",
                f"The system file manager could not open:\n{path}",
            )

    def _save(self):
        self.save_requested.emit(dict(self.pending))

    def mark_saved(self):
        self._saved = dict(self.pending)
        self._update_dirty()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 820
        slider_width = 180 if compact else 240
        self.level_slider.slider.setFixedWidth(slider_width)
        self.worker_slider.slider.setFixedWidth(slider_width)
        if compact != self._compact:
            self._compact = compact
            self.appearance.set_compact(compact)
            self.processing.set_compact(compact)
