"""Runs a persistent local ``whisper-server`` and transcribes over localhost HTTP.

Speech recognition is performed entirely by the bundled whisper.cpp server
(``bin/whisper.cpp/whisper-server``). Instead of the one-shot ``whisper-cli``
subprocess the app used to spawn per recording, the runner owns one long-lived
server child:

1. finds the bundled server (``bin/whisper.cpp/whisper-server`` next to the project),
2. resolves the active model (``model_name`` from settings -> models dir),
3. starts the server once, with ``--host 127.0.0.1 --port <ephemeral>``,
4. polls ``GET /`` until the HTTP listener is up (model loaded) and reports
   ``state_changed("ready")``,
5. sends each WAV as a ``multipart/form-data`` ``POST /inference`` and parses
   the ``{"text": ...}`` JSON reply.

The server stays alive between transcriptions and is only restarted when the
active model changes or the process crashes. Cancellation aborts the in-flight
request without touching the server.

Lifecycle states: ``stopped -> starting -> ready -> transcribing`` with
``stopping`` used during shutdown/restarts and ``failed`` for terminal errors.
"""

import json
import logging
import os
import shlex
import socket
import sys
import uuid

from PySide6.QtCore import QObject, QProcess, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from app.models.manager import selected_model_path

log = logging.getLogger(__name__)
STARTUP_TIMEOUT_MS = 60000
_READY_POLL_MS = 250
STOP_TIMEOUT_MS = 5000
_FALLBACK_PORT = 8080
_INFERENCE_PATH = "/inference"

# The runner must keep control of model, host, port and request paths, so these
# flags are dropped from user-supplied extra server arguments.
_DROPPED_FLAGS = {"-f", "--file", "-m", "--model"}


def project_root():
    """Absolute path of the project root (…/app/whisper/runner.py -> up 3)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def find_whisper_server():
    """Locate the bundled whisper-server binary, or return ``None``.

    Search order:
    1. next to a frozen executable (PyInstaller-style packaging),
    2. ``<project_root>/bin/whisper.cpp/whisper-server`` (the canonical release
       folder — the prebuilt release directory, server and shared libs together),
    3. ``<project_root>/bin/whisper-server`` (legacy flat layout),
    4. inside the Python package (``app/bin/whisper-server``) for future bundling.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = []
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        candidates += [
            os.path.join(base, "whisper.cpp", "whisper-server"),
            os.path.join(base, "bin", "whisper.cpp", "whisper-server"),
            os.path.join(base, "whisper-server"),
            os.path.join(base, "bin", "whisper-server"),
        ]
    candidates += [
        os.path.join(project_root(), "bin", "whisper.cpp", "whisper-server"),
        os.path.join(project_root(), "bin", "whisper-server"),
        os.path.join(os.path.dirname(here), "bin", "whisper-server"),
    ]
    for path in candidates:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def filter_server_args(args_str):
    """Split user extra args into ``(kept, dropped)``.

    Input-file (``-f/--file``) and model (``-m/--model``) flags are dropped so
    the runner retains control of what is transcribed and which model is used;
    everything else is passed through to the server. Raises ``ValueError`` on
    bad quoting.
    """
    tokens = shlex.split(args_str or "")
    kept = []
    dropped = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token in _DROPPED_FLAGS:
            dropped.append(token)
            if i + 1 < len(tokens):
                dropped.append(tokens[i + 1])
                i += 1
        else:
            kept.append(token)
        i += 1
    return kept, dropped


def build_server_command(settings, exe, model_path, host, port):
    """Build the whisper-server argv (excluding ``argv[0]``).

    ``model``, ``host``, ``port`` and ``language`` are always owned by the
    runner; the user's extra args (already filtered) are appended unchanged.
    """
    lang = (settings.get("whisper_language") or "auto").strip() or "auto"
    extra, _ = filter_server_args(settings.get("whisper_extra_args") or "")
    return [
        "-m", model_path,
        "--host", host,
        "--port", str(port),
        "-l", lang,
    ] + extra


def _encode_part(boundary, name, value, filename=None, content_type=None):
    if isinstance(boundary, str):
        boundary = boundary.encode("ascii")
    out = bytearray()
    out += b"--" + boundary + b"\r\n"
    disp = 'Content-Disposition: form-data; name="%s"' % name
    if filename:
        disp += '; filename="%s"' % filename
    out += disp.encode("utf-8") + b"\r\n"
    if content_type:
        out += ("Content-Type: %s\r\n" % content_type).encode("ascii")
    out += b"\r\n"
    out += value if isinstance(value, (bytes, bytearray)) else str(value).encode("utf-8")
    out += b"\r\n"
    return bytes(out)


def build_inference_body(wav_bytes, lang, boundary):
    """Build the multipart body for ``POST /inference``."""
    boundary = boundary.encode("ascii") if isinstance(boundary, str) else boundary
    body = bytearray()
    body += _encode_part(boundary, "file", wav_bytes, filename="audio.wav", content_type="audio/wav")
    body += _encode_part(boundary, "language", lang)
    body += _encode_part(boundary, "response_format", "json")
    body += b"--" + boundary + b"--\r\n"
    return bytes(body)


def parse_inference_response(data):
    """Extract the transcript text from a ``{"text": ...}`` reply."""
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
        text = payload.get("text") if isinstance(payload, dict) else None
        if isinstance(text, str):
            return text.strip()
        return ""
    except (ValueError, AttributeError):
        return ""


