# raingist

A self-hosted service that enriches Raindrop.io bookmarks. Save a TikTok into your **`raingist` collection** and within a minute or two, with no manual step, the service:

- appends an AI summary to the bookmark's **Note**
- adds topic **Tags**
- gives it a descriptive **title** if it only had a placeholder
- **moves it out** of `raingist`: into an existing collection with similar content, or into Unsorted if none fits

`raingist` is a processing inbox: anything in it is waiting, anything that leaves it is done.

It runs natively on an M1 Mac mini. mlx-whisper handles speech-to-text on the Apple GPU, Apple Vision handles OCR, and Gemini's free tier writes the summaries. Running it costs nothing beyond electricity.

Terms are defined in [GLOSSARY.md](GLOSSARY.md). Design decisions are in [docs/adr/](docs/adr/).

## Architecture

```
launchd (KeepAlive) → raingist serve
  every 60 s (POLL_INTERVAL_SECONDS):
    for each enabled account (DATA_DIR/accounts/*.json, OAuth tokens auto-refreshed)
      Raindrop API: bookmarks in the inbox collection, except raingist-failed / raingist-skip
      → extractor (TikTok: video via yt-dlp, slideshow via the post page's JSON)
          → captions, else transcriber (mlx-whisper)
          → OCR (Apple Vision, in a child process with a timeout) for slideshows, or videos tagged raingist-ocr
      → LLM (Gemini, optional Anthropic fallback): summary, takeaways, tags, title
      → write-back, one PUT: append note block, merge tags, drop raingist-* tags, move to the chosen collection
        (on failure: raingist-failed + reason line, stays in the inbox)
```

Each pluggable part is a plain `name → implementation` dict selected in `.env` ([ADR 0004](docs/adr/0004-pluggable-registries.md)):

| Registry | Where | Config | Today |
|---|---|---|---|
| `EXTRACTORS` | `extract/__init__.py` | `ENABLED_EXTRACTORS` | `tiktok` |
| `TRANSCRIBERS` | `transcribe/__init__.py` | `TRANSCRIBER` | `mlx-whisper` |
| `OCR_BACKENDS` | `ocr/__init__.py` | `OCR_BACKEND` | `vision` |
| `PROVIDERS` | `llm/__init__.py` | `LLM_PROVIDERS` (ordered fallback) | `gemini`, `anthropic` |
| `ACCOUNT_STORES` | `accounts/__init__.py` | `ACCOUNT_STORE` | `files` |

All data lives on the T7 drive under `DATA_DIR` (`/Volumes/T7/raingist`):

| Path | Contents |
|---|---|
| `accounts/` | Account files |
| `models/` | Whisper model |
| `transcripts/` | Extraction cache |
| `state/<account-id>/` | Retries and last-cycle status per account |
| `state/serve.json`, `state/run.lock` | Service heartbeat (pid, next poll) and the lock that stops cycles overlapping |
| `work/` | Temporary downloads |
| `logs/raingist.log` | Rotating log, 10 MB × 3 |

The sentinel file `DATA_DIR/.raingist` proves the drive is mounted. If it's missing, `serve` skips the cycle and sends an alert, and one-shot commands exit with code 2.

## Setup

1. **Prerequisites (one time):**
   - Create a Raindrop app: app.raindrop.io → Settings → Integrations → For Developers → Create new app. Set the redirect URI to `http://localhost:8765/callback`.
   - Get a Gemini API key from aistudio.google.com/apikey.
   - In System Settings → Energy, prevent automatic sleep, and keep the user session logged in.
   - Subscribe the ntfy phone app to a long random topic.
   - Optional: export TikTok cookies while logged in.
2. **Tooling:**
   ```bash
   brew install pyenv uv ffmpeg
   pyenv install --skip-existing "$(pyenv latest -k 3.13)"
   uv sync
   ```
3. **Config:**
   ```bash
   cp .env.example .env
   chmod 600 .env
   ```
   Fill in `RAINDROP_CLIENT_ID`, `RAINDROP_CLIENT_SECRET`, `GEMINI_API_KEY` and `NOTIFY_URL`. Optional cookies go in `secrets/tiktok-cookies.txt` (`chmod 600`), with `TIKTOK_COOKIES_FILE` set to the file's absolute path.
