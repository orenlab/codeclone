<!-- doc-scope: TUTORIAL — narrated first governed-edit walkthrough.
     owns: the end-to-end declare→edit→verify tutorial narration.
     does-not-own: install / MCP setup (getting-started.md), the change-control
       how-to recipe (guide/mcp/workflows/change-control.md), the controller
       contract (book/12-structural-change-controller/index.md).
     rule: tutorial voice — one happy path; narrate what each call returns. -->

# Your first governed edit

CodeClone turns an ordinary edit into a *governed* edit: you declare what you
intend to change, edit inside that boundary, and the controller verifies the
patch and clears the intent with an auditable receipt. This tutorial walks one
small fix through the full cycle.

**Before you start:** [install CodeClone and connect your agent](../getting-started.md).
Every call below uses an **absolute** repository root — relative roots like `.`
are rejected.

## The cycle at a glance

```text
analyze_repository       → register a baseline "before" run
start_controlled_change  → declare scope; get edit permission + blast radius
get_relevant_memory      → load evidence-linked context for your scope
edit                     → change only files inside the declared scope
analyze_repository       → an "after" run for structural verification
finish_controlled_change → scope check + verify + receipt + clear intent
```

## 1. Analyze — register a before-run

```text
analyze_repository(root="/abs/path/to/repo")
```

Returns a `run_id` and a health snapshot. This run is the **before** state the
controller compares your edit against. Run it first — `start` needs an existing
run for the root.

## 2. Declare your intent

Say what you will touch *before you touch it*:

```text
start_controlled_change(
  root="/abs/path/to/repo",
  scope={"allowed_files": ["myapp/formatting.py"]},
  intent="Fix default rounding in format_ratio",
)
```

Read three fields in the response:

| Field | What it tells you |
|-------|-------------------|
| `edit_allowed` | `true` means you may edit — nothing before this authorizes a write |
| `scope.allowed_files` | the exact boundary; edits outside it are violations |
| `blast_radius.radius_level` | how far the change reaches (`low`/`medium`/`high`), plus dependents to review |

Keep the returned `intent_id` — `finish` needs it. If the response is `queued`,
another agent holds an overlapping intent: wait and promote rather than editing.

## 3. Load scoped memory

```text
get_relevant_memory(root="/abs/path/to/repo", intent_id="<intent_id>")
```

Returns evidence-linked `records` (asserted facts), `trajectories` (past workflow
runs over these files), and `experiences` (recurring patterns). Read any stale or
contradiction notes before you edit — they flag context that has changed. Memory
informs your edit; it never authorizes one.

## 4. Edit inside the boundary

Make the change — and only inside `allowed_files`:

```diff
- def format_ratio(value, digits=1):
+ def format_ratio(value, digits=2):
```

If the fix needs a file outside scope, **stop**. Re-run `start_controlled_change`
with a wider scope instead of silently editing extra files.

## 5. Analyze again — the after-run

```text
analyze_repository(root="/abs/path/to/repo")
```

For any Python change the controller needs this **after** run to verify there are
no structural regressions. Keep its `run_id`.

## 6. Finish — verify and clear

```text
finish_controlled_change(
  intent_id="<intent_id>",
  changed_files=["myapp/formatting.py"],
  after_run_id="<after run_id>",
)
```

The controller runs hygiene, scope check, and structural verify, builds the patch
trail, and on success issues a receipt and clears the intent:

| Field | Accept when |
|-------|-------------|
| `status` | `accepted` (or `accepted_with_external_changes`) |
| `scope_check.status` | `clean` or `expanded` |
| `intent_cleared` | `true` |

## The completion gate

Do **not** report the edit as done, verified, or ready until **all three** hold:

1. `finish` returned `accepted`,
2. `scope_check.status` is `clean` (or `expanded`), and
3. `intent_cleared` is `true`.

If `status` is `unverified` or `violated`, the intent stays active — follow the
`next_step` hint (often: re-run `analyze_repository` for a fresh after-run, then
`finish` again on the **same** `intent_id`). Never present an unverified patch as
finished.

## Where to go next

- [Change control recipe](../guide/mcp/workflows/change-control.md) — the how-to,
  including queue, promote, and the atomic fallback path.
- [Structural Change Controller](../book/12-structural-change-controller/index.md)
  — the normative contract: verification profiles, finish hygiene, receipts.
- [Engineering Memory](../guide/memory/overview.md) — what to record before you finish.
