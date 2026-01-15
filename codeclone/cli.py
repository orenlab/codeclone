from __future__ import annotations

import argparse
from pathlib import Path

from .baseline import Baseline
from .cache import Cache, file_stat_signature
from .extractor import extract_units_from_source
from .normalize import NormalizationConfig
from .report import build_groups, build_block_groups, to_json, to_text
from .scanner import iter_py_files, module_name_from_path


def main():
    ap = argparse.ArgumentParser("codeclone")
    ap.add_argument("root", help="Project root")
    ap.add_argument("--cache", default="~/.cache/codeclone/")
    ap.add_argument("--min-loc", type=int, default=15)
    ap.add_argument("--min-stmt", type=int, default=6)
    ap.add_argument("--json-out", default="")
    ap.add_argument("--text-out", default="")
    ap.add_argument("--fail-if-groups", type=int, default=-1)
    ap.add_argument("--baseline", default="~/.config/codeclone/baseline.json")
    ap.add_argument("--update-baseline", action="store_true",
                    help="Write current clones as baseline")
    ap.add_argument("--fail-on-new", action="store_true",
                    help="Fail if new clones appear vs baseline")
    args = ap.parse_args()

    cfg = NormalizationConfig(
        ignore_docstrings=True,
        ignore_type_annotations=True,
        normalize_attributes=True,
        normalize_constants=True,
        normalize_names=True,
    )

    cache = Cache(args.cache)
    cache.load()

    all_units: list[dict] = []
    all_blocks: list[dict] = []
    changed = 0

    for fp in iter_py_files(args.root):
        stat = file_stat_signature(fp)
        cached = cache.get_file_entry(fp)

        if cached and cached.get("stat") == stat:
            all_units.extend(cached.get("units", []))
            all_blocks.extend(cached.get("blocks", []))
            continue

        try:
            source = Path(fp).read_text("utf-8")
        except UnicodeDecodeError:
            continue

        module_name = module_name_from_path(args.root, fp)
        units, blocks = extract_units_from_source(
            source=source,
            filepath=fp,
            module_name=module_name,
            cfg=cfg,
            min_loc=args.min_loc,
            min_stmt=args.min_stmt,
        )

        cache.put_file_entry(fp, stat, units, blocks)
        changed += 1

        all_units.extend([u.__dict__ for u in units])
        all_blocks.extend([b.__dict__ for b in blocks])

    func_groups = build_groups(all_units)
    block_groups = build_block_groups(all_blocks)

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
            to_json({
                "functions": func_groups,
                "blocks": block_groups,
            }),
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

    if args.fail_on_new:
        if new_func or new_block:
            print("\n❌ New code clones detected\n")

            if new_func:
                print(f"New FUNCTION clone groups: {len(new_func)}")
                for k in sorted(new_func):
                    print(f"  - {k}")

            if new_block:
                print(f"New BLOCK clone groups: {len(new_block)}")
                for k in sorted(new_block):
                    print(f"  - {k}")

            raise SystemExit(3)

    print(f"Baseline function clones: {len(baseline.functions)}")
    print(f"Baseline block clones: {len(baseline.blocks)}")
    print(f"New function clones: {len(new_func)}")
    print(f"New block clones: {len(new_block)}")

    cache.save()

    if 0 <= args.fail_if_groups < len(func_groups):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