4. **Data volume:**
   ```bash
   mkdir -p /Volumes/T7/raingist/{models,accounts}
   chmod 700 /Volumes/T7/raingist/accounts
   touch /Volumes/T7/raingist/.raingist
   ```
5. **Model:** `uv run raingist test --url <tiktok>` downloads the Whisper model (about 1.6 GB) into `DATA_DIR/models` on first use. It never uses `~/.cache`.
6. **Connect your Raindrop account:** `uv run raingist connect`. Your browser opens; approve there. The command prints `connected account <id> (<name>)`.
7. **Service:**
   ```bash
   ./launchd/install.sh
   ```
   Check it's running and when it polls next:
   ```bash
   uv run raingist status
   ```

## Commands

`uv run raingist <command>`:

| Command | What it does |
|---|---|
| `serve` | Long-running loop (what launchd runs) |
| `once [--account ID] [--dry-run] [--limit N]` | One cycle now. `--dry-run` logs the would-be `PUT`s |
| `process --account ID --id RAINDROP_ID [--dry-run]` | One bookmark |
| `test --url URL [--ocr] [--note TEXT]` | Extract and summarize one URL without touching Raindrop; `--note` tries an owner note |
| `connect` | OAuth-connect (or reconnect) a Raindrop account |
| `accounts [list\|enable\|disable\|disconnect] [ID]` | Manage connected accounts |
| `status` | Whether the service is running and when it polls next; per account: filters, pending count, last cycle, items being retried |
| `restart` | Restart the background service, e.g. after code or `.env` changes |

Uninstall the service: `launchctl bootout gui/$(id -u)/com.raingist.serve`

## Polling

The service checks Raindrop **every 60 seconds** (`POLL_INTERVAL_SECONDS=60` in `.env`; change it, then run `uv run raingist restart`). It processes at most `MAX_ITEMS_PER_ACCOUNT` (10) bookmarks per account per cycle, and only bookmarks created in the last `POLL_LOOKBACK_DAYS` (14). An idle cycle costs 2 Raindrop API requests, against a limit of 120 per minute. TikTok and Gemini are called only when there is a bookmark to process, so the interval doesn't affect their limits. A cycle that runs longer than the interval is followed immediately by the next one; cycles never overlap.

## The AI block

Appended below your own note:

```
**AI summary**
Four free Claude Code plugins: setup, planning, frontend design, security.
- Claude Code Setup: official Anthropic plugin that scans a project for missing add-ons and automations
- Security Guidance: checks code changes against ~25 dangerous patterns
```

- **Summary:** one or two terse sentences that open with the subject itself. The person who posted it is left out (their handle is never sent to Gemini).
- **Takeaways:** one line per distinct point, written `Name: what it is or does` for lists.
- **Searchable wording:** exact names, tools, people, brands and buzzwords from the source are kept, so free-text search finds the bookmark later.
- **Recipes:** the takeaways are the full recipe in order: an `Ingredients:` line with every amount, then one line per step with its times, temperatures and heat settings. Every quantity mentioned anywhere (caption, speech, on-screen text) is kept.
- **Length:** decided by the content, not a fixed count. The only cap is Raindrop's 10,000-character limit per note.
- The source and model used are logged, not written into the note.

## The inbox and routing

| You want to | Do this |
|---|---|
| Process a TikTok | Save it into `raingist`, or drag any existing bookmark in, whatever its age |
| Redo a summary | Move it back into `raingist` and add `raingist-redo`: the old AI block is replaced |
| Read on-screen text too | Move it back into `raingist` with `raingist-ocr` and `raingist-redo` |
| Pick the destination yourself | Ask in its note, e.g. `put this in Recipes` |

- **Where it goes:** the same Gemini call that writes the summary picks a destination. It compares the bookmark with each collection's name, description and 5 most recent bookmark titles (nested collections included, as `Parent / Child`). A weak match goes to Unsorted, so a new kind of content never lands in the wrong place. Routing improves as your collections fill up.
- **Moving back in without `raingist-redo`** keeps the existing summary and just re-routes the bookmark.
- **Failures stay in the inbox**, tagged `raingist-failed` with the reason in the note. So do non-TikToks, untouched. Retries in progress also wait there.
- Inbox mode is per account (`inbox_collection` in `DATA_DIR/accounts/<id>.json`). The owner's inbox is `raingist` (id 76070344).

