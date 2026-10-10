"""Comment filter for skip-the-comment.

Drops everything that repeats (the trigger word people were told to comment, the creator's auto-replies),
keeps unique comments, pulls links out of ALL comments (fans often repost the DM link many times).
No predefined keywords: repetition is the only signal.
"""
import re
import unicodedata
from collections import Counter

MENTION_RE = re.compile(r"@[\w.]+")
TLDS = "com|io|so|dev|app|ai|pl|link|me|co|gg|ly|site|page|org|net"
URL_RE = re.compile(
    r"https?://[^\s]+"
    # bare domain: starts a word (after whitespace, an opening bracket or quote) and the label before the TLD has
    # at least 2 characters, so "e.g.com" / "i.e.com" are not links
    rf"|(?<![^\s(\[\"'\u00ab\u201e\u201c])(?:www\.)?(?:[a-z0-9-]+\.)*[a-z0-9-]{{2,}}\.(?:{TLDS})\b(?:/[^\s]*)?",
    re.I,
)
TRAILING = ".,!?);:\"'\u00bb]\u2026\u201d"


def normalize(text):
    text = MENTION_RE.sub(" ", text or "")
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in text)
    return " ".join(text.split())


def _dedupe(comments):
    seen, out = set(), []
    for c in comments:
        key = c.get("id") if c.get("id") is not None else (c.get("author"), c.get("text"), c.get("timestamp"))
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return out


def _links(texts):
    return sorted({m.group(0).rstrip(TRAILING) for t in texts for m in URL_RE.finditer(t or "")} - {""})


def filter_comments(comments, creator=None, max_kept=100):
    comments = _dedupe(comments)
    creator = (creator or "").lstrip("@").lower()
    norm = [normalize(c.get("text")) for c in comments]
    by_creator = [
        bool(c.get("author_is_uploader")) or (bool(creator) and (c.get("author") or "").lstrip("@").lower() == creator)
        for c in comments
    ]
    audience = Counter(n for n, cr in zip(norm, by_creator) if n and not cr)
    replies = Counter(n for n, cr in zip(norm, by_creator) if n and cr)
    repeated = [(t, k) for t, k in audience.most_common() if k >= 2]
    trigger, trigger_count = repeated[0] if repeated else (None, 0)

    kept, removed_repeats, removed_replies = [], 0, 0
    for c, n, cr in zip(comments, norm, by_creator):
        if not n:
            continue
        if cr and replies[n] >= 2:
            removed_replies += 1
            continue
        if not cr and audience[n] >= 2:
            removed_repeats += 1
            continue
        kept.append({"author": c.get("author"), "text": c.get("text"), "by_creator": cr})

    kept.sort(key=lambda k: 0 if URL_RE.search(k["text"] or "") else 1)  # stable: link comments first
    kept = kept[:max_kept]
    links = _links(c.get("text") for c in comments)
    return {
        "total": len(comments),
        "trigger": trigger,
        "trigger_count": trigger_count,
        "removed_repeats": removed_repeats,
        "removed_creator_replies": removed_replies,
        "kept": kept,
        "links": links,
    }
