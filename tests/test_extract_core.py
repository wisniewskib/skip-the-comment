import json
import sys

import pytest

import extract as ex


@pytest.mark.parametrize("url,kind,code", [
    ("https://www.instagram.com/reel/ABC123/?igsh=xyz", "reel", "ABC123"),
    ("instagram.com/p/XyZ_9-/", "post", "XyZ_9-"),
    ("https://www.instagram.com/some.user/reel/DEF456/", "reel", "DEF456"),
    ("https://instagram.com/reels/GHI789", "reel", "GHI789"),
    ("https://www.instagram.com/tv/TV1/", "reel", "TV1"),
    ("https://m.instagram.com/p/MOB1/", "post", "MOB1"),
])
def test_parse_url_variants(url, kind, code):
    k, c, canonical = ex.parse_url(url)
    assert (k, c) == (kind, code)
    assert canonical == f"https://www.instagram.com/{'p' if kind == 'post' else 'reel'}/{code}/"


def test_share_links_are_kept_as_is():
    k, c, canonical = ex.parse_url("https://www.instagram.com/share/reel/BAbc123xyz/")
    assert k == "reel"
    assert canonical == "https://www.instagram.com/share/reel/BAbc123xyz/"


@pytest.mark.parametrize("url", ["https://youtube.com/shorts/abc", "https://www.instagram.com/someuser/", "hello"])
def test_parse_url_rejects_non_posts(url):
    with pytest.raises(ex.UnsupportedURL):
        ex.parse_url(url)


@pytest.mark.parametrize("text,code", [
    ("ERROR: [Instagram] X: Requested content is not available, rate-limit reached or login required", "blocked"),
    ("HTTP Error 429: Too Many Requests", "blocked"),
    ("This account is private", "private"),
    ("ERROR: Unable to download webpage: HTTP Error 404: Not Found", "not_found"),
    ("urlopen error [Errno -3] Temporary failure in name resolution", "network"),
    ("Tunnel connection failed: 403 Forbidden", "network"),
    ("something odd", "unknown"),
    ("", "unknown"),
    ("ERROR: [Instagram] DQx: Instagram sent an empty media response. Check if this post is accessible", "blocked"),
    ("[instagram][error] HTTP redirect to login page (https://www.instagram.com/accounts/login/)", "blocked"),
    ("ERROR: [Instagram] DQx: Restricted Video: You must be 18 years old. Use --cookies-from-browser", "blocked"),
    ("ERROR: [Instagram] DQx: This content is only available for registered users who follow this account",
     "blocked"),
    ("ERROR: [Instagram] 3741234044291: Unable to extract data; please report this issue", "unknown"),
    ("ERROR: [Instagram] 3740429123412: something odd", "unknown"),
    ("ERROR: Failed to decrypt with DPAPI. See https://github.com/yt-dlp/yt-dlp/issues/10927", "cookies_unreadable"),
    ("WARNING: failed to decrypt cookie (AES-GCM) because the MAC check failed\nERROR: login required",
     "cookies_unreadable"),
    ("FileNotFoundError: could not find chrome cookies database in \"/home/u/.config/google-chrome\"",
     "cookies_unreadable"),
    ("ERROR: Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271",
     "cookies_unreadable"),
    ("WARNING: [Instagram] DQx: Requested format is not available\nERROR: rate-limit reached", "blocked"),
    ("WARNING: [Instagram] DQx: Requested format is not available", "unknown"),
])
def test_classify_error(text, code):
    assert ex.classify_error(text) == code


def test_ytdlp_cmd_cookies_only_when_consented(tmp_path):
    cmd = ex.ytdlp_cmd("U", tmp_path, "none", "/bin/ffmpeg")
    assert cmd[:3] == [sys.executable, "-m", "yt_dlp"]
    assert "--ignore-no-formats-error" in cmd and "--no-warnings" not in cmd
    assert "--write-thumbnail" not in cmd
    assert "--cookies-from-browser" not in cmd
    assert "--write-comments" in cmd and "--write-info-json" in cmd
    assert cmd[-1] == "U"
    cmd = ex.ytdlp_cmd("U", tmp_path, "firefox", "/bin/ffmpeg", skip_download=True)
    assert cmd[cmd.index("--cookies-from-browser") + 1] == "firefox"
    assert "--skip-download" in cmd


