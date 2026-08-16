"""Settings row + group — the 11×-repeated row pattern in the settings page.

A ``SettingRow`` is a title, an optional description, an optional leading
icon, and a right-aligned control strip. Each row is its own rounded card
(see the ``QFrame#settingRow`` rule in ``dark.qss``), so every setting reads
as a distinct surface the way each model does on the Models page. Rows are
stacked inside a ``SettingGroup``, which is just the section header plus the
spacing between cards.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from app.ui.components.labels import BodyStrong, Caption
from app.ui.icons import icon
from app.ui.theme import dimensions


class SettingRow(QFrame):
    """A titled row with a right-aligned control strip."""

    def __init__(self, title, description=None, icon_name=None, parent=None):
        super().__init__(parent)
        self.setObjectName("settingRow")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(12)

        if icon_name:
            icon_label = QLabel()
            icon_label.setPixmap(icon(icon_name, dimensions.ROW_ICON_SIZE).pixmap(dimensions.ROW_ICON_SIZE))
            layout.addWidget(icon_label)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        text_col.addWidget(BodyStrong(title))
        layout.addLayout(text_col, 1)

        self._text_col = text_col
        self._description = None
        if description:
            self.set_description(description)

        self.controls = QHBoxLayout()
        self.controls.setSpacing(8)
        layout.addLayout(self.controls)

    def set_description(self, text):
        """Set or replace the row's description text.

        Rows whose description depends on the current control value (e.g. a
        combo that explains the selected option) update this instead of
        rebuilding the row. The label is rich text so a value name can be
        emboldened; plain strings render unchanged.
        """
        if self._description is None:
            self._description = Caption(text)
            self._description.setWordWrap(True)
            self._description.setTextFormat(Qt.RichText)
            self._text_col.addWidget(self._description)
        else:
            self._description.setText(text)

    def add_widget(self, widget):
        self.controls.addWidget(widget)

    def add_layout(self, layout):
        self.controls.addLayout(layout)


class SettingGroup(QFrame):
    """A section header plus its stacked rows."""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("settingGroup")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        header = Caption(title)
        header.setObjectName("groupHeader")
        layout.addWidget(header)
        self._rows = layout

    def add_row(self, row):
        self._rows.addWidget(row)
