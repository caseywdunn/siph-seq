"""Describe the study behind each flagged or unresolved dataset.

Report readers are usually the people behind one study, so the release report
groups datasets by study. A study is a publication, a BioProject, or a
submitter, taken from:

- GenBank records: the REFERENCE blocks of the stored flat file. The first
  reference that is not the "Direct Submission" gives the publication (or the
  unpublished manuscript title); the Direct Submission gives the submitter.
- SRA runs: the ENA study (BioProject), its title and submitting centre.
- Genome assemblies: the BioProject and submitter from NCBI Datasets.

Usage:
    python scripts/describe_studies.py --placements .../placements.tsv ... \
        --sra-runs .../sra_runs.tsv --genomes .../genomes.tsv \
        --genbank-store data/ncbi_nucleotide --out .../studies.tsv
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from Bio import SeqIO

from common import http_request, log, read_tsv, write_tsv

REPORTED = {"outside_focal_clade", "family_mismatch", "genus_mismatch", "unresolved"}
ENA_SEARCH = "https://www.ebi.ac.uk/ena/portal/api/search"
COLUMNS = [
    "source",
    "accession",
    "study_id",
    "study_label",
    "short_label",
    "authors",
    "title",
    "journal",
    "year",
    "pubmed",
    "bioproject",
    "submitter",
    "submitted",
]


def first_author(authors: str) -> str:
    """'Bergmeier,F.S., Ostermair,L. and Jorger,K.M.' -> 'Bergmeier et al.'"""
    names = [a.strip() for a in re.split(r",\s(?=[^,]+,)|\sand\s", authors) if a.strip()]
    if not names:
        return ""
    surname = names[0].split(",")[0]
    return surname if len(names) == 1 else f"{surname} et al."


def genbank_study(path: Path) -> dict:
    record = SeqIO.read(path, "genbank")
    refs = record.annotations.get("references", [])
    pub = next((r for r in refs if r.title and r.title != "Direct Submission"), None)
    sub = next((r for r in refs if r.title == "Direct Submission"), None)
    out = {}
    if sub is not None:
        m = re.match(r"Submitted \((\d{2}-[A-Z]{3}-(\d{4}))\)\s*(.*)", sub.journal or "")
        out["submitted"] = m.group(1) if m else ""
        institution = m.group(3).split(",")[0].strip() if m else ""
        out["submitter"] = ", ".join(x for x in (first_author(sub.authors), institution) if x)
        out["year"] = m.group(2) if m else ""
    projects = [x.split(":", 1)[1] for x in record.dbxrefs if x.startswith("BioProject:")]
    out["bioproject"] = projects[0] if projects else ""
    if pub is not None:
        year = re.search(r"\((\d{4})\)", pub.journal or "")
        out.update(
            authors=pub.authors or pub.consrtm or "",
            title=pub.title.rstrip("."),
            journal=pub.journal or "",
            pubmed=pub.pubmed_id or "",
        )
        if year:
            out["year"] = year.group(1)
        lead = first_author(out["authors"])
        if out["journal"] == "Unpublished":
            when = f", submitted {out['year']}" if out.get("year") else ""
            out["study_label"] = f"{lead} (unpublished{when}). {out['title']}"
            out["short_label"] = f"{lead}, unpublished" + (
                f" ({out['year']})" if out.get("year") else ""
            )
        else:
            out["study_label"] = f"{lead} ({out['year']}). {out['title']}. {out['journal']}"
            out["short_label"] = f"{lead} ({out['year']})"
        out["study_id"] = f"ref:{lead}:{out['title'].lower()}"
    elif out.get("submitter"):
        out["study_label"] = f"Submitted by {out['submitter']}"
        out["short_label"] = out["study_label"]
        out["study_id"] = f"sub:{out['submitter'].lower()}"
    return out


def ena_studies(runs: list[str]) -> dict[str, dict]:
    """Study, title and submitting centre for SRA runs, from ENA."""
    out = {}
    for i in range(0, len(runs), 50):
        chunk = runs[i : i + 50]
        r = http_request(
            "GET",
            ENA_SEARCH,
            params={
                "result": "read_run",
                "query": " OR ".join(f"run_accession={a}" for a in chunk),
                "fields": "run_accession,study_accession,study_title,center_name,first_public",
                "format": "tsv",
                "limit": 0,
            },
        )
        lines = r.text.strip().splitlines()
        header = lines[0].split("\t")
        for line in lines[1:]:
            row = dict(zip(header, line.split("\t"), strict=False))
            out[row["run_accession"]] = row
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--placements", nargs="+", required=True)
    ap.add_argument("--sra-runs", required=True)
    ap.add_argument("--genomes", required=True)
    ap.add_argument("--genbank-store", required=True, type=Path)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    wanted: set[tuple[str, str]] = set()
    for path in args.placements:
        for p in read_tsv(path):
            if p["flag"] in REPORTED and p["source"] != "ref":
                wanted.add((p["source"], p["dataset"]))
    sra_inv = {r["run_accession"]: r for r in read_tsv(args.sra_runs)}
    genomes = {r["accession"]: r for r in read_tsv(args.genomes)}
    ena = ena_studies(sorted(a for s, a in wanted if s == "sra"))

    rows = []
    for source, acc in sorted(wanted):
        row = {"source": source, "accession": acc}
        if source == "ncbi":
            row.update(genbank_study(args.genbank_store / f"{acc}.gb"))
        elif source == "sra":
            e = ena.get(acc) or sra_inv.get(acc, {})
            project = e.get("study_accession", "")
            centre = e.get("center_name", "")
            if re.fullmatch(r"SUB\d+", centre):
                centre = ""  # a submission id, not a centre name
            row.update(
                bioproject=project,
                title=e.get("study_title", ""),
                submitter=centre,
                submitted=e.get("first_public", ""),
                study_id=f"project:{project}",
                short_label=f"BioProject {project}",
                study_label=f"BioProject {project}: {e.get('study_title', '')}"
                + (f" (submitted by {centre})" if centre else ""),
            )
        elif source == "genome":
            g = genomes.get(acc, {})
            project = g.get("bioproject", "")
            row.update(
                bioproject=project,
                title=g.get("assembly_name", ""),
                submitter=g.get("submitter", ""),
                submitted=g.get("release_date", ""),
                study_id=f"project:{project}",
                short_label=f"BioProject {project}",
                study_label=f"BioProject {project}: genome assembly {g.get('assembly_name', '')}"
                + (f" (submitted by {g['submitter']})" if g.get("submitter") else ""),
            )
        if not row.get("study_id"):
            row["study_id"] = f"dataset:{acc}"
            row["study_label"] = f"{acc} (no study information)"
            row["short_label"] = acc
        rows.append(row)
    write_tsv(args.out, rows, COLUMNS)
    log(f"described {len(rows)} datasets in {len({r['study_id'] for r in rows})} studies")


if __name__ == "__main__":
    main()
