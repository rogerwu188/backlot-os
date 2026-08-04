#!/usr/bin/env bash

backlot_write_source_metadata() {
  local repo_root="$1"
  local install_root="$2"
  local version commit origin

  version="$(tr -d '[:space:]' < "$repo_root/VERSION")"
  commit="source-archive:v${version}"
  origin="${BACKLOT_SOURCE_ORIGIN:-https://github.com/rogerwu188/backlot-os.git}"

  if git -C "$repo_root" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    commit="$(git -C "$repo_root" rev-parse HEAD)"
    origin="$(git -C "$repo_root" remote get-url origin 2>/dev/null || printf '%s' "$origin")"
  fi

  mkdir -p "$install_root/source"
  printf '%s\n' "$repo_root" > "$install_root/source/repository-path"
  printf '%s\n' "$version" > "$install_root/source/version"
  printf '%s\n' "$commit" > "$install_root/source/git-commit"
  printf '%s\n' "$origin" > "$install_root/source/git-origin"
}
