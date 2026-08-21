"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const Module = require("node:module");

const moduleInternals = /** @type {{_load: Function}} */ (
    /** @type {unknown} */ (Module)
);
const originalLoad = moduleInternals._load;
moduleInternals._load = function patchedLoad(request, parent, isMain) {
    if (request === "vscode") {
        return {
            ThemeIcon: class ThemeIcon {},
            ThemeColor: class ThemeColor {},
        };
    }
    return originalLoad.call(this, request, parent, isMain);
};

const {
    renderTrajectoryDashboardHtml,
    renderTrajectoryDetailHtml,
    renderTrajectoryDashboardMarkdown,
    formatTrajectoryPickDescription,
} = require("../src/trajectoryViewerRenderer");

const NONCE = "test-nonce";
const WORKSPACE = "wave-fixture-workspace";

function includesPin(haystack, fragment) {
    assert.ok(
        haystack.includes(fragment),
        `expected fragment present: ${fragment}`,
    );
}

function excludesPin(haystack, fragment) {
    assert.ok(
        !haystack.includes(fragment),
        `expected fragment absent: ${fragment}`,
    );
}

// --- P1: score classifier boundaries, pinned through renderTrajectoryDetailHtml ---

const QUALITY_CLASSES = ["quality-high", "quality-mid", "quality-low"];
const QUALITY_BOUNDARY_CASES = [
    [90, "quality-high"],
    [89, "quality-mid"],
    [70, "quality-mid"],
    [69, "quality-low"],
];

for (const [score, expectedClass] of QUALITY_BOUNDARY_CASES) {
    test(`P1 quality boundary: ${score} -> ${expectedClass}`, () => {
        const html = renderTrajectoryDetailHtml(
            {trajectory_id: "traj-quality-boundary", quality_score: score},
            WORKSPACE,
            NONCE,
        );
        includesPin(html, `<span class="${expectedClass}">${score}<span`);
        for (const other of QUALITY_CLASSES) {
            if (other !== expectedClass) {
                excludesPin(html, `<span class="${other}">${score}<span`);
            }
        }
    });
}

test("P1 quality non-numeric score falls back to quality-mid", () => {
    const html = renderTrajectoryDetailHtml(
        {trajectory_id: "traj-quality-garbage", quality_score: "ninetyish"},
        WORKSPACE,
        NONCE,
    );
    includesPin(html, '<span class="quality-mid">ninetyish<span');
});

const COMPLEXITY_CLASSES = ["complexity-high", "complexity-mid", "complexity-low"];
const COMPLEXITY_BOUNDARY_CASES = [
    [70, "complexity-high"],
    [69, "complexity-mid"],
    [35, "complexity-mid"],
    [34, "complexity-low"],
];

for (const [score, expectedClass] of COMPLEXITY_BOUNDARY_CASES) {
    test(`P1 complexity boundary: ${score} -> ${expectedClass}`, () => {
        const html = renderTrajectoryDetailHtml(
            {trajectory_id: "traj-complexity-boundary", complexity_score: score},
            WORKSPACE,
            NONCE,
        );
        includesPin(html, `<span class="${expectedClass}">${score}<span`);
        for (const other of COMPLEXITY_CLASSES) {
            if (other !== expectedClass) {
                excludesPin(html, `<span class="${other}">${score}<span`);
            }
        }
    });
}

test("P1 complexity non-numeric score falls back to complexity-mid", () => {
    const html = renderTrajectoryDetailHtml(
        {trajectory_id: "traj-complexity-garbage", complexity_score: "wild"},
        WORKSPACE,
        NONCE,
    );
    includesPin(html, '<span class="complexity-mid">wild<span');
});

