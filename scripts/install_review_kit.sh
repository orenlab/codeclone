#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
KIT_ROOT="$REPO_ROOT/tools/review"
CLAUDE_REVIEW="$REPO_ROOT/.claude/review"
CLAUDE_AGENTS="$REPO_ROOT/.claude/agents"
# The review-change skill lives natively under .claude/skills/review-change/ and is
# not managed by this installer (it has no tracked source under tools/review).

mkdir -p "$CLAUDE_REVIEW" "$CLAUDE_AGENTS"

link_or_copy() {
  local src="$1"
  local dest="$2"
  if [[ -e "$dest" || -L "$dest" ]]; then
    rm -rf "$dest"
  fi
  ln -s "$src" "$dest"
}

link_or_copy "$KIT_ROOT/policy.yaml" "$CLAUDE_REVIEW/policy.yaml"
link_or_copy "$KIT_ROOT/rubric.md" "$CLAUDE_REVIEW/rubric.md"
link_or_copy "$KIT_ROOT/schemas/artifact-v3.schema.json" "$CLAUDE_REVIEW/artifact-schema.json"
link_or_copy "$KIT_ROOT/review-change.sh" "$CLAUDE_REVIEW/review-change.sh"

for agent in review-coordinator review-scout surface-reviewer critical-reviewer; do
  link_or_copy "$KIT_ROOT/agents/${agent}.md" "$CLAUDE_AGENTS/${agent}.md"
done

chmod +x "$KIT_ROOT/review-change.sh" "$CLAUDE_REVIEW/review-change.sh"

printf 'Review kit installed into .claude/ (symlinks to tools/review; skill is native under .claude/skills/review-change).\n'
