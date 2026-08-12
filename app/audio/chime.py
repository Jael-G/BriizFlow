"""Recording chimes — start/stop feedback from bundled audio assets.

The start cue is ``app/assets/recording_start_sfx.wav`` and the stop cue is
``app/assets/recording_end_sfx.wav``, each played through the default output
device when recording begins and ends. Both are decoded once at import into
stereo float32 arrays (``miniaudio``), then played with ``sounddevice``
(already a hard dependency for the mic, so it's imported lazily like in
``app.audio.recorder``).

Purely cosmetic: every failure is swallowed and :func:`play_chime` returns
``False``, so a missing asset, miniaudio or output device never delays or
blocks dictation.
"""

import logging
import os

import numpy as np

log = logging.getLogger(__name__)
_LATENCY_MARGIN_MS = 80
_ASSET_NAMES = {"start": "recording_start_sfx.wav", "stop": "recording_end_sfx.wav"}


def _asset_path(filename):
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", filename
    )


def _load(filename):
    """Decode ``filename`` to stereo float32; ``(samples, rate)``.

    Returns ``(None, 44100)`` — never raises — when the asset, miniaudio or a
    decoder is unavailable.
    """
    try:
        import miniaudio

        decoded = miniaudio.decode_file(
            _asset_path(filename), output_format=miniaudio.SampleFormat.FLOAT32
        )
        samples = np.frombuffer(decoded.samples, dtype=np.float32).reshape(-1, decoded.nchannels)
        if decoded.nchannels == 1:
            samples = np.column_stack((samples, samples))
        return (samples, decoded.sample_rate)
    except Exception as exc:
        log.debug("Chime asset unavailable: %s", exc)
        return (None, 44100)


_START_SAMPLES, _START_RATE = _load(_ASSET_NAMES["start"])
_STOP_SAMPLES, _STOP_RATE = _load(_ASSET_NAMES["stop"])


def _cue_duration_ms(samples, rate):
    if samples is None:
        return 0
    return int(len(samples) / rate * 1000)


# How long to wait after the start chime before dictation audio counts, so the
# cue itself never lands in the transcript (cue duration + latency margin).
START_DELAY_MS = _LATENCY_MARGIN_MS + _cue_duration_ms(_START_SAMPLES, _START_RATE)


def play_chime(kind):
    """Play the start/stop cue; ``False`` on any failure (never raises)."""
    samples, rate = (
        (_START_SAMPLES, _START_RATE) if kind == "start" else (_STOP_SAMPLES, _STOP_RATE)
    )
    if samples is None:
        return False
    try:
        import sounddevice as sd

        sd.play(samples, rate)
        return True
    except Exception as exc:
        log.debug("Could not play %s chime: %s", kind, exc)
        return False
