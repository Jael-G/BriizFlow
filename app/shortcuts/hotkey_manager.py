"""Global hotkey manager.

Backends (clearly separated, selected by session):

* ``PynputHotkey``  — X11 / XWayland, via pynput's GlobalHotKeys.
* ``PortalHotkey``  — Wayland, via the XDG Desktop Portal
  ``org.freedesktop.portal.GlobalShortcuts`` interface (GNOME 45+/KDE/etc.).
  Requires the ``dbus-next`` package.

On Wayland the portal is the *only* sanctioned way to register a global
shortcut; if it is unavailable the app still works through the tray icon,
and a clear message is shown.
"""

import asyncio
import logging
import os
import threading

from PySide6.QtCore import QObject, Signal

from app.util import normalize_combo, session_type

log = logging.getLogger(__name__)
_PORTAL_SERVICE = "org.freedesktop.portal.Desktop"
_PORTAL_PATH = "/org/freedesktop/portal/desktop"
_PORTAL_IFACE = "org.freedesktop.portal.GlobalShortcuts"

_MOD_KEYS = {
    "ctrl": "KEY_LEFTCTRL",
    "shift": "KEY_LEFTSHIFT",
    "alt": "KEY_LEFTALT",
    "super": "KEY_LEFTMETA",
}
_KEY_KEYS = {
    "space": "KEY_SPACE",
    "enter": "KEY_ENTER",
    "escape": "KEY_ESC",
    "tab": "KEY_TAB",
    "backspace": "KEY_BACKSPACE",
    "delete": "KEY_DELETE",
    "home": "KEY_HOME",
    "end": "KEY_END",
    "up": "KEY_UP",
    "down": "KEY_DOWN",
    "left": "KEY_LEFT",
    "right": "KEY_RIGHT",
}


def portal_key_mapping(combo):
    """Map a normalized combo to the portal's key list.

    ``'ctrl+shift+space'`` -> ``['KEY_LEFTCTRL', 'KEY_LEFTSHIFT', 'KEY_SPACE']``
    """
    result = []
    for part in combo.split("+"):
        part = part.strip().lower()
        if part in _MOD_KEYS:
            result.append(_MOD_KEYS[part])
        else:
            result.append(_KEY_KEYS.get(part, "KEY_" + part.upper()))
    return result


class HotkeyManager(QObject):
    """Selects and owns the global-hotkey backend for the current session."""

    triggered = Signal()
    failed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._backend = None

    def start(self):
        combo = normalize_combo(self._settings.get("hotkey"))
        self._backend = self._select_backend()
        if self._backend is None:
            log.info("No global-hotkey backend available for this session")
            self.failed.emit(
                "Global shortcuts are not available in this session. "
                "Use the tray icon instead."
            )
            return
        log.info("Global hotkey %s via %s", combo, self._backend.__class__.__name__)
        self._backend.triggered.connect(self.triggered)
        self._backend.failed.connect(self.failed)
        self._backend.start(combo)

    def stop(self):
        if self._backend is not None:
            self._backend.stop()
            self._backend = None

    def _select_backend(self):
        sess = session_type()
        if sess == "wayland":
            portal = PortalHotkey()
            if portal.available():
                return portal
            # XWayland fallback, only when a real X display exists.
            if os.environ.get("DISPLAY"):
                return PynputHotkey()
            return None
        if sess == "x11":
            return PynputHotkey()
        return None


class _HotkeyBackend(QObject):
    triggered = Signal()
    failed = Signal(str)

    def start(self, combo):
        raise NotImplementedError

    def stop(self):
        pass


class PynputHotkey(_HotkeyBackend):
    """X11/XWayland global hotkey via pynput's GlobalHotKeys."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._listener = None

    def start(self, combo):
        from pynput import keyboard

        hotkey = "+".join("<%s>" % p for p in combo.split("+") if p)
        self._listener = keyboard.GlobalHotKeys({hotkey: self.triggered.emit})
        self._listener.start()

    def stop(self):
        if self._listener is not None:
            self._listener.stop()
            self._listener = None


class PortalHotkey(_HotkeyBackend):
    """XDG Desktop Portal GlobalShortcuts backend (Wayland)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._bus = None
        self._loop = None
        self._thread = None
        self._session = None
        self._shortcut_id = "briizflow-dictate"

    def available(self):
        """Whether the desktop portal exposes the GlobalShortcuts interface."""
        try:
            import dbus_next  # noqa: F401
        except ImportError:
            return False
        return os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("XDG_SESSION_TYPE") == "wayland"

    def start(self, combo):
        if self._loop is None:
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(
                target=self._run_loop, name="portal-hotkey", daemon=True
            )
            self._thread.start()
        future = asyncio.run_coroutine_threadsafe(self._start_async(combo), self._loop)
        try:
            future.result(timeout=10)
        except Exception as exc:
            log.warning("Could not register the portal shortcut: %s", exc)
            self.failed.emit(
                "Could not register the global shortcut through the desktop portal."
            )

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _start_async(self, combo):
        from dbus_next import BusType
        from dbus_next.aio import MessageBus
        from dbus_next.introspection import Node

        bus = await MessageBus(bus_type=BusType.SESSION).connect()
        introspection = await bus.introspect(_PORTAL_SERVICE, _PORTAL_PATH)
        if _PORTAL_IFACE not in self._interface_names(introspection):
            raise RuntimeError("GlobalShortcuts interface not exposed by the portal")

        proxy = bus.get_proxy_object(_PORTAL_SERVICE, _PORTAL_PATH, introspection)
        iface = proxy.get_interface(_PORTAL_IFACE)
        session_reply = await iface.call_create_session(
            "", {"handle_token": "briizflow-dictation"}
        )
        session = session_reply[0]  # (request_handle, session_handle)
        self._session = session

        keys = portal_key_mapping(combo)
        shortcuts = {
            self._shortcut_id: {
                "description": "BriizFlow dictation",
                "preferred_trigger": {
                    "type": "KEYBOARD",
                    "keys": keys,
                },
            }
        }
        await iface.call_bind_shortcuts(session, shortcuts)

        # Route activation signals back to the Qt thread.
        bus.add_message_handler(
            lambda msg: self._on_portal_signal(msg, bus)
        )

    def _interface_names(self, introspection):
        """Collect interface names exposed by an introspection node tree."""
        names = []
        stack = [introspection]
        while stack:
            node = stack.pop()
            names.extend(interface.name for interface in node.interfaces)
            stack.extend(node.nodes)
        return names

    def _on_portal_signal(self, message, bus):
        if message.interface == _PORTAL_IFACE and message.member == "Activated":
            shortcut_id = message.body[1] if len(message.body) > 1 else None
            if shortcut_id == self._shortcut_id:
                self.triggered.emit()
        return False

    def stop(self):
        if self._session is not None and self._loop is not None:
            future = asyncio.run_coroutine_threadsafe(self._close_session(), self._loop)
            try:
                future.result(timeout=3)
            except Exception:
                pass
            self._session = None

    async def _close_session(self):
        if self._bus is None:
            return
        # Best-effort; the portal cleans up sessions when the app exits.
        await self._bus.close()
        self._bus = None
