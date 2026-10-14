import re

MARKER = "**AI summary**"
LEGACY_FOOTER = "_source:"   # last line of blocks written before 2026-10-14
FAIL_MARKER = "_raingist-failed:"
PLACEHOLDER_TITLES = {"tiktok - make your day", "tiktok", ""}
PLACEHOLDER_PREFIXES = ("tiktok · ",)   # Raindrop's default "TikTok · <creator name>"
MAX_NOTE = 10000   # Raindrop's hard limit; the API rejects longer notes
RESERVED_PREFIX = "raingist-"   # state/control tags live here; generated tags never may

def normalize_tag(t: str) -> str:
    t = re.sub(r"[\s_]+", "-", t.strip().lower())
    t = re.sub(r"[^a-z0-9-]", "", t)
    return re.sub(r"-{2,}", "-", t).strip("-")

def choose_tags(generated: list[str], library_tags: list[str], reserved: frozenset[str], max_new: int = 6) -> list[str]:
    lib = {normalize_tag(t): t for t in library_tags}
    out, new = [], 0
    for g in generated:
        n = normalize_tag(g)
        if not n or n in reserved or n.startswith(RESERVED_PREFIX) or n in out:
            continue
        if n in lib:
            out.append(lib[n])
        elif new < max_new:
            out.append(n); new += 1
    return out

def merge_tags(item_tags: list[str], add: list[str]) -> list[str]:
    """Existing tags first, then `add`, case-insensitively de-duplicated. Never removes the person's tags."""
    out, seen = [], set()
    for t in [*item_tags, *add]:
        if t.lower() not in seen:
            seen.add(t.lower()); out.append(t)
    return out

NOTE_TOKEN = re.compile(r"\$(start|end)\.")

def owner_note(note: str) -> str:
    """The part of the person's own note sent to the summarizer: the whole note when it has no
    $start./$end. tokens, else only the spans between them ($start. alone runs to the end,
    a leading $end. alone starts at the beginning). Never the AI block or failure line."""
    own = strip_failure_line(strip_ai_block(note or ""))
    pieces = NOTE_TOKEN.split(own)   # [text, "start"|"end", text, ...]
    if len(pieces) == 1:
        return own.strip()
    out, inside = [], pieces[1] == "end"
    for i in range(0, len(pieces), 2):
        if inside and pieces[i].strip():
            out.append(pieces[i].strip())
        if i + 1 < len(pieces):
            inside = pieces[i + 1] == "start"
    return "\n".join(out)

def strip_reserved(tags: list[str]) -> list[str]:
    return [t for t in tags if not t.lower().startswith(RESERVED_PREFIX)]

def strip_failure_line(note: str) -> str:
    return "\n".join(l for l in note.splitlines() if not l.startswith(FAIL_MARKER)).rstrip()

def strip_ai_block(note: str) -> str:
    """Remove our block: the MARKER line, the summary line after it, the "- " takeaway lines that follow,
    and a legacy _source: footer. Anything after the last bullet is the person's again."""
    out, state = [], "outside"
    for line in (note or "").splitlines():
        if line.strip() == MARKER:
            state = "summary"; continue
        if state == "summary":
            state = "bullets"; continue
        if state == "bullets" and line.startswith("- "):
            continue
        if state == "bullets" and line.startswith(LEGACY_FOOTER):
            state = "outside"; continue
        state = "outside"
        out.append(line)
    return "\n".join(out).rstrip()

def _one_line(text: str) -> str:
    return " ".join(text.split())   # strip_ai_block relies on one line per summary/takeaway

def creator_label(name: str | None, handle: str | None) -> str | None:
    """'Cassie Yeung (@cassyeungmoney)', '@cassyeungmoney' or None, from the platform's own data."""
    tag = f"@{handle}" if handle else None
    if name and tag and name.lower().replace(" ", "") != handle.lower():
        return f"{name} ({tag})"
    return tag or name or None

def build_block(summary, creator: str | None = None) -> str:
    """Recipes credit their creator on the first takeaway line."""
    credit = [f"- Creator: {creator}"] if summary.recipe and creator else []
    return "\n".join([MARKER, _one_line(summary.summary), *credit,
                      *[f"- {_one_line(t)}" for t in summary.key_takeaways if t.strip()]])

def merge_note(existing: str, block: str) -> str:
    existing = strip_failure_line(existing or "")
    if MARKER in existing:
        return existing   # already enriched; idempotent
    note = f"{existing}\n\n{block}" if existing.strip() else block
    return note if len(note) <= MAX_NOTE else note[:MAX_NOTE - 1].rstrip() + "…"

def merge_failure(existing: str, reason: str, date: str) -> str:
    base = strip_failure_line(existing or "")
    line = f"{FAIL_MARKER} {reason[:200]} · {date}_"
    return f"{base}\n\n{line}" if base.strip() else line

def is_placeholder_title(title: str | None, link: str) -> bool:
    t = (title or "").strip().lower()
    return t in PLACEHOLDER_TITLES or t.startswith(PLACEHOLDER_PREFIXES) or t == link.strip().lower()
