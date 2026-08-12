"""PageScroll — the shared scrollable container for both pages.

Every BriizFlow page is a vertically scrolling column of sections with a page
title up top. This is that pattern, once. The container keeps a trailing
stretch so content stays top-aligned; ``add_title``/``add``/``add_layout``
insert *before* that stretch, so ordering is natural no matter the mix.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from app.ui.components.labels import PageSubtitle, Title
from app.ui.theme import dimensions

_TOP_MARGIN = dimensions.PAGE_PADDING_TOP


class PageScroll(QScrollArea):
    """A vertically scrolling page with a title and a content column."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        self._body = QWidget()
        self._layout = QVBoxLayout(self._body)
        self._layout.setContentsMargins(
            dimensions.PAGE_MARGIN,
            _TOP_MARGIN,
            dimensions.PAGE_MARGIN,
            dimensions.PAGE_PADDING_BOTTOM,
        )
        self._layout.setSpacing(dimensions.SPACE_L)
        self._layout.addStretch(1)  # trailing stretch; inserts go before it

        self.setWidget(self._body)

    def add_title(self, text):
        self._layout.insertWidget(self._layout.count() - 1, Title(text))

    def add_subtitle(self, text):
        self._layout.insertWidget(self._layout.count() - 1, PageSubtitle(text))

    def add(self, widget):
        self._layout.insertWidget(self._layout.count() - 1, widget)

    def add_layout(self, layout):
        container = QWidget()
        container.setLayout(layout)
        self._layout.insertWidget(self._layout.count() - 1, container)

    def add_spacing(self, px):
        """Insert empty vertical space before the trailing stretch, so content
       -heavy pages can breathe at the bottom instead of hugging the edge."""
        self._layout.insertSpacing(self._layout.count() - 1, px)
