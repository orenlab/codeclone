# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
# SPDX-License-Identifier: MPL-2.0
# Copyright (c) 2026 Den Rozhnovskiy

"""Report Provenance / metadata panel renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from codeclone import __version__
from codeclone.utils import coerce as _coerce

from .._context import _meta_pick
from ..primitives.data_attrs import _build_data_attrs
from ..primitives.escape import _escape_html, _meta_display
from ..widgets.glossary import glossary_tip

if TYPE_CHECKING:
    from .._context import ReportContext

_as_mapping = _coerce.as_mapping
_as_sequence = _coerce.as_sequence


def _path_basename(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    normalized = text.replace("\\", "/").rstrip("/")
    if not normalized:
        return ""
    return normalized.rsplit("/", maxsplit=1)[-1]


_PATH_LABELS = frozenset(
    {
        "Scan root",
        "Baseline path",
        "Metrics baseline path",
        "Cache path",
        "Scan root absolute",
        "Baseline path absolute",
        "Cache path absolute",
        "Metrics baseline path absolute",
    }
)
_HASH_LABELS = frozenset(
    {
        "Baseline payload sha256",
        "Metrics baseline payload sha256",
        "Digest value",
    }
)


def _truncate_middle(value: str, head: int, tail: int) -> str:
    """Shorten *value* with a middle ellipsis when it exceeds head+tail+1."""
    if len(value) <= head + tail + 1:
        return value
    return f"{value[:head]}\u2026{value[-tail:]}"


def _prov_badge_html(label: str | None, value: str, color: str) -> str:
    classes = ["prov-badge", f"prov-badge--{color}"]
    if label is None:
        classes.append("prov-badge--inline")
    label_html = (
        f'<span class="prov-badge-lbl">{_escape_html(label)}</span>'
        if label is not None
        else ""
    )
    return (
        f'<span class="{" ".join(classes)}">'
        f'<span class="prov-badge-val">{_escape_html(value)}</span>'
        f"{label_html}"
        "</span>"
    )


def build_topbar_provenance_summary(ctx: ReportContext) -> tuple[str, str, str]:
    """Return (status_label, status_color, tooltip_text) for the topbar pill.

    Collapses the full provenance state into a single word + colour +
    hover tooltip. The detail lives in the modal, not the topbar.
    """
    meta = ctx.meta
    baseline_meta = ctx.baseline_meta
    cache_meta = ctx.cache_meta

    bl_verified = _meta_pick(
        meta.get("baseline_payload_sha256_verified"),
        baseline_meta.get("payload_sha256_verified"),
    )
    bl_loaded = _meta_pick(meta.get("baseline_loaded"), baseline_meta.get("loaded"))
    cache_used = _meta_pick(meta.get("cache_used"), cache_meta.get("used"))
    analysis_mode = str(_meta_pick(meta.get("analysis_mode")) or "").strip()

    bl_part: str
    bl_color: str
    if bl_verified is True:
        bl_part, bl_color = "Baseline verified", "green"
    elif bl_loaded is True and bl_verified is not True:
        bl_part, bl_color = "Baseline untrusted", "red"
    elif bl_loaded is False or bl_loaded is None:
        bl_part, bl_color = "No baseline", "amber"
    else:
        bl_part, bl_color = "Baseline state unknown", "neutral"

    cache_part = ""
    if cache_used is True:
        cache_part = "cache hit"
    elif cache_used is False:
        cache_part = "cache miss"

    mode_part = f"{analysis_mode} mode" if analysis_mode else ""

    tooltip_bits = [p for p in (bl_part, cache_part, mode_part) if p]
    tooltip = " \u00b7 ".join(tooltip_bits) if tooltip_bits else "Report provenance"

    label_map = {
        "green": "Verified",
        "amber": "Partial",
        "red": "Unverified",
        "neutral": "Provenance",
    }
    status_label = label_map[bl_color]
    return status_label, bl_color, tooltip


def render_meta_panel(ctx: ReportContext) -> str:
    """Build the collapsible Report Provenance panel."""
    meta = ctx.meta
    baseline_meta = ctx.baseline_meta
    cache_meta, metrics_baseline_meta, runtime_meta, integrity_map = (
        ctx.cache_meta,
        ctx.metrics_baseline_meta,
        ctx.runtime_meta,
        ctx.integrity_map,
    )

    baseline_path_value = _meta_pick(
        meta.get("baseline_path"),
        baseline_meta.get("path"),
        runtime_meta.get("baseline_path_absolute"),
    )
    cache_path_value = _meta_pick(
        meta.get("cache_path"),
        cache_meta.get("path"),
        runtime_meta.get("cache_path_absolute"),
    )
    mbl_path_value = _meta_pick(
        meta.get("metrics_baseline_path"),
        metrics_baseline_meta.get("path"),
        runtime_meta.get("metrics_baseline_path_absolute"),
    )
    scan_root_value = _meta_pick(
        meta.get("scan_root"), runtime_meta.get("scan_root_absolute")
    )
    python_tag_value = _meta_pick(meta.get("python_tag"))
    report_mode_value = _meta_pick(meta.get("report_mode"), "full")
    metrics_computed_value = _meta_pick(
        meta.get("metrics_computed"),
        meta.get("computed_metric_families"),
    )
    integrity_canon = _as_mapping(integrity_map.get("canonicalization"))
    integrity_digest = _as_mapping(integrity_map.get("digest"))
    canonical_sections = ", ".join(
        str(i) for i in _as_sequence(integrity_canon.get("sections")) if str(i).strip()
    )

    general_rows: list[tuple[str, object]] = [
        ("CodeClone", _meta_pick(meta.get("codeclone_version"), __version__)),
        ("Project", _meta_pick(meta.get("project_name"))),
        ("Report schema", ctx.report_schema_version),
        ("Scan root", scan_root_value),
        ("Python", _meta_pick(meta.get("python_version"))),
        ("Python tag", python_tag_value),
        ("Analysis mode", _meta_pick(meta.get("analysis_mode"))),
        ("Report mode", report_mode_value),
        ("Report generated (UTC)", ctx.report_generated_at),
        (
            "Metrics computed",
            ", ".join(str(i) for i in _as_sequence(metrics_computed_value)),
        ),
        ("Health score", _meta_pick(meta.get("health_score"))),
        ("Health grade", _meta_pick(meta.get("health_grade"))),
        ("Source IO skipped", _meta_pick(meta.get("files_skipped_source_io"))),
    ]

    _bl_status = _meta_pick(meta.get("baseline_status"), baseline_meta.get("status"))
    _bl_loaded = _meta_pick(meta.get("baseline_loaded"), baseline_meta.get("loaded"))
    _bl_fp_ver = _meta_pick(
        meta.get("baseline_fingerprint_version"),
        baseline_meta.get("fingerprint_version"),
    )
    _bl_schema_ver = _meta_pick(
        meta.get("baseline_schema_version"), baseline_meta.get("schema_version")
    )
    _bl_py_tag = _meta_pick(
        meta.get("baseline_python_tag"), baseline_meta.get("python_tag")
    )
    _bl_gen_name = _meta_pick(
        meta.get("baseline_generator_name"), baseline_meta.get("generator_name")
    )
    _bl_gen_ver = _meta_pick(
        meta.get("baseline_generator_version"), baseline_meta.get("generator_version")
    )
    _bl_sha256 = _meta_pick(
        meta.get("baseline_payload_sha256"), baseline_meta.get("payload_sha256")
    )
    _bl_verified = _meta_pick(
        meta.get("baseline_payload_sha256_verified"),
        baseline_meta.get("payload_sha256_verified"),
    )

    bl_rows: list[tuple[str, object]] = [
        ("Baseline file", _path_basename(baseline_path_value)),
        ("Baseline path", baseline_path_value),
        ("Baseline status", _bl_status),
        ("Baseline loaded", _bl_loaded),
        ("Baseline fingerprint", _bl_fp_ver),
        ("Baseline schema", _bl_schema_ver),
        ("Baseline Python tag", _bl_py_tag),
        ("Baseline generator name", _bl_gen_name),
        ("Baseline generator version", _bl_gen_ver),
        ("Baseline payload sha256", _bl_sha256),
        ("Baseline payload verified", _bl_verified),
    ]

    _mbl_loaded = _meta_pick(
        meta.get("metrics_baseline_loaded"), metrics_baseline_meta.get("loaded")
    )
    _mbl_status = _meta_pick(
        meta.get("metrics_baseline_status"), metrics_baseline_meta.get("status")
    )
    _mbl_schema_ver = _meta_pick(
        meta.get("metrics_baseline_schema_version"),
        metrics_baseline_meta.get("schema_version"),
    )
    _mbl_sha256 = _meta_pick(
        meta.get("metrics_baseline_payload_sha256"),
        metrics_baseline_meta.get("payload_sha256"),
    )
    _mbl_verified = _meta_pick(
        meta.get("metrics_baseline_payload_sha256_verified"),
        metrics_baseline_meta.get("payload_sha256_verified"),
    )

    mbl_rows: list[tuple[str, object]] = [
        ("Metrics baseline path", mbl_path_value),
        ("Metrics baseline loaded", _mbl_loaded),
        ("Metrics baseline status", _mbl_status),
        ("Metrics baseline schema", _mbl_schema_ver),
        ("Metrics baseline payload sha256", _mbl_sha256),
        ("Metrics baseline payload verified", _mbl_verified),
    ]

    _cache_schema_ver = _meta_pick(
        meta.get("cache_schema_version"), cache_meta.get("schema_version")
    )
    _cache_status = _meta_pick(meta.get("cache_status"), cache_meta.get("status"))
    _cache_used = _meta_pick(meta.get("cache_used"), cache_meta.get("used"))

    cache_rows: list[tuple[str, object]] = [
        ("Cache path", cache_path_value),
        ("Cache schema", _cache_schema_ver),
        ("Cache status", _cache_status),
        ("Cache used", _cache_used),
    ]

    rt_rows = [
        r
        for r in (
            ("Scan root absolute", runtime_meta.get("scan_root_absolute")),
            ("Baseline path absolute", runtime_meta.get("baseline_path_absolute")),
            ("Cache path absolute", runtime_meta.get("cache_path_absolute")),
            (
                "Metrics baseline path absolute",
                runtime_meta.get("metrics_baseline_path_absolute"),
            ),
        )
        if _meta_pick(r[1]) is not None
    ]

    integ_rows = [
        r
        for r in (
            ("Canonicalization version", integrity_canon.get("version")),
            ("Canonicalization scope", integrity_canon.get("scope")),
            ("Canonical sections", canonical_sections),
            ("Digest algorithm", integrity_digest.get("algorithm")),
            ("Digest value", integrity_digest.get("value")),
            ("Digest verified", integrity_digest.get("verified")),
        )
        if _meta_pick(r[1]) is not None
    ]

    meta_sections = [
        ("General", general_rows),
        ("Clone Baseline", bl_rows),
        ("Metrics Baseline", mbl_rows),
        ("Cache", cache_rows),
        ("Runtime", rt_rows),
        ("Integrity", integ_rows),
    ]

    # Data attrs
    metrics_csv = ",".join(str(i) for i in _as_sequence(metrics_computed_value))
    meta_attrs = _build_data_attrs(
        {
            "data-report-schema-version": ctx.report_schema_version,
            "data-codeclone-version": meta.get("codeclone_version", __version__),
            "data-project-name": meta.get("project_name"),
            "data-scan-root": scan_root_value,
            "data-python-version": meta.get("python_version"),
            "data-python-tag": python_tag_value,
            "data-analysis-mode": meta.get("analysis_mode"),
            "data-report-mode": report_mode_value,
            "data-report-generated-at-utc": ctx.report_generated_at,
            "data-metrics-computed": metrics_csv,
            "data-health-score": meta.get("health_score"),
            "data-health-grade": meta.get("health_grade"),
            "data-baseline-file": _path_basename(baseline_path_value),
            "data-baseline-path": baseline_path_value,
            "data-baseline-fingerprint-version": _bl_fp_ver,
            "data-baseline-schema-version": _bl_schema_ver,
            "data-baseline-python-tag": _bl_py_tag,
            "data-baseline-generator-name": _bl_gen_name,
            "data-baseline-generator-version": _bl_gen_ver,
            "data-baseline-payload-sha256": _bl_sha256,
            "data-baseline-payload-verified": _meta_display(_bl_verified),
            "data-baseline-loaded": _meta_display(_bl_loaded),
            "data-baseline-status": _bl_status,
            "data-cache-path": cache_path_value,
            "data-cache-schema-version": _cache_schema_ver,
            "data-cache-status": _cache_status,
            "data-cache-used": _meta_display(_cache_used),
            "data-files-skipped-source-io": meta.get("files_skipped_source_io"),
            "data-metrics-baseline-path": mbl_path_value,
            "data-metrics-baseline-loaded": _meta_display(_mbl_loaded),
            "data-metrics-baseline-status": _mbl_status,
            "data-metrics-baseline-schema-version": _mbl_schema_ver,
            "data-metrics-baseline-payload-sha256": _mbl_sha256,
            "data-metrics-baseline-payload-verified": _meta_display(_mbl_verified),
            "data-runtime-scan-root-absolute": runtime_meta.get("scan_root_absolute"),
            "data-runtime-baseline-path-absolute": runtime_meta.get(
                "baseline_path_absolute"
            ),
            "data-runtime-cache-path-absolute": runtime_meta.get("cache_path_absolute"),
            "data-runtime-metrics-baseline-path-absolute": runtime_meta.get(
                "metrics_baseline_path_absolute"
            ),
            "data-canonicalization-version": integrity_canon.get("version"),
            "data-canonicalization-scope": integrity_canon.get("scope"),
            "data-canonical-sections": canonical_sections,
            "data-digest-algorithm": integrity_digest.get("algorithm"),
            "data-digest-value": integrity_digest.get("value"),
            "data-digest-verified": _meta_display(integrity_digest.get("verified")),
        }
    )

    _BOOL_LABELS: dict[str, tuple[str, str]] = {
        "Baseline payload verified": ("verified", "unverified"),
        "Baseline loaded": ("loaded", "not loaded"),
        "Cache used": ("hit", "miss"),
        "Metrics baseline loaded": ("loaded", "not loaded"),
        "Metrics baseline payload verified": ("verified", "unverified"),
        "Digest verified": ("verified", "unverified"),
    }
    _STATUS_LABELS = frozenset(
        {"Baseline status", "Metrics baseline status", "Cache status"}
    )
    _prov_badge = _prov_badge_html

    runtime_python_tag = str(python_tag_value or "").strip()

    def _val_html(label: str, value: object) -> str:
        if label in _BOOL_LABELS and isinstance(value, bool):
            true_text, false_text = _BOOL_LABELS[label]
            return _prov_badge(
                None,
                true_text if value else false_text,
                "green" if value else "red",
            )
        if label in _STATUS_LABELS and isinstance(value, str) and value.strip():
            raw = value.strip()
            key = raw.lower()
            if key == "ok":
                color = "green"
                text = "ok"
            elif key in {"error", "failed", "fail"}:
                color = "red"
                text = raw
            elif key in {"missing", "absent", "none"}:
                color = "amber"
                text = raw
            else:
                color = "neutral"
                text = raw
            return _prov_badge(None, text, color)
        # Long path/hash values: middle-truncate with copy button + full title
        if (
            isinstance(value, str)
            and value
            and (label in _PATH_LABELS or label in _HASH_LABELS)
        ):
            full = value.strip()
            if label in _HASH_LABELS:
                short = _truncate_middle(full, 8, 8)
            else:
                short = _truncate_middle(full, 24, 28)
            title = _escape_html(full)
            copy_payload = _escape_html(full)
            return (
                '<span class="prov-mono-trunc" '
                f'title="{title}">{_escape_html(short)}</span>'
                f'<button type="button" class="prov-copy-btn" '
                f'data-prov-copy="{copy_payload}" '
                f'aria-label="Copy {_escape_html(label)}">'
                '<svg viewBox="0 0 16 16" width="12" height="12" '
                'fill="none" stroke="currentColor" stroke-width="1.5">'
                '<rect x="4" y="4" width="9" height="9" rx="1.2"/>'
                '<path d="M3 11V3.5C3 2.7 3.7 2 4.5 2H11"/></svg>'
                "</button>"
            )
        # Runtime-match badge for baseline python tag
        if (
            label == "Baseline Python tag"
            and isinstance(value, str)
            and runtime_python_tag
        ):
            text = _escape_html(value)
            if value.strip() == runtime_python_tag:
                badge = _prov_badge(None, "matches runtime", "green")
            else:
                badge = _prov_badge(None, f"runtime {runtime_python_tag}", "amber")
            return f"{text} {badge}"
        return _escape_html(_meta_display(value))

    _SECTION_ICONS: dict[str, str] = {
        "General": (
            '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">'
            '<circle cx="8" cy="8" r="6.5"/><path d="M8 5v3"/><circle cx="8" cy="11" r=".5" fill="currentColor"/></svg>'
        ),
        "Clone Baseline": (
            '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">'
            '<path d="M2 4h12M2 8h12M2 12h8"/></svg>'
        ),
        "Metrics Baseline": (
            '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">'
            '<path d="M3 13V7M7 13V3M11 13V9M15 13V5"/></svg>'
        ),
        "Cache": (
            '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">'
            '<ellipse cx="8" cy="4" rx="6" ry="2.5"/><path d="M2 4v4c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V4"/>'
            '<path d="M2 8v4c0 1.4 2.7 2.5 6 2.5s6-1.1 6-2.5V8"/></svg>'
        ),
        "Runtime": (
            '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">'
            '<rect x="2" y="3" width="12" height="10" rx="1.5"/><path d="M5 7l2 2 4-4"/></svg>'
        ),
        "Integrity": (
            '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">'
            '<path d="M8 1.5L2 4v4c0 3.5 2.5 6 6 7 3.5-1 6-3.5 6-7V4z"/><path d="M5.5 8l2 2 3.5-4"/></svg>'
        ),
    }

    def _section_html(title: str, rows: list[tuple[str, object]]) -> str:
        icon = _SECTION_ICONS.get(title, "")
        visible_rows = [
            (label_name, value)
            for label_name, value in rows
            if _meta_pick(value) is not None
        ]
        if not visible_rows:
            return ""
        row_html = "".join(
            f'<tr><td class="prov-td-label">{_escape_html(label)}'
            f"{glossary_tip(label)}</td>"
            f'<td class="prov-td-value">{_val_html(label, value)}</td></tr>'
            for label, value in visible_rows
        )
        return (
            '<section class="prov-section">'
            f'<h3 class="prov-section-title">{icon}{_escape_html(title)}</h3>'
            f'<table class="prov-table"><tbody>{row_html}</tbody></table></section>'
        )

    meta_rows_html = "".join(
        _section_html(st, rows) for st, rows in meta_sections if rows
    )

    badges: list[str] = []
    if _bl_verified is True:
        badges.append(_prov_badge("Baseline", "verified", "green"))
    elif _bl_loaded is True and _bl_verified is not True:
        badges.append(_prov_badge("Baseline", "untrusted", "red"))
    elif _bl_loaded is False or _bl_loaded is None:
        badges.append(_prov_badge("Baseline", "missing", "amber"))
    if ctx.report_schema_version:
        badges.append(_prov_badge("Schema", str(ctx.report_schema_version), "neutral"))
    if _bl_fp_ver is not None:
        badges.append(_prov_badge("Fingerprint", str(_bl_fp_ver), "neutral"))
    gen_name = str(_bl_gen_name or "")
    if gen_name and gen_name != "codeclone":
        badges.append(_prov_badge("Generator mismatch", gen_name, "red"))
    if _cache_used is True:
        badges.append(_prov_badge("Cache", "hit", "green"))
    elif _cache_used is False:
        badges.append(_prov_badge("Cache", "miss", "amber"))
    else:
        badges.append(_prov_badge("Cache", "N/A", "neutral"))
    analysis_mode = str(_meta_pick(meta.get("analysis_mode")) or "")
    if analysis_mode:
        badges.append(_prov_badge("Mode", analysis_mode, "neutral"))
    if _mbl_verified is True:
        badges.append(_prov_badge("Metrics baseline", "verified", "green"))
    elif _mbl_loaded is True and _mbl_verified is not True:
        badges.append(_prov_badge("Metrics baseline", "untrusted", "red"))

    status_label, status_color, tooltip = build_topbar_provenance_summary(ctx)
    hero_icon = (
        '<svg class="prov-hero-icon" viewBox="0 0 24 24" width="22" height="22" '
        'fill="none" stroke="currentColor" stroke-width="1.8" '
        'stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 2.5L4 5.5v6c0 5 3.5 8.5 8 10 4.5-1.5 8-5 8-10v-6z"/>'
        '<path d="M8.5 12l2.5 2.5L16 9"/></svg>'
    )
    hero_html = (
        f'<div class="prov-hero prov-hero--{status_color}">'
        f'<div class="prov-hero-badge">{hero_icon}'
        f'<span class="prov-hero-label">{_escape_html(status_label)}</span></div>'
        f'<div class="prov-hero-text">'
        f'<h2 class="prov-hero-title">Report Provenance</h2>'
        f'<p class="prov-hero-sub">{_escape_html(tooltip)}</p>'
        "</div>"
        '<button class="modal-close prov-hero-close" type="button" data-prov-close '
        'aria-label="Close">&times;</button>'
        "</div>"
    )

    prov_summary = (
        f'<div class="prov-summary">{"".join(badges)}'
        '<span class="prov-explain">Baseline-aware \u00b7 contract-verified</span></div>'
        if badges
        else ""
    )

    return (
        f'<dialog class="prov-modal" id="prov-modal"{meta_attrs}>'
        f"{hero_html}"
        f"{prov_summary}"
        f'<div class="prov-modal-body">{meta_rows_html}</div>'
        "</dialog>"
    )