function detailWithQualityContract() {
    return {
        trajectory_id: "traj-contract",
        quality_score: 90,
        quality_contract: {
            quality_score: 55,
            complexity_score: 40,
            components: [
                {id: "scope", label: "Scope clean", pass: true, score: 30},
                {id: "verify", label: "Verification reached", pass: false, score: 0},
            ],
            calculation: {
                formula: "min over gates",
                quality_score: 55,
                lines: [
                    {id: "scope", label: "Scope clean", score: 30, pass: true, limits_quality: false},
                    {id: "verify", label: "Verification reached", score: 0, pass: false, limits_quality: true},
                ],
            },
            complexity_calculation: {
                band_label: "moderate",
                hint: "touch fewer files per intent",
                formula: "sum of capped factors",
                complexity_score: 40,
                lines: [
                    {id: "files", label: "Files touched", raw: 12, unit: "files", contribution: 20, cap: 20},
                    {id: "steps", label: "Steps", raw: 3, contribution: 5, cap: 30},
                ],
            },
        },
    };
}

test("P1 contribution at cap marks calc-row-cap; below cap does not", () => {
    const html = renderTrajectoryDetailHtml(detailWithQualityContract(), WORKSPACE, NONCE);
    includesPin(html, '<tr class="calc-row-cap"><td class="calc-label">Files touched</td>');
    includesPin(html, '<tr class=""><td class="calc-label">Steps</td>');
    includesPin(html, '<td class="calc-raw">12 files</td>');
    includesPin(html, '<td class="calc-score">20 / 20</td>');
});

test("P1 contract scores take precedence over root scores in the passport", () => {
    const html = renderTrajectoryDetailHtml(detailWithQualityContract(), WORKSPACE, NONCE);
    includesPin(html, '<span class="quality-low">55<span');
    excludesPin(html, '<span class="quality-high">90<span');
    includesPin(html, '<span class="complexity-mid">40<span');
    includesPin(html, '<span class="passport-band">moderate</span>');
});

// --- P2: outcome / severity / trail-status / timeline-tone dictionaries plus fallbacks ---

const OUTCOME_CASES = [
    ["accepted", "pill pill-ok"],
    ["accepted_with_external_changes", "pill pill-ok"],
    ["violated", "pill pill-bad"],
    ["blocked", "pill pill-bad"],
    ["meandering", "pill pill-warn"],
];

for (const [outcome, expectedClass] of OUTCOME_CASES) {
    test(`P2 outcome pill: ${outcome} -> ${expectedClass}`, () => {
        const html = renderTrajectoryDetailHtml(
            {trajectory_id: "traj-outcome", outcome},
            WORKSPACE,
            NONCE,
        );
        includesPin(html, `<span class="${expectedClass}">${outcome}</span>`);
    });
}

test("P2 outcome classification is case-insensitive, display is verbatim", () => {
    const html = renderTrajectoryDetailHtml(
        {trajectory_id: "traj-outcome-case", outcome: "ACCEPTED"},
        WORKSPACE,
        NONCE,
    );
    includesPin(html, '<span class="pill pill-ok">ACCEPTED</span>');
});

test("P2 quality tier verified maps to ok pill; unknown tier maps to warn pill", () => {
    const verified = renderTrajectoryDetailHtml(
        {trajectory_id: "traj-tier", quality_tier: "verified"},
        WORKSPACE,
        NONCE,
    );
    includesPin(verified, '<span class="pill pill-ok">verified</span>');
    const flawed = renderTrajectoryDetailHtml(
        {trajectory_id: "traj-tier", quality_tier: "flawed"},
        WORKSPACE,
        NONCE,
    );
    includesPin(flawed, '<span class="pill pill-warn">flawed</span>');
});

function dashboardPayloadWithSeverityTags() {
    return {
        anomalies: {
            summary: {trajectories_with_anomalies: 1, anomaly_count: 3, error_count: 1, warn_count: 2},
            trajectories: [
                {
                    trajectory_id: "traj-tagged",
                    outcome: "accepted",
                    quality_tier: "verified",
                    summary: "anomaly fixture",
                    agent_label: "agent-gamma",
                    anomalies: [
                        {severity: "error", kind: "contract_gap", message: "verify never ran"},
                        {severity: "warn", kind: "slow_step", message: "step exceeded budget"},
                        {severity: "mystery", kind: "unclassified_tag", message: "novel anomaly kind"},
                    ],
                },
            ],
        },
    };
}

