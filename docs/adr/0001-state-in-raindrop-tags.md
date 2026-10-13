# State lives in Raindrop tags

## Context
The service must know which bookmarks it has already enriched, which failed, and which a person opted out of. A local database would be the obvious place, but it can drift from Raindrop (bookmark deleted, restored, re-saved, edited on another device) and would be invisible to the person using Raindrop.

## Decision
Processing state is stored on the bookmark itself as tags: `raingist-done`, `raingist-failed`, `raingist-skip`, plus the control tags `raingist-ocr` and `raingist-redo`. Polling queries Raindrop for bookmarks without a state tag. Only retry bookkeeping (attempt counts and backoff times) lives locally, in `DATA_DIR/state/<account-id>/attempts.json`.

## Consequences
- People can see and change state from any Raindrop client: remove `raingist-done` or add `raingist-redo` to reprocess, add `raingist-skip` to opt out.
- Losing the local state directory only resets retry counters; nothing gets processed twice.
- These tag names are reserved: the LLM may never generate them, and they are configurable (`TAG_*`) for anyone who already uses them.
- State tags appear in the user's tag list.
