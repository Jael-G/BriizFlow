"""BriizFlow's icon set, rendered at runtime from bundled Lucide SVG assets.

The line icons used to be hand-drawn with QPainter; they're now the Lucide
icon set (ISC license — see ``lucide/LICENSE``) rendered through
``QSvgRenderer``. This keeps the crisp 2x-DPR output, adds no third-party
runtime dependency, and lets every icon be recolored on demand: Lucide icons
are ``stroke="currentColor"``, so the token is swapped for the target color
at render time (nav items re-tint on hover/active).

Use::

    from app.ui.icons import icon
    btn.setIcon(icon("gear", 16))

Unknown names fall back to a neutral circle so callers never crash on a typo.
"""

import os

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer

from app.ui.theme import colors

DEFAULT_COLOR = colors.TEXT_MUTED
_LUCIDE_DIR = os.path.join(os.path.dirname(__file__), "lucide")


def _read_svg(name):
    path = os.path.join(_LUCIDE_DIR, name + ".svg")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _recolor(svg, color):
    return svg.replace("currentColor", color)


def icon(name, size, color=None):
    """Return a ``QIcon`` for the named Lucide icon at ``size`` px."""
    color = color or DEFAULT_COLOR
    svg = _read_svg(name)
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if svg is None:
        # Neutral circle fallback so callers never crash on a typo.
        painter.setPen(QPen(QColor(color)))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    else:
        renderer = QSvgRenderer(QByteArray(_recolor(svg, color).encode("utf-8")))
        # The pixmap is size*2 physical px at DPR 2, so painting happens in
        # logical coordinates (0..size); rendering into size*2 would cram the
        # glyph into the upper-left corner.
        renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return QIcon(pm)
