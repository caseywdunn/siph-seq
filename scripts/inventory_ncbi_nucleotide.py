"""Inventory all NCBI nucleotide records for a clade.

Queries `txid<taxid>[Organism:exp]` and classifies each record so that the
manifest covers everything public while only gene records and mitochondrial
genomes go on to marker identification:

- gene_record: an ordinary GenBank submission (genes, amplicons, rDNA).
- mitochondrial_genome: a mitochondrial record of at least 10 kb.
- assembly_component: a chromosome, scaffold, or WGS/TSA contig belonging to an
  assembly; genome assemblies are handled through the genome route.
- project_master: a WGS or TSA project master record (no sequence of its own).
"""

from __future__ import annotations

import argparse
import re

from common import check_taxon, entrez, log, write_tsv

COLUMNS = [
    "accession",
    "uid",
    "record_type",
    "selected",
    "tax_id",
    "organism",
    "length",
    "molecule",
    "organelle",
    "title",
    "create_date",
    "update_date",
]

# WGS/TSA component accessions: 4-6 letter project prefix, 2-digit version,
# then 6+ digits (e.g. JAXZRT010000001.1). Masters end in zeros.
WGS_RE = re.compile(r"^[A-Z]{4,6}\d{8,}\.\d+$")
MASTER_RE = re.compile(r"^[A-Z]{4,6}0{8,}\.\d+$|^[A-Z]{4,6}\d{2}0{6,}\.\d+$")


def classify(doc: dict, max_length: int) -> str:
    """Assign a record type from an esummary document."""
    acc = doc["accessionversion"]
    title = doc.get("title", "")
    genome = doc.get("genome", "")
    if MASTER_RE.match(acc) or title.startswith(("TSA:", "WGS:")):
        return "project_master"
    if WGS_RE.match(acc) or genome in ("chromosome", "plasmid") or int(doc["slen"]) > max_length:
        return "assembly_component"
    if genome == "mitochondrion" and int(doc["slen"]) >= 10000:
        return "mitochondrial_genome"
    return "gene_record"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--taxid", type=int, required=True)
    ap.add_argument("--taxon-name", required=True)
    ap.add_argument("--max-record-length", type=int, required=True)
    ap.add_argument("--process-record-types", nargs="+", required=True)
    ap.add_argument("--batch-size", type=int, default=200)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    check_taxon(args.taxid, args.taxon_name)
    term = f"txid{args.taxid}[Organism:exp]"
    r = entrez("esearch", {"db": "nuccore", "term": term, "retmode": "json", "retmax": 0})
    count = int(r.json()["esearchresult"]["count"])
    log(f"{term}: {count} nucleotide records")

    uids: list[str] = []
    step = 10000
    for start in range(0, count, step):
        r = entrez(
            "esearch",
            {
                "db": "nuccore",
                "term": term,
                "retmode": "json",
                "retstart": start,
                "retmax": step,
                "idtype": "acc",
            },
        )
        uids.extend(r.json()["esearchresult"]["idlist"])
    if len(set(uids)) != count:
        raise SystemExit(f"esearch returned {len(set(uids))} unique ids, expected {count}")

    rows = []
    for i in range(0, len(uids), args.batch_size):
        batch = uids[i : i + args.batch_size]
        r = entrez(
            "esummary", {"db": "nuccore", "id": ",".join(batch), "retmode": "json"}, post=True
        )
        res = r.json()["result"]
        for uid in res["uids"]:
            d = res[uid]
            rtype = classify(d, args.max_record_length)
            rows.append(
                {
                    "accession": d["accessionversion"],
                    "uid": uid,
                    "record_type": rtype,
                    "selected": str(rtype in args.process_record_types).lower(),
                    "tax_id": d.get("taxid"),
                    "organism": d.get("organism"),
                    "length": d.get("slen"),
                    "molecule": d.get("biomol"),
                    "organelle": d.get("genome"),
                    "title": d.get("title"),
                    "create_date": d.get("createdate"),
                    "update_date": d.get("updatedate"),
                }
            )
        log(f"  summarized {len(rows)}/{len(uids)}")

    accs = [r["accession"] for r in rows]
    if len(accs) != len(set(accs)) or len(rows) != count:
        raise SystemExit(
            f"Inventory has {len(rows)} rows ({len(set(accs))} unique), expected {count}"
        )
    rows.sort(key=lambda r: r["accession"])
    write_tsv(args.out, rows, COLUMNS)


if __name__ == "__main__":
    main()
