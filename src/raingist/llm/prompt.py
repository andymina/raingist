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
    collection_id: int = 0   # 0 = stays in Unsorted

class Assignment(BaseModel):
    moves: list[Move] = Field(default_factory=list)

class ProviderUnavailable(Exception):
    """Quota, overload or connection problem: try the next provider."""

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
Tags: 2-4 tags is typical. Reuse EXISTING_TAGS first: an existing tag that largely fits beats a new, more precise
one. Create a new tag only for a main topic no existing tag covers; zero new tags is normal, 6 is the hard maximum.
Tags are lowercase, hyphenated, ASCII, broad reusable topics (for example "cooking", "swift", "personal-finance"),
never one-off phrases or names, and never starting with "raingist-".
Recipes: key_takeaways are the full recipe, in order: first "Ingredients: ..." with every ingredient and its amount,
then one line per step with its times (cooking, marinating, resting), temperatures and heat settings. Every
quantity, count, time and temperature that appears anywhere in the material (DESCRIPTION/caption, transcript,
on-screen text) is kept, attached to its ingredient or step: "1 tsp dashi powder", "2 packs frozen udon", "2 eggs".
Write the summary, takeaways and title in the language with ISO 639-1 code "{language}".
Report the source material's own ISO 639-1 code in "language".
Output strict JSON with fields: summary (string), key_takeaways (string[]), tags (string[]), title (string),
language (ISO 639-1), confidence ("high"|"medium"|"low"), collection_id (integer), recipe (boolean: true when the
material is a recipe for food or drink).
collection_id: when COLLECTIONS is present, the id of the collection whose title, description and recent bookmarks
show it already holds this kind of content. Use 0 when none clearly fits; a weak match is 0. Only ids from COLLECTIONS.
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
of the collection whose title, description and recent bookmarks show it already holds this kind of content. Use 0
when none clearly fits; a weak match is 0. Only ids from COLLECTIONS.
Output strict JSON with field moves ({item_id, collection_id}[]), one entry per UNSORTED bookmark."""

MAX_WORDS = 6000

def catalog_lines(catalog: list[dict]) -> list[str]:
    return ["COLLECTIONS (id: title | description | recent bookmarks):"] + [
        f"{c['id']}: {c['title']} | {c['description']} | {'; '.join(t for t in c['samples'] if t)}" for c in catalog
    ] if catalog else ["COLLECTIONS: (none)"]

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
