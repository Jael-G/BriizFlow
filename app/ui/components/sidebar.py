"""Sidebar navigation — the fixed left rail of the AppWindow.

* ``NavItem`` — a checkable nav button. The active state shows a 3px accent
  bar at the left edge (painted, not ``border-left``, so the bar never shifts
  the label) and re-tints its icon to the accent color. Selecting it while it
  is already the active page re-emits ``clicked`` (Qt's exclusive groups skip
  that), so the AppWindow can refresh-on-click.
* ``Sidebar`` — the rail itself: brand header (app icon + name), the stacked
  NavItems as one exclusive ``QButtonGroup``, and a stretch at the bottom to
  keep the items pinned under the brand.
"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.gui.icon import make_app_icon
from app.ui.icons import icon
from app.ui.theme import colors, dimensions

_ICON_COLORS = {"normal": colors.TEXT_MUTED, "hover": colors.TEXT, "checked": colors.ACCENT}


class NavItem(QPushButton):
    """A checkable sidebar nav button with a painted active bar."""

    def __init__(self, label, icon_name, parent=None):
        super().__init__(label, parent)
        self.setObjectName("navItem")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._icon_name = icon_name
        self._icon_color = _ICON_COLORS["normal"]
        self._refresh_icon()
        self.toggled.connect(self._on_toggled)

    def _refresh_icon(self):
        color = self._icon_color
        self.setIcon(icon(self._icon_name, dimensions.NAV_ICON_SIZE, color=color))
        self.setIconSize(QSize(dimensions.NAV_ICON_SIZE, dimensions.NAV_ICON_SIZE))

    def _on_toggled(self, checked):
        self._icon_color = _ICON_COLORS["checked"] if checked else _ICON_COLORS["normal"]
        self._refresh_icon()

    def enterEvent(self, event):
        if not self.isChecked():
            self._icon_color = _ICON_COLORS["hover"]
            self._refresh_icon()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if not self.isChecked():
            self._icon_color = _ICON_COLORS["normal"]
            self._refresh_icon()
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.isChecked():
            painter = QPainter(self)
            painter.fillRect(0, 0, 3, self.height(), QColor(colors.ACCENT))
            painter.end()


class Sidebar(QFrame):
    """The fixed left rail: brand header + exclusive nav items."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(dimensions.SIDEBAR_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 12)
        layout.setSpacing(4)

        # Brand header.
        brand = QHBoxLayout()
        brand.setContentsMargins(dimensions.SPACE_L, 0, dimensions.SPACE_L, 8)
        brand_icon = QLabel()
        brand_icon.setPixmap(make_app_icon(dimensions.BRAND_ICON_SIZE).pixmap(dimensions.BRAND_ICON_SIZE))
        brand.addWidget(brand_icon)
        brand_name = QLabel("BriizFlow")
        brand_name.setObjectName("brandName")
        brand.addWidget(brand_name)
        brand.addStretch(1)
        layout.addLayout(brand)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self.items = []

        layout.addStretch(1)

    def add_item(self, label, icon_name):
        item = NavItem(label, icon_name)
        self._group.addButton(item)
        layout = self.layout()
        layout.insertWidget(layout.count() - 1, item)
        self.items.append(item)
        return item
