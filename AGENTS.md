# raingist

Self-hosted service that enriches Raindrop.io bookmarks (TikToks today) with an AI summary in the note and topic tags. It runs natively on an M1 Mac as a launchd agent. For what it does and how to operate it, read [README.md](README.md). For vocabulary, read [GLOSSARY.md](GLOSSARY.md). Read the relevant [docs/adr/](docs/adr/) entry before changing anything an ADR covers.

## Secrets and private data

Keep out of: `.env`, `secrets/`, and `/Volumes/T7/raingist/accounts/` (OAuth tokens). Don't read, print, edit or search them.
- To check config, load it through `load_settings()` and print only presence or non-secret fields.
- To touch an account, go through `accounts.store(s)`.
- If a value is needed, ask the owner.
- When `.env` needs a change, tell the owner which lines to edit; `.env.example` is the template you maintain.

## Working loop

1. Change code and add a test beside it (`tests/test_<module>.py`). Tests make no network calls; monkeypatch at the module boundary (`pipeline.extract`, `llm.PROVIDERS`, `tiktok.fetch_page`, …).
2. `uv run pytest -q` is green.
3. For behaviour that touches TikTok or the LLM, check a real URL without writing to Raindrop: `uv run raingist test --url <url> [--ocr] [--note '…']`.
4. Before any real Raindrop write, run `uv run raingist once --dry-run` and read the logged `PUT`s. The owner's library is real data.
5. `uv run raingist restart` so the running service picks up the change.
6. Commit with a message that says why.

Python is pyenv 3.13 with uv set to system interpreters only (ADR 0005). Run everything through `uv run`.

## Invariants

- **The note is append-only.** The owner's text stays byte-for-byte; the service only appends or replaces its own block (`**AI summary**` … `_source: …_`) and its `_raingist-failed: …_` line.
- **The `raingist-` tag prefix is reserved** for state and control tags, which are configurable but must keep the prefix. `choose_tags` drops any generated tag in that namespace.
- **Failure classification decides retry.** Raise `TransientFailure` for anything that might work later (layout changes, timeouts, quota) and `PermanentFailure` only when the post itself is gone or private. A wrong permanent failure tags the bookmark `raingist-failed` for good.
- **Fail loud on config.** Validate in `settings.load_settings` and exit with a clear message; registries are plain dicts checked there (ADR 0004).
- **All data lives under `DATA_DIR` on the T7 drive**, never in `~/.cache` or the repo; the `.raingist` sentinel proves the drive is mounted.

## Gotchas (each found the hard way)

- **TikTok `/photo/` pages carry no post data.** Slideshows are read from the same post's `/video/` URL (`tiktok.data_url`).
- **Raindrop's token URL redirects.** `raindrop.io/oauth/access_token` answers 307; call `api.raindrop.io/v1/oauth/access_token` directly. Raindrop also reports OAuth errors as HTTP 200 with `result: false`.
- **Apple Vision can hang forever.** OCR runs in a child process (`ocr/worker.py`) with a timeout; keep backends out of the main process.
- **Keep a reference to SDK clients for the whole call.** A garbage-collected `genai.Client` closes its HTTP connection mid-request.
- **Gemini overshoots length rules.** Takeaway caps are enforced in `llm.summarize`, not only in the prompt.
- **Extraction is cached by URL** (`DATA_DIR/transcripts`, separate key with OCR), so a redo reuses the transcript. Delete the cache entry to force a fresh download.
