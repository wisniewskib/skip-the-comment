import json

import pytest

import setup as stc

ALL = {"yt_dlp": True, "curl_cffi": True, "gallery_dl": True, "faster_whisper": True, "imageio_ffmpeg": True}


def test_isolation_guard_data_and_config_dirs_under_tmp_path(tmp_path):
    """Verify that tests are isolated: data_dir and config_dir must be under tmp_path."""
    data_dir = stc.data_dir()
    config_dir = stc.config_dir()
    assert data_dir.is_relative_to(tmp_path), f"data_dir {data_dir} not under tmp_path {tmp_path}"
    assert config_dir.is_relative_to(tmp_path), f"config_dir {config_dir} not under tmp_path {tmp_path}"


def test_ready_when_everything_present_and_configured():
    s = stc.check(installed=ALL, system_ffmpeg=True, config={"cookies": "none"}, python_version=(3, 12), has_model=True)
    assert s["ready"] is True
    assert s["missing"] == []


def test_missing_lists_names_sizes_purposes_and_needs_bundled_ffmpeg_without_system_one():
    s = stc.check(installed={}, system_ffmpeg=False, config=None, python_version=(3, 12), has_model=False)
    names = [m["name"] for m in s["missing"]]
    assert names == ["yt-dlp", "gallery-dl", "faster-whisper", "imageio-ffmpeg", "whisper model 'small'"]
    assert all(m["size"] and m["purpose"] for m in s["missing"])
    assert s["ready"] is False


def test_system_ffmpeg_means_no_bundled_ffmpeg():
    s = stc.check(installed={}, system_ffmpeg=True, config=None, python_version=(3, 12), has_model=True)
    assert "imageio-ffmpeg" not in [m["name"] for m in s["missing"]]


def test_not_ready_without_config_even_if_installed():
    s = stc.check(installed=ALL, system_ffmpeg=True, config=None, python_version=(3, 12), has_model=True)
    assert s["ready"] is False


def test_old_python_not_ok():
    s = stc.check(installed=ALL, system_ffmpeg=True, config={"cookies": "none"}, python_version=(3, 9), has_model=True)
    assert s["python_ok"] is False and s["ready"] is False
    s = stc.check(installed=ALL, system_ffmpeg=True, config={"cookies": "none"}, python_version=(3, 10), has_model=True)
    assert s["python_ok"] is True


def test_ytdlp_needs_curl_cffi_for_logged_out_instagram():
    s = stc.check(installed={**ALL, "curl_cffi": False}, system_ffmpeg=True, config={"cookies": "none"},
                  python_version=(3, 12), has_model=True)
    assert [m["name"] for m in s["missing"]] == ["yt-dlp"]
    assert s["ready"] is False


def test_install_pip_spec_includes_curl_cffi_extra():
    assert "yt-dlp[default,curl-cffi]" in stc.pip_specs(system_ffmpeg=True)


def test_load_config_ignores_corrupt_or_invalid_file():
    stc.config_dir().mkdir(parents=True)
    (stc.config_dir() / "config.json").write_text("{not json", encoding="utf-8")
    assert stc.load_config() is None
    (stc.config_dir() / "config.json").write_text('{"cookies": "safari"}', encoding="utf-8")
    assert stc.load_config() is None
    (stc.config_dir() / "config.json").write_text('[1, 2]', encoding="utf-8")
    assert stc.load_config() is None


def test_config_roundtrip_and_validation():
    assert stc.load_config() is None
    stc.save_config("firefox")
    assert stc.load_config() == {"cookies": "firefox"}
    with pytest.raises(ValueError):
        stc.save_config("safari")


def test_check_never_creates_the_venv():
    stc.check()
    assert not stc.venv_dir().exists()


def test_install_reports_venv_unavailable(capsys, monkeypatch):
    monkeypatch.setattr(stc.shutil, "which", lambda name: "/usr/bin/apt" if name == "apt" else None)

    class Broken:
        def create(self, path):
            raise RuntimeError("ensurepip is not available")

    rc = stc.install(builder=Broken())
    out = json.loads(capsys.readouterr().out)
    assert rc == 1
    assert out["error_code"] == "venv_unavailable"
    assert out["hint"] == "sudo apt install python3-venv"
    assert not stc.venv_dir().exists()


def test_install_removes_half_made_venv(capsys, monkeypatch):
    monkeypatch.setattr(stc.shutil, "which", lambda name: None)

    class HalfBroken:
        def create(self, path):
            stc.venv_python().parent.mkdir(parents=True, exist_ok=True)
            stc.venv_python().write_text("", encoding="utf-8")  # ensurepip fails after bin/python exists
            raise RuntimeError("ensurepip failed")

    assert stc.install(builder=HalfBroken()) == 1
    assert json.loads(capsys.readouterr().out)["error_code"] == "venv_unavailable"
    assert not stc.venv_dir().exists()


def test_install_recreates_venv_without_working_pip(monkeypatch):
    py = stc.venv_python()
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("", encoding="utf-8")
    (stc.venv_dir() / "stale").write_text("x", encoding="utf-8")
    stc._model_marker().write_text("ok", encoding="utf-8")
    created, calls = [], []

    class Builder:
        def create(self, path):
            created.append(path)
            stc.venv_python().parent.mkdir(parents=True, exist_ok=True)
            stc.venv_python().write_text("", encoding="utf-8")

    class R:
        def __init__(self, rc):
            self.returncode, self.stdout = rc, "{}"

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        is_pip_version = "--version" in cmd
        return R(1 if is_pip_version and not created else 0)

    monkeypatch.setattr(stc.subprocess, "run", fake_run)
    assert stc.install(builder=Builder()) == 0
    assert created and not (stc.venv_dir() / "stale").exists()


def test_install_pins_av_below_17(monkeypatch):
    py = stc.venv_python()
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("", encoding="utf-8")
    stc._model_marker().parent.mkdir(parents=True, exist_ok=True)
    stc._model_marker().write_text("ok", encoding="utf-8")
    calls = []

    class R:
        returncode = 0
        stdout = "{}"

    monkeypatch.setattr(stc.subprocess, "run", lambda cmd, *a, **k: calls.append(cmd) or R())
    stc.install()
    pip = [c for c in calls if "pip" in c and "install" in c]
    assert pip and "av<17" in pip[0] and "yt-dlp[default,curl-cffi]" in pip[0]


def test_python_too_old_names_310_and_macos_install(capsys, monkeypatch):
    monkeypatch.setattr(stc, "check", lambda: {"python_ok": False, "python_version": "3.9"})
    monkeypatch.setattr(stc.sys, "platform", "darwin")
    assert stc.install() == 1
    out = json.loads(capsys.readouterr().out)
    assert out["error_code"] == "python_too_old" and "3.10" in out["detail"]
    assert "brew install python" in out["hint"] and "python.org" in out["hint"]


def test_models_dir_env_and_default(monkeypatch, tmp_path):
    monkeypatch.setenv("SKIP_THE_COMMENT_MODEL_DIR", str(tmp_path / "m"))
    assert stc.models_dir() == tmp_path / "m"
    monkeypatch.delenv("SKIP_THE_COMMENT_MODEL_DIR")
    assert stc.models_dir() == stc.data_dir() / "models"
