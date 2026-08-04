#!/usr/bin/env bash

backlot_python_is_supported() {
  local candidate="$1"
  local version major minor

  command -v "$candidate" >/dev/null 2>&1 || return 1
  version="$("$candidate" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)" || return 1
  IFS=. read -r major minor <<< "$version"
  [[ "$major" == "3" && "$minor" -ge 10 && "$minor" -le 12 ]]
}

backlot_select_python() {
  local requested="${BACKLOT_PYTHON:-}"
  local candidate

  if [[ -n "$requested" ]]; then
    backlot_python_is_supported "$requested" || return 1
    printf '%s\n' "$requested"
    return 0
  fi

  for candidate in python3.12 python3.11 python3.10 python3; do
    if backlot_python_is_supported "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}
