import os

from PySide6.QtCore import (
    Property,
    QEasingCurve,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QSlider,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

from gui import styles as S
from gui.icons import icon_pixmap


class ElidingLabel(QLabel):
    """Single-line label that never pushes neighbouring controls off-screen."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(0)
        self.setToolTip(text)

    def setText(self, text):
        super().setText(text)
        self.setToolTip(text)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setFont(self.font())
        color = (
            S.CURRENT["text_sub"]
            if self.objectName() in {"Subtitle", "BadgeText"}
            else S.CURRENT["text_main"]
        )
        painter.setPen(QColor(color))
        text = self.fontMetrics().elidedText(
            self.text(), Qt.ElideRight, self.contentsRect().width()
        )
        painter.drawText(self.contentsRect(), Qt.AlignLeft | Qt.AlignVCenter, text)


def _lerp(a, b, t):
    if t <= 0:
        return QColor(a)
    if t >= 1:
        return QColor(b)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
        int(a.alpha() + (b.alpha() - a.alpha()) * t),
    )


def fade_in(widget, duration=180):
    widget.show()
    from PySide6.QtWidgets import QGraphicsOpacityEffect

    eff = QGraphicsOpacityEffect(widget)
    widget.setGraphicsEffect(eff)
    a = QPropertyAnimation(eff, b"opacity", widget)
    a.setDuration(duration)
    a.setStartValue(0.0)
    a.setEndValue(1.0)
    a.finished.connect(lambda: widget.setGraphicsEffect(None))
    a.start()


KINDS = {
    "nav": {"radius": 8, "pad": (8, 12)},
    "primary": {"radius": 10, "pad": (9, 16)},
    "big": {"radius": 11, "pad": (11, 28)},
    "secondary": {"radius": 10, "pad": (9, 14)},
    "ghost": {"radius": 10, "pad": (8, 10)},
    "icon": {"radius": 10, "pad": (9, 9)},
    "link": {"radius": 8, "pad": (5, 7)},
}


class AnimatedButton(QPushButton):
    def __init__(self, text="", kind="secondary", icon=None, parent=None):
        super().__init__(text, parent)
        self.setObjectName("AnimBtn")
        self.kind = kind
        self.icon_name = icon
        self._ht = 0.0
        self._pt = 0.0
        self.setFlat(True)  # skip native bevel/hover paint entirely
        self.setFocusPolicy(Qt.StrongFocus)
        self._ha = QPropertyAnimation(self, b"hoverT", self)
        self._ha.setDuration(130)
        self._ha.setEasingCurve(QEasingCurve.OutCubic)
        self._pa = QPropertyAnimation(self, b"pressT", self)
        self._pa.setDuration(90)
        self._pa.setEasingCurve(QEasingCurve.OutCubic)
        self.setCursor(Qt.PointingHandCursor)

    def getHoverT(self):
        return self._ht

    def setHoverT(self, v):
        self._ht = v
        self.update()

    hoverT = Property(float, getHoverT, setHoverT)

    def getPressT(self):
        return self._pt

    def setPressT(self, v):
        self._pt = v
        self.update()

    pressT = Property(float, getPressT, setPressT)

    def set_icon(self, name):
        self.icon_name = name
        self.update()

    def _anim(self, anim, target):
        cur = self._ht if anim is self._ha else self._pt
        anim.stop()
        anim.setStartValue(cur)
        anim.setEndValue(target)
        anim.start()

    def enterEvent(self, e):
        self._anim(self._ha, 1.0)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._anim(self._ha, 0.0)
        self._anim(self._pa, 0.0)
        super().leaveEvent(e)

    def mousePressEvent(self, e):
        self._anim(self._pa, 1.0)
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        self._anim(self._pa, 0.0)
        super().mouseReleaseEvent(e)

    def sizeHint(self):
        ph, pw = KINDS[self.kind]["pad"]
        fm = self.fontMetrics()
        extra = 26 if self.kind == "nav" else (22 if self.icon_name else 0)
        return QSize(
            fm.horizontalAdvance(self.text()) + pw * 2 + extra, fm.height() + ph * 2 + 2
        )

    def _colors(self):
        t = S.CURRENT
        checked = self.isCheckable() and self.isChecked()
        if self.kind == "nav":
            hover = QColor(t["selected"]) if not checked else QColor(t["nav_selected"])
            # base uses the SAME rgb as hover but alpha 0, so the fade-in is a
            # pure opacity ramp — not a color shift. Using QColor(0,0,0,0) here
            # would interpolate through translucent BLACK on the way to grey,
            # which is invisible on dark backgrounds but shows as a dark
            # flash/smear on light backgrounds.
            base = (
                QColor(t["nav_selected"])
                if checked
                else QColor(hover.red(), hover.green(), hover.blue(), 0)
            )
            press = _lerp(hover, QColor(t["border"]), 0.6)
            text = QColor(t["accent"]) if checked else QColor(t["text_main"])
        elif self.kind in ("primary", "big"):
            base = QColor(t["accent"])
            hover = QColor(t["accent_hover"])
            press = _lerp(QColor(t["accent"]), QColor("#003d99"), 0.55)
            text = QColor("#ffffff")
        elif self.kind in ("ghost", "icon"):
            hover = QColor(t["selected"])
            press = QColor(t["border"])
            text = QColor(t["text_sub"])
            base = QColor(hover.red(), hover.green(), hover.blue(), 0)
        elif self.kind == "link":
            hover = QColor(t["accent"])
            hover.setAlpha(34)
            press = QColor(t["selected"])
            text = QColor(t["accent"])
            base = QColor(hover.red(), hover.green(), hover.blue(), 0)
        else:
            base = QColor(t["bg_card"])
            hover = QColor(t["selected"])
            press = QColor(t["border_soft"])
            text = QColor(t["text_main"])
        if not self.isEnabled():
            base = QColor(t["selected"])
            hover = base
            press = base
            text = QColor(t["text_sub"])
        return base, hover, press, text

    def paintEvent(self, ev):
        base, hover, press, text = self._colors()
        col = _lerp(_lerp(base, hover, self._ht), press, self._pt)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = KINDS[self.kind]["radius"]
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), r, r)
        if col.alpha() > 0:
            p.fillPath(path, col)
        if self.kind in ("secondary", "ghost", "icon"):
            border = QColor(
                S.CURRENT["border"] if self.isEnabled() else S.CURRENT["border_soft"]
            )
            p.setPen(QPen(border, 1))
            p.drawPath(path)
        if self.hasFocus():
            p.setPen(QPen(QColor(S.CURRENT["accent"]), 2))
            p.drawRoundedRect(
                QRectF(2, 2, self.width() - 4, self.height() - 4),
                max(2, r - 2),
                max(2, r - 2),
            )
        fm = self.fontMetrics()
        tw = fm.horizontalAdvance(self.text())
        isp = max(14, fm.height() - 4) if self.icon_name else 0
        gap = 7 if isp else 0
        x = 12 if self.kind == "nav" else max(8, (self.width() - (tw + isp + gap)) // 2)
        if isp:
            p.drawPixmap(
                x,
                (self.height() - isp) // 2,
                icon_pixmap(self.icon_name, isp, text.name()),
            )
            x += isp + gap
        p.setPen(text)
        p.setFont(self.font())
        p.drawText(
            QRect(x, 0, self.width() - x - 8, self.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            self.text(),
        )
        p.end()


class _CenterDelegate(QStyledItemDelegate):
    def initStyleOption(self, opt, index):
        super().initStyleOption(opt, index)
        opt.displayAlignment = Qt.AlignCenter


class CenteredComboBox(QComboBox):
    """Theme-aware combobox with animated chevron."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._arrow = 0.0
        self._hover = 0.0
        self._anim = QPropertyAnimation(self, b"arrowT", self)
        self._anim.setDuration(200)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._hover_anim = QPropertyAnimation(self, b"hoverT", self)
        self._hover_anim.setDuration(150)
        self._hover_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.setItemDelegate(_CenterDelegate(self))
        self.setCursor(Qt.PointingHandCursor)
        self._style_popup()

    def _style_popup(self):
        """Force popup to follow app theme."""
        t = S.CURRENT
        view = self.view()
        view.setStyleSheet(f"""
            QListView {{
                background: {t["bg_card"]};
                color: {t["text_main"]};
                border: 1px solid {t["border_soft"]};
                padding: 4px;
                outline: none;
            }}
            QListView::item {{
                padding: 8px 16px;
                color: {t["text_main"]};
            }}
            QListView::item:selected {{
                background: {t["accent_tint"]};
                color: {t["accent"]};
            }}
            QListView::item:hover {{
                background: {t["selected"]};
            }}
        """)

    def getArrowT(self):
        return self._arrow

    def setArrowT(self, v):
        self._arrow = v
        self.update()

    arrowT = Property(float, getArrowT, setArrowT)

    def getHoverT(self):
        return self._hover

    def setHoverT(self, v):
        self._hover = v
        self.update()

    hoverT = Property(float, getHoverT, setHoverT)

    def enterEvent(self, e):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(1.0)
        self._hover_anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover_anim.stop()
        self._hover_anim.setStartValue(self._hover)
        self._hover_anim.setEndValue(0.0)
        self._hover_anim.start()
        super().leaveEvent(e)

    def showPopup(self):
        # Re-apply theme right before opening (covers theme switches at runtime)
        self._style_popup()
        # Make sure the popup is at least as wide as the combo and never clipped
        self.view().setMinimumWidth(max(self.width(), 110))
        self._anim.stop()
        self._anim.setStartValue(self._arrow)
        self._anim.setEndValue(1.0)
        self._anim.start()
        super().showPopup()

    def sizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(90, 32)

    def minimumSizeHint(self):
        from PySide6.QtCore import QSize

        return QSize(80, 30)

    def hidePopup(self):
        self._anim.stop()
        self._anim.setStartValue(self._arrow)
        self._anim.setEndValue(0.0)
        self._anim.start()
        super().hidePopup()

    def paintEvent(self, e):
        t = S.CURRENT
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Fill entire rect with theme background
        p.fillRect(self.rect(), QColor(t["bg_input"]))

        # Simple square border
        if self.view().isVisible():
            border_color = QColor(t["accent"])
            border_width = 2
        elif self._hover > 0:
            base_border = QColor(t["border"])
            accent = QColor(t["accent"])
            border_color = _lerp(base_border, accent, self._hover * 0.6)
            border_width = 1
        else:
            border_color = QColor(t["border"])
            border_width = 1

        p.setPen(QPen(border_color, border_width))
        p.setBrush(QColor(t["bg_input"]))
        p.drawRect(
            self.rect().adjusted(
                border_width // 2,
                border_width // 2,
                -border_width // 2,
                -border_width // 2,
            )
        )

        # Text
        p.setPen(QColor(t["text_main"]))
        p.setFont(self.font())
        text_rect = self.rect().adjusted(12, 0, -32, 0)
        p.drawText(text_rect, Qt.AlignCenter, self.currentText())

        # Animated chevron
        p.save()
        p.translate(self.width() - 16, self.height() / 2.0)
        p.rotate(180.0 * self._arrow)

        chev_color = QColor(t["text_sub"])
        if self._hover > 0 or self.view().isVisible():
            chev_color = _lerp(chev_color, QColor(t["accent"]), max(self._hover, 0.7))

        chev = QPainterPath()
        chev.moveTo(-4, -2)
        chev.lineTo(0, 2)
        chev.lineTo(4, -2)
        p.setPen(QPen(chev_color, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(chev)
        p.restore()
        p.end()


class SegmentedControl(QFrame):
    value_changed = Signal(str)

    def __init__(self, options, current=None, icons=None, parent=None):
        super().__init__(parent)
        self.setObjectName("Segmented")
        self._icons = icons or {}
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for opt in options:
            b = QPushButton(opt)
            b.setObjectName("SegBtn")
            b.setCheckable(True)
            b.setChecked(opt == current)
            b.setCursor(Qt.PointingHandCursor)
            self.group.addButton(b)
            lay.addWidget(b)
        self.group.buttonClicked.connect(lambda b: self.value_changed.emit(b.text()))
        self.group.buttonToggled.connect(lambda *_: self.refresh_theme())
        self.refresh_theme()

    def set_value(self, v):
        for b in self.group.buttons():
            b.setChecked(b.text() == v)

    def refresh_theme(self):
        for button in self.group.buttons():
            icon_name = self._icons.get(button.text())
            if icon_name:
                color = (
                    S.CURRENT["accent"]
                    if button.isChecked()
                    else S.CURRENT["text_main"]
                )
                button.setIcon(QIcon(icon_pixmap(icon_name, 17, color)))
                button.setIconSize(QSize(17, 17))


class SectionCard(QFrame):
    def __init__(self, title=None, description=None, label_width=150, parent=None):
        super().__init__(parent)
        self.setObjectName("Section")
        self._label_width = label_width
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(18, 16, 18, 18)
        self._lay.setSpacing(14)
        if title:
            if description:
                header = QWidget()
                header_layout = QVBoxLayout(header)
                header_layout.setContentsMargins(0, 0, 0, 0)
                header_layout.setSpacing(3)
                t = QLabel(title)
                t.setObjectName("SectionTitle")
                detail = QLabel(description)
                detail.setObjectName("SubHeader")
                detail.setWordWrap(True)
                header_layout.addWidget(t)
                header_layout.addWidget(detail)
                self._lay.addWidget(header)
            else:
                t = QLabel(title)
                t.setObjectName("SectionTitle")
                self._lay.addWidget(t)
        self._rows = QGridLayout()
        self._rows.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._rows.setHorizontalSpacing(12)
        self._rows.setVerticalSpacing(16)
        self._row = 0
        self._compact = False
        self._responsive_rows = []
        self._lay.addLayout(self._rows)
        self._lay.addStretch(1)

    def _divider(self):
        line = QFrame()
        line.setObjectName("Divider")
        line.setFixedHeight(1)
        self._rows.addWidget(line, self._row, 0, 1, 4)
        self._row += 1

    def add_row(self, label, *widgets, stretch_last=True, divider=False):  # opt-in
        lb = None
        if label:
            lb = QLabel(label)
            lb.setObjectName("InfoKey")
            lb.setMinimumWidth(self._label_width)
        self._responsive_rows.append(("row", lb, widgets, stretch_last, divider))
        self._rebuild_rows()

    def add_widget(self, w):
        self._responsive_rows.append(("widget", w))
        self._rebuild_rows()

    def set_compact(self, compact):
        compact = bool(compact)
        if compact != self._compact:
            self._compact = compact
            self._rebuild_rows()

    def _rebuild_rows(self):
        while self._rows.count():
            self._rows.takeAt(0)
        # QGridLayout keeps column stretch factors after its items are removed.
        # Reset them before changing between compact and desktop layouts so the
        # fixed label column cannot inherit the compact layout's stretch.
        for column in range(4):
            self._rows.setColumnStretch(column, 0)
        self._row = 0
        for item in self._responsive_rows:
            if item[0] == "widget":
                self._rows.addWidget(item[1], self._row, 0, 1, 4)
                self._row += 1
                continue
            _, label, widgets, stretch_last, divider = item
            if divider and self._row:
                self._divider()
            if self._compact and label is not None:
                label.setMinimumWidth(0)
                self._rows.addWidget(label, self._row, 0, 1, 4, Qt.AlignLeft)
                self._row += 1
                col = 0
            else:
                if label is not None:
                    label.setMinimumWidth(self._label_width)
                    self._rows.addWidget(
                        label, self._row, 0, Qt.AlignLeft | Qt.AlignVCenter
                    )
                    col = 1
                else:
                    col = 0
            for i, widget in enumerate(widgets):
                self._rows.addWidget(widget, self._row, col + i)
            if widgets and stretch_last:
                self._rows.setColumnStretch(col + len(widgets) - 1, 1)
            self._row += 1


class StatusBadge(QFrame):
    """Compact text badge used for status and low-emphasis metadata."""

    def __init__(self, text="", icon=None, parent=None):
        super().__init__(parent)
        self.setObjectName("StatusBadge")
        h = QHBoxLayout(self)
        h.setContentsMargins(9, 4, 9, 4)
        h.setSpacing(6)
        self.icon = QLabel()
        self.label = QLabel(text)
        self.label.setObjectName("BadgeText")
        self.icon_name = icon
        if icon:
            self.refresh_theme()
        else:
            self.icon.hide()
        h.addWidget(self.icon)
        h.addWidget(self.label)
        self.setMaximumWidth(260)

    def setText(self, text):
        self.label.setText(text)
        self.setToolTip(text)

    def refresh_theme(self):
        if self.icon_name:
            self.icon.setPixmap(icon_pixmap(self.icon_name, 13, S.CURRENT["text_sub"]))


class LevelSlider(QWidget):
    value_changed = Signal(int)

    def __init__(self, value=9, parent=None):
        super().__init__(parent)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(1, 12)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.slider.setPageStep(1)
        self.slider.setFixedWidth(240)
        self.slider.setValue(value)
        self.lbl = QLabel()
        self.lbl.setFixedWidth(102)
        self.lbl.setStyleSheet("margin-left: 4px;")
        self.slider.valueChanged.connect(self._on)
        h.addWidget(self.slider)
        h.addWidget(self.lbl)
        h.addStretch(1)  # ← pushes slider+label to the left
        self._on(value)

    def _tag(self, v):
        return "Fast" if v <= 4 else ("Balanced" if v <= 8 else "Max")

    def _on(self, v):
        mode = "fast" if v <= 4 else "hc"
        self.lbl.setText(f"{v} · {self._tag(v)} ({mode})")
        self.value_changed.emit(v)

    def value(self):
        return self.slider.value()

    def set_value(self, v):
        try:
            self.slider.setValue(int(v))
        except RuntimeError:
            pass  # C++ object not ready — ignore, slider already has the right value


class WorkerSlider(QWidget):
    value_changed = Signal(int)

    def __init__(self, value=None, parent=None):
        super().__init__(parent)
        self.max_w = max(1, (os.cpu_count() or 2) - 1)  # cpu-1, never saturate the PC
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.slider = QSlider(Qt.Horizontal)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.slider.setRange(1, self.max_w)
        self.slider.setPageStep(1)
        self.slider.setFixedWidth(240)
        self.slider.setValue(value if value else self.max_w)
        self.lbl = QLabel()
        self.lbl.setFixedWidth(106)
        self.slider.valueChanged.connect(self._on)
        h.addWidget(self.slider)
        h.addWidget(self.lbl)
        self._on(self.slider.value())

    def _on(self, v):
        self.lbl.setText(f"{v} / {self.max_w} threads")
        self.value_changed.emit(v)

    def value(self):
        return self.slider.value()

    def set_value(self, v):
        self.slider.setValue(min(max(1, int(v)), self.max_w))
