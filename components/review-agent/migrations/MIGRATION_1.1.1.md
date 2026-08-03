# Review Agent 1.1.1

- The official package now installs RapidOCR, ONNX Runtime, and OpenCV.
- OCR subprocesses prefer the Review Agent's own Python interpreter.
- Normal BacklotOS installations no longer require
  `QINGSHAN_OCR_PYTHON`; the variable remains a compatibility override.
- StoryClaw host-model access and unattended visual-command execution remain
  separate capabilities. No visual capability is marked PASS without an
  exact-SHA adapter result.
