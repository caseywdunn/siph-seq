"""Summarize a release: what each dataset yielded and which datasets look misidentified.

Outputs:
- dataset_status.tsv: the manifest plus, for each processed dataset, the
  genes recovered, its processing status, and its suspect-placement flags.
- dataset_flags.tsv: datasets with at least one flagged placement, with
  flags across genes. A dataset flagged in several genes, or at family level,
  is the strongest candidate for a wrong species identification. A flag
  marked "(another copy consistent)" means the dataset also has a copy of
  that gene placed with its own taxon, which points to contamination.
- suspect_placements.tsv: all per-gene placement evaluations combined.
- summary.tsv: counts by source and outcome.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict

from common import read_tsv, write_tsv

STRENGTH = {"outside_focal_clade": 3, "family_mismatch": 2, "genus_mismatch": 1}
SOURCE_KEY = {"ncbi": "ncbi_nucleotide", "sra": "sra_run", "genome": "genome_assembly"}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--ncbi-records", required=True, help="record_genes.tsv")
    ap.add_argument("--sra-status", required=True, help="combined sharkmer run status")
    ap.add_argument("--genome-regions", nargs="*", default=[])
    ap.add_argument("--placements", nargs="+", required=True, help="per-gene placement tables")
    ap.add_argument("--dataset-status", required=True)
    ap.add_argument("--dataset-flags", required=True)
    ap.add_argument("--suspect-placements", required=True)
    ap.add_argument("--summary", required=True)
    args = ap.parse_args()

    genes = defaultdict(set)
    status = {}
    for r in read_tsv(args.ncbi_records):
        key = ("ncbi_nucleotide", r["accession"])
        genes[key].update(g for g in r["genes"].split(";") if g)
        status[key] = "conflict: " + r["conflict"] if r["conflict"] else "processed"
    for r in read_tsv(args.sra_status):
        key = ("sra_run", r["run"])
        if r["run_status"] != "complete":
            status[key] = f"failed: {r['note']}"
            continue
        status[key] = "processed"
        if r["gene_id"] and int(r["n_products"] or 0) > 0:
            genes[key].add(r["gene_id"])
    for path in args.genome_regions:
        asm = path.rstrip("/").split("/")[-2]
        key = ("genome_assembly", asm)
        status[key] = "processed"
        genes[key].update(r["gene_id"] for r in read_tsv(path))

    placements = [p for path in args.placements for p in read_tsv(path)]
    in_tree = defaultdict(set)
    for p in placements:
        if p["flag"] != "not_in_tree":
            in_tree[(SOURCE_KEY[p["source"]], p["dataset"])].add(p["gene_id"])
    write_tsv(
        args.suspect_placements,
        placements,
        list(placements[0].keys()) if placements else ["gene_id"],
    )
    # A dataset can have several tips per gene (e.g. several sharkmer
    # products); keep the strongest evaluation for each gene.
    rank = {"not_in_tree": -3, "not_evaluable": -2, "unresolved": -1, "consistent": 0, **STRENGTH}
    flags = defaultdict(dict)
    consistent_copy = set()  # (dataset key, gene) with at least one consistent copy
    for p in placements:
        key = (SOURCE_KEY[p["source"]], p["dataset"])
        if p["flag"] == "consistent":
            consistent_copy.add((key, p["gene_id"]))
        prev = flags[key].get(p["gene_id"])
        if prev is None or rank[p["flag"]] > rank[prev]:
            flags[key][p["gene_id"]] = p["flag"]

    def describe(key, gene, flag):
        # A flagged copy alongside a consistent copy of the same gene points to
        # foreign DNA in the dataset (contamination) rather than a wrong species.
        mixed = " (another copy consistent)" if (key, gene) in consistent_copy else ""
        return f"{gene}:{flag}{mixed}"

    manifest = read_tsv(args.manifest)
    rows, flagged = [], []
    for m in manifest:
        key = (m["source"], m["accession"])
        f = flags.get(key, {})
        bad = {g: v for g, v in f.items() if v in STRENGTH}
        row = dict(
            m,
            status=status.get(key, "not processed" if m["selected"] == "true" else ""),
            genes_recovered=";".join(sorted(genes.get(key, []))),
            genes_in_trees=";".join(sorted(in_tree.get(key, []))),
            genes_evaluated=len(
                [v for v in f.values() if v not in ("not_evaluable", "not_in_tree", "unresolved")]
            ),
            genes_flagged=len(bad),
            flags="; ".join(describe(key, g, v) for g, v in sorted(bad.items())),
            max_flag=max(bad.values(), key=STRENGTH.get) if bad else "",
        )
        rows.append(row)
        if bad:
            flagged.append(row)
    cols = list(manifest[0].keys()) + [
        "status",
        "genes_recovered",
        "genes_in_trees",
        "genes_evaluated",
        "genes_flagged",
        "flags",
        "max_flag",
    ]
    write_tsv(args.dataset_status, rows, cols)
    flagged.sort(key=lambda r: (-STRENGTH[r["max_flag"]], -r["genes_flagged"], r["accession"]))
    write_tsv(
        args.dataset_flags,
        flagged,
        [
            "source",
            "accession",
            "organism",
            "family",
            "voucher",
            "genes_in_trees",
            "genes_evaluated",
            "genes_flagged",
            "max_flag",
            "flags",
            "project",
            "title",
        ],
    )

    summary = Counter()
    for r in rows:
        summary[(r["source"], "datasets")] += 1
        summary[(r["source"], "selected")] += r["selected"] == "true"
        summary[(r["source"], "failed")] += r["status"].startswith("failed")
        summary[(r["source"], "with_marker_genes")] += bool(r["genes_recovered"])
        summary[(r["source"], "in_any_tree")] += bool(r["genes_in_trees"])
        summary[(r["source"], "flagged")] += r["genes_flagged"] > 0
    write_tsv(
        args.summary,
        [{"source": s, "measure": k, "count": v} for (s, k), v in sorted(summary.items())],
        ["source", "measure", "count"],
    )


if __name__ == "__main__":
    main()
