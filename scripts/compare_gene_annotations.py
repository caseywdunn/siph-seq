"""Combine similarity-based gene identification with GenBank annotations.

Similarity (BLAST to reference markers) is the primary evidence for which gene
a GenBank record contains. Submitter annotations, normalized to the same gene
vocabulary, are compared against it:

gene_assignments.tsv, one row per (record, gene):
- evidence: similarity+annotation, similarity, annotation (an annotated or
  titled gene with no similarity hit; usually a gene outside the reference
  set), or none for records with no recognizable gene.
- annotation_agrees: for similarity regions, whether an annotated feature
  overlapping the region names the same gene (yes), a different gene (no), or
  no feature names a gene there (unannotated).

record_genes.tsv, one row per record, summarizes the genes found by each line
of evidence and flags conflicts for review. Annotated genes outside the
vocabulary (e.g. piwi, histone H3) are listed verbatim in other_labels.
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from common import Vocabulary, read_tsv, write_tsv

ASSIGN_COLUMNS = [
    "accession",
    "gene_id",
    "evidence",
    "region_id",
    "start",
    "end",
    "strand",
    "length",
    "best_ref_pident",
    "best_ref_coverage",
    "annotation_gene_ids",
    "annotation_agrees",
    "so_id",
    "hgnc_symbol",
]
RECORD_COLUMNS = [
    "accession",
    "organism",
    "tax_id",
    "length",
    "compartment",
    "genes",
    "similarity_genes",
    "annotation_genes",
    "title_genes",
    "other_labels",
    "conflict",
    "title",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--metadata", required=True)
    ap.add_argument("--annotations", required=True)
    ap.add_argument("--regions", required=True)
    ap.add_argument("--vocabulary", required=True)
    ap.add_argument("--assignments", required=True)
    ap.add_argument("--records", required=True)
    args = ap.parse_args()

    vocab = Vocabulary(args.vocabulary)
    meta = read_tsv(args.metadata)
    annots = defaultdict(list)
    other_labels = defaultdict(list)  # labels outside the vocabulary, kept verbatim
    for a in read_tsv(args.annotations):
        if a["gene_id"]:
            annots[a["accession"]].append(a)
        elif a["feature_type"] in ("CDS", "rRNA", "misc_RNA"):
            label = a["label"].split(" | ")[0]
            if label not in other_labels[a["accession"]]:
                other_labels[a["accession"]].append(label)
    regions = defaultdict(list)
    for r in read_tsv(args.regions):
        regions[r["target"]].append(r)

    def onto(gene_id: str) -> dict:
        v = vocab.by_id.get(gene_id, {})
        return {"so_id": v.get("so_id", ""), "hgnc_symbol": v.get("hgnc_symbol", "")}

    rows, records = [], []
    for m in meta:
        acc = m["accession"]
        sim_genes, used, disagreements = [], set(), 0
        for r in regions[acc]:
            s, e = int(r["start"]), int(r["end"])
            over = sorted(
                {
                    a["gene_id"]
                    for a in annots[acc]
                    if min(e, int(a["end"])) - max(s, int(a["start"])) + 1 > 0.2 * (e - s + 1)
                }
            )
            agrees = "unannotated" if not over else ("yes" if r["gene_id"] in over else "no")
            disagreements += agrees == "no"
            rows.append(
                {
                    "accession": acc,
                    "gene_id": r["gene_id"],
                    "evidence": "similarity+annotation" if agrees == "yes" else "similarity",
                    "region_id": r["region_id"],
                    "start": s,
                    "end": e,
                    "strand": r["strand"],
                    "length": r["length"],
                    "best_ref_pident": r["best_ref_pident"],
                    "best_ref_coverage": r["best_ref_coverage"],
                    "annotation_gene_ids": ";".join(over),
                    "annotation_agrees": agrees,
                    **onto(r["gene_id"]),
                }
            )
            sim_genes.append(r["gene_id"])
            used.add(r["gene_id"])
        ann_genes = sorted({a["gene_id"] for a in annots[acc]})
        title_genes = [g for g in m["title_genes"].split(";") if g]
        # Genes named only by annotation or title. With no similarity hit at all,
        # these are the only identification available for the record.
        for g in sorted(set(ann_genes) | set(title_genes)):
            if g in used:
                continue
            src = "annotation" if g in ann_genes else "title"
            rows.append(
                {
                    "accession": acc,
                    "gene_id": g,
                    "evidence": src,
                    "annotation_agrees": "",
                    **onto(g),
                }
            )
        if not sim_genes and not ann_genes and not title_genes:
            rows.append({"accession": acc, "gene_id": "", "evidence": "none"})
        named = set(ann_genes) | set(title_genes)
        conflict = []
        if sim_genes and named and not (set(sim_genes) & named):
            conflict.append("similarity and annotation name different genes")
        if disagreements:
            conflict.append("annotated feature overlaps a region of another gene")
        genes = list(dict.fromkeys(sim_genes + sorted(named - set(sim_genes))))
        records.append(
            {
                "accession": acc,
                "organism": m["organism"],
                "tax_id": m["tax_id"],
                "length": m["length"],
                "compartment": m["compartment"],
                "genes": ";".join(genes),
                "similarity_genes": ";".join(dict.fromkeys(sim_genes)),
                "annotation_genes": ";".join(ann_genes),
                "title_genes": ";".join(title_genes),
                "other_labels": "; ".join(other_labels[acc]),
                "conflict": "; ".join(conflict),
                "title": m["title"],
            }
        )
    write_tsv(args.assignments, rows, ASSIGN_COLUMNS)
    write_tsv(args.records, records, RECORD_COLUMNS)


if __name__ == "__main__":
    main()
