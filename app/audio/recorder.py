"""Microphone recorder.

Records 16 kHz mono (with graceful fallbacks) into a temp WAV file while
exposing the current audio level for the overlay's waveform animation.

The PortAudio callback runs on its own thread; ``level`` is a plain float
written by that thread and read by the GUI thread (safe under the GIL). The
GUI polls it from a QTimer rather than receiving a per-frame signal.
"""

import logging
import os
import time
import wave

import numpy as np
from PySide6.QtCore import QObject

from app.config.settings import cache_dir

log = logging.getLogger(__name__)


class RecorderError(Exception):
    """Raised when the microphone cannot be opened or recorded to."""


def _sounddevice():
    """Import sounddevice lazily so the app can start without PortAudio.

    Raises a :class:`RecorderError` with install instructions when the
    PortAudio shared library (``libportaudio2``) is not installed.
    """
    try:
        import sounddevice as sd

        return sd
    except OSError as exc:
        raise RecorderError(
            "Audio backend not available (%s). Install libportaudio2:\n"
            "  sudo apt-get install libportaudio2" % exc
        ) from exc


def list_input_devices():
    """Return metadata dicts for all available input devices."""
    try:
        sd = _sounddevice()
        devices = sd.query_devices()
        result = []
        for index, dev in enumerate(devices):
            if int(dev.get("max_input_channels", 0)) > 0:
                result.append(
                    {
                        "index": index,
                        "name": dev["name"],
                        "channels": int(dev["max_input_channels"]),
                    }
                )
        return result
    except Exception as exc:
        log.warning("Could not query audio devices: %s", exc)
        return None


def resolve_device_id(name_or_index):
    """Resolve the stored mic setting (name or index) to a PortAudio index.

    Returns None when empty, which makes sounddevice use the system default.
    """
    if name_or_index is None or name_or_index == "":
        return None
    if isinstance(name_or_index, int):
        return name_or_index
    text = str(name_or_index).strip()
    if text.isdigit():
        return int(text)
    for dev in list_input_devices() or []:
        if dev["name"] == text or text in dev["name"]:
            return dev["index"]
    return None


class AudioRecorder(QObject):
    """Streams microphone input into a mono 16 kHz WAV file.

    The PortAudio callback thread appends decoded int16 frames to the open
    ``wave`` file and updates ``level`` (a plain float the GUI polls).
    """

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._stream = None
        self._wav = None
        self._path = None
        self._channels = 1
        self._recording = False
        self._skip_frames = 0
        self.level = 0.0

    @property
    def recording(self):
        return self._recording

    def start(self, skip_ms=0):
        """Begin recording into a fresh temp WAV; returns its path.

        ``skip_ms`` drops that many milliseconds from the start of the audio
        (used to keep the start chime out of the transcript). The mic still
        opens immediately either way.
        """
        sd = _sounddevice()
        rate = int(self._settings.get("sample_rate") or 16000)
        device = resolve_device_id(self._settings.get("mic_device"))
        self._channels = 1
        self._recording = True
        self.level = 0.0
        self._skip_frames = int((skip_ms / 1000.0) * rate)
        os.makedirs(cache_dir(), exist_ok=True)
        self._path = os.path.join(cache_dir(), "recording_%d.wav" % int(time.time()))
        self._wav = wave.open(self._path, "wb")
        self._wav.setnchannels(1)
        self._wav.setsampwidth(2)
        self._wav.setframerate(rate)
        self._stream = sd.InputStream(
            samplerate=rate,
            channels=self._channels,
            dtype="int16",
            device=device,
            callback=self._callback,
        )
        self._stream.start()
        log.info("Microphone opened (device=%r, rate=%d) -> %s", device, rate, self._path)
        return self._path

    def _callback(self, indata, frames, time_info, status):
        data = np.asarray(indata).copy()
        if data.ndim == 2 and data.shape[1] > 1:
            # Downmix any stereo/surround input to mono.
            data = data.mean(axis=1).astype(np.int16)
        if self._skip_frames > 0:
            # Trim the start chime window so it never lands in the transcript.
            if len(data) <= self._skip_frames:
                self._skip_frames -= len(data)
                return
            data = data[self._skip_frames:]
            self._skip_frames = 0
        if self._wav is not None:
            self._wav.writeframes(data.tobytes())
        self.level = float(np.abs(data).mean() / 32768.0)

    def stop(self):
        """Stop recording, finalize the WAV, and return its path."""
        if self._stream is not None:
            try:
                self._stream.stop()
            finally:
                self._stream.close()
                self._stream = None
        self._recording = False
        self.level = 0.0
        if self._wav is not None:
            self._wav.close()
            self._wav = None
        log.info("Recording stopped -> %s", self._path)
        return self._path

    def cleanup(self):
        """Remove the temp WAV if one exists."""
        if self._path and os.path.exists(self._path):
            try:
                os.remove(self._path)
            except OSError as exc:
                log.warning("Could not remove temp recording %s: %s", self._path, exc)
        self._path = None