test("P2 severity error -> bad pill; warn and unknown severities -> warn pill", () => {
    const html = renderTrajectoryDashboardHtml(dashboardPayloadWithSeverityTags(), WORKSPACE, NONCE);
    includesPin(html, '<li><span class="pill pill-bad">error</span> <code>contract_gap</code> — verify never ran</li>');
    includesPin(html, '<li><span class="pill pill-warn">warn</span> <code>slow_step</code> — step exceeded budget</li>');
    includesPin(html, '<li><span class="pill pill-warn">mystery</span> <code>unclassified_tag</code> — novel anomaly kind</li>');
    includesPin(html, '<p class="meta">anomaly fixture · agent-gamma</p>');
});

function detailWithTrail(scopeStatus, verificationStatus, counts) {
    return {
        trajectory_id: "traj-trail",
        patch_trail_summary: {
            scope_check_status: scopeStatus,
            verification_status: verificationStatus,
            counts: counts ?? {declared: 4, changed: 2, untouched_in_declared: 3, unexpected: 0},
        },
    };
}

const SCOPE_STATUS_CASES = [
    ["clean", "pill pill-ok", "Scope clean"],
    ["violated", "pill pill-bad", "Scope violated"],
    ["expanded", "pill pill-warn", "Scope expanded"],
    ["wandering", "pill pill-muted", "Scope wandering"],
];

for (const [status, expectedClass, label] of SCOPE_STATUS_CASES) {
    test(`P2 scope trail status: ${status} -> ${expectedClass}`, () => {
        const html = renderTrajectoryDetailHtml(detailWithTrail(status, undefined), WORKSPACE, NONCE);
        includesPin(html, `<span class="${expectedClass}">${label}</span>`);
    });
}

const VERIFICATION_STATUS_CASES = [
    ["accepted", "pill pill-ok", "Verification accepted"],
    ["accepted_with_external_changes", "pill pill-ok", "Verification accepted with external changes"],
    ["unverified", "pill pill-warn", "Verification unverified"],
    ["violated", "pill pill-bad", "Verification violated"],
    ["blocked", "pill pill-bad", "Verification blocked"],
    ["meandering", "pill pill-muted", "Verification meandering"],
];

for (const [status, expectedClass, label] of VERIFICATION_STATUS_CASES) {
    test(`P2 verification trail status: ${status} -> ${expectedClass}`, () => {
        const html = renderTrajectoryDetailHtml(detailWithTrail(undefined, status), WORKSPACE, NONCE);
        includesPin(html, `<span class="${expectedClass}">${label}</span>`);
    });
}

test("P2 patch trail counts classify untouched>0 warn, unexpected==0 ok, forbidden hidden at 0", () => {
    const html = renderTrajectoryDetailHtml(detailWithTrail("clean", "accepted"), WORKSPACE, NONCE);
    includesPin(html, '<td class="patch-count "><span class="patch-count-label">Declared</span><span class="patch-count-value">4</span></td>');
    includesPin(html, '<td class="patch-count patch-count-warn"><span class="patch-count-label">Untouched</span><span class="patch-count-value">3</span></td>');
    includesPin(html, '<td class="patch-count patch-count-ok"><span class="patch-count-label">Unexpected</span><span class="patch-count-value">0</span></td>');
    excludesPin(html, "Forbidden");
});

