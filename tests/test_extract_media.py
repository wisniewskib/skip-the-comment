import json
from pathlib import Path
import shutil
import subprocess

import extract as ex

FFMPEG = shutil.which("ffmpeg") or __import__("imageio_ffmpeg").get_ffmpeg_exe()


def make_video(path, seconds=5, audio=False):
    cmd = [FFMPEG, "-nostdin", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
           f"testsrc=duration={seconds}:size=320x240:rate=10"]
    if audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    cmd += ["-pix_fmt", "yuv420p", str(path)]
    subprocess.run(cmd, check=True)
    return path


def test_video_without_audio_track_has_no_speech(tmp_path):
    v = make_video(tmp_path / "silent.mp4", audio=False)
    out = ex.transcribe(v, tmp_path / "t.txt")
    assert out["has_speech"] is False
    assert "(no speech detected)" in (tmp_path / "t.txt").read_text(encoding="utf-8")


def test_tone_only_audio_has_no_speech(tmp_path):
    v = make_video(tmp_path / "tone.mp4", audio=True)
    out = ex.transcribe(v, tmp_path / "t.txt")
    assert out["has_speech"] is False
    assert "transcribe_error" not in out


def test_frames_and_sheets(tmp_path):
    v = make_video(tmp_path / "v.mp4", seconds=5)
    frames = ex.extract_frames(v, tmp_path, FFMPEG)
    secs = [s for s, _ in frames]
    assert secs == sorted(secs) and len(secs) >= 4 and secs[0] == 0
    sheets = ex.make_sheets(frames, tmp_path, FFMPEG)
    assert len(sheets) == 1
    assert sheets[0]["seconds"] == secs
    assert (tmp_path / "sheet_1.jpg").exists()


def test_make_sheets_samples_long_videos(tmp_path):
    v = make_video(tmp_path / "v.mp4", seconds=60)
    frames = ex.extract_frames(v, tmp_path, FFMPEG)
    sheets = ex.make_sheets(frames, tmp_path, FFMPEG, max_frames=18)
    assert len(sheets) == 2
    assert sum(len(s["seconds"]) for s in sheets) == 18


def test_main_rejects_unsupported_url(capsys):
    assert ex.main(["https://youtube.com/shorts/x"]) == 2
    assert '"unsupported_url"' in capsys.readouterr().out


def test_download_stops_early_on_private(tmp_path, monkeypatch):
    calls = []

    def fake_once(*a):
        calls.append(1)
        return "This account is private"

    monkeypatch.setattr(ex, "download_once", fake_once)
    assert "private" in ex.download("reel", "U", tmp_path, "none", FFMPEG, wait=0)
    assert len(calls) == 1


def test_download_retries_once_on_blocked(tmp_path, monkeypatch):
    calls = []

    def fake_once(*a):
        calls.append(1)
        return "rate-limit reached or login required"

    monkeypatch.setattr(ex, "download_once", fake_once)
    ex.download("reel", "U", tmp_path, "none", FFMPEG, wait=0)
    assert len(calls) == 2


def test_transcribe_reports_model_errors_instead_of_no_speech(tmp_path, monkeypatch):
    class Boom:
        def transcribe(self, *a, **k):
            raise TypeError("boom")

    monkeypatch.setattr(ex, "_MODEL", Boom())
    v = make_video(tmp_path / "tone.mp4", audio=True)
    out = ex.transcribe(v, tmp_path / "t.txt")
    assert out["has_speech"] is False and "TypeError" in out["transcribe_error"]
    assert "transcription failed" in (tmp_path / "t.txt").read_text(encoding="utf-8")


def test_transcribe_survives_corrupt_media(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"this is not a video" * 50)
    out = ex.transcribe(bad, tmp_path / "t.txt")
    assert out["has_speech"] is False and out["transcribe_error"]
    assert "transcription failed" in (tmp_path / "t.txt").read_text(encoding="utf-8")


def test_extract_frames_falls_back_to_vsync_on_old_ffmpeg(tmp_path, monkeypatch):
    calls = []
    real_run = ex.run

    class Fail:
        returncode, stderr = 1, "Unrecognized option 'fps_mode'.\nError splitting the argument list: Option not found"

    def fake_run(cmd):
        calls.append([str(c) for c in cmd])
        return Fail() if "-fps_mode" in calls[-1] else real_run(cmd)

    monkeypatch.setattr(ex, "run", fake_run)
    v = make_video(tmp_path / "v.mp4", seconds=3)
    errors = []
    frames = ex.extract_frames(v, tmp_path, FFMPEG, errors)
    assert len(calls) == 2 and "-vsync" in calls[1] and "-fps_mode" not in calls[1]
    assert frames and errors == []


def test_extract_frames_reports_error_when_ffmpeg_fails(tmp_path, monkeypatch):
    class Fail:
        returncode, stderr = 1, "x" * 1000 + "Invalid data found when processing input"

    monkeypatch.setattr(ex, "run", lambda cmd: Fail())
    errors = []
    assert ex.extract_frames(tmp_path / "v.mp4", tmp_path, FFMPEG, errors) == []
    assert errors and errors[0].endswith("Invalid data found when processing input") and len(errors[0]) <= 300


def test_manifest_lists_single_frames_and_frames_error(tmp_path, monkeypatch, capsys):
    def fake_download(kind, url, media_dir, cookies, ffmpeg):
        make_video(media_dir / "00001.mp4", seconds=3)
        return ""

    monkeypatch.setattr(ex, "download", fake_download)
    monkeypatch.setattr(ex, "transcribe", lambda p, out: {"language": None, "has_speech": False})
    out = tmp_path / "out"
    assert ex.main(["https://www.instagram.com/reel/ABC/", "--out", str(out)]) == 0
    m = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    item = m["media"][0]
    assert [f["second"] for f in item["frames"]][:2] == [0, 1]
    assert all(Path(f["path"]).exists() for f in item["frames"])
    assert "frames_error" not in item
