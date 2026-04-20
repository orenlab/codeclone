from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, cast

from .. import ui_messages as ui
from ..contracts import (
    DEFAULT_COHESION_THRESHOLD,
    DEFAULT_COMPLEXITY_THRESHOLD,
    DEFAULT_COUPLING_THRESHOLD,
    DEFAULT_HEALTH_THRESHOLD,
)

CliKind = Literal[
    "positional",
    "value",
    "optional_path",
    "bool_optional",
    "store_true",
    "store_false",
    "help",
    "version",
]

DEFAULT_ROOT = "."
DEFAULT_MIN_LOC = 10
DEFAULT_MIN_STMT = 6
DEFAULT_BLOCK_MIN_LOC = 20
DEFAULT_BLOCK_MIN_STMT = 8
DEFAULT_SEGMENT_MIN_LOC = 20
DEFAULT_SEGMENT_MIN_STMT = 10
DEFAULT_PROCESSES = 4
DEFAULT_MAX_CACHE_SIZE_MB = 50
DEFAULT_MAX_BASELINE_SIZE_MB = 5

DEFAULT_BASELINE_PATH = "codeclone.baseline.json"
DEFAULT_HTML_REPORT_PATH = ".cache/codeclone/report.html"
DEFAULT_JSON_REPORT_PATH = ".cache/codeclone/report.json"
DEFAULT_MARKDOWN_REPORT_PATH = ".cache/codeclone/report.md"
DEFAULT_SARIF_REPORT_PATH = ".cache/codeclone/report.sarif"
DEFAULT_TEXT_REPORT_PATH = ".cache/codeclone/report.txt"

_UNSET: Final[object] = object()
_INFER_PYPROJECT_KEY: Final[object] = object()


@dataclass(frozen=True, slots=True)
class ConfigKeySpec:
    expected_type: type[object]
    allow_none: bool = False
    expected_name: str | None = None


@dataclass(frozen=True, slots=True)
class OptionSpec:
    dest: str
    group: str | None
    cli_kind: CliKind | None = None
    flags: tuple[str, ...] = ()
    default: object = _UNSET
    value_type: type[object] | None = None
    const: object | None = None
    nargs: str | int | None = None
    metavar: str | None = None
    help_text: str | None = None
    pyproject_key: str | None = None
    config_spec: ConfigKeySpec | None = None
    path_value: bool = False

    @property
    def has_default(self) -> bool:
        return self.default is not _UNSET


def _option(
    *,
    dest: str,
    group: str | None,
    cli_kind: CliKind | None = None,
    flags: tuple[str, ...] = (),
    default: object = _UNSET,
    value_type: type[object] | None = None,
    const: object | None = None,
    nargs: str | int | None = None,
    metavar: str | None = None,
    help_text: str | None = None,
    pyproject_type: type[object] | None = None,
    allow_none: bool = False,
    expected_name: str | None = None,
    pyproject_key: object = _INFER_PYPROJECT_KEY,
    path_value: bool = False,
) -> OptionSpec:
    config_spec = (
        ConfigKeySpec(
            expected_type=pyproject_type,
            allow_none=allow_none,
            expected_name=expected_name,
        )
        if pyproject_type is not None
        else None
    )
    resolved_pyproject_key: str | None
    if pyproject_type is None:
        resolved_pyproject_key = None
    elif pyproject_key is _INFER_PYPROJECT_KEY:
        resolved_pyproject_key = dest
    else:
        resolved_pyproject_key = cast("str | None", pyproject_key)
    return OptionSpec(
        dest=dest,
        group=group,
        cli_kind=cli_kind,
        flags=flags,
        default=default,
        value_type=value_type,
        const=const,
        nargs=nargs,
        metavar=metavar,
        help_text=help_text,
        pyproject_key=resolved_pyproject_key,
        config_spec=config_spec,
        path_value=path_value,
    )


ARGUMENT_GROUP_TITLES: Final[tuple[str, ...]] = (
    "Target",
    "Analysis",
    "Baselines and CI",
    "Quality gates",
    "Analysis stages",
    "Reporting",
    "Output and UI",
    "General",
)

