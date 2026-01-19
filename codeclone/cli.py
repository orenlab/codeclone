"""
CodeClone — AST and CFG-based code clone detector for Python
focused on architectural duplication.

Copyright (c) 2026 Den Rozhnovskiy
Licensed under the MIT License.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from .baseline import Baseline
from .cache import Cache, file_stat_signature
from .extractor import extract_units_from_source
from .html_report import build_html_report
from .normalize import NormalizationConfig
from .report import build_groups, build_block_groups, to_json, to_text
from .scanner import iter_py_files, module_name_from_path


def process_file(
    filepath: str,
    root: str,
    cfg: NormalizationConfig,
    min_loc: int,
    min_stmt: int,
) -> tuple[str, dict, list, list] | None:
    try:
        source = Path(filepath).read_text("utf-8")
    except UnicodeDecodeError:
        return None

    stat = file_stat_signature(filepath)
    module_name = module_name_from_path(root, filepath)

    units, blocks = extract_units_from_source(
        source=source,
        filepath=filepath,
        module_name=module_name,
        cfg=cfg,
        min_loc=min_loc,
        min_stmt=min_stmt,
    )

    return filepath, stat, units, blocks


def main() -> None:
    ap = argparse.ArgumentParser("codeclone")
    ap.add_argument("root", help="Project root")
    ap.add_argument("--processes", type=int, default=4)
    ap.add_argument("--cache", default="~/.cache/codeclone/")
    ap.add_argument("--min-loc", type=int, default=15)
    ap.add_argument("--min-stmt", type=int, default=6)
    ap.add_argument("--json-out", default="")
    ap.add_argument("--text-out", default="")
    ap.add_argument("--html-out", default="")
    ap.add_argument("--fail-if-groups", type=int, default=-1)
    ap.add_argument("--baseline", default="~/.config/codeclone/baseline.json")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--fail-on-new", action="store_true")

    args = ap.parse_args()

    cfg = NormalizationConfig()

    cache = Cache(args.cache)
    cache.load()

    all_units: list[dict] = []
    all_blocks: list[dict] = []
    changed = 0

    files_to_process: list[str] = []

    for fp in iter_py_files(args.root):
        stat = file_stat_signature(fp)
        cached = cache.get_file_entry(fp)

        if cached and cached.get("stat") == stat:
            all_units.extend(cached.get("units", []))
            all_blocks.extend(cached.get("blocks", []))
        else:
            files_to_process.append(fp)

    with ProcessPoolExecutor(max_workers=args.processes) as executor:
        futures = [
            executor.submit(
                process_file,
                fp,
                args.root,
                cfg,
                args.min_loc,
                args.min_stmt,
            )
            for fp in files_to_process
        ]

        for future in futures:
            result = future.result()
            if result is None:
                continue

            fp, stat, units, blocks = result

            cache.put_file_entry(fp, stat, units, blocks)
            changed += 1

            all_units.extend([u.__dict__ for u in units])
            all_blocks.extend([b.__dict__ for b in blocks])

    func_groups = build_groups(all_units)
    block_groups = build_block_groups(all_blocks)

    if args.html_out:
        out = Path(args.html_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            build_html_report(
                func_groups=func_groups,
                block_groups=block_groups,
                title="CodeClone Report",
                context_lines=3,
                max_snippet_lines=220,
            ),
            "utf-8",
        )

    baseline = Baseline(args.baseline)
    baseline.load()

    if args.update_baseline:
        new_baseline = Baseline.from_groups(func_groups, block_groups)
        new_baseline.path = Path(args.baseline)
        new_baseline.save()
        print(f"Baseline updated: {args.baseline}")
        return

    new_func, new_block = baseline.diff(func_groups, block_groups)

    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            to_json({"functions": func_groups, "blocks": block_groups}),
            "utf-8",
        )

    if args.text_out:
        out = Path(args.text_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            "FUNCTION CLONES\n"
            + to_text(func_groups)
            + "\nBLOCK CLONES\n"
            + to_text(block_groups),
            "utf-8",
        )

    print(f"Scanned root: {args.root}")
    print(f"Changed files parsed: {changed}")
    print(f"Function clone groups: {len(func_groups)}")
    print(f"Block clone groups: {len(block_groups)}")

    if args.fail_on_new and (new_func or new_block):
        print("\n❌ New code clones detected\n")
        raise SystemExit(3)

    cache.save()

    if 0 <= args.fail_if_groups < len(func_groups):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
