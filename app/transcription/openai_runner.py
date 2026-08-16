"""Asynchronous OpenAI transcription backend.

Implements the same signal contract as the local ``WhisperRunner`` so the
controller can drive either provider uniformly:

* ``finished(str)`` / ``failed(str)`` / ``state_changed(str)``
* ``start()`` / ``stop()`` / ``cancel()`` / ``transcribe(wav_path)``

Each recording is uploaded to ``POST https://api.openai.com/v1/audio/
transcriptions`` with ``Authorization: Bearer <key>``. The key is fetched from
the credential store immediately before the request and never logged, stored in
settings, or included in error text.

Readiness is a lightweight state — ``start()`` makes no network probe. The key,
model and audio are validated when a transcription is actually requested, and
failures are classified into concise, actionable messages with ``sk-...``
secrets redacted. On any failure the controller returns to idle; BriizFlow never
falls back to the local server.
"""

import json
import logging
import os
import re
import uuid

from PySide6.QtCore import QByteArray, QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

from app.config.credentials import CredentialStoreError, KeyringUnavailableError, get_default_store
from app.transcription.models import is_valid_model, language_hint_field

log = logging.getLogger(__name__)
ENDPOINT = "https://api.openai.com/v1/audio/transcriptions"
MAX_UPLOAD_BYTES = 26214400  # 25 MB
REQUEST_TIMEOUT_MS = 60000
_SK_PATTERN = re.compile(r"(?i)sk-[A-Za-z0-9_-]{4,}")


def redact(value):
    """Replace ``sk-...``-shaped secrets so they never reach logs or the UI."""
    if not value:
        return value
    return _SK_PATTERN.sub("sk-***", value)


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


def language_hint_value(model_id, language):
    """The ``(field, value)`` pair to send for a language hint, or ``None``
    when the request carries none — the setting is ``auto``, or the model
    accepts no hint at all (never sent, even if the user picked a language).

    The value is the exact string placed in the multipart part: a plain ISO
    code for the singular ``language`` field, a JSON array of codes for the
    plural ``languages`` field.
    """
    if not language:
        return None
    lang = language.strip().lower()
    if lang == "auto":
        return None
    field = language_hint_field(model_id)
    if field == "languages":
        return (field, json.dumps([lang]))
    if field == "language":
        return (field, lang)
    return None


def build_transcription_body(wav_bytes, model_id, language, boundary):
    """Build the multipart/form-data body for the transcriptions endpoint.

    Whether a language hint is sent is decided by the model's contract, never
    by the user's setting alone: ``whisper-1`` and the GPT-4o transcription
    models take the singular ``language`` field; ``gpt-transcribe`` takes the
    plural ``languages`` field as a JSON array of expected languages; a model
    that accepts no hint sends neither. ``auto`` omits the hint entirely and
    both fields are never sent together.
    """
    boundary = boundary.encode("ascii") if isinstance(boundary, str) else boundary
    body = bytearray()
    body += _encode_part(boundary, "file", wav_bytes, filename="audio.wav", content_type="audio/wav")
    body += _encode_part(boundary, "model", model_id)
    body += _encode_part(boundary, "response_format", "json")
    hint = language_hint_value(model_id, language)
    if hint is not None:
        field, value = hint
        body += _encode_part(boundary, field, value)
    body += b"--" + boundary + b"--\r\n"
    return bytes(body)


def parse_transcription_response(data):
    """Extract the transcript and say whether it parsed cleanly.

    Returns ``(text, reason)`` where ``reason`` is:

    * ``"ok"``      — a non-empty ``text`` string (only ``text`` is injected),
    * ``"empty"``   — valid JSON with a blank ``text`` (e.g. no speech detected),
    * ``"invalid"`` — the body is not JSON, not a dict, or has no usable ``text``.

    The reason lets the caller show an accurate message and log the body for
    diagnosis instead of a generic "invalid response".
    """
    try:
        payload = json.loads(data.decode("utf-8", errors="replace"))
        if not isinstance(payload, dict):
            return ("", "invalid")
        text = payload.get("text")
        if not isinstance(text, str):
            return ("", "invalid")
        text = text.strip()
        if text:
            return (text, "ok")
        return ("", "empty")
    except (ValueError, AttributeError):
        return ("", "invalid")


def _body_snippet(data, limit=500):
    """A bounded, redactable preview of a response body for diagnostics."""
    return data[:limit].decode("utf-8", errors="replace")


def error_message(response_bytes):
    """Extract a safe provider error message from ``{"error": {"message":…}}``."""
    try:
        payload = json.loads(response_bytes.decode("utf-8", errors="replace"))
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"].strip()
    except (ValueError, AttributeError):
        return ""
    return ""


