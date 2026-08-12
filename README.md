# BriizFlow

<p align="center">
  <img src="app/assets/icon.svg" alt="BriizFlow" width="128">
</p>

> **Don't type. Just talk.**
>
> BriizFlow turns your voice into text and puts it directly into the application you're using.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-FCC624.svg)](pyproject.toml)[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB.svg)](pyproject.toml)[![Desktop: X11 and Wayland](https://img.shields.io/badge/Desktop-X11%20%7C%20Wayland-4C9A2A.svg)](pyproject.toml)

BriizFlow is speech-to-text for Linux that lives quietly in your system tray. Hit a hotkey, say what you mean, hit it again — your words land right at your cursor, in whatever app you have focused. No copy-paste relay. No switching windows. No breaking your flow. Just talk, and keep working.

Run it fully offline with `whisper.cpp` and your voice never leaves your machine. Or flip on OpenAI's transcription API and trade privacy for a hosted model. Your call — BriizFlow never switches backends behind your back.

<br>

## See it in action

> 🎥 **Demo coming soon** — watch the whole loop: focus a text field → hotkey → talk → hotkey → text appears.

<br>

## Why BriizFlow?

Most dictation tools make you choose between *fast* and *private*. BriizFlow doesn't.

- **Speak into any app** — no dedicated editor, no clipboard juggling. The transcript is typed straight into whatever has focus.
- **Offline and private by default** — local transcription via `whisper.cpp`. Nothing leaves your machine unless you explicitly turn on OpenAI mode.
- **One hotkey, zero friction** — press to record, press to stop. BriizFlow handles the rest: transcription, clipboard, paste.
- **Easily swappable models** — from a 75 MB `tiny` for speed to a 3 GB `large-v3` for accuracy. Download and swap from inside the app.
- **Tray-first, out of your way** — no dock icon. It sits in the tray until you need it.
- **Built for real Linux desktops** — X11 and Wayland, with sane fallbacks when a compositor doesn't support global shortcuts.

<br>

## Local vs. online transcription

| | Local Whisper | OpenAI |
|---|---|---|
| **Audio goes to** | Your machine, only | OpenAI's API |
| **Setup** | Download a model once | Enable online mode + add an API key |
| **Needs network while dictating?** | No | Yes |
| **API key required?** | No | Yes |

Online mode is off by default — flip it on in Settings. Recordings over 25 MB are rejected before upload, and requests time out after 60 seconds.

<br>

## Quick start

```bash
./install.sh
./briizflow
```

The installer checks for Python 3.10+, installs system dependencies via `apt`, sets up a virtual environment, and downloads a verified `whisper.cpp` runtime. It does **not** download a speech model — BriizFlow asks you to pick one on first launch:

1. Launch with `./briizflow` — the **Models** page opens automatically.
2. Download a model (tiny and fast, or large and accurate — your call).
3. Pick a microphone in Settings.
4. Click into any text field.
5. Press `Ctrl+Shift+Space` to start talking.
6. Press it again — your words appear where your cursor is.

If your desktop doesn't support global shortcuts (some Wayland setups), the tray menu always works as a fallback.

Want to configure things before your first recording?

```bash
./briizflow --settings
```

### Building a portable AppImage

```bash
.venv/bin/python packaging/build_appimage.py
```

Produces `dist/briizflow-<version>-<arch>.AppImage` — Python, Qt, PortAudio and the whisper server bundled, ready to run on a clean Ubuntu desktop.

<br>

## Models

### Local models

Whisper runs entirely on your machine. All models come from the public [`ggerganov/whisper.cpp`](https://huggingface.co/ggerganov/whisper.cpp) repository, downloaded and managed from inside the app.

| Model | Size | Good for |
|---|---:|---|
| `ggml-tiny.bin` | 75 MB | Fastest, lowest accuracy — quick notes |
| `ggml-base.bin` | 142 MB | Solid everyday default |
| `ggml-small.bin` | 466 MB | Better accuracy, still fast |
| `ggml-medium.bin` | 1.53 GB | High accuracy, more resource use |
| `ggml-large-v3.bin` | 3.09 GB | Best accuracy available |
| `ggml-large-v3-turbo.bin` | 1.62 GB | Large-model accuracy, faster inference |


### OpenAI models

Prefer a hosted model? Enable online transcription in Settings and pick one (requires OpenAI Api key):

- `gpt-transcribe` — the default
- `gpt-4o-transcribe`
- `gpt-4o-mini-transcribe`
- `whisper-1`

<br>

## Requirements

- Ubuntu/Debian-based distros (`apt`)
- x86_64 (the installer grabs the Ubuntu x86_64 `whisper.cpp` build)
- Python 3.10+
- A graphical desktop with a system tray
- A working microphone

Other distros or architectures can work if you install a compatible `whisper-server` yourself, but that's not the paved path yet.


### X11 vs. Wayland

X11 is the smoothest experience — global shortcuts and paste both just work. Wayland works too, but depends on your compositor:

| | X11 | Wayland |
|---|---|---|
| Global hotkey | Native | Via XDG `GlobalShortcuts` portal, or XWayland fallback |
| Paste | Clipboard + XTEST | Clipboard + `ydotool` or `wtype` |
| Watch out for | Paste shortcut varies by app | No universal paste-injection API — depends on your compositor |

`wtype` works out of the box on wlroots compositors like Sway and Hyprland. `ydotool` needs its daemon running. If neither is available, BriizFlow still puts the transcript on your clipboard — you'll just need to paste manually. In most terminals the paste shortcut is `Ctrl+Shift+V`, not `Ctrl+V` — you can change this in Settings.

<br>

## Privacy

- **Local mode**: your voice never leaves your machine. Temporary recordings live in `~/.cache/briizflow` and are auto-deleted after 7 days. Saving recordings permanently is off by default.
- **Online mode**: audio is uploaded to OpenAI only when you've explicitly enabled it.
- **API keys**: stored in your system keyring (freedesktop Secret Service). No keyring available? BriizFlow keeps the key in memory for the session and forgets it on exit — never written to disk.
- **Clipboard**: your transcript sits on the clipboard briefly to get pasted. Clipboard restoration afterward is optional and off by default (some apps read the clipboard lazily, so restoring too fast can break them).

<br>

## Configuration

Everything lives in standard XDG locations:

| Item | Location |
|---|---|
| Settings | `~/.config/briizflow/settings.json` |
| Temp recordings / cache | `~/.cache/briizflow` |
| Downloaded models | `~/.local/share/briizflow/models` |
| Saved recordings (if enabled) | `~/BriizFlowRecordings` |

Defaults: `Ctrl+Shift+Space` to dictate, `Ctrl+V` to paste, local transcription, recording chimes on, saved recordings off, clipboard restoration off. Change any of it in `./briizflow --settings`.

<br>

## License & credits

BriizFlow is [MIT licensed](LICENSE). © 2026 Jael Gonzalez.

Built on [`whisper.cpp`](https://github.com/ggml-org/whisper.cpp) (MIT) and [`ggml`](https://github.com/ggml-org/ggml) for local transcription, with UI icons from [Lucide](https://lucide.dev) (ISC; some icons derive from [Feather](https://feathericons.com), MIT). Binary releases also bundle Qt/PySide6 and other Python dependencies, PortAudio, and the whisper.cpp runtime — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) for the complete list and licenses.

<br>

<sub>
⚠️ This project was developed with the assistance of multiple AI tools and models.
</sub>
