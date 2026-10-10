#!/usr/bin/env python3
"""skip-the-comment extractor: everything a public Instagram reel/post contains, ready for the agent to read.

    python3 extract.py <instagram_url> [--out DIR]

Re-runs itself inside the private venv made by setup.py. Writes DIR/manifest.json (also printed): caption, author,
every media file, per video a transcript + frame contact sheets, filtered comments.
Exit codes: 0 ok · 2 unsupported link or unusable --out · 3 download failed · 4 not set up (run setup.py).
"""
import argparse
import getpass
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import setup as stc_setup  # noqa: E402
from comments import filter_comments  # noqa: E402

VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv", ".m4v"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}
URL_RE = re.compile(
    r"^(?:https?://)?(?:www\.|m\.)?(?:instagram\.com|instagr\.am)/(?:share/)?(?:[A-Za-z0-9_.]+/)?(reel|reels|p|tv)/([A-Za-z0-9_-]+)",
    re.I,
)
NETWORK_HINTS = ("name or service not known", "temporary failure in name resolution", "getaddrinfo",
                 "network is unreachable", "connection refused", "proxyerror", "tunnel connection failed",
                 "nodename nor servname")
BLOCKED_HINTS = ("rate-limit", "rate limit", "login required", "checkpoint", "please wait a few minutes",
                 "empty media response", "redirect to login", "--cookies", "registered users", "restricted video")
NOT_FOUND_HINTS = ("not found", "does not exist", "unavailable", "not available")
HTTP_429_RE = re.compile(r"\b(?:http error )?429\b")  # word-bounded: 19-digit media ids contain "429"/"404"
HTTP_404_RE = re.compile(r"\b(?:http error )?404\b")
WARNING_LINE_RE = re.compile(r"^.*(?:warning:|\]\[warning\]).*$", re.I | re.M)
INTERMEDIATE_RE = re.compile(r"\.f[\w-]+\.[^.]+$")  # yt-dlp per-format parts before merging: 00001.f123.mp4


class UnsupportedURL(ValueError):
    pass


def parse_url(url):
    url = url.strip()
    m = URL_RE.match(url)
    if not m:
        raise UnsupportedURL(url)
    kind = "post" if m.group(1).lower() == "p" else "reel"
    code = m.group(2)
    if "/share/" in url.lower():  # share ids are not shortcodes; let the downloader follow the redirect
        return kind, code, url if url.lower().startswith("http") else "https://" + url
    return kind, code, f"https://www.instagram.com/{'p' if kind == 'post' else 'reel'}/{code}/"


def cookies_unreadable(t):
    return ("failed to decrypt" in t or "could not copy chrome cookie database" in t
            or ("could not find" in t and "cookies" in t))


def classify_error(text):
    full = (text or "").lower()
    if any(h in full for h in NETWORK_HINTS):
        return "network"
    if cookies_unreadable(full):  # often only a warning, but it explains the failure that follows
        return "cookies_unreadable"
    t = WARNING_LINE_RE.sub("", full)  # warnings ("Requested format is not available") are not the failure
    if "private" in t:
        return "private"
    if any(h in t for h in BLOCKED_HINTS) or HTTP_429_RE.search(t):
        return "blocked"
    if any(h in t for h in NOT_FOUND_HINTS) or HTTP_404_RE.search(t):
        return "not_found"
    return "unknown"


def ytdlp_cmd(url, media_dir, cookies, ffmpeg, skip_download=False, thumbnails=False):
    # --ignore-no-formats-error: image posts/slides have no video formats; still write info.json (caption, comments)
    cmd = [sys.executable, "-m", "yt_dlp", "--ignore-no-formats-error", "--write-info-json", "--write-comments",
           "--no-write-playlist-metafiles", "--ffmpeg-location", str(ffmpeg),
           "-o", str(Path(media_dir) / "%(autonumber)s.%(ext)s")]
    if skip_download:
        cmd.append("--skip-download")
    if thumbnails:  # logged out, yt-dlp exposes image slides only as thumbnails
        cmd += ["--write-thumbnail", "--convert-thumbnails", "jpg"]
    if cookies != "none":
        cmd += ["--cookies-from-browser", cookies]
    return cmd + [url]


def gallery_cmd(url, media_dir, cookies):
    cmd = [sys.executable, "-m", "gallery_dl", "--write-metadata", "-D", str(media_dir),
           "-f", "{num:>02}.{extension}"]  # 01.jpg, 02.mp4 ... sorts in slide order
    if cookies != "none":
        cmd += ["--cookies-from-browser", cookies]
    return cmd + [url]


def media_files(media_dir):
    files = [p for p in Path(media_dir).iterdir()
             if p.suffix.lower() in VIDEO_EXT | IMAGE_EXT and not INTERMEDIATE_RE.search(p.name)]
    video_stems = {p.stem for p in files if p.suffix.lower() in VIDEO_EXT}
    # yt-dlp thumbnail mode also writes a cover image next to each video (00001.mp4 + 00001.jpg): skip it
    return sorted(p for p in files if p.suffix.lower() in VIDEO_EXT or p.stem not in video_stems)


