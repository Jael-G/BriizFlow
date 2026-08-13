# Changelog

All notable changes to BriizFlow are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.0.0/), and the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-08-12

### Fixed
- AppImage packaging now produces a working AppImage: absolute asset paths
  for PyInstaller, a bundled desktop entry and icon, the `ARCH` env var for
  appimagetool, and an `AppRun` launcher so the app actually starts.

### Changed
- Removed the unused `APP_VERSION` constant; `app.__version__` is now the
  single source of truth for the version.