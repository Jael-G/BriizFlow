"""Curated OpenAI transcription models: display labels <-> API IDs.

Labels stay separate from API IDs so a provider rename never corrupts
persisted settings, and only allow-listed IDs can ever be sent to the API.
The ``language_hint`` entry records the language-hint request field each model
accepts — the model's contract, independent of what the user set. ``whisper-1``
and the GPT-4o transcription models take the singular ``language`` field;
``gpt-transcribe`` takes the plural ``languages`` field (a JSON array of
expected languages). A model whose entry has no ``language_hint`` accepts no
hint at all, and none is ever sent for it.
"""

OPENAI_MODELS = [
    {"label": "GPT Transcribe", "id": "gpt-transcribe", "language_hint": "languages"},
    {"label": "GPT-4o Transcribe", "id": "gpt-4o-transcribe", "language_hint": "language"},
    {"label": "GPT-4o Mini Transcribe", "id": "gpt-4o-mini-transcribe", "language_hint": "language"},
    {"label": "Whisper", "id": "whisper-1", "language_hint": "language"},
]


def model_labels():
    """Return the display labels in menu order."""
    return [m["label"] for m in OPENAI_MODELS]


def model_id_for_label(label):
    """Map a display label to its API id, or ``None``."""
    for m in OPENAI_MODELS:
        if m["label"] == label:
            return m["id"]
    return None


def model_label_for_id(model_id):
    """Map an API id back to its display label, or ``None``."""
    for m in OPENAI_MODELS:
        if m["id"] == model_id:
            return m["label"]
    return None


def is_valid_model(model_id):
    """Whether ``model_id`` is an allow-listed API id."""
    return any(m["id"] == model_id for m in OPENAI_MODELS)


def language_hint_field(model_id):
    """The language-hint request field a model accepts, or ``None`` when it
    accepts no hint at all (so the hint must never be sent, even if the user
    picked a language)."""
    for m in OPENAI_MODELS:
        if m["id"] == model_id:
            return m.get("language_hint")
    return None
