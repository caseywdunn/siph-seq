"""Gather sharkmer products from all runs of a release into one FASTA and table.

Products carrying sharkmer assembly warnings are listed but left out of the
FASTA unless --include-uncertain is given. Sequence ids are
`<run>__<gene_id>__<product>`.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from Bio import SeqIO

from common import read_tsv, write_tsv

COLUMNS = [
    "product_id",
    "run",
    "gene_id",
    "length",
    "kmer_count_mean",
    "assembly_status",
    "included",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--status", nargs="+", required=True, help="per-run status tables")
    ap.add_argument("--include-uncertain", action="store_true")
    ap.add_argument("--fasta", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--run-table", required=True, help="all per-run status rows combined")
    args = ap.parse_args()

    status_rows, rows = [], []
    Path(args.fasta).parent.mkdir(parents=True, exist_ok=True)
    tmp = f"{args.fasta}.tmp"
    with open(tmp, "w") as out:
        for path in args.status:
            for s in read_tsv(path):
                status_rows.append(s)
                if s["run_status"] != "complete" or not s["fasta"] or not s["gene_id"]:
                    continue
                for rec in SeqIO.parse(s["fasta"], "fasta"):
                    fields = dict(
                        kv.split("=", 1) for kv in rec.description.split()[1:] if "=" in kv
                    )
                    uncertain = fields.get("assembly_status") == "warning"
                    pid = f"{s['run']}__{s['gene_id']}__{fields.get('product', len(rows))}"
                    keep = args.include_uncertain or not uncertain
                    rows.append(
                        {
                            "product_id": pid,
                            "run": s["run"],
                            "gene_id": s["gene_id"],
                            "length": len(rec.seq),
                            "kmer_count_mean": fields.get("kmer_count_mean", ""),
                            "assembly_status": fields.get("assembly_status", "ok"),
                            "included": str(keep).lower(),
                        }
                    )
                    if keep:
                        out.write(f">{pid}\n{str(rec.seq).upper()}\n")
    Path(tmp).replace(args.fasta)
    write_tsv(args.table, rows, COLUMNS)
    cols = list(status_rows[0].keys()) if status_rows else ["run"]
    write_tsv(args.run_table, status_rows, cols)


if __name__ == "__main__":
    main()
