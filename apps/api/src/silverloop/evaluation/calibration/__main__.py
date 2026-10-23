"""CLI: `python -m silverloop.evaluation.calibration [--out DIR] [--check]`.

Exit codes: 0 ok, 2 usage, 3 artifact drift under `--check`. Shaped after
`silverloop.evaluation.ranking_llm.__main__`; it writes `review-calibration.{json,md}` and touches
no other artifact.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from silverloop.evaluation.calibration.report import check_artifacts, to_markdown, write_artifacts
from silverloop.evaluation.calibration.runner import run_calibration_evaluation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m silverloop.evaluation.calibration")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--quiet", action="store_true", help="Do not print the Markdown report.")
    args = parser.parse_args(argv)

    if args.check and args.out is None:
        print("error: --check requires --out", file=sys.stderr)
        return 2

    result = run_calibration_evaluation()
    if not args.quiet:
        print(to_markdown(result))

    if args.check:
        if not check_artifacts(result, args.out):
            print(
                f"error: artifacts in {args.out} are stale; run "
                "`python -m silverloop.evaluation.calibration --out ../../docs/evaluation`",
                file=sys.stderr,
            )
            return 3
    elif args.out is not None:
        write_artifacts(result, args.out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
