"""Write the sequences of identified marker regions, oriented to the reference strand.

Reads target sequences either from a FASTA file (small collections such as
GenBank records and sharkmer products) or from a BLAST database built with
-parse_seqids (genome assemblies, extracted with blastdbcmd so the genome is
never loaded into memory). Region coordinates are 1-based inclusive.
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

from Bio import SeqIO
from Bio.Seq import reverse_complement

from common import read_tsv


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--regions", required=True)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--fasta")
    src.add_argument("--blastdb")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    regions = read_tsv(args.regions)
    seqs = {}
    if args.fasta:
        seqs = {r.id: str(r.seq).upper() for r in SeqIO.parse(args.fasta, "fasta")}

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    tmp = f"{args.out}.tmp"
    with open(tmp, "w") as out:
        for r in regions:
            start, end = int(r["start"]), int(r["end"])
            if args.fasta:
                seq = seqs[r["target"]][start - 1 : end]
            else:
                res = subprocess.run(
                    [
                        "blastdbcmd",
                        "-db",
                        args.blastdb,
                        "-entry",
                        r["target"],
                        "-range",
                        f"{start}-{end}",
                        "-outfmt",
                        "%s",
                    ],
                    check=True,
                    capture_output=True,
                    text=True,
                )
                seq = res.stdout.strip().upper()
            if len(seq) != end - start + 1:
                raise SystemExit(
                    f"{r['region_id']}: extracted {len(seq)} bp, expected {end - start + 1}"
                )
            if r["strand"] == "-":
                seq = reverse_complement(seq)
            out.write(f">{r['region_id']}\n{seq}\n")
    Path(tmp).replace(args.out)


if __name__ == "__main__":
    main()
