"""Combine one marker gene's sequences from all data sources into a tree input set.

Sources and dataset identities:
- ncbi: GenBank record regions identified as the gene (dataset = accession).
- sra: sharkmer products confirmed by similarity to be the targeted gene
  (dataset = run accession). Products whose best match is another gene, or
  nothing, are excluded as off-target.
- genome: regions extracted from genome assemblies (dataset = assembly).
- ref: reference marker sequences from outside the focal clade, kept as
  outgroups to help place contaminants and non-siphonophore sequences.

Tip labels follow the lab convention `Genus_species@<source>-<dataset>[-n]`.
Alignment and tree tools receive short internal ids (`seq00001`) instead,
because some tools rewrite characters such as `@`; relabel_tree.py restores
the tip labels on the final tree.

Sequences of at least --backbone-min-length form the alignment backbone; shorter
ones (barcodes, partial sequences) are written separately and added to the
backbone alignment as fragments. If fewer than four sequences reach the
backbone length, all sequences form the backbone.

tip_metadata.tsv lists every candidate sequence, including those left out of
the tree and why, with the taxonomy used to evaluate placements.
"""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from Bio import SeqIO

from common import read_tsv, sanitize, species_prefix, write_tsv

COLUMNS = [
    "tip_id",
    "seq_id",
    "role",
    "gene_id",
    "source",
    "dataset",
    "sequence_id",
    "tax_id",
    "organism",
    "species",
    "genus",
    "family",
    "suborder",
    "in_focal_clade",
    "voucher",
    "length",
    "included",
    "exclusion_reason",
]


