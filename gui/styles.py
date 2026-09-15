import platform

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette

# ---------------------------------------------------------------------------
# Palettes — tuned to match macOS HIG system colors
# (Big Sur/Sonoma "systemBlue", "labelColor", "separatorColor", etc.)
# ---------------------------------------------------------------------------
THEMES = {
    "light": {
        "bg_window": "#ececec",
        "bg_sidebar": "#f6f6f6",
        "bg_card": "#ffffff",
        "bg_card_hover": "#f9f9fb",
        "bg_drop": "#fbfbfb",
        "bg_input": "#ffffff",
        "bg_console": "#f7f7f7",
        "text_main": "#1d1d1f",
        "text_sub": "#6e6e73",
        "text_tertiary": "#a1a1a6",
        "border": "#d1d1d6",
        "border_soft": "#e5e5ea",
        "accent": "#007aff",
        "accent_hover": "#0060df",
        "accent_tint": "rgba(0,122,255,0.12)",
        "nav_selected": "#dceafe",
        "selected": "#e4e4e9",
        "selected_text": "#0b57d0",
        "error": "#ff3b30",
        "warning": "#ff9500",
        "success": "#34c759",
        "shadow": "rgba(0,0,0,30)",
        "track": "#d6d6db",
    },
    "dark": {
        "bg_window": "#1e1e1e",
        "bg_sidebar": "#242426",
        "bg_card": "#2c2c2e",
        "bg_card_hover": "#3a3a3c",
        "bg_drop": "#232325",
        "bg_input": "#1c1c1e",
        "bg_console": "#161618",
        "text_main": "#f5f5f7",
        "text_sub": "#98989d",
        "text_tertiary": "#6e6e73",
        "border": "#3a3a3c",
        "border_soft": "#333335",
        "accent": "#0a84ff",
        "accent_hover": "#409cff",
        "accent_tint": "rgba(10,132,255,0.20)",
        "nav_selected": "#0d3a66",
        "selected": "#3a3a3c",
        "selected_text": "#7cb4ff",
        "error": "#ff453a",
        "warning": "#ff9f0a",
        "success": "#30d158",
        "shadow": "rgba(0,0,0,140)",
        "track": "#48484a",
    },
}

CURRENT = THEMES["light"]

# ---------------------------------------------------------------------------
# Fonts — best native family per-OS with sane fallbacks
# ---------------------------------------------------------------------------
_SYS = platform.system()

if _SYS == "Darwin":
    FONT_STACK = '"SF Pro Text", "Helvetica Neue", Arial, sans-serif'
    MONO_STACK = '"SF Mono", Menlo, monospace'
elif _SYS == "Windows":
    FONT_STACK = '"Segoe UI Variable", "Segoe UI", "Helvetica Neue", Arial, sans-serif'
    MONO_STACK = '"Cascadia Code", Consolas, monospace'
else:
    FONT_STACK = '"Ubuntu", "Noto Sans", "Cantarell", "DejaVu Sans", Arial, sans-serif'
    MONO_STACK = '"Ubuntu Mono", "DejaVu Sans Mono", "Noto Sans Mono", monospace'


def resolve_theme(name):
    n = (name or "auto").strip().lower()
    if n == "auto":
        try:
            dark = QGuiApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
        except (AttributeError, RuntimeError):
            dark = False
        n = "dark" if dark else "light"
    return n if n in THEMES else "light"


# ---------------------------------------------------------------------------
# QSS fragment helpers — keep button variants consistent & DRY
# ---------------------------------------------------------------------------
def _solid_button(
    t,
    sel,
    *,
    bg,
    hover,
    pressed=None,
    radius=8,
    pad="7px 16px",
    size=13,
    weight=600,
    text="#ffffff",
):
    p = pressed or hover
    return f"""
    {sel} {{ background-color: {bg}; color: {text}; border: none;
        border-radius: {radius}px; padding: {pad}; font-size: {size}px; font-weight: {weight}; }}
    {sel}:hover {{ background-color: {hover}; }}
    {sel}:pressed {{ background-color: {p}; }}
    {sel}:disabled {{ background-color: {t["selected"]}; color: {t["text_sub"]}; }}
    """


def _input_focus_sel(*names):
    return ",\n    ".join(f"{n}:focus" for n in names)


_INPUTS = "QLineEdit, QSpinBox, QDoubleSpinBox, QDateEdit, QDateTimeEdit"


