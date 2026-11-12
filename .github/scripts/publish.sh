#!/usr/bin/env bash
# ينشر نصًا في status.txt داخل المستودع حتى يمكن قراءته لحظيًا من الخارج.
# يحتاج: GH_TOKEN, GITHUB_REPOSITORY, jq, curl
publish() {
  local b64 sha
  b64=$(printf '%s' "$1" | base64 -w0)
  sha=$(curl -s -H "Authorization: Bearer $GH_TOKEN" \
        "https://api.github.com/repos/$GITHUB_REPOSITORY/contents/status.txt" | jq -r '.sha // empty')
  if [ -n "$sha" ]; then
    curl -s -o /dev/null -X PUT -H "Authorization: Bearer $GH_TOKEN" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/$GITHUB_REPOSITORY/contents/status.txt" \
      -d "{\"message\":\"status\",\"content\":\"$b64\",\"sha\":\"$sha\"}"
  else
    curl -s -o /dev/null -X PUT -H "Authorization: Bearer $GH_TOKEN" \
      -H "Accept: application/vnd.github+json" \
      "https://api.github.com/repos/$GITHUB_REPOSITORY/contents/status.txt" \
      -d "{\"message\":\"status\",\"content\":\"$b64\"}"
  fi
}
