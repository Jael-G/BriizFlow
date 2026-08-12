"""AppWindow — the app shell: sidebar nav + stacked pages + toast host.

This replaces qfluentwidgets' ``FluentWindow`` 1:1. Everything the controller
and tests touch is preserved:

* ``.settings_page`` / ``.models_page`` — the two pages
* ``show_settings()`` / ``show_models()`` — switch + bring the window forward
* ``closeEvent`` hides (the singleton stays alive for the tray to reopen)
* ``show_toast(kind, title, message, duration_ms)`` — the in-app fallback
  used when no desktop notification daemon is reachable (feedback normally
  goes to ``app.notifications.system_notify``), routed to the floating
  ``ToastHost``

The window is a plain ``QMainWindow``: a ``Sidebar`` on the left and a
``QStackedWidget`` of pages to the right. Toasts float top-center, above the
pages, and never reserve layout space.
"""

from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QStackedWidget, QWidget

from app.ui.components.sidebar import Sidebar
from app.ui.components.toast import ToastHost
from app.ui.pages.models_page import ModelsPage
from app.ui.pages.settings_page import SettingsPage
from app.ui.theme import dimensions


class AppWindow(QMainWindow):
    """The main settings/models window (lives for the tray to reopen)."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self.setWindowTitle("BriizFlow")
        self.setObjectName("appRoot")
        self.resize(dimensions.WINDOW_W, dimensions.WINDOW_H)
        self.setMinimumSize(dimensions.WINDOW_MIN_W, dimensions.WINDOW_MIN_H)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.sidebar = Sidebar()
        root.addWidget(self.sidebar)

        self.pages = QStackedWidget()
        self.models_page = ModelsPage(settings)
        self.settings_page = SettingsPage(settings)
        self.pages.addWidget(self.models_page)
        self.pages.addWidget(self.settings_page)
        root.addWidget(self.pages, 1)
        self.setCentralWidget(central)

        self._nav_settings = self.sidebar.add_item("Settings", "settings")
        self._nav_models = self.sidebar.add_item("Models", "cpu")
        self._nav_settings.clicked.connect(self.show_settings)
        self._nav_models.clicked.connect(self.show_models)
        self._nav_settings.setChecked(True)
        self.pages.setCurrentWidget(self.settings_page)

        # Floating toast host, above the pages, never reserving space.
        self._toast_host = ToastHost(self)
        self._toast_host.hide()

    # --- page switching -----------------------------------------------------
    def show_settings(self):
        self.pages.setCurrentWidget(self.settings_page)
        self._nav_settings.setChecked(True)
        self._bring_forward()

    def show_models(self):
        self.pages.setCurrentWidget(self.models_page)
        self._nav_models.setChecked(True)
        self._bring_forward()

    def _bring_forward(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        # Hide instead of quitting; the tray reopens the window.
        event.ignore()
        self.hide()

    def show_toast(self, kind, title, message, duration_ms=4000):
        self._toast_host.show_toast(kind, title, message, duration_ms)