## Tags

| Tag | Set by | Meaning |
|---|---|---|
| `raingist-failed` | service | Gave up; the reason is on a `_raingist-failed: …_` line in the note |
| `raingist-skip` | you | Leave this bookmark alone |
| `raingist-ocr` | you | Also OCR this video's frames (1 frame every 2 s, ≤ 60 frames) |
| `raingist-redo` | you | Reprocess: the old AI block is replaced |
| `raingist-done` | service | Tag mode only (accounts without an inbox): enriched |

All `raingist-*` tags are removed when a bookmark leaves the inbox. All names are configurable (`TAG_*`, must keep the `raingist-` prefix). Topic tags: the service only adds them, never removes yours, and prefers your existing tags: one that largely fits wins over a new, more precise one. Typically a bookmark gets 2–4 tags, often with no new ones; new tags are broad `lowercase-hyphen` topics, at most 6. The title is replaced only if it is a placeholder: empty, the URL itself, `TikTok - Make Your Day`, or Raindrop's default `TikTok · <creator name>`. The excerpt is never touched.

## TikTok: videos vs slideshows

- **Videos:** captions via yt-dlp, else Whisper. Frame OCR runs only with `raingist-ocr`.
- **Slideshows** (`/photo/` posts): the image URLs and caption come from the JSON embedded in the post's `/video/` page; the `/photo/` page itself renders in the browser and carries no data. Every image (≤ 35) is OCR'd and nothing is transcribed. If OCR finds no text, the summary is built from the caption alone with `confidence: low`.
- **Reused sounds:** when a video's sound isn't the creator's own (a song, or someone else's audio), the summarizer is told so. Any transcript is then treated as possibly lyrics or another person's voice, and the caption and on-screen text take priority. Detection compares the sound's author with the creator's name.

Bookmarks from other sites are left untouched and untagged, so a future extractor can pick them up.

## Steering a summary from the note

Your note is sent to the summarizer as the **owner note**. If it asks for something ("list every tool by name"), the summary does it. Otherwise it's used as context for why you saved the bookmark ("Claude skills").

To send only part of your note, mark it with tokens:

```
private thoughts $start. List every tool by name with one line on what it does. $end. more private thoughts
```

| Note contains | Sent to the summarizer |
|---|---|
| No tokens | The whole note |
| `$start. … $end.` (one or more pairs) | Only the marked spans |
| `$start.` only | From the token to the end of the note |
| `$end.` only | From the start of the note to the token |
| `$start. $end.` | Nothing |

- The note itself is never changed; the AI block is appended below it and is never sent back.
- An owner note can't change the tag rules, and it can't make the summary go beyond the source material.
- To apply a changed note to an already-processed bookmark, add `raingist-redo`.
- To try a note without touching Raindrop: `uv run raingist test --url <url> --note '…'`

## Alerts

Alerts go to `NOTIFY_URL` (ntfy), at most once every 6 h per alert key. Without a URL, they're only logged at ERROR level. Triggers:

- T7 not mounted
- a cycle crash
- an account's cycle failing (for example, a revoked grant)
- an invalid account file
- 3 failing bookmarks in a row within one account's cycle
- each bookmark marked `raingist-failed`

## Tag mode and collection filters

An account without `inbox_collection` runs in tag mode: it processes TikToks from the last 14 days anywhere in the library, marks them `raingist-done`, and leaves them where they are. `include_collections` / `exclude_collections` (lists of collection ids) narrow that down. Filters match a bookmark's own collection exactly, so sub-collections must be listed separately; Unsorted is `-1`. Reconnecting keeps all of these settings.

## Hosting later

- Add `faster-whisper` to `TRANSCRIBERS` and `tesseract` to `OCR_BACKENDS` as new registry entries.
- Add a Dockerfile.
- Register a public redirect URI for the OAuth callback.

