# Native macOS with MLX and Apple Vision

## Context
The service runs on an M1 Mac mini (16 GB). Whisper large-v3-turbo on the CPU in Docker is several times slower than on the Apple GPU, and Docker on macOS cannot reach the GPU or the Vision framework.

## Decision
Run natively under a launchd user agent (`KeepAlive`, `RunAtLoad`) that keeps one `raingist serve` process alive. Speech-to-text uses mlx-whisper on the GPU; OCR uses Apple Vision through ocrmac. Models stay loaded between cycles. All data (model, cache, accounts, state, logs) lives on the external T7 drive; launchd's own stdout/stderr go to `/dev/null` so the agent can start, and send its "T7 missing" alert, while the drive is unplugged.

## Consequences
- Fast and free on this hardware, but tied to macOS on Apple silicon for now.
- The agent runs in the GUI session: the Mac must not sleep and the user must stay logged in.
- Docker and Linux backends (faster-whisper, Tesseract) are deferred until hosting and slot in as registry entries (ADR 0004).
