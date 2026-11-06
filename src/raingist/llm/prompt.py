from typing import Literal
from pydantic import BaseModel, Field
from ..extract.common import Extraction

class Summary(BaseModel):
    summary: str
    key_takeaways: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    title: str = ""
    language: str = "en"
    confidence: Literal["high", "medium", "low"] = "medium"
    collection_id: int = 0   # routing choice from COLLECTIONS; 0 = none fits
    collection_reason: str = ""   # what in the chosen collection's profile it matches
    collection_confidence: Literal["high", "medium", "low"] = "low"   # only "high" routes
    recipe: bool = False     # the code then credits the creator (see writeback.build_block)

class NewCollection(BaseModel):
    title: str
    description: str
    parent_id: int = 0       # 0 = top level
    item_ids: list[int] = Field(default_factory=list)

class Merge(BaseModel):
    from_id: int
    into_id: int
    reason: str = ""

class Proposal(BaseModel):
    new_collections: list[NewCollection] = Field(default_factory=list)
    merges: list[Merge] = Field(default_factory=list)

class Move(BaseModel):
    item_id: int
    collection_id: int = 0   # 0 = no collection clearly fits (assign: stays in Unsorted; rebalance: back to Unsorted)
    confidence: Literal["high", "medium", "low"] = "low"   # only "high" moves
    reason: str = ""

class Assignment(BaseModel):
    moves: list[Move] = Field(default_factory=list)

class Description(BaseModel):
    collection_id: int
    description: str

class Descriptions(BaseModel):
    items: list[Description] = Field(default_factory=list)

class ProviderUnavailable(Exception):
    """Quota, overload or connection problem: try the next provider."""

FIT_RULES = """How to judge whether a bookmark belongs in a collection from COLLECTIONS:
- A collection's scope, when given, is the rule: the bookmark belongs only if the scope covers what it is about.
  Its examples only illustrate the scope; without a scope, infer one from what the examples have in common.
- A bookmark like one listed under "not here" does not belong there: the owner moved that kind out.
- Sharing a word, a tag, a place, a mood, a person or an occasion is not belonging. A guide to jazz bars is not
  music-making material; a restaurant list that mentions playlists is still a restaurant list.
- Confidence is "high" only when a careful reader of that collection would expect this bookmark in it.
  Anything less is "medium" or "low", and a weak or partial match means no collection."""

SYSTEM_PROMPT = """You write terse, searchable notes about saved bookmarks for a personal knowledge base.
Use ONLY the provided material (title, URL, description, transcript, on-screen text). Every fact, name,
number and claim comes from it. If the material is thin, write less and set confidence to "low".

summary: one short sentence, two at most, stating the substance itself, like a note to self. Open with the subject
("Four free Claude Code plugins: ...", "NFL scoring streaks for week 6: ..."), not with framing about the post
("This video highlights...", "The creator shows...").
key_takeaways: one terse line per distinct point or item in the material, as many as it has and no more, unless
OWNER_NOTE narrows them. When the material lists things, write "Name: what it is or does". Each line adds something
the summary does not.
Write about the content only: the person who posted it stays out of the summary, takeaways and title.
Searchability: use the exact names and terms someone would later type to find this: products, tools, repos, people,
teams, brands, places, acronyms, jargon and buzzwords, spelled as in the material. Prefer the specific name to a
generic description.
title: at most 80 characters, specific, keyword-first.
Tags: 2-4 tags, never fewer than 2. For each main topic, reuse an EXISTING_TAGS tag only when it truly names that
topic; a loosely related tag does not count (a list of YouTube videos to watch is not "productivity"). Otherwise
create a new broad tag for it. 6 new tags is the hard maximum.
Tags are lowercase, hyphenated, ASCII, broad reusable topics (for example "cooking", "swift", "personal-finance"),
never one-off phrases or names, and never starting with "raingist-".
Recipes: key_takeaways are the full recipe, in order: first "Ingredients: ..." with every ingredient and its amount,
then one line per step with its times (cooking, marinating, resting), temperatures and heat settings. Every
quantity, count, time and temperature that appears anywhere in the material (DESCRIPTION/caption, transcript,
on-screen text) is kept, attached to its ingredient or step: "1 tsp dashi powder", "2 packs frozen udon", "2 eggs".
Write the summary, takeaways and title in the language with ISO 639-1 code "{language}".
Report the source material's own ISO 639-1 code in "language".
Output strict JSON with fields: summary (string), key_takeaways (string[]), tags (string[]), title (string),
language (ISO 639-1), confidence ("high"|"medium"|"low"), collection_id (integer), collection_reason (string),
collection_confidence ("high"|"medium"|"low"), recipe (boolean: true when the material is a recipe for food or drink).
collection_id: when COLLECTIONS is present, the id of the one collection this bookmark clearly belongs in, judged by
the rules below; 0 when none does. Only ids from COLLECTIONS. collection_reason: a short phrase naming what in that
collection's scope or examples it matches (empty for 0). collection_confidence: how sure the collection fits.
""" + FIT_RULES + """
AUDIO, when present, means the video uses a reused sound (a song or another person's audio), so TEXT may be lyrics
or someone else's voice rather than the creator's words: use TEXT only where it clearly matches DESCRIPTION or
ON_SCREEN_TEXT, and otherwise base the summary on those.
OWNER_NOTE, when present, comes first and is written by the person who saved the bookmark. If it asks for something
(what to focus on, include, leave out or list), it decides the scope of summary, key_takeaways and title: cover only
what it asks for and drop everything else, even when the material has more. Otherwise treat it as context for why
they saved it. It never overrides the JSON format, the tag rules, or using only the provided material; never
summarize the note itself."""

