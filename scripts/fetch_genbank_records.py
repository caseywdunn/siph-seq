"""Download GenBank flat files for accessions not already in the local store.

The store holds one file per accession.version (`<store>/<accession>.gb`).
Versioned accessions are immutable, so a stored file never needs refreshing;
a revised record arrives as a new version. Each file is written atomically
after its accession is checked, so an interrupted download leaves no partial
record behind. Writes a list of the accessions now present.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

from common import atomic_write_text, entrez, log, read_tsv

ACC_LINE = re.compile(r"^VERSION\s+(\S+)", re.M)


def split_records(text: str) -> list[str]:
    """Split a multi-record GenBank flat file into records."""
    return [r.strip() + "\n//\n" for r in text.split("\n//") if r.strip()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inventory", nargs="*", default=[], help="TSV(s) with accession, selected")
    ap.add_argument("--accessions", nargs="*", default=[], help="additional accessions")
    ap.add_argument("--panel", help="sharkmer panel YAML whose reference accessions to add")
    ap.add_argument("--store", required=True)
    ap.add_argument("--batch-size", type=int, default=100)
    ap.add_argument("--out", required=True, help="list of accessions present in the store")
    args = ap.parse_args()

    wanted = list(args.accessions)
    if args.panel:
        panel = yaml.safe_load(open(args.panel))
        wanted += [s["accession"] for b in panel.get("references", []) for s in b["sequences"]]
    for inv in args.inventory:
        wanted += [r["accession"] for r in read_tsv(inv) if r["selected"] == "true"]
    wanted = sorted(set(wanted))
    store = Path(args.store)
    store.mkdir(parents=True, exist_ok=True)
    missing = [a for a in wanted if not (store / f"{a}.gb").exists()]
    log(f"{len(wanted)} records wanted, {len(missing)} to download")

    for i in range(0, len(missing), args.batch_size):
        batch = missing[i : i + args.batch_size]
        text = entrez(
            "efetch",
            {"db": "nuccore", "id": ",".join(batch), "rettype": "gbwithparts", "retmode": "text"},
            post=True,
        ).text
        got = {}
        for rec in split_records(text):
            m = ACC_LINE.search(rec)
            if m:
                got[m.group(1)] = rec
        for acc in batch:
            if acc not in got:
                raise SystemExit(f"efetch did not return {acc}")
            atomic_write_text(store / f"{acc}.gb", got[acc])
        log(f"  downloaded {min(i + args.batch_size, len(missing))}/{len(missing)}")

    atomic_write_text(args.out, "".join(f"{a}\n" for a in wanted))


if __name__ == "__main__":
    main()
