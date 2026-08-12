"""X11 text injection.

The transcript is placed on the CLIPBOARD selection through Qt, then a paste
shortcut (default Ctrl+V) is synthesized with XTEST (python-xlib). Because the
paste goes to whatever window currently has focus, it works in text editors,
browsers, terminals and chats alike.

Notes
-----
* The paste key combo is configurable (``paste_shortcut``) because terminals
  usually paste with Ctrl+Shift+V.
* The focused application requests the clipboard content *after* it receives
  the paste key. Qt serves that request as soon as this function returns to
  the event loop, so a short event pump is used both before and after sending
  the keys.
* ``restore_clipboard`` optionally restores the previous clipboard a moment
  later. It is off by default because some apps read the clipboard lazily.
"""

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.input.text_injector import TextInjector

log = logging.getLogger(__name__)

_MOD_KEYSYMS = {"ctrl": "Control_L", "shift": "Shift_L", "alt": "Alt_L", "super": "Super_L"}
_KEY_KEYSYMS = {
    "enter": "Return",
    "escape": "Escape",
    "space": "space",
    "tab": "Tab",
    "backspace": "BackSpace",
    "delete": "Delete",
    "home": "Home",
    "end": "End",
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
}


class X11Injector(TextInjector):
    """Clipboard + XTEST paste for X11 sessions."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings

    def inject(self, text):
        if not text:
            return
        combo = (self._settings.get("paste_shortcut") or "ctrl+v").strip().lower()
        previous = None
        if self._settings.get("restore_clipboard"):
            previous = QApplication.clipboard().text()
        self._clipboard_set(text)
        self._pump_events(30)
        if not self._send_keys(combo):
            self.failed.emit("Could not synthesize the paste shortcut.")
            return
        self._pump_events(60)
        if previous is not None:
            QTimer.singleShot(250, lambda: QApplication.clipboard().setText(previous))
        self.injected.emit()

    def _send_keys(self, combo):
        """Synthesize a chord like ``ctrl+v`` with XTEST."""
        from Xlib import X, XK, display
        from Xlib.ext import xtest

        parts = [p for p in combo.split("+") if p]
        mod_keysyms = [_MOD_KEYSYMS[p] for p in parts if p in _MOD_KEYSYMS]
        main = next((p for p in parts if p not in _MOD_KEYSYMS), None)

        def keycode(name):
            return disp.keysym_to_keycode(XK.string_to_keysym(name))

        try:
            disp = display.Display()
            if not mod_keysyms and not main:
                return False
            for ks in mod_keysyms:
                xtest.fake_input(disp, X.KeyPress, keycode(ks))
            if main:
                ks = _KEY_KEYSYMS.get(main, main)
                xtest.fake_input(disp, X.KeyPress, keycode(ks))
                xtest.fake_input(disp, X.KeyRelease, keycode(ks))
            for ks in reversed(mod_keysyms):
                xtest.fake_input(disp, X.KeyRelease, keycode(ks))
            disp.sync()
            return True
        except Exception as exc:
            log.warning("XTEST injection failed: %s", exc)
            return False
        finally:
            try:
                disp.close()
            except Exception:
                pass
