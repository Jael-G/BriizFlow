"""Cards and badges.

* ``Panel`` — a base framed surface.
* ``ModelCard`` — one model row in the Models page. The public button
  attributes (``active_badge``, ``set_active_btn``, ``remove_btn``,
  ``download_btn``, ``progress_bar``, ``cancel_btn``) are the contract the
  page and its tests rely on; the page fills them in.
* ``Badge`` — the small "✓ Active" status pill.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from app.ui.components.labels import BodyStrong, Caption


def format_size(size_mb):
    """Format a model size in MB as a short human string."""
    if size_mb >= 1024:
        return "%.1f GB" % (size_mb / 1024)
    return "%d MB" % size_mb


class Panel(QFrame):
    """A base framed surface."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")


class ModelCard(Panel):
    """One model row in the Models page; the page wires the actions."""

    def __init__(self, name, size_mb, parent=None):
        super().__init__(parent)
        self.setObjectName("modelCard")
        self.model_name = name
        self.size_mb = size_mb

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(12)
        self.name_label = BodyStrong(name)
        self.size_label = Caption(format_size(size_mb))
        self.size_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        top.addWidget(self.name_label)
        top.addWidget(self.size_label)

        # The page owns the active badge (only downloaded models get one) and
        # places it in the actions area, where "Set Active" normally sits.
        self.active_badge = None  # Badge, created by the page
        self.remove_btn = None  # filled in by the page (danger)
        self.set_active_btn = None  # filled in by the page (success)
        self.download_btn = None  # filled in by the page (primary)
        self.cancel_btn = None  # filled in by the page (danger)
        self.progress_bar = None  # filled in by the page

        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        self.actions.addStretch(1)
        top.addLayout(self.actions)
        outer.addLayout(top)


class Badge(QLabel):
    """The small "✓ Active" status pill."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setObjectName("badge")
        self.setAlignment(Qt.AlignCenter)
