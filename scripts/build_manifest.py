"""Combine the three inventories into one manifest of all public siphonophore sequence data.

One row per public dataset (GenBank record, SRA run, genome assembly), with
harmonized columns, NCBI taxonomy, and the workflow route that processes it.
Datasets that are inventoried but not processed say why in selection_reason.
"""

from __future__ import annotations

import argparse

from common import read_tsv, write_tsv

COLUMNS = [
    "source",
    "accession",
    "data_type",
    "platform",
    "tax_id",
    "organism",
    "species",
    "genus",
    "family",
    "suborder",
    "in_focal_clade",
    "size_bp",
    "n_reads",
    "date",
    "voucher",
    "project",
    "title",
    "selected",
    "selection_reason",
    "route",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--ncbi", required=True)
    ap.add_argument("--sra", required=True)
    ap.add_argument("--genomes", required=True)
    ap.add_argument("--taxonomy", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    tax = {r["tax_id"]: r for r in read_tsv(args.taxonomy)}
    rows = []
    for r in read_tsv(args.ncbi):
        sel = r["selected"] == "true"
        rows.append(
            {
                "source": "ncbi_nucleotide",
                "accession": r["accession"],
                "data_type": r["record_type"],
                "tax_id": r["tax_id"],
                "organism": r["organism"],
                "size_bp": r["length"],
                "date": r["create_date"],
                "title": r["title"],
                "selected": r["selected"],
                "selection_reason": r["record_type"]
                if sel
                else f"{r['record_type']} not processed",
                "route": "marker_identification" if sel else "inventory_only",
            }
        )
    for r in read_tsv(args.sra):
        sel = r["selected"] == "true"
        rows.append(
            {
                "source": "sra_run",
                "accession": r["accession"],
                "data_type": f"{r['library_strategy']} {r['library_source']}".strip(),
                "platform": f"{r['instrument_platform']} {r['instrument_model']}".strip(),
                "tax_id": r["tax_id"],
                "organism": r["scientific_name"],
                "size_bp": r["base_count"],
                "n_reads": r["read_count"],
                "date": r["first_public"],
                "voucher": r["specimen_voucher"] or r["isolate"],
                "project": r["study_accession"],
                "title": r["study_title"],
                "selected": r["selected"],
                "selection_reason": r["selection_reason"],
                "route": "sharkmer" if sel else "inventory_only",
            }
        )
    for r in read_tsv(args.genomes):
        sel = r["selected"] == "true"
        rows.append(
            {
                "source": "genome_assembly",
                "accession": r["accession"],
                "data_type": r["assembly_level"],
                "tax_id": r["tax_id"],
                "organism": r["organism"],
                "size_bp": r["total_length"],
                "date": r["release_date"],
                "project": r["bioproject"],
                "title": r["assembly_name"],
                "selected": r["selected"],
                "selection_reason": r["selection_reason"],
                "route": "genome_marker_extraction" if sel else "inventory_only",
            }
        )
    for row in rows:
        t = tax.get(row["tax_id"], {})
        for k in ("species", "genus", "family", "suborder", "in_focal_clade"):
            row[k] = t.get(k, "")
    keys = [(r["source"], r["accession"]) for r in rows]
    if len(keys) != len(set(keys)):
        raise SystemExit("Duplicate datasets in manifest")
    write_tsv(args.out, rows, COLUMNS)


if __name__ == "__main__":
    main()
