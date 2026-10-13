# Service-level credentials, OAuth per account

## Context
A Raindrop test token only reaches the library that issued it. The service is meant to serve a few accounts (< 10) eventually, but today only the owner's account is connected. LLM keys, the TikTok session and alerts are not tied to any one account.

## Decision
All credentials and behaviour are service-level in `.env`: one Raindrop OAuth app, one Gemini key, one TikTok cookie file, one ntfy URL. Every account, the owner's included, authorizes the Raindrop app once through `raingist connect`, which opens the browser and runs a temporary callback server on `localhost:8765` that captures the code, stores the tokens in `DATA_DIR/accounts/<id>.json` (mode 600), and exits. Tokens refresh automatically when less than an hour remains.

## Consequences
- The owner's account takes the same path as any future account; no special-case token.
- The redirect URI is `http://localhost`, so only someone at this Mac can connect. Onboarding friends requires hosting with a public redirect URI and a clear disclosure of what the operator can access.
- A revoked or broken account is alerted and skipped; others keep running.
