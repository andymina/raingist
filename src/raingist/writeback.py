import re

MARKER = "**AI summary**"
FOOTER_PREFIX = "_source:"
FAIL_MARKER = "_ai-failed:"
PLACEHOLDER_TITLES = {"tiktok - make your day", "tiktok", ""}
MAX_NOTE = 9000

def normalize_tag(t: str) -> str:
    t = re.sub(r"[\s_]+", "-", t.strip().lower())
    t = re.sub(r"[^a-z0-9-]", "", t)
    return re.sub(r"-{2,}", "-", t).strip("-")

def choose_tags(generated: list[str], library_tags: list[str], reserved: frozenset[str], max_new: int = 6) -> list[str]:
    lib = {normalize_tag(t): t for t in library_tags}
    out, new = [], 0
    for g in generated:
        n = normalize_tag(g)
        if not n or n in reserved or n in out:
            continue
        if n in lib:
            out.append(lib[n])
        elif new < max_new:
            out.append(n); new += 1
    return out

def merge_tags(item_tags: list[str], chosen: list[str], state_tag: str, drop: frozenset[str]) -> list[str]:
    """Keep existing tags, add chosen + state_tag, remove every tag in `drop` except state_tag."""
    out, seen = [], set()
    for t in [*item_tags, *chosen, state_tag]:
        if t.lower() in seen or (t.lower() in drop and t != state_tag):
            continue
        seen.add(t.lower()); out.append(t)
    return out

def strip_failure_line(note: str) -> str:
    return "\n".join(l for l in note.splitlines() if not l.startswith(FAIL_MARKER)).rstrip()

def strip_ai_block(note: str) -> str:
    """Remove the lines from the MARKER line through the first footer line after it."""
    out, inside = [], False
    for line in (note or "").splitlines():
        if line.strip() == MARKER:
            inside = True; continue
        if inside:
            inside = not line.startswith(FOOTER_PREFIX); continue
        out.append(line)
    return "\n".join(out).rstrip()

def build_block(summary, source: str, model: str, date: str, home_language: str) -> str:
    lines = [MARKER, summary.summary.strip(), *[f"- {t.strip()}" for t in summary.key_takeaways]]
    footer = f"{FOOTER_PREFIX} {source} · {model} · {date}"
    if summary.language and summary.language != home_language:
        footer += f" · lang: {summary.language}"
    lines.append(footer + "_")
    return "\n".join(lines)

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
    return t in PLACEHOLDER_TITLES or t == link.strip().lower()
