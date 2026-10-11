---
name: skip-the-comment
description: Get the content an Instagram creator promises to send by DM ("comment PLAN and I'll send you the full guide") without commenting. Use when the user pastes an Instagram reel or post link (instagram.com/reel/..., /p/..., carousels too) and wants what is in it - the full instruction, setup, plan, list or resource the creator gates behind a comment.
---

# Skip the comment

Turn a public Instagram reel/post into the content the creator gates behind "comment X and I'll DM you".
"You" are the agent reading this skill (Claude, Codex or another agent). Always reply in the user's language. Paths below are relative to this skill's directory. Use `python3` (on Windows: `python`; if that is not found or opens the Microsoft Store, use `py -3`).

## Network and search

`setup.py install` and `extract.py` need internet. If your sandbox blocks network (Codex's default), request permission/escalation to run those two commands with network access. If you cannot get it, say so plainly and stop; never guess the content.
Research (step 4) needs web search. If you have no web search tool (Codex: enable web search in its settings or run with `--search`), tell the user in one line and still produce the deliverable from the post, tagging unverified parts ❓.

## 1. Setup (first run only)

Run `python3 scripts/setup.py check`. It installs nothing.

- `python_ok: false` → tell the user Python 3.10+ is required (macOS: `brew install python` or the installer from python.org). Stop.
- `ready: true` → go to step 2.
- `missing` is empty and only `config` is null → ask only the cookie question below (no "Install?"), save the answer, go to step 2.
- Otherwise send the user ONE message, in this order (questions always last):
  - one line: the skill is installed, but the libraries it needs are not yet (say "libraries", not "the skill");
  - the `missing` list (name, size, purpose) and where it goes: a private folder (`venv`), removable by deleting it;
  - "Install? (yes / no)";
  - only if `config` is null, the cookie question: "Can I use your browser's Instagram session to read comments? Your browser must be logged in to Instagram. Nothing leaves your computer except requests to Instagram. Options: no (default) / chrome / firefox." On Windows recommend firefox (Chrome's cookies usually cannot be decrypted there, and are locked while Chrome is open). On macOS say that chrome makes macOS ask for "Chrome Safe Storage" access once: click Allow.
- Save the cookie answer right away, even if the user declines the install: `python3 scripts/setup.py config --cookies none|chrome|firefox` (no answer → `none`).
- Run `python3 scripts/setup.py install` only after an explicit yes, using your shell tool with a long timeout (at least 10 min; Claude Code: timeout 600000 ms, or run in background). Tell the user the first install takes about 2–5 minutes.
  On no: say what is missing and stop.
- Install errors (`error_code`):
  - `venv_unavailable` → show `hint`; ask the user to run it in their own terminal (it needs their password; Claude Code: they can type `! <command>`), then rerun install.
  - `pip_failed` / `model_download_failed` → on claude.ai or in a sandboxed agent this means no network access (see Errors → `network`); elsewhere show the output.
  - `python_too_old` → as above.

## 2. Extract

Run `python3 scripts/extract.py "<link>"` using your shell tool with a long timeout (at least 5 min; Claude Code: timeout 300000 ms, or run in background; it takes 30 s – 2 min). It prints a manifest (also saved as `<out_dir>/manifest.json`).
If `status` is `error`, go to Errors.

## 3. Read everything

- `caption`.
- Each `media` item:
  - video: Read `transcript_path` and every `sheets[].path` image. Tiles go left→right, top→bottom; `seconds` gives when each tile appears; repeated tiles at the end are padding. If text on a sheet is too small to read, open the single frame for that second from `frames` (`second`, `path`).
    If the item has `transcribe_error` or `frames_error`, that step failed — tell the user in one clause and rely on what is left (sheets, transcript, caption); never treat it as 'no speech' or 'nothing on screen'.
  - image (carousel slide): Read it.
- `comments`:
  - `available: false` → mention it in one short clause, nothing more.
  - `trigger` = what people were told to comment (a hint of what is promised); `kept` = non-repeated comments (`by_creator: true` = written by the creator); `links` = links found in them.

Then decide:
1. **The deliverable:** what exactly the creator promises to send, and in what form — a prompt, a link, a file, a template, a plan, a checklist, a guide. Quote the promise (transcript or caption).
2. Which parts of it are already in the post (said, shown, written, in a comment).
3. What is missing.

The deliverable is the whole point: the user skipped the comment to get *that thing*. A summary of the reel is not the deliverable.

## 4. Research what is missing

For each missing piece separately, search by topic: tool names, exact quotes, on-screen text, what is shown. Never search by the creator's name or handle. Keep going until the piece is filled or honestly unknown. Open the page before citing it; never cite a search snippet alone.

Sources by topic:

| Topic | Use | Do not use |
|---|---|---|
| Health, fitness, diet | meta-analyses and studies (PubMed, Cochrane), WHO, medical societies | blogs, influencers, supplement shops |
| Law, tax | official law texts of the country concerned (e.g. ISAP for Poland, EUR-Lex for the EU), government sites | legal-advice blogs |
| Finance | regulators (KNF, SEC…), official data | gurus, courses |
| Tech, AI, tools | official docs, repositories, changelogs | rewritten SEO articles |

Check the creator's factual claims against these sources too.

## 5. Answer — short

```
**What they promise:** <one sentence, quoting the promise>

<THE DELIVERABLE ITSELF, in the promised form and ready to use>

<supporting content: what each part is, from the post and research>
Every item tagged:
✅ from the post · 🔎 from research ([source](link)) · ❓ best guess — say what is missing
⚠️ Creator: X. Sources: Y ([source](link))

**Want me to …?** <one offer that fits the content>
```

- **Always produce the deliverable in its promised form**, even when the creator never showed it. Build it from the post plus research.
  - A prompt → one complete, copy-paste prompt in a code block, with the real values filled in (URLs, commands, names), not placeholders.
  - A link → the actual link (from the post, its comments, or the official source found in research).
  - A plan, template or checklist → the full thing, not a description of it.
  - Say in one line that it is reconstructed, not the creator's original, and tag the reconstructed parts 🔎 / ❓.
  - **Unrecoverable deliverables:** if the promised thing is a unique private resource with no clues in the post (the creator's own Notion/Drive link, a discount or affiliate code, a personal file, "my full system" with no details), say plainly in one line that it cannot be recovered from the post. Then give the closest public equivalent, tagged ❓. Never invent a URL, code or file name.
- ✅ only for things actually said, shown or written in the post or its comments.
- No process recap, no padding.
- Offer examples: install the skill/repo, write the plan out week by week, save it as a file, make a step-by-step checklist, check which tools are still free and current.
- Do the offered action only after the user says yes.

## Errors

| `error_code` | What to do |
|---|---|
| `unsupported_url` | "I only handle Instagram reel/post links." Stop. |
| `private`, `not_found` | "This works only on public posts." Stop. |
| `blocked` | Instagram blocked the download. If `cookies` is `none`: offer to use the browser session (`setup.py config --cookies chrome|firefox`, the browser must be logged in to Instagram), then rerun once after a yes. Otherwise: "Instagram is blocking downloads right now, try again later." |
| `cookies_unreadable` | The browser's cookies could not be read. Suggest the other browser (`setup.py config --cookies firefox` or `chrome`) or closing Chrome completely, then rerun once after a yes. |
| `network` | "I can't download this reel in this environment." Then say how to fix it: claude.ai: Settings → Capabilities → allow all domains, then a new chat; Codex: approve network access for the command or enable network in the sandbox settings; or use Claude Code. |
| `not_set_up` | Go to step 1. |
| `unknown` | Show the last lines of `detail`. |

Never reconstruct or guess the content of a post you could not download.

## Files

Everything stays in `out_dir` in the system temp folder. Do not copy anything into the user's working directory unless asked.
