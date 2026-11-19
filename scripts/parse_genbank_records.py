"""Extract sequences, specimen metadata, and normalized gene annotations from GenBank records.

Outputs:
- records.fasta: one sequence per record, header = accession.version.
- record_metadata.tsv: organism, tax_id, voucher/isolate, locality, and the
  genes named in the record title (normalized to the gene vocabulary).
- record_annotations.tsv: one row per annotated feature (rRNA, CDS, gene,
  misc_RNA, misc_feature) with its raw label and normalized gene_id. Labels
  naming no gene, or several, get an empty gene_id.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from Bio import SeqIO

from common import Vocabulary, log, write_tsv

META_COLUMNS = [
    "accession",
    "tax_id",
    "organism",
    "length",
    "compartment",
    "specimen_voucher",
    "isolate",
    "country",
    "lat_lon",
    "collection_date",
    "title",
    "title_genes",
    "reference_title",
]
ANNOT_COLUMNS = [
    "accession",
    "feature_type",
    "start",
    "end",
    "strand",
    "label",
    "gene_id",
]
FEATURE_TYPES = {"rRNA", "CDS", "gene", "misc_RNA", "misc_feature", "tRNA"}


def first(q: dict, key: str) -> str:
    return q.get(key, [""])[0]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--accessions", required=True, help="file listing accessions to parse")
    ap.add_argument("--store", required=True)
    ap.add_argument("--vocabulary", required=True)
    ap.add_argument("--fasta", required=True)
    ap.add_argument("--metadata", required=True)
    ap.add_argument("--annotations", required=True)
    args = ap.parse_args()

    vocab = Vocabulary(args.vocabulary)
    accs = [a.strip() for a in open(args.accessions) if a.strip()]
    meta, annots = [], []
    Path(args.fasta).parent.mkdir(parents=True, exist_ok=True)
    tmp_fasta = f"{args.fasta}.tmp"
    with open(tmp_fasta, "w") as fa:
        for acc in accs:
            rec = SeqIO.read(Path(args.store) / f"{acc}.gb", "genbank")
            if rec.id != acc:
                raise SystemExit(f"{acc}: GenBank file holds {rec.id}")
            seq = str(rec.seq).upper()
            if not seq:
                raise SystemExit(f"{acc}: record has no sequence")
            src = next((f for f in rec.features if f.type == "source"), None)
            sq = src.qualifiers if src else {}
            organelle = first(sq, "organelle")
            compartment = "mitochondrion" if "mitochondri" in organelle else "nuclear"
            taxon = next(
                (x.split(":", 1)[1] for x in sq.get("db_xref", []) if x.startswith("taxon:")), ""
            )
            refs = rec.annotations.get("references", [])
            meta.append(
                {
                    "accession": acc,
                    "tax_id": taxon,
                    "organism": first(sq, "organism") or rec.annotations.get("organism"),
                    "length": len(seq),
                    "compartment": compartment,
                    "specimen_voucher": first(sq, "specimen_voucher"),
                    "isolate": first(sq, "isolate"),
                    "country": first(sq, "geo_loc_name") or first(sq, "country"),
                    "lat_lon": first(sq, "lat_lon"),
                    "collection_date": first(sq, "collection_date"),
                    "title": rec.description,
                    "title_genes": ";".join(vocab.find_all(rec.description, compartment)),
                    "reference_title": refs[0].title if refs else "",
                }
            )
            fa.write(f">{acc}\n{seq}\n")
            for f in rec.features:
                if f.type not in FEATURE_TYPES:
                    continue
                q = f.qualifiers
                label = " | ".join(
                    x for x in (first(q, "gene"), first(q, "product"), first(q, "note")) if x
                )
                if not label:
                    continue
                # Normalize gene and product separately first; the note is a
                # fallback because notes often mention neighbouring genes.
                gene_id = None
                for part in (first(q, "gene"), first(q, "product")):
                    if part and not gene_id:
                        gene_id = vocab.normalize(part, compartment)
                if not gene_id and not (first(q, "gene") or first(q, "product")):
                    gene_id = vocab.normalize(first(q, "note"), compartment)
                annots.append(
                    {
                        "accession": acc,
                        "feature_type": f.type,
                        "start": int(f.location.start) + 1,
                        "end": int(f.location.end),
                        "strand": "-" if f.location.strand == -1 else "+",
                        "label": label,
                        "gene_id": gene_id or "",
                    }
                )
    Path(tmp_fasta).replace(args.fasta)
    write_tsv(args.metadata, meta, META_COLUMNS)
    write_tsv(args.annotations, annots, ANNOT_COLUMNS)
    log(f"parsed {len(meta)} records, {len(annots)} annotated features")


if __name__ == "__main__":
    main()
