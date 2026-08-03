# Review Agent 1.2.0

- Adds `backlotos-storyclaw-image-analysis`, an exact-SHA StoryClaw GPT‑5.5
  visual adjudication adapter using the Chat Completions protocol.
- Credentials are read only from `BACKLOT_STORYCLAW_API_KEY` in the deployment
  environment. They are never accepted through review requests or emitted.
- Review Agent auto-selects the bundled adapter when the key is present.
- Missing credentials remain a truthful capability failure; no image is passed
  merely because the host Agent itself has multimodal access.
