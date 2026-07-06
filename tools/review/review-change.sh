#!/usr/bin/env bash
set -euo pipefail

KIT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$KIT_ROOT" rev-parse --show-toplevel 2>/dev/null || pwd)"

usage() {
  cat <<'USAGE'
Usage:
  tools/review/review-change.sh --commit SHA [options]
  tools/review/review-change.sh --range BASE..HEAD [options]
  tools/review/review-change.sh --release BASE..HEAD [options]

Options:
  --profile economy|balanced|thorough  Cost/assurance profile (default: balanced)
  --incremental-from SHA               Reuse units unchanged since prior head
  --dry-run                            Build packet and print routing only
  --validate                           Validate packet against v3 schema
  --execute-verification               Run planned verification commands
  --max-agents N                       Override subagent cap
  --max-concurrency N                  Override parallel subagent cap
  --auto-fanout                        Do not ask again before launching subagents
  --yes                                Skip the initial paid-run confirmation
  --no-transcript                      Disable terminal transcript recording

Behavior:
  - Canonical kit lives under tools/review/.
  - Preflight runs surface coverage and schema validation when --validate is set.
  - No repository source file may be changed.
USAGE
}

if [[ $# -lt 2 ]]; then
  usage >&2
  exit 2
fi

case "$1" in
  --commit) mode="commit" ;;
  --range) mode="range" ;;
  --release) mode="release" ;;
  *) usage >&2; exit 2 ;;
esac

target="$2"
shift 2

profile="balanced"
incremental_from=""
dry_run=false
validate_packet=false
execute_verification=false
max_agents=""
max_concurrency=""
auto_fanout=false
assume_yes=false
record_transcript=true

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      profile="$2"; shift
      ;;
    --incremental-from)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      incremental_from="$2"; shift
      ;;
    --dry-run) dry_run=true ;;
    --validate) validate_packet=true ;;
    --execute-verification) execute_verification=true ;;
    --max-agents)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      max_agents="$2"; shift
      ;;
    --max-concurrency)
      [[ $# -ge 2 ]] || { usage >&2; exit 2; }
      max_concurrency="$2"; shift
      ;;
    --auto-fanout) auto_fanout=true ;;
    --yes) assume_yes=true ;;
    --no-transcript) record_transcript=false ;;
    *) usage >&2; exit 2 ;;
  esac
  shift
done

case "$profile" in
  economy) default_agents=8; default_concurrency=4 ;;
  balanced) default_agents=12; default_concurrency=4 ;;
  thorough) default_agents=20; default_concurrency=6 ;;
  *)
    printf 'Unknown profile: %s\n' "$profile" >&2
    exit 2
    ;;
esac

max_agents="${max_agents:-$default_agents}"
max_concurrency="${max_concurrency:-$default_concurrency}"

for required in git; do
  if ! command -v "$required" >/dev/null 2>&1; then
    printf 'Required command not found: %s\n' "$required" >&2
    exit 127
  fi
done

if command -v uv >/dev/null 2>&1; then
  python_runner=(uv run python)
else
  if ! command -v python3 >/dev/null 2>&1; then
    printf 'Required command not found: python3 (or uv for project deps)\n' >&2
    exit 127
  fi
  python_runner=(python3)
fi

cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT/tools/review${PYTHONPATH:+:$PYTHONPATH}"

if ! "${python_runner[@]}" -m review_kit.cli check-coverage; then
  printf 'Surface coverage check failed; update tools/review/policy.yaml before review.\n' >&2
  exit 8
fi

if [[ "$dry_run" == true ]]; then
  "${python_runner[@]}" -m review_kit.cli dry-run "$mode" "$target" --profile "$profile"
  exit 0
fi

review_root=".codeclone/reviews"
mkdir -p "$review_root"
packet_tmp="$review_root/pending.packet.json"

build_args=(build-packet "$mode" "$target" --out "$packet_tmp" --profile "$profile")
if [[ -n "$incremental_from" ]]; then
  build_args+=(--incremental-from "$incremental_from")
fi
if [[ "$execute_verification" == true ]]; then
  build_args+=(--execute-verification)
fi
if [[ "$validate_packet" == true ]]; then
  build_args+=(--validate)
fi

if ! "${python_runner[@]}" -m review_kit.cli "${build_args[@]}"; then
  printf 'Failed to build review packet.\n' >&2
  exit 1
fi
if [[ ! -f "$packet_tmp" ]]; then
  printf 'Review packet was not written: %s\n' "$packet_tmp" >&2
  exit 1
fi

read_packet_field() {
  "${python_runner[@]}" -c "$1" "$packet_tmp"
}

base_sha="$(read_packet_field 'import json,sys; print(json.load(open(sys.argv[1]))["target"]["base_sha"])')"
head_sha="$(read_packet_field 'import json,sys; print(json.load(open(sys.argv[1]))["target"]["head_sha"])')"
subject="$(read_packet_field 'import json,sys; p=json.load(open(sys.argv[1])); print(p["target"].get("subject") or "")')"
changed_count="$(read_packet_field 'import json,sys; p=json.load(open(sys.argv[1])); print(len(p.get("change",{}).get("files",[])))')"
commit_count="$(read_packet_field 'import json,sys; p=json.load(open(sys.argv[1])); print(len(p.get("change",{}).get("commits",[])))')"
large_review="$(read_packet_field 'import json,sys; p=json.load(open(sys.argv[1])); print(str(bool(p.get("change",{}).get("review_scale",{}).get("large",False))).lower())')"
decompose_recommended="$(read_packet_field 'import json,sys; p=json.load(open(sys.argv[1])); print(str(bool(p.get("routing",{}).get("decomposed",False))).lower())')"
coordinator_model="$(read_packet_field 'import json,sys; p=json.load(open(sys.argv[1])); print(p.get("routing",{}).get("coordinator_model","opus"))')"
cost_weight="$(read_packet_field 'import json,sys; p=json.load(open(sys.argv[1])); print(p.get("cost_estimate",{}).get("relative_weight",0))')"
unmapped_count="$(read_packet_field 'import json,sys; p=json.load(open(sys.argv[1])); print(len(p.get("change",{}).get("unmapped_paths",[])))')"
unit_count="$(read_packet_field 'import json,sys; p=json.load(open(sys.argv[1])); print(len(p.get("review_units",[])))')"
release_enabled="$(read_packet_field 'import json,sys; p=json.load(open(sys.argv[1])); print(str(bool(p.get("release",{}).get("enabled",False))).lower())')"
changed_lines="$(read_packet_field 'import json,sys; p=json.load(open(sys.argv[1])); s=p.get("change",{}).get("stats",{}); print(int(s.get("insertions",0))+int(s.get("deletions",0)))')"