test("P2 patch trail counts classify unexpected>0 bad and forbidden>0 shown bad", () => {
    const html = renderTrajectoryDetailHtml(
        detailWithTrail("violated", "violated", {
            declared: 4,
            changed: 2,
            untouched_in_declared: 0,
            unexpected: 2,
            forbidden_touched: 1,
        }),
        WORKSPACE,
        NONCE,
    );
    includesPin(html, '<td class="patch-count patch-count-bad"><span class="patch-count-label">Unexpected</span><span class="patch-count-value">2</span></td>');
    includesPin(html, '<td class="patch-count patch-count-bad"><span class="patch-count-label">Forbidden</span><span class="patch-count-value">1</span></td>');
});

function detailWithTonedSteps() {
    return {
        trajectory_id: "traj-timeline",
        steps: [
            {event_type: "intent.declared", status: "active", summary: "Declared edit scope", audit_sequence: 1},
            {event_type: "patch.verify", status: "violated", summary: "Scope violated", audit_sequence: 2},
            {event_type: "intent.queued", status: "queued", summary: "Waiting on foreign intent", audit_sequence: 3},
            {event_type: "workspace.conflict", summary: "Foreign overlap detected", audit_sequence: 4},
            {event_type: "lease.expired", summary: "Lease ran out", audit_sequence: 5},
            {event_type: "note.recorded", status: "zigzag", summary: "Unknown status recorded", audit_sequence: 6},
            {event_type: "verify.finish", status: "not_reached", summary: "Verify skipped", audit_sequence: 7},
        ],
    };
}

test("P2 timeline tones: bad/warn dictionaries, event-type hints, unknown status -> ok", () => {
    const html = renderTrajectoryDetailHtml(detailWithTonedSteps(), WORKSPACE, NONCE);
    includesPin(html, '<div class="timeline-index timeline-index-ok" title="active">1</div>');
    includesPin(html, '<div class="timeline-index timeline-index-bad" title="violated">2</div>');
    includesPin(html, '<div class="timeline-index timeline-index-warn" title="queued">3</div>');
    includesPin(html, '<div class="timeline-index timeline-index-bad" title="bad">4</div>');
    includesPin(html, '<div class="timeline-index timeline-index-warn" title="warn">5</div>');
    includesPin(html, '<div class="timeline-index timeline-index-ok" title="zigzag">6</div>');
    includesPin(html, '<div class="timeline-index timeline-index-bad" title="not reached">7</div>');
});

test("P2 redundant 'Review receipt: <status>' step summary is suppressed", () => {
    const html = renderTrajectoryDetailHtml(
        {
            trajectory_id: "traj-receipt",
            steps: [
                {event_type: "receipt.created", status: "accepted", summary: "Review receipt: accepted", audit_sequence: 9},
            ],
        },
        WORKSPACE,
        NONCE,
    );
    excludesPin(html, ">Review receipt: accepted<");
});

test("P2 timeline title strips a trailing parenthetical from the step label", () => {
    const html = renderTrajectoryDetailHtml(
        {
            trajectory_id: "traj-labels",
            steps: [
                {step_label: "Patch verification (2 files, 1 gate)", status: "accepted", audit_sequence: 3},
            ],
        },
        WORKSPACE,
        NONCE,
    );
    includesPin(html, "<strong>Patch verification</strong>");
    excludesPin(html, "(2 files, 1 gate)");
});

test("P2 trajectory labels are humanized into muted pills", () => {
    const html = renderTrajectoryDetailHtml(
        {trajectory_id: "traj-labelled", labels: ["change_control_workflow"]},
        WORKSPACE,
        NONCE,
    );
    includesPin(html, '<span class="pill pill-muted">Change Control Workflow</span>');
});

