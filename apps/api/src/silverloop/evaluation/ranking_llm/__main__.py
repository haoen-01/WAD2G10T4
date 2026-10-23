"""CLI: `python -m silverloop.evaluation.ranking_llm [--out DIR] [--check] [--recordings PATH]`.

Exit codes: 0 ok, 2 usage, 3 artifact drift under `--check`. Shaped after
`silverloop.evaluation.ranking.__main__`; it writes `ranking-llm.{json,md}` and never touches
`ranking-evaluation.{json,md}`, which the deterministic benchmark owns.

A missing recording is not an error here: the arm reports "not recorded" and exits 0. Drift
between the committed artifact and a regenerated one IS an error, which is how a recording that
has gone stale against an edited prompt becomes visible.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from silverloop.evaluation.ranking_llm.report import check_artifacts, to_markdown, write_artifacts
from silverloop.evaluation.ranking_llm.runner import run_llm_evaluation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m silverloop.evaluation.ranking_llm")
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--check", action="store_true")
    parser.add_argument(
        "--recordings",
        type=Path,
        default=None,
        help="Recording file or directory; defaults to apps/api/tests/recordings/activity_ranking.",
    )
    args = parser.parse_args(argv)

    if args.check and args.out is None:
        print("error: --check requires --out", file=sys.stderr)
        return 2

    result = run_llm_evaluation(args.recordings)
    print(to_markdown(result))

    if args.check:
        if not check_artifacts(result, args.out):
            print(
                f"error: artifacts in {args.out} are stale; run "
                "`python -m silverloop.evaluation.ranking_llm --out ../../docs/evaluation` "
                "(and `...ranking_llm.synthesise` first if the prompt or the dataset moved)",
                file=sys.stderr,
            )
            return 3
    elif args.out is not None:
        write_artifacts(result, args.out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
