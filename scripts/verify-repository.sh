#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

bad=0
if find . -path ./.git -prune -o -type f -size +5M -print | grep -q .; then
  echo "FAIL files larger than 5 MiB are present"
  find . -path ./.git -prune -o -type f -size +5M -print
  bad=1
fi

if find . -path ./.git -prune -o -type f \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.wav' -o -iname '*.mp3' -o -iname '*.png' -o -iname '*.jpg' -o -name '.env' \) -print | grep -q .; then
  echo "FAIL media or local environment files are present"
  bad=1
fi

secret_pattern='(sk-[A-Za-z0-9_-]{20,}|gh[oprsu]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----)'
if git grep -I -E "$secret_pattern" -- . ':!scripts/verify-repository.sh' >/dev/null 2>&1; then
  echo "FAIL a probable credential was detected (values withheld)"
  bad=1
fi

python3 -m compileall -q components/review-agent/qingshan_review components/agentcut/agentcut components/story-agent/src/claude_story_agent components/factory-runtime components/pipeline-tools/action_prompt_pipeline_cli.py components/pipeline-tools/action_spatial_feasibility_gate.py components/pipeline-tools/generation_prompt_optimizer.py components/pipeline-tools/bgm_authenticity_gate.py components/pipeline-tools/local_lora_memory_sync.py
echo "Repository verification completed"
exit "$bad"