test("P2 quality contract components render pass check and fail cross", () => {
    const html = renderTrajectoryDetailHtml(detailWithQualityContract(), WORKSPACE, NONCE);
    includesPin(html, '<li class="quality-check-pass"><span class="quality-check-mark" aria-hidden="true">✓</span><span class="quality-check-label">Scope clean</span><span class="quality-check-score">30</span></li>');
    includesPin(html, '<li class="quality-check-fail"><span class="quality-check-mark" aria-hidden="true">✗</span><span class="quality-check-label">Verification reached</span><span class="quality-check-score">0</span></li>');
    includesPin(html, '<tr class="calc-row-limit"><td class="calc-label">Verification reached</td>');
    includesPin(html, '<td class="calc-flag">← limits score</td>');
});

// --- P3: time formatting, ranges, duration protection ---

test("P3 valid ISO timestamp is normalized to UTC display form", () => {
    assert.equal(
        formatTrajectoryPickDescription({started_at_utc: "2026-08-21T10:00:00Z"}),
        "0 events · 0 incidents · 2026-08-21 · 10:00:00 UTC",
    );
});

test("P3 offset timestamps are normalized to UTC, not echoed", () => {
    assert.equal(
        formatTrajectoryPickDescription({started_at_utc: "2026-08-21T12:30:45+02:30"}),
        "0 events · 0 incidents · 2026-08-21 · 10:00:45 UTC",
    );
});

test("P3 unparseable timestamp text passes through verbatim", () => {
    assert.equal(
        formatTrajectoryPickDescription({started_at_utc: "yesterday-ish"}),
        "0 events · 0 incidents · yesterday-ish",
    );
});

test("P3 step created_at_utc is rendered in UTC display form", () => {
    const html = renderTrajectoryDetailHtml(
        {
            trajectory_id: "traj-step-time",
            steps: [
                {event_type: "intent.declared", summary: "Declared", audit_sequence: 1, created_at_utc: "2026-08-21T10:00:00Z"},
            ],
        },
        WORKSPACE,
        NONCE,
    );
    includesPin(html, '<div class="meta">2026-08-21 · 10:00:00 UTC</div>');
});

test("P3 full time range renders start -> finish and duration 5m", () => {
    const html = renderTrajectoryDetailHtml(
        {
            trajectory_id: "traj-window",
            started_at_utc: "2026-08-21T10:00:00Z",
            finished_at_utc: "2026-08-21T10:05:00Z",
        },
        WORKSPACE,
        NONCE,
    );
    includesPin(html, 'title="2026-08-21 · 10:00:00 UTC → 2026-08-21 · 10:05:00 UTC">');
    includesPin(html, '<div class="passport-cell-value">5m</div>');
});

test("P3 half time range renders only the known end, duration em dash", () => {
    const html = renderTrajectoryDetailHtml(
        {trajectory_id: "traj-half-window", started_at_utc: "2026-08-21T10:00:00Z"},
        WORKSPACE,
        NONCE,
    );
    includesPin(html, 'title="2026-08-21 · 10:00:00 UTC">');
    excludesPin(html, "→ 2026-08-21");
    includesPin(html, '<div class="passport-cell-label">Duration</div><div class="passport-cell-value">—</div>');
});

test("P3 reversed order (finished before started) clamps duration to expired", () => {
    const html = renderTrajectoryDetailHtml(
        {
            trajectory_id: "traj-reversed",
            started_at_utc: "2026-08-21T10:10:00Z",
            finished_at_utc: "2026-08-21T10:00:00Z",
        },
        WORKSPACE,
        NONCE,
    );
    includesPin(html, '<div class="passport-cell-value">expired</div>');
    excludesPin(html, '<div class="passport-cell-value">10m</div>');
});

test("P3 explicit duration_seconds wins over recomputing from the range", () => {
    const html = renderTrajectoryDetailHtml(
        {
            trajectory_id: "traj-explicit-duration",
            duration_seconds: 45,
            started_at_utc: "2026-08-21T10:00:00Z",
            finished_at_utc: "2026-08-21T10:05:00Z",
        },
        WORKSPACE,
        NONCE,
    );
    includesPin(html, '<div class="passport-cell-value">45s</div>');
    excludesPin(html, '<div class="passport-cell-value">5m</div>');
});

