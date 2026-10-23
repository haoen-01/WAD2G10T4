"""CLI: `python -m silverloop.evaluation.ranking [--out DIR] [--check]`.

Exit codes: 0 ok, 3 artifact drift under `--check`. There is no scenario directory to load (the
dataset is frozen in code, see `dataset.py`) and no hard-violation gate (this is a ranking-quality
benchmark, not a safety-policy one) -- both of which is why this CLI is smaller than
`silverloop.evaluation`'s.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from silverloop.evaluation.ranking.report import check_artifacts, to_markdown, write_artifacts
from silverloop.evaluation.ranking.runner import run_evaluation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m silverloop.evaluation.ranking")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    if args.check and args.out is None:
        print("error: --check requires --out", file=sys.stderr)
        return 2

    result = run_evaluation()
    print(to_markdown(result))

    if args.check:
        if not check_artifacts(result, args.out):
            print(
                f"error: artifacts in {args.out} are stale; run `pnpm evaluate` to regenerate",
                file=sys.stderr,
            )
            return 3
    elif args.out is not None:
        write_artifacts(result, args.out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