PROPOSE_PROMPT = """You organize a personal bookmark library. You get the existing COLLECTIONS and the UNSORTED bookmarks,
which are only those that fit no existing collection.
new_collections: propose one only for a clear topic shared by at least {min_group} UNSORTED bookmarks.
item_ids are the UNSORTED ids that belong in it.
title: copy the style of the existing collection titles exactly: if most start with an emoji, start with one fitting
emoji; match their letter case, length and singular or plural. At most 40 characters, specific rather than generic.
description: one sentence saying what belongs in it and, where it helps, what does not, so a reader can decide whether
a new bookmark belongs there.
parent_id: an existing collection id when the topic is clearly a sub-topic of it, otherwise 0.
merges: only two existing collections that serve the same purpose under different names (for example "Recipes" and
"Cooking", or "AI tools" and "AI Tools 🤖"). Overlapping but distinct scopes ("Recipes" and "Meal prep") stay apart.
Never merge a collection with its own parent or child. from_id is merged into into_id; reason is a short phrase.
No new collections and no merges is a normal answer. Use only ids from the input.
Output strict JSON with fields: new_collections ({{title, description, parent_id, item_ids}}[]), merges
({{from_id, into_id, reason}}[])."""

ASSIGN_PROMPT = """You file UNSORTED bookmarks into existing COLLECTIONS. For each UNSORTED bookmark, collection_id is the id
of the one collection it clearly belongs in, or 0 when none does. Only ids from COLLECTIONS.
""" + FIT_RULES + """
Output strict JSON with field moves ({item_id, collection_id, confidence ("high"|"medium"|"low"), reason}[]), one entry
per UNSORTED bookmark; reason is a short phrase naming what in the collection's scope or examples it matches."""

REBALANCE_PROMPT = """You re-check FILED bookmarks, which an automatic filer put into collections earlier, against COLLECTIONS.
Judge each FILED bookmark fresh: collection_id is the one collection it clearly belongs in, or 0 when none does.
Only ids from COLLECTIONS.
""" + FIT_RULES + """
Output strict JSON with field moves ({item_id, collection_id, confidence ("high"|"medium"|"low"), reason}[]), one entry
per FILED bookmark; reason is a short phrase naming what in the chosen collection's scope or examples it matches, or
why none fits."""

DESCRIBE_PROMPT = """You write scope descriptions for the owner's bookmark collections listed in DESCRIBE, using each one's
title, examples and "not here" bookmarks from COLLECTIONS. A scope is one sentence of at most 200
characters, in the form "What belongs; not what doesn't", specific enough that a reader can decide whether a new
bookmark belongs (for example "Techniques, artists and albums I study for making music; not concerts, venues or
playlists"). Describe what the examples have in common, not every example.
Output strict JSON with field items ({collection_id, description}[]), one per DESCRIBE id."""

MAX_WORDS = 6000

def catalog_lines(catalog: list[dict]) -> list[str]:
    """Each collection's profile: scope (the rule), examples (title - summary), and "not here" bookmarks. No tag
    summary: the model matched tags instead of judging scope."""
    if not catalog:
        return ["COLLECTIONS: (none)"]
    lines = ["COLLECTIONS (id: path, then its profile):"]
    for c in catalog:
        size = f" ({c['size']} bookmarks, made by {c['made_by']})" if "size" in c else ""
        lines += [f"{c['id']}: {c['title']}{size}",
                  f"  scope: {c['description'] or '(none: infer it from the examples)'}"]
        lines.append(f"  examples: {' | '.join(e for e in c.get('examples', []) if e) or '(none)'}")
        if c.get("not_here"):
            lines.append(f"  not here: {' | '.join(c['not_here'])}")
    return lines

def build_user_message(item: dict, ctype: str, ex: Extraction, existing_tags: list[str], owner_note: str = "",
                       catalog: list[dict] | None = None) -> str:
    words = (ex.text or "").split()
    text = " ".join(words[:MAX_WORDS]) + (" [truncated]" if len(words) > MAX_WORDS else "")
    return "\n".join([
        *(["OWNER_NOTE:", owner_note] if owner_note else []),   # first, so long material can't bury it
        f"CONTENT_TYPE: {ctype} {ex.format}",
        f"URL: {item.get('link', '')}",
        f"TITLE: {item.get('title', '')}",
        f"DESCRIPTION: {ex.description or item.get('excerpt') or ''}",
        f"EXISTING_TAGS: {', '.join(existing_tags[:300])}",
        f"TEXT_SOURCE: {ex.source}",
        *([f"AUDIO: reused sound: {ex.sound}"] if ex.sound else []),
        "TEXT:", text or "(none)",
        "ON_SCREEN_TEXT:", ex.onscreen or "(none)",
        *(catalog_lines(catalog) if catalog is not None else []),
    ])
