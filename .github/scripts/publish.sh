#!/usr/bin/env bash
# Writes a one-line "KEY=VALUE|KEY=VALUE" status file into the repo through the
# GitHub Contents API, so the desktop app can read live state from outside.
#
# Requires : GH_TOKEN, GITHUB_REPOSITORY, jq, curl, base64
# Optional : STATUS_FILE  -> per-slot file name (default: status.txt)
#
# Usage    : source publish.sh
#            publish_set STATE=ready IP=100.x.y.z SLOT=1 RUN=123
#            publish_raw "STATE=ready|IP=..."      # overwrite whole line

_api_url() {
  echo "https://api.github.com/repos/${GITHUB_REPOSITORY}/contents/${STATUS_FILE:-status.txt}"
}

_api_get() {
  curl -s -H "Authorization: Bearer ${GH_TOKEN}" \
       -H "Accept: application/vnd.github+json" "$(_api_url)"
}

# publish_raw "<line>"  -> replace file content entirely
publish_raw() {
  local file="${STATUS_FILE:-status.txt}" b64 sha
  b64=$(printf '%s' "$1" | base64 -w0)
  sha=$(_api_get | jq -r '.sha // empty' 2>/dev/null)
  if [ -n "$sha" ]; then
    curl -s -o /dev/null -X PUT -H "Authorization: Bearer ${GH_TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/${GITHUB_REPOSITORY}/contents/${file}" \
      -d "{\"message\":\"status\",\"content\":\"${b64}\",\"sha\":\"${sha}\"}"
  else
    curl -s -o /dev/null -X PUT -H "Authorization: Bearer ${GH_TOKEN}" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/${GITHUB_REPOSITORY}/contents/${file}" \
      -d "{\"message\":\"status\",\"content\":\"${b64}\"}"
  fi
}

# publish_set KEY=VALUE ...  -> merge into the existing line, keeping other keys
publish_set() {
  local cur tmp pair k v
  tmp=$(mktemp)
  # ملاحظة: محتوى GitHub API base64 قد يحتوي \r\n — يجب إزالة كليهما
  cur=$(_api_get | jq -r '.content // empty' 2>/dev/null | tr -d '\r\n' | base64 -d 2>/dev/null || true)
  printf '%s' "$cur" | tr '|' '\n' | grep -E '^[A-Z0-9_]+=' > "$tmp" || true
  for pair in "$@"; do
    k=${pair%%=*}
    v=${pair#*=}
    grep -vE "^${k}=" "$tmp" > "${tmp}.n" 2>/dev/null || true
    mv "${tmp}.n" "$tmp"
    printf '%s=%s\n' "$k" "$v" >> "$tmp"
  done
  publish_raw "$(paste -sd'|' "$tmp")"
  rm -f "$tmp" "${tmp}.n"
}
