"""Record the outcome of one sharkmer run as a per-gene status table.

A run counts as complete only when sharkmer's manifest says `complete`, the
stats file carries the same run_id, and every file listed in the manifest
matches its SHA-256 checksum (the completion test documented by sharkmer).
Runs that exited with an error or left an incomplete manifest are recorded
with run_status `failed`, so the release can proceed and report them.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

import yaml

from common import write_tsv

COLUMNS = [
    "run",
    "run_status",
    "exit_code",
    "gene",
    "gene_id",
    "status",
    "n_products",
    "n_standard_products",
    "n_uncertain_products",
    "failure_reason",
    "fasta",
    "n_reads_read",
    "sharkmer_version",
    "note",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True)
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--exit-code", type=int, required=True)
    ap.add_argument("--panel", required=True)
    ap.add_argument("--gene-map", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    gene_map = dict(x.split("=", 1) for x in args.gene_map)
    outdir = Path(args.outdir)
    manifest_path = outdir / f"{args.run}.manifest.yaml"
    stats_path = outdir / f"{args.run}.stats.yaml"
    base = {"run": args.run, "exit_code": args.exit_code}

    note = ""
    if args.exit_code != 0:
        note = f"sharkmer exited with code {args.exit_code}"
    elif not manifest_path.exists() or not stats_path.exists():
        note = "manifest or stats missing"
    else:
        manifest = yaml.safe_load(open(manifest_path))
        stats = yaml.safe_load(open(stats_path))
        bad = [
            f["path"]
            for f in manifest.get("files", [])
            if sha256(outdir / f["path"]) != f["sha256"]
        ]
        if manifest.get("status") != "complete":
            note = f"manifest status {manifest.get('status')}"
        elif stats.get("run_id") != manifest.get("run_id"):
            note = "stats run_id does not match manifest"
        elif bad:
            note = f"checksum mismatch: {', '.join(bad)}"
    if note:
        write_tsv(args.out, [dict(base, run_status="failed", note=note)], COLUMNS)
        return

    rows = []
    prefix = f"{args.panel}_"
    for g in stats.get("pcr_results", []):
        gene = g["gene_name"].removeprefix(prefix)
        fasta = g.get("output_file") or ""
        rows.append(
            dict(
                base,
                run_status="complete",
                gene=gene,
                gene_id=gene_map.get(gene, ""),
                status=g.get("status"),
                n_products=g.get("n_products", 0),
                n_standard_products=g.get("n_standard_products", 0),
                n_uncertain_products=g.get("n_uncertain_products", 0),
                failure_reason=g.get("failure_reason") or "",
                fasta=str(outdir / fasta) if fasta else "",
                n_reads_read=stats.get("n_reads_read"),
                sharkmer_version=stats.get("sharkmer_version"),
            )
        )
    write_tsv(args.out, rows, COLUMNS)


if __name__ == "__main__":
    main()
