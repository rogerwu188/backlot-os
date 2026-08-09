#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "$repo_root/scripts/lib/runtime-profile.sh"

install_root="${BACKLOT_INSTALL_DIR:-${XDG_DATA_HOME:-$HOME/.local/share}/backlotos}"
failed=0

source_version="$(tr -d '[:space:]' < "$repo_root/VERSION")"
installed_version_file="$install_root/source/version"
if [[ -f "$installed_version_file" ]] && [[ "$(tr -d '[:space:]' < "$installed_version_file")" == "$source_version" ]]; then
  echo "PASS installed-version:$source_version"
else
  installed_version="MISSING"
  if [[ -f "$installed_version_file" ]]; then
    installed_version="$(tr -d '[:space:]' < "$installed_version_file")"
  fi
  echo "FAIL installed-version:source=$source_version installed=$installed_version"
  failed=1
fi

for parity_artifact in \
  submit_giggle_image_manifest.py \
  giggle_api_client.py \
  seedance2_prompt_compiler.py \
  shot_package_completion_gate.py \
  production_video_submission_gate.py \
  provider_video_capability_gate.py \
  provider_video_capabilities.json; do
  source_artifact="$repo_root/components/pipeline-tools/$parity_artifact"
  installed_artifact="$install_root/share/pipeline-tools/$parity_artifact"
  if [[ -f "$installed_artifact" ]] && cmp -s "$source_artifact" "$installed_artifact"; then
    echo "PASS installed-artifact:$parity_artifact"
  else
    echo "FAIL installed-artifact:$parity_artifact differs-from-source"
    failed=1
  fi
done

check_command() {
  if command -v "$1" >/dev/null 2>&1; then
    echo "PASS command:$1"
  else
    echo "FAIL command:$1"
    failed=1
  fi
}

check_command git
check_command ffmpeg
check_command ffprobe
check_command node

if [[ -x "$install_root/venv/bin/qingshan-review" ]]; then
  echo "PASS review-agent"
  "$install_root/venv/bin/qingshan-review" health
else
  echo "FAIL review-agent"
  failed=1
fi

if [[ -x "$install_root/venv/bin/agentcut" ]]; then
  echo "PASS agentcut"
  "$install_root/venv/bin/agentcut" health
else
  echo "FAIL agentcut"
  failed=1
fi

if [[ -x "$install_root/venv/bin/claude-story-agent" ]]; then
  echo "PASS story-agent"
  "$install_root/venv/bin/claude-story-agent" health
else
  echo "FAIL story-agent"
  failed=1
fi

if [[ -x "$install_root/venv/bin/backlotos" ]]; then
  echo "PASS launcher"
  "$install_root/venv/bin/backlotos" health
else
  echo "FAIL launcher"
  failed=1
fi

if [[ -x "$install_root/venv/bin/backlotos-producer-command" ]]; then
  echo "PASS producer-supervisor-agent"
  printf '%s\n' '{"verb":"health"}' | "$install_root/venv/bin/backlotos-producer-command"
else
  echo "FAIL producer-supervisor-agent"
  failed=1
fi

if [[ -x "$install_root/venv/bin/backlotos-pipeline-command" ]]; then
  echo "PASS pipeline-semantic-adapter"
  printf '%s\n' '{"verb":"health"}' | \
    BACKLOT_PIPELINE_TOOLS_DIR="$install_root/share/pipeline-tools" "$install_root/venv/bin/backlotos-pipeline-command"
else
  echo "FAIL pipeline-semantic-adapter"
  failed=1
fi

runtime_profile="$(backlot_detect_runtime_profile)" || exit $?
echo "PASS runtime-profile:$runtime_profile"
backlot_report_model_configuration "$runtime_profile" "$install_root"

for production_gate in \
  action_prompt_pipeline_cli.py \
  action_spatial_feasibility_gate.py \
  generation_prompt_optimizer.py \
  bgm_authenticity_gate.py \
  continuous_task_lane_dispatcher.py \
  shot_package_completion_gate.py \
  submit_giggle_image_manifest.py \
  retry_strategy_change_gate.py \
  task_lane_global_wait_gate.py \
  provider_video_capability_gate.py \
  provider_video_capabilities.json \
  production_video_submission_gate.py \
  local_lora_memory_sync.py; do
  if [[ -f "$repo_root/components/pipeline-tools/$production_gate" ]]; then
    echo "PASS production-gate:$production_gate"
  else
    echo "FAIL production-gate:$production_gate"
    failed=1
  fi
done

if [[ -f "$install_root/config/lora-auto-sync.enabled" ]]; then
  echo "PASS lora-memory-auto-sync:enabled"
else
  echo "NOT_CONFIGURED lora-memory-auto-sync:run-current-installer-to-enable"
fi

exit "$failed"
