# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Den Rozhnovskiy

"""Report Provenance / metadata panel renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ... import __version__, _coerce
from ..._html_data_attrs import _build_data_attrs
from ..._html_escape import _escape_html, _meta_display
from .._context import _meta_pick
from .._glossary import glossary_tip

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

    _BOOL = {
        "Baseline payload verified",
        "Baseline loaded",
        "Cache used",
        "Metrics baseline loaded",
        "Metrics baseline payload verified",
        "Digest verified",
    }

    def _val_html(label: str, value: object) -> str:
        if label in _BOOL and isinstance(value, bool):
            badge_cls = "meta-bool-true" if value else "meta-bool-false"
            return f'<span class="meta-bool {badge_cls}">{"true" if value else "false"}</span>'
        return _escape_html(_meta_display(value))

    meta_rows_html = "".join(
        '<section class="prov-section">'
        f'<h3 class="prov-section-title">{_escape_html(st)}</h3>'
        '<table class="prov-table"><tbody>'
        + "".join(
            f'<tr><td class="prov-td-label">{_escape_html(label)}'
            f"{glossary_tip(label)}</td>"
            f'<td class="prov-td-value">{_val_html(label, value)}</td></tr>'
            for label, value in rows
        )
        + "</tbody></table></section>"
        for st, rows in meta_sections
        if rows
    )

    def _prov_badge(label: str, color: str) -> str:
        return f'<span class="prov-badge {color}">{_escape_html(label)}</span>'

    badges: list[str] = []
    if _bl_verified is True:
        badges.append(_prov_badge("Baseline verified", "green"))
    elif _bl_loaded is True and _bl_verified is not True:
        badges.append(_prov_badge("Baseline untrusted", "red"))
    elif _bl_loaded is False or _bl_loaded is None:
        badges.append(_prov_badge("Baseline missing", "amber"))
    if ctx.report_schema_version:
        badges.append(_prov_badge(f"Schema {ctx.report_schema_version}", "neutral"))
    if _bl_fp_ver is not None:
        badges.append(_prov_badge(f"Fingerprint {_bl_fp_ver}", "neutral"))
    gen_name = str(_bl_gen_name or "")
    if gen_name and gen_name != "codeclone":
        badges.append(_prov_badge(f"Generator mismatch: {gen_name}", "red"))
    if _cache_used is True:
        badges.append(_prov_badge("Cache hit", "green"))
    elif _cache_used is False:
        badges.append(_prov_badge("Cache miss", "amber"))
    else:
        badges.append(_prov_badge("Cache N/A", "neutral"))
    analysis_mode = str(_meta_pick(meta.get("analysis_mode")) or "")
    if analysis_mode:
        badges.append(_prov_badge(f"Mode: {analysis_mode}", "neutral"))
    if _mbl_verified is True:
        badges.append(_prov_badge("Metrics baseline verified", "green"))
    elif _mbl_loaded is True and _mbl_verified is not True:
        badges.append(_prov_badge("Metrics baseline untrusted", "red"))

    sep = '<span class="prov-sep">\u00b7</span>'
    prov_summary = (
        f'<div class="prov-summary">{sep.join(badges)}'
        '<span class="prov-explain">Baseline-aware \u00b7 contract-verified</span></div>'
        if badges
        else ""
    )

    return (
        f'<dialog class="prov-modal" id="prov-modal"{meta_attrs}>'
        '<div class="prov-modal-head">'
        "<h2>Report Provenance</h2>"
        '<button class="modal-close" type="button" data-prov-close '
        'aria-label="Close">&times;</button></div>'
        f"{prov_summary}"
        f'<div class="prov-modal-body">{meta_rows_html}</div>'
        "</dialog>"
    )
