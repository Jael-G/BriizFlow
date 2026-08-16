"""Application settings.

Settings are stored as JSON at
``$XDG_CONFIG_HOME/briizflow/settings.json`` (default ``~/.config/briizflow/settings.json``).

The ``Settings`` class is a thin dict wrapper that loads defaults, merges the
saved file, and can persist changes. One instance is shared across the app, so
the settings page and the workers always agree.
"""

import json
import logging
import os

log = logging.getLogger(__name__)
APP_NAME = "BriizFlow"


def xdg_config_home():
    return os.environ.get("XDG_CONFIG_HOME", os.path.join(os.path.expanduser("~"), ".config"))


def xdg_cache_home():
    return os.environ.get("XDG_CACHE_HOME", os.path.join(os.path.expanduser("~"), ".cache"))


def xdg_data_home():
    return os.environ.get("XDG_DATA_HOME", os.path.join(os.path.expanduser("~"), ".local", "share"))


def config_dir():
    return os.path.join(xdg_config_home(), APP_NAME.lower())


def data_dir():
    """Directory for persistent app data (e.g. downloaded Whisper models)."""
    return os.path.join(xdg_data_home(), APP_NAME.lower())


def config_path():
    return os.path.join(config_dir(), "settings.json")


def cache_dir():
    """Directory for temporary recording files."""
    return os.path.join(xdg_cache_home(), APP_NAME.lower())


def default_recordings_dir():
    return os.path.join(os.path.expanduser("~"), "BriizFlowRecordings")


DEFAULTS = {
    "enabled": True,
    "hotkey": "ctrl+shift+space",
    "paste_shortcut": "ctrl+v",
    "paste_backend": "auto",
    "mic_device": "",
    "sample_rate": 16000,
    "model_name": "",
    "whisper_language": "auto",
    "whisper_extra_args": "",
    "save_recordings": False,
    "recordings_dir": "",
    "start_on_login": False,
    "restore_clipboard": False,
    "recording_chimes": True,
    "online_transcription_enabled": False,
    "openai_model": "gpt-transcribe",
    "speech_cleanup": "none",
}


class Settings:
    """Thin dict wrapper around the saved settings, with defaults.

    ``get``/``set``/``update`` only touch keys that exist in :data:`DEFAULTS` —
    unknown keys in the saved JSON are deliberately ignored. Changes are
    persisted explicitly with :meth:`save`.
    """

    def __init__(self, path=None):
        self.path = path or config_path()
        self.data = dict(DEFAULTS)
        self._dirty = {}  # key -> previous value, cleared on save()
        self._load()

    def _load(self):
        """Merge the saved JSON over the defaults; ignore unknown keys."""
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                for key, value in loaded.items():
                    if key in DEFAULTS:
                        self.data[key] = value
        except FileNotFoundError:
            log.info("No settings file at %s; using defaults.", self.path)
        except Exception as exc:
            log.warning("Could not read settings file: %s", exc)

    def save(self):
        """Persist the current settings to disk; ``True`` on success."""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
            for key, old in self._dirty.items():
                log.info("Setting %s = %r (was %r)", key, self.data.get(key), old)
            self._dirty.clear()
            log.info("Settings saved to %s", self.path)
            return True
        except OSError as exc:
            log.error("Failed to save settings: %s", exc)
            return False

    def get(self, key, default=None):
        return self.data.get(key, default)

    def set(self, key, value):
        if key in DEFAULTS and self.data.get(key) != value:
            self._dirty[key] = self.data.get(key)
            self.data[key] = value

    def update(self, mapping):
        for key, value in mapping.items():
            if key in DEFAULTS and self.data.get(key) != value:
                self._dirty[key] = self.data.get(key)
                self.data[key] = value

    def as_dict(self):
        return dict(self.data)
