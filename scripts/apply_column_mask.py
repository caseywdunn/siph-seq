"""Trim an alignment to the columns trimAl kept for the backbone sequences.

trimAl's automated column selection is run on the backbone (near full-length)
sequences only, because columns covered only by short barcodes would look
gappy and be removed. The kept columns are applied here to the full
alignment, backbone and fragments alike. Sequences left with fewer than
--min-sites non-gap sites cannot be placed reliably and are dropped; the
per-sequence site counts are written so placements can be weighed by them.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from Bio import SeqIO

from common import write_tsv


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--alignment", required=True)
    ap.add_argument("--columns", required=True, help="trimAl -colnumbering output")
    ap.add_argument("--min-sites", type=int, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sites", required=True, help="TSV of retained sites per sequence")
    args = ap.parse_args()

    text = Path(args.columns).read_text().strip()
    if not text.startswith("#ColumnsMap"):
        raise SystemExit(f"{args.columns}: not trimAl -colnumbering output")
    keep = [int(x) for x in text.split("\t", 1)[1].split(",") if x.strip()]
    records = list(SeqIO.parse(args.alignment, "fasta"))
    width = len(records[0].seq)
    if any(len(r.seq) != width for r in records):
        raise SystemExit(f"{args.alignment}: sequences differ in aligned length")
    if not keep or max(keep) >= width:
        raise SystemExit(f"{args.columns}: column numbers do not fit the alignment")

    rows, n_kept = [], 0
    tmp = f"{args.out}.tmp"
    with open(tmp, "w") as out:
        for r in records:
            seq = str(r.seq).upper()
            trimmed = "".join(seq[i] for i in keep)
            sites = sum(c not in "-N?" for c in trimmed)
            ok = sites >= args.min_sites
            rows.append({"seq_id": r.id, "aligned_sites": sites, "in_tree": str(ok).lower()})
            if ok:
                out.write(f">{r.id}\n{trimmed}\n")
                n_kept += 1
    if n_kept < 4:
        raise SystemExit(f"Only {n_kept} sequences retain {args.min_sites} sites; need 4")
    Path(tmp).replace(args.out)
    write_tsv(args.sites, rows, ["seq_id", "aligned_sites", "in_tree"])


if __name__ == "__main__":
    main()