base_short="${base_sha:0:12}"
head_short="${head_sha:0:12}"
case "$mode" in
  commit) artifact_stem="${head_sha}" ;;
  range) artifact_stem="${base_short}--${head_short}.range" ;;
  release) artifact_stem="${base_short}--${head_short}.release" ;;
esac

packet="$review_root/${artifact_stem}.packet.json"
mv "$packet_tmp" "$packet"

decomposed=false
if [[ "$decompose_recommended" == true ]]; then
  decomposed=true
fi

if ! command -v claude >/dev/null 2>&1; then
  printf '\nPacket built without Claude launcher (claude not found).\n'
  printf 'Packet: %s\n' "$packet"
  exit 0
fi

if [[ "$decomposed" == true ]]; then
  artifact_dir="$review_root/${artifact_stem}"
  mkdir -p "$artifact_dir/units"
  review_md="$artifact_dir/aggregate.review.md"
  transcript="$artifact_dir/session.typescript"
  prompt="/review-change --${mode} ${target} --packet ${packet} --artifact-dir ${artifact_dir} --profile ${profile} --max-agents ${max_agents} --max-concurrency ${max_concurrency} --auto-fanout ${auto_fanout}"
else
  artifact_dir=""
  review_md="$review_root/${artifact_stem}.review.md"
  transcript="$review_root/${artifact_stem}.review.typescript"
  prompt="/review-change --${mode} ${target} --packet ${packet} --review-md ${review_md} --profile ${profile} --max-agents ${max_agents} --max-concurrency ${max_concurrency} --auto-fanout ${auto_fanout}"
fi

printf '\n'
printf 'CodeClone independent review (kit v3)\n'
printf '────────────────────────────────────────────────────────────\n'
printf 'Mode:             %s\n' "$mode"
printf 'Target:           %s\n' "$target"
printf 'Base SHA:         %s\n' "$base_sha"
printf 'Head SHA:         %s\n' "$head_sha"
printf 'Subject:          %s\n' "${subject:-<range/release review>}"
printf 'Files / commits:  %s / %s\n' "$changed_count" "$commit_count"
printf 'Changed lines:    %s\n' "$changed_lines"
printf 'Large review:     %s\n' "$large_review"
printf 'Decompose:        %s\n' "$decompose_recommended"
printf 'Review units:     %s\n' "$unit_count"
printf 'Release vectors:  %s\n' "$release_enabled"
printf 'Unmapped paths:   %s\n' "$unmapped_count"
printf 'Cost weight:      %s\n' "$cost_weight"
printf 'Topology:         %s\n' "$([[ "$decomposed" == true ]] && printf 'decomposed multi-agent' || printf 'direct')"
printf 'Profile:          %s\n' "$profile"
printf 'Coordinator:      %s\n' "$coordinator_model"
printf 'Agent cap:        %s\n' "$max_agents"
printf 'Concurrency cap:  %s\n' "$max_concurrency"
printf 'Packet:           %s\n' "$packet"
if [[ "$decomposed" == true ]]; then
  printf 'Artifact dir:     %s\n' "$artifact_dir"
  printf 'Aggregate MD:     %s\n' "$review_md"
else
  printf 'Review MD:        %s\n' "$review_md"
fi
if [[ "$record_transcript" == true ]]; then
  printf 'Transcript:       %s\n' "$transcript"
else
  printf 'Transcript:       disabled\n'
fi
printf '────────────────────────────────────────────────────────────\n'

if [[ "$assume_yes" != true ]]; then
  read -r -p "Start paid Claude review? [y/N] " answer
  case "$answer" in
    y|Y|yes|YES) ;;
    *)
      printf 'Review cancelled. Packet retained at %s\n' "$packet"
      exit 0
      ;;
  esac
fi

claude_args=(--permission-mode default --model "$coordinator_model" --effort high)
set +e
if [[ "$record_transcript" == true ]] && command -v script >/dev/null 2>&1; then
  case "$(uname -s)" in
    Darwin|FreeBSD)
      script -q "$transcript" claude "${claude_args[@]}" "$prompt"
      status=$?
      ;;
    *)
      printf -v quoted_command '%q ' claude "${claude_args[@]}" "$prompt"
      script -q -e -c "$quoted_command" "$transcript"
      status=$?
      ;;
  esac
else
  claude "${claude_args[@]}" "$prompt"
  status=$?
fi
set -e

if [[ "$status" -ne 0 ]]; then
  printf 'Review session ended with exit code %s.\n' "$status" >&2
  exit "$status"
fi

printf 'Review session completed.\n'
printf 'Review Markdown: %s\n' "$review_md"
printf 'Packet: %s\n' "$packet"
