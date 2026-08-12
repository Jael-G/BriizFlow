"""Whisper runner tests: arg filtering, server command, inference body."""

import pytest

from app.config.settings import Settings
from app.whisper import runner as runner_module
from app.whisper.runner import (
    build_inference_body,
    build_server_command,
    filter_server_args,
    find_whisper_server,
    parse_inference_response,
)


def test_filter_server_args_keeps_server_options_and_drops_cli_only():
    (kept, dropped) = filter_server_args(
        '-t 4 --no-fallback -f /tmp/x.wav -nt --prompt "hi there" -m other.bin'
    )
    assert kept == ["-t", "4", "--no-fallback", "-nt", "--prompt", "hi there"]
    assert dropped == ["-f", "/tmp/x.wav", "-m", "other.bin"]


def test_filter_server_args_bad_quoting_raises():
    with pytest.raises(ValueError):
        filter_server_args('"unterminated')


def test_build_server_command_includes_model_host_port_lang_and_extra():
    s = Settings(path="/tmp/nonexistent.json")
    s.set("whisper_language", "en")
    s.set("whisper_extra_args", "-t 4 -f junk.bin")
    args = build_server_command(s, "/bin/whisper-server", "/models/ggml-base.bin", "127.0.0.1", 9999)
    assert args == [
        "-m", "/models/ggml-base.bin",
        "--host", "127.0.0.1",
        "--port", "9999",
        "-l", "en",
        "-t", "4",
    ]


def test_build_server_command_default_language_is_auto():
    s = Settings(path="/tmp/nonexistent.json")
    args = build_server_command(s, "exe", "m.bin", "127.0.0.1", 1)
    assert args[args.index("-l") + 1] == "auto"


def test_build_inference_body_is_multipart_with_file_lang_format():
    body = build_inference_body(b"WAVBYTES", "es", "BOUND")
    assert body.startswith(b"--BOUND\r\n")
    assert b'name="file"; filename="audio.wav"' in body
    assert b"WAVBYTES" in body
    assert b'name="language"' in body and b"es" in body
    assert b'name="response_format"' in body
    assert body.endswith(b"--BOUND--\r\n")


def test_parse_inference_response_extracts_text():
    assert parse_inference_response(b'{"text": "hi there"}') == "hi there"
    assert parse_inference_response(b'{"text": ""}') == ""
    assert parse_inference_response(b"junk") == ""
    assert parse_inference_response(b'[]') == ""


def _make_fake_server(path):
    """Create a fake executable ``whisper-server`` at ``path``."""
    path.parent.mkdir(parents=True)
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    return path


def test_find_whisper_server_finds_bundled(tmp_path, monkeypatch):
    """Locates the canonical ``bin/whisper.cpp/whisper-server`` layout."""
    server = _make_fake_server(tmp_path / "project" / "bin" / "whisper.cpp" / "whisper-server")
    monkeypatch.setattr(runner_module, "project_root", lambda: str(tmp_path / "project"))
    assert find_whisper_server() == str(server)


def test_find_whisper_server_legacy_flat_layout(tmp_path, monkeypatch):
    """Falls back to the legacy ``<project_root>/bin/whisper-server`` layout."""
    server = _make_fake_server(tmp_path / "project" / "bin" / "whisper-server")
    monkeypatch.setattr(runner_module, "project_root", lambda: str(tmp_path / "project"))
    assert find_whisper_server() == str(server)


def test_find_whisper_server_missing_returns_none(tmp_path, monkeypatch):
    """Returns ``None`` when no bundled server is present (e.g. a fresh CI checkout)."""
    monkeypatch.setattr(runner_module, "project_root", lambda: str(tmp_path / "project"))
    assert find_whisper_server() is None