The pipeline itself doesn't change. Before onboarding friends, give them a clear disclosure of what the operator can access: their Raindrop tokens and bookmarks.

## Adding a content source

1. Write `extract/<source>.py` with `matches(url) -> bool` and `extract(settings, item, workdir, want_ocr) -> Extraction`.
2. Add one entry to `EXTRACTORS` in `extract/__init__.py`.
3. Add the name to `ENABLED_EXTRACTORS`.

## Local development

```bash
uv run pytest -q
```

If the pinned pyenv version was removed, recreate the venv:

```bash
uv venv --python "$(pyenv which python)" && uv sync
```

To upgrade yt-dlp when TikTok breaks it:

```bash
uv lock --upgrade-package yt-dlp && uv sync && uv run raingist restart
```

## Timings (M1 16 GB)

| Stage | Time |
|---|---|
| Whisper large-v3-turbo, 5 s clip, model already on disk | ~7 s (includes model load) |
| Apple Vision OCR, per image | 0.07–0.4 s |
| First OCR call after install | ~1 min, one-time warm-up |
| End to end, 62 s TikTok video with captions (download, captions, Gemini) | 3.4 s |
| End to end, 11-image TikTok slideshow (2 page fetches, downloads, OCR, Gemini) | 8.1 s |
| End to end, 8 s video with no captions (Whisper incl. model load, finds no speech, Gemini) | 9.5 s |
| Same video with `raingist-ocr` (Whisper + 4 frames OCR'd + Gemini) | 8.1 s |

## Costs

| Item | Cost |
|---|---|
| LLM | $0 (Gemini free tier, one key for the service) |
| Transcription (MLX) and OCR (Vision) | $0, local |
| Raindrop API/OAuth and ntfy.sh | $0 |
| Hosting (Mac mini electricity) | ≈ $1–2/month, estimated |
| Optional Claude fallback | ≈ $0.50 per 1,000 bookmarks, only if an Anthropic key is added |

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Alert "N bookmarks in a row failed … Unable to extract" | yt-dlp broke against TikTok | `uv lock --upgrade-package yt-dlp && uv sync && uv run raingist restart` |
| "IP address is blocked" / 403 | IP flagged by TikTok | Wait a few hours |
| Login-only TikTok → `raingist-failed` "log in" | No TikTok session | Add `secrets/tiktok-cookies.txt` and set `TIKTOK_COOKIES_FILE` |
| Slideshows → retry "no embedded data" / "no post data" | TikTok page layout changed, or a bot wall | Set cookies; update `parse_post` and `data_url` in `extract/tiktok.py` |
| Retry "OCR timed out" | Apple Vision hung (it happens intermittently); the OCR process was killed | Nothing: the bookmark retries with backoff |
| "no LLM provider available … 429" | Gemini free quota hit | Items retry on their own; or add `anthropic` to `LLM_PROVIDERS` with a key |
| Alert `account:<id>` "… 401" | Grant revoked or refresh failed | Run `uv run raingist connect` again |
| Alert `account-file:<id>` | Corrupt account file | Run `uv run raingist accounts`, then reconnect |
| Alert "… not mounted" | T7 disconnected | Reconnect it; the next cycle resumes |
| `connect` fails "address already in use" | Port 8765 is busy | Free the port, or change `RAINDROP_REDIRECT_URI` and the Raindrop app setting to match |
| Bookmark sits in `raingist` | Not a TikTok, tagged `raingist-failed` / `raingist-skip`, waiting for a retry, or the service isn't running (Mac asleep or logged out) | `uv run raingist status`; the note's `_raingist-failed:` line says why; add `raingist-redo` to retry a failure |
| Went to Unsorted, not a collection | No collection clearly matched | Move it yourself, or ask in its note (`put this in Recipes`) and redo it |
| `status` says the service is NOT RUNNING | It crashed during startup, e.g. a config error in `.env` | `launchctl print gui/$(id -u)/com.raingist.serve` shows the last exit code; run `uv run raingist once` to see the error |
| Want OCR on a video that's already done | Video OCR is opt-in | Move it back into `raingist` with `raingist-ocr` and `raingist-redo` |
