'''BriizFlow dark theme: palette (colors.py), metrics (dimensions.py), the QSS
stylesheet (dark.qss) and its application (theme.py::apply_theme).

Global design changes should be made here — colors.py and dimensions.py feed
every token the stylesheet uses, and the components style themselves through
QSS rather than inline pixel values.
'''
from app.ui.theme.theme import apply_theme, build_stylesheet, tokens
__all__ = [
    'apply_theme',
    'build_stylesheet',
    'tokens']
