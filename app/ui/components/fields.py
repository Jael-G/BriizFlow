"""Input fields: TextField, ComboBox and an editable ComboBox.

Thin wrappers over the native Qt widgets; all visual styling (including the
dropdown popup) lives in the global QSS. The ComboBox paints its own chevron
because QSS ``image:`` can't load an in-memory pixmap.
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QLineEdit

from app.ui.theme import colors


class TextField(QLineEdit):
    """A styled single-line text input."""

    def __init__(self, text="", placeholder="", parent=None):
        super().__init__(text, parent)
        if placeholder:
            self.setPlaceholderText(placeholder)


class PasswordField(TextField):
    """A password input whose content is masked."""

    def __init__(self, text="", placeholder="", parent=None):
        super().__init__(text, placeholder, parent)
        self.setEchoMode(QLineEdit.Password)


class ComboBox(QComboBox):
    """A styled dropdown that paints its own chevron."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pen = QPen(QColor(colors.TEXT_MUTED))
        pen.setWidthF(1.4)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        x = self.width() - 16
        y = self.height() / 2
        painter.drawLine(x - 3, y - 2, x, y + 1)
        painter.drawLine(x, y + 1, x + 3, y - 2)
        painter.end()


class EditableComboBox(ComboBox):
    """A combo whose text can also be typed directly."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)


class HotkeyCapture(QLineEdit):
    """A click-to-capture hotkey field.

    Click the field and press the desired shortcut; it records the combo
    automatically (e.g. ``Ctrl+Shift+A`` -> ``"ctrl+shift+a"``) and emits
    ``captured`` with the normalized string. ``Esc`` cancels the capture.
    """

    captured = Signal(str)

    _KEY_NAMES = {
        Qt.Key_Space: "space",
        Qt.Key_Return: "enter",
        Qt.Key_Enter: "enter",
        Qt.Key_Escape: "escape",
        Qt.Key_Tab: "tab",
        Qt.Key_Backspace: "backspace",
        Qt.Key_Delete: "delete",
        Qt.Key_Home: "home",
        Qt.Key_End: "end",
        Qt.Key_Up: "up",
        Qt.Key_Down: "down",
        Qt.Key_Left: "left",
        Qt.Key_Right: "right",
        Qt.Key_PageUp: "pageup",
        Qt.Key_PageDown: "pagedown",
    }

    def __init__(self, combo="", placeholder="Press keys…", parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setPlaceholderText(placeholder)
        self._combo = combo or ""
        self._capturing = False
        self.setText(self._display(self._combo))

    def combo(self):
        """The normalized combo (e.g. ``"ctrl+shift+a"``)."""
        return self._combo

    def mousePressEvent(self, event):
        self._begin_capture()
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        self._begin_capture()
        super().focusInEvent(event)

    def _begin_capture(self):
        if not self._capturing:
            self._capturing = True
            self.setText("")
            self.setPlaceholderText("Press keys…")

    def keyPressEvent(self, event):
        if not self._capturing:
            event.ignore()
            return
        key = event.key()
        if key == Qt.Key_Escape:
            self._cancel()
            event.accept()
            return
        if key in (Qt.Key_Control, Qt.Key_Shift, Qt.Key_Alt, Qt.Key_Meta):
            event.accept()  # a modifier on its own — wait for the real key
            return
        combo = self._build_combo(event)
        if combo:
            self._finish(combo)
        event.accept()

    def _build_combo(self, event):
        parts = []
        mods = event.modifiers()
        if mods & Qt.ControlModifier:
            parts.append("ctrl")
        if mods & Qt.ShiftModifier:
            parts.append("shift")
        if mods & Qt.AltModifier:
            parts.append("alt")
        if mods & Qt.MetaModifier:
            parts.append("super")
        key = event.key()
        name = self._KEY_NAMES.get(key)
        if name is None:
            name = QKeySequence(key).toString(QKeySequence.PortableText).lower()
            if not name:
                return ""
        parts.append(name)
        return "+".join(parts)

    def _finish(self, combo):
        self._capturing = False
        self._combo = combo
        self.setText(self._display(combo))
        self.setPlaceholderText("")
        self.clearFocus()
        self.captured.emit(combo)

    def _cancel(self):
        self._capturing = False
        self.setText(self._display(self._combo))
        self.clearFocus()

    def focusOutEvent(self, event):
        if self._capturing:
            self._cancel()
        super().focusOutEvent(event)

    @staticmethod
    def _display(combo):
        if not combo:
            return ""
        return "+".join(part[:1].upper() + part[1:] for part in combo.split("+"))
