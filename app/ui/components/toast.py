"""Toast notifications — the InfoBar replacement.

Pages call :func:`show_toast` with themselves as the anchor. Feedback is
posted as a **desktop notification** via :func:`app.notifications.system_notify`
so it appears even when the main window is hidden; the floating ``ToastHost``
below is kept only as a fallback for when no notification daemon is reachable.
:func:`show_toast` resolves the top-level window and, if that window exposes
``show_toast``, posts there. For a standalone widget (e.g. a page built
directly in a test) it is a silent no-op.

Dismissal is a plain ``QTimer.singleShot`` → ``deleteLater``: correctness
never depends on animation, and toasts that outlive a test's non-running event
loop are simply torn down with their parent.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from app import notifications

VALID_KINDS = ("info", "success", "error")
_TEXT_MAX_WIDTH = 348


class Toast(QFrame):
    """A single floating toast card."""

    def __init__(self, kind, title, message, parent=None):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setProperty("kind", kind if kind in VALID_KINDS else "info")
        self.setMaximumWidth(_TEXT_MAX_WIDTH)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        title_label = QLabel(title)
        title_label.setObjectName("bodyStrong")
        message_label = QLabel(message)
        message_label.setObjectName("caption")
        message_label.setWordWrap(True)
        text_col.addWidget(title_label)
        text_col.addWidget(message_label)
        layout.addLayout(text_col)


class ToastHost(QWidget):
    """Floating top-center container that stacks toasts."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 8, 0, 0)
        self._layout.setSpacing(8)
        self._layout.setAlignment(Qt.AlignTop | Qt.AlignHCenter)

    def show_toast(self, kind, title, message, duration_ms=4000):
        toast = Toast(kind, title, message, self)
        self._layout.addWidget(toast)
        self.adjustSize()
        if not self.isVisible():
            self.show()
        QTimer.singleShot(duration_ms, toast.deleteLater)


def show_toast(widget, kind, title, message, duration_ms=4000):
    """Post a desktop notification; fall back to an in-app toast when unreachable."""
    if notifications.system_notify(kind, title, message):
        return
    win = widget.window()
    if win is not None and hasattr(win, "show_toast"):
        win.show_toast(kind, title, message, duration_ms)