def classify_failure(reply_error, http_status, response_bytes=b""):
    """Map a failed reply to a concise, safe, user-visible message.

    The HTTP status wins when present (OpenAI returns proper status codes);
    Qt network-level errors are classified below it. The message never
    contains the API key or raw request/response headers.
    """
    http_status = int(http_status or 0)
    if http_status >= 400:
        if http_status in (401, 403):
            return "OpenAI rejected the API key. Check the key and project access."
        if http_status == 429:
            return "OpenAI rate limit or quota reached. Try again later."
        if http_status == 400:
            detail = redact(error_message(response_bytes))
            if detail:
                return "OpenAI rejected the recording: %s" % detail
        if http_status >= 500:
            return "OpenAI is temporarily unavailable. Try again later."
        return "OpenAI rejected the recording."
    if reply_error == QNetworkReply.TimeoutError:
        return "OpenAI transcription timed out."
    if reply_error in (
        QNetworkReply.HostNotFoundError,
        QNetworkReply.ConnectionRefusedError,
        QNetworkReply.UnknownNetworkError,
        QNetworkReply.NetworkSessionFailedError,
        QNetworkReply.TemporaryNetworkFailureError,
    ):
        return "Could not reach OpenAI. Check your internet connection."
    if reply_error == QNetworkReply.SslHandshakeFailedError:
        return "Could not establish a secure connection to OpenAI."
    return "OpenAI transcription failed."


class OpenAITranscriptionRunner(QObject):
    """Online OpenAI transcription backend (see module docstring)."""

    finished = Signal(str)
    failed = Signal(str)
    state_changed = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._qnam = QNetworkAccessManager(self)
        self._reply = None
        self._state = "idle"

    # --- provider contract -------------------------------------------------
    def start(self):
        """Lightweight readiness; ``start()`` makes no network probe."""
        self._set_state("ready")

    def stop(self):
        self.cancel()
        self._set_state("idle")

    def cancel(self):
        """Abort any in-flight request (also used on setting changes)."""
        if self._reply is not None:
            self._reply.abort()
            self._reply = None

    def transcribe(self, wav_path):
        """Validate at request time, upload, then emit ``finished``/``failed``."""
        try:
            store = get_default_store()
            api_key = store.get()
        except (KeyringUnavailableError, CredentialStoreError) as exc:
            log.warning("Could not read the API key: %s", exc)
            api_key = None
        if not api_key:
            self.failed.emit("OpenAI API key is not set. Add it in Settings.")
            return
        model_id = self._settings.get("openai_model")
        if not is_valid_model(model_id):
            self.failed.emit("The selected OpenAI model is no longer supported.")
            return
        if not wav_path or not os.path.isfile(wav_path):
            self.failed.emit("The recording could not be read.")
            return
        size = os.path.getsize(wav_path)
        if size > MAX_UPLOAD_BYTES:
            self.failed.emit("Recording is larger than the 25 MB OpenAI upload limit.")
            return
        try:
            with open(wav_path, "rb") as fh:
                wav_bytes = fh.read()
        except OSError as exc:
            self.failed.emit("The recording could not be read.")
            log.error("Could not read WAV for upload: %s", exc)
            return

        boundary = "----BriizFlow" + uuid.uuid4().hex
        body = build_transcription_body(
            wav_bytes,
            model_id,
            self._settings.get("whisper_language") or "auto",
            boundary,
        )
        req = QNetworkRequest(QUrl(ENDPOINT))
        req.setRawHeader(b"Authorization", b"Bearer " + api_key.encode("utf-8"))
        req.setHeader(QNetworkRequest.ContentTypeHeader, "multipart/form-data; boundary=%s" % boundary)
        req.setTransferTimeout(REQUEST_TIMEOUT_MS)

        log.info("Uploading %s to OpenAI (model=%s, lang=%s, %d bytes)", wav_path, model_id, self._settings.get("whisper_language") or "auto", size)
        self._set_state("transcribing")
        reply = self._qnam.post(req, body)
        self._reply = reply
        reply.finished.connect(lambda: self._on_finished(reply))

    # --- internals ---------------------------------------------------------
    def _set_state(self, state):
        if state != self._state:
            self._state = state
            self.state_changed.emit(state)

    def _on_finished(self, reply):
        if self._reply is reply:
            self._reply = None
        if reply.error() != QNetworkReply.NoError:
            status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
            status = int(status) if status else 0
            msg = classify_failure(reply.error(), status, bytes(reply.readAll()))
            reply.deleteLater()
            self._set_state("ready")
            self.failed.emit(msg)
            return
        data = bytes(reply.readAll())
        reply.deleteLater()
        self._set_state("ready")
        text, reason = parse_transcription_response(data)
        if reason == "ok":
            log.info("OpenAI transcript: %r", text)
            self.finished.emit(text)
        elif reason == "empty":
            # No speech detected — a silent empty transcript, not a failure.
            log.info("OpenAI returned no speech; empty transcript")
            self.finished.emit("")
        else:
            log.warning("Unexpected OpenAI response: %s", _body_snippet(data))
            self.failed.emit("OpenAI returned an unexpected response.")
