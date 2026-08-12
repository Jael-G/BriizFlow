# Third-party notices

BriizFlow is [MIT licensed](LICENSE), © 2026 Jael Gonzalez. This file lists the
third-party components it uses — in the source tree, in the bundled whisper.cpp
runtime, or inside the portable AppImage release — and where each one's license
can be found. Every component is used under its original license, unmodified.

## Bundled in the repository

| Component | Purpose | License | License text |
|---|---|---|---|
| whisper.cpp + ggml | Local transcription runtime (server binary + shared libraries, `bin/whisper.cpp/`) | MIT | `bin/whisper.cpp/LICENSE` |
| Lucide icons | UI icons (`app/ui/lucide/`) | ISC | `app/ui/lucide/LICENSE` — also covers the Feather-derived icons it includes (MIT) |

## Bundled in the AppImage — Python packages

Pulled in by PyInstaller alongside the app and distributed in binary releases.
All are used unmodified and remain dynamically linked.

| Package | License (SPDX) |
|---|---|
| PySide6, PySide6-Essentials, PySide6-Addons | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| shiboken6 | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only |
| sounddevice | MIT |
| numpy | BSD-3-Clause |
| miniaudio | MIT |
| pynput | LGPL-3.0-only |
| python-xlib | LGPL-2.1-or-later |
| dbus-next | MIT |
| secretstorage | BSD-3-Clause |
| cffi | MIT-0 |
| cryptography | Apache-2.0 OR BSD-3-Clause |
| jeepney | MIT |
| evdev | BSD-3-Clause |
| six | MIT |
| pycparser | BSD-3-Clause |

> **About the LGPL packages.** PySide6, shiboken6, pynput, and python-xlib are
> used unmodified and stay dynamically linked (separate `.so` files in the
> bundle), so end users can replace them with their own builds as the LGPL
> requires. Because BriizFlow is MIT-licensed open source, the application's
> own source is always available; the LGPL libraries' source is available from
> each project's upstream repository.

## Bundled in the AppImage — system libraries

| Component | Purpose | License |
|---|---|---|
| PortAudio (`libportaudio.so.2`) | Cross-platform audio I/O for the microphone | MIT (© 1999–2002 Ross Bencina and Phil Burk) |

## Build tooling embedded in the binary

| Component | License |
|---|---|
| PyInstaller bootloader | GPL-2.0-or-later WITH Bootloader-exception (permits distribution inside produced executables) |

## Downloaded at runtime — not distributed

Speech models are fetched by the app from the official
[`ggerganov/whisper.cpp`](https://huggingface.co/ggerganov/whisper.cpp) Hugging
Face repository and are subject to the licenses stated there. They are never
bundled with or redistributed by BriizFlow.
