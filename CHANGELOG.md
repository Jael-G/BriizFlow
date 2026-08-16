# Changelog

All notable changes to BriizFlow are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-08-16

### Added
- **Text Cleanup** — an optional post-transcription pass that tidies your
  dictation before it's pasted. Pick **Clean** (removes filler words,
  stutters, and false starts), **Polish** (also fixes grammar and phrasing so
  it reads naturally), or **Compact** (also makes it substantially more
  concise). It works with both the local `whisper.cpp` and OpenAI backends —
  it operates on the text, not the audio — and uses a small GPT model. If a
  cleanup request ever fails, the original transcript is pasted unchanged.
- New `speech_cleanup` setting (`none` / `clean` / `polish` / `compact`),
  exposed as a **Cleanup level** dropdown in the Settings.

### Changed
- The online transcription section is now titled **OpenAI features**, with the
  toggle labelled **Online transcription** and the model picker **Transcription
  model**. Cleanup level and the API key live in the same section.

## [0.1.1] - 2026-08-12

### Fixed
- AppImage packaging now produces a working AppImage: absolute asset paths
  for PyInstaller, a bundled desktop entry and icon, the `ARCH` env var for
  appimagetool, and an `AppRun` launcher so the app actually starts.

### Changed
- Removed the unused `APP_VERSION` constant; `app.__version__` is now the
  single source of truth for the version.