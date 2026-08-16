"""Text cleanup tests: prompt construction, request body, response parsing.

No network: the pure helpers are tested directly, and the ``TextCleanupRunner``
only exercises its no-request paths (mode ``none``, empty transcript), which
emit synchronously without touching the QNAM.
"""

import json

import pytest
from PySide6.QtNetwork import QNetworkReply

from app.transcription.cleanup import (
    BASE_INSTRUCTIONS,
    CLEANUP_MODEL,
    build_cleanup_instructions,
    build_chat_completion_body,
    classify_cleanup_failure,
    parse_cleanup_response,
)

MODES = ("clean", "polish", "compact")


# --------------------------------------------------------------------------
# Prompt construction
# --------------------------------------------------------------------------
def test_build_cleanup_instructions_none_returns_none():
    assert build_cleanup_instructions("none") is None
    assert build_cleanup_instructions("") is None
    assert build_cleanup_instructions(None) is None
    # A stale/unrecognized persisted value disables cleanup, never crashes.
    assert build_cleanup_instructions("bogus") is None


def test_build_cleanup_instructions_includes_base_and_exactly_one_mode():
    for mode in MODES:
        prompt = build_cleanup_instructions(mode)
        assert prompt is not None
        assert prompt.startswith(BASE_INSTRUCTIONS)
        assert "Mode: %s" % mode.title() in prompt
        for other in MODES:
            if other != mode:
                assert "Mode: %s" % other.title() not in prompt


def test_build_cleanup_instructions_is_case_insensitive():
    assert build_cleanup_instructions("POLISH") == build_cleanup_instructions("polish")


# --------------------------------------------------------------------------
# Request body (stateless: system + user only)
# --------------------------------------------------------------------------
def test_chat_completion_body_only_instructions_and_transcript():
    body = json.loads(build_chat_completion_body("INSTRUCTIONS", "RAW TRANSCRIPT"))
    assert body["model"] == CLEANUP_MODEL
    roles = [m["role"] for m in body["messages"]]
    assert roles == ["system", "user"]
    assert body["messages"][0]["content"] == "INSTRUCTIONS"
    assert body["messages"][1]["content"] == "RAW TRANSCRIPT"
    assert body["temperature"] == 0
    # No history, no tools, no extra keys beyond the minimal request.
    assert set(body) <= {"model", "messages", "temperature"}


# --------------------------------------------------------------------------
# Response parsing
# --------------------------------------------------------------------------
def test_parse_cleanup_response_extracts_content():
    data = json.dumps({"choices": [{"message": {"role": "assistant", "content": "  cleaned  "}}]})
    assert parse_cleanup_response(data.encode("utf-8")) == "cleaned"


def test_parse_cleanup_response_invalid_returns_none():
    assert parse_cleanup_response(b"not json") is None
    assert parse_cleanup_response(b'{"nope": 1}') is None
    assert parse_cleanup_response(b'{"choices": []}') is None
    assert parse_cleanup_response(b'{"choices": [{"message": {}}]}') is None
    assert parse_cleanup_response(b'{"choices": [{"message": {"content": ""}}]}') is None
    assert parse_cleanup_response(b'{"choices": [{"message": {"content": 42}}]}') is None


# --------------------------------------------------------------------------
# Failure classification
# --------------------------------------------------------------------------
def test_classify_cleanup_failure():
    assert "API key" in classify_cleanup_failure(QNetworkReply.NoError, 401)
    assert "rate limit" in classify_cleanup_failure(QNetworkReply.NoError, 429)
    assert "temporarily unavailable" in classify_cleanup_failure(QNetworkReply.NoError, 503)
    assert "internet" in classify_cleanup_failure(QNetworkReply.HostNotFoundError, 0)
    assert "timed out" in classify_cleanup_failure(QNetworkReply.TimeoutError, 0)
    assert classify_cleanup_failure(QNetworkReply.RemoteHostClosedError, 0) == "OpenAI cleanup request failed."


# --------------------------------------------------------------------------
# Runner: no-request paths (no QNAM hit, synchronous emit)
# --------------------------------------------------------------------------
def test_cleanup_runner_none_mode_passthrough(qt_app, settings):
    from app.transcription.cleanup import TextCleanupRunner

    runner = TextCleanupRunner(settings)
    got = []
    runner.finished.connect(got.append)
    runner.cleanup("hello world", "none")
    assert got == ["hello world"]
    assert runner._reply is None


def test_cleanup_runner_empty_text_makes_no_request(qt_app, settings):
    from app.transcription.cleanup import TextCleanupRunner

    runner = TextCleanupRunner(settings)
    got = []
    runner.finished.connect(got.append)
    runner.cleanup("   ", "clean")
    assert got == ["   "]
    assert runner._reply is None
