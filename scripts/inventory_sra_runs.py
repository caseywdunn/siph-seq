"""Inventory all public read runs for a clade from ENA.

ENA mirrors NCBI SRA, and sharkmer streams reads from ENA, so ENA's portal API
is the single source for run metadata. Every run is listed; runs whose
sequencing platform and library strategy suit sharkmer's short-read k-mer
assembly are marked `selected`, and the reason is recorded for the others.
"""

from __future__ import annotations

import argparse
import csv
import io

from common import check_taxon, http_request, log, write_tsv

PORTAL = "https://www.ebi.ac.uk/ena/portal/api/search"
FIELDS = [
    "run_accession",
    "experiment_accession",
    "sample_accession",
    "secondary_sample_accession",
    "study_accession",
    "secondary_study_accession",
    "tax_id",
    "scientific_name",
    "library_strategy",
    "library_source",
    "library_selection",
    "library_layout",
    "instrument_platform",
    "instrument_model",
    "read_count",
    "base_count",
    "first_public",
    "last_updated",
    "fastq_ftp",
    "specimen_voucher",
    "isolate",
    "sample_title",
    "study_title",
    "country",
    "collection_date",
]
COLUMNS = ["accession", "selected", "selection_reason", *FIELDS]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--taxid", type=int, required=True)
    ap.add_argument("--taxon-name", required=True)
    ap.add_argument("--platforms", nargs="+", required=True)
    ap.add_argument("--strategies", nargs="+", required=True)
    ap.add_argument("--max-runs", type=int, default=None, help="pilot cap on selected runs")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    check_taxon(args.taxid, args.taxon_name)
    params = {
        "result": "read_run",
        "query": f"tax_tree({args.taxid})",
        "fields": ",".join(FIELDS),
        "format": "tsv",
        "limit": 0,
    }
    text = http_request("GET", PORTAL, params=params).text
    rows = list(csv.DictReader(io.StringIO(text), delimiter="\t"))
    log(f"ENA tax_tree({args.taxid}): {len(rows)} runs")

    n_selected = 0
    for r in sorted(rows, key=lambda r: r["run_accession"]):
        r["accession"] = r["run_accession"]
        reasons = []
        if r["instrument_platform"] not in args.platforms:
            reasons.append(f"platform {r['instrument_platform']} not short-read")
        if r["library_strategy"] not in args.strategies:
            reasons.append(f"strategy {r['library_strategy']} not selected")
        if not r["fastq_ftp"]:
            reasons.append("no FASTQ at ENA")
        if not reasons and args.max_runs is not None and n_selected >= args.max_runs:
            reasons.append("beyond pilot max_runs")
        r["selected"] = str(not reasons).lower()
        r["selection_reason"] = "; ".join(reasons) or "short-read run"
        n_selected += not reasons

    runs = [r["accession"] for r in rows]
    if len(runs) != len(set(runs)):
        raise SystemExit("Duplicate run accessions in ENA response")
    rows.sort(key=lambda r: r["accession"])
    write_tsv(args.out, rows, COLUMNS)
    log(f"  {n_selected} runs selected for sharkmer")


if __name__ == "__main__":
    main()
