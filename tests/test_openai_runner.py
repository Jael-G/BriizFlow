"""OpenAI transcription backend tests (no network: the QNAM is faked)."""

import json

import pytest
from PySide6.QtNetwork import QNetworkReply

from app.transcription.openai_runner import (
    build_transcription_body,
    classify_failure,
    language_hint_value,
    parse_transcription_response,
    redact,
)


def test_redact_masks_sk_tokens():
    assert redact("key sk-abcdef123456") == "key sk-***"
    assert redact("sk-ABC_1234-xyz") == "sk-***"
    assert redact("no secret") == "no secret"
    assert redact(None) is None


def test_language_hint_value():
    assert language_hint_value("whisper-1", "auto") is None
    assert language_hint_value("whisper-1", "") is None
    assert language_hint_value("whisper-1", "en") == ("language", "en")
    assert language_hint_value("gpt-transcribe", "es") == ("languages", '["es"]')
    assert language_hint_value("whisper-1", " EN ") == ("language", "en")


def test_model_label_roundtrip():
    """Every curated model label maps to an id and back without loss."""
    from app.transcription.models import model_id_for_label, model_label_for_id, model_labels

    for label in model_labels():
        model_id = model_id_for_label(label)
        assert model_id is not None
        assert model_label_for_id(model_id) == label
    assert model_label_for_id("gpt-some-future-model") is None


def test_build_transcription_body_file_model_format():
    body = build_transcription_body(b"WAVDATA", "whisper-1", "en", "BOUNDARY")
    assert body.startswith(b"--BOUNDARY\r\n")
    assert b'name="file"; filename="audio.wav"' in body
    assert b'WAVDATA' in body
    assert b'name="model"' in body and b"whisper-1" in body
    assert b'name="response_format"' in body
    assert b'name="language"' in body
    assert body.endswith(b"--BOUNDARY--\r\n")


def test_build_transcription_body_auto_omits_hint():
    body = build_transcription_body(b"WAVDATA", "whisper-1", "auto", "B")
    assert b"language" not in body


def test_build_transcription_body_languages_field_for_gpt_transcribe():
    body = build_transcription_body(b"WAVDATA", "gpt-transcribe", "es", "B")
    assert b'name="languages"' in body
    assert b'["es"]' in body


def test_parse_transcription_response():
    assert parse_transcription_response(b'{"text": " hello "}') == ("hello", "ok")
    assert parse_transcription_response(b'{"text": ""}') == ("", "empty")
    assert parse_transcription_response(b'{"text": "   "}') == ("", "empty")
    assert parse_transcription_response(b"not json") == ("", "invalid")
    assert parse_transcription_response(b'[1,2,3]') == ("", "invalid")
    assert parse_transcription_response(b'{"nope": 1}') == ("", "invalid")


def test_classify_failure_http_status_wins():
    assert "API key" in classify_failure(QNetworkReply.NoError, 401, b'{"error":{"message":"bad"}}')
    assert "rate limit" in classify_failure(QNetworkReply.NoError, 429)
    assert "temporarily unavailable" in classify_failure(QNetworkReply.NoError, 503)
    assert "rejected the recording" in classify_failure(QNetworkReply.NoError, 400)
    assert classify_failure(QNetworkReply.NoError, 400, b'{"error":{"message":"bad audio"}}') == "OpenAI rejected the recording: bad audio"


def test_classify_failure_network_errors():
    assert "internet" in classify_failure(QNetworkReply.HostNotFoundError, 0)
    assert "internet" in classify_failure(QNetworkReply.ConnectionRefusedError, 0)
    assert "timed out" in classify_failure(QNetworkReply.TimeoutError, 0)
    assert "secure connection" in classify_failure(QNetworkReply.SslHandshakeFailedError, 0)
    assert classify_failure(QNetworkReply.RemoteHostClosedError, 0) == "OpenAI transcription failed."
