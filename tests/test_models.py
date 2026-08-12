"""Model manager tests (no network: downloads use a fake QNetworkAccessManager)."""

import os
from PySide6.QtCore import QObject, QByteArray, QUrl, Signal
from PySide6.QtNetwork import QNetworkReply

from app.models.manager import (
    CURATED_MODELS,
    ModelManager,
    delete,
    installed_models,
    migrate_legacy_model_path,
    selected_model_path,
)


def test_curated_models_well_formed():
    names = {m["name"] for m in CURATED_MODELS}
    assert len(names) == len(CURATED_MODELS)
    for m in CURATED_MODELS:
        assert m["name"].startswith("ggml-")
        assert m["size_mb"] > 0


def test_installed_models_scans_dir(models_dir):
    (models_dir / "ggml-base.bin").write_bytes(b"x" * 1048576)
    (models_dir / "ggml-tiny.bin.part").write_bytes(b"partial")
    found = installed_models()
    names = [m["name"] for m in found]
    assert names == ["ggml-base.bin"]
    assert found[0]["size_mb"] == 1


def test_installed_models_missing_dir(tmp_path, monkeypatch):
    import app.models.manager as manager

    monkeypatch.setattr(manager, "models_dir", lambda: str(tmp_path / "nope"))
    assert installed_models() == []


def test_selected_model_path_resolves(settings, models_dir):
    settings.set("model_name", "ggml-base.bin")
    assert selected_model_path(settings) == str(models_dir / "ggml-base.bin")


def test_selected_model_path_empty(settings):
    assert selected_model_path(settings) == ""


def test_migrate_legacy_model_path(models_dir):
    old = models_dir / "old"
    old.mkdir()
    src = old / "ggml-large-v3-turbo.bin"
    src.write_bytes(b"model")
    settings = _settings_with_legacy(str(src))
    migrate_legacy_model_path(settings)
    assert settings.get("model_name") == "ggml-large-v3-turbo.bin"
    assert (models_dir / "ggml-large-v3-turbo.bin").exists()


def test_migrate_legacy_does_nothing_when_already_set(settings, models_dir):
    settings.set("model_name", "ggml-base.bin")
    (models_dir / "ggml-base.bin").write_bytes(b"x")
    settings.data["model_path"] = str(models_dir / "ggml-small.bin")
    migrate_legacy_model_path(settings)
    assert settings.get("model_name") == "ggml-base.bin"


def test_migrate_legacy_ignores_missing_file(models_dir):
    settings = _settings_with_legacy("/nonexistent/ggml-base.bin")
    migrate_legacy_model_path(settings)
    assert not settings.get("model_name")


def _settings_with_legacy(model_path):
    import tempfile

    from app.config.settings import Settings

    s = Settings(path=os.path.join(tempfile.mkdtemp(), "s.json"))
    s.data["model_path"] = model_path
    return s


# --------------------------------------------------------------------------
# Downloads (fake QNAM)
# --------------------------------------------------------------------------
class FakeReply(QObject):
    downloadProgress = Signal(int, int)
    readyRead = Signal()
    finished = Signal()

    def __init__(self, data=b"", error=None):
        super().__init__()
        self._data = QByteArray(data)
        self._error = QNetworkReply.NoError if error is None else error
        self.aborted = False

    def readAll(self):
        return self._data

    def error(self):
        return self._error

    def errorString(self):
        return "boom"

    def abort(self):
        self.aborted = True

    def deleteLater(self):
        pass


class FakeQNAM(QObject):
    def __init__(self):
        super().__init__()
        self.requests = []
        self.replies = []
        self.pending = None

    def get(self, request):
        reply = self.pending or FakeReply(b"model-data")
        self.replies.append(reply)
        return reply

    def post(self, request, data):
        return self.pending or FakeReply(b'{"text": "hi"}')


def _manager_with_fake_qnam(monkeypatch, models_dir):
    manager = ModelManager()
    fake = FakeQNAM()
    manager._qnam = fake
    return manager, fake


def test_download_streams_and_renames(qt_app, settings, models_dir):
    manager, fake = _manager_with_fake_qnam(None, models_dir)
    manager.download("ggml-base.bin")
    reply = fake.replies[-1]
    reply.readyRead.emit()
    reply.finished.emit()
    assert (models_dir / "ggml-base.bin").exists()
    assert manager.is_installed("ggml-base.bin")


def test_download_rejects_non_model_name(qt_app, settings, models_dir):
    manager, fake = _manager_with_fake_qnam(None, models_dir)
    assert manager.download("evil.bin") is False
    assert not fake.replies


def test_duplicate_download_is_ignored(qt_app, settings, models_dir):
    """A second request for an already-downloading model must be a no-op."""
    manager, fake = _manager_with_fake_qnam(None, models_dir)
    assert manager.download("ggml-base.bin") is True
    assert len(fake.replies) == 1
    assert manager.download("ggml-base.bin") is False  # duplicate ignored
    assert len(fake.replies) == 1
    # A different model can start concurrently.
    assert manager.download("ggml-tiny.bin") is True
    assert len(fake.replies) == 2


def test_concurrent_downloads_survive_refresh(qt_app, settings, models_dir):
    """Finishing one download must not hide another that's still running."""
    from app.ui.pages.models_page import ModelsPage

    page = ModelsPage(settings)
    fake = FakeQNAM()
    page._manager._qnam = fake

    page._start_download("ggml-base.bin")
    page._start_download("ggml-tiny.bin")
    assert len(fake.replies) == 2
    assert len(page._manager._active) == 2

    # Finish the small one (file written) -> triggers a full _refresh().
    (models_dir / "ggml-base.bin").write_bytes(b"done")
    page._on_download_finished("ggml-base.bin", str(models_dir / "ggml-base.bin"))

    # The big one must still be shown as downloading on its rebuilt card.
    tiny = page._cards["ggml-tiny.bin"]
    assert not tiny.cancel_btn.isHidden()
    assert not tiny.progress_bar.isHidden()
    assert tiny.download_btn.isHidden()
    # And the finished one is now installed/active.
    base = page._cards["ggml-base.bin"]
    assert not base.active_badge.isHidden()


def test_cancel_download_is_silent(qt_app, settings, models_dir):
    """Cancelling a download must not surface a failure/toast."""
    manager, fake = _manager_with_fake_qnam(None, models_dir)
    failed = []
    manager.download_failed.connect(lambda name, error: failed.append((name, error)))
    manager.download("ggml-base.bin")
    manager.cancel("ggml-base.bin")
    fake.replies[-1].finished.emit()  # abort triggers finished -> _on_finished
    assert not failed
    assert not (models_dir / "ggml-base.bin.part").exists()


def test_delete_removes_file(models_dir):
    (models_dir / "ggml-base.bin").write_bytes(b"x")
    assert delete("ggml-base.bin") is True
    assert not (models_dir / "ggml-base.bin").exists()
    assert delete("ggml-base.bin") is False
