#!/usr/bin/env python3
"""skip-the-comment setup: checks dependencies, installs them into a private venv (only when asked), stores config.

    python3 setup.py check                                 JSON: what is missing (name, size, purpose), config
    python3 setup.py install                               venv + pip install + one-time whisper model download
    python3 setup.py config --cookies none|chrome|firefox  store the cookie choice

`check` never installs anything. Claude runs `install` only after the user said yes in chat.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

MODEL = "small"
PACKAGES = [
    # (name shown to the user, pip spec, import names that must all be present, approx size, purpose)
    # curl_cffi: yt-dlp only tries Instagram's logged-out API when it can impersonate a browser
    ("yt-dlp", "yt-dlp[default,curl-cffi]", ("yt_dlp", "curl_cffi"), "~25 MB",
     "downloads the reel video, caption and comments"),
    ("gallery-dl", "gallery-dl", ("gallery_dl",), "~1 MB", "downloads every slide of a carousel post"),
    ("faster-whisper", "faster-whisper", ("faster_whisper",), "~500 MB", "turns speech into text, locally"),
]
FFMPEG_PKG = ("imageio-ffmpeg", "imageio-ffmpeg", ("imageio_ffmpeg",), "~30 MB",
              "bundled ffmpeg for cutting frames (no system install, no sudo)")
MIN_PYTHON = (3, 10)
MODEL_INFO = {"name": f"whisper model '{MODEL}'", "size": "~470 MB", "purpose": "speech recognition model, downloaded once"}
COOKIE_CHOICES = ("none", "chrome", "firefox")
_UNSET = object()


def config_dir():
    if os.environ.get("SKIP_THE_COMMENT_CONFIG_DIR"):
        return Path(os.environ["SKIP_THE_COMMENT_CONFIG_DIR"])
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home()))) / "skip-the-comment"
    return Path.home() / ".config" / "skip-the-comment"


def data_dir():
    if os.environ.get("SKIP_THE_COMMENT_DATA_DIR"):
        return Path(os.environ["SKIP_THE_COMMENT_DATA_DIR"])
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "skip-the-comment"
    return Path.home() / ".local" / "share" / "skip-the-comment"


def models_dir():
    if os.environ.get("SKIP_THE_COMMENT_MODEL_DIR"):
        return Path(os.environ["SKIP_THE_COMMENT_MODEL_DIR"])
    return data_dir() / "models"


def venv_dir():
    return data_dir() / "venv"


def venv_python():
    return venv_dir() / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def load_config():
    """The saved config, or None if there is none or it is unreadable (then setup asks again)."""
    p = config_dir() / "config.json"
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(cfg, dict) or cfg.get("cookies") not in COOKIE_CHOICES:
        return None
    return cfg


def save_config(cookies):
    if cookies not in COOKIE_CHOICES:
        raise ValueError(f"cookies must be one of {COOKIE_CHOICES}")
    config_dir().mkdir(parents=True, exist_ok=True)
    cfg = {"cookies": cookies}
    (config_dir() / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return cfg


def _model_marker():
    return data_dir() / f"model-{MODEL}.ok"


def installed_modules(modules):
    """{import name: bool} as seen by the private venv's python."""
    py = venv_python()
    if not py.exists():
        return {m: False for m in modules}
    code = "import importlib.util,json,sys; print(json.dumps({m: importlib.util.find_spec(m) is not None for m in sys.argv[1:]}))"
    r = subprocess.run([str(py), "-c", code, *modules], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else {m: False for m in modules}


def required_packages(system_ffmpeg):
    return PACKAGES + ([] if system_ffmpeg else [FFMPEG_PKG])


def pip_specs(system_ffmpeg):
    return [p[1] for p in required_packages(system_ffmpeg)]


def check(installed=None, system_ffmpeg=None, config=_UNSET, python_version=None, has_model=None):
    if system_ffmpeg is None:
        system_ffmpeg = shutil.which("ffmpeg") is not None
    pkgs = required_packages(system_ffmpeg)
    if installed is None:
        installed = installed_modules([m for p in pkgs for m in p[2]])
    if config is _UNSET:
        config = load_config()
    if python_version is None:
        python_version = sys.version_info[:2]
    if has_model is None:
        has_model = _model_marker().exists()
    missing = [{"name": n, "size": s, "purpose": why} for n, _, mods, s, why in pkgs
               if not all(installed.get(m) for m in mods)]
    if not has_model:
        missing.append(dict(MODEL_INFO))
    python_ok = tuple(python_version) >= MIN_PYTHON
    return {
        "ready": python_ok and not missing and config is not None,
        "python_ok": python_ok,
        "python_version": ".".join(str(v) for v in python_version),
        "missing": missing,
        "config": config,
        "system_ffmpeg": system_ffmpeg,
        "venv": str(venv_dir()),
    }


def fail(code, detail, hint=""):
    print(json.dumps({"status": "error", "error_code": code, "detail": detail, "hint": hint}, indent=2))
    return 1


def _venv_has_pip():
    r = subprocess.run([str(venv_python()), "-m", "pip", "--version"], capture_output=True, text=True)
    return r.returncode == 0


def install(builder=None):
    status = check()
    if not status["python_ok"]:
        hint = "brew install python  (or the installer from https://www.python.org/downloads/)" \
            if sys.platform == "darwin" else ""
        return fail("python_too_old", f"Python 3.10+ required, found {status['python_version']}", hint)
    if venv_python().exists() and not _venv_has_pip():  # left over from a failed install
        shutil.rmtree(venv_dir(), ignore_errors=True)
    if not venv_python().exists():
        print("creating a private Python environment ...", file=sys.stderr, flush=True)
        try:
            (builder or venv.EnvBuilder(with_pip=True, clear=True)).create(str(venv_dir()))
        except Exception as e:
            shutil.rmtree(venv_dir(), ignore_errors=True)  # a half-made venv would look installed next time
            hint = "sudo apt install python3-venv" if shutil.which("apt") else ""
            return fail("venv_unavailable", str(e), hint)
    pkgs = pip_specs(status["system_ffmpeg"])
    print("installing: " + ", ".join(p[0] for p in required_packages(status["system_ffmpeg"])) + " ...",
          file=sys.stderr, flush=True)
    # faster-whisper 1.2.x passes `metadata_errors` to av.open, an argument removed in av 17+, so cap av
    r = subprocess.run([str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check", "-q", "-U",
                        *pkgs, "av<17"])
    if r.returncode != 0:
        return fail("pip_failed", "pip install failed, see the output above")
    if not _model_marker().exists():
        print(f"downloading the whisper model '{MODEL}' (~470 MB, one time) ...", file=sys.stderr, flush=True)
        code = (f"from faster_whisper import WhisperModel; "
                f"WhisperModel('{MODEL}', device='cpu', compute_type='int8', download_root={str(models_dir())!r})")
        if subprocess.run([str(venv_python()), "-c", code]).returncode != 0:
            return fail("model_download_failed", "could not download the speech model")
        _model_marker().write_text("ok", encoding="utf-8")
    print(json.dumps({"status": "ok", **check()}, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("install")
    c = sub.add_parser("config")
    c.add_argument("--cookies", choices=COOKIE_CHOICES, required=True)
    a = ap.parse_args(argv)
    if a.cmd == "check":
        print(json.dumps(check(), indent=2))
        return 0
    if a.cmd == "install":
        return install()
    print(json.dumps({"status": "ok", "config": save_config(a.cookies)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
