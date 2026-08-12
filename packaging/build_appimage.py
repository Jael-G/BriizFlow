"""Build a portable BriizFlow AppImage without touching the project.

Usage::

    python3 packaging/build_appimage.py [--output DIR] [--fresh] [--keep]

The default artifact goes to ``<project>/dist/briizflow-<version>-<arch>.AppImage``
(``dist/`` is gitignored). Use ``--output`` to put it elsewhere.

Requirements
------------
* Python 3.10+ and the project's virtualenv (created by ``./install.sh``)
* ``libportaudio2`` installed (the ``.so`` is bundled into the AppImage)
* the bundled whisper server at ``bin/whisper.cpp/whisper-server``

The AppImage bundles Python, PySide6/Qt, numpy, libportaudio, whisper-server
and the app's assets, so it runs on a clean Ubuntu x86_64 desktop.
"""

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tempfile

APPIMAGETOOL_URL = (
    "https://github.com/AppImage/appimagetool/releases/download/continuous/"
    "appimagetool-x86_64.AppImage"
)


def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_version():
    sys.path.insert(0, project_root())
    from app import __version__

    return __version__


def arch_name():
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        return "x86_64"
    if machine in ("aarch64", "arm64"):
        return "aarch64"
    return machine


def find_libportaudio():
    """Return the path to libportaudio.so.2 on the build machine."""
    try:
        import sounddevice

        for line in sounddevice._ffi.dlopen("libportaudio.so.2") or []:
            pass
    except Exception:
        pass
    # Fall back to a filesystem search.
    candidates = []
    for root in ("/usr/lib/x86_64-linux-gnu", "/usr/lib", "/lib/x86_64-linux-gnu", "/lib"):
        candidates.append(os.path.join(root, "libportaudio.so.2"))
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def ensure_appimagetool(cache_dir):
    tool = os.path.join(cache_dir, "appimagetool-x86_64.AppImage")
    if os.path.exists(tool):
        return tool
    os.makedirs(cache_dir, exist_ok=True)
    print("==> Downloading appimagetool ...")
    subprocess.run(["curl", "-fL", "-o", tool, APPIMAGETOOL_URL], check=True)
    os.chmod(tool, 0o755)
    return tool


def build_venv(cache_dir, fresh):
    venv = os.path.join(cache_dir, "venv")
    if fresh and os.path.isdir(venv):
        shutil.rmtree(venv)
    if not os.path.isdir(venv):
        subprocess.run([sys.executable, "-m", "venv", venv], check=True)
    pip = os.path.join(venv, "bin", "pip")
    subprocess.run([pip, "install", "--upgrade", "pip"], check=True)
    deps = [
        "pyinstaller",
        "PySide6>=6.6",
        "numpy>=1.24",
        "sounddevice>=0.4.6",
        "miniaudio>=1.61",
        "pynput>=1.7.6",
        "python-xlib>=0.33",
        "dbus-next>=0.2.3",
        "secretstorage>=3.3",
    ]
    subprocess.run([pip, "install"] + deps, check=True)
    return os.path.join(venv, "bin", "pyinstaller")


def build(root, output, cache_dir, fresh, keep):
    version = app_version()
    arch = arch_name()
    os.makedirs(output, exist_ok=True)
    artifact = os.path.join(output, "briizflow-%s-%s.AppImage" % (version, arch))

    pyinstaller = build_venv(cache_dir, fresh)
    appimagetool = ensure_appimagetool(cache_dir)

    workdir = tempfile.mkdtemp(prefix="briizflow-appimage-")
    try:
        dist = os.path.join(workdir, "dist")
        spec_dir = os.path.join(workdir, "spec")

        print("==> Bundling with PyInstaller ...")
        subprocess.run(
            [
                pyinstaller,
                "--noconfirm",
                "--clean",
                "--name", "briizflow",
                "--distpath", dist,
                "--workpath", os.path.join(workdir, "build"),
                "--specpath", spec_dir,
                "--add-data", "app/assets:%s" % os.path.join("app", "assets"),
                "--add-data", "app/ui/lucide:%s" % os.path.join("app", "ui", "lucide"),
                "--add-data", "app/ui/theme/dark.qss:%s" % os.path.join("app", "ui", "theme"),
                "--add-data", "THIRD_PARTY_NOTICES.md:.",
                "--collect-all", "PySide6",
                "--hidden-import", "app.transcription.provider",
                os.path.join(root, "app", "main.py"),
            ],
            check=True,
        )

        bundle = os.path.join(dist, "briizflow")
        # Bundle the whisper server and shared libs next to the executable.
        server_src = os.path.join(root, "bin", "whisper.cpp")
        if os.path.isdir(server_src):
            shutil.copytree(server_src, os.path.join(bundle, "bin", "whisper.cpp"))
        port = find_libportaudio()
        if port:
            shutil.copy2(port, os.path.join(bundle, "libportaudio.so.2"))

        print("==> Packaging AppImage ...")
        subprocess.run(
            [appimagetool, bundle, artifact],
            check=True,
        )
        print("==> Wrote %s" % artifact)
        return artifact
    finally:
        if not keep and os.path.isdir(workdir):
            shutil.rmtree(workdir, ignore_errors=True)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build a portable BriizFlow AppImage without touching the project.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--root", default=project_root(),
                        help="BriizFlow project root (default: repo containing this script)")
    parser.add_argument("--output", default=None,
                        help="output directory for the AppImage "
                             "(default: <project>/dist, which is gitignored)")
    parser.add_argument("--cache",
                        default=os.path.join(os.path.expanduser("~"), ".cache", "briizflow-appimage"),
                        help="cache dir for the build venv and appimagetool")
    parser.add_argument("--fresh", action="store_true",
                        help="rebuild the cached venv from scratch")
    parser.add_argument("--keep", action="store_true",
                        help="keep the temporary build directory (debugging)")
    args = parser.parse_args(argv)
    if args.output is None:
        args.output = os.path.join(args.root, "dist")
    return build(args.root, args.output, args.cache, args.fresh, args.keep)


if __name__ == "__main__":
    main()
