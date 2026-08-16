"""Dictation controller: the state machine wiring everything together.

States: ``idle`` -> ``recording`` -> ``transcribing`` -> ``idle``

* Hotkey / tray calls :meth:`toggle`.
* Recording is handled by :class:`app.audio.recorder.AudioRecorder` (async,
  PortAudio callback thread) while the overlay animates its level.
* A persistent local ``whisper-server`` (owned by
  :class:`app.whisper.runner.WhisperRunner`) transcribes the WAV over
  localhost HTTP; the overlay shows a spinner meanwhile. When online
  transcription is enabled, :class:`app.transcription.openai_runner.OpenAITranscriptionRunner`
  is used instead.
* When ``speech_cleanup`` is non-``none``, the finished transcript is first
  sent through the text-cleanup pass (``app.transcription.cleanup``); on any
  cleanup failure the original transcript is pasted unchanged.
* The transcript is injected at the cursor by the configured injector (X11 or
  Wayland).

Dictation is gated on the server being ready: a toggle before readiness shows
a concise starting state instead of recording audio that could not be
transcribed. Shutdown stops the server asynchronously and only quits the app
once its cleanup has been observed.
"""

import logging
import os
import shutil
import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from app.audio.chime import START_DELAY_MS, play_chime
from app.audio.recorder import AudioRecorder
from app.config.settings import cache_dir, default_recordings_dir
from app.input.text_injector import create_injector
from app.notifications import system_notify
from app.shortcuts.hotkey_manager import HotkeyManager
from app.transcription.cleanup import TextCleanupRunner
from app.transcription.openai_runner import OpenAITranscriptionRunner
from app.ui.components.window import AppWindow
from app.whisper.runner import WhisperRunner

log = logging.getLogger(__name__)
_TEMP_TTL_SECONDS = 7 * 86400  # recordings older than 7 days are cleaned


