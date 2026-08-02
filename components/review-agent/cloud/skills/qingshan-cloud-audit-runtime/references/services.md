# Official services and installation sources

## Core media runtime

- FFmpeg downloads and packages: https://ffmpeg.org/download.html
- Ubuntu/Debian: `apt-get update && apt-get install -y ffmpeg python3-venv`

Verify with `ffmpeg -version` and `ffprobe -version`.

## OCR

- RapidOCR installation: https://rapidai.github.io/RapidOCRDocs/main/install_usage/rapidocr/install/
- RapidOCR repository: https://github.com/RapidAI/RapidOCR
- Install: `python -m pip install rapidocr onnxruntime opencv-python-headless`
- Verify: `rapidocr check`

Use RapidOCR rather than requiring Tesseract. If legacy policy explicitly requires Tesseract, use https://tesseract-ocr.github.io/tessdoc/Installation.html and install the `chi_sim` trained data, but do not run both engines and double-count the same finding.

## ASR

Preferred self-hosted runtime:

- faster-whisper official repository: https://github.com/SYSTRAN/faster-whisper
- PyPI: https://pypi.org/project/faster-whisper/
- Install: `python -m pip install faster-whisper`

Use a pinned model revision in production. For Chinese dialogue, return word timestamps when the model supports them and always preserve raw segments.

Managed alternative:

- OpenAI speech-to-text guide: https://developers.openai.com/api/docs/guides/speech-to-text
- Official Python SDK: https://github.com/openai/openai-python

Store API credentials only in the cloud secret manager/environment. Never add them to evidence or the skill.

## Semantic visual review

- OpenAI images and vision guide: https://developers.openai.com/api/docs/guides/images-vision
- Official Python SDK: https://github.com/openai/openai-python

The adapter must use image inputs and structured output, then normalize the response into the Qingshan exact-SHA evidence contract. Sampling video frames is the adapter's responsibility; include frame number/time and region for every finding.

## Lip-sync evidence

Use both face/mouth motion and audio-visual synchronization:

- MediaPipe Face Landmarker Python guide: https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker/python
- MediaPipe repository: https://github.com/google-ai-edge/mediapipe
- Wav2Lip/SyncNet reference implementation and evaluation: https://github.com/Rudrabha/Wav2Lip

MediaPipe alone measures visible mouth motion but not phoneme alignment. SyncNet alone does not establish the intended speaker identity. A production PASS requires both signals plus ASR/role timing evidence.

## Acceptance

Record versions, model revisions, candidate SHA-256, command exit status, runtime duration, and output evidence SHA-256. Test at least:

- clear Chinese speech with a visible synchronized speaker;
- visible speaker with intentionally shifted audio;
- off-screen narration where lip-sync is `NOT_APPLICABLE`;
- OCR-free frame and persistent forbidden text;
- missing model/runtime returning `CAPABILITY_FAIL`.
