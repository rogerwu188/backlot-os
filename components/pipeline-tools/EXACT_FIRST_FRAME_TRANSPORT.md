# Exact-first-frame transport

`EXACT_FIRST_FRAME` is a provider transport contract, not an ordinary visual
reference role. A paid task carrying this role is admitted only when all of the
following are true:

- model is `seedance-2.0-fast` and provider-native resolution is `720p`;
- the request uses `/api/v1/generation/image-to-video` and the image is sent in
  the native `start_frame` field;
- the same image is absent from Omni `images[]`, and no Omni-only audio binding
  is attached to the task;
- source-file SHA-256 and decoded RGB SHA-256 are both bound before encoding;
- the durable transaction binds the transport endpoint and full contract
  fingerprint before the paid request.

Native `start_frame` preserves semantic intent, but the provider does not
promise that the decoded output frame is pixel-identical. Every harvested clip
must therefore run `exact_first_frame_post_harvest_gate.py`. It compares decoded
frame 0 to the source authority and compares the frame-0-to-frame-1 transition
using decoded frame 0 and decoded frame 1 against the clip's following motion
baseline. Authority-to-decoded-frame-1 is retained only as a separately named
composite diagnostic; it cannot replace either hard gate or affect the gate's
overall status. Human review still owns duplicate silhouette, flash, pose/crop
jump, and prop owner/count/transfer judgments.

The gate is read-only. A failed clip is retained as failed evidence. Prepending
or replacing one frame is forbidden as an automatic repair because it can hide
a discontinuity without fixing the generated motion.
