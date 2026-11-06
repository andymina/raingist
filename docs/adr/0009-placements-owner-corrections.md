---
status: accepted (amends ADR-0007 and ADR-0008)
---

# Placements: owner corrections stick, and wrong filings don't snowball

## Context
A retro of the owner's "music inspiration" collection found 13 of its 14 bookmarks filed by the service, 11 of them wrong (NYC restaurant and cafe guides, a coding playlist). Two mechanisms made it worse over time:
- A collection is described to the LLM by its name, description and 5 newest bookmark titles. The collection had no description, so every wrong filing became one of the 5 titles and pulled in more of the same.
- Organizing files whatever is in Unsorted. When the owner moved a wrong bookmark back to Unsorted, the next run filed it into the same collection again (4 times in 11 days).

## Decision
Each account keeps **placements**, `DATA_DIR/state/<account>/placements.json`: the collections the service itself filed each bookmark into, by routing or Organizing. The first load backfills it from the Organizing journals; routing history before this change is not recovered.
- A bookmark in Unsorted that the service once filed into collection C was moved out by the owner, so Organizing never files it into C again. It can still go to another collection or a new one.
- An owner's collection is sampled only from bookmarks the service did not file there, so only the owner's own picks (and its description) say what it holds. A collection the service created keeps all its samples, since everything in it is a service filing and its description anchors it.
- Routing records placements but does not consult the rejections: dragging a bookmark back into the inbox is how the owner asks for a fresh routing.

## Consequences
- An owner's collection that only ever received service filings is described by its name and description alone. A clear description matters more than before.
- Moving a bookmark back to Unsorted is now a real "not there" signal, not a no-op until the next morning.
- Placements only grow; a bookmark the owner deletes leaves a stale entry, which is harmless.