// --- P4: hostile strings never reach markup raw ---

const HOSTILE = '<img src=x onerror="pwn()">';
const HOSTILE_ESCAPED = "&lt;img src=x onerror=&quot;pwn()&quot;&gt;";

test("P4 dashboard escapes workspace name, agent label, and anomaly summary", () => {
    const html = renderTrajectoryDashboardHtml(
        {
            agents: {
                agent_count: 1,
                trajectory_count: 1,
                unlabeled_trajectory_count: 0,
                agents: [{agent_label: HOSTILE, trajectory_count: 1, intent_count: 1, failed_outcome_count: 0, anomaly_count: 0, incident_total: 0}],
            },
            anomalies: {
                summary: {trajectories_with_anomalies: 1, anomaly_count: 1, error_count: 1, warn_count: 0},
                trajectories: [
                    {trajectory_id: "traj-hostile", outcome: "violated", quality_tier: "flawed", summary: HOSTILE, anomalies: []},
                ],
            },
        },
        HOSTILE,
        NONCE,
    );
    includesPin(html, `Workspace: ${HOSTILE_ESCAPED}`);
    includesPin(html, `<td><code>${HOSTILE_ESCAPED}</code></td>`);
    includesPin(html, `<p class="meta">${HOSTILE_ESCAPED}</p>`);
    excludesPin(html, "<img");
});

test("P4 detail escapes workspace name, trajectory id, outcome, step summary, intent description", () => {
    const hostileScript = "<script>steal()</script> refactor formatters";
    const html = renderTrajectoryDetailHtml(
        {
            trajectory_id: HOSTILE,
            outcome: HOSTILE,
            steps: [
                {event_type: "intent.declared", summary: hostileScript, audit_sequence: 1},
            ],
        },
        HOSTILE,
        NONCE,
    );
    includesPin(html, `<code class="trajectory-id">${HOSTILE_ESCAPED}</code>`);
    includesPin(html, `Workspace: ${HOSTILE_ESCAPED}`);
    includesPin(html, `>${HOSTILE_ESCAPED}</span>`);
    includesPin(html, "&lt;script&gt;steal()&lt;/script&gt; refactor formatters");
    excludesPin(html, "<img");
    excludesPin(html, "<script>");
});

// --- P5: markdown export mirrors the HTML dashboard from one payload ---

function dashboardPayloadWithOneAgentAndOneAnomaly() {
    return {
        status: {
            trajectory_count: 37,
            latest_projection: {finished_at_utc: "2026-08-20T09:00:00Z", workflows_seen: 4, created: 2, updated: 1},
        },
        agents: {
            agent_count: 1,
            trajectory_count: 37,
            unlabeled_trajectory_count: 3,
            agents: [
                {agent_label: "agent-alpha", trajectory_count: 5, intent_count: 4, failed_outcome_count: 1, anomaly_count: 2, incident_total: 6},
            ],
        },
        anomalies: {
            summary: {trajectories_with_anomalies: 1, anomaly_count: 2, error_count: 1, warn_count: 1},
            trajectories: [
                {trajectory_id: "traj-x", outcome: "violated", quality_tier: "flawed", summary: "scope escaped twice", anomalies: []},
            ],
        },
    };
}

test("P5 HTML dashboard renders the shared payload facts", () => {
    const html = renderTrajectoryDashboardHtml(dashboardPayloadWithOneAgentAndOneAnomaly(), WORKSPACE, NONCE);
    includesPin(html, "<tr><th>Stored trajectories</th><td>37</td></tr>");
    includesPin(html, "<tr><th>Latest projection</th><td>2026-08-20T09:00:00Z · 4 workflows · +2/~1</td></tr>");
    includesPin(html, '<p class="meta">1 agents · 37 trajectories · 3 unlabeled</p>');
    includesPin(html, '<tr><td><code>agent-alpha</code></td><td class="num">5</td><td class="num">4</td><td class="num">1</td><td class="num">2</td><td class="num">6</td></tr>');
    includesPin(html, '<p class="banner banner-warn">1 trajectories with 2 anomaly tags (1 error / 1 warn)</p>');
    includesPin(html, '<div class="card-head"><code>traj-x</code> <span class="pill pill-bad">violated</span> <span class="pill">flawed</span></div>');
});

