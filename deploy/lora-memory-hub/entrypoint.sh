#!/bin/sh
set -eu

checkout="${BACKLOTOS_LORA_GITHUB_CHECKOUT:-/data/backlot-os}"
remote="${BACKLOTOS_LORA_GITHUB_REMOTE:-https://github.com/rogerwu188/backlot-os.git}"

if [ -n "${BACKLOTOS_LORA_GITHUB_TOKEN:-}" ]; then
  basic="$(printf 'x-access-token:%s' "$BACKLOTOS_LORA_GITHUB_TOKEN" | base64 | tr -d '\n')"
  export GIT_CONFIG_COUNT=1
  export GIT_CONFIG_KEY_0=http.extraHeader
  export GIT_CONFIG_VALUE_0="Authorization: Basic $basic"
fi

if [ ! -d "$checkout/.git" ]; then
  mkdir -p "$(dirname "$checkout")"
  git clone "$remote" "$checkout"
fi

git -C "$checkout" config user.name "BacklotOS Memory Hub"
git -C "$checkout" config user.email "backlotos-memory-hub@users.noreply.github.com"
export BACKLOTOS_LORA_GITHUB_CHECKOUT="$checkout"

exec python /app/lora_memory_hub.py --host 0.0.0.0 --port 8080
