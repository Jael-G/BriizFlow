"""Small shared helpers (session detection, hotkey normalization)."""

import os

MODIFIER_ALIASES = {
    "control": "ctrl",
    "ctrl": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "option": "alt",
    "super": "super",
    "meta": "super",
    "win": "super",
    "windows": "super",
    "cmd": "super",
    "mod4": "super",
}

KEY_ALIASES = {
    "return": "enter",
    "esc": "escape",
    "spacebar": "space",
    "leftctrl": "ctrl",
    "rightctrl": "ctrl",
    "leftshift": "shift",
    "rightshift": "shift",
    "leftalt": "alt",
    "rightalt": "alt",
    "capslock": "caps_lock",
}


def session_type():
    """Return 'wayland', 'x11' or None, based on the display environment."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    if os.environ.get("DISPLAY"):
        return "x11"


def normalize_combo(combo):
    """Normalize a hotkey string to lower-case '+'-separated parts.

    'Ctrl+Shift+Space' -> 'ctrl+shift+space'
    'Meta+V'           -> 'super+v'
    """
    if not combo:
        return "ctrl+shift+space"
    parts = str(combo).replace(" ", "+").split("+")
    out = []
    for p in parts:
        p = p.strip().lower()
        if not p:
            continue
        p = MODIFIER_ALIASES.get(p, p)
        p = KEY_ALIASES.get(p, p)
        if p not in out:
            out.append(p)
    return "+".join(out) or "ctrl+shift+space"
