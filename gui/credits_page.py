from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from gui import styles as S
from gui.icons import icon_pixmap
from gui.widgets import AnimatedButton

CONTRIBUTORS = (
    (
        "Nazky",
        "https://github.com/Nazky",
        "N",
        "#0a84ff",
        "Project creator and main development.",
    ),
    (
        "Deckerr97",
        "https://github.com/kerrdec97",
        "D",
        "#a56eff",
        "Development, testing and support.",
    ),
    (
        "Pippo",
        "https://github.com/Pippo26442999",
        "P",
        "#4fd06f",
        "Development, testing and support.",
    ),
    (
        "drakmor",
        "https://github.com/drakmor",
        "D",
        "#ffad32",
        "Thank you to drakmor for his hard work on LZ4 and related tooling that made this possible.",
    ),
)


class InitialAvatar(QWidget):
    def __init__(self, initial, accent, parent=None):
        super().__init__(parent)
        self.initial = initial
        self.accent = QColor(accent)
        self.setFixedSize(72, 72)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(4, 4, self.width() - 8, self.height() - 8)
        painter.setBrush(QColor(S.CURRENT["bg_input"]))
        painter.setPen(QPen(self.accent, 4))
        painter.drawEllipse(rect)
        font = QFont(self.font())
        font.setPointSize(20)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QColor(S.CURRENT["text_main"]))
        painter.drawText(self.rect(), Qt.AlignCenter, self.initial)


class IconBadge(QWidget):
    def __init__(self, icon, parent=None):
        super().__init__(parent)
        self.icon = icon
        self.setFixedSize(56, 56)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(S.CURRENT["nav_selected"]))
        painter.drawEllipse(self.rect())
        size = 30
        painter.drawPixmap(
            (self.width() - size) // 2,
            (self.height() - size) // 2,
            icon_pixmap(self.icon, size, S.CURRENT["accent"]),
        )


class ContributorCard(QFrame):
    def __init__(self, name, url, initial, accent, description, parent=None):
        super().__init__(parent)
        self.setObjectName("ContributorCard")
        self.url = url
        self._compact = None
        self.setMinimumHeight(116)
        self.setMinimumWidth(0)
        self.setAttribute(Qt.WA_Hover, True)

        self.layout = QGridLayout(self)
        self.layout.setContentsMargins(24, 18, 22, 18)
        self.layout.setHorizontalSpacing(20)
        self.layout.setVerticalSpacing(5)

        self.avatar = InitialAvatar(initial, accent)

        self.name_label = QLabel(name)
        self.name_label.setObjectName("CreditName")

        self.link_button = AnimatedButton(url, "link", icon="github")
        self.link_button.setAccessibleName(f"Open {name} on GitHub")
        self.link_button.setToolTip(f"Open {url} in the default browser")
        self.link_button.setMinimumWidth(0)
        self.link_button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.link_button.clicked.connect(self._open_link)

        self.detail = QLabel(description)
        self.detail.setObjectName("SubHeader")
        self.detail.setWordWrap(True)
        self.detail.setMinimumWidth(0)
        self.detail.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        self.external_button = AnimatedButton("", "icon", icon="external")
        self.external_button.setFixedSize(46, 46)
        self.external_button.setAccessibleName(f"Open {name} GitHub profile")
        self.external_button.setToolTip(f"Open {url} in the default browser")
        self.external_button.clicked.connect(self._open_link)
        self._reflow(False)

    def _reflow(self, compact):
        compact = bool(compact)
        if compact == self._compact:
            return
        self._compact = compact
        while self.layout.count():
            self.layout.takeAt(0)
        for column in range(3):
            self.layout.setColumnStretch(column, 0)
        if compact:
            self.setMinimumHeight(166)
            self.layout.setContentsMargins(18, 16, 18, 16)
            self.layout.addWidget(self.avatar, 0, 0, 2, 1, Qt.AlignVCenter)
            self.layout.addWidget(self.name_label, 0, 1)
            self.layout.addWidget(self.external_button, 0, 2, 2, 1, Qt.AlignVCenter)
            self.layout.addWidget(self.link_button, 2, 0, 1, 3)
            self.layout.addWidget(self.detail, 3, 0, 1, 3)
        else:
            self.setMinimumHeight(116)
            self.layout.setContentsMargins(24, 18, 22, 18)
            self.layout.addWidget(self.avatar, 0, 0, 3, 1, Qt.AlignVCenter)
            self.layout.addWidget(self.name_label, 0, 1)
            self.layout.addWidget(self.link_button, 1, 1, Qt.AlignLeft)
            self.layout.addWidget(self.detail, 2, 1)
            self.layout.addWidget(self.external_button, 0, 2, 3, 1, Qt.AlignVCenter)
        self.layout.setColumnStretch(1, 1)

    def _open_link(self):
        target = QUrl(self.url)
        if (
            not target.isValid()
            or target.scheme() != "https"
            or target.host().casefold() != "github.com"
        ):
            QMessageBox.warning(
                self, "Could not open GitHub", "The GitHub link is invalid."
            )
            return
        if not QDesktopServices.openUrl(target):
            QMessageBox.warning(
                self,
                "Could not open GitHub",
                f"The system browser could not open:\n{self.url}",
            )

    def enterEvent(self, event):
        self.setProperty("hover", True)
        self.style().unpolish(self)
        self.style().polish(self)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setProperty("hover", False)
        self.style().unpolish(self)
        self.style().polish(self)
        super().leaveEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow(self.width() < 520)


class CreditsPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ContentBG")

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
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 8)
        layout.setSpacing(14)

        title = QLabel("Credits")
        title.setObjectName("Header")
        subtitle = QLabel("Lazy_AMPR was created with contributions from:")
        subtitle.setObjectName("SubHeader")
        subtitle.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(subtitle)

        self.cards = []
        for contributor in CONTRIBUTORS:
            card = ContributorCard(*contributor)
            self.cards.append(card)
            layout.addWidget(card)

        thanks = QFrame()
        thanks.setObjectName("CreditsThanks")
        thanks_layout = QHBoxLayout(thanks)
        thanks_layout.setContentsMargins(24, 18, 24, 18)
        thanks_layout.setSpacing(18)
        self.heart = IconBadge("heart")
        thanks_layout.addWidget(self.heart, 0, Qt.AlignVCenter)
        thanks_text = QWidget()
        thanks_text_layout = QVBoxLayout(thanks_text)
        thanks_text_layout.setContentsMargins(0, 0, 0, 0)
        thanks_text_layout.setSpacing(4)
        thanks_title = QLabel("Thank you")
        thanks_title.setObjectName("SectionTitle")
        thanks_copy = QLabel(
            "Lazy_AMPR is made possible by the work and support of the community.\n"
            "Special thanks to Nazky, Deckerr97, Pippo and drakmor."
        )
        thanks_copy.setObjectName("SubHeader")
        thanks_copy.setWordWrap(True)
        thanks_text_layout.addWidget(thanks_title)
        thanks_text_layout.addWidget(thanks_copy)
        thanks_layout.addWidget(thanks_text, 1)
        layout.addWidget(thanks)
        layout.addStretch(1)

        host_layout.addStretch(1)
        host_layout.addWidget(content, 100)
        host_layout.addStretch(1)
        self.scroll.setWidget(host)
        outer.addWidget(self.scroll)

    def refresh_theme(self):
        for card in self.cards:
            card.avatar.update()
            card.link_button.update()
            card.external_button.update()
        self.heart.update()
