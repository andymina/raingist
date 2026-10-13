# Pluggable parts are plain registries

## Context
Several parts will change when the service moves to a proper host or gains sources: the transcriber and OCR backend (Mac-only today), the LLM provider (free-tier quota), the account store, and the content extractors (TikTok only today).

## Decision
Each pluggable part is a plain `name -> implementation` dict chosen by config: `EXTRACTORS`, `TRANSCRIBERS`, `OCR_BACKENDS`, `PROVIDERS`, `ACCOUNT_STORES`. No plugin framework, base classes or entry points. Config values are validated against the registry keys at startup and fail loud with the valid choices.

## Consequences
- Adding a backend or source is one module plus one dict entry; the pipeline does not change.
- Implementations share a calling convention by agreement, not by an enforced interface; tests cover each registry entry.
- LLM providers form an ordered fallback list (`LLM_PROVIDERS`); quota or overload moves to the next.
