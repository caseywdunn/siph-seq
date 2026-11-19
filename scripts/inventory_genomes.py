"""Inventory genome assemblies for a clade from the NCBI Datasets API.

Lists every assembly. GenBank (GCA) assemblies are selected by default; RefSeq
(GCF) entries duplicate a GCA assembly and are recorded but not processed.
"""

from __future__ import annotations

import argparse

from common import check_taxon, http_request, log, write_tsv

API = "https://api.ncbi.nlm.nih.gov/datasets/v2/genome/taxon/{taxid}/dataset_report"
COLUMNS = [
    "accession",
    "selected",
    "selection_reason",
    "paired_accession",
    "tax_id",
    "organism",
    "assembly_name",
    "assembly_level",
    "total_length",
    "contig_n50",
    "scaffold_n50",
    "release_date",
    "bioproject",
    "biosample",
    "submitter",
]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--taxid", type=int, required=True)
    ap.add_argument("--taxon-name", required=True)
    ap.add_argument("--prefix", default="GCA")
    ap.add_argument("--include", nargs="*", default=None, help="pilot: only these accessions")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    check_taxon(args.taxid, args.taxon_name)
    reports, token = [], None
    while True:
        params = {"page_size": 1000}
        if token:
            params["page_token"] = token
        d = http_request("GET", API.format(taxid=args.taxid), params=params).json()
        reports.extend(d.get("reports", []))
        token = d.get("next_page_token")
        if not token:
            break
    log(f"NCBI Datasets taxon {args.taxid}: {len(reports)} assemblies")

    rows = []
    for rep in reports:
        info, stats = rep.get("assembly_info", {}), rep.get("assembly_stats", {})
        acc = rep["accession"]
        reasons = []
        if not acc.startswith(args.prefix):
            reasons.append(f"{acc[:3]} copy of {rep.get('paired_accession', '')}")
        if args.include is not None and acc not in args.include:
            reasons.append("not in pilot include list")
        rows.append(
            {
                "accession": acc,
                "selected": str(not reasons).lower(),
                "selection_reason": "; ".join(reasons) or "genome assembly",
                "paired_accession": rep.get("paired_accession"),
                "tax_id": rep["organism"].get("tax_id"),
                "organism": rep["organism"].get("organism_name"),
                "assembly_name": info.get("assembly_name"),
                "assembly_level": info.get("assembly_level"),
                "total_length": stats.get("total_sequence_length"),
                "contig_n50": stats.get("contig_n50"),
                "scaffold_n50": stats.get("scaffold_n50"),
                "release_date": info.get("release_date"),
                "bioproject": info.get("bioproject_accession"),
                "biosample": info.get("biosample", {}).get("accession"),
                "submitter": info.get("submitter"),
            }
        )
    rows.sort(key=lambda r: r["accession"])
    write_tsv(args.out, rows, COLUMNS)


if __name__ == "__main__":
    main()
