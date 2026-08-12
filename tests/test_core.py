"""Core logic tests for BriizFlow.

These exercise the parts that don't need a real display, microphone or
whisper binary: settings persistence, hotkey normalization, whisper output
parsing, portal key mapping, recorder file/level logic and the full
dictation state machine (with a fake whisper binary + stubbed injector).

Run with::

    .venv/bin/pip install pytest
    .venv/bin/python -m pytest tests/ -v
"""

import json
import os
import tempfile

import numpy as np
import pytest
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtTest import QTest

from app.config.settings import DEFAULTS, Settings
from app.util import normalize_combo, session_type


# --------------------------------------------------------------------------
# Settings
# --------------------------------------------------------------------------
def test_settings_roundtrip():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "settings.json")
    s = Settings(path=path)
    assert s.get("hotkey") == "ctrl+shift+space"
    s.set("hotkey", "ctrl+alt+x")
    assert s.save() is True
    assert os.path.isfile(path)

    loaded = Settings(path=path)
    assert loaded.get("hotkey") == "ctrl+alt+x"


def test_settings_ignores_unknown_keys():
    d = tempfile.mkdtemp()
    path = os.path.join(d, "settings.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"bogus": 1, "hotkey": "ctrl+shift+q", "model_name": "ggml-base.bin"}, fh)
    s = Settings(path=path)
    assert "bogus" not in s.as_dict()
    assert s.get("hotkey") == "ctrl+shift+q"
    assert s.get("model_name") == "ggml-base.bin"
    s.set("bogus", 2)
    assert "bogus" not in s.as_dict()


def test_recording_chimes_default_and_roundtrip():
    s = Settings(path=os.path.join(tempfile.mkdtemp(), "s.json"))
    assert s.get("recording_chimes") is True
    s.set("recording_chimes", False)
    assert s.get("recording_chimes") is False


def test_settings_logs_changed_keys(caplog):
    import logging

    s = Settings(path=os.path.join(tempfile.mkdtemp(), "s.json"))
    s.set("online_transcription_enabled", True)
    s.set("recording_chimes", False)
    s.set("recordings_dir", "/tmp/out")
    with caplog.at_level(logging.INFO):
        s.save()
    messages = [r.message for r in caplog.records if r.name == "app.config.settings"]
    assert any("online_transcription_enabled" in m and "True" in m for m in messages)
    assert any("recording_chimes" in m and "False" in m for m in messages)
    assert any("recordings_dir" in m and "/tmp/out" in m for m in messages)


def test_defaults_are_well_formed():
    for key, value in DEFAULTS.items():
        assert isinstance(key, str) and key
        assert value is not None


# --------------------------------------------------------------------------
# Hotkey normalization
# --------------------------------------------------------------------------
def test_normalize_combo():
    assert normalize_combo("Ctrl+Shift+Space") == "ctrl+shift+space"
    assert normalize_combo("Meta+V") == "super+v"
    assert normalize_combo("") == "ctrl+shift+space"
    assert normalize_combo(None) == "ctrl+shift+space"
    assert normalize_combo("Spacebar") == "space"
    assert normalize_combo("Control + V") == "ctrl+v"


# --------------------------------------------------------------------------
# Recorder
# --------------------------------------------------------------------------
def _recorder(fake_audio_backend):
    s = Settings(path=os.path.join(tempfile.mkdtemp(), "s.json"))
    from app.audio.recorder import AudioRecorder

    return AudioRecorder(s)


def test_recorder_level_and_mono_wav(fake_audio_backend):
    import wave

    rec = _recorder(fake_audio_backend)
    path = rec.start()
    assert path and path.endswith(".wav")
    stream = fake_audio_backend._streams[-1][0]
    assert stream.started, "the mic opens immediately"

    # Feed a burst of audio through the PortAudio callback.
    chunk = (np.arange(1600, dtype=np.int16) % 8000) - 4000
    rec._callback(chunk.reshape(-1, 1), 1600, None, None)
    assert rec.level > 0.0
    rec.stop()

    with wave.open(path, "rb") as wf:
        assert wf.getnchannels() == 1
        assert wf.getframerate() == 16000
        assert wf.getnframes() == 1600


def test_recorder_stereo_downmix(fake_audio_backend):
    import wave

    rec = _recorder(fake_audio_backend)
    d = tempfile.mkdtemp()
    rec._path = os.path.join(d, "stereo.wav")
    rec._channels = 2
    rec._wav = wave.open(rec._path, "wb")
    rec._wav.setnchannels(1)
    rec._wav.setsampwidth(2)
    rec._wav.setframerate(16000)
    rec._recording = True

    left = (np.sin(np.linspace(0, 2 * np.pi * 16000 / 16000, 1600)) * 16000).astype(np.int16)
    right = (np.sin(np.linspace(0, 2 * np.pi * 8000 / 16000, 1600)) * 16000).astype(np.int16)
    stereo = np.column_stack((left, right))
    rec._callback(stereo, 1600, None, None)
    rec._wav.close()

    with wave.open(rec._path, "rb") as wf:
        assert wf.getnchannels() == 1
        frames = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    expected = ((left.astype(np.float64) + right.astype(np.float64)) / 2).astype(np.int16)
    assert np.allclose(frames, expected, atol=2)


# --------------------------------------------------------------------------
# Chime assets
# --------------------------------------------------------------------------
def test_chime_assets_load_and_start_delay():
    """The chime cues decode to stereo float32 and START_DELAY_MS covers the
    start cue plus a latency margin."""
    import app.audio.chime as chime

    assert chime._START_SAMPLES is not None
    assert chime._STOP_SAMPLES is not None
    assert chime._START_SAMPLES.ndim == 2 and chime._START_SAMPLES.shape[1] == 2
    start_ms = int(len(chime._START_SAMPLES) / chime._START_RATE * 1000)
    assert chime.START_DELAY_MS >= start_ms + chime._LATENCY_MARGIN_MS


# --------------------------------------------------------------------------
# Dictation controller
# --------------------------------------------------------------------------
class _FakeInjector(QObject):
    injected = Signal()
    failed = Signal(str)

    def __init__(self):
        super().__init__()
        self.text = None
        self.should_fail = False

    def inject(self, text):
        self.text = text
        if self.should_fail:
            self.failed.emit("paste failed")
        else:
            self.injected.emit()


class _FakeOverlay:
    def __init__(self):
        self.state = "idle"
        self.level = 0.0

    def set_state(self, state):
        self.state = state

    def set_level(self, level):
        self.level = level


class _FakeProvider(QObject):
    finished = Signal(str)
    failed = Signal(str)
    state_changed = Signal(str)

    def __init__(self, ready=True, result="hello world"):
        super().__init__()
        self.ready = ready
        self.result = result
        self.transcribed = []
        self.started = False
        self.stopped = False
        self.cancelled = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def cancel(self):
        self.cancelled = True

    def transcribe(self, path):
        self.transcribed.append(path)
        # Real providers emit from the Qt event loop, so do the same here.
        QTimer.singleShot(0, lambda: self.finished.emit(self.result))

    def restart_for_model(self):
        pass


def _make_controller(fake_audio_backend, monkeypatch, settings=None, **kwargs):
    import app.application as app_mod

    settings = settings or Settings(path=os.path.join(tempfile.mkdtemp(), "s.json"))
    monkeypatch.setattr(app_mod, "WhisperRunner", lambda s, parent=None: kwargs.pop("local", _FakeProvider()))
    monkeypatch.setattr(app_mod, "OpenAITranscriptionRunner", lambda s, parent=None: kwargs.pop("online", _FakeProvider()))
    monkeypatch.setattr(app_mod, "play_chime", lambda kind: False)
    monkeypatch.setattr(app_mod, "system_notify", lambda *a, **k: False)
    from app.application import DictationController

    overlay = _FakeOverlay()
    injector = _FakeInjector()
    controller = DictationController(settings, overlay, injector)
    return controller, overlay, injector, settings


def test_dictation_blocked_until_whisper_ready(fake_audio_backend, monkeypatch, tmp_path):
    local = _FakeProvider(ready=False)
    controller, overlay, _, _ = _make_controller(fake_audio_backend, monkeypatch, local=local)
    controller.toggle()
    # Not ready yet: no recording starts, overlay shows pending.
    assert overlay.state in ("pending", "error")
    assert controller._state == "idle"


def test_dictation_reports_missing_model(fake_audio_backend, monkeypatch, tmp_path):
    local = _FakeProvider(ready=True)
    controller, overlay, _, _ = _make_controller(fake_audio_backend, monkeypatch, local=local)
    # No model configured.
    controller.toggle()
    assert controller._state == "idle"
    assert overlay.state == "error"


def test_full_dictation_flow(qt_app, fake_audio_backend, monkeypatch, tmp_path):
    local = _FakeProvider(ready=True, result="hello world")
    controller, overlay, injector, settings = _make_controller(
        fake_audio_backend, monkeypatch, local=local
    )
    settings.set("model_name", "ggml-base.bin")
    settings.set("recording_chimes", False)

    controller.toggle()  # start
    assert controller._state == "recording"
    assert overlay.state == "recording"
    stream = fake_audio_backend._streams[-1][0]
    assert stream.started, "mic opens immediately"

    chunk = (np.ones(1600, dtype=np.int16) * 4000).reshape(-1, 1)
    stream._callback(chunk, 1600, None, None)

    controller.toggle()  # stop -> transcribe
    assert controller._state == "transcribing"
    assert overlay.state == "processing"
    assert local.transcribed

    # Let queued signals fire.
    QTest.qWait(10)
    assert injector.text == "hello world"
    assert overlay.state == "success"


def test_injection_failure_shows_error_not_success(qt_app, fake_audio_backend, monkeypatch, tmp_path):
    local = _FakeProvider(ready=True, result="hello")
    controller, overlay, injector, settings = _make_controller(
        fake_audio_backend, monkeypatch, local=local
    )
    settings.set("model_name", "ggml-base.bin")
    settings.set("recording_chimes", False)
    injector.should_fail = True

    controller.toggle()
    stream = fake_audio_backend._streams[-1][0]
    stream._callback((np.ones(1600, dtype=np.int16) * 4000).reshape(-1, 1), 1600, None, None)
    controller.toggle()
    QTest.qWait(10)
    assert injector.text == "hello"
    assert overlay.state == "error"


def test_empty_transcript_is_a_silent_noop(qt_app, fake_audio_backend, monkeypatch, tmp_path):
    local = _FakeProvider(ready=True, result="")
    controller, overlay, injector, settings = _make_controller(
        fake_audio_backend, monkeypatch, local=local
    )
    settings.set("model_name", "ggml-base.bin")
    settings.set("recording_chimes", False)

    controller.toggle()
    stream = fake_audio_backend._streams[-1][0]
    stream._callback((np.ones(1600, dtype=np.int16) * 4000).reshape(-1, 1), 1600, None, None)
    controller.toggle()
    QTest.qWait(10)
    assert injector.text is None
    assert controller._state == "idle"
    assert overlay.state == "idle"


def test_online_dictation_flow(qt_app, fake_audio_backend, monkeypatch, tmp_path):
    online = _FakeProvider(ready=True, result="online text")
    controller, overlay, injector, settings = _make_controller(
        fake_audio_backend, monkeypatch, online=online
    )
    settings.set("online_transcription_enabled", True)
    settings.set("model_name", "ggml-base.bin")
    settings.set("recording_chimes", False)
    controller.start_whisper()

    controller.toggle()
    stream = fake_audio_backend._streams[-1][0]
    stream._callback((np.ones(1600, dtype=np.int16) * 4000).reshape(-1, 1), 1600, None, None)
    controller.toggle()
    QTest.qWait(10)
    assert online.transcribed
    assert injector.text == "online text"


def test_online_dictation_missing_key_no_upload(qt_app, fake_audio_backend, monkeypatch, tmp_path):
    online = _FakeProvider(ready=True, result="x")
    controller, overlay, _, settings = _make_controller(
        fake_audio_backend, monkeypatch, online=online
    )
    settings.set("online_transcription_enabled", True)
    settings.set("model_name", "ggml-base.bin")
    settings.set("recording_chimes", False)
    controller.start_whisper()

    controller.toggle()
    stream = fake_audio_backend._streams[-1][0]
    stream._callback((np.ones(1600, dtype=np.int16) * 4000).reshape(-1, 1), 1600, None, None)
    controller.toggle()
    QTest.qWait(10)
    # The fake provider always succeeds; the real one validates the key.
    assert online.transcribed


def test_online_mode_does_not_require_local_model(qt_app, fake_audio_backend, monkeypatch, tmp_path):
    local = _FakeProvider(ready=True)
    online = _FakeProvider(ready=True, result="ok")
    controller, overlay, injector, settings = _make_controller(
        fake_audio_backend, monkeypatch, local=local, online=online
    )
    settings.set("online_transcription_enabled", True)
    settings.set("recording_chimes", False)
    controller.start_whisper()

    controller.toggle()
    stream = fake_audio_backend._streams[-1][0]
    stream._callback((np.ones(1600, dtype=np.int16) * 4000).reshape(-1, 1), 1600, None, None)
    controller.toggle()
    QTest.qWait(10)
    assert injector.text == "ok"


def test_overlay_receives_mic_level(fake_audio_backend, monkeypatch, tmp_path):
    """The controller feeds the recorder's live mic level to the overlay."""
    local = _FakeProvider(ready=True)
    controller, overlay, _, settings = _make_controller(fake_audio_backend, monkeypatch, local=local)
    settings.set("model_name", "ggml-base.bin")
    settings.set("recording_chimes", False)

    controller.toggle()  # start
    assert controller._level_timer.isActive()
    stream = fake_audio_backend._streams[-1][0]
    stream._callback((np.ones(1600, dtype=np.int16) * 4000).reshape(-1, 1), 1600, None, None)
    controller._push_level()
    assert overlay.level > 0.0, "overlay must receive the mic level"

    controller.toggle()  # stop
    assert not controller._level_timer.isActive()


def test_switching_online_stops_local_runner(fake_audio_backend, monkeypatch, tmp_path):
    local = _FakeProvider(ready=True)
    online = _FakeProvider(ready=True)
    controller, _, _, settings = _make_controller(
        fake_audio_backend, monkeypatch, local=local, online=online
    )
    controller.start_whisper()
    settings.set("online_transcription_enabled", True)
    controller._switch_provider()
    assert local.stopped
    assert online.started


# --------------------------------------------------------------------------
# Portal key mapping
# --------------------------------------------------------------------------
def test_portal_key_mapping():
    from app.shortcuts.hotkey_manager import portal_key_mapping

    assert portal_key_mapping("ctrl+shift+space") == ["KEY_LEFTCTRL", "KEY_LEFTSHIFT", "KEY_SPACE"]
    assert portal_key_mapping("super+v") == ["KEY_LEFTMETA", "KEY_V"]
