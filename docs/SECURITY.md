# Security and repository boundaries

BacklotOS repositories contain source and test contracts, not production content.

Never commit:

- API keys, access tokens, cookies, credentials, or `.env` files.
- Episode video, audio, images, subtitles, voiceprints, or production source text.
- QA evidence containing private media frames.
- Append-only production ledgers, inbox/outbox messages, receipts, or runtime caches.
- Virtual environments, downloaded model weights, bundled FFmpeg binaries, wheels, or build output.

`scripts/verify-repository.sh` rejects common secret forms, media extensions, generated environments, and files larger than 5 MiB. This is a guardrail, not a substitute for review.

If a secret is ever committed, revoke it first, then remove it from Git history. Deleting only the latest file is insufficient.
