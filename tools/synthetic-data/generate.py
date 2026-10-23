from __future__ import annotations

import argparse
import csv
import random
import sys
from datetime import date, timedelta


def rows(days: int, seed: int) -> list[dict[str, object]]:
    rng = random.Random(seed)
    start = date(2026, 7, 21)
    return [
        {
            "day": (start + timedelta(days=index)).isoformat(),
            "steps": max(3800, int(rng.gauss(5850, 420))),
            "active_minutes": max(18, int(rng.gauss(42, 6))),
            "sleep_hours": round(min(8.4, max(5.6, rng.gauss(7.0, 0.45))), 1),
            "wear_hours": round(min(16, max(10, rng.gauss(13.6, 0.8))), 1),
            "source": "synthetic",
        }
        for index in range(days)
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate non-clinical Care+ fixture CSV")
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--seed", type=int, default=2026)
    arguments = parser.parse_args()
    if arguments.days < 1 or arguments.days > 365:
        parser.error("--days must be between 1 and 365")

    writer = csv.DictWriter(sys.stdout, fieldnames=list(rows(1, arguments.seed)[0]))
    writer.writeheader()
    writer.writerows(rows(arguments.days, arguments.seed))


if __name__ == "__main__":
    main()

