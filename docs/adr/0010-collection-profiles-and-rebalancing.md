---
status: accepted (amends ADR-0007, ADR-0008 and ADR-0009)
---

# Collection profiles, confident decisions, and rebalancing

## Context
Routing and Organizing judged a collection by its name, description and 5 newest titles. Five bare titles are a thin signal: "Six NYC vinyl listening bars" reads as music to a model that only sees the word "music inspiration". The prompts also asked whether a collection "already holds this kind of content", which made the model guess each scope from examples. And once a bookmark was filed, nothing ever reconsidered it unless its whole collection was merged.

## Decision
- **Profiles.** Each collection is shown as a profile: path, description (labelled scope), up to 15 example bookmarks spread across it (title and summary line), and up to 5 "not here" titles: bookmarks the service filed there that the owner moved out. In an owner's collection only bookmarks the owner placed are examples or tag sources (ADR 0009). The owner has a handful of collections, so the larger prompt is cheap. A first version also listed each collection's common tags; in a dry run the model justified every decision by tag overlap ("nyc, food-guide") and kept NYC restaurant lists in a music collection, so tags are left out.
- **The description is the rule.** Shared fit rules in every deciding prompt: a scope decides, examples only illustrate it, a "not here" lookalike does not belong, and sharing a word, place, mood or occasion is not belonging.
- **Confident decisions only.** Routing (`collection_confidence`, `collection_reason` in the summary) and Organizing's filing and rebalancing (`confidence`, `reason` per move) act only on "high". The reason is logged and journalled.
- **Grounded evidence.** Each Organizing move also carries `evidence`: words copied from that bookmark's own title, tags, excerpt or note that make it what the scope describes, written before the confidence. A move into a collection is applied only if at least two thirds of the evidence's words appear in the bookmark (`organize.grounded`); a move back to Unsorted needs none. Added after Flash-Lite filed three Claude prompt tips into "Open Source GitHub" at "high", each time giving the collection's scope sentence, word for word, as its reason. A reason that only restates the scope says nothing about the bookmark. Inbox routing does not check evidence yet.
- **Decision model.** Organizing's calls use `<PROVIDER>_DECISION_MODEL`, defaulting to the summary model, so a stronger model can make the decisions without changing summaries.
- **Numbered bookmarks.** Organizing's prompts number bookmarks 1..n instead of showing 10-digit Raindrop ids; the model kept dropping a digit (a Recipes collection was refused five days running because one id was wrong).
- **Rebalancing**, Organizing's last step: bookmarks the service filed and that still sit in that collection are re-checked against the profiles, without being told where each one is now (shown its current collection, the model defended it every time). A confident better fit is a move to that collection, or to Unsorted when none fits. Never into a collection the owner moved the bookmark out of, never a bookmark the owner placed or tagged `raingist-skip`, and never in an excluded collection. `ORGANIZE_REBALANCE` is `suggest` by default (journal + alert only), `move` (capped by `ORGANIZE_REBALANCE_MAX`, default 10) or `off`.
- **Draft descriptions.** `raingist describe` prints a one-sentence scope for each owner collection without one. It never writes it: the owner's collection metadata stays theirs.

## Consequences
- Each cycle with pending work reads up to 200 bookmarks per collection (4 pages), plus one GET per newly seen "not here" bookmark, which is then cached.
- Fewer filings: medium-confidence matches now wait in Unsorted. That is the intended trade.
- In `move` mode the service can move its own past filings between collections, journalled with the reason; the owner undoes one by moving it, and that correction sticks.
