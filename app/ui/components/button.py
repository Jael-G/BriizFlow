"""BriizFlow's single button component.

One class, three visual variants selected through a dynamic Qt property that
the global QSS reacts to:

* ``"secondary"`` — the default quiet bordered button (Refresh, Browse, …)
* ``"primary"``   — the accent-filled call-to-action (Set Active, Download)
* ``"danger"``    — destructive action (Remove) in subtle red text

The property is set in ``__init__`` (before the widget is first polished), so
the stylesheet picks it up with no re-polish dance.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

VALID_VARIANTS = ("secondary", "primary", "success", "danger")


class Button(QPushButton):
    def __init__(self, text="", variant="secondary", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.set_variant(variant)

    def set_variant(self, variant):
        """Switch the visual variant; re-polishes so the QSS re-evaluates."""
        variant = variant if variant in VALID_VARIANTS else "secondary"
        self.setProperty("variant", variant)
        self.style().unpolish(self)
        self.style().polish(self)
