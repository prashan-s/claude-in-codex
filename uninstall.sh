#!/usr/bin/env bash
# Remove what install.sh created. Job history in ~/.cic is kept unless you pass --purge.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
BIN_DIR="${CIC_BIN_DIR:-$HOME/.local/bin}"
SKILLS=(claude-in-codex claude-delegate claude-review claude-session claude-jobs claude-prompting claude-pair claude-council agent-bus claude-setup)

remove_link() {
  local path="$1"
  if [ -L "$path" ] && { [ "$(readlink "$path")" = "$ROOT/bin/cic" ] || [ "$(readlink "$path")" = "$ROOT/skills/${path##*/}" ]; }; then
    rm "$path"
    echo "removed $path"
  fi
}

remove_link "$BIN_DIR/cic"
for skill in "${SKILLS[@]}"; do
  remove_link "$CODEX_HOME/skills/$skill"
done
if [ -f "$CODEX_HOME/rules/claude-in-codex.rules" ]; then
  rm "$CODEX_HOME/rules/claude-in-codex.rules"
  echo "removed $CODEX_HOME/rules/claude-in-codex.rules"
fi
if [ "${1:-}" = "--purge" ]; then
  rm -rf "${CIC_HOME:-$HOME/.cic}"
  echo "removed ${CIC_HOME:-$HOME/.cic}"
fi
echo "Done. Restart Codex."
