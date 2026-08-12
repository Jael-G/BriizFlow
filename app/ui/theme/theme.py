"""Theme application: turns colors.py + dimensions.py + dark.qss into the
app-wide stylesheet, and wires it onto the QApplication.

Call ``apply_theme(app)`` once at startup (app/main.py), right after the
QApplication is created. It replaces the old ``configure_fluent()``: there is
no lazy import cost and nothing is written to disk.
"""

import os
from string import Template

from PySide6.QtGui import QColor, QFont, QPalette

from app.ui.theme import colors, dimensions

_QSS_PATH = os.path.join(os.path.dirname(__file__), "dark.qss")
_FONT_FAMILIES = ["Inter", "Noto Sans", "Cantarell", "Ubuntu"]


def tokens():
    """Flatten the palette + dimensions into the QSS template's $tokens."""
    out = {}
    for module in (colors, dimensions):
        for name, value in vars(module).items():
            if not name.startswith("_"):
                out[name] = value
    return out


def build_stylesheet():
    """Interpolate the palette into dark.qss. Returns the QSS string.

    Uses ``string.Template`` (``$name``), not ``str.format``: QSS is full of
    literal ``{}`` braces that would need escaping.
    """
    with open(_QSS_PATH, encoding="utf-8") as fh:
        template = fh.read()
    return Template(template).safe_substitute(tokens())


def _dark_palette():
    """A dark QPalette fallback for the native bits QSS can't reach (menus,
    tooltips, scrollbars, dialog internals) when the style is Fusion."""
    p = QPalette()
    roles = {
        QPalette.ColorRole.PlaceholderText: colors.TEXT_MUTED,
        QPalette.ColorRole.ToolTipText: colors.TEXT,
        QPalette.ColorRole.ToolTipBase: colors.SURFACE,
        QPalette.ColorRole.HighlightedText: colors.ON_ACCENT,
        QPalette.ColorRole.Highlight: colors.ACCENT,
        QPalette.ColorRole.ButtonText: colors.TEXT,
        QPalette.ColorRole.Button: colors.SURFACE_2,
        QPalette.ColorRole.Text: colors.TEXT,
        QPalette.ColorRole.WindowText: colors.TEXT,
        QPalette.ColorRole.AlternateBase: colors.SURFACE,
        QPalette.ColorRole.Base: colors.SURFACE_2,
        QPalette.ColorRole.Window: colors.BG,
    }
    for role, value in roles.items():
        p.setColor(role, QColor(value))
    for group in (QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
        p.setColor(group, QPalette.ColorRole.Text, QColor(colors.TEXT_DISABLED))
    return p


def _configure_font(app):
    font = QFont()
    if hasattr(font, "setFamilies"):
        font.setFamilies(_FONT_FAMILIES)
    else:
        font.setFamily(_FONT_FAMILIES[0])
    font.setPixelSize(dimensions.FONT_BODY)
    app.setFont(font)


def apply_theme(app):
    """Apply the full BriizFlow dark theme to ``app`` (a QApplication). Idempotent."""
    app.setStyle("Fusion")
    app.setPalette(_dark_palette())
    app.setStyleSheet(build_stylesheet())
    _configure_font(app)