def read_metadata(media_dir):
    meta = {"caption": "", "author": None, "duration": None, "comments": None}
    seen = set()
    for p in sorted(Path(media_dir).glob("*.info.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        meta["caption"] = meta["caption"] or d.get("description") or ""
        meta["author"] = meta["author"] or d.get("channel") or d.get("uploader_id") or d.get("uploader")
        meta["duration"] = meta["duration"] or d.get("duration")
        if d.get("comments") is not None:
            meta["comments"] = meta["comments"] or []
            for c in d["comments"]:
                key = c.get("id") if c.get("id") is not None else (c.get("author"), c.get("text"), c.get("timestamp"))
                if key in seen:  # carousels repeat the same comments in every slide's info.json
                    continue
                seen.add(key)
                meta["comments"].append({"id": c.get("id"), "author": c.get("author"), "text": c.get("text"),
                                         "timestamp": c.get("timestamp"),
                                         "author_is_uploader": c.get("author_is_uploader")})
    for p in sorted(Path(media_dir).glob("*.json")):
        if p.name.endswith(".info.json"):
            continue
        d = json.loads(p.read_text(encoding="utf-8"))  # gallery-dl per-file metadata
        meta["caption"] = meta["caption"] or d.get("description") or ""
        meta["author"] = meta["author"] or d.get("username")
    return meta


def run(cmd):
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace")


def find_ffmpeg():
    return shutil.which("ffmpeg") or __import__("imageio_ffmpeg").get_ffmpeg_exe()


_MODEL = None


def transcribe(path, out_txt):
    global _MODEL
    try:
        import av
        with av.open(str(path)) as container:
            has_audio = bool(container.streams.audio)
        if not has_audio:
            Path(out_txt).write_text("# language: None\n(no speech detected)\n", encoding="utf-8")
            return {"language": None, "has_speech": False}
        from faster_whisper import WhisperModel
        if _MODEL is None:
            _MODEL = WhisperModel(stc_setup.MODEL, device="cpu", compute_type="int8",
                                  download_root=str(stc_setup.models_dir()))
        segments, info = _MODEL.transcribe(str(path), vad_filter=True)
        lines = [f"[{int(s.start) // 60:02d}:{int(s.start) % 60:02d}] {s.text.strip()}" for s in segments if s.text.strip()]
    except Exception as e:  # a real failure (corrupt file, model error) must not look like silence
        err = f"{type(e).__name__}: {e}"
        Path(out_txt).write_text(f"# error: {err}\n(transcription failed)\n", encoding="utf-8")
        return {"language": None, "has_speech": False, "transcribe_error": err}
    lang = info.language if lines else None
    body = "\n".join(lines) if lines else "(no speech detected)"
    Path(out_txt).write_text(f"# language: {lang}\n{body}\n", encoding="utf-8")
    return {"language": lang, "has_speech": bool(lines)}


def extract_frames(video, vdir, ffmpeg, errors=None):
    """[(second, path)]; if ffmpeg produced nothing, a short stderr tail is appended to `errors`."""
    fdir = Path(vdir) / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    # 1 frame/s, near-identical frames dropped; with fps=1 the pts in the file name is the second
    base = [ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-i", video, "-vf", "fps=1,mpdecimate,scale=540:-2"]
    r = run(base + ["-fps_mode", "passthrough", "-frame_pts", "1", fdir / "%d.jpg"])
    if r.returncode != 0:  # ffmpeg < 5.1 (e.g. Ubuntu 22.04) has no -fps_mode
        for p in fdir.glob("*.jpg"):
            p.unlink()
        r = run(base + ["-vsync", "passthrough", "-frame_pts", "1", fdir / "%d.jpg"])
    frames = sorted((int(p.stem), p) for p in fdir.glob("*.jpg") if p.stem.isdigit())
    if not frames and errors is not None:
        errors.append((r.stderr or f"ffmpeg exit code {r.returncode}").strip()[-300:])
    return frames


def make_sheets(frames, vdir, ffmpeg, max_frames=45):
    if len(frames) > max_frames:
        idx = sorted({round(i * (len(frames) - 1) / (max_frames - 1)) for i in range(max_frames)})
        frames = [frames[i] for i in idx]
    sheets = []
    for n, start in enumerate(range(0, len(frames), 9), 1):
        chunk = frames[start:start + 9]
        padded = chunk + [chunk[-1]] * (9 - len(chunk))  # tile needs 9 inputs; padding repeats the last frame
        lst = Path(vdir) / f"sheet_{n}.txt"
        lst.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for _, p in padded), encoding="utf-8")
        out = Path(vdir) / f"sheet_{n}.jpg"
        run([ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
             "-vf", "tile=3x3:padding=6", "-frames:v", "1", out])
        if out.exists():
            sheets.append({"path": str(out), "seconds": [s for s, _ in chunk]})
    return sheets


def download_once(kind, url, media_dir, cookies, ffmpeg):
    errs = []
    if kind == "reel":
        errs.append(run(ytdlp_cmd(url, media_dir, cookies, ffmpeg)).stderr)
    else:
        errs.append(run(gallery_cmd(url, media_dir, cookies)).stderr)
        if media_files(media_dir):  # slides are here; yt-dlp only adds caption + comments
            errs.append(run(ytdlp_cmd(url, media_dir, cookies, ffmpeg, skip_download=True)).stderr)
        else:  # gallery-dl needs a login for posts: let yt-dlp fetch videos + image slides (as thumbnails)
            errs.append(run(ytdlp_cmd(url, media_dir, cookies, ffmpeg, thumbnails=True)).stderr)
    return "\n".join(e for e in errs if e)


def download(kind, url, media_dir, cookies, ffmpeg, attempts=2, wait=3):
    err = ""
    for i in range(attempts):
        err = download_once(kind, url, media_dir, cookies, ffmpeg)
        if media_files(media_dir):
            return ""
        if classify_error(err) in ("private", "not_found", "network"):
            break
        if i + 1 < attempts:
            time.sleep(wait)
    return err or "no media downloaded"


def emit(manifest, out_dir=None):
    if out_dir is not None:
        text = json.dumps(manifest, ensure_ascii=False, indent=2)
        (Path(out_dir) / "manifest.json").write_text(text, encoding="utf-8")
    # stdout stays ASCII: a Windows cp125x console/pipe cannot encode emoji from captions
    print(json.dumps(manifest, ensure_ascii=True, indent=2))


def ensure_venv():
    if Path(sys.prefix).resolve() == stc_setup.venv_dir().resolve():
        return
    if os.environ.get("SKIP_THE_COMMENT_CHILD") == "1":  # already re-executed once: never loop, run here
        return
    py = stc_setup.venv_python()
    if not py.exists():
        emit({"status": "error", "error_code": "not_set_up", "detail": "run setup.py check, then install"})
        sys.exit(4)
    env = {**os.environ, "SKIP_THE_COMMENT_CHILD": "1"}
    sys.exit(subprocess.run([str(py), str(Path(__file__).resolve()), *sys.argv[1:]], env=env).returncode)


def default_root():
    try:
        user = getpass.getuser()
    except Exception:  # no USER/LOGNAME and no passwd entry
        user = "user"
    return Path(tempfile.gettempdir()) / f"skip-the-comment-{user}"


def default_out(code):
    return default_root() / code


def prepare_out(out):
    """Clear a previous run's output; never delete a folder this script did not make. False if unusable."""
    if not out.exists():
        return True
    if not out.is_dir():
        return False
    under_default = default_root().resolve() in out.resolve().parents
    if (out / "manifest.json").exists() or under_default:
        shutil.rmtree(out)
        return True
    return not any(out.iterdir())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("url")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    try:
        kind, code, url = parse_url(a.url)
    except UnsupportedURL:
        emit({"status": "error", "error_code": "unsupported_url", "detail": a.url})
        return 2
    cookies = (stc_setup.load_config() or {}).get("cookies", "none")
    out = Path(a.out) if a.out else default_out(code)
    if not prepare_out(out):
        emit({"status": "error", "error_code": "out_dir_not_empty", "detail": str(out)})
        return 2
    media_dir = out / "media"
    media_dir.mkdir(parents=True)
    ffmpeg = find_ffmpeg()
    base = {"url": url, "kind": kind, "shortcode": code, "out_dir": str(out), "cookies": cookies}

    err = download(kind, url, media_dir, cookies, ffmpeg)
    if err:
        emit({**base, "status": "error", "error_code": classify_error(err), "detail": err.strip()[-600:]}, out)
        return 3

    meta = read_metadata(media_dir)
    media = []
    for i, p in enumerate(media_files(media_dir), 1):
        item = {"path": str(p), "type": "video" if p.suffix.lower() in VIDEO_EXT else "image"}
        if item["type"] == "video":
            vdir = out / f"video_{i}"
            vdir.mkdir()
            item.update(transcribe(p, vdir / "transcript.txt"))
            item["transcript_path"] = str(vdir / "transcript.txt")
            errors = []
            frames = extract_frames(p, vdir, ffmpeg, errors)
            item["sheets"] = make_sheets(frames, vdir, ffmpeg)
            item["frames"] = [{"second": s, "path": str(fp)} for s, fp in frames]
            if errors:
                item["frames_error"] = errors[0]
        media.append(item)
    comments = {"available": False}
    if meta["comments"]:
        comments = {"available": True, **filter_comments(meta["comments"], meta["author"])}
    emit({**base, "status": "ok", "author": meta["author"], "caption": meta["caption"],
          "duration": meta["duration"], "media": media, "comments": comments}, out)
    return 0


if __name__ == "__main__":
    ensure_venv()
    sys.exit(main())
