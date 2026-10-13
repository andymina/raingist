# raingist

A self-hosted service that enriches Raindrop.io bookmarks. When a connected Raindrop account saves a TikTok, the service adds two things within about 5 minutes, with no manual step:

- an AI summary appended to the bookmark's **Note**
- topic **Tags**

It runs natively on an M1 Mac mini. mlx-whisper handles speech-to-text on the Apple GPU, Apple Vision handles OCR, and Gemini's free tier writes the summaries. Running it costs nothing beyond electricity.

Terms are defined in [GLOSSARY.md](GLOSSARY.md). Design decisions are in [docs/adr/](docs/adr/).

## Architecture

```
launchd (KeepAlive) → raingist serve
  every POLL_INTERVAL_SECONDS:
    for each enabled account (DATA_DIR/accounts/*.json, OAuth tokens auto-refreshed)
      Raindrop API: bookmarks from the last 14 days without a state tag, plus any tagged ai-redo
      → extractor (TikTok: video via yt-dlp, slideshow via page JSON)
          → captions, else transcriber (mlx-whisper); OCR (Apple Vision) for slideshows or ai-ocr
      → LLM (Gemini, optional Anthropic fallback): summary, takeaways, tags, title
      → write-back: append note block, merge tags, add ai-done (or ai-failed)
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
| `state/<account-id>/` | Retries, status, run lock |
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
   Check it's running:
   ```bash
   launchctl print gui/$(id -u)/com.raingist.serve | grep state
   ```

## Commands

`uv run raingist <command>`:

| Command | What it does |
|---|---|
| `serve` | Long-running loop (what launchd runs) |
| `once [--account ID] [--dry-run] [--limit N]` | One cycle now. `--dry-run` logs the would-be `PUT`s |
| `process --account ID --id RAINDROP_ID [--dry-run]` | One bookmark |
| `test --url URL [--ocr]` | Extract and summarize one URL without touching Raindrop |
| `connect` | OAuth-connect (or reconnect) a Raindrop account |
| `accounts [list\|enable\|disable\|disconnect] [ID]` | Manage connected accounts |
| `status` | Per-account pending count, last cycle, items being retried |

Service control:

- Restart after code changes: `launchctl kickstart -k gui/$(id -u)/com.raingist.serve`
- Uninstall: `launchctl bootout gui/$(id -u)/com.raingist.serve`

## Tags

| Tag | Set by | Meaning |
|---|---|---|
| `ai-done` | service | Enriched |
| `ai-failed` | service | Gave up; the reason is on a `_ai-failed: …_` line in the note |
| `ai-skip` | you | Never process this bookmark |
| `ai-ocr` | you | Also OCR this video's frames (1 frame every 2 s, ≤ 60 frames) |
| `ai-redo` | you | Reprocess: the old AI block is replaced, then `ai-redo` is removed |

All names are configurable (`TAG_*`). The service only adds tags: it reuses your existing tags, adds at most 6 new `lowercase-hyphen` ones, and never removes yours. The title is replaced only if it is empty, equals the URL, or is `TikTok - Make Your Day`. The excerpt is never touched.

## TikTok: videos vs slideshows

- **Videos:** captions via yt-dlp, else Whisper. Frame OCR runs only with `ai-ocr`.
- **Slideshows** (`/photo/` posts): the image URLs and caption come from the post page's embedded JSON. Every image (≤ 35) is OCR'd and nothing is transcribed. If OCR finds no text, the summary is built from the caption alone with `confidence: low`.

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
- An owner note can override the default length (up to 15 takeaways). It can't change the tag rules, and it can't make the summary go beyond the source material.
- To apply a changed note to an already-processed bookmark, add `ai-redo`.
- To try a note without touching Raindrop: `uv run raingist test --url <url> --note '…'`

## Alerts

Alerts go to `NOTIFY_URL` (ntfy), at most once every 6 h per alert key. Without a URL, they're only logged at ERROR level. Triggers:

- T7 not mounted
- a cycle crash
- an account's cycle failing (for example, a revoked grant)
- an invalid account file
- 3 failing bookmarks in a row within one account's cycle
- each bookmark marked `ai-failed`

## Collection filters

Edit `include_collections` / `exclude_collections` (lists of Raindrop collection ids) in `DATA_DIR/accounts/<id>.json`. An empty list means all collections. Filters match a bookmark's own collection exactly, so sub-collections must be listed separately. Unsorted is collection `-1`. Reconnecting keeps the filters.

The owner account currently processes only the `raingist` collection (`include_collections: [76070344]`).

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
uv lock --upgrade-package yt-dlp && uv sync && launchctl kickstart -k gui/$(id -u)/com.raingist.serve
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
| Same video with `ai-ocr` (Whisper + 4 frames OCR'd + Gemini) | 8.1 s |

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
| Alert "N bookmarks in a row failed … Unable to extract" | yt-dlp broke against TikTok | `uv lock --upgrade-package yt-dlp && uv sync`, then kickstart the agent |
| "IP address is blocked" / 403 | IP flagged by TikTok | Wait a few hours |
| Login-only TikTok → `ai-failed` "log in" | No TikTok session | Add `secrets/tiktok-cookies.txt` and set `TIKTOK_COOKIES_FILE` |
| Slideshows → retry "no embedded data" | TikTok page layout changed, or a bot wall | Set cookies; update `parse_post` |
| "no LLM provider available … 429" | Gemini free quota hit | Items retry on their own; or add `anthropic` to `LLM_PROVIDERS` with a key |
| Alert `account:<id>` "… 401" | Grant revoked or refresh failed | Run `uv run raingist connect` again |
| Alert `account-file:<id>` | Corrupt account file | Run `uv run raingist accounts`, then reconnect |
| Alert "… not mounted" | T7 disconnected | Reconnect it; the next cycle resumes |
| `connect` fails "address already in use" | Port 8765 is busy | Free the port, or change `RAINDROP_REDIRECT_URI` and the Raindrop app setting to match |
| Nothing processed | Agent not running, Mac asleep or logged out, not a TikTok, > 14 days old, has a state tag, collection filter, account disabled | `launchctl print gui/$(id -u)/com.raingist.serve`; `uv run raingist status`; add `ai-redo` |
| Want OCR on a video that's already done | Video OCR is opt-in | Add `ai-ocr` and `ai-redo` |
