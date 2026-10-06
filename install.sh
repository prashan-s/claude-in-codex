#!/usr/bin/env bash
# Install claude-in-codex: cic on PATH, the Codex skills, and the Codex exec-policy rule.
# Re-runnable; everything it creates is a symlink or a single rules file (see uninstall.sh).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
BIN_DIR="${CIC_BIN_DIR:-$HOME/.local/bin}"
SKILLS=(claude-in-codex)
LEGACY_SKILLS=(claude-delegate claude-review claude-session claude-jobs claude-prompting claude-pair claude-council agent-bus claude-setup)
INSTALL_RULES=1

for arg in "$@"; do
  case "$arg" in
    --no-rules) INSTALL_RULES=0 ;;
    -h|--help) echo "usage: install.sh [--no-rules]"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "cic needs Python 3.10 or newer as python3" >&2
  exit 1
fi
command -v claude >/dev/null 2>&1 || echo "warning: the claude CLI is not on PATH (https://code.claude.com/docs)"

mkdir -p "$BIN_DIR" "$CODEX_HOME/skills" "$CODEX_HOME/rules"
chmod +x "$ROOT/bin/cic" "$ROOT/install.sh" "$ROOT/uninstall.sh"

ln -sfn "$ROOT/bin/cic" "$BIN_DIR/cic"
echo "linked $BIN_DIR/cic"

for skill in "${LEGACY_SKILLS[@]}"; do
  target="$CODEX_HOME/skills/$skill"
  if [ -L "$target" ] && [ "$(readlink "$target")" = "$ROOT/skills/$skill" ]; then
    rm "$target"
    echo "removed legacy skill link $target"
  fi
done

for skill in "${SKILLS[@]}"; do
  target="$CODEX_HOME/skills/$skill"
  if [ -L "$target" ] && [ "$(readlink "$target")" != "$ROOT/skills/$skill" ]; then
    echo "skipped $skill: $target is a link owned by another installation" >&2
    continue
  fi
  if [ -e "$target" ] && [ ! -L "$target" ]; then
    echo "skipped $skill: $target exists and is not a symlink" >&2
    continue
  fi
  ln -sfn "$ROOT/skills/$skill" "$target"
done
echo "linked ${#SKILLS[@]} skills into $CODEX_HOME/skills"

if [ "$INSTALL_RULES" -eq 1 ]; then
  rule="$CODEX_HOME/rules/claude-in-codex.rules"
  sed -e "s#__CIC_BIN__#$BIN_DIR/cic#g" -e "s#__CIC_REPO_BIN__#$ROOT/bin/cic#g" \
    "$ROOT/codex/rules/claude-in-codex.rules" > "$rule"
  echo "installed exec-policy rule $rule"
  if command -v codex >/dev/null 2>&1; then
    if codex execpolicy check --rules "$rule" -- cic doctor | grep -q '"allow"'; then
      echo "verified: Codex will run 'cic ...' outside the sandbox"
    else
      echo "warning: 'codex execpolicy check' did not report allow for cic" >&2
    fi
  fi
else
  echo "skipped the exec-policy rule (--no-rules): Codex will ask before each cic run"
fi

case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) echo "note: add $BIN_DIR to PATH" ;;
esac

"$BIN_DIR/cic" doctor || true
echo "Done. Restart Codex so it loads the new skills and rules."
