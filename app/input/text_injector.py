"""Text injection base and factory.

Injection works by putting the transcript on the clipboard and then sending a
paste shortcut to the currently focused application (which is what "insert at
cursor" means without a universal input-injection API on Linux).

The actual key sending is backend-specific and clearly separated:

* :class:`app.input.x11_injector.X11Injector` — XTEST via python-xlib.
* :class:`app.input.wayland_injector.WaylandInjector` — best-effort, requires
  ``ydotool`` or ``wtype`` (see the module docstring there).

Both put text on the clipboard first. The clipboard itself is managed through
Qt (works on X11 and Wayland), with ``wl-copy`` preferred on Wayland.
"""

import logging

from PySide6.QtCore import QEventLoop, QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from app.util import session_type

log = logging.getLogger(__name__)


class TextInjector(QObject):
    """Base class for clipboard+paste injectors."""

    injected = Signal()
    failed = Signal(str)

    def inject(self, text):
        raise NotImplementedError

    def _pump_events(self, ms):
        """Run the Qt event loop for `ms` ms (lets clipboard ownership settle)."""
        loop = QEventLoop(self)
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def _clipboard_set(self, text):
        QApplication.clipboard().setText(text)
        self._pump_events(120)


def create_injector(settings, parent=None):
    """Build the injector for the current session (or an explicit override)."""
    backend = (settings.get("paste_backend") or "auto").strip().lower()
    if backend == "auto":
        backend = session_type() or "x11"
    if backend == "wayland":
        from app.input.wayland_injector import WaylandInjector

        return WaylandInjector(settings, parent)
    from app.input.x11_injector import X11Injector

    return X11Injector(settings, parent)
