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
MCP_GUIDE_URL: Final = f"{DOCS_URL}mcp/"
MCP_INTERFACE_DOC_LINK: Final[tuple[str, str]] = (
    "MCP interface contract",
    f"{MCP_BOOK_URL}20-mcp-interface/",
)
BASELINE_DOC_LINK: Final[tuple[str, str]] = (
    "Baseline contract",
    f"{MCP_BOOK_URL}06-baseline/",
)
CONFIG_DOC_LINK: Final[tuple[str, str]] = (
    "Config and defaults",
    f"{MCP_BOOK_URL}04-config-and-defaults/",
)
REPORT_DOC_LINK: Final[tuple[str, str]] = (
    "Report contract",
    f"{MCP_BOOK_URL}08-report/",
)
CLI_DOC_LINK: Final[tuple[str, str]] = (
    "CLI contract",
    f"{MCP_BOOK_URL}09-cli/",
)
PIPELINE_DOC_LINK: Final[tuple[str, str]] = (
    "Core pipeline",
    f"{MCP_BOOK_URL}05-core-pipeline/",
)
SUPPRESSIONS_DOC_LINK: Final[tuple[str, str]] = (
    "Inline suppressions contract",
    f"{MCP_BOOK_URL}19-inline-suppressions/",
)
MCP_GUIDE_DOC_LINK: Final[tuple[str, str]] = ("MCP usage guide", MCP_GUIDE_URL)
CHANGE_CONTROL_DOC_LINK: Final[tuple[str, str]] = (
    "Structural change controller",
    f"{MCP_BOOK_URL}24-structural-change-controller/",
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
            "Change control is the edit-time MCP workflow: inspect concurrent "
            "workspace intents, declare scope, read blast radius and patch "
            "budget, then verify the finished patch."
        ),
        key_points=(
            (
                "Start with manage_change_intent(action='list_workspace', "
                "root=...) before analysis so active agents are visible early."
            ),
            (
                "Recover ownership only when list_workspace marks an intent "
                "recoverable and the matching run is available; live foreign "
                "active or stale intents require coordination."
            ),
            (
                "Run analyze_repository, then declare intent with allowed_files, "
                "allowed_related, and forbidden paths before editing."
            ),
            (
                "Use get_blast_radius and check_patch_contract(mode='budget') "
                "as the pre-edit boundary."
            ),
            (
                "Use manage_change_intent(action='renew') before long edits, "
                "test runs, or other blind windows between MCP calls."
            ),
            (
                "Hard overlaps mean two agents claimed the same primary file; "
                "soft overlaps mean primary files overlap related context."
            ),
            (
                "After editing, re-run analysis, check intent scope, verify "
                "the patch contract, validate review claims, and clear the "
                "intent."
            ),
            (
                "Use reset_workspace for interrupted own, expired, or "
                "recoverable registry records; foreign live intents require "
                "coordination."
            ),
        ),
        recommended_tools=(
            "manage_change_intent",
            "analyze_repository",
            "get_blast_radius",
            "check_patch_contract",
            "validate_review_claims",
            "create_review_receipt",
        ),
        doc_links=(CHANGE_CONTROL_DOC_LINK, MCP_INTERFACE_DOC_LINK),
        warnings=(
            (
                "The workspace registry is advisory coordination state under "
                ".cache/codeclone/intents/, not analysis truth."
            ),
            (
                "Do not treat review_context as a ban or concurrent_intents as "
                "an automatic blocker without human or orchestrator policy."
            ),
        ),
        anti_patterns=(
            "Editing files before declaring intent.",
            "Silently expanding scope after a hard overlap or scope violation.",
            (
                "Resetting a foreign live intent instead of coordinating with "
                "the owning agent or user."
            ),
        ),
    ),
    "trust_boundaries": MCPHelpTopicSpec(
        summary=(
            "Documented MCP trust limits: read-only analysis, advisory "
            "workspace intents, optional absolute artifact paths, and "
            "non-authenticated remote transport."
        ),
        key_points=(
            "MCP never mutates source, baseline, cache.json, or canonical reports.",
            (
                "Optional paths (baseline_path, cache_path, coverage_xml) may "
                "resolve outside the scan root by design."
            ),
            (
                "Workspace intents under .cache/codeclone/intents/ are "
                "advisory same-UID coordination, not signed proof."
            ),
            (
                "Cache signatures and baseline payload_sha256 detect "
                "corruption, not hostile same-UID writers."
            ),
            (
                "--allow-remote removes loopback guard only; add external "
                "auth/network controls for HTTP MCP."
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
            "Assuming MCP sandboxes optional absolute artifact paths.",
        ),
    ),
    "engineering_memory": MCPHelpTopicSpec(
        summary=(
            "Engineering Memory: ranked scope context before edits, FTS search, "
            "optional semantic search (off by default), MCP sync from analysis "
            "runs, and draft-only agent writes."
        ),
        key_points=(
            "After start_controlled_change with edit_allowed=true, call "
            "get_relevant_memory(root=abs, scope=... or intent_id=...). "
            "root is required; intent_id alone fails validation.",
            "Default mcp_sync_policy=bootstrap_if_missing auto-creates the store "
            "from the latest MCP run on first get_relevant_memory.",
            "Explicit refresh: manage_engineering_memory(action=refresh_from_run) "
            "after analyze_repository.",
            "Semantic sidecar: when memory.semantic.enabled, run "
            "manage_engineering_memory(action=rebuild_semantic_index) after "
            "refresh/init (requires codeclone[semantic-lancedb]); then "
            "query_engineering_memory(mode=search, semantic=true).",
            "Optional mcp_sync_policy=refresh_when_stale in pyproject for digest-based "
            "auto refresh.",
            "Drill down with query_engineering_memory(mode=for_path|search|get).",
            "for_symbol resolves exact symbol subjects first, then falls back to "
            "module_role records for the owning module prefix.",
            "Search filters.match_mode: any (default) or all.",
            "Optional semantic: query_engineering_memory(mode=search, "
            "semantic=true) when memory.semantic.enabled and index rebuilt; "
            "default provider diagnostic is deterministic, not semantic-quality.",
            "Scoped get_relevant_memory includes draft agent notes automatically; "
            "for_path/for_symbol include drafts without an extra flag.",
            "Stale excluded by default; do not ignore stale warnings.",
            "retrieval_policy in responses states memory never authorizes edits "
            "or overrides CodeClone findings.",
            "Agent writes are draft-only: record_candidate, validate_claims, "
            "finish(propose_memory=true). Human approve/reject/archive is only "
            "through the CodeClone VS Code Memory view, not MCP agent tools.",
            "Memory cannot expand scope, authorize do_not_touch edits, "
            "or override findings.",
            "Engineering Memory is scoped and compact: never use project root as "
            "scope/path; compress record_candidate statements to one durable fact "
            "(target <= 300 chars); list responses default to compact previews — "
            "use mode=get or detail_level=full for complete statements.",
        ),
        recommended_tools=(
            "help",
            "analyze_repository",
            "get_relevant_memory",
            "query_engineering_memory",
            "manage_engineering_memory",
            "start_controlled_change",
            "finish_controlled_change",
        ),
        doc_links=(MCP_INTERFACE_DOC_LINK,),
        warnings=(
            "Do not treat draft, inferred, or stale records as established facts.",
            "Do not skip memory retrieval before high-radius scope edits.",
            "refresh_from_run ingests system records; human approve still required "
            "for agent drafts.",
        ),
        anti_patterns=(
            "Using memory to justify touching do-not-touch paths.",
            "Skipping get_relevant_memory because blast radius was already read.",
            "Calling get_relevant_memory without scope, intent_id, or symbols.",
            "Using scope=['.'], path='.', or project root for memory retrieval.",
            "Writing long chat transcripts into record_candidate statements.",
            "Calling get_relevant_memory with intent_id or scope but without "
            "absolute root (Pydantic validation error).",
            "Calling manage_engineering_memory with approve/reject/archive — use "
            "the VS Code Memory view instead.",
            "Claiming a draft record is verified project policy without human approve.",
        ),
    ),
}