OPTIONS: Final[tuple[OptionSpec, ...]] = (
    _option(
        dest="root",
        group="Target",
        cli_kind="positional",
        default=DEFAULT_ROOT,
        nargs="?",
        help_text=ui.HELP_ROOT,
    ),
    _option(
        dest="min_loc",
        group="Analysis",
        cli_kind="value",
        flags=("--min-loc",),
        default=DEFAULT_MIN_LOC,
        value_type=int,
        help_text=ui.HELP_MIN_LOC,
        pyproject_type=int,
    ),
    _option(
        dest="min_stmt",
        group="Analysis",
        cli_kind="value",
        flags=("--min-stmt",),
        default=DEFAULT_MIN_STMT,
        value_type=int,
        help_text=ui.HELP_MIN_STMT,
        pyproject_type=int,
    ),
    _option(
        dest="block_min_loc",
        group="Analysis",
        default=DEFAULT_BLOCK_MIN_LOC,
        pyproject_type=int,
    ),
    _option(
        dest="block_min_stmt",
        group="Analysis",
        default=DEFAULT_BLOCK_MIN_STMT,
        pyproject_type=int,
    ),
    _option(
        dest="segment_min_loc",
        group="Analysis",
        default=DEFAULT_SEGMENT_MIN_LOC,
        pyproject_type=int,
    ),
    _option(
        dest="segment_min_stmt",
        group="Analysis",
        default=DEFAULT_SEGMENT_MIN_STMT,
        pyproject_type=int,
    ),
    _option(
        dest="golden_fixture_paths",
        group="Analysis",
        default=(),
        pyproject_type=list,
        expected_name="list[str]",
    ),
    _option(
        dest="processes",
        group="Analysis",
        cli_kind="value",
        flags=("--processes",),
        default=DEFAULT_PROCESSES,
        value_type=int,
        help_text=ui.HELP_PROCESSES,
        pyproject_type=int,
    ),
    _option(
        dest="changed_only",
        group="Analysis",
        cli_kind="bool_optional",
        flags=("--changed-only",),
        default=False,
        help_text=ui.HELP_CHANGED_ONLY,
    ),
    _option(
        dest="diff_against",
        group="Analysis",
        cli_kind="value",
        flags=("--diff-against",),
        default=None,
        metavar="GIT_REF",
        help_text=ui.HELP_DIFF_AGAINST,
    ),
    _option(
        dest="paths_from_git_diff",
        group="Analysis",
        cli_kind="value",
        flags=("--paths-from-git-diff",),
        default=None,
        metavar="GIT_REF",
        help_text=ui.HELP_PATHS_FROM_GIT_DIFF,
    ),
    _option(
        dest="cache_path",
        group="Analysis",
        cli_kind="optional_path",
        flags=("--cache-path",),
        default=None,
        metavar="FILE",
        help_text=ui.HELP_CACHE_PATH,
        pyproject_type=str,
        allow_none=True,
        path_value=True,
    ),
    _option(
        dest="cache_path",
        group="Analysis",
        cli_kind="optional_path",
        flags=("--cache-dir",),
        metavar="FILE",
        help_text=ui.HELP_CACHE_DIR_LEGACY,
        pyproject_key=None,
    ),
    _option(
        dest="max_cache_size_mb",
        group="Analysis",
        cli_kind="value",
        flags=("--max-cache-size-mb",),
        default=DEFAULT_MAX_CACHE_SIZE_MB,
        value_type=int,
        metavar="MB",
        help_text=ui.HELP_MAX_CACHE_SIZE_MB,
        pyproject_type=int,
    ),
    _option(
        dest="baseline",
        group="Baselines and CI",
        cli_kind="optional_path",
        flags=("--baseline",),
        default=DEFAULT_BASELINE_PATH,
        const=DEFAULT_BASELINE_PATH,
        metavar="FILE",
        help_text=ui.HELP_BASELINE,
        pyproject_type=str,
        path_value=True,
    ),
    _option(
        dest="max_baseline_size_mb",
        group="Baselines and CI",
        cli_kind="value",
        flags=("--max-baseline-size-mb",),
        default=DEFAULT_MAX_BASELINE_SIZE_MB,
        value_type=int,
        metavar="MB",
        help_text=ui.HELP_MAX_BASELINE_SIZE_MB,
        pyproject_type=int,
    ),
    _option(
        dest="update_baseline",
        group="Baselines and CI",
        cli_kind="bool_optional",
        flags=("--update-baseline",),
        default=False,
        help_text=ui.HELP_UPDATE_BASELINE,
        pyproject_type=bool,
    ),
    _option(
        dest="metrics_baseline",
        group="Baselines and CI",
        cli_kind="optional_path",
        flags=("--metrics-baseline",),
        default=DEFAULT_BASELINE_PATH,
        const=DEFAULT_BASELINE_PATH,
        metavar="FILE",
        help_text=ui.HELP_METRICS_BASELINE,
        pyproject_type=str,
        path_value=True,
    ),
    _option(
        dest="update_metrics_baseline",
        group="Baselines and CI",
        cli_kind="bool_optional",
        flags=("--update-metrics-baseline",),
        default=False,
        help_text=ui.HELP_UPDATE_METRICS_BASELINE,
        pyproject_type=bool,
    ),
    _option(
        dest="ci",
        group="Baselines and CI",
        cli_kind="bool_optional",
        flags=("--ci",),
        default=False,
        help_text=ui.HELP_CI,
        pyproject_type=bool,
    ),
    _option(
        dest="api_surface",
        group="Baselines and CI",
        cli_kind="bool_optional",
        flags=("--api-surface",),
        default=False,
        help_text=ui.HELP_API_SURFACE,
        pyproject_type=bool,
    ),
    _option(
        dest="coverage_xml",
        group="Baselines and CI",
        cli_kind="value",
        flags=("--coverage",),
        default=None,
        metavar="FILE",
        help_text=ui.HELP_COVERAGE,
        pyproject_type=str,
        allow_none=True,
        path_value=True,
    ),
    _option(
        dest="fail_on_new",
        group="Quality gates",
        cli_kind="bool_optional",
        flags=("--fail-on-new",),
        default=False,
        help_text=ui.HELP_FAIL_ON_NEW,
        pyproject_type=bool,
    ),
    _option(
        dest="fail_on_new_metrics",
        group="Quality gates",
        cli_kind="bool_optional",
        flags=("--fail-on-new-metrics",),
        default=False,
        help_text=ui.HELP_FAIL_ON_NEW_METRICS,
        pyproject_type=bool,
    ),
    _option(
        dest="fail_threshold",
        group="Quality gates",
        cli_kind="value",
        flags=("--fail-threshold",),
        default=-1,
        value_type=int,
        metavar="MAX_CLONES",
        help_text=ui.HELP_FAIL_THRESHOLD,
        pyproject_type=int,
    ),
    _option(
        dest="fail_complexity",
        group="Quality gates",
        cli_kind="value",
        flags=("--fail-complexity",),
        default=-1,
        value_type=int,
        nargs="?",
        const=DEFAULT_COMPLEXITY_THRESHOLD,
        metavar="CC_MAX",
        help_text=ui.HELP_FAIL_COMPLEXITY,
        pyproject_type=int,
    ),
    _option(
        dest="fail_coupling",
        group="Quality gates",
        cli_kind="value",
        flags=("--fail-coupling",),
        default=-1,
        value_type=int,
        nargs="?",
        const=DEFAULT_COUPLING_THRESHOLD,
        metavar="CBO_MAX",
        help_text=ui.HELP_FAIL_COUPLING,
        pyproject_type=int,
    ),
    _option(
        dest="fail_cohesion",
        group="Quality gates",
        cli_kind="value",
        flags=("--fail-cohesion",),
        default=-1,
        value_type=int,
        nargs="?",
        const=DEFAULT_COHESION_THRESHOLD,
        metavar="LCOM4_MAX",
        help_text=ui.HELP_FAIL_COHESION,
        pyproject_type=int,
    ),
    _option(
        dest="fail_cycles",
        group="Quality gates",
        cli_kind="bool_optional",
        flags=("--fail-cycles",),
        default=False,
        help_text=ui.HELP_FAIL_CYCLES,
        pyproject_type=bool,
    ),
    _option(
        dest="fail_dead_code",
        group="Quality gates",
        cli_kind="bool_optional",
        flags=("--fail-dead-code",),
        default=False,
        help_text=ui.HELP_FAIL_DEAD_CODE,
        pyproject_type=bool,
    ),
    _option(
        dest="fail_health",
        group="Quality gates",
        cli_kind="value",
        flags=("--fail-health",),
        default=-1,
        value_type=int,
        nargs="?",
        const=DEFAULT_HEALTH_THRESHOLD,
        metavar="SCORE_MIN",
        help_text=ui.HELP_FAIL_HEALTH,
        pyproject_type=int,
    ),
    _option(
        dest="fail_on_typing_regression",
        group="Quality gates",
        cli_kind="bool_optional",
        flags=("--fail-on-typing-regression",),
        default=False,
        help_text=ui.HELP_FAIL_ON_TYPING_REGRESSION,
        pyproject_type=bool,
    ),
    _option(
        dest="fail_on_docstring_regression",
        group="Quality gates",
        cli_kind="bool_optional",
        flags=("--fail-on-docstring-regression",),
        default=False,
        help_text=ui.HELP_FAIL_ON_DOCSTRING_REGRESSION,
        pyproject_type=bool,
    ),
    _option(
        dest="fail_on_api_break",
        group="Quality gates",
        cli_kind="bool_optional",
        flags=("--fail-on-api-break",),
        default=False,
        help_text=ui.HELP_FAIL_ON_API_BREAK,
        pyproject_type=bool,
    ),
    _option(
        dest="fail_on_untested_hotspots",
        group="Quality gates",
        cli_kind="bool_optional",
        flags=("--fail-on-untested-hotspots",),
        default=False,
        help_text=ui.HELP_FAIL_ON_UNTESTED_HOTSPOTS,
        pyproject_type=bool,
    ),
    _option(
        dest="min_typing_coverage",
        group="Quality gates",
        cli_kind="value",
        flags=("--min-typing-coverage",),
        default=-1,
        value_type=int,
        metavar="PERCENT",
        help_text=ui.HELP_MIN_TYPING_COVERAGE,
        pyproject_type=int,
    ),
    _option(
        dest="min_docstring_coverage",
        group="Quality gates",
        cli_kind="value",
        flags=("--min-docstring-coverage",),
        default=-1,
        value_type=int,
        metavar="PERCENT",
        help_text=ui.HELP_MIN_DOCSTRING_COVERAGE,
        pyproject_type=int,
    ),
    _option(
        dest="coverage_min",
        group="Quality gates",
        cli_kind="value",
        flags=("--coverage-min",),
        default=50,
        value_type=int,
        metavar="PERCENT",
        help_text=ui.HELP_COVERAGE_MIN,
        pyproject_type=int,
    ),
    _option(
        dest="skip_metrics",
        group="Analysis stages",
        cli_kind="bool_optional",
        flags=("--skip-metrics",),
        default=False,
        help_text=ui.HELP_SKIP_METRICS,
        pyproject_type=bool,
    ),
    _option(
        dest="skip_dead_code",
        group="Analysis stages",
        cli_kind="bool_optional",
        flags=("--skip-dead-code",),
        default=False,
        help_text=ui.HELP_SKIP_DEAD_CODE,
        pyproject_type=bool,
    ),
    _option(
        dest="skip_dependencies",
        group="Analysis stages",
        cli_kind="bool_optional",
        flags=("--skip-dependencies",),
        default=False,
        help_text=ui.HELP_SKIP_DEPENDENCIES,
        pyproject_type=bool,
    ),
    _option(
        dest="html_out",
        group="Reporting",
        cli_kind="optional_path",
        flags=("--html",),
        default=None,
        const=DEFAULT_HTML_REPORT_PATH,
        metavar="FILE",
        help_text=ui.HELP_HTML,
        pyproject_type=str,
        allow_none=True,
        path_value=True,
    ),
    _option(
        dest="json_out",
        group="Reporting",
        cli_kind="optional_path",
        flags=("--json",),
        default=None,
        const=DEFAULT_JSON_REPORT_PATH,
        metavar="FILE",
        help_text=ui.HELP_JSON,
        pyproject_type=str,
        allow_none=True,
        path_value=True,
    ),
    _option(
        dest="md_out",
        group="Reporting",
        cli_kind="optional_path",
        flags=("--md",),
        default=None,
        const=DEFAULT_MARKDOWN_REPORT_PATH,
        metavar="FILE",
        help_text=ui.HELP_MD,
        pyproject_type=str,
        allow_none=True,
        path_value=True,
    ),
    _option(
        dest="sarif_out",
        group="Reporting",
        cli_kind="optional_path",
        flags=("--sarif",),
        default=None,
        const=DEFAULT_SARIF_REPORT_PATH,
        metavar="FILE",
        help_text=ui.HELP_SARIF,
        pyproject_type=str,
        allow_none=True,
        path_value=True,
    ),
    _option(
        dest="text_out",
        group="Reporting",
        cli_kind="optional_path",
        flags=("--text",),
        default=None,
        const=DEFAULT_TEXT_REPORT_PATH,
        metavar="FILE",
        help_text=ui.HELP_TEXT,
        pyproject_type=str,
        allow_none=True,
        path_value=True,
    ),
    _option(
        dest="timestamped_report_paths",
        group="Reporting",
        cli_kind="bool_optional",
        flags=("--timestamped-report-paths",),
        default=False,
        help_text=ui.HELP_TIMESTAMPED_REPORT_PATHS,
    ),
    _option(
        dest="open_html_report",
        group="Output and UI",
        cli_kind="bool_optional",
        flags=("--open-html-report",),
        default=False,
        help_text=ui.HELP_OPEN_HTML_REPORT,
    ),
    _option(
        dest="no_progress",
        group="Output and UI",
        cli_kind="store_true",
        flags=("--no-progress",),
        default=False,
        help_text=ui.HELP_NO_PROGRESS,
        pyproject_type=bool,
    ),
    _option(
        dest="no_progress",
        group="Output and UI",
        cli_kind="store_false",
        flags=("--progress",),
        help_text=ui.HELP_PROGRESS,
        pyproject_key=None,
    ),
    _option(
        dest="no_color",
        group="Output and UI",
        cli_kind="store_true",
        flags=("--no-color",),
        default=False,
        help_text=ui.HELP_NO_COLOR,
        pyproject_type=bool,
    ),
    _option(
        dest="no_color",
        group="Output and UI",
        cli_kind="store_false",
        flags=("--color",),
        help_text=ui.HELP_COLOR,
        pyproject_key=None,
    ),
    _option(
        dest="quiet",
        group="Output and UI",
        cli_kind="bool_optional",
        flags=("--quiet",),
        default=False,
        help_text=ui.HELP_QUIET,
        pyproject_type=bool,
    ),
    _option(
        dest="verbose",
        group="Output and UI",
        cli_kind="bool_optional",
        flags=("--verbose",),
        default=False,
        help_text=ui.HELP_VERBOSE,
        pyproject_type=bool,
    ),
    _option(
        dest="debug",
        group="Output and UI",
        cli_kind="bool_optional",
        flags=("--debug",),
        default=False,
        help_text=ui.HELP_DEBUG,
        pyproject_type=bool,
    ),
    _option(
        dest="help",
        group="General",
        cli_kind="help",
        flags=("-h", "--help"),
        help_text="Show this help message and exit.",
    ),
    _option(
        dest="version",
        group="General",
        cli_kind="version",
        flags=("--version",),
        help_text=ui.HELP_VERSION,
    ),
)


