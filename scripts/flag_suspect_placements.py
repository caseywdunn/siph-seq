"""Flag sequences whose position in a gene tree contradicts their species label.

For each tip from the focal clade, the k nearest tips by patristic distance
are found (plus any tied with the k-th), ignoring tips from the same dataset
(e.g. several sharkmer products from one run). For each taxonomic rank
evaluated for the gene, a tip is `*_mismatch` when other datasets of its genus
(family) are in the tree, none are among its nearest neighbours, and the
nearest one is at least --min-gap substitutions/site farther than the nearest
neighbour. The ranks and gap are set per gene: slowly evolving rRNA genes
(18S, 28S) do not resolve genera in siphonophores and are evaluated at family
level only. Nearest neighbours that are mostly
outside the focal clade, or a non-focal nearest neighbour with every focal-clade
sequence at least --min-gap farther, give `outside_focal_clade`, which indicates
contamination (prey, symbionts) or a misidentified non-siphonophore.

This is a screening heuristic, not a test: non-monophyletic genera, sparse
sampling, and short or partial sequences also produce flags; aligned_sites
gives the number of sites each placement rests on. Family-level and
cross-gene flags (see report_release.py) are the strongest signals.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter

import numpy as np
from Bio import Phylo

from common import read_tsv, write_tsv

COLUMNS = [
    "gene_id",
    "tip_id",
    "source",
    "dataset",
    "organism",
    "genus",
    "family",
    "flag",
    "length",
    "aligned_sites",
    "n_neighbors",
    "neighbor_genera",
    "neighbor_families",
    "nearest_neighbor",
    "nearest_distance",
    "nearest_same_genus_distance",
    "nearest_same_family_distance",
    "genus_in_tree",
    "family_in_tree",
    "note",
]


def patristic_matrix(tree) -> tuple[list[str], np.ndarray]:
    """All pairwise tip distances, computed per internal node with numpy."""
    tips = tree.get_terminals()
    names = [t.name for t in tips]
    index = {id(t): i for i, t in enumerate(tips)}
    n = len(tips)
    depth = {}
    stack = [(tree.root, 0.0)]
    while stack:
        c, d = stack.pop()
        depth[id(c)] = d
        for ch in c.clades:
            stack.append((ch, d + (ch.branch_length or 0.0)))
    tip_depth = np.array([depth[id(t)] for t in tips], dtype=np.float64)
    D = np.zeros((n, n), dtype=np.float32)
    desc: dict[int, np.ndarray] = {}
    for c in tree.find_clades(order="postorder"):
        if c.is_terminal():
            desc[id(c)] = np.array([index[id(c)]])
            continue
        kids = [desc.pop(id(ch)) for ch in c.clades]
        dv = depth[id(c)]
        for i in range(len(kids)):
            for j in range(i + 1, len(kids)):
                a, b = kids[i], kids[j]
                block = tip_depth[a][:, None] + tip_depth[b][None, :] - 2 * dv
                D[np.ix_(a, b)] = block
                D[np.ix_(b, a)] = block.T
        desc[id(c)] = np.concatenate(kids)
    return names, D


def summarize(values: list[str]) -> str:
    return ",".join(f"{k or 'unknown'}({n})" for k, n in Counter(values).most_common())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tree", required=True)
    ap.add_argument("--tips", required=True, help="tip_metadata.tsv")
    ap.add_argument("--sites", required=True, help="aligned_sites.tsv")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--ranks", nargs="+", default=["genus", "family"])
    ap.add_argument(
        "--min-gap",
        type=float,
        default=0.01,
        help="substitutions/site by which the nearest same-rank sequence must be farther "
        "than the nearest neighbour for a mismatch to be flagged",
    )
    ap.add_argument(
        "--tie-tolerance",
        type=float,
        default=1e-4,
        help="sequences this close to the k-th neighbour distance also count as neighbours",
    )
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    sys.setrecursionlimit(100000)
    tree = Phylo.read(args.tree, "newick")
    names, D = patristic_matrix(tree)
    meta = {r["tip_id"]: r for r in read_tsv(args.tips)}
    missing = [n for n in names if n not in meta]
    if missing:
        raise SystemExit(f"Tree tips missing from {args.tips}: {missing[:5]}")
    info = [meta[n] for n in names]
    datasets = np.array([f"{m['source']}:{m['dataset']}" for m in info])
    sites = {r["seq_id"]: r["aligned_sites"] for r in read_tsv(args.sites)}
    rows = []

    def base(m: dict) -> dict:
        return {
            "gene_id": m["gene_id"],
            "tip_id": m["tip_id"],
            "source": m["source"],
            "dataset": m["dataset"],
            "organism": m["organism"],
            "genus": m["genus"],
            "family": m["family"],
            "length": m["length"],
            "aligned_sites": sites.get(m["seq_id"], ""),
        }

    # Sequences that passed the length filter but kept too few sites after
    # trimming are reported rather than silently missing.
    in_tree = set(names)
    for m in meta.values():
        if m["included"] == "true" and m["tip_id"] not in in_tree and m["source"] != "ref":
            rows.append(dict(base(m), flag="not_in_tree", note="too few aligned sites"))

    for i, m in enumerate(info):
        if m["source"] == "ref" or m["in_focal_clade"] != "true":
            continue
        others = np.where(datasets != datasets[i])[0]
        row = base(m)
        if len(others) == 0:
            rows.append(dict(row, flag="not_evaluable", note="no other datasets in tree"))
            continue
        order = others[np.lexsort((np.array(names)[others], D[i, others]))]
        # Slowly evolving genes give many equally close neighbours; take all
        # of them rather than an arbitrary k, so ties never decide a flag.
        kth = D[i, order[min(args.k, len(order)) - 1]]
        nn = order[D[i, order] <= kth + args.tie_tolerance]
        ng = [info[j]["genus"] for j in nn]
        nf = [info[j]["family"] for j in nn]
        row.update(
            n_neighbors=len(nn),
            neighbor_genera=summarize(ng),
            neighbor_families=summarize(nf),
            nearest_neighbor=names[nn[0]],
            nearest_distance=f"{D[i, nn[0]]:.4f}",
        )
        flags, notes, unresolved = [], [], []
        # Foreign sequence: most neighbours are outside the focal clade, or the
        # nearest neighbour is, with every focal-clade sequence resolvably farther.
        n_outside = sum(info[j]["in_focal_clade"] != "true" for j in nn)
        focal = [j for j in others if info[j]["in_focal_clade"] == "true"]
        nearest_focal = min((D[i, j] for j in focal), default=np.inf)
        if n_outside > len(nn) / 2 or (
            info[nn[0]]["in_focal_clade"] != "true" and nearest_focal - D[i, nn[0]] >= args.min_gap
        ):
            flags.append("outside_focal_clade")
        for rank in args.ranks:
            value = m.get(rank, "")
            n_in_tree = sum(1 for j in others if value and info[j][rank] == value)
            row[f"{rank}_in_tree"] = n_in_tree
            if n_in_tree:
                same_d = min(D[i, j] for j in others if info[j][rank] == value)
                row[f"nearest_same_{rank}_distance"] = f"{same_d:.4f}"
            if not value:
                notes.append(f"{rank} unknown")
            elif n_in_tree == 0:
                notes.append(f"only dataset of its {rank}")
            elif not any(info[j][rank] == value for j in nn):
                # Flag only when the gene resolves the difference: the nearest
                # same-rank sequence must be clearly farther than the nearest
                # neighbour, not just outside an arbitrary neighbour count.
                if same_d - D[i, nn[0]] >= args.min_gap:
                    flags.append(f"{rank}_mismatch")
                else:
                    unresolved.append(rank)
                    notes.append(f"{rank} not resolved by this gene")
        # Report the coarsest mismatch: a family mismatch implies a genus mismatch.
        order_pref = ["outside_focal_clade"] + [f"{r}_mismatch" for r in reversed(args.ranks)]
        flag = next((f for f in order_pref if f in flags), None)
        if flag is None and unresolved:
            flag = "unresolved"
        elif flag is None:
            flag = "consistent" if len(notes) < len(args.ranks) else "not_evaluable"
        rows.append(dict(row, flag=flag, note="; ".join(notes)))

    write_tsv(args.out, rows, COLUMNS)


if __name__ == "__main__":
    main()
