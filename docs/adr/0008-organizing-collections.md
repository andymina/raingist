---
status: accepted (amends ADR-0007)
---

# Organizing: the service files Unsorted and maintains collections

## Context
Routing (ADR 0007) sends a bookmark to Unsorted when no collection clearly fits, so Unsorted fills with topics that have no home, and nothing ever makes one. The owner wanted the service to create collections for those topics, file Unsorted into them, and condense collections that serve the same purpose, unattended.

## Decision
A daily **Organizing** run per account, on by default (`ORGANIZE_ENABLED=0` turns it off), made inside the serve loop after the inbox cycle and under the same lock. The first run waits until Unsorted holds `ORGANIZE_FIRST_RUN` bookmarks. After that it runs on the first cycle after 10:00 America/New_York; a failed run retries after an hour.

It makes up to two typed LLM calls, through the same provider fallback as summaries (free tier first):
1. **assign**: each Unsorted bookmark goes to an existing collection, or stays, by the same "clear fit" bar as routing. It is shaped as pure classification so a decision model (e.g. Jev) can take it over later. It is skipped when there are no collections.
2. **propose**: from the leftovers only, new collections (title in the owner's style, a one-sentence scope description ending in `(created by raingist)`, an optional existing parent, and at least `ORGANIZE_MIN_GROUP` member bookmarks), plus merges of same-purpose collections. With fewer leftovers than that it sees no bookmarks and only judges merges, and it is skipped when there is nothing to merge either. A bookmark filed into a collection that is merged away follows it to the survivor.

Code validates everything the LLM returns and drops what breaks a rule.
- An **excluded** collection (description contains `#raingist-exclude`) and the inbox are never touched, and routing skips excluded collections too.
- In a merge, an owner-made collection survives a raingist-made one; otherwise the larger survives.
- A merge source with child collections, or one that is shared, is never deleted.
- A merge moves every bookmark, re-lists the source, and deletes it only when it is empty.
- `raingist-skip` keeps a bookmark in Unsorted.

Each run writes a journal under `DATA_DIR/state/<account>/organize/`, including the full object of every deleted collection.

## Consequences
- The service now changes the library outside the inbox: Unsorted, and every non-excluded collection through merges. This is the only path that does.
- Merges are automatic and uncapped; the journal is the way back (there is no undo command).
- The owner's collection metadata is never edited; only collections the service created carry its provenance suffix. Deleting that suffix makes a collection the owner's.
- Each Unsorted bookmark reaches the LLM once per run, and a second time only if no existing collection took it.