def _build_defaults_by_dest() -> dict[str, object]:
    defaults: dict[str, object] = {}
    for spec in OPTIONS:
        if not spec.has_default or spec.dest in defaults:
            continue
        defaults[spec.dest] = spec.default
    return defaults


def _build_pyproject_specs() -> dict[str, ConfigKeySpec]:
    config_specs: dict[str, ConfigKeySpec] = {}
    for spec in OPTIONS:
        if spec.pyproject_key is None or spec.config_spec is None:
            continue
        if spec.pyproject_key in config_specs:
            existing = config_specs[spec.pyproject_key]
            if existing != spec.config_spec:
                raise RuntimeError(
                    f"Conflicting pyproject spec for {spec.pyproject_key}"
                )
            continue
        config_specs[spec.pyproject_key] = spec.config_spec
    return config_specs


DEFAULTS_BY_DEST: Final[dict[str, object]] = _build_defaults_by_dest()
CONFIG_KEY_SPECS: Final[dict[str, ConfigKeySpec]] = _build_pyproject_specs()
PATH_CONFIG_KEYS: Final[frozenset[str]] = frozenset(
    spec.pyproject_key
    for spec in OPTIONS
    if spec.pyproject_key is not None and spec.path_value
)
TESTABLE_CLI_OPTIONS: Final[tuple[OptionSpec, ...]] = tuple(
    spec
    for spec in OPTIONS
    if spec.cli_kind is not None and spec.cli_kind not in {"help", "version"}
)
PYPROJECT_OPTIONS: Final[tuple[OptionSpec, ...]] = tuple(
    spec for spec in OPTIONS if spec.pyproject_key is not None and spec.config_spec
)

