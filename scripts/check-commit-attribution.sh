#!/usr/bin/env bash
# Rejects commits authored, committed or co-authored by Claude / Anthropic.
# Claude may help write a change, but every commit must carry a human teammate's identity.
#
#   check-commit-attribution.sh --message <file>   # commit-msg hook: the commit being made
#   check-commit-attribution.sh --range <a>..<b>   # CI: every commit in a range
set -euo pipefail

ident_pattern='(^|[[:space:]<])claude([[:space:]>]|$)|anthropic\.com'
message_pattern='^(co-authored-by:.*(claude|anthropic)|claude-session:)|generated with \[claude code\]'

failures=0

fail() {
  echo "commit attribution: $1" >&2
  failures=$((failures + 1))
}

check_ident() { # <label> <"Name <email>">
  if grep -qiE "$ident_pattern" <<<"$2"; then
    fail "$1 is '$2'. Set your own identity: git config user.name \"Your Name\" && git config user.email \"you@example.com\""
  fi
}

check_message() { # <label> <message text>
  local hits
  hits="$(grep -iE "$message_pattern" <<<"$2" || true)"
  if [[ -n "$hits" ]]; then
    fail "$1 has a Claude attribution line; remove it:"$'\n'"$hits"
  fi
}

case "${1:-}" in
  --message)
    [[ -f "${2:-}" ]] || { echo "usage: $0 --message <file>" >&2; exit 2; }
    # git var honours GIT_AUTHOR_* / GIT_COMMITTER_* overrides as well as git config.
    check_ident "commit author" "$(git var GIT_AUTHOR_IDENT | sed -E 's/ [0-9]+ [+-][0-9]{4}$//')"
    check_ident "committer" "$(git var GIT_COMMITTER_IDENT | sed -E 's/ [0-9]+ [+-][0-9]{4}$//')"
    check_message "commit message" "$(grep -v '^#' "$2")"
    ;;
  --range)
    [[ -n "${2:-}" ]] || { echo "usage: $0 --range <a>..<b>" >&2; exit 2; }
    while read -r sha; do
      [[ -n "$sha" ]] || continue
      short="${sha:0:9}"
      check_ident "$short author" "$(git log -1 --format='%an <%ae>' "$sha")"
      check_ident "$short committer" "$(git log -1 --format='%cn <%ce>' "$sha")"
      check_message "$short message" "$(git log -1 --format='%B' "$sha")"
    done < <(git rev-list --no-merges "$2")
    ;;
  *)
    echo "usage: $0 --message <file> | --range <a>..<b>" >&2
    exit 2
    ;;
esac

if ((failures > 0)); then
  echo "commit attribution: rejected ($failures problem(s)). See CONTRIBUTING.md." >&2
  exit 1
fi
