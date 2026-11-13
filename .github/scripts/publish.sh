#!/usr/bin/env bash
# Publishes a one-line status into a repo file so it can be read live from outside.
# Requires: GH_TOKEN, GITHUB_REPOSITORY, jq, curl
# Optional: STATUS_FILE (default: status.txt) - used to keep parallel slots separate.
publish() {
  local b64 sha file
  file="${STATUS_FILE:-status.txt}"
  b64=$(printf '%s' "$1" | base64 -w0)
  sha=$(curl -s -H "Authorization: Bearer $GH_TOKEN" \
        "https://api.github.com/repos/$GITHUB_REPOSITORY/contents/$file" | jq -r '.sha // empty')
  if [ -n "$sha" ]; then
    curl -s -o /dev/null -X PUT -H "Authorization: Bearer $GH_TOKEN" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/$GITHUB_REPOSITORY/contents/$file" \
      -d "{\"message\":\"status\",\"content\":\"$b64\",\"sha\":\"$sha\"}"
  else
    curl -s -o /dev/null -X PUT -H "Authorization: Bearer $GH_TOKEN" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/$GITHUB_REPOSITORY/contents/$file" \
      -d "{\"message\":\"status\",\"content\":\"$b64\"}"
  fi
}
