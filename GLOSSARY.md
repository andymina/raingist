# raingist

A self-hosted service that enriches Raindrop.io bookmarks with an AI summary and topic tags, without any manual step.

## Service and accounts

**Service**:
This application as one deployment: one configuration, one Raindrop app, one LLM key set, one TikTok session, one alert channel.
_Avoid_: app, bot, server

**Account**:
A Raindrop account connected to the Service via OAuth. Its own data is only its tokens and an on/off switch. Currently only the owner's.
_Avoid_: user, tenant, library

**Inbox**:
The Account's one collection named `raingist`, the only place the Service processes from. A Bookmark in it is waiting; leaving it means done.
_Avoid_: queue, processing box

**Routing**:
Moving a finished Bookmark out of the Inbox into the collection that already holds similar content, or Unsorted if none does.
_Avoid_: filing, sorting

**Organizing**:
The daily run that files Unsorted Bookmarks into collections, creates a collection for a topic with enough Bookmarks, and merges collections that serve the same purpose.
_Avoid_: cleanup, auto-sort, librarian

**Excluded collection**:
A collection whose description contains `#raingist-exclude`. The Service never routes to, files into, merges or nests under it.

**Provenance**:
The `(created by raingist)` suffix on the description of a collection that Organizing created. A collection without it is the owner's, and survives any merge with one that has it.

**Bookmark**:
A Raindrop item. The Service never destroys its existing Note or Tags.
_Avoid_: raindrop, item, link, save

**Enrichment**:
The AI summary block appended to a Bookmark's Note, plus the tags added to it.
_Avoid_: hydration, annotation

**Processing state**:
Where a Bookmark stands with the Service: pending (in the Inbox), done (routed out of it), failed (`raingist-failed`), or opted out (`raingist-skip`).

**Owner note**:
The spans of a Bookmark's Note marked with `$start.` and `$end.`, given to the summarizer and cut from the Note once the Enrichment is written. It steers or explains that Bookmark's Enrichment.
_Avoid_: owner instructions, prompt, note prompt

**Control tag**:
A tag a person adds to steer processing: `raingist-ocr` (read the on-screen text of a video) or `raingist-redo` (replace the Enrichment).
_Avoid_: flag, command tag

## Content

**Extractor**:
The pluggable part that turns a Bookmark from one content source (currently TikTok and Instagram Reels) into an Extraction.
_Avoid_: scraper, downloader, handler

**Extraction**:
The text gathered for one Bookmark: transcript, on-screen text, and metadata. Its **Source** is `captions`, `whisper`, `ocr` or `metadata`; its **Format** is `video` or `slideshow`.

**Reused sound**:
A TikTok video's audio that is not the creator's own: a song, or another person's sound. Its transcript is not trusted as the creator's words.
_Avoid_: trending audio, borrowed audio

**Slideshow**:
A TikTok photo post. Its text comes from the on-screen text of every image plus the caption.
_Avoid_: carousel, photo mode

**Registry**:
A named set of interchangeable implementations of one pluggable part: Extractors, transcribers, OCR backends, LLM providers, account stores.
_Avoid_: plugin, factory

## Operation

**Cycle**:
One pass of the Service over all enabled Accounts, processing a bounded number of pending Bookmarks per Account.
_Avoid_: run, tick, job

**Transient failure**:
A failure worth retrying later with backoff; becomes `raingist-failed` once retries run out.

**Permanent failure**:
A failure that cannot succeed on retry (private, deleted, login-only, geo-blocked); the Bookmark is marked `raingist-failed` immediately.

**Systemic alert**:
The alert raised when several Bookmarks in a row fail within one Account's Cycle, signalling breakage rather than a bad Bookmark.
