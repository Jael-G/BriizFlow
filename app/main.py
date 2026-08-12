"""BriizFlow entry point.

Usage::

    python -m app.main            # start (stays in the tray)
    python -m app.main --settings # open settings immediately
    briizflow                      # if installed with `pip install -e .`
"""

import argparse
import logging
import os
import sys

from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication

from app.application import DictationController
from app.config.settings import Settings, cache_dir, config_dir
from app.gui.icon import make_app_icon
from app.gui.overlay import Overlay
from app.gui.tray import SystemTray
from app.input.text_injector import create_injector
from app.models.manager import migrate_legacy_model_path
from app.notifications import start as start_notifications
from app.ui.theme import apply_theme


def main(argv=None):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("briizflow.main")
    parser = argparse.ArgumentParser(
        prog="briizflow",
        description="BriizFlow — voice-to-text dictation for Linux (local whisper.cpp or online OpenAI)",
    )
    parser.add_argument("--settings", action="store_true", help="open the Settings page on start")
    args = parser.parse_args(argv)

    os.makedirs(config_dir(), exist_ok=True)
    os.makedirs(cache_dir(), exist_ok=True)

    # Single-instance lock.
    lock = QLockFile(os.path.join(cache_dir(), "briizflow.lock"))
    if not lock.tryLock(100):
        print("BriizFlow is already running.", file=sys.stderr)
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName("BriizFlow")
    app.setApplicationDisplayName("BriizFlow")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(make_app_icon(64))
    apply_theme(app)
    start_notifications()

    settings = Settings()
    migrate_legacy_model_path(settings)

    overlay = Overlay(settings)
    injector = create_injector(settings)
    controller = DictationController(settings, overlay, injector)
    controller.cleanup_temp()
    controller.create_hotkeys()
    controller.start_whisper()

    tray = SystemTray(controller)
    controller.attach_tray(tray)
    tray.show()

    if args.settings:
        QTimer.singleShot(300, controller.open_settings)
    elif not settings.get("model_name"):
        QTimer.singleShot(300, controller.open_model_manager)

    log.info("%s started (hotkey: %s)", "BriizFlow", settings.get("hotkey"))
    code = app.exec()
    lock.unlock()
    return code


if __name__ == "__main__":
    sys.exit(main())
