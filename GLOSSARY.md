# raingist

A self-hosted service that enriches Raindrop.io bookmarks with an AI summary and topic tags, without any manual step.

## Service and accounts

**Service**:
This application as one deployment: one configuration, one Raindrop app, one LLM key set, one TikTok session, one alert channel.
_Avoid_: app, bot, server

**Account**:
A Raindrop account connected to the Service via OAuth. Its own data is only its tokens, an on/off switch and collection filters. Currently only the owner's.
_Avoid_: user, tenant, library

**Collection filter**:
An Account's list of Raindrop collections to include or exclude. Empty means all.

## Bookmarks

**Bookmark**:
A Raindrop item. The Service never destroys its existing Note or Tags.
_Avoid_: raindrop, item, link, save

**Enrichment**:
The AI summary block appended to a Bookmark's Note, plus the tags added to it.
_Avoid_: hydration, annotation

**Processing state**:
Where a Bookmark stands with the Service: pending, done (`ai-done`), failed (`ai-failed`), or opted out (`ai-skip`).

**Control tag**:
A tag a person adds to steer processing: `ai-ocr` (read the on-screen text of a video) or `ai-redo` (replace the Enrichment).
_Avoid_: flag, command tag

## Content

**Extractor**:
The pluggable part that turns a Bookmark from one content source (currently TikTok) into an Extraction.
_Avoid_: scraper, downloader, handler

**Extraction**:
The text gathered for one Bookmark: transcript, on-screen text, and metadata. Its **Source** is `captions`, `whisper`, `ocr` or `metadata`; its **Format** is `video` or `slideshow`.

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
A failure worth retrying later with backoff; becomes `ai-failed` once retries run out.

**Permanent failure**:
A failure that cannot succeed on retry (private, deleted, login-only, geo-blocked); the Bookmark is marked `ai-failed` immediately.

**Systemic alert**:
The alert raised when several Bookmarks in a row fail within one Account's Cycle, signalling breakage rather than a bad Bookmark.