def get_stylesheet(theme_name):
    global CURRENT
    t = THEMES[resolve_theme(theme_name)]
    CURRENT = t

    btn_primary = _solid_button(
        t, "QPushButton#PrimaryBtn", bg=t["accent"], hover=t["accent_hover"]
    )
    btn_big = _solid_button(
        t,
        "QPushButton#BigStartBtn",
        bg=t["accent"],
        hover=t["accent_hover"],
        radius=10,
        pad="11px 28px",
        size=14,
        weight=700,
    )
    btn_destr = _solid_button(
        t,
        "QPushButton#DestructiveBtn",
        bg=t["error"],
        hover=_darken(t["error"]),
        pressed=_darken(t["error"]),
    )

    return f"""
    * {{ font-family: {FONT_STACK}; color: {t["text_main"]}; font-size: 13px; outline: none; }}
    QMainWindow, QWidget#ContentBG {{ background-color: {t["bg_window"]}; }}
    QLabel, QGroupBox, QCheckBox, QRadioButton, QLineEdit, QComboBox, QPlainTextEdit,
    QTextEdit, QListWidget, QTreeWidget, QTableWidget, QTabBar {{ color: {t["text_main"]}; }}
    QToolTip {{ background-color: {t["bg_card"]}; color: {t["text_main"]}; border: 1px solid {t["border_soft"]};
        border-radius: 8px; padding: 6px 10px; font-size: 12px; }}

    /* ---------- Sidebar ---------- */
    QFrame#Sidebar {{ background-color: {t["bg_sidebar"]}; border-right: 1px solid {t["border_soft"]}; }}
    QLabel#Brand {{ font-size: 17px; font-weight: 800; color: {t["accent"]}; }}
    QLabel#SideFoot {{ font-size: 11px; color: {t["text_sub"]}; }}
    /* Sidebar nav buttons are AnimatedButton instances — fully custom-painted
       in gui/widgets.py; the #AnimBtn rule below just resets QSS painting. */

    /* ---------- Typography ---------- */
    QLabel#Header {{ font-size: 26px; font-weight: 700; letter-spacing: -0.3px; }}
    QLabel#SubHeader {{ font-size: 13px; color: {t["text_sub"]}; }}
    QLabel#Subtitle {{ font-size: 12px; color: {t["text_sub"]}; }}
    QLabel#CardTitle {{ font-size: 13px; font-weight: 600; }}
    QLabel#CreditName {{ font-size: 17px; font-weight: 700; }}
    QLabel#SectionTitle {{ font-size: 15px; font-weight: 700; }}
    QLabel#InfoKey {{ font-size: 12px; color: {t["text_sub"]}; }}
    QLabel#InfoVal {{ font-size: 13px; font-weight: 600; }}
    QLabel#BadgeText {{ font-size: 11px; color: {t["text_sub"]}; }}
    QLabel[error="true"] {{ color: {t["error"]}; }}
    QLabel[warning="true"] {{ color: {t["warning"]}; }}

    /* ---------- Surfaces ---------- */
    QFrame#DropArea {{ background-color: {t["bg_drop"]}; border: 1.5px dashed {t["border"]}; border-radius: 14px; }}
    QFrame#DropArea[drag="true"] {{ border-color: {t["accent"]}; background-color: {t["accent_tint"]}; }}
    
    /* Batch page drop zones */
    QFrame#DropZone {{ 
        background-color: {t["bg_drop"]}; 
        border: 2px dashed {t["border"]}; 
        border-radius: 16px;
        padding: 40px;
    }}
    QFrame#DropZone[drag="true"] {{ 
        border-color: {t["accent"]}; 
        background-color: {t["accent_tint"]};
    }}
    QFrame#SmallDropZone {{ 
        background-color: {t["bg_drop"]}; 
        border: 1.5px dashed {t["border"]}; 
        border-radius: 10px;
    }}
    QFrame#SmallDropZone[drag="true"] {{ 
        border-color: {t["accent"]}; 
        background-color: {t["accent_tint"]};
    }}
    
    /* Game card — background is now painted in paintEvent, but keep border/radius for fallback */
    QFrame#GameCard {{ background-color: transparent; border: none; border-radius: 16px; }}
    QFrame#Section {{ background-color: {t["bg_card"]}; border: 1px solid {t["border_soft"]}; border-radius: 14px; }}
    QFrame#StatusBadge {{ background-color: {t["selected"]}; border: 1px solid {t["border_soft"]}; border-radius: 10px; }}
    QFrame#StatusBadge[warning="true"] {{ background-color: {t["bg_input"]}; border-color: {t["warning"]}; }}
    QFrame#ContributorCard, QFrame#CreditsThanks {{ background-color: {t["bg_card"]}; border: 1px solid {t["border_soft"]}; border-radius: 14px; }}
    QFrame#ContributorCard[hover="true"] {{ background-color: {t["bg_card_hover"]}; border-color: {t["border"]}; }}
    QFrame#TomlDropSurface {{ background: transparent; border: 1px solid transparent; border-radius: 14px; }}
    QFrame#TomlDropSurface[drag="true"] {{ background-color: {t["accent_tint"]}; border: 1.5px dashed {t["accent"]}; }}
    QFrame#Divider {{ background-color: {t["border_soft"]}; max-height: 1px; border: none; }}
    QFrame[hline="true"] {{ background-color: {t["border_soft"]}; max-height: 1px; }}

    /* ---------- Buttons ---------- */
    QPushButton {{ background-color: {t["bg_card"]}; border: 1px solid {t["border"]};
        border-radius: 8px; padding: 6px 14px; font-size: 13px; }}
    QPushButton:hover {{ background-color: {t["selected"]}; }}
    QPushButton:pressed {{ background-color: {t["border_soft"]}; }}
    QPushButton:disabled {{ color: {t["text_tertiary"]}; background-color: {t["bg_card"]}; }}
    QPushButton:focus {{ border: 2px solid {t["accent"]}; }}

    /* AnimatedButton fully custom-paints itself — strip all QSS painting. */
    QPushButton#AnimBtn, QPushButton#AnimBtn:hover, QPushButton#AnimBtn:pressed,
    QPushButton#AnimBtn:checked, QPushButton#AnimBtn:disabled {{ background: transparent; border: none; padding: 0; }}
{btn_primary}{btn_big}{btn_destr}
    QPushButton#SecondaryBtn {{ background-color: {t["selected"]}; color: {t["text_main"]}; border: none;
        border-radius: 8px; padding: 7px 12px; font-size: 13px; font-weight: 500; }}
    QPushButton#SecondaryBtn:hover {{ background-color: {t["border"]}; }}
    QPushButton#SecondaryBtn:pressed {{ background-color: {t["border_soft"]}; }}
    QPushButton#SecondaryBtn:disabled {{ color: {t["text_tertiary"]}; }}

    QPushButton#GhostBtn {{ background: transparent; color: {t["text_sub"]}; border: 1px solid {t["border_soft"]};
        border-radius: 8px; padding: 6px 8px; font-size: 12px; }}
    QPushButton#GhostBtn:hover {{ color: {t["text_main"]}; border-color: {t["border"]}; background-color: {t["selected"]}; }}
    QPushButton#GhostBtn:pressed {{ background-color: {t["border_soft"]}; }}
    QPushButton#GhostBtn:disabled {{ color: {t["text_tertiary"]}; border-color: {t["border_soft"]}; }}

    /* Segmented control */
    QFrame#Segmented {{ background-color: {t["bg_input"]}; border: 1px solid {t["border_soft"]}; border-radius: 10px; }}
    QPushButton#SegBtn {{ background: transparent; border: 1px solid transparent; border-radius: 7px;
        min-height: 24px; padding: 6px 14px; font-size: 12px; font-weight: 600; }}
    QPushButton#SegBtn:hover {{ color: {t["accent"]}; }}
    QPushButton#SegBtn:checked {{ background-color: {t["accent_tint"]}; border-color: {t["accent"]}; color: {t["accent"]}; }}
    QPushButton#SegBtn:focus {{ border: 2px solid {t["accent"]}; }}
    QPushButton#SegBtn:disabled {{ color: {t["text_tertiary"]}; }}

    /* ---------- Inputs ---------- */
    {_INPUTS} {{
        background-color: {t["bg_input"]}; border: 1px solid {t["border"]};
        border-radius: 8px; padding: 7px 10px; selection-background-color: {t["accent"]};
        selection-color: #ffffff; }}
    {_input_focus_sel(*_INPUTS.split(", "))} {{ border: 1.5px solid {t["accent"]}; }}
    {_INPUTS}:disabled {{ color: {t["text_tertiary"]}; background-color: {t["bg_sidebar"]}; border-color: {t["border_soft"]}; }}
    QLineEdit[readOnly="true"] {{ color: {t["text_sub"]}; background-color: {t["bg_input"]}; }}

    QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
        width: 16px; border: none; background: transparent; }}

    QGroupBox {{ border: 1px solid {t["border_soft"]}; border-radius: 10px; margin-top: 14px; padding-top: 18px; font-weight: 600; }}
    QGroupBox::title {{ subcontrol-origin: margin; left: 14px; padding: 0 5px; color: {t["text_sub"]}; }}

    /* Checkboxes / radios */
    QCheckBox {{ spacing: 8px; }}
    QCheckBox::indicator, QRadioButton::indicator {{
        width: 16px; height: 16px; border: 1.5px solid {t["border"]}; background-color: {t["bg_input"]}; }}
    QCheckBox::indicator {{ border-radius: 4px; }}
    QRadioButton::indicator {{ border-radius: 8px; }}
    QCheckBox::indicator:hover, QRadioButton::indicator:hover {{ border-color: {t["accent"]}; }}
    QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
        background-color: {t["accent"]}; border-color: {t["accent"]}; }}
    QCheckBox:disabled, QRadioButton:disabled {{ color: {t["text_tertiary"]}; }}
    QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
        border-color: {t["border_soft"]}; background-color: {t["bg_sidebar"]}; }}

    /* ---------- Tabs ---------- */
    QTabWidget::pane {{ border: 1px solid {t["border_soft"]}; border-radius: 10px; top: -1px; }}
    QTabBar::tab {{ background: transparent; color: {t["text_sub"]}; padding: 7px 16px;
        margin-right: 2px; border-top-left-radius: 8px; border-top-right-radius: 8px; font-weight: 500; }}
    QTabBar::tab:selected {{ color: {t["accent"]}; font-weight: 700; border-bottom: 2px solid {t["accent"]}; }}
    QTabBar::tab:hover:!selected {{ color: {t["text_main"]}; }}
    QTabBar::tab:disabled {{ color: {t["text_tertiary"]}; }}

    /* ---------- Sliders ---------- */
    QSlider::groove:horizontal {{ height: 4px; background: {t["track"]}; border-radius: 2px; }}
    QSlider::sub-page:horizontal {{ background: {t["accent"]}; border-radius: 2px; }}
    QSlider::handle:horizontal {{ background: #ffffff; border: 1px solid {t["border"]}; width: 16px;
        height: 16px; margin: -6px 0; border-radius: 8px; }}
    QSlider::handle:horizontal:hover {{ border-color: {t["accent"]}; }}
    QSlider::handle:horizontal:disabled {{ background: {t["bg_sidebar"]}; border-color: {t["border_soft"]}; }}
    QSlider::sub-page:horizontal:disabled {{ background: {t["border_soft"]}; }}

    /* ---------- Menus & popups ---------- */
    QMenuBar {{ background-color: {t["bg_window"]}; }}
    QMenuBar::item {{ background: transparent; padding: 4px 10px; border-radius: 6px; }}
    QMenuBar::item:selected {{ background-color: {t["selected"]}; }}
    QMenu {{ background-color: {t["bg_card"]}; border: 1px solid {t["border_soft"]}; border-radius: 10px; padding: 6px; }}
    QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 6px; }}
    QMenu::item:selected {{ background-color: {t["accent_tint"]}; color: {t["accent"]}; }}
    QMenu::item:disabled {{ color: {t["text_tertiary"]}; }}
    QMenu::separator {{ height: 1px; background: {t["border_soft"]}; margin: 6px 8px; }}

    /* Default list styling — makes ALL popups (combo boxes etc.) theme-aware.
       CenteredComboBox overrides its own popup inline in gui/widgets.py. */
    QListView {{ background-color: {t["bg_card"]}; color: {t["text_main"]};
        border: 1px solid {t["border_soft"]}; padding: 4px; outline: none; }}
    QListView::item {{ padding: 6px 12px; border-radius: 6px; color: {t["text_main"]}; }}
    QListView::item:selected {{ background-color: {t["accent_tint"]}; color: {t["accent"]}; }}
    QListView::item:hover {{ background-color: {t["selected"]}; }}

    /* ---------- Progress ---------- */
    QProgressBar {{ background-color: {t["selected"]}; border: none; border-radius: 3px; height: 6px; text-align: center; }}
    QProgressBar::chunk {{ background-color: {t["accent"]}; border-radius: 3px; }}
    QProgressBar[error="true"]::chunk {{ background-color: {t["error"]}; }}
    QProgressBar[done="true"]::chunk {{ background-color: {t["success"]}; }}
    
    /* Game card progress bar */
    QProgressBar#CardProgress {{ 
        background-color: {t["border_soft"]}; 
        border: none; 
        border-radius: 3px; 
        height: 6px; 
        text-align: center; 
    }}
    QProgressBar#CardProgress::chunk {{ 
        background-color: {t["accent"]}; 
        border-radius: 3px; 
    }}
    QProgressBar#CardProgress[error="true"]::chunk {{ 
        background-color: {t["error"]}; 
    }}
    QProgressBar#CardProgress[done="true"]::chunk {{ 
        background-color: {t["success"]}; 
    }}

    /* ---------- Console / lists / scroll ---------- */
    QPlainTextEdit#Console {{ background-color: {t["bg_console"]}; border: 1px solid {t["border_soft"]};
        border-radius: 10px; font-family: {MONO_STACK}; font-size: 11px; }}
    QListWidget, QTreeWidget, QTableWidget {{ background-color: {t["bg_card"]};
        border: 1px solid {t["border_soft"]}; border-radius: 10px; }}
    QListWidget::item, QTreeWidget::item {{ padding: 5px; border-radius: 6px; }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background-color: {t["accent_tint"]}; color: {t["selected_text"]}; }}
    QHeaderView::section {{ background-color: {t["bg_sidebar"]}; color: {t["text_sub"]};
        border: none; border-bottom: 1px solid {t["border_soft"]}; padding: 6px; font-weight: 600; }}

    QScrollArea {{ border: none; background: transparent; }}
    /* Qt gotcha: the scroll content widget paints the palette's Window color
       behind everything unless made transparent — causes grey flashes on
       theme switches. */
    QScrollArea > QWidget > QWidget {{ background: transparent; }}

    QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: {t["border"]}; border-radius: 5px; min-height: 40px; }}
    QScrollBar::handle:vertical:hover {{ background: {t["text_sub"]}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
    QScrollBar::handle:horizontal {{ background: {t["border"]}; border-radius: 5px; min-width: 40px; }}
    QScrollBar::handle:horizontal:hover {{ background: {t["text_sub"]}; }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
    QAbstractScrollArea::corner {{ background: transparent; }}

    QSplitter::handle {{ background-color: {t["border_soft"]}; }}
    QSplitter::handle:hover {{ background-color: {t["accent"]}; }}

    QStatusBar {{ background-color: {t["bg_sidebar"]}; border-top: 1px solid {t["border_soft"]}; color: {t["text_sub"]}; }}
    """


