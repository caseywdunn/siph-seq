"""Resolve NCBI taxonomy lineages for every tax_id in the inventories.

Writes one row per tax_id with the named ranks used to judge whether a
sequence sits where its label predicts (species, genus, family, suborder,
order) and whether it falls within the focal clade.
"""

from __future__ import annotations

import argparse
import xml.etree.ElementTree as ET

from common import entrez, log, read_tsv, write_tsv

RANKS = ["species", "genus", "family", "suborder", "order", "class", "phylum"]
COLUMNS = ["tax_id", "scientific_name", "rank", *RANKS, "in_focal_clade", "lineage"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tables", nargs="+", required=True, help="TSVs with a tax_id column")
    ap.add_argument("--focal-taxid", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    taxids = sorted(
        {r["tax_id"] for t in args.tables for r in read_tsv(t) if r.get("tax_id")}, key=int
    )
    log(f"resolving {len(taxids)} tax_ids")
    rows = {}
    for i in range(0, len(taxids), 200):
        batch = taxids[i : i + 200]
        xml = entrez(
            "efetch", {"db": "taxonomy", "id": ",".join(batch), "retmode": "xml"}, post=True
        )
        for taxon in ET.fromstring(xml.content).findall("Taxon"):
            tid = taxon.findtext("TaxId")
            row = {
                "tax_id": tid,
                "scientific_name": taxon.findtext("ScientificName"),
                "rank": taxon.findtext("Rank"),
                "lineage": taxon.findtext("Lineage"),
            }
            lineage_ids = []
            for t in taxon.findall("LineageEx/Taxon"):
                lineage_ids.append(t.findtext("TaxId"))
                if t.findtext("Rank") in RANKS:
                    row[t.findtext("Rank")] = t.findtext("ScientificName")
            if row["rank"] in RANKS:
                row[row["rank"]] = row["scientific_name"]
            row["in_focal_clade"] = str(
                args.focal_taxid in lineage_ids or tid == args.focal_taxid
            ).lower()
            rows[tid] = row
            # Merged tax_ids are returned under their current id; keep the old one too.
            for aka in taxon.findall("AkaTaxIds/TaxId"):
                rows[aka.text] = dict(row, tax_id=aka.text)
    missing = [t for t in taxids if t not in rows]
    if missing:
        raise SystemExit(f"Taxonomy lookup did not return tax_ids: {', '.join(missing[:20])}")
    write_tsv(args.out, [rows[t] for t in taxids], COLUMNS)


if __name__ == "__main__":
    main()
