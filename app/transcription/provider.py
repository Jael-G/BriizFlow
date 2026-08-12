"""Provider boundary shared by the local and online transcription backends.

Both backends implement the same asynchronous signal/method contract so the
controller can drive either one uniformly:

* ``finished(str)`` / ``failed(str)`` / ``state_changed(str)``
* ``start()`` / ``stop()`` / ``cancel()`` / ``transcribe(wav_path)``

Selection is explicit via the ``online_transcription_enabled`` setting. Online
failures must not silently fall back to local transcription — BriizFlow always
surfaces the failure and returns to idle.

(PySide6's ``QObject`` metaclass cannot combine with ``ABCMeta``, so the
contract is expressed as a concrete base whose methods raise
``NotImplementedError``.)
"""

from PySide6.QtCore import QObject, Signal


class TranscriptionProvider(QObject):
    """The common contract every transcription backend implements."""

    finished = Signal(str)
    failed = Signal(str)
    state_changed = Signal(str)

    def start(self):
        """Bring the backend to a ready state (no network probe required)."""
        raise NotImplementedError

    def stop(self):
        """Shut the backend down and return it to idle."""
        raise NotImplementedError

    def cancel(self):
        """Abort any in-flight transcription."""
        raise NotImplementedError

    def transcribe(self, wav_path):
        """Transcribe a WAV file; emit ``finished`` or ``failed``."""
        raise NotImplementedError
