#!/usr/bin/env bash
# One-shot installer for Ubuntu/Debian-style systems.
#
# It installs the system libraries BriizFlow needs, creates (or reuses) a virtualenv,
# installs the Python dependencies, and downloads the pinned whisper.cpp server
# into bin/whisper.cpp/ if it is not already present. It does NOT download a
# model — that happens in-app from the Models page.
set -euo pipefail
cd "$(dirname "$0")"

# ---- 0. Python version check ------------------------------------------------
PY="python3"
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "error: python3 is not installed." >&2
  echo "  Install it with: sudo apt-get install python3 python3-venv python3-pip" >&2
  exit 1
fi

pyver=$("$PY" -c 'import sys; print("%d.%d" % sys.version_info[:2])')
major=${pyver%%.*}
minor=${pyver#*.}
if [ "$major" -lt 3 ] || { [ "$major" -eq 3 ] && [ "$minor" -lt 10 ]; }; then
  echo "error: BriizFlow needs Python >= 3.10 (found $pyver)." >&2
  exit 1
fi
echo "==> Python $pyver detected."

# ---- 1. System packages ------------------------------------------------------
# This list covers everything BriizFlow needs on a clean Ubuntu/Debian desktop:
# Python tooling, PortAudio for the microphone, the shared libraries that
# PySide6's bundled Qt links against (for both the X11 and Wayland platform
# plugins), and the clipboard helper for Wayland. The X11 libraries are
# harmless on a Wayland system and vice versa — the full set is what makes a
# minimal install work.
#
#  * `curl` + `ca-certificates` are used in step 3 to download and verify the
#    pinned whisper.cpp server over HTTPS.
#  * `libportaudio2` is the PortAudio C library that `sounddevice` talks to.
#  * `libgomp1` is the OpenMP runtime library that the bundled whisper-server
#    links against.
#  * `libegl1` / `libgl1` / `libfontconfig1` / `libfreetype6` / `libdbus-1-3` /
#    `libglib2.0-0` / `libssl3` / `libxkbcommon0` / `libxkbcommon-x11-0` are the
#    Qt runtime and its EGL/GL/font/DBus/XKB dependencies.
#  * The `libxcb-*`, `libx11-*`, `libxext6`, `libxfixes3`, `libxrender1`,
#    `libxcomposite1`, `libxdamage1`, `libxrandr2`, `libxkbfile1` and `libxtst6`
#    packages are what Qt's XCB platform plugin links against on X11.
#  * The `libwayland-*` packages are what Qt's Wayland platform plugin links
#    against on Wayland.
#  * `wl-clipboard` provides `wl-copy`/`wl-paste` (Wayland clipboard). It is
#    harmless on X11, where BriizFlow uses Qt's clipboard directly (no `xclip` needed).
echo "==> Installing system packages (this may ask for your password) ..."
sudo apt-get update
sudo apt-get install -y \
  python3 python3-venv python3-pip \
  curl ca-certificates \
  libportaudio2 libgomp1 \
  libegl1 libgl1 libfontconfig1 libfreetype6 libdbus-1-3 libglib2.0-0 libssl3 \
  libxkbcommon0 libxkbcommon-x11-0 \
  libx11-6 libx11-xcb1 libxcb1 libxcb-cursor0 \
  libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 libxcb-render0 \
  libxcb-render-util0 libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-util1 \
  libxcb-xfixes0 libxcb-xkb1 \
  libxext6 libxfixes3 libxrender1 libxcomposite1 libxdamage1 libxrandr2 libxkbfile1 libxtst6 \
  libwayland-client0 libwayland-cursor0 libwayland-egl1 \
  wl-clipboard

# Notes:
#  * Wayland *paste* also needs a key-injection tool (`ydotool` or `wtype`).
#    They are NOT installed here on purpose: ydotool needs the `ydotoold` daemon
#    and `input` group membership, and wtype only works on wlroots compositors.
#    See README → "Wayland" and the app's message if you hit that case.

# ---- 2. Virtualenv ------------------------------------------------------------
echo "==> Creating virtualenv (.venv) ..."
if [ ! -d ".venv" ]; then
  "$PY" -m venv .venv
else
  echo "    .venv already exists — reusing it."
fi
.venv/bin/python -m pip install --upgrade pip
# Editable install pulls the runtime dependencies from pyproject.toml and
# creates the `briizflow` command in .venv/bin — the launcher (./briizflow) and
# docs assume it exists.
.venv/bin/pip install -e .

# ---- 3. Bundled whisper.cpp server ----------------------------------------------
# BriizFlow needs the prebuilt whisper.cpp server at bin/whisper.cpp/. If it is not
# already there, download the pinned release and verify its SHA256 checksum
# before installing. A `.briizflow-version` marker inside the folder records which
# version was installed, so an existing install is never redownloaded.
echo ""
WHISPER_VER="1.9.2"
WHISPER_TARBALL="whisper-bin-ubuntu-x64.tar.gz"
# Pinned checksum for whisper-bin-ubuntu-x64.tar.gz from the v1.9.2 release.
WHISPER_SHA256="46811a3ecf584307480a220b9ef5ff81b7b22dc41577cbc274ce3afc61f753b1"
WHISPER_URL="https://github.com/ggml-org/whisper.cpp/releases/download/v${WHISPER_VER}/${WHISPER_TARBALL}"

if [ -x "bin/whisper.cpp/whisper-server" ] || [ -x "bin/whisper-server" ]; then
  if [ -f "bin/whisper.cpp/.briizflow-version" ] && \
     [ "$(cat bin/whisper.cpp/.briizflow-version)" = "$WHISPER_VER" ]; then
    echo "==> Whisper.cpp v$WHISPER_VER already installed — good to go."
  else
    echo "==> Found an existing whisper.cpp server — leaving it as-is."
  fi
else
  echo "==> Downloading whisper.cpp v$WHISPER_VER (pinned release) ..."
  tmpdir="$(mktemp -d)"
  trap 'rm -rf "$tmpdir"' EXIT
  curl -fL --retry 3 -o "$tmpdir/$WHISPER_TARBALL" "$WHISPER_URL"
  echo "    verifying SHA256 checksum ..."
  echo "$WHISPER_SHA256  $tmpdir/$WHISPER_TARBALL" | sha256sum -c - >/dev/null || {
    echo "error: checksum mismatch for $WHISPER_TARBALL — the download is" >&2
    echo "corrupted or tampered with. Refusing to install it." >&2
    exit 1
  }
  tar -xzf "$tmpdir/$WHISPER_TARBALL" -C "$tmpdir"
  mkdir -p bin
  rm -rf bin/whisper.cpp
  mv "$tmpdir/whisper-bin-ubuntu-x64" bin/whisper.cpp
  chmod +x bin/whisper.cpp/whisper-server
  echo "$WHISPER_VER" > bin/whisper.cpp/.briizflow-version
  echo "==> Installed whisper.cpp v$WHISPER_VER at bin/whisper.cpp."
fi

echo ""
echo "Done."
echo "Next steps:"
echo "  1. Run ./briizflow — on first launch the Models page opens so you can"
echo "     download a Whisper model straight from Hugging Face."
