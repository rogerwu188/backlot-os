---
name: qingshan-cloud-audit-runtime
description: Install, configure, and verify the Qingshan cloud review Agent runtime, including FFmpeg, RapidOCR, faster-whisper ASR, a VLM command adapter, and lip-sync evidence dependencies. Use when a cloud Audit Agent reports OCR, ASR, semantic visual review, or lip-sync as missing, NOT_RUN, or CAPABILITY_FAIL, or when deploying and accepting qingshan-review-agent in a new Linux or container environment.
---

# Qingshan cloud audit runtime

Install only into an isolated virtual environment or container. Never write credentials into the skill, logs, evidence JSON, or command line. Keep media read-only and state directories append-only.

## Workflow

1. Read `references/services.md` and select CPU or NVIDIA GPU deployment.
2. Run `scripts/runtime_check.py --json` before changing the environment. Preserve its output as pre-install evidence.
3. Install system packages using the official URLs and platform commands in the reference. Obtain approval first if the environment requires privileged package installation.
4. Install the Qingshan wheel plus Python runtimes into a dedicated environment:

   ```bash
   python3 -m venv .ai_review_env
   .ai_review_env/bin/pip install qingshan_review_agent-0.9.2-py3-none-any.whl
   .ai_review_env/bin/pip install rapidocr onnxruntime opencv-python-headless faster-whisper openai mediapipe
   ```

5. Configure service commands through environment variables. Keep secrets in the cloud secret manager:

   ```bash
   export QINGSHAN_WORKERS=4
   export QINGSHAN_PRODUCTION_ROOT=/srv/qingshan
   export QINGSHAN_IMAGE_ANALYSIS_COMMAND=/app/bin/vlm_audit_adapter
   export QINGSHAN_ASR_COMMAND=/app/bin/asr_adapter
   export QINGSHAN_LIPSYNC_COMMAND=/app/bin/lipsync_audit_adapter
   ```

6. Require every adapter to bind evidence to the candidate's exact SHA-256. Reject mismatched or missing provenance as `CAPABILITY_FAIL`; never count it as content failure or PASS.
7. Run `scripts/runtime_check.py --json --require-all`, `qingshan-review health`, the packaged unit tests, then immutable real-media positive and negative reviews.
8. Mark overall support only after OCR, ASR, VLM, and lip-sync show actual execution evidence. If media is unavailable, report `BLOCKED_NO_MEDIA`.

## Required adapter behavior

- ASR: emit segment and word timestamps, language, confidence, media path, candidate SHA-256, model/version, and rollback metadata.
- VLM: accept candidate path/SHA and review rubric; emit per-check status, regions or time/frame ranges, confidence, evidence, and repair advice.
- Lip-sync: combine ASR speech intervals with visible-face mouth motion and an audio-visual synchronization score. ASR timestamps alone are insufficient.
- All adapters: deterministic JSON, timeout/error evidence, no publishing or deletion.

Do not change a missing capability into optional merely to obtain PASS. Do not claim “100% restored” until the real-media acceptance contract is satisfied.
