"""Remove stored sharkmer runs that failed, so the next release retries them.

A failed run (e.g. ENA unreachable) is recorded rather than retried
automatically, so that one unreachable file cannot stall every release. Only
runs whose status says `failed` are removed; completed runs that recovered no
genes are kept.

Usage: python scripts/clear_failed_sharkmer_runs.py [--dry-run]

A new release retries cleared runs. To retry within an existing release, add
`--forcerun collect_sharkmer_products` when relaunching it; otherwise its
existing results are treated as up to date.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from common import read_tsv


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", default="results/sharkmer")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    for status in sorted(Path(args.root).glob("*/status.tsv")):
        rows = read_tsv(status)
        if rows and rows[0]["run_status"] == "failed":
            print(f"{status.parent.name}: {rows[0]['note']}")
            if not args.dry_run:
                shutil.rmtree(status.parent)


if __name__ == "__main__":
    main()