def read_fasta(path: str) -> dict[str, str]:
    return {r.id: str(r.seq) for r in SeqIO.parse(path, "fasta")} if Path(path).exists() else {}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--gene", required=True)
    ap.add_argument("--min-length", type=int, required=True)
    ap.add_argument("--backbone-min-length", type=int, required=True)
    ap.add_argument("--taxonomy", required=True)
    ap.add_argument("--ncbi-regions", required=True)
    ap.add_argument("--ncbi-fasta", required=True)
    ap.add_argument("--ncbi-metadata", required=True)
    ap.add_argument("--sra-products", required=True, help="sharkmer products table")
    ap.add_argument("--sra-regions", required=True)
    ap.add_argument("--sra-fasta", required=True)
    ap.add_argument("--sra-inventory", required=True)
    ap.add_argument("--genome-regions", nargs="*", default=[])
    ap.add_argument("--genome-fastas", nargs="*", default=[])
    ap.add_argument("--genome-inventory", required=True)
    ap.add_argument("--references", required=True)
    ap.add_argument("--reference-fasta", required=True)
    ap.add_argument("--backbone", required=True, help="FASTA of backbone sequences")
    ap.add_argument("--fragments", required=True, help="FASTA of short sequences")
    ap.add_argument("--table", required=True)
    args = ap.parse_args()

    tax = {r["tax_id"]: r for r in read_tsv(args.taxonomy)}
    cands = []  # (source, dataset, sequence_id, tax_id, organism, voucher, seq, reason)

    meta = {r["accession"]: r for r in read_tsv(args.ncbi_metadata)}
    seqs = read_fasta(args.ncbi_fasta)
    for r in read_tsv(args.ncbi_regions):
        if r["gene_id"] != args.gene:
            continue
        m = meta[r["target"]]
        cands.append(
            (
                "ncbi",
                r["target"],
                r["region_id"],
                m["tax_id"],
                m["organism"],
                m["specimen_voucher"] or m["isolate"],
                seqs[r["region_id"]],
                "",
            )
        )

    runs = {r["accession"]: r for r in read_tsv(args.sra_inventory)}
    regions = {}
    for r in read_tsv(args.sra_regions):
        regions.setdefault(r["target"], []).append(r)
    seqs = read_fasta(args.sra_fasta)
    for p in read_tsv(args.sra_products):
        if p["gene_id"] != args.gene:
            continue
        run = runs[p["run"]]
        found = regions.get(p["product_id"], [])
        best = max(found, key=lambda r: float(r["score"])) if found else None
        if p["included"] != "true":
            seq, reason = "", f"sharkmer assembly status {p['assembly_status']}"
        elif best is None:
            seq, reason = "", "no similarity to reference markers"
        elif best["gene_id"] != args.gene:
            seq, reason = "", f"off-target product: best match {best['gene_id']}"
        else:
            seq, reason = seqs[best["region_id"]], ""
        cands.append(
            (
                "sra",
                p["run"],
                p["product_id"],
                run["tax_id"],
                run["scientific_name"],
                run["specimen_voucher"] or run["isolate"],
                seq,
                reason,
            )
        )

    genomes = {r["accession"]: r for r in read_tsv(args.genome_inventory)}
    for reg_path, fa_path in zip(args.genome_regions, args.genome_fastas, strict=True):
        seqs = read_fasta(fa_path)
        asm = Path(reg_path).parent.name
        g = genomes[asm]
        for r in read_tsv(reg_path):
            if r["gene_id"] == args.gene:
                cands.append(
                    (
                        "genome",
                        asm,
                        r["region_id"],
                        g["tax_id"],
                        g["organism"],
                        "",
                        seqs[r["region_id"]],
                        "",
                    )
                )

    seqs = read_fasta(args.reference_fasta)
    for r in read_tsv(args.references):
        t = tax.get(r["tax_id"], {})
        if r["gene_id"] == args.gene and t.get("in_focal_clade") == "false":
            cands.append(
                (
                    "ref",
                    r["accession"],
                    r["ref_id"],
                    r["tax_id"],
                    r["taxon"],
                    "",
                    seqs[r["ref_id"]],
                    "",
                )
            )

    rows, used, seqs_out = [], Counter(), {}
    for source, dataset, sid, tax_id, organism, voucher, seq, reason in cands:
        t = tax.get(tax_id, {})
        name = t.get("scientific_name") or organism or "unknown"
        base = f"{species_prefix(name)}@{source}-{sanitize(dataset)}"
        used[base] += 1
        tip = base if used[base] == 1 else f"{base}-{used[base]}"
        if not reason and len(seq) < args.min_length:
            reason = f"shorter than {args.min_length} bp"
        if not reason and set(seq) - set("ACGTRYSWKMBDHVN"):
            reason = "non-nucleotide characters"
        seq_id = ""
        if not reason:
            seq_id = f"seq{len(seqs_out) + 1:05d}"
            seqs_out[seq_id] = seq
        rows.append(
            {
                "tip_id": tip,
                "seq_id": seq_id,
                "gene_id": args.gene,
                "source": source,
                "dataset": dataset,
                "sequence_id": sid,
                "tax_id": tax_id,
                "organism": name,
                "species": t.get("species", ""),
                "genus": t.get("genus", ""),
                "family": t.get("family", ""),
                "suborder": t.get("suborder", ""),
                "in_focal_clade": t.get("in_focal_clade", ""),
                "voucher": voucher,
                "length": len(seq),
                "included": str(not reason).lower(),
                "exclusion_reason": reason,
            }
        )

    long_ids = {k for k, v in seqs_out.items() if len(v) >= args.backbone_min_length}
    if len(long_ids) < 4:
        long_ids = set(seqs_out)
    for r in rows:
        if r["seq_id"]:
            r["role"] = "backbone" if r["seq_id"] in long_ids else "fragment"
    Path(args.backbone).parent.mkdir(parents=True, exist_ok=True)
    with open(args.backbone, "w") as bb, open(args.fragments, "w") as fr:
        for k, v in seqs_out.items():
            (bb if k in long_ids else fr).write(f">{k}\n{v}\n")
    tips = [r["tip_id"] for r in rows]
    if len(tips) != len(set(tips)):
        raise SystemExit("Tip labels are not unique")
    write_tsv(args.table, rows, COLUMNS)


if __name__ == "__main__":
    main()
