from comments import filter_comments, normalize


def c(author, text, **kw):
    return {"author": author, "text": text, **kw}


def test_normalize_strips_case_emoji_punctuation_and_mentions():
    assert normalize("PLAN 🔥!!") == "plan"
    assert normalize("  Plan   🙏 ") == "plan"
    assert normalize("@some.user Wysłane! ✅") == "wysłane"
    assert normalize(None) == ""


def test_spec_scenario_repeats_and_creator_replies_removed():
    comments = []
    for i in range(200):
        comments.append(c(f"fan{i}", ["PLAN", "plan 🔥", "Plan!!"][i % 3]))
    for i in range(150):
        comments.append(c("coach", f"@fan{i} Wysłane! Sprawdź DM 🔥"))
    comments += [
        c("anna", "tu macie wszystko https://notion.so/plan-abc"),
        c("bob", "github.com/someone/repo działa"),
        c("cid", "pełna wersja: https://drive.google.com/x"),
    ]
    out = filter_comments(comments, creator="coach")
    assert out["total"] == 353
    assert out["trigger"] == "plan"
    assert out["trigger_count"] == 200
    assert out["removed_repeats"] == 200
    assert out["removed_creator_replies"] == 150
    assert [k["author"] for k in out["kept"]] == ["anna", "bob", "cid"]
    assert out["links"] == ["github.com/someone/repo", "https://drive.google.com/x", "https://notion.so/plan-abc"]


def test_unique_creator_comment_is_kept_and_flagged():
    out = filter_comments([c("coach", "Link jest też w bio"), c("x", "dzięki")], creator="@Coach")
    assert out["kept"][0] == {"author": "coach", "text": "Link jest też w bio", "by_creator": True}


def test_author_is_uploader_flag_works_without_creator_name():
    comments = [c("coach", "Sent!", author_is_uploader=True), c("coach", "sent", author_is_uploader=True)]
    out = filter_comments(comments)
    assert out["removed_creator_replies"] == 2
    assert out["kept"] == []


def test_emoji_only_comments_dropped_and_empty_input():
    assert filter_comments([c("a", "🔥🔥"), c("b", "😍")])["kept"] == []
    out = filter_comments([])
    assert out == {"total": 0, "trigger": None, "trigger_count": 0, "removed_repeats": 0,
                   "removed_creator_replies": 0, "kept": [], "links": []}


def test_cap_keeps_link_comments_first():
    comments = [c(f"u{i}", f"unikalny komentarz numer {i}") for i in range(300)]
    comments.append(c("linker", "https://example.com/guide"))
    out = filter_comments(comments, max_kept=100)
    assert len(out["kept"]) == 100
    assert out["kept"][0]["author"] == "linker"


def test_duplicate_ids_counted_once():
    comments = [c("a", "PLAN", id="1"), c("a", "PLAN", id="1"), c("b", "jak to zrobić?", id="2"),
                c("b", "jak to zrobić?", id="2")]
    out = filter_comments(comments)
    assert out["total"] == 2
    assert out["trigger"] is None
    assert len(out["kept"]) == 2


def test_links_include_repeated_comments():
    comments = [c(f"fan{i}", "jest tu: https://notion.so/guide") for i in range(5)]
    comments += [c("coach", "@a Wysłane! bit.ly/xyz"), c("coach", "@b Wysłane! bit.ly/xyz"), c("z", "super")]
    out = filter_comments(comments, creator="coach")
    assert out["removed_repeats"] == 5 and out["removed_creator_replies"] == 2
    assert [k["author"] for k in out["kept"]] == ["z"]
    assert out["links"] == ["bit.ly/xyz", "https://notion.so/guide"]


def test_link_trailing_punctuation_and_false_domains():
    comments = [c("a", "Link: (https://example.com/a).”"), c("b", "zobacz github.com/x/y…"),
                c("d", "np. e.g.com albo i.e.com nie są linkami"), c("e", "»https://tally.so/r/abc»!"),
                c("f", "plik \"drive.google.com/file\";")]
    links = filter_comments(comments)["links"]
    assert links == ["drive.google.com/file", "github.com/x/y", "https://example.com/a", "https://tally.so/r/abc"]


def test_id_less_duplicates_deduped_by_author_text_timestamp():
    comments = [c("a", "PLAN", id=None, timestamp=1), c("a", "PLAN", id=None, timestamp=1),
                c("b", "PLAN", id=None, timestamp=2), c("a", "PLAN", id=None, timestamp=3)]
    out = filter_comments(comments)
    assert out["total"] == 3