def test_gallery_cmd(tmp_path):
    cmd = ex.gallery_cmd("U", tmp_path, "none")
    assert cmd[:3] == [sys.executable, "-m", "gallery_dl"]
    assert "--write-metadata" in cmd and "--cookies-from-browser" not in cmd
    assert cmd[cmd.index("-f") + 1] == "{num:>02}.{extension}"
    assert ex.gallery_cmd("U", tmp_path, "chrome")[-3:] == ["--cookies-from-browser", "chrome", "U"]


def test_media_files_sorted_and_filtered(tmp_path):
    for n in ["2.jpg", "1.mp4", "1.mp4.json", "00001.info.json", "3.webp", "notes.txt"]:
        (tmp_path / n).write_text("x")
    assert [p.name for p in ex.media_files(tmp_path)] == ["1.mp4", "2.jpg", "3.webp"]


def test_media_files_skips_ytdlp_intermediate_formats_and_video_covers(tmp_path):
    for n in ["00001.mp4", "00001.f1234.mp4", "00001.fdash-9876v.mp4", "00001.jpg",  # cover of video 1
              "00002.jpg", "00003.NA.jpg"]:
        (tmp_path / n).write_text("x")
    assert [p.name for p in ex.media_files(tmp_path)] == ["00001.mp4", "00002.jpg", "00003.NA.jpg"]


def test_ytdlp_thumbnail_mode_flags(tmp_path):
    cmd = ex.ytdlp_cmd("U", tmp_path, "none", "/bin/ffmpeg", thumbnails=True)
    assert "--write-thumbnail" in cmd and cmd[cmd.index("--convert-thumbnails") + 1] == "jpg"
    assert "--ignore-no-formats-error" in cmd and "--skip-download" not in cmd


class _R:
    def __init__(self, stderr="", returncode=0):
        self.stderr, self.returncode = stderr, returncode