class DictationController(QObject):
    """Owns the recorder, providers, injector, overlay, tray and hotkeys."""

    def __init__(self, settings, overlay, injector, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._overlay = overlay
        self._injector = injector
        self._recorder = AudioRecorder(settings, self)
        self._local = WhisperRunner(settings, self)
        self._online = OpenAITranscriptionRunner(settings, self)
        self._cleanup = TextCleanupRunner(settings, self)
        self._provider = self._local
        self._state = "idle"
        # Raw transcript awaiting the optional cleanup pass, if one is running.
        self._pending_text = None
        self._hotkeys = None
        self._tray = None
        self._window = None
        # Feeds the recorder's live mic level to the overlay while recording.
        self._level_timer = QTimer(self)
        self._level_timer.setInterval(50)
        self._level_timer.timeout.connect(self._push_level)

        self._connect_provider(self._local)
        self._connect_provider(self._online)
        self._cleanup.finished.connect(self._on_cleanup_finished)
        self._cleanup.failed.connect(self._on_cleanup_failed)
        self._injector.injected.connect(self._on_injected)
        self._injector.failed.connect(self._on_inject_failed)

    # --- provider plumbing --------------------------------------------------
    def _online_enabled(self):
        return bool(self._settings.get("online_transcription_enabled"))

    def _current_provider(self):
        return self._online if self._online_enabled() else self._local

    def _connect_provider(self, provider):
        provider.finished.connect(self._on_finished)
        provider.failed.connect(self._on_failed)

    def _push_level(self):
        """Feed the recorder's live mic level to the overlay (50 ms cadence)."""
        self._overlay.set_level(self._recorder.level)

    # --- startup / lifecycle ------------------------------------------------
    def start_whisper(self):
        """Start the selected transcription backend."""
        self._provider = self._current_provider()
        log.info(
            "Starting transcription backend: %s",
            "online (OpenAI)" if self._online_enabled() else "local (whisper.cpp)",
        )
        self._provider.start()

    def cleanup_temp(self):
        """Remove temp recordings older than the TTL."""
        try:
            for name in os.listdir(cache_dir()):
                if not name.startswith("recording_"):
                    continue
                path = os.path.join(cache_dir(), name)
                try:
                    if time.time() - os.path.getmtime(path) > _TEMP_TTL_SECONDS:
                        os.remove(path)
                except OSError:
                    pass
        except OSError:
            pass

    def create_hotkeys(self):
        """Register the global hotkey; re-registering rebinds a new combo."""
        if self._hotkeys is not None:
            self._hotkeys.stop()
        self._hotkeys = HotkeyManager(self._settings, self)
        self._hotkeys.triggered.connect(self.toggle)
        self._hotkeys.failed.connect(self._on_hotkey_failed)
        log.info("Registering global hotkey: %s", self._settings.get("hotkey"))
        self._hotkeys.start()

    def attach_tray(self, tray):
        self._tray = tray

    def quit(self):
        """Cancel in-flight work, stop the server, then quit."""
        log.info("Quitting: cancelling in-flight work and stopping the server")
        self._online.cancel()
        self._cleanup.cancel()
        self._recorder.cleanup()
        self._local.stop()
        if self._hotkeys is not None:
            self._hotkeys.stop()
        QApplication.quit()

    # --- windows ------------------------------------------------------------
    def open_settings(self):
        self._ensure_window().show_settings()

    def open_model_manager(self):
        self._ensure_window().show_models()

    def _ensure_window(self):
        if self._window is None:
            self._window = AppWindow(self._settings)
            self._window.settings_page.settings_saved.connect(self._on_settings_saved)
            self._window.models_page.settings_saved.connect(self._on_settings_saved)
        return self._window

    # --- dictation ----------------------------------------------------------
    def toggle(self):
        if self._state == "idle":
            self._begin_recording()
        elif self._state == "recording":
            self._end_recording()
        # transcribing: toggles are ignored until we return to idle.

    def _begin_recording(self):
        provider = self._current_provider()
        if provider is self._local:
            if not self._local.ready:
                # The overlay's pending state is feedback enough; no toast.
                log.info("Dictation blocked: local speech engine is still starting")
                self._overlay.set_state("pending")
                return
            if not self._settings.get("model_name"):
                log.warning("Dictation blocked: no speech model installed")
                self._overlay.set_state("error")
                system_notify("error", "BriizFlow", "No speech model installed. Open the Models page.")
                return

        self._state = "recording"
        if self._settings.get("recording_chimes"):
            play_chime("start")
        # The mic opens immediately; the start-chime window is trimmed so it
        # never lands in the transcript.
        skip_ms = START_DELAY_MS if self._settings.get("recording_chimes") else 0
        log.info(
            "Recording started (backend: %s, chime trim: %d ms)",
            "online" if self._online_enabled() else "local",
            skip_ms,
        )
        self._recorder.start(skip_ms=skip_ms)
        self._overlay.set_state("recording")
        self._level_timer.start()

    def _end_recording(self):
        self._state = "transcribing"
        self._overlay.set_state("processing")
        self._level_timer.stop()
        if self._settings.get("recording_chimes"):
            play_chime("stop")
        path = self._recorder.stop()
        if not path or not os.path.isfile(path) or os.path.getsize(path) == 0:
            log.info("Recording captured nothing; cancelling silently")
            self._return_to_idle(hide_overlay=True)
            return
        if self._settings.get("save_recordings"):
            self._save_recording(path)
        log.info("Sending recording to %s: %s", self._current_provider().__class__.__name__, path)
        self._current_provider().transcribe(path)

    def _save_recording(self, path):
        directory = self._settings.get("recordings_dir") or default_recordings_dir()
        try:
            os.makedirs(directory, exist_ok=True)
            name = "briizflow_%d.wav" % int(time.time())
            shutil.copy2(path, os.path.join(directory, name))
        except OSError as exc:
            log.warning("Could not save recording: %s", exc)

    def _on_finished(self, text):
        text = (text or "").strip()
        if not text:
            log.info("Transcript was empty; silent no-op")
            self._return_to_idle(hide_overlay=True)
            return
        mode = (self._settings.get("speech_cleanup") or "none").lower()
        if mode == "none":
            log.info("Transcript received: %r", text)
            self._injector.inject(text)
            return
        # Cleanup enabled: the overlay stays in its processing state while the
        # text model cleans the transcript; the result is pasted on completion
        # (and the raw transcript is pasted if cleanup fails).
        log.info("Transcript received (cleanup=%s): %r", mode, text)
        self._pending_text = text
        self._cleanup.cleanup(text, mode)

    def _on_cleanup_finished(self, text):
        text = (text or "").strip()
        if not text:
            # A blank cleanup result is treated like a failure: paste the raw.
            text = self._pending_text or ""
        self._pending_text = None
        log.info("Cleaned transcript: %r", text)
        self._injector.inject(text)
        # Result is reported by _on_injected / _on_inject_failed.

    def _on_cleanup_failed(self, message):
        log.warning("Text cleanup failed; pasting the original transcript: %s", message)
        raw = self._pending_text or ""
        self._pending_text = None
        self._injector.inject(raw)
        # Result is reported by _on_injected / _on_inject_failed.

    def _on_failed(self, message):
        log.warning("Transcription failed: %s", message)
        self._return_to_idle()
        self._overlay.set_state("error")
        system_notify("error", "BriizFlow", message)

    def _on_injected(self):
        log.info("Transcript injected at the cursor")
        self._return_to_idle()
        self._overlay.set_state("success")

    def _on_inject_failed(self, message):
        log.warning("Text injection failed: %s", message)
        self._return_to_idle()
        self._overlay.set_state("error")
        system_notify("error", "BriizFlow", message)

    def _on_hotkey_failed(self, message):
        system_notify("info", "BriizFlow", message)

    def _return_to_idle(self, hide_overlay=False):
        self._state = "idle"
        if hide_overlay:
            self._overlay.set_state("idle")

    # --- settings changes ---------------------------------------------------
    def _on_settings_saved(self, key):
        if key == "hotkey":
            self.create_hotkeys()
        elif key in ("model_name", "whisper_language", "whisper_extra_args"):
            if not self._online_enabled():
                self._local.restart_for_model()
        elif key == "online_transcription_enabled":
            self._switch_provider()
        elif key in ("paste_backend", "paste_shortcut"):
            self._injector = create_injector(self._settings, self)
            self._injector.injected.connect(self._on_injected)
            self._injector.failed.connect(self._on_inject_failed)
        elif key == "openai_model":
            # A model change mid-transcription cancels the in-flight request.
            if self._online_enabled():
                self._online.cancel()
        elif key == "openai_api_key":
            if self._online_enabled():
                self._online.cancel()

    def _switch_provider(self):
        self._online.cancel()
        if self._online_enabled():
            log.info("Switching to online transcription (OpenAI)")
            self._local.stop()
            self._online.start()
            self._provider = self._online
        else:
            log.info("Switching back to local transcription (whisper.cpp)")
            self._online.stop()
            self._provider = self._local
            self._local.start()
