"""Shared test fixtures (no network, no real keyring, no real notifications)."""

import os
import pathlib
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture
def _isolated_key_store(monkeypatch):
    """Replace the credential store with an in-memory session store."""
    import app.config.credentials as credentials

    store = credentials.SessionOnlyStore()
    monkeypatch.setattr(credentials, "_default_store", store)
    monkeypatch.setattr(credentials, "get_default_store", lambda: store)
    return store


@pytest.fixture
def _no_system_notifications(monkeypatch):
    """Disable desktop notifications during tests."""
    import app.notifications as notifications

    monkeypatch.setattr(notifications, "system_notify", lambda *a, **k: False)


@pytest.fixture
def settings():
    """An isolated Settings instance backed by a temp file."""
    from app.config.settings import Settings

    d = tempfile.mkdtemp()
    return Settings(path=os.path.join(d, "settings.json"))


@pytest.fixture
def models_dir(monkeypatch):
    """A temp models directory with the manager pointed at it."""
    import app.models.manager as manager

    d = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setattr(manager, "models_dir", lambda: str(d))
    return d


@pytest.fixture
def qt_app():
    """A QApplication for widget tests (offscreen)."""
    from PySide6.QtWidgets import QApplication

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    return app


class _FakeStream:
    def __init__(self, callback):
        self._callback = callback
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def close(self):
        pass


class FakeSounddevice:
    """A controllable stand-in for ``sounddevice``."""

    def __init__(self):
        self._streams = []

    def InputStream(self, samplerate, channels, dtype, device, callback):
        stream = _FakeStream(callback)
        self._streams.append((stream, samplerate, channels, dtype, device))
        return stream

    def play(self, data, rate=None):
        pass


@pytest.fixture
def fake_audio_backend(monkeypatch):
    """Replace sounddevice with a controllable fake for recorder tests."""
    import app.audio.recorder as recorder

    fake = FakeSounddevice()
    monkeypatch.setattr(recorder, "_sounddevice", lambda: fake)
    return fake