class WhisperRunner(QObject):
    """Owns the persistent ``whisper-server`` child process (see module docstring)."""

    finished = Signal(str)
    failed = Signal(str)
    state_changed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._qnam = QNetworkAccessManager(self)
        self._process = None
        self._reply = None
        self._ready_timer = None
        self._server = None
        self._model = None
        self._port = None
        self._startup_elapsed = 0
        self._state = "stopped"

    # --- provider contract -------------------------------------------------
    def start(self):
        """Start the whisper-server child and wait until it reports ready."""
        if self._state in ("starting", "ready", "transcribing"):
            return
        self._set_state("starting")
        server = find_whisper_server()
        if not server:
            self._set_state("failed")
            self.failed.emit("The bundled whisper.cpp server is missing. Run ./install.sh.")
            return
        model = selected_model_path(self._settings)
        if not model:
            self._set_state("failed")
            self.failed.emit("No speech model is installed. Download one from the Models page.")
            return
        self._server = server
        self._model = model
        self._port = self._pick_port()
        args = build_server_command(self._settings, server, model, "127.0.0.1", self._port)
        self._process = QProcess(self)
        self._process.setProgram(server)
        self._process.setArguments(args)
        self._process.start()
        log.info("Starting whisper-server on 127.0.0.1:%d (model %s)", self._port, model)
        self._startup_elapsed = 0
        self._ready_timer = QTimer(self)
        self._ready_timer.setInterval(_READY_POLL_MS)
        self._ready_timer.timeout.connect(self._poll_ready)
        self._ready_timer.start()

    def stop(self):
        """Terminate the server child and return to ``stopped``."""
        self.cancel()
        if self._ready_timer is not None:
            self._ready_timer.stop()
            self._ready_timer = None
        if self._process is not None:
            self._set_state("stopping")
            self._process.terminate()
            if not self._process.waitForFinished(STOP_TIMEOUT_MS):
                self._process.kill()
            self._process = None
        self._server = None
        self._model = None
        self._port = None
        self._set_state("stopped")

    def cancel(self):
        """Abort the in-flight request without touching the server."""
        if self._reply is not None:
            self._reply.abort()
            self._reply = None

    def transcribe(self, wav_path):
        """POST a WAV to the running server; emit ``finished``/``failed``."""
        if self._state != "ready":
            self.failed.emit("The local speech engine is not ready yet.")
            return
        if not wav_path or not os.path.isfile(wav_path):
            self.failed.emit("The recording could not be read.")
            return
        try:
            with open(wav_path, "rb") as fh:
                wav_bytes = fh.read()
        except OSError as exc:
            log.error("Could not read WAV for inference: %s", exc)
            self.failed.emit("The recording could not be read.")
            return

        lang = (self._settings.get("whisper_language") or "auto").strip() or "auto"
        boundary = "----BriizFlow" + uuid.uuid4().hex
        body = build_inference_body(wav_bytes, lang, boundary)
        url = QUrl("http://127.0.0.1:%d%s" % (self._port, _INFERENCE_PATH))
        req = QNetworkRequest(url)
        req.setHeader(QNetworkRequest.ContentTypeHeader, "multipart/form-data; boundary=%s" % boundary)
        log.info("POST /inference (lang=%s, %d bytes)", lang, len(wav_bytes))
        self._set_state("transcribing")
        reply = self._qnam.post(req, body)
        self._reply = reply
        reply.finished.connect(lambda: self._on_reply(reply))

    def restart_for_model(self):
        """Restart the server when the active model changes."""
        self.stop()
        self.start()

    # --- internals ---------------------------------------------------------
    @property
    def ready(self):
        return self._state == "ready"

    def _set_state(self, state):
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _pick_port(self):
        """Return a free localhost port, falling back to the default."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.bind(("127.0.0.1", 0))
                return sock.getsockname()[1]
        except OSError:
            return _FALLBACK_PORT

    def _poll_ready(self):
        self._startup_elapsed += _READY_POLL_MS
        if self._startup_elapsed > STARTUP_TIMEOUT_MS:
            if self._ready_timer is not None:
                self._ready_timer.stop()
            self._set_state("failed")
            self.failed.emit("The local speech engine failed to start.")
            return
        url = QUrl("http://127.0.0.1:%d/" % self._port)
        reply = self._qnam.get(QNetworkRequest(url))
        reply.finished.connect(lambda: self._on_ready_probe(reply))

    def _on_ready_probe(self, reply):
        ok = reply.error() == QNetworkReply.NoError
        reply.deleteLater()
        if not ok:
            return  # keep polling
        if self._ready_timer is not None:
            self._ready_timer.stop()
            self._ready_timer = None
        log.info("whisper-server ready on 127.0.0.1:%d", self._port)
        self._set_state("ready")

    def _on_reply(self, reply):
        if self._reply is reply:
            self._reply = None
        if reply.error() != QNetworkReply.NoError:
            reply.deleteLater()
            self._set_state("ready")
            self.failed.emit("The local speech engine could not process the recording.")
            return
        data = bytes(reply.readAll())
        reply.deleteLater()
        self._set_state("ready")
        text = parse_inference_response(data)
        if text:
            log.info("whisper-server transcript: %r", text)
            self.finished.emit(text)
        else:
            # An empty return usually means no speech was detected — report it
            # as an empty transcript (a silent no-op), not a failure.
            log.info("whisper-server returned no speech; empty transcript")
            self.finished.emit("")
