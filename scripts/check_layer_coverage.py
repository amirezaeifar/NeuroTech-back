"""Enforce branch coverage for the business layer from coverage.py JSON output."""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPORT = Path(".coverage-report.json")
PREFIXES = ("app/services/", "app/domain/")
MINIMUM_PERCENT = 95.0


def main() -> int:
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    summaries = [
        value["summary"]
        for raw_name, value in report["files"].items()
        if raw_name.replace("\\", "/").startswith(PREFIXES)
    ]
    branches = sum(item["num_branches"] for item in summaries)
    covered = sum(item["covered_branches"] for item in summaries)
    percent = 100.0 if branches == 0 else covered * 100 / branches
    print(f"domain/services branch coverage: {covered}/{branches} ({percent:.2f}%)")
    if percent < MINIMUM_PERCENT:
        print(f"required branch coverage is {MINIMUM_PERCENT:.2f}%", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