def _darken(hex_color, factor=0.22):
    """Return a darkened variant of a hex color (used for pressed states)."""
    c = QColor(hex_color)
    return QColor(
        max(0, int(c.red() * (1 - factor))),
        max(0, int(c.green() * (1 - factor))),
        max(0, int(c.blue() * (1 - factor))),
    ).name()


def apply_theme(app, name):
    """Applies both the QPalette (for native widgets) and the QSS."""
    app.setStyle("Fusion")  # ensures QSS fully overrides native paint
    t = THEMES[resolve_theme(name)]
    p = QPalette()
    p.setColor(QPalette.Window, QColor(t["bg_window"]))
    p.setColor(QPalette.WindowText, QColor(t["text_main"]))
    p.setColor(QPalette.Base, QColor(t["bg_input"]))
    p.setColor(QPalette.AlternateBase, QColor(t["bg_console"]))
    p.setColor(QPalette.Text, QColor(t["text_main"]))
    p.setColor(QPalette.Button, QColor(t["selected"]))
    p.setColor(QPalette.ButtonText, QColor(t["text_main"]))
    p.setColor(QPalette.Highlight, QColor(t["accent"]))
    p.setColor(QPalette.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.Link, QColor(t["accent"]))
    p.setColor(QPalette.PlaceholderText, QColor(t["text_sub"]))
    p.setColor(QPalette.ToolTipBase, QColor(t["bg_card"]))
    p.setColor(QPalette.ToolTipText, QColor(t["text_main"]))
    p.setColor(QPalette.Light, QColor(t["border_soft"]))
    p.setColor(QPalette.Mid, QColor(t["border"]))
    p.setColor(QPalette.Dark, QColor(t["border"]))
    p.setColor(QPalette.BrightText, QColor(t["text_main"]))
    p.setColor(QPalette.Disabled, QPalette.WindowText, QColor(t["text_tertiary"]))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(t["text_tertiary"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t["text_tertiary"]))
    p.setColor(QPalette.Disabled, QPalette.Base, QColor(t["bg_sidebar"]))
    app.setPalette(p)
    app.setStyleSheet(get_stylesheet(name))
