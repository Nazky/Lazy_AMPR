from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.param_parser import parse_game_info
from gui import styles as S
from gui.game_card import SIZES, GameCard
from gui.icons import icon_pixmap
from gui.widgets import AnimatedButton
from utils.file_ops import detect_games


class BatchPage(QWidget):
    game_added = Signal(object, object)
    start_all_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentBG")
        self.cards = {}
        self.grid_size = "Comfortable"
        self._init_ui()

    def _init_ui(self):
        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.container = QWidget()
        self.container.setMaximumWidth(1220)
        lay = QVBoxLayout(self.container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(14)
        outer.addStretch(1)
        outer.addWidget(self.container, 100)
        outer.addStretch(1)

        # ---- Header toolbar ----
        header = QFrame()
        hv = QHBoxLayout(header)
        hv.setContentsMargins(0, 4, 0, 4)
        hv.setSpacing(16)

        # Left: title + count
        title_wrap = QHBoxLayout()
        title_wrap.setSpacing(8)
        self.header = QLabel("Batch")
        self.header.setObjectName("Header")
        self.count_lbl = QLabel("")
        self.count_lbl.setObjectName("SubHeader")
        title_wrap.addWidget(self.header)
        title_wrap.addWidget(self.count_lbl)
        title_wrap.addStretch(1)
        hv.addLayout(title_wrap, 1)

        self.start_btn = AnimatedButton("Start selected", "primary", icon="play")
        self.start_btn.setFixedHeight(40)
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_all_requested.emit)
        hv.addWidget(self.start_btn)

        lay.addWidget(header)

        # ---- Stacked widget for empty vs populated states ----
        self.stack = QStackedWidget()
        
        # Empty state: big drop zone
        self.empty_state = QWidget()
        empty_lay = QVBoxLayout(self.empty_state)
        empty_lay.setAlignment(Qt.AlignCenter)
        
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("DropZone")
        self.drop_zone.setMinimumHeight(260)
        self.drop_zone.setCursor(Qt.PointingHandCursor)
        
        dz_layout = QVBoxLayout(self.drop_zone)
        dz_layout.setAlignment(Qt.AlignCenter)
        dz_layout.setSpacing(16)
        
        self.drop_icon = QLabel()
        self.drop_icon.setAlignment(Qt.AlignCenter)
        c = S.CURRENT["text_sub"]
        self.drop_icon.setPixmap(icon_pixmap("upload", 64, c))
        
        drop_title = QLabel("Drop game folders here")
        drop_title.setAlignment(Qt.AlignCenter)
        drop_title.setStyleSheet("font-size: 24px; font-weight: 700;")
        
        drop_subtitle = QLabel("or click to browse")
        drop_subtitle.setAlignment(Qt.AlignCenter)
        drop_subtitle.setObjectName("SubHeader")
        
        dz_layout.addWidget(self.drop_icon)
        dz_layout.addWidget(drop_title)
        dz_layout.addWidget(drop_subtitle)
        
        empty_lay.addWidget(self.drop_zone)
        self.stack.addWidget(self.empty_state)

        # Populated state: small drop zone + grid
        self.populated_state = QWidget()
        pop_lay = QVBoxLayout(self.populated_state)
        pop_lay.setContentsMargins(0, 0, 0, 0)
        pop_lay.setSpacing(16)
        
        # Small upload div
        self.small_drop = QFrame()
        self.small_drop.setObjectName("SmallDropZone")
        self.small_drop.setFixedHeight(88)
        self.small_drop.setCursor(Qt.PointingHandCursor)
        
        sd_layout = QHBoxLayout(self.small_drop)
        sd_layout.setAlignment(Qt.AlignCenter)
        sd_layout.setSpacing(12)
        
        self.small_drop_icon = QLabel()
        self.small_drop_icon.setPixmap(icon_pixmap("plus", 32, c))
        
        small_drop_text = QLabel("Drop more games or click to browse")
        small_drop_text.setObjectName("SubHeader")
        
        sd_layout.addWidget(self.small_drop_icon)
        sd_layout.addWidget(small_drop_text)
        
        pop_lay.addWidget(self.small_drop)
        
        # Grid
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea{border:none;background:transparent;}")
        self.host = QWidget()
        self.host.setObjectName("ContentBG")
        self.host.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        
        self.grid = QGridLayout(self.host)
        self.grid.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.grid.setContentsMargins(4, 4, 4, 8)
        self.grid.setSpacing(16)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        
        self.scroll.setWidget(self.host)
        pop_lay.addWidget(self.scroll, 1)
        
        self.stack.addWidget(self.populated_state)
        lay.addWidget(self.stack, 1)

        self.setAcceptDrops(True)
        self.drop_zone.setAcceptDrops(True)
        self.small_drop.setAcceptDrops(True)
        
        # Click handlers for drop zones
        self.drop_zone.mousePressEvent = lambda e: self._browse_games()
        self.small_drop.mousePressEvent = lambda e: self._browse_games()

    def _browse_games(self):
        from PySide6.QtWidgets import QFileDialog
        paths = QFileDialog.getExistingDirectory(self, "Select game folders")
        if paths:
            self.add_paths([Path(paths)])

    # ------------------------------------------------------------------ DnD
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._set_drag_over(True)
        else:
            super().dragEnterEvent(event)

    def dragLeaveEvent(self, event):
        self._set_drag_over(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent):
        self._set_drag_over(False)
        if event.mimeData().hasUrls():
            paths = []
            for url in event.mimeData().urls():
                local_path = url.toLocalFile()
                if local_path:
                    paths.append(Path(local_path))
            if paths:
                self.add_paths(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _set_drag_over(self, on):
        for zone in (self.drop_zone, self.small_drop):
            zone.setProperty("drag", on)
            zone.style().unpolish(zone)
            zone.style().polish(zone)

    # ------------------------------------------------------------------ Logic
    def add_paths(self, paths):
        for p in paths:
            for g in detect_games(p, max_depth=4):
                self.add_game(g)

    def add_game(self, game_dir):
        key = str(game_dir)
        if key in self.cards:
            return

        card = GameCard(parse_game_info(game_dir))
        card.apply_size(self.grid_size)
        card.selection_changed.connect(self._selection_changed)
        self.cards[key] = card
        self.game_added.emit(game_dir, card)
        self._update_state()
        self._reflow()
        self._count()

    def selected_cards(self):
        return [
            (key, card) for key, card in self.cards.items()
            if card.selected_for_batch
        ]

    def _selection_changed(self, _selected=None):
        self.start_btn.setEnabled(bool(self.selected_cards()))
        self._count()

    def _update_state(self):
        if len(self.cards) == 0:
            self.stack.setCurrentWidget(self.empty_state)
        else:
            self.stack.setCurrentWidget(self.populated_state)

    def _count(self):
        n = len(self.cards)
        selected = len(self.selected_cards())
        if not n:
            self.count_lbl.setText("")
            return
        self.count_lbl.setText(
            f"·  {n} game{'s' if n != 1 else ''} · {selected} selected"
        )

    def _reflow(self):
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it.widget():
                it.widget().setParent(None)

        viewport_width = max(1, self.scroll.viewport().width() - 8)
        cols = self._columns_for_width(viewport_width)
        self.column_count = cols

        for i, c in enumerate(self.cards.values()):
            self.grid.addWidget(c, i // cols, i % cols)

    def _columns_for_width(self, available_width):
        card_width = SIZES.get(self.grid_size, SIZES["Comfortable"])[0]
        gap = self.grid.spacing()
        possible = max(1, (available_width + gap) // (card_width + gap))
        return min(5, len(self.cards), possible)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Defer one tick so the scroll viewport has its final width before reflow
        QTimer.singleShot(0, self._reflow)
