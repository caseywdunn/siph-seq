"""Build the reference marker set used to identify genes by sequence similarity.

Two sources, both traceable to public records:
1. The sharkmer panel's reference regions: the amplicon spanned by each
   primer pair, from siphonophores and other hydrozoans.
2. Annotated rRNA, CDS, and misc_RNA features of the configured reference
   records (mitochondrial genomes and nuclear rRNA records), whose labels are
   normalized with the gene vocabulary. Features with unrecognized or
   ambiguous labels are skipped.

Identical sequences within a gene are kept once.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import yaml
from Bio import SeqIO

from common import Vocabulary, log, sanitize, write_tsv

COLUMNS = [
    "ref_id",
    "gene_id",
    "source",
    "accession",
    "taxon",
    "tax_id",
    "start",
    "end",
    "strand",
    "length",
]


def record_taxid(store: Path, acc: str) -> str:
    path = store / f"{acc}.gb"
    if not path.exists():
        return ""
    rec = SeqIO.read(path, "genbank")
    for f in rec.features:
        if f.type == "source":
            for x in f.qualifiers.get("db_xref", []):
                if x.startswith("taxon:"):
                    return x.split(":", 1)[1]
    return ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--panel", required=True, help="sharkmer panel YAML")
    ap.add_argument("--gene-map", nargs="+", required=True, help="panel_gene=gene_id pairs")
    ap.add_argument("--records", nargs="*", default=[], help="reference record accessions")
    ap.add_argument("--store", required=True)
    ap.add_argument("--vocabulary", required=True)
    ap.add_argument("--fasta", required=True)
    ap.add_argument("--table", required=True)
    args = ap.parse_args()

    vocab = Vocabulary(args.vocabulary)
    gene_map = dict(x.split("=", 1) for x in args.gene_map)
    store = Path(args.store)
    rows, seqs, seen = [], {}, set()

    def add(gene_id, source, acc, taxon, start, end, strand, seq):
        seq = seq.upper()
        if (gene_id, seq) in seen or len(seq) < 50:
            return
        seen.add((gene_id, seq))
        ref_id = f"{sanitize(gene_id)}__{source}__{acc}__{len(rows) + 1}"
        rows.append(
            {
                "ref_id": ref_id,
                "gene_id": gene_id,
                "source": source,
                "accession": acc,
                "taxon": taxon,
                "tax_id": record_taxid(store, acc),
                "start": start,
                "end": end,
                "strand": strand,
                "length": len(seq),
            }
        )
        seqs[ref_id] = seq

    panel = yaml.safe_load(open(args.panel))
    for block in panel.get("references", []):
        gene_id = gene_map.get(block["gene"])
        if gene_id is None:
            raise SystemExit(f"Panel gene {block['gene']} has no entry in sharkmer.gene_map")
        if gene_id not in vocab.by_id:
            raise SystemExit(f"gene_map target {gene_id} is not in the gene vocabulary")
        for s in block.get("sequences", []):
            prov = s.get("provenance", {})
            add(
                gene_id,
                "panel",
                s["accession"],
                s.get("taxon", ""),
                prov.get("start", ""),
                prov.get("end", ""),
                prov.get("strand", ""),
                s["sequence"],
            )

    for acc in args.records:
        rec = SeqIO.read(store / f"{acc}.gb", "genbank")
        src = next((f for f in rec.features if f.type == "source"), None)
        organelle = src.qualifiers.get("organelle", [""])[0] if src else ""
        compartment = "mitochondrion" if "mitochondri" in organelle else "nuclear"
        organism = rec.annotations.get("organism", "")
        n_before = len(rows)
        for f in rec.features:
            if f.type not in ("rRNA", "CDS", "misc_RNA"):
                continue
            gene_id = None
            for key in ("gene", "product"):
                label = f.qualifiers.get(key, [""])[0]
                if label and not gene_id:
                    gene_id = vocab.normalize(label, compartment)
            if gene_id:
                add(
                    gene_id,
                    "record",
                    acc,
                    organism,
                    int(f.location.start) + 1,
                    int(f.location.end),
                    "-" if f.location.strand == -1 else "+",
                    str(f.extract(rec.seq)),
                )
        if len(rows) == n_before:
            log(f"warning: reference record {acc} contributed no recognized features")

    Path(args.fasta).parent.mkdir(parents=True, exist_ok=True)
    with open(args.fasta, "w") as fa:
        for ref_id, seq in seqs.items():
            fa.write(f">{ref_id}\n{seq}\n")
    write_tsv(args.table, rows, COLUMNS)
    genes = sorted({r["gene_id"] for r in rows})
    log(f"{len(rows)} reference sequences for {len(genes)} genes: {', '.join(genes)}")


if __name__ == "__main__":
    main()
