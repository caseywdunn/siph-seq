"""Replace internal sequence ids in a tree with the lab tip labels."""

from __future__ import annotations

import argparse
import sys

from Bio import Phylo

from common import read_tsv


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tree", required=True)
    ap.add_argument("--tips", required=True, help="tip_metadata.tsv with seq_id and tip_id")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    sys.setrecursionlimit(100000)
    labels = {r["seq_id"]: r["tip_id"] for r in read_tsv(args.tips) if r["seq_id"]}
    tree = Phylo.read(args.tree, "newick")
    for tip in tree.get_terminals():
        if tip.name not in labels:
            raise SystemExit(f"{args.tree}: tip {tip.name} is not in {args.tips}")
        tip.name = labels[tip.name]
    Phylo.write(tree, args.out, "newick")


if __name__ == "__main__":
    main()