def test_post_falls_back_to_ytdlp_thumbnails_when_gallery_dl_needs_login(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        if "yt_dlp" in cmd:  # logged-out yt-dlp exposes image slides as thumbnails
            (tmp_path / "00001.jpg").write_text("x")
            (tmp_path / "00001.info.json").write_text("{}")
            return _R("WARNING: [Instagram] DQx: There is no video in this post")
        return _R("[instagram][error] HTTP redirect to login page (https://www.instagram.com/accounts/login/)")

    monkeypatch.setattr(ex, "run", fake_run)
    err = ex.download_once("post", "U", tmp_path, "none", "/bin/ffmpeg")
    assert [c[2] for c in calls] == ["gallery_dl", "yt_dlp"]
    yt = calls[1]
    assert "--write-thumbnail" in yt and "--ignore-no-formats-error" in yt and "--skip-download" not in yt
    assert "redirect to login" in err
    assert [p.name for p in ex.media_files(tmp_path)] == ["00001.jpg"]


def test_post_with_gallery_dl_media_fetches_only_metadata_with_ytdlp(tmp_path, monkeypatch):
    calls = []

    def fake_run(cmd):
        calls.append(cmd)
        if "gallery_dl" in cmd:
            (tmp_path / "01.jpg").write_text("x")
        return _R()

    monkeypatch.setattr(ex, "run", fake_run)
    ex.download_once("post", "U", tmp_path, "none", "/bin/ffmpeg")
    assert [c[2] for c in calls] == ["gallery_dl", "yt_dlp"]
    assert "--skip-download" in calls[1] and "--ignore-no-formats-error" in calls[1]
    assert "--write-thumbnail" not in calls[1]


def test_emit_prints_ascii_but_writes_utf8_file(tmp_path, capsys):
    ex.emit({"caption": "Plan 🔥 żółw"}, tmp_path)
    printed = capsys.readouterr().out
    assert printed.isascii() and json.loads(printed)["caption"] == "Plan 🔥 żółw"
    assert "🔥 żółw" in (tmp_path / "manifest.json").read_text(encoding="utf-8")


def test_ensure_venv_reexecs_once_with_child_marker(monkeypatch, tmp_path):
    py = ex.stc_setup.venv_python()
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("")
    monkeypatch.delenv("SKIP_THE_COMMENT_CHILD", raising=False)
    seen = {}

    class R:
        returncode = 0

    def fake_run(cmd, env=None, **k):
        seen["env"] = env
        return R()

    monkeypatch.setattr(ex.subprocess, "run", fake_run)
    with pytest.raises(SystemExit):
        ex.ensure_venv()
    assert seen["env"]["SKIP_THE_COMMENT_CHILD"] == "1"


def test_ensure_venv_child_never_reexecs(monkeypatch):
    py = ex.stc_setup.venv_python()
    py.parent.mkdir(parents=True, exist_ok=True)
    py.write_text("")
    monkeypatch.setenv("SKIP_THE_COMMENT_CHILD", "1")
    monkeypatch.setattr(ex.subprocess, "run", lambda *a, **k: pytest.fail("re-exec loop"))
    ex.ensure_venv()  # prefix still differs, but we are the child: run in-process


def test_read_metadata_dedupes_id_less_comments_by_author_text_time(tmp_path):
    info = {"comments": [{"id": None, "author": "a", "text": "PLAN", "timestamp": 1},
                         {"id": None, "author": "b", "text": "PLAN", "timestamp": 2}]}
    (tmp_path / "00001.info.json").write_text(json.dumps(info))
    (tmp_path / "00002.info.json").write_text(json.dumps(info))
    m = ex.read_metadata(tmp_path)
    assert [(c["author"], c["timestamp"]) for c in m["comments"]] == [("a", 1), ("b", 2)]


def test_default_out_dir_is_per_user(monkeypatch):
    monkeypatch.setattr(ex.getpass, "getuser", lambda: "ola")
    assert ex.default_out("ABC").parent.name == "skip-the-comment-ola"
    assert ex.default_out("ABC").name == "ABC"

    def boom():
        raise OSError("no user")

    monkeypatch.setattr(ex.getpass, "getuser", boom)
    assert ex.default_out("ABC").parent.name == "skip-the-comment-user"


def test_out_dir_with_foreign_files_is_not_deleted(tmp_path, capsys):
    out = tmp_path / "my-project"
    out.mkdir()
    (out / "important.txt").write_text("keep me")
    assert ex.main(["https://www.instagram.com/reel/ABC/", "--out", str(out)]) == 2
    assert '"out_dir_not_empty"' in capsys.readouterr().out
    assert (out / "important.txt").exists()


def test_read_metadata_from_ytdlp_dedupes_comments(tmp_path):
    info = {"description": "Opis", "channel": "coach", "uploader": "Coach PL", "duration": 42.0,
            "comments": [{"id": "1", "author": "a", "text": "PLAN"}, {"id": "2", "author": "b", "text": "wow"}]}
    (tmp_path / "00001.info.json").write_text(json.dumps(info))
    (tmp_path / "00002.info.json").write_text(json.dumps(info))  # carousel: same comments twice
    m = ex.read_metadata(tmp_path)
    assert (m["caption"], m["author"], m["duration"]) == ("Opis", "coach", 42.0)
    assert [c["id"] for c in m["comments"]] == ["1", "2"]


def test_read_metadata_falls_back_to_gallery_dl(tmp_path):
    (tmp_path / "slide1.jpg").write_text("x")
    (tmp_path / "slide1.jpg.json").write_text(json.dumps({"description": "Plan treningowy", "username": "fitcoach"}))
    m = ex.read_metadata(tmp_path)
    assert (m["caption"], m["author"], m["comments"]) == ("Plan treningowy", "fitcoach", None)