test("P5 markdown dashboard reads the same payload fields as the HTML dashboard", () => {
    const payload = dashboardPayloadWithOneAgentAndOneAnomaly();
    const html = renderTrajectoryDashboardHtml(payload, WORKSPACE, NONCE);
    const markdown = renderTrajectoryDashboardMarkdown(payload);
    includesPin(markdown, "- Stored trajectories: 37");
    includesPin(html, "<tr><th>Stored trajectories</th><td>37</td></tr>");
    includesPin(markdown, "- `agent-alpha`: 5 trajectories, 2 anomaly tags");
    includesPin(markdown, "- `traj-x` violated/flawed");
    includesPin(html, '<span class="pill pill-bad">violated</span> <span class="pill">flawed</span>');
});

// --- P6: empty and minimal payloads render a meaningful empty form ---

test("P6 dashboard on empty payload renders zeroed empty form without throwing", () => {
    const html = renderTrajectoryDashboardHtml(undefined, "empty-workspace", NONCE);
    includesPin(html, "<h1>Trajectory Dashboard</h1>");
    includesPin(html, "Workspace: empty-workspace");
    includesPin(html, "<tr><th>Stored trajectories</th><td>0</td></tr>");
    includesPin(html, "<tr><th>Latest projection</th><td>none</td></tr>");
    includesPin(html, "No agent-labeled trajectories yet");
    includesPin(html, "No anomalies detected in stored trajectories.");
});

test("P6 detail on empty payload renders placeholder pills, em-dash duration, empty timeline", () => {
    const html = renderTrajectoryDetailHtml(undefined, "empty-workspace", NONCE);
    includesPin(html, '<p class="muted">No steps returned.</p>');
    includesPin(html, '<span class="pill pill-warn">?</span>');
    includesPin(html, '<div class="passport-cell-label">Duration</div><div class="passport-cell-value">—</div>');
    includesPin(html, 'title="unknown"');
    includesPin(html, '<h2 class="section-heading">Patch trail</h2>');
});

test("P6 markdown on empty payload is the exact minimal document", () => {
    assert.equal(
        renderTrajectoryDashboardMarkdown(undefined),
        "# Trajectory dashboard\n\n- Stored trajectories: 0\n\n## Agents\n\n## Anomalies",
    );
});

test("P6 pick description on empty payload is the exact zero line", () => {
    assert.equal(formatTrajectoryPickDescription(undefined), "0 events · 0 incidents");
});

test("P6 pick description recovers incidents from the machine summary", () => {
    assert.equal(
        formatTrajectoryPickDescription({event_count: 3, summary: "workflow done incidents=7 clean"}),
        "3 events · 7 incidents",
    );
});

test("P6 pick description prefers structured incident_count over the summary text", () => {
    assert.equal(
        formatTrajectoryPickDescription({event_count: 3, incident_count: 2, summary: "incidents=9"}),
        "3 events · 2 incidents",
    );
});

test("P6 pick description keeps a zero quality score visible", () => {
    assert.equal(
        formatTrajectoryPickDescription({quality_score: 0}),
        "0 events · 0 incidents · 0/100 contract",
    );
});

test("P6 pick description appends agent label and start time in order", () => {
    assert.equal(
        formatTrajectoryPickDescription({agent_label: "agent-beta", started_at_utc: "2026-08-21T10:00:00Z"}),
        "0 events · 0 incidents · agent-beta · 2026-08-21 · 10:00:00 UTC",
    );
});
