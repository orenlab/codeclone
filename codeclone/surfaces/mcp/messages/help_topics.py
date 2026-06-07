# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""MCP help topic copy and doc links."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ....contracts import BASELINE_SCHEMA_VERSION, DOCS_URL


@dataclass(frozen=True)
class MCPHelpTopicSpec:
    summary: str
    key_points: tuple[str, ...]
    recommended_tools: tuple[str, ...]
    doc_links: tuple[tuple[str, str], ...]
    warnings: tuple[str, ...] = ()
    anti_patterns: tuple[str, ...] = ()


MCP_BOOK_URL: Final = f"{DOCS_URL}book/"
MCP_GUIDE_URL: Final = f"{DOCS_URL}guide/mcp/"
MCP_INTERFACE_DOC_LINK: Final[tuple[str, str]] = (
    "MCP interface contract",
    f"{MCP_BOOK_URL}25-mcp-interface/",
)
BASELINE_DOC_LINK: Final[tuple[str, str]] = (
    "Baseline contract",
    f"{MCP_BOOK_URL}07-baseline/",
)
CONFIG_DOC_LINK: Final[tuple[str, str]] = (
    "Config and defaults",
    f"{MCP_BOOK_URL}10-config-and-defaults/",
)
REPORT_DOC_LINK: Final[tuple[str, str]] = (
    "Report contract",
    f"{MCP_BOOK_URL}05-report/",
)
CLI_DOC_LINK: Final[tuple[str, str]] = (
    "CLI contract",
    f"{MCP_BOOK_URL}11-cli/",
)
PIPELINE_DOC_LINK: Final[tuple[str, str]] = (
    "Core pipeline",
    f"{MCP_BOOK_URL}03-core-pipeline/",
)
SUPPRESSIONS_DOC_LINK: Final[tuple[str, str]] = (
    "Inline suppressions contract",
    f"{MCP_BOOK_URL}19-inline-suppressions/",
)
MCP_GUIDE_DOC_LINK: Final[tuple[str, str]] = ("MCP usage guide", MCP_GUIDE_URL)
CHANGE_CONTROL_DOC_LINK: Final[tuple[str, str]] = (
    "Structural change controller",
    f"{MCP_BOOK_URL}12-structural-change-controller/",
)
ENGINEERING_MEMORY_DOC_LINK: Final[tuple[str, str]] = (
    "Engineering Memory",
    f"{MCP_BOOK_URL}13-engineering-memory/",
)
HELP_TOPIC_SPECS: Final[dict[str, MCPHelpTopicSpec]] = {
    "workflow": MCPHelpTopicSpec(
        summary=(
            "CodeClone MCP is triage-first and budget-aware. Start with a "
            "summary or production triage, then narrow through hotspots or "
            "focused checks before opening one finding in detail."
        ),
        key_points=(
            "Recommended first pass: analyze_repository or analyze_changed_paths.",
            (
                "Start with default or pyproject-resolved thresholds; lower them "
                "only for an explicit higher-sensitivity follow-up pass."
            ),
            (
                "Use get_run_summary or get_production_triage before broad "
                "finding listing."
            ),
            (
                "Prefer list_hotspots or focused check_* tools over "
                "list_findings on noisy repositories."
            ),
            ("Use get_finding and get_remediation only after selecting an issue."),
            (
                "get_report_section(section='all') is an exception path, not "
                "a default first step."
            ),
        ),
        recommended_tools=(
            "analyze_repository",
            "analyze_changed_paths",
            "get_run_summary",
            "get_production_triage",
            "list_hotspots",
            "check_clones",
            "check_dead_code",
            "get_finding",
            "get_remediation",
        ),
        doc_links=(MCP_INTERFACE_DOC_LINK, MCP_GUIDE_DOC_LINK),
        warnings=(
            (
                "Broad list_findings calls burn context quickly on large or "
                "noisy repositories."
            ),
            (
                "Prefer generate_pr_summary(format='markdown') unless machine "
                "JSON is explicitly required."
            ),
        ),
        anti_patterns=(
            "Starting exploration with list_findings on a noisy repository.",
            "Using get_report_section(section='all') as the default first step.",
            (
                "Escalating detail on larger lists instead of opening one "
                "finding with get_finding."
            ),
        ),
    ),
    "analysis_profile": MCPHelpTopicSpec(
        summary=(
            "CodeClone default analysis is intentionally conservative: stable "
            "first-pass review, baseline-aware governance, and CI-friendly "
            "signal over maximum local sensitivity."
        ),
        key_points=(
            (
                "Default thresholds are intentionally conservative and "
                "production-friendly."
            ),
            (
                "A clean default run does not rule out smaller local "
                "duplication or repetition."
            ),
            (
                "Lowering thresholds increases sensitivity and can surface "
                "smaller functions, tighter windows, and finer local signals."
            ),
            (
                "Lower-threshold runs are best for exploratory local review, "
                "not as a silent replacement for the default governance profile."
            ),
            "Interpret results in the context of the active threshold profile.",
        ),
        recommended_tools=(
            "analyze_repository",
            "analyze_changed_paths",
            "get_run_summary",
            "compare_runs",
        ),
        doc_links=(
            CONFIG_DOC_LINK,
            PIPELINE_DOC_LINK,
            MCP_INTERFACE_DOC_LINK,
        ),
        warnings=(
            (
                "Do not treat a default-threshold run as proof that no smaller "
                "local clone or repetition exists."
            ),
            (
                "Lower-threshold runs usually increase noise and should be read "
                "as higher-sensitivity exploratory passes."
            ),
            "Run comparisons are most meaningful when profiles are aligned.",
        ),
        anti_patterns=(
            (
                "Assuming a clean default pass means no finer-grained "
                "duplication exists anywhere in the repository."
            ),
            (
                "Lowering thresholds for exploration and then interpreting the "
                "result as if it had the same meaning as the conservative "
                "default pass."
            ),
            (
                "Mixing low-threshold exploratory output into baseline or CI "
                "reasoning without acknowledging the profile change."
            ),
        ),
    ),
    "suppressions": MCPHelpTopicSpec(
        summary=(
            "CodeClone supports explicit inline suppressions for selected "
            "findings. They are local policy, not analysis truth, and should "
            "stay narrow and declaration-scoped."
        ),
        key_points=(
            "Current syntax uses codeclone: ignore[rule-id,...].",
            "Binding is declaration-scoped: def, async def, or class.",
            (
                "Supported placement is the previous line or inline on the "
                "declaration or header line."
            ),
            (
                "Suppressions are target-specific and do not imply file-wide "
                "or cascading scope."
            ),
            (
                "Use suppressions for accepted dynamic or runtime false "
                "positives, not to hide broad classes of debt."
            ),
        ),
        recommended_tools=("get_finding", "get_remediation"),
        doc_links=(SUPPRESSIONS_DOC_LINK, MCP_INTERFACE_DOC_LINK),
        warnings=(
            (
                "MCP explains suppression semantics but never creates or "
                "updates suppressions."
            ),
        ),
        anti_patterns=(
            "Treating suppressions as file-wide or inherited state.",
            (
                "Using suppressions to hide broad structural debt instead of "
                "accepted false positives."
            ),
        ),
    ),
    "baseline": MCPHelpTopicSpec(
        summary=(
            "A baseline is CodeClone's accepted comparison snapshot for clones "
            "and optional metrics. It separates accepted debt from "
            "baseline-relative new findings and is trust-checked before use."
        ),
        key_points=(
            (
                f"Canonical baseline schema is v{BASELINE_SCHEMA_VERSION} "
                "with meta and clone keys; metrics may be embedded for "
                "unified flows."
            ),
            (
                "Compatibility depends on generator identity, supported "
                "schema version, fingerprint version, python tag, and payload "
                "integrity."
            ),
            (
                "Known means already present in the trusted baseline; new "
                "means not accepted by baseline. This is baseline-relative, "
                "not proof that a patch did or did not introduce the finding."
            ),
            (
                "Patch-local regressions require clean before-run to after-run "
                "comparison evidence from compare_runs or patch contract verify."
            ),
            (
                "In CI and gating contexts, untrusted baseline states are "
                "contract errors rather than soft warnings."
            ),
            "MCP is read-only and does not update or rewrite baselines.",
        ),
        recommended_tools=("get_run_summary", "evaluate_gates", "compare_runs"),
        doc_links=(BASELINE_DOC_LINK,),
        warnings=(
            "Baseline trust semantics directly affect new-vs-known classification.",
            "Do not use baseline novelty alone for patch-local regression claims.",
        ),
        anti_patterns=(
            "Treating baseline as mutable MCP session state.",
            "Assuming an untrusted baseline is only cosmetic in CI contexts.",
        ),
    ),
    "coverage": MCPHelpTopicSpec(
        summary=(
            "Coverage join is an external current-run signal: CodeClone reads "
            "an existing Cobertura XML report and joins line hits to risky "
            "function spans."
        ),
        key_points=(
            "Use Cobertura XML such as `coverage xml` output from coverage.py.",
            "Coverage join does not become baseline truth and does not affect health.",
            (
                "Coverage hotspot gating is current-run only and focuses on "
                "medium/high-risk functions measured below the configured "
                "threshold."
            ),
            (
                "Functions missing from the supplied coverage.xml are surfaced "
                "as scope gaps, not labeled as untested."
            ),
            "Use metrics_detail(family='coverage_join') for bounded drill-down.",
        ),
        recommended_tools=(
            "analyze_repository",
            "analyze_changed_paths",
            "get_run_summary",
            "get_report_section",
            "evaluate_gates",
        ),
        doc_links=(
            MCP_INTERFACE_DOC_LINK,
            CLI_DOC_LINK,
            REPORT_DOC_LINK,
        ),
        warnings=(
            "Coverage join is only as accurate as the external XML path mapping.",
            "It does not infer branch coverage and does not execute tests.",
            "Use fail-on-untested-hotspots only with a valid joined coverage input.",
        ),
        anti_patterns=(
            "Treating missing coverage XML as zero coverage without stating it.",
            "Reading coverage join as a baseline-aware trend signal.",
            "Assuming dynamic runtime dispatch is visible through a static line join.",
        ),
    ),
    "latest_runs": MCPHelpTopicSpec(
        summary=(
            "latest/* resources point to the most recent analysis run in the "
            "current MCP session. They are convenience handles, not persistent "
            "truth anchors."
        ),
        key_points=(
            "Run history is in-memory only and bounded by history-limit.",
            "The latest pointer moves when a newer analyze_* call registers a run.",
            "A fresh repository state requires a fresh analyze run.",
            (
                "Short run ids are convenience handles derived from canonical "
                "run identity."
            ),
            (
                "Do not assume latest/* is globally current outside the "
                "active MCP session."
            ),
        ),
        recommended_tools=(
            "analyze_repository",
            "analyze_changed_paths",
            "get_run_summary",
            "compare_runs",
        ),
        doc_links=(MCP_INTERFACE_DOC_LINK, MCP_GUIDE_DOC_LINK),
        warnings=(
            (
                "latest/* can point at a different repository after a later "
                "analyze call in the same session."
            ),
        ),
        anti_patterns=(
            (
                "Assuming latest/* remains tied to one repository across the "
                "whole client session."
            ),
            (
                "Using latest/* as a substitute for starting a fresh run when "
                "freshness matters."
            ),
        ),
    ),
    "review_state": MCPHelpTopicSpec(
        summary=(
            "Reviewed state in MCP is session-local workflow state. It helps "
            "long sessions track review progress without modifying canonical "
            "findings, baseline, or persisted artifacts."
        ),
        key_points=(
            "Review markers are in-memory only.",
            "They do not change report truth, finding identity, or CI semantics.",
            "They are useful for triage workflows across long sessions.",
            (
                "They should not be interpreted as acceptance, suppression, "
                "or baseline update."
            ),
        ),
        recommended_tools=(
            "list_hotspots",
            "get_finding",
            "mark_finding_reviewed",
            "list_reviewed_findings",
        ),
        doc_links=(MCP_INTERFACE_DOC_LINK, MCP_GUIDE_DOC_LINK),
        warnings=(
            "Reviewed markers disappear when the MCP session is cleared or restarted.",
        ),
        anti_patterns=(
            "Treating reviewed state as a persistent acceptance signal.",
            "Assuming reviewed findings are removed from canonical report truth.",
        ),
    ),
    "changed_scope": MCPHelpTopicSpec(
        summary=(
            "Changed-scope analysis narrows review to findings that touch a "
            "selected change set. It is for PR and patch review, not a "
            "replacement for full canonical analysis."
        ),
        key_points=(
            (
                "Use analyze_changed_paths with explicit changed_paths or "
                "git_diff_ref for review-focused runs."
            ),
            (
                "Start with the same conservative profile as the default "
                "review, then lower thresholds only when you explicitly want "
                "a higher-sensitivity changed-files pass."
            ),
            (
                "Changed-scope is best for asking what new issues touch "
                "modified files and whether anything should block CI."
            ),
            "Prefer production triage and hotspot views before broad listing.",
            "If repository-wide truth is needed, run full analysis first.",
        ),
        recommended_tools=(
            "analyze_changed_paths",
            "get_run_summary",
            "get_production_triage",
            "evaluate_gates",
            "generate_pr_summary",
        ),
        doc_links=(MCP_INTERFACE_DOC_LINK, MCP_GUIDE_DOC_LINK),
        warnings=(
            (
                "Changed-scope narrows review focus; it does not replace the "
                "full canonical report for repository-wide truth."
            ),
        ),
        anti_patterns=(
            "Using changed-scope as if it were the only source of repository truth.",
            (
                "Starting changed-files review with broad listing instead of "
                "compact triage."
            ),
        ),
    ),
    "change_control": MCPHelpTopicSpec(
        summary=(
            "Edit-time workflow: declare scope, edit inside it, finish with "
            "evidence. Prefer start_controlled_change and finish_controlled_change."
        ),
        key_points=(
            (
                "Cycle: analyze_repository → start_controlled_change → "
                "get_relevant_memory → edit → analyze (if after_run required) → "
                "finish_controlled_change."
            ),
            (
                "Requires edit_allowed=true from start; queue via "
                "start(on_conflict=queue) then manage_change_intent(promote)."
            ),
            (
                "Multi-agent: manage_change_intent(list_workspace|renew|recover|"
                "gc_workspace) — registry is advisory under .codeclone/intents/."
            ),
            (
                "Finish: changed_files XOR diff_ref; after_run_id when "
                "verification.after_run_required "
                "(help(topic=verification_profiles))."
            ),
            (
                "finish detail_level=full adds hygiene path attribution; "
                "patch_trail_detail summary|full on patch_trail (forensics only)."
            ),
            (
                "Blocks finish: missing_evidence, foreign_dirty_overlap. "
                "Out-of-scope dirt is advisory — may yield "
                "accepted_with_external_changes."
            ),
            ("Optional CODECLONE_STRICT_FINISH env may block own_unscoped_dirty."),
            ("patch_trail + audit patch_trail.computed do not authorize edits."),
            (
                "Atomic declare/check/verify/clear is legacy/debug only when "
                "start/finish unavailable."
            ),
        ),
        recommended_tools=(
            "analyze_repository",
            "start_controlled_change",
            "get_relevant_memory",
            "finish_controlled_change",
            "manage_change_intent",
        ),
        doc_links=(CHANGE_CONTROL_DOC_LINK, MCP_INTERFACE_DOC_LINK),
        warnings=(
            "Workspace registry is coordination state, not analysis truth.",
            "review_context is information, not an edit ban.",
        ),
        anti_patterns=(
            "Editing before start_controlled_change with edit_allowed=true.",
            "Mixing start/finish with atomic verify/clear in one cycle.",
            "Resetting a foreign live intent instead of coordinating.",
        ),
    ),
    "trust_boundaries": MCPHelpTopicSpec(
        summary=(
            "Documented MCP trust limits: read-only analysis, advisory "
            "workspace intents, strict artifact paths with opt-in external "
            "resolution, and optional Bearer auth on streamable-http."
        ),
        key_points=(
            "MCP never mutates source, baseline, cache.json, or canonical reports.",
            (
                "baseline_path, cache_path, coverage_xml resolve under the scan "
                "root by default; pass allow_external_artifacts=true for "
                "absolute or out-of-repo paths (privileged)."
            ),
            (
                "Workspace intents under .codeclone/intents/ are "
                "advisory same-UID coordination, not signed proof."
            ),
            (
                "Cache signatures and baseline payload_sha256 detect "
                "corruption, not hostile same-UID writers."
            ),
            (
                "streamable-http: set CODECLONE_MCP_AUTH_TOKEN (>=32 chars) for "
                "Bearer auth; --allow-remote is separate loopback guard."
            ),
            (
                "security_surfaces in responses is report-only inventory, "
                "not a vulnerability scan."
            ),
        ),
        recommended_tools=("help", "analyze_repository", "start_controlled_change"),
        doc_links=(MCP_INTERFACE_DOC_LINK,),
        warnings=(
            "Do not treat advisory intent files as cryptographic agent identity.",
        ),
        anti_patterns=(
            "Calling Security Surfaces a vulnerability audit.",
            "Passing allow_external_artifacts=true without treating paths "
            "as privileged.",
        ),
    ),
    "engineering_memory": MCPHelpTopicSpec(
        summary=(
            "Ranked scope context before edits, FTS search, optional semantic "
            "sidecar (off by default), trajectory forensics, draft-only writes."
        ),
        key_points=(
            (
                "After edit_allowed=true: get_relevant_memory(root=abs, "
                "scope|intent_id|symbols). root is required."
            ),
            (
                "Bootstrap: mcp_sync_policy default bootstrap_if_missing; "
                "refresh_from_run for explicit ingest."
            ),
            (
                "Query: for_path, for_symbol, search (filters.match_mode), get, "
                "status, stale; trajectory_status|trajectory_search|"
                "trajectory_get after rebuild_trajectories."
            ),
            (
                "Scoped response may include trajectories[] and "
                "patch_trail_summary — forensics only, not edit authorization."
            ),
            (
                "Semantic (off by default): enable sidecar, rebuild_semantic_index, "
                "then search with semantic=true."
            ),
            (
                "Projections: rebuild_trajectories; jobs via "
                "enqueue_projection_rebuild, projection_rebuild_status, "
                "run_projection_jobs_once (or finish hook when policy on)."
            ),
            (
                "Agent writes draft-only: record_candidate, validate_claims, "
                "finish(propose_memory=true). Approve via VS Code Memory view."
            ),
            (
                "Never use project root as scope; one fact per record_candidate "
                "(target <=300 chars). detail_level=full or mode=get for full text."
            ),
        ),
        recommended_tools=(
            "get_relevant_memory",
            "query_engineering_memory",
            "manage_engineering_memory",
            "start_controlled_change",
        ),
        doc_links=(ENGINEERING_MEMORY_DOC_LINK, MCP_INTERFACE_DOC_LINK),
        warnings=(
            "Draft, inferred, and stale records are not established policy.",
            "trajectories[] and patch_trail_summary do not override findings.",
        ),
        anti_patterns=(
            "Using memory to justify do_not_touch edits or scope expansion.",
            "get_relevant_memory without root, scope, intent_id, or symbols.",
            "approve/reject/archive via MCP — use VS Code Memory view.",
        ),
    ),
    "verification_profiles": MCPHelpTopicSpec(
        summary=(
            "finish_controlled_change derives verification_profile from changed "
            "files — controls after_run requirements and structural checks."
        ),
        key_points=(
            (
                "Read verification.verification_profile and after_run_required "
                "from finish — do not guess."
            ),
            (
                "python_structural (.py/.pyi) and governance_config need a new "
                "after_run_id."
            ),
            (
                "documentation_only and non_python_patch may verify from "
                "changed_files without after_run."
            ),
            (
                "state_artifact_change (codeclone.baseline.json, .codeclone/**, "
                ".cache/codeclone/**) is violated, not verified."
            ),
            (
                "after_run_not_new when before and after runs match for "
                "structural profiles."
            ),
            (
                "accepted means patch contract passed for scope — not unchanged "
                "health or repo-wide cleanliness."
            ),
            (
                "Read verification.structural_delta and health_regression_advisory "
                "on accept."
            ),
            "Skipped receipt checks are not applicable, never passed.",
        ),
        recommended_tools=(
            "finish_controlled_change",
            "analyze_repository",
            "check_patch_contract",
        ),
        doc_links=(CHANGE_CONTROL_DOC_LINK,),
        warnings=("Do not claim full structural verification for docs-only patches.",),
        anti_patterns=(
            "Skipping after_run_id for Python patches.",
            "Treating documentation_only accepted as no regressions repo-wide.",
        ),
    ),
}
