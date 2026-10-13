# TikTok slideshows: page JSON scrape and always-OCR

## Context
TikTok photo posts ("slideshows") have no video stream and usually no speech, so yt-dlp cannot extract them and there is nothing to transcribe. The meaning is in the text drawn on the images plus the caption.

## Decision
Every TikTok bookmark's URL is resolved (following `vm.tiktok.com` redirects) and its post page fetched. A `/photo/` URL is a slideshow: the image URLs and caption come from the page's embedded `__UNIVERSAL_DATA_FOR_REHYDRATION__` JSON, all images (up to 35) are downloaded and OCR'd, and no transcription runs. If OCR finds nothing, the summary is built from the caption alone with low confidence. Videos keep the yt-dlp path, with frame OCR opt-in via `ai-ocr`.

## Consequences
- The scrape depends on an undocumented page structure and may break or hit a bot wall; that is treated as a transient failure and surfaces as a systemic alert. The fix is updating `parse_post`, or setting TikTok cookies.
- Slideshows always cost OCR time; videos only when asked.
