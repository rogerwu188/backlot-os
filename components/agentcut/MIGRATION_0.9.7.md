# AgentCut 0.9.6 → 0.9.7

0.9.7 is additive. It preserves the accepted 0.9.5 production baseline and the 0.9.6 CL2X-352/353 long-take and first/last-frame contracts. Existing character records are not rewritten or invalidated automatically; the CL2X-358 gate applies when a new canonical card is explicitly submitted through its new methods.

Safe activation:

1. Keep the currently activated production 0.9.6 environment unchanged while Task2 reviews the package.
2. Install the 0.9.7 wheel in a separate environment with the same qingshan wrapper.
3. Compare canonical NDJSON health capabilities. After removing only `longTake`, `giggleFirstLast`, and `characterCanonicalCard`, the object must equal the current 0.9.5 object.
4. Run all source and installed-wheel tests and the read-only qingshan regression receipts.
5. Generate a prompt from the structured description, create the card outside production assets, attach independent layout/identity evidence, and run `character-card-validate`.
6. Run `character-card-admit` without `--write` first. Write only to a staged registry and promote through the normal asset-review process.

The validator accepts one PNG, JPEG, or WebP image with an actual 16:9 stream. It hard-fails missing front/side/back full-body views, incorrect order or bounds, cropped bodies, absent or failed evidence, inconsistent identity attributes, and any unconfirmed forbidden-content constraint. No Seedance binding is emitted for a rejected card.

Rollback is package-only: discard the isolated 0.9.7 environment or reinstall the retained 0.9.6 wheel (with 0.9.5 retained as the earlier accepted baseline). Registry writes are explicit, atomic, and directed to a caller-provided output, so the original registry and media remain untouched.