__all__ = [
    "ARGUMENT_GROUP_TITLES",
    "CONFIG_KEY_SPECS",
    "DEFAULTS_BY_DEST",
    "DEFAULT_BASELINE_PATH",
    "DEFAULT_BLOCK_MIN_LOC",
    "DEFAULT_BLOCK_MIN_STMT",
    "DEFAULT_HTML_REPORT_PATH",
    "DEFAULT_JSON_REPORT_PATH",
    "DEFAULT_MARKDOWN_REPORT_PATH",
    "DEFAULT_MAX_BASELINE_SIZE_MB",
    "DEFAULT_MAX_CACHE_SIZE_MB",
    "DEFAULT_MIN_LOC",
    "DEFAULT_MIN_STMT",
    "DEFAULT_PROCESSES",
    "DEFAULT_ROOT",
    "DEFAULT_SARIF_REPORT_PATH",
    "DEFAULT_SEGMENT_MIN_LOC",
    "DEFAULT_SEGMENT_MIN_STMT",
    "DEFAULT_TEXT_REPORT_PATH",
    "OPTIONS",
    "PATH_CONFIG_KEYS",
    "PYPROJECT_OPTIONS",
    "TESTABLE_CLI_OPTIONS",
    "ConfigKeySpec",
    "OptionSpec",
]
