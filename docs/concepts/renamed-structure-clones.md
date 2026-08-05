---
title: "Renamed-structure clones"
audience: public
doc_type: concept
status: draft
source_commit: "705196efd385d64131a12405045e1ea4637e4856"
---

## What it is

The strict exact tier deliberately keeps semantically meaningful names rigid,
so two functions that differ only in a consistent renaming — locals renamed,
`self`-attributes renamed, everything else identical — never match it. The
renamed-structure tier closes that gap with its own declared rule.

Two clone-eligible units group as renamed-structure clones when there exists a
**bijective, consistent renaming** between them:

- local bindings may rename;
- attributes on local, `self` or `cls` receivers may rename;
- the mapping is one-to-one and the same across the whole unit;
- everything else stays rigid.

## The rule

Equality in the tier's own digest domain — no pairwise matcher, no similarity
score, no tunable floor. Each unit is canonicalized once (renameable symbols
become ordinals; rigid symbols stay literal) and units with equal digests form
a group.

What stays rigid:

- imported identities and proven global names (`math.floor` is not a renaming
  of `math.trunc`);
- the terminal callee of a call (`obj.get()` never matches `obj.post()`), in
  every position the symbol appears;
- attribute-chain length and control-flow structure
  (`gateway.channel.send(x)` never matches `gateway.send(x)`, while renaming
  the intermediate `channel` to `pipe` is fine);
- any name whose status cannot be proven — the honest default is rigid.

The mapping is genuinely bijective and consistent: `a → x` in one place with
`a → y` in another does not match, and neither does collapsing `a` and `b`
onto one name. `a.x + b.x` stays distinguishable from `a.x + b.y`.

A group whose members already share one strict-exact fingerprint is the exact
tier's business and is not reported here.

## Opt-in and confinement

The channel is produced only with `--renamed-structure` (or
`renamed_structure = true` in `pyproject.toml`), off by default.

It is gate-neutral by construction rather than by a flag someone could flip:
renamed-structure groups never enter the clone groups, so they reach no
observation lane, no baseline novelty and no gate. Turning the flag on cannot
change an exit code.

```bash
codeclone --renamed-structure
```

## Related pages

- [Near-miss clones](near-miss-clones.md) — the sibling advisory tier for one-statement edits
- [Structural analysis](structural-analysis.md) — the clone tiers that do gate
- [Baseline container and lane trust](baseline-container.md) — the lanes this tier stays out of
