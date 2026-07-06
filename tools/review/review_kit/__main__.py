"""python -m review_kit entrypoint."""

from __future__ import annotations

import sys

from review_kit.cli import main

raise SystemExit(main(sys.argv[1:]))
