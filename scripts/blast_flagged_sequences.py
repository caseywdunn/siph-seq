"""BLAST each flagged sequence against GenBank and classify the top hits.

A flagged sequence can belong to another siphonophore, or not be a
siphonophore sequence at all (contamination, symbionts, prey). Searching it
against NCBI's nucleotide collection shows which, with links readers can
follow. Searches run at NCBI through the BLAST URL API, all sequences in
one request, because NCBI queues remote searches. Results are cached by sequence, database and
task under --cache, and reused until older than --max-age-days, so later
releases only search new or changed sequences.

Each hit is classified from its NCBI Taxonomy lineage as a siphonophore, a
hydrozoan that is not a siphonophore, another cnidarian, or the phylum (or
kingdom) it belongs to. Hits to the query's own GenBank record are dropped.

Usage:
    python scripts/blast_flagged_sequences.py --tree-dirs results/releases/R/trees/CO1 ... \
        --cache results/blast_remote --out results/releases/R/reports/blast_hits.tsv
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from Bio import SeqIO

from common import TOOL_NAME, entrez, http_request, log, read_tsv, write_tsv

FLAGGED = {"outside_focal_clade", "family_mismatch", "genus_mismatch"}
BLAST_URL = "https://blast.ncbi.nlm.nih.gov/Blast.cgi"
HIT_COLUMNS = ["sacc", "pident", "length", "qcovs", "evalue", "bitscore"]
COLUMNS = [
    "gene_id",
    "tip_id",
    "source",
    "dataset",
    "query_length",
    "hit_rank",
    "hit_accession",
    "hit_organism",
    "hit_taxid",
    "hit_group",
    "hit_title",
    "pident",
    "align_length",
    "query_coverage",
    "evalue",
    "bitscore",
    "database",
    "searched",
    "status",
]


def cache_key(seq: str, db: str, task: str) -> str:
    return hashlib.sha1(f"{db}|{task}|{seq.upper()}".encode()).hexdigest()


def read_cache(path: Path, max_age_days: int) -> tuple[str, list[dict]] | None:
    """Cached hits and search date, or None if missing or stale."""
    if not path.exists():
        return None
    lines = path.read_text().splitlines()
    searched = lines[0].removeprefix("# searched ")
    age = dt.date.today() - dt.date.fromisoformat(searched)
    if age.days > max_age_days:
        return None
    hits = [dict(zip(HIT_COLUMNS, line.split("\t"), strict=True)) for line in lines[1:]]
    return searched, hits


def run_remote_blast(queries: dict[str, str], db: str, task: str, max_hits: int) -> dict:
    """Search queries at NCBI through the BLAST URL API; returns hits per query id.

    The URL API is used instead of `blastn -remote`, which hung for over half an
    hour on searches the URL API finished in a minute. Status is polled once a
    minute, as NCBI's usage guidelines ask.
    """
    if task not in ("megablast", "blastn"):
        raise SystemExit(f"--task {task} is not supported for remote searches")
    ids = list(queries)
    fasta = "".join(f">{q}\n{queries[q]}\n" for q in ids)
    params = {
        "CMD": "Put",
        "PROGRAM": "blastn",
        "DATABASE": db,
        "QUERY": fasta,
        "EXPECT": "1e-10",
        "HITLIST_SIZE": str(max_hits),
        "TOOL": TOOL_NAME,
    }
    if task == "megablast":
        params["MEGABLAST"] = "on"
    put = http_request("POST", BLAST_URL, data=params).text
    m = re.search(r"RID = (\S+)", put)
    if not m:
        raise RuntimeError(f"BLAST submission failed: {put[:500]}")
    rid = m.group(1)
    log(f"remote BLAST of {len(ids)} sequences against {db}: RID {rid}")
    deadline = time.time() + 6 * 3600
    while True:
        time.sleep(60)
        info = http_request(
            "GET", BLAST_URL, params={"CMD": "Get", "FORMAT_OBJECT": "SearchInfo", "RID": rid}
        ).text
        status = re.search(r"Status=(\w+)", info)
        status = status.group(1) if status else "UNKNOWN"
        if status == "READY":
            break
        if status != "WAITING" or time.time() > deadline:
            raise RuntimeError(f"BLAST search {rid} ended with status {status}")
    result = http_request(
        "GET", BLAST_URL, params={"CMD": "Get", "RID": rid, "FORMAT_TYPE": "JSON2_S"}
    ).json()
    reports = result["BlastOutput2"]
    if len(reports) != len(ids):
        raise RuntimeError(f"BLAST {rid}: {len(reports)} reports for {len(ids)} queries")
    hits: dict[str, list[dict]] = {}
    for qid, rep in zip(ids, reports, strict=True):
        search = rep["report"]["results"]["search"]
        qlen = search["query_len"]
        rows = []
        for h in search.get("hits", []):
            hsp = h["hsps"][0]  # the best-scoring segment for this subject
            rows.append(
                {
                    "sacc": h["description"][0]["accession"],
                    "pident": f"{100 * hsp['identity'] / hsp['align_len']:.2f}",
                    "length": str(hsp["align_len"]),
                    "qcovs": f"{100 * (hsp['query_to'] - hsp['query_from'] + 1) / qlen:.0f}",
                    "evalue": f"{hsp['evalue']:.2g}",
                    "bitscore": f"{hsp['bit_score']:.1f}",
                }
            )
        hits[qid] = rows
    return hits


def summarize_accessions(accessions: list[str]) -> dict[str, dict]:
    """Title, organism and taxid of nucleotide accessions (esummary)."""
    out = {}
    for i in range(0, len(accessions), 200):
        chunk = accessions[i : i + 200]
        data = entrez(
            "esummary", {"db": "nuccore", "id": ",".join(chunk), "retmode": "json"}, post=True
        ).json()["result"]
        for uid in data.get("uids", []):
            d = data[uid]
            acc = d.get("caption", "")
            out[acc] = {"title": d.get("title", ""), "taxid": str(d.get("taxid", ""))}
    return out


def classify_taxa(taxids: list[str]) -> dict[str, tuple[str, str]]:
    """Scientific name and a broad group for each taxid."""
    out = {}
    for i in range(0, len(taxids), 200):
        chunk = [t for t in taxids[i : i + 200] if t]
        if not chunk:
            continue
        root = ET.fromstring(
            entrez("efetch", {"db": "taxonomy", "id": ",".join(chunk)}, post=True).text
        )
        for taxon in root.findall("Taxon"):
            tid = taxon.findtext("TaxId")
            name = taxon.findtext("ScientificName")
            lineage = {
                (t.findtext("Rank"), t.findtext("ScientificName"))
                for t in taxon.findall("LineageEx/Taxon")
            }
            names = {n for _, n in lineage} | {name}
            ranks = dict(lineage)
            if "Siphonophorae" in names:
                group = "siphonophore"
            elif "Hydrozoa" in names:
                group = "hydrozoan, not a siphonophore"
            elif "Cnidaria" in names:
                group = "cnidarian, not a hydrozoan"
            else:
                group = (
                    ranks.get("phylum")
                    or ranks.get("kingdom")
                    or ranks.get("superkingdom", "unclassified")
                )
            out[tid] = (name, group)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tree-dirs", nargs="+", required=True, type=Path)
    ap.add_argument("--cache", required=True, type=Path)
    ap.add_argument("--db", default="core_nt")
    ap.add_argument("--task", default="megablast")
    ap.add_argument("--max-hits", type=int, default=5)
    ap.add_argument("--max-age-days", type=int, default=180)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    args.cache.mkdir(parents=True, exist_ok=True)

    # Flagged sequences, from each gene's placements and its sequence files.
    queries = []
    for d in args.tree_dirs:
        tips = {r["tip_id"]: r for r in read_tsv(d / "tip_metadata.tsv")}
        seqs = {
            r.id: str(r.seq).replace("-", "")
            for name in ("backbone.fasta", "fragments.fasta")
            if (d / name).exists()
            for r in SeqIO.parse(d / name, "fasta")
        }
        for p in read_tsv(d / "placements.tsv"):
            if p["flag"] in FLAGGED:
                seq = seqs[tips[p["tip_id"]]["seq_id"]]
                queries.append((p, seq, cache_key(seq, args.db, args.task)))

    todo = {}
    for _, seq, key in queries:
        if read_cache(args.cache / f"{key}.tsv", args.max_age_days) is None:
            todo[key] = seq
    if todo:
        hits = run_remote_blast(todo, args.db, args.task, args.max_hits + 5)
        today = dt.date.today().isoformat()
        for key, rows in hits.items():
            lines = [f"# searched {today}"] + ["\t".join(r[c] for c in HIT_COLUMNS) for r in rows]
            (args.cache / f"{key}.tsv").write_text("\n".join(lines) + "\n")
    log(f"{len(queries)} flagged sequences, {len(todo)} searched now, rest from cache")

    results = []
    for p, seq, key in queries:
        searched, hits = read_cache(args.cache / f"{key}.tsv", 10**6)
        own = p["dataset"].split(".")[0]
        hits = [h for h in hits if h["sacc"].split(".")[0] != own][: args.max_hits]
        results.append((p, seq, searched, hits))

    accessions = sorted({h["sacc"] for _, _, _, hits in results for h in hits})
    info = summarize_accessions(accessions) if accessions else {}
    info = {k.split(".")[0]: v for k, v in info.items()}
    taxa = classify_taxa(sorted({v["taxid"] for v in info.values()}))

    rows = []
    for p, seq, searched, hits in results:
        base = {
            "gene_id": p["gene_id"],
            "tip_id": p["tip_id"],
            "source": p["source"],
            "dataset": p["dataset"],
            "query_length": len(seq),
            "database": args.db,
            "searched": searched,
        }
        if not hits:
            rows.append(dict(base, status="no hits"))
        for rank, h in enumerate(hits, 1):
            meta = info.get(h["sacc"].split(".")[0], {})
            name, group = taxa.get(meta.get("taxid", ""), ("", ""))
            rows.append(
                dict(
                    base,
                    hit_rank=rank,
                    hit_accession=h["sacc"],
                    hit_organism=name,
                    hit_taxid=meta.get("taxid", ""),
                    hit_group=group,
                    hit_title=meta.get("title", ""),
                    pident=h["pident"],
                    align_length=h["length"],
                    query_coverage=h["qcovs"],
                    evalue=h["evalue"],
                    bitscore=h["bitscore"],
                    status="ok",
                )
            )
    write_tsv(args.out, rows, COLUMNS)


if __name__ == "__main__":
    main()
