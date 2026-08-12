"""Desktop notifications via the freedesktop Notifications D-Bus spec.

BriizFlow posts transient status feedback (API key saved, download failed, …) as
real desktop notifications, so they appear no matter whether the main window
is visible. The old in-app toasts only showed while the window was open, and
several fired at once stacked and squished together. The freedesktop daemon
handles stacking/grouping of its own.

The notifier drives ``dbus-next`` on its own asyncio loop in a daemon thread
— the same pattern as the Wayland hotkey backend — so calls never block the
Qt UI thread. When no notification daemon is reachable, ``system_notify``
returns ``False`` and the caller falls back to the in-app toast host (see
``app/ui/components/toast.py``).
"""

import asyncio
import logging
import threading

from dbus_next import BusType, Variant
from dbus_next.aio import MessageBus

log = logging.getLogger(__name__)
_NOTIF_SERVICE = "org.freedesktop.Notifications"
_NOTIF_PATH = "/org/freedesktop/Notifications"
_NOTIF_IFACE = "org.freedesktop.Notifications"
_URGENCY = {"info": 0, "success": 1, "error": 2}
_ICONS = {"info": "dialog-information", "success": "dialog-information", "error": "dialog-error"}


class SystemNotifier:
    """Sends freedesktop notifications over a background asyncio D-Bus loop."""

    def __init__(self):
        self._bus = None
        self._iface = None
        self._loop = None
        self._thread = None

    def start(self):
        """Begin the background D-Bus connection (call once at app startup).

        The connection is opened lazily on first use if this is never called,
        but starting it at launch means the daemon is already probed by the
        time the user triggers the first notification.
        """
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_loop, name="notifier-dbus", daemon=True
        )
        self._thread.start()
        asyncio.run_coroutine_threadsafe(self._connect(), self._loop)

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _connect(self):
        try:
            bus = await MessageBus(bus_type=BusType.SESSION).connect()
            introspection = await bus.introspect(_NOTIF_SERVICE, _NOTIF_PATH)
            obj = bus.get_proxy_object(_NOTIF_SERVICE, _NOTIF_PATH, introspection)
            self._iface = obj.get_interface(_NOTIF_IFACE)
            self._bus = bus
        except Exception as exc:
            log.warning("Could not connect to the notification daemon: %s", exc)

    def notify(self, kind, title, message):
        """Post a notification; ``False`` when the daemon is unreachable."""
        if self._loop is None:
            self.start()
        if self._iface is None or self._bus is None:
            return False
        future = asyncio.run_coroutine_threadsafe(self._send(kind, title, message), self._loop)
        try:
            future.result(timeout=2.0)
            return True
        except Exception:
            log.exception("Notification send failed")
            return False

    async def _send(self, kind, title, message):
        urgency = _URGENCY.get(kind, 0)
        icon = _ICONS.get(kind, "dialog-information")
        hints = {"urgency": Variant("y", urgency)}
        try:
            # expire_timeout -1 = transient (the daemon decides lifetime).
            await self._iface.call_notify(
                "BriizFlow", 0, icon, title, message, [], hints, -1
            )
        except Exception as exc:
            log.warning("Failed to post notification to the daemon: %s", exc)


_notifier = SystemNotifier()


def start():
    """Begin the background D-Bus connection (call once at app startup)."""
    _notifier.start()


def system_notify(kind, title, message):
    """Post a freedesktop desktop notification; ``False`` when unreachable."""
    try:
        return _notifier.notify(kind, title, message)
    except Exception:
        log.exception("Desktop notification failed")
        return False
