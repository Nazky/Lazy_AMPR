import shutil
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui.icons import icon_pixmap
from gui.widgets import AnimatedButton, ElidingLabel, StatusBadge
from utils import net
from utils.state import TOML_DIR, State


class UrlImportDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import TOML from URL")
        self.resize(520, 380)
        v = QVBoxLayout(self); v.setSpacing(10)
        row = QHBoxLayout()
        self.url = QLineEdit(); self.url.setPlaceholderText("https://…/file.toml or GitHub repository")
        fetch = AnimatedButton("Fetch", "secondary", icon="download"); fetch.clicked.connect(self._fetch)
        row.addWidget(self.url, 1); row.addWidget(fetch); v.addLayout(row)
        self.list = QListWidget(); v.addWidget(self.list, 1)
        bar = QHBoxLayout(); bar.addStretch(1)
        download = AnimatedButton("Download selected", "primary", icon="download")
        download.clicked.connect(self._download); bar.addWidget(download); v.addLayout(bar)
        self.found = []

    def _fetch(self):
        self.list.clear(); self.found = []
        try:
            self.found = net.list_tomls_at_url(self.url.text().strip())
        except Exception as exc:  # noqa: BLE001 - show network failures in the dialog
            QMessageBox.warning(self, "Fetch failed", str(exc)); return
        for name, _ in self.found:
            item = QListWidgetItem(name); item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked); self.list.addItem(item)
        if not self.found:
            QMessageBox.information(self, "No TOML found", "No .toml files were found at that URL.")

    def _download(self):
        for index in range(self.list.count()):
            item = self.list.item(index)
            if item.checkState() != Qt.Checked:
                continue
            name, url = self.found[index]
            destination = TOML_DIR / name
            if destination.exists() and QMessageBox.question(
                    self, "Overwrite", f"Overwrite {name}?",
                    QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
                continue
            try:
                net.download_toml(name, url, TOML_DIR)
            except Exception as exc:  # noqa: BLE001 - continue remaining downloads
                QMessageBox.warning(self, "Download failed", f"{name}: {exc}")
        self.accept()


class TomlRow(QFrame):
    link_requested = Signal(object)

    def __init__(self, toml, users, parent=None):
        super().__init__(parent)
        self.setObjectName("Section")
        self.toml = toml
        self._compact = None
        self.grid = QGridLayout(self)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.grid.setContentsMargins(16, 12, 16, 12)
        self.grid.setHorizontalSpacing(12); self.grid.setVerticalSpacing(8)
        self.setMinimumHeight(60)
        self.file_icon = QLabel(); self.file_icon.setPixmap(icon_pixmap("doc", 19, "#86868b"))
        self.name = ElidingLabel(toml.name); self.name.setObjectName("CardTitle")
        if not users:
            status_text, status_icon = "Not linked to any game", "link"
        elif len(users) == 1:
            status_text, status_icon = users[0].get("title", Path(users[0]["path"]).name), "check"
        else:
            status_text, status_icon = f"Linked to {len(users)} games", "check"
        self.status = StatusBadge(status_text, status_icon)
        self.link_btn = AnimatedButton("Link game", "primary", icon="link")
        self.link_btn.setFixedHeight(38)
        self.link_btn.setToolTip(f"Link {toml.name} to a known game")
        self.link_btn.clicked.connect(lambda: self.link_requested.emit(self.toml))
        self._reflow(False)

    def _reflow(self, compact):
        if compact == self._compact:
            return
        self._compact = compact
        while self.grid.count():
            self.grid.takeAt(0)
        if compact == 2:
            self.grid.addWidget(self.file_icon, 0, 0)
            self.grid.addWidget(self.name, 0, 1)
            self.grid.addWidget(self.status, 1, 0, 1, 2, Qt.AlignLeft)
            self.grid.addWidget(self.link_btn, 2, 0, 1, 2, Qt.AlignLeft)
        elif compact:
            self.grid.addWidget(self.file_icon, 0, 0)
            self.grid.addWidget(self.name, 0, 1, 1, 2)
            self.grid.addWidget(self.status, 1, 0, 1, 2, Qt.AlignLeft)
            self.grid.addWidget(self.link_btn, 1, 2, Qt.AlignRight)
        else:
            self.grid.addWidget(self.file_icon, 0, 0)
            self.grid.addWidget(self.name, 0, 1)
            self.grid.addWidget(self.status, 0, 2)
            self.grid.addWidget(self.link_btn, 0, 3)
        self.grid.setColumnStretch(1, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow(self.layout_mode_for_width(self.width()))

    @staticmethod
    def layout_mode_for_width(width):
        return 2 if width < 430 else (1 if width < 700 else 0)


class TomlPage(QWidget):
    changed = Signal()

    def __init__(self, state: State, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentBG")
        self.state = state
        self.setAcceptDrops(True)
        outer = QHBoxLayout(self); outer.setContentsMargins(0, 0, 0, 0)
        self.container = QFrame(); self.container.setObjectName("TomlDropSurface")
        self.container.setMaximumWidth(1100)
        self.content = QVBoxLayout(self.container)
        self.content.setContentsMargins(16, 12, 16, 12); self.content.setSpacing(12)
        outer.addStretch(1); outer.addWidget(self.container, 100); outer.addStretch(1)

        self.header_grid = QGridLayout(); self.header_grid.setSpacing(10)
        self.header_grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.title = QLabel("Toml list"); self.title.setObjectName("Header")
        self.actions = QWidget(); self.actions_layout = QGridLayout(self.actions)
        self.actions_layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.actions_layout.setContentsMargins(0, 0, 0, 0); self.actions_layout.setSpacing(10)
        self.url_btn = AnimatedButton("Import from URL", "primary", icon="download")
        self.url_btn.setFixedHeight(40); self.url_btn.clicked.connect(self._url)
        self.open_btn = AnimatedButton("Open folder", "secondary", icon="folder")
        self.open_btn.setFixedHeight(40); self.open_btn.clicked.connect(self._open)
        self._actions_narrow = None
        self.content.addLayout(self.header_grid)
        hint = QLabel(f"Drop .toml files here — they are stored in {TOML_DIR}\n"
                      "Games auto-link to a toml named after their Title ID or title.")
        hint.setObjectName("Subtitle"); hint.setWordWrap(True); self.content.addWidget(hint)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.host = QWidget(); self.host.setObjectName("ContentBG")
        self.host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.rows = QVBoxLayout(self.host); self.rows.setContentsMargins(0, 6, 0, 0)
        self.rows.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.rows.setSpacing(10); self.rows.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.host); self.content.addWidget(self.scroll, 1)
        self._header_compact = None
        self._reflow_actions(False)
        self._reflow_header(False)
        self.refresh()

    def _reflow_header(self, compact):
        if compact == self._header_compact:
            return
        self._header_compact = compact
        while self.header_grid.count():
            self.header_grid.takeAt(0)
        self.header_grid.addWidget(self.title, 0, 0)
        if compact:
            self.header_grid.addWidget(self.actions, 1, 0, Qt.AlignLeft)
        else:
            self.header_grid.addWidget(self.actions, 0, 1, Qt.AlignRight)
            self.header_grid.setColumnStretch(0, 1)

    def _reflow_actions(self, narrow):
        if narrow == self._actions_narrow:
            return
        self._actions_narrow = narrow
        while self.actions_layout.count():
            self.actions_layout.takeAt(0)
        self.actions_layout.addWidget(self.url_btn, 0, 0)
        self.actions_layout.addWidget(self.open_btn, 1 if narrow else 0, 0 if narrow else 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow_header(self.width() < 680)
        self._reflow_actions(self.width() < 500)

    def refresh(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        tomls = self.state.tomls()
        if not tomls:
            empty = QLabel("No TOML configs yet. Drop a file here or import one from a URL.")
            empty.setObjectName("Subtitle"); self.rows.addWidget(empty); return
        for toml in tomls:
            row = TomlRow(toml, self.state.games_using(toml.name))
            row.link_requested.connect(self._link_game)
            self.rows.addWidget(row)
        self.rows.addStretch(1)

    def _link_game(self, toml):
        games = list(self.state.games.items())
        if not games:
            QMessageBox.information(self, "No games available",
                                    "Add a game in One Shot or Batch before linking a TOML profile.")
            return
        labels = []
        for path, game in games:
            title = game.get("title") or Path(path).name or path
            title_id = game.get("title_id", "")
            labels.append(f"{title}  ·  {title_id}" if title_id else title)
        selected, accepted = QInputDialog.getItem(self, "Link TOML", "Choose a game:", labels, 0, False)
        if not accepted:
            return
        index = labels.index(selected)
        self.state.link_toml(games[index][0], toml.name, "manual")
        self.refresh(); self.changed.emit()

    def _url(self):
        if UrlImportDialog(self).exec() == QDialog.Accepted:
            self.refresh(); self.changed.emit()

    def _open(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(TOML_DIR)))

    def _set_drag_over(self, active):
        self.container.setProperty("drag", bool(active))
        self.container.style().unpolish(self.container); self.container.style().polish(self.container)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction(); self._set_drag_over(True)

    def dragLeaveEvent(self, event):
        self._set_drag_over(False); super().dragLeaveEvent(event)

    def dropEvent(self, event):
        self._set_drag_over(False)
        copied = False
        for url in event.mimeData().urls():
            path = Path(url.toLocalFile())
            if path.is_file() and path.suffix.casefold() == ".toml":
                copied = self._copy_in(path) or copied
            elif path.is_dir():
                for file in path.glob("*.toml"):
                    copied = self._copy_in(file) or copied
        if copied:
            self.refresh(); self.changed.emit(); event.acceptProposedAction()
        else:
            event.ignore()

    def _copy_in(self, path):
        destination = TOML_DIR / path.name
        if destination.exists() and QMessageBox.question(
                self, "Overwrite", f"Overwrite {path.name}?",
                QMessageBox.Yes | QMessageBox.No) != QMessageBox.Yes:
            return False
        shutil.copy2(path, destination)
        return True
