from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap

try:
    from PySide6.QtSvg import QSvgRenderer

    HAS_SVG = True
except ImportError:
    HAS_SVG = False

_WRAP = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">{}</svg>'
_SVGS = {
    "target": '<circle cx="12" cy="12" r="8" fill="none" stroke="{c}" stroke-width="2"/><circle cx="12" cy="12" r="3" fill="{c}"/>',
    "grid": '<rect x="4" y="4" width="7" height="7" rx="1.5" fill="{c}"/><rect x="13" y="4" width="7" height="7" rx="1.5" fill="{c}"/><rect x="4" y="13" width="7" height="7" rx="1.5" fill="{c}"/><rect x="13" y="13" width="7" height="7" rx="1.5" fill="{c}"/>',
    "gear": '<line x1="4" y1="7" x2="20" y2="7" stroke="{c}" stroke-width="2" stroke-linecap="round"/><circle cx="9" cy="7" r="2.5" fill="{c}"/><line x1="4" y1="12" x2="20" y2="12" stroke="{c}" stroke-width="2" stroke-linecap="round"/><circle cx="15" cy="12" r="2.5" fill="{c}"/><line x1="4" y1="17" x2="20" y2="17" stroke="{c}" stroke-width="2" stroke-linecap="round"/><circle cx="7" cy="17" r="2.5" fill="{c}"/>',
    "log": '<line x1="4" y1="6" x2="20" y2="6" stroke="{c}" stroke-width="2" stroke-linecap="round"/><line x1="4" y1="12" x2="20" y2="12" stroke="{c}" stroke-width="2" stroke-linecap="round"/><line x1="4" y1="18" x2="14" y2="18" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
    "play": '<path d="M8 5.5v13l11-6.5z" fill="{c}"/>',
    "clock": '<circle cx="12" cy="12" r="8" fill="none" stroke="{c}" stroke-width="2"/><path d="M12 8v4l3 2" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
    "chart": '<polyline points="4,17 9,11 13,14 20,6" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
    "download": '<path d="M12 4v10" stroke="{c}" stroke-width="2" stroke-linecap="round"/><polyline points="7,10 12,15 17,10" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M5 19h14" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" fill="{c}"/>',
    "plus": '<path d="M12 5v14M5 12h14" stroke="{c}" stroke-width="2.5" stroke-linecap="round"/>',
    "warn": '<path d="M12 4l9 16H3z" fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round"/><line x1="12" y1="10" x2="12" y2="15" stroke="{c}" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="17.5" r="1.2" fill="{c}"/>',
    "save": '<path d="M5 3h11l3 3v15H5z" fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round"/><rect x="8" y="3" width="7" height="5" fill="none" stroke="{c}" stroke-width="2"/><rect x="8" y="13" width="8" height="8" fill="none" stroke="{c}" stroke-width="2"/>',
    "game": '<rect x="3" y="8" width="18" height="10" rx="4" fill="none" stroke="{c}" stroke-width="2"/><path d="M8 11v4M6 13h4" stroke="{c}" stroke-width="2" stroke-linecap="round"/><circle cx="16" cy="12" r="1.4" fill="{c}"/><circle cx="18.5" cy="14.5" r="1.4" fill="{c}"/>',
    "check": '<polyline points="5,13 10,18 19,7" fill="none" stroke="{c}" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>',
    "link": '<path d="M10 13a5 5 0 0 0 7.5.5l2-2a5 5 0 0 0-7-7l-1.2 1.2" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/><path d="M14 11a5 5 0 0 0-7.5-.5l-2 2a5 5 0 0 0 7 7l1.2-1.2" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
    "users": '<circle cx="9" cy="8" r="3" fill="none" stroke="{c}" stroke-width="2"/><path d="M3.5 19c.4-4 2.3-6 5.5-6s5.1 2 5.5 6" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/><circle cx="17" cy="9" r="2.3" fill="none" stroke="{c}" stroke-width="1.8"/><path d="M16 14c2.8 0 4.4 1.6 4.7 4.5" fill="none" stroke="{c}" stroke-width="1.8" stroke-linecap="round"/>',
    "doc": '<rect x="5" y="3" width="14" height="18" rx="2" fill="none" stroke="{c}" stroke-width="2"/><line x1="9" y1="9" x2="15" y2="9" stroke="{c}" stroke-width="2"/><line x1="9" y1="13" x2="15" y2="13" stroke="{c}" stroke-width="2"/>',
    "extract": '<path d="M12 3v10" stroke="{c}" stroke-width="2" stroke-linecap="round"/><polyline points="8,7 12,3 16,7" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M4 13v6a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-6" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
    "github": '<path d="M12 2.8a9.2 9.2 0 0 0-2.9 17.9c.5.1.7-.2.7-.5v-1.8c-2.8.6-3.4-1.2-3.4-1.2-.5-1.2-1.1-1.5-1.1-1.5-.9-.6.1-.6.1-.6 1 0 1.6 1 1.6 1 .9 1.6 2.4 1.1 2.9.9.1-.7.4-1.1.7-1.3-2.3-.3-4.7-1.1-4.7-5.1 0-1.1.4-2 1-2.8-.1-.3-.4-1.3.1-2.7 0 0 .8-.3 2.8 1.1a9.5 9.5 0 0 1 5 0c1.9-1.3 2.8-1.1 2.8-1.1.5 1.4.2 2.4.1 2.7.6.8 1 1.7 1 2.8 0 4-2.4 4.8-4.7 5.1.4.3.7 1 .7 1.9v2.7c0 .3.2.6.7.5A9.2 9.2 0 0 0 12 2.8z" fill="{c}"/>',
    "external": '<path d="M13 4h7v7" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/><path d="M20 4l-9 9" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/><path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
    "sun": '<circle cx="12" cy="12" r="4" fill="none" stroke="{c}" stroke-width="2"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
    "moon": '<path d="M20 15.3A8 8 0 0 1 8.7 4a8.5 8.5 0 1 0 11.3 11.3z" fill="none" stroke="{c}" stroke-width="2" stroke-linejoin="round"/>',
    "monitor": '<rect x="3" y="4" width="18" height="13" rx="2" fill="none" stroke="{c}" stroke-width="2"/><path d="M8 21h8M12 17v4" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/>',
    "help": '<circle cx="12" cy="12" r="9" fill="none" stroke="{c}" stroke-width="2"/><path d="M9.7 9a2.4 2.4 0 1 1 3.6 2.1c-.9.5-1.3 1-1.3 2" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="17" r="1" fill="{c}"/>',
    "heart": '<path d="M20.8 5.8a5 5 0 0 0-7.1 0L12 7.5l-1.7-1.7a5 5 0 0 0-7.1 7.1L12 21l8.8-8.1a5 5 0 0 0 0-7.1z" fill="none" stroke="{c}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
}
_CACHE = {}


def device_pixel_ratio():
    screen = QGuiApplication.primaryScreen()
    return max(1.0, float(screen.devicePixelRatio())) if screen else 1.0


def icon_pixmap(name: str, size: int = 16, color: str = "#ffffff") -> QPixmap:
    dpr = device_pixel_ratio()
    key = (name, size, color, dpr)
    pm = _CACHE.get(key)
    if pm is not None:
        return pm
    physical_size = max(1, round(size * dpr))
    pm = QPixmap(physical_size, physical_size)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    if HAS_SVG and name in _SVGS:
        r = QSvgRenderer(QByteArray(_WRAP.format(_SVGS[name].format(c=color)).encode()))
        p = QPainter(pm)
        r.render(p, QRectF(0, 0, size, size))
        p.end()
    _CACHE[key] = pm
    return pm
