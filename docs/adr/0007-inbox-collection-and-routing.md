---
status: accepted (supersedes ADR-0001)
---

# Inbox collection: state by location, LLM routing

## Context
The owner wanted the `raingist` collection to be a processing box: bookmarks leave it once enriched, go to a collection with similar content (else Unsorted), and keep no `raingist-*` tags. ADR 0001 tracked state with tags, so removing `raingist-done` would make done bookmarks look pending again.

## Decision
Each account's inbox is its one collection named `raingist`, found by name every cycle; none or several is an alerted error. The service processes only bookmarks in it, of any age, and never touches the rest of the library, so dragging an old bookmark in queues it. Being in the inbox means pending; leaving it means done. Only `raingist-failed` and `raingist-skip` block processing there, and `raingist-redo` overrides them. The destination is chosen by the same LLM call that writes the summary, from each collection's path, description and 5 recent bookmark titles. A weak match returns 0, which means Unsorted. Note, tags and collection are written in a single PUT, so no half-done state is visible. The earlier tag mode (library-wide scan of the last 14 days, `raingist-done`, include/exclude collection filters) was removed.

## Consequences
- Done bookmarks carry no service tags. Moving one back into the inbox re-routes it, and with `raingist-redo` also re-summarizes it.
- Routing quality depends on the owner's collections having names and contents that describe them. Until other collections exist, everything goes to Unsorted.
- Failures, non-TikToks and retries wait visibly in the inbox.
- Each cycle with pending work costs one extra request per collection (up to 50) to read recent titles.
