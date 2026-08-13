"""Whisper model management.

Models live in the XDG data directory (``~/.local/share/briizflow/models``) and are
downloaded straight from the official whisper.cpp Hugging Face repository
(``ggerganov/whisper.cpp``). The active model is selected by *name* in settings
(``model_name``); its full path is resolved at runtime via
:func:`selected_model_path`.

Downloads run asynchronously through Qt's ``QNetworkAccessManager`` so the UI
never blocks, and report progress through the :class:`ModelManager` signals.
"""

import json
import logging
import os
import shutil

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from app.config.settings import data_dir

log = logging.getLogger(__name__)
MODEL_REPO = "ggerganov/whisper.cpp"
CURATED_MODELS = [
    {"name": "ggml-tiny.bin", "size_mb": 75},
    {"name": "ggml-base.bin", "size_mb": 142},
    {"name": "ggml-small.bin", "size_mb": 466},
    {"name": "ggml-medium.bin", "size_mb": 1530},
    {"name": "ggml-large-v3.bin", "size_mb": 3090},
    {"name": "ggml-large-v3-turbo.bin", "size_mb": 1620},
]
_MODEL_SUFFIXES = (".bin", ".gguf")


def models_dir():
    """Directory where installed models live (created on demand)."""
    directory = os.path.join(data_dir(), "models")
    os.makedirs(directory, exist_ok=True)
    return directory


def installed_models():
    """Scan the models dir.

    Returns ``[{"name", "path", "size_mb"}]`` sorted by name.
    """
    directory = models_dir()
    found = []
    try:
        entries = os.listdir(directory)
        for name in sorted(entries):
            if not name.startswith("ggml-") or not name.endswith(_MODEL_SUFFIXES):
                continue
            path = os.path.join(directory, name)
            if not os.path.isfile(path):
                continue
            size_mb = round(os.path.getsize(path) / 1048576)
            found.append({"name": name, "path": path, "size_mb": size_mb})
        return found
    except OSError:
        return []


def installed_names():
    """Names of installed models, sorted."""
    return [m["name"] for m in installed_models()]


def selected_model_path(settings):
    """Resolve the active model name to a full path (``""`` when none set)."""
    name = (settings.get("model_name") or "").strip()
    if not name:
        return ""
    return os.path.join(models_dir(), name)


def migrate_legacy_model_path(settings):
    """One-time migration from the old ``model_path`` setting.

    If the settings file still had a ``model_path`` pointing at a real model
    file and no ``model_name`` is selected yet, copy that file into the models
    dir and select it. Never clobbers an existing file; silently does nothing
    on any failure.
    """
    if settings.get("model_name"):
        return
    legacy = settings.data.get("model_path")
    if not legacy:
        return
    src = os.path.expanduser(legacy)
    if not os.path.isfile(src):
        return
    name = os.path.basename(src)
    dest = os.path.join(models_dir(), name)
    if os.path.exists(dest):
        return
    try:
        shutil.copy2(src, dest)
        settings.set("model_name", name)
        settings.save()
        log.info("Migrated legacy model %s -> %s", src, dest)
    except OSError as exc:
        log.warning("Could not migrate legacy model path %s: %s", src, exc)


def delete(name):
    """Delete an installed model. Returns True if it was removed."""
    path = os.path.join(models_dir(), name)
    try:
        os.remove(path)
        log.info("Deleted model %s", name)
        return True
    except FileNotFoundError:
        return False
    except OSError as exc:
        log.warning("Could not delete model %s: %s", name, exc)
        return False


def model_download_url(name):
    return f"https://huggingface.co/{MODEL_REPO}/resolve/main/{name}"


class ModelManager(QObject):
    """Async Hugging Face downloader for curated models.

    Downloads stream to ``<name>.part`` and are atomically renamed on success;
    a failed or cancelled download always removes its ``.part`` file. Only
    allow-listed curated names can ever be requested.
    """

    download_progress = Signal(str, int, int)  # (name, received, total)
    download_finished = Signal(str, str)  # (name, path)
    download_failed = Signal(str, str)  # (name, error)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._qnam = QNetworkAccessManager(self)
        self._active = {}  # name -> QNetworkReply
        self._cancelled = set()  # downloads the user aborted (no failure toast)
        self._progress = {}  # name -> (received, total), so rebuilt cards restore it

    def is_installed(self, name):
        return os.path.isfile(os.path.join(models_dir(), name))

    def download(self, name):
        """Start (or no-op on) a download for a curated model name."""
        self._cancelled.discard(name)
        if name not in {m["name"] for m in CURATED_MODELS}:
            log.warning("Rejecting download of non-curated name %r", name)
            return False
        if name in self._active:
            # Already downloading this model — never start a second request
            # writing to the same .part file.
            log.info("Already downloading %s; ignoring duplicate request", name)
            return False
        dest = os.path.join(models_dir(), name)
        if os.path.isfile(dest):
            self.download_finished.emit(name, dest)
            return True
        partial = dest + ".part"
        req = QNetworkRequest(QUrl(model_download_url(name)))
        reply = self._qnam.get(req)
        self._active[name] = reply
        self._progress[name] = (0, 0)
        reply.downloadProgress.connect(
            lambda received, total, n=name: self._on_download_progress(n, received, total)
        )
        reply.readyRead.connect(lambda n=name, r=reply: self._on_ready_read(n, r, partial))
        reply.finished.connect(lambda n=name, r=reply: self._on_finished(n, r, partial, dest))
        return True

    def progress_of(self, name):
        """Latest ``(received, total)`` for an in-flight download, or ``None``."""
        return self._progress.get(name)

    def _on_download_progress(self, name, received, total):
        self._progress[name] = (received, total)
        self.download_progress.emit(name, received, total)

    def cancel(self, name):
        """Abort an in-flight download and clean up its partial file.

        A cancelled download is cleaned up silently — no ``download_failed``
        (and therefore no failure toast); the user asked for it.
        """
        reply = self._active.pop(name, None)
        self._cancelled.add(name)
        self._progress.pop(name, None)
        if reply is not None:
            reply.abort()
            reply.deleteLater()
        self._cleanup_partial(os.path.join(models_dir(), name) + ".part")

    def _on_ready_read(self, name, reply, partial):
        try:
            os.makedirs(os.path.dirname(partial), exist_ok=True)
            with open(partial, "ab") as fh:
                fh.write(bytes(reply.readAll()))
        except OSError as exc:
            log.warning("Could not write partial download %s: %s", partial, exc)
            reply.abort()

    def _on_finished(self, name, reply, partial, dest):
        self._active.pop(name, None)
        self._progress.pop(name, None)
        if name in self._cancelled:
            self._cancelled.discard(name)
            reply.deleteLater()
            return
        try:
            if reply.error() != QNetworkReply.NoError:
                self._cleanup_partial(partial)
                self.download_failed.emit(name, reply.errorString())
                return
            # Flush any bytes that arrived outside readyRead, then rename.
            with open(partial, "ab") as fh:
                fh.write(bytes(reply.readAll()))
            os.replace(partial, dest)
            log.info("Downloaded model %s", name)
            self.download_finished.emit(name, dest)
        except OSError as exc:
            self._cleanup_partial(partial)
            self.download_failed.emit(name, f"Could not save the model: {exc}")
        finally:
            reply.deleteLater()

    def _cleanup_partial(self, partial):
        try:
            if os.path.exists(partial):
                os.remove(partial)
        except OSError as exc:
            log.warning("Could not remove partial download %s: %s", partial, exc)
