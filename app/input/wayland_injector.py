"""Best-effort Wayland text injection.

Wayland does not let normal (unprivileged) applications synthesize input or
read what the focused application is — so there is no universal injector.

This backend is deliberately separate from the X11 one and degrades clearly:

1. The transcript is copied to the clipboard with ``wl-copy`` (from the
   ``wl-clipboard`` package), falling back to Qt's clipboard.
2. A paste shortcut is synthesized with one of:
   * ``ydotool`` — works on any compositor but needs the ``ydotoold`` daemon
     (a uinput-based service; may require being in the ``input`` group).
   * ``wtype`` — works on wlroots-based compositors (sway, Hyprland, …) only.

If neither tool is present, ``failed`` is emitted with setup instructions.
"""

import logging
import shutil
import subprocess

from app.input.text_injector import TextInjector

log = logging.getLogger(__name__)


class WaylandInjector(TextInjector):
    """Best-effort clipboard + paste injector for Wayland sessions."""

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._tool = self._detect_tool()

    def _detect_tool(self):
        for tool in ("ydotool", "wtype"):
            if shutil.which(tool):
                return tool
        return None

    def inject(self, text):
        if not text:
            return
        if self._tool is None:
            self.failed.emit(
                "Wayland injection needs ydotool or wtype. Install one "
                "(ydotool needs the ydotoold daemon) and try again."
            )
            return
        if not self._clipboard_wl_copy(text):
            self._clipboard_set(text)  # Qt fallback
        self._pump_events(50)
        if not self._send_paste():
            self.failed.emit("Could not send the paste shortcut.")
            return
        self.injected.emit()

    def _clipboard_wl_copy(self, text):
        try:
            subprocess.run(
                ["wl-copy", "--type", "text/plain"],
                input=text.encode("utf-8"),
                check=True,
                timeout=5,
            )
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("wl-copy failed: %s", exc)
            return False

    def _send_paste(self):
        combo = (self._settings.get("paste_shortcut") or "ctrl+v").strip().lower()
        parts = [p for p in combo.split("+") if p]
        try:
            if self._tool == "ydotool":
                subprocess.run(["ydotool", "key", "+".join(parts)], check=True, timeout=5)
            else:
                cmd = ["wtype"]
                for mod in parts[:-1]:
                    cmd += ["-M", mod]
                cmd += ["-k", parts[-1]]
                for mod in parts[:-1]:
                    cmd += ["-P", mod]
                cmd += ["-K", parts[-1]]
                subprocess.run(cmd, check=True, timeout=5)
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("%s paste failed: %s", self._tool, exc)
            return False
