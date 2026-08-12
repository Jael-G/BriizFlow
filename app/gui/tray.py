"""System tray icon and menu."""

from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app.gui.icon import tray_icon


class SystemTray(QSystemTrayIcon):
    """Tray icon whose menu drives the dictation controller."""

    def __init__(self, controller, parent=None):
        super().__init__(tray_icon(), parent)
        self._controller = controller
        self.setToolTip("BriizFlow — voice dictation")
        self._build_menu()
        self.activated.connect(self._on_activated)

    def _build_menu(self):
        menu = QMenu()
        self.dictate_action = menu.addAction("Dictate")
        menu.addSeparator()
        self.settings_action = menu.addAction("Settings…")
        self.models_action = menu.addAction("Models…")
        menu.addSeparator()
        self.quit_action = menu.addAction("Quit")
        self.setContextMenu(menu)

        self.dictate_action.triggered.connect(self._controller.toggle)
        self.settings_action.triggered.connect(self._controller.open_settings)
        self.models_action.triggered.connect(self._controller.open_model_manager)
        self.quit_action.triggered.connect(self._controller.quit)

    def _on_activated(self, reason):
        # Left-click toggles dictation like the hotkey.
        if reason == QSystemTrayIcon.Trigger:
            self._controller.toggle()
