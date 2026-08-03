#!/usr/bin/env bash

# Runtime-profile helpers shared by doctor and deployment acceptance scripts.
# This file intentionally reports configuration names only; it never prints
# credential values.

backlot_detect_runtime_profile() {
  local requested="${BACKLOT_RUNTIME_PROFILE:-auto}"
  case "$requested" in
    storyclaw|standalone)
      printf '%s\n' "$requested"
      return 0
      ;;
    auto|"")
      ;;
    *)
      printf 'invalid BACKLOT_RUNTIME_PROFILE: %s\n' "$requested" >&2
      return 2
      ;;
  esac

  if [[ -n "${STORYCLAW_DEVICE_ID:-}" || -n "${STORYCLAW_RUNTIME:-}" || \
        -n "${OPENCLAW_HOME:-}" || -d "${HOME}/.openclaw" ]]; then
    printf '%s\n' storyclaw
  else
    printf '%s\n' standalone
  fi
}

backlot_report_model_configuration() {
  local profile="$1"
  local install_root="${2:-${BACKLOT_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/backlotos}}"
  local host_model="${BACKLOT_HOST_MODEL:-storyclaw-managed}"

  if [[ "$profile" == "storyclaw" ]]; then
    printf 'PASS host-model-runtime:%s\n' "$host_model"
    printf '%s\n' \
      'NOT_APPLICABLE OPENAI_API_KEY reason=host_managed_storyclaw_model_runtime'
  elif [[ -n "${OPENAI_API_KEY:-}" ]]; then
    printf '%s\n' 'CONFIGURED OPENAI_API_KEY'
  else
    printf '%s\n' 'OPTIONAL_NOT_CONFIGURED OPENAI_API_KEY reason=direct_api_adapter_only'
  fi

  if [[ -n "${QINGSHAN_IMAGE_ANALYSIS_COMMAND:-}" ]]; then
    printf '%s\n' 'CONFIGURED QINGSHAN_IMAGE_ANALYSIS_COMMAND'
  elif [[ "$profile" == "storyclaw" ]]; then
    printf '%s\n' \
      'OPTIONAL_NOT_CONFIGURED QINGSHAN_IMAGE_ANALYSIS_COMMAND reason=host_multimodal_available_but_cli_bridge_not_configured'
  else
    printf '%s\n' 'OPTIONAL_NOT_CONFIGURED QINGSHAN_IMAGE_ANALYSIS_COMMAND'
  fi

  if [[ -n "${QINGSHAN_OCR_PYTHON:-}" ]]; then
    printf '%s\n' 'CONFIGURED QINGSHAN_OCR_PYTHON'
  elif [[ -x "$install_root/venv/bin/python" ]] && \
       "$install_root/venv/bin/python" -c 'import cv2, onnxruntime, rapidocr_onnxruntime' >/dev/null 2>&1; then
    printf '%s\n' 'PASS ocr-runtime:rapidocr-onnx source=backlotos-venv'
    printf '%s\n' \
      'NOT_APPLICABLE QINGSHAN_OCR_PYTHON reason=bundled_ocr_runtime_uses_review_agent_interpreter'
  else
    printf '%s\n' 'CAPABILITY_NOT_CONFIGURED ocr-runtime reason=rapidocr_dependencies_missing'
  fi
}
