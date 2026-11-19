"""Identify marker gene regions in target sequences from BLAST hits to reference markers.

The same procedure serves every data type:
- `--mode query-targets`: targets were the BLAST queries (GenBank records,
  sharkmer products) searched against the reference marker database.
- `--mode subject-targets`: targets were the BLAST subjects (genome contigs)
  and the reference markers were the queries.

For each target, HSPs to references of the same gene on the same strand are
chained when they lie within `--max-gap` bases of each other on the target.
A chain's score is the best single reference's summed bitscore in the chain,
so many similar references hitting the same place do not inflate it. Chains
are then accepted from highest score down, rejecting any that overlap an
already accepted chain by more than `--max-overlap` of their length; this
separates adjacent genes (18S, ITS, 28S; mitochondrial genes) and resolves
regions where references of two genes both hit. Finally at most
`--max-per-gene` chains per gene are kept for each target (or across all
targets with `--per-gene-scope all`, for genome assemblies).
`--max-per-gene-override GENE=N` sets a different limit for one gene.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass, field

from common import read_tsv, write_tsv

BLAST_FIELDS = [
    "qseqid",
    "sseqid",
    "pident",
    "length",
    "qstart",
    "qend",
    "sstart",
    "send",
    "evalue",
    "bitscore",
    "qlen",
    "slen",
]
COLUMNS = [
    "region_id",
    "target",
    "gene_id",
    "start",
    "end",
    "strand",
    "length",
    "score",
    "best_ref",
    "best_ref_pident",
    "best_ref_coverage",
    "n_hsps",
    "rank",
    "n_candidate_regions",
]


@dataclass
class Hsp:
    target: str
    ref: str
    gene: str
    start: int  # 1-based inclusive target coordinates, start <= end
    end: int
    strand: str
    bitscore: float
    pident: float
    aln_len: int
    ref_start: int
    ref_end: int
    ref_len: int


@dataclass
class Chain:
    target: str
    gene: str
    strand: str
    hsps: list[Hsp] = field(default_factory=list)

    @property
    def start(self) -> int:
        return min(h.start for h in self.hsps)

    @property
    def end(self) -> int:
        return max(h.end for h in self.hsps)

    def best_ref(self) -> tuple[str, float, float, float]:
        """Return (ref, summed bitscore, weighted pident, ref coverage) of the best reference."""
        by_ref: dict[str, list[Hsp]] = defaultdict(list)
        for h in self.hsps:
            by_ref[h.ref].append(h)
        best = max(by_ref, key=lambda r: (sum(h.bitscore for h in by_ref[r]), r))
        hs = by_ref[best]
        score = sum(h.bitscore for h in hs)
        pident = sum(h.pident * h.aln_len for h in hs) / sum(h.aln_len for h in hs)
        covered = set()
        for h in hs:
            covered.update(range(min(h.ref_start, h.ref_end), max(h.ref_start, h.ref_end) + 1))
        return best, score, pident, min(1.0, len(covered) / hs[0].ref_len)


def parse_hits(path: str, ref_gene: dict[str, str], mode: str, evalue: float, min_len: int):
    hsps = []
    with open(path) as f:
        for line in f:
            v = dict(zip(BLAST_FIELDS, line.rstrip("\n").split("\t"), strict=True))
            if float(v["evalue"]) > evalue or int(v["length"]) < min_len:
                continue
            # BLAST reports the query on the plus strand; a reversed subject
            # interval means the target and reference are on opposite strands.
            strand = "-" if int(v["sstart"]) > int(v["send"]) else "+"
            if mode == "query-targets":
                target, ref = v["qseqid"], v["sseqid"]
                t1, t2 = int(v["qstart"]), int(v["qend"])
                r1, r2, rlen = int(v["sstart"]), int(v["send"]), int(v["slen"])
            else:
                target, ref = v["sseqid"], v["qseqid"]
                t1, t2 = sorted((int(v["sstart"]), int(v["send"])))
                r1, r2, rlen = int(v["qstart"]), int(v["qend"]), int(v["qlen"])
            hsps.append(
                Hsp(
                    target,
                    ref,
                    ref_gene[ref],
                    t1,
                    t2,
                    strand,
                    float(v["bitscore"]),
                    float(v["pident"]),
                    int(v["length"]),
                    r1,
                    r2,
                    rlen,
                )
            )
    return hsps


def chain_hsps(hsps: list[Hsp], max_gap: int) -> list[Chain]:
    """Group HSPs into chains per (target, gene, strand) by target proximity."""
    groups: dict[tuple, list[Hsp]] = defaultdict(list)
    for h in hsps:
        groups[(h.target, h.gene, h.strand)].append(h)
    chains = []
    for (target, gene, strand), hs in groups.items():
        hs.sort(key=lambda h: (h.start, h.end))
        cur = Chain(target, gene, strand, [hs[0]])
        cur_end = hs[0].end
        for h in hs[1:]:
            if h.start - cur_end <= max_gap:
                cur.hsps.append(h)
                cur_end = max(cur_end, h.end)
            else:
                chains.append(cur)
                cur = Chain(target, gene, strand, [h])
                cur_end = h.end
        chains.append(cur)
    return chains


def overlap(a: Chain, b: Chain) -> int:
    return max(0, min(a.end, b.end) - max(a.start, b.start) + 1)


def resolve(chains: list[Chain], max_overlap: float) -> list[tuple[Chain, tuple]]:
    """Accept chains greedily by score, rejecting those overlapping accepted ones."""
    scored = [(c, c.best_ref()) for c in chains]
    scored.sort(key=lambda x: (-x[1][1], x[0].target, x[0].start, x[0].gene))
    accepted: dict[str, list[Chain]] = defaultdict(list)
    out = []
    for c, best in scored:
        length = c.end - c.start + 1
        if any(overlap(c, a) > max_overlap * length for a in accepted[c.target]):
            continue
        accepted[c.target].append(c)
        out.append((c, best))
    return out


def parse_overrides(values: list[str]) -> dict[str, int]:
    """Parse GENE=N strings into a gene -> limit mapping."""
    limits = {}
    for value in values:
        gene, sep, n = value.partition("=")
        if not sep or not gene or not n.isdigit() or int(n) < 1:
            raise SystemExit(f"--max-per-gene-override expects GENE=N with N >= 1, got {value!r}")
        limits[gene] = int(n)
    return limits


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--blast", required=True, help="BLAST outfmt 6 with the fields in BLAST_FIELDS")
    ap.add_argument("--references", required=True, help="reference table (ref_id, gene_id)")
    ap.add_argument("--mode", choices=["query-targets", "subject-targets"], required=True)
    ap.add_argument("--evalue", type=float, default=1e-10)
    ap.add_argument("--min-hsp-length", type=int, default=50)
    ap.add_argument("--max-gap", type=int, default=300)
    ap.add_argument("--max-overlap", type=float, default=0.5)
    ap.add_argument("--max-per-gene", type=int, default=None)
    ap.add_argument(
        "--max-per-gene-override",
        action="append",
        default=[],
        metavar="GENE=N",
        help="per-gene limit replacing --max-per-gene for that gene (repeatable)",
    )
    ap.add_argument("--per-gene-scope", choices=["target", "all"], default="target")
    ap.add_argument("--region-prefix", default="", help="prefix for region ids")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    limits = parse_overrides(args.max_per_gene_override)
    ref_gene = {r["ref_id"]: r["gene_id"] for r in read_tsv(args.references)}
    hsps = parse_hits(args.blast, ref_gene, args.mode, args.evalue, args.min_hsp_length)
    accepted = resolve(chain_hsps(hsps, args.max_gap), args.max_overlap)

    groups: dict[tuple, list] = defaultdict(list)
    for c, best in accepted:
        key = (c.gene,) if args.per_gene_scope == "all" else (c.target, c.gene)
        groups[key].append((c, best))

    rows = []
    for key in sorted(groups):
        items = groups[key]  # already in descending score order
        limit = limits.get(key[-1], args.max_per_gene)
        kept = items[:limit] if limit else items
        for rank, (c, (ref, score, pident, cov)) in enumerate(kept, 1):
            rows.append(
                {
                    "region_id": f"{args.region_prefix}{c.target}__{c.gene}__{rank}",
                    "target": c.target,
                    "gene_id": c.gene,
                    "start": c.start,
                    "end": c.end,
                    "strand": c.strand,
                    "length": c.end - c.start + 1,
                    "score": round(score, 1),
                    "best_ref": ref,
                    "best_ref_pident": round(pident, 2),
                    "best_ref_coverage": round(cov, 3),
                    "n_hsps": len(c.hsps),
                    "rank": rank,
                    "n_candidate_regions": len(items),
                }
            )
    rows.sort(key=lambda r: (r["target"], r["start"]))
    write_tsv(args.out, rows, COLUMNS)


if __name__ == "__main__":
    main()
