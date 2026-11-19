"""Write a self-contained GitHub-markdown report for one release.

The report directory (reports/<release>/) is meant to be shared by URL with
the people who deposited or curate the data. It explains how flags were
derived and gives the evidence for each one: placement statistics,
neighbourhood figures from the gene trees, and the underlying tables, trees
and alignments as files. reports/README.md, the index of all releases, is
rewritten at the same time.

Usage:
    python scripts/write_release_report.py --release 2026-11-18 \
        --release-dir results/releases/2026-11-18 --genes 18S 28S 16S CO1 \
        --out-dir reports/2026-11-18 --index reports/README.md
"""

from __future__ import annotations

import argparse
import gzip
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml
from Bio import Phylo
from flag_suspect_placements import patristic_matrix

from common import read_tsv

FLAG_ORDER = ["outside_focal_clade", "family_mismatch", "genus_mismatch"]
FLAG_TEXT = {
    "outside_focal_clade": "groups outside siphonophores",
    "family_mismatch": "groups with another family",
    "genus_mismatch": "groups with another genus",
    "unresolved": "unresolved",
    "consistent": "consistent",
    "not_evaluable": "not evaluable",
    "not_in_tree": "not in tree",
}
SOURCE_TEXT = {
    "ncbi_nucleotide": "GenBank record",
    "sra_run": "SRA run",
    "genome_assembly": "Genome assembly",
}
SOURCE_PLURAL = {
    "ncbi_nucleotide": "GenBank records",
    "sra_run": "SRA runs",
    "genome_assembly": "Genome assemblies",
}
TIP_SOURCE = {"ncbi_nucleotide": "ncbi", "sra_run": "sra", "genome_assembly": "genome"}
TIP_SOURCE_TEXT = {"ncbi": "GenBank", "sra": "SRA", "genome": "genome", "ref": "reference"}


# --- Links and text helpers ----------------------------------------------------------


def dataset_url(source: str, accession: str) -> str:
    """Public page for a dataset, by placement or dataset source name."""
    if source in ("sra", "sra_run"):
        return f"https://www.ncbi.nlm.nih.gov/sra/{accession}"
    if source in ("genome", "genome_assembly"):
        return f"https://www.ncbi.nlm.nih.gov/datasets/genome/{accession}/"
    return f"https://www.ncbi.nlm.nih.gov/nuccore/{accession}"


def project_url(project: str) -> str:
    return f"https://www.ncbi.nlm.nih.gov/bioproject/{project}"


def md(text) -> str:
    """Escape text for a markdown table cell."""
    return str(text if text is not None else "").replace("|", "\\|").replace("\n", " ")


def anchor(heading: str) -> str:
    """GitHub's anchor for a heading: lowercase, punctuation dropped, spaces to hyphens."""
    slug = re.sub(r"[^\w\- ]", "", heading.strip().lower())
    return slug.replace(" ", "-")


def file_stem(tip_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", tip_id.split("@", 1)[-1])


def fmt_dist(value: str, checked: bool = True) -> str:
    if not checked:
        return "not checked"
    return value if value not in ("", None) else "none in tree"


def flag_text(flags: str) -> str:
    """'18S:family_mismatch (another copy consistent)' -> plain-language text."""
    parts = []
    for item in filter(None, (f.strip() for f in flags.split(";"))):
        gene, _, rest = item.partition(":")
        code, _, extra = rest.partition(" ")
        parts.append(f"{gene}: {FLAG_TEXT.get(code, code)}" + (f" {extra}" if extra else ""))
    return "; ".join(parts)


@dataclass
class Tip:
    tip_id: str
    source: str
    dataset: str
    organism: str
    genus: str
    family: str
    in_focal_clade: bool

    @property
    def copy(self) -> str:
        rest = self.tip_id.split("@", 1)[-1][len(f"{self.source}-{self.dataset}") :]
        return rest.lstrip("-")

    @property
    def label(self) -> str:
        where = f"{TIP_SOURCE_TEXT.get(self.source, self.source)} {self.dataset}"
        if self.copy:
            where += f", copy {self.copy}"
        return f"{self.organism} ({where})"


def load_tips(path: Path) -> dict[str, Tip]:
    tips = {}
    for r in read_tsv(path):
        if r.get("included", "true") != "true":
            continue
        tips[r["tip_id"]] = Tip(
            r["tip_id"],
            r["source"],
            r["dataset"],
            r["organism"],
            r["genus"],
            r["family"],
            r["in_focal_clade"] == "true",
        )
    return tips


# --- Neighbourhood figures -------------------------------------------------------------


@dataclass
class Node:
    name: str | None = None
    support: float | None = None  # support of the edge above this node
    length: float = 0.0
    children: list[Node] = field(default_factory=list)


def induced_subtree(tree, keep: set[str]) -> Node:
    """Subtree spanned by the kept tips, with unbranched nodes merged into one edge.

    A merged edge keeps the highest support among the edges it replaces: the
    induced split is present whenever any of them is.
    """

    def build(clade) -> Node | None:
        if clade.is_terminal():
            if clade.name in keep:
                return Node(clade.name, None, clade.branch_length or 0.0)
            return None
        kids = [k for k in (build(c) for c in clade.clades) if k is not None]
        if not kids:
            return None
        support = clade.confidence
        length = clade.branch_length or 0.0
        if len(kids) == 1:
            only = kids[0]
            only.length += length
            if support is not None and only.children:
                only.support = max(only.support or 0.0, support)
            return only
        return Node(None, support, length, kids)

    root = build(tree.root)
    root.length = 0.0
    return root


def midpoint_root(root: Node) -> Node:
    """Re-root a small tree at the midpoint of its longest tip-to-tip path."""
    adj: dict[int, list[tuple[Node, float, float | None]]] = defaultdict(list)
    nodes = []

    def walk(n: Node):
        nodes.append(n)
        for c in n.children:
            adj[id(n)].append((c, c.length, c.support))
            adj[id(c)].append((n, c.length, c.support))
            walk(c)

    walk(root)

    def farthest(start: Node):
        dist = {id(start): 0.0}
        prev = {id(start): None}
        stack = [start]
        while stack:
            n = stack.pop()
            for m, length, _ in adj[id(n)]:
                if id(m) not in dist:
                    dist[id(m)] = dist[id(n)] + length
                    prev[id(m)] = n
                    stack.append(m)
        tips = [n for n in nodes if not n.children]
        end = max(tips, key=lambda n: dist[id(n)])
        return end, dist, prev

    a, _, _ = farthest(next(n for n in nodes if not n.children))
    b, dist, prev = farthest(a)
    half = dist[id(b)] / 2
    # Walk back from b to find the edge containing the midpoint.
    n = b
    while prev[id(n)] is not None and dist[id(prev[id(n)])] > half:
        n = prev[id(n)]
    p = prev[id(n)]
    if p is None:
        return root
    edge = next(e for e in adj[id(n)] if e[0] is p)
    new_root = Node(None, None, 0.0)
    to_p, to_n = half - dist[id(p)], dist[id(n)] - half

    def orient(node: Node, parent: Node | None, length: float, support) -> Node:
        out = Node(node.name, support, length)
        for m, ln, sup in adj[id(node)]:
            if parent is not None and m is parent:
                continue
            out.children.append(orient(m, node, ln, sup))
        return out

    adj[id(n)] = [e for e in adj[id(n)] if e[0] is not p]
    adj[id(p)] = [e for e in adj[id(p)] if e[0] is not n]
    new_root.children = [
        orient(p, None, max(to_p, 0.0), edge[2]),
        orient(n, None, max(to_n, 0.0), edge[2]),
    ]
    return new_root


def nice_scale(max_depth: float) -> float:
    target = max_depth / 5 if max_depth > 0 else 0.01
    exp = 10 ** np.floor(np.log10(target))
    for m in (1, 2, 5, 10):
        if m * exp >= target:
            return float(m * exp)
    return float(10 * exp)


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def draw_svg(root: Node, tips: dict[str, Tip], focus: Tip, title: str) -> str:
    """Rectangular phylogram with the focus tip and its expected relatives highlighted."""
    row, top, left, tree_w, label_w = 18, 46, 12, 420, 520
    order: list[Node] = []
    depth: dict[int, float] = {}

    def lay(n: Node, d: float):
        depth[id(n)] = d + n.length
        if not n.children:
            order.append(n)
        for c in n.children:
            lay(c, depth[id(n)])

    lay(root, -root.length)
    max_d = max(depth.values()) or 1.0
    xs = {k: left + v / max_d * tree_w for k, v in depth.items()}
    ys: dict[int, float] = {id(n): top + i * row for i, n in enumerate(order)}

    def set_y(n: Node) -> float:
        if n.children:
            ys[id(n)] = sum(set_y(c) for c in n.children) / len(n.children)
        return ys[id(n)]

    set_y(root)
    height = top + len(order) * row + 52
    width = left + tree_w + label_w
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" font-family="Helvetica, Arial, sans-serif">',
        f'<rect width="{width}" height="{height}" fill="#ffffff"/>',
        f'<text x="{left}" y="20" font-size="14" font-weight="bold" fill="#000">'
        f"{esc(title)}</text>",
    ]

    def edges(n: Node, parent: Node | None):
        x, y = xs[id(n)], ys[id(n)]
        if parent is not None:
            px = xs[id(parent)]
            out.append(
                f'<line x1="{px:.1f}" y1="{y:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="#444"/>'
            )
        if n.children:
            y0 = min(ys[id(c)] for c in n.children)
            y1 = max(ys[id(c)] for c in n.children)
            out.append(
                f'<line x1="{x:.1f}" y1="{y0:.1f}" x2="{x:.1f}" y2="{y1:.1f}" stroke="#444"/>'
            )
            if n.support is not None and parent is not None:
                out.append(
                    f'<text x="{x - 3:.1f}" y="{y - 3:.1f}" font-size="9" fill="#777" '
                    f'text-anchor="end">{n.support:.0f}</text>'
                )
        for c in n.children:
            edges(c, n)

    edges(root, None)
    for n in order:
        tip = tips[n.name]
        style = 'fill="#222"'
        if tip.tip_id == focus.tip_id:
            style = 'fill="#c62828" font-weight="bold"'
        elif tip.dataset == focus.dataset and tip.source == focus.source:
            style = 'fill="#c62828"'
        elif not tip.in_focal_clade:
            style = 'fill="#777" font-style="italic"'
        elif focus.genus and tip.genus == focus.genus:
            style = 'fill="#1565c0" font-weight="bold"'
        elif focus.family and tip.family == focus.family:
            style = 'fill="#1565c0"'
        family = f" [{tip.family}]" if tip.family else ""
        out.append(
            f'<text x="{xs[id(n)] + 5:.1f}" y="{ys[id(n)] + 4:.1f}" font-size="12" {style}>'
            f"{esc(tip.label + family)}</text>"
        )
    scale = nice_scale(max_d)
    sy = top + len(order) * row + 8
    sx2 = left + scale / max_d * tree_w
    out.append(f'<line x1="{left}" y1="{sy}" x2="{sx2:.1f}" y2="{sy}" stroke="#000"/>')
    out.append(
        f'<text x="{left}" y="{sy + 14}" font-size="10" fill="#000">'
        f"{scale:g} substitutions/site</text>"
    )
    legend = (
        "red: this dataset; blue: same genus (bold) or family as its label; "
        "grey italic: outside siphonophores; numbers: ultrafast bootstrap support"
    )
    out.append(f'<text x="{left}" y="{sy + 32}" font-size="10" fill="#555">{esc(legend)}</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def neighbourhood(focus_i: int, names: list[str], D, tips: dict[str, Tip], n_near: int) -> set[str]:
    """The focus tip, its nearest tips, and the nearest tips of its labelled genus and family."""
    focus = tips[names[focus_i]]
    order = np.argsort(D[focus_i], kind="stable")
    keep = {names[j] for j in order[: n_near + 1]}
    for rank, n in (("genus", 3), ("family", 3)):
        value = getattr(focus, rank)
        if not value:
            continue
        found = 0
        for j in order:
            t = tips[names[j]]
            if t.dataset != focus.dataset and getattr(t, rank) == value:
                keep.add(names[j])
                found += 1
                if found == n:
                    break
    return keep


# --- Report ------------------------------------------------------------------------------


def table(header: list[str], rows: list[list]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines += ["| " + " | ".join(md(c) for c in r) + " |" for r in rows]
    return lines + [""]


def tip_link(tip_id: str, tips_by_gene: dict, gene: str) -> str:
    t = tips_by_gene[gene].get(tip_id)
    if t is None:
        return md(tip_id)
    return (
        f"{md(t.label)} ([link]({dataset_url(t.source, t.dataset)}))"
        if t.source != "ref"
        else md(t.label)
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--release", required=True)
    ap.add_argument("--release-dir", required=True, type=Path)
    ap.add_argument("--genes", nargs="+", required=True)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--index", required=True, type=Path)
    ap.add_argument("--neighbours-shown", type=int, default=10)
    ap.add_argument("--record", type=Path, help="release record (default: in --release-dir)")
    args = ap.parse_args()

    rel, out = args.release_dir, args.out_dir
    if out.exists():
        shutil.rmtree(out)
    (out / "figures").mkdir(parents=True)
    (out / "data").mkdir()

    record_path = args.record or rel / "release_record.yaml"
    record = yaml.safe_load(record_path.read_text())
    cfg = record["config"]
    summary = read_tsv(rel / "reports/summary.tsv")
    status = read_tsv(rel / "reports/dataset_status.tsv")
    flags = read_tsv(rel / "reports/dataset_flags.tsv")
    placements = {g: read_tsv(rel / f"trees/{g}/placements.tsv") for g in args.genes}
    tips_by_gene = {g: load_tips(rel / f"trees/{g}/tip_metadata.tsv") for g in args.genes}
    sra_inv = {r["run_accession"]: r for r in read_tsv(rel / "inventory/sra_runs.tsv")}
    status_by = {(r["source"], r["accession"]): r for r in status}

    # Figures for every flagged placement.
    figures: dict[str, str] = {}
    for g in args.genes:
        flagged = [p for p in placements[g] if p["flag"] in FLAG_ORDER]
        if not flagged:
            continue
        tree = Phylo.read(rel / f"trees/{g}/tree.nwk", "newick")
        names, D = patristic_matrix(tree)
        index = {n: i for i, n in enumerate(names)}
        (out / "figures" / g).mkdir()
        for p in flagged:
            tips = tips_by_gene[g]
            keep = neighbourhood(index[p["tip_id"]], names, D, tips, args.neighbours_shown)
            sub = midpoint_root(induced_subtree(tree, keep))
            focus = tips[p["tip_id"]]
            title = f"{g}: {focus.label} ({FLAG_TEXT[p['flag']]})"
            path = out / "figures" / g / f"{file_stem(p['tip_id'])}.svg"
            path.write_text(draw_svg(sub, tips, focus, title))
            figures[p["tip_id"] + "|" + g] = str(path.relative_to(out))

    # Backup files.
    for name in ("summary.tsv", "dataset_flags.tsv", "dataset_status.tsv"):
        shutil.copy(rel / "reports" / name, out / "data" / name)
    for g in args.genes:
        shutil.copy(rel / f"trees/{g}/placements.tsv", out / "data" / f"placements_{g}.tsv")
        shutil.copy(rel / f"trees/{g}/tip_metadata.tsv", out / "data" / f"tips_{g}.tsv")
        shutil.copy(rel / f"trees/{g}/tree.nwk", out / "data" / f"tree_{g}.nwk")
        with (
            open(rel / f"trees/{g}/aligned.fasta", "rb") as src,
            gzip.GzipFile(out / "data" / f"alignment_{g}.fasta.gz", "wb", mtime=0) as dst,
        ):
            shutil.copyfileobj(src, dst)
        shutil.copy(rel / f"trees/{g}/trimal_columns.txt", out / "data" / f"trimal_columns_{g}.txt")
    shutil.copy(record_path, out / "data" / "release_record.yaml")

    L: list[str] = []
    w = L.append
    commit = str(record.get("git_commit", "unknown")).split()[0]

    # --- Header and summary
    counts = defaultdict(dict)
    for r in summary:
        counts[r["source"]][r["measure"]] = int(r["count"])
    n_flagged = sum(c.get("flagged", 0) for c in counts.values())
    w(f"# Siphonophore public sequence data: identity screen, release {args.release}")
    w("")
    w(
        f"This report screens all public sequence data for siphonophores (Siphonophorae, "
        f"NCBI Taxonomy ID {cfg['taxon']['taxid']}) for datasets whose species label "
        "disagrees with where their marker genes fall in gene trees. It covers GenBank "
        "nucleotide records, raw reads in the Sequence Read Archive (SRA), and genome "
        f"assemblies, as listed by NCBI and ENA on {args.release}."
    )
    w("")
    w(
        f"**{n_flagged} datasets are flagged.** A flag means that a sequence from the "
        "dataset is surrounded in a gene tree by sequences of a different genus, family, "
        "or by non-siphonophores, while sequences of its own genus or family are present "
        "elsewhere in the tree. Possible causes are a misidentified specimen, "
        "contamination, a sample or file mix-up, or a problem with the reference "
        "sequences it was compared with. A flag is a reason to look at a dataset, not a "
        "conclusion: see [How to read a flag](#how-to-read-a-flag). Each flagged dataset "
        "has its own section below with the evidence."
    )
    w("")
    w("## Contents")
    w("")
    for h in (
        "Summary",
        "Flagged datasets",
        "How to read a flag",
        "Methods",
        "Unresolved placements",
        "Coverage",
        "Files",
        "Provenance",
    ):
        w(f"- [{h}](#{anchor(h)})")
    w("")
    w("## Summary")
    w("")
    rows = []
    for src in ("ncbi_nucleotide", "sra_run", "genome_assembly"):
        c = counts.get(src, {})
        rows.append(
            [
                SOURCE_PLURAL[src],
                c.get("datasets", 0),
                c.get("selected", 0),
                c.get("with_marker_genes", 0),
                c.get("in_any_tree", 0),
                c.get("flagged", 0),
                c.get("failed", 0),
            ]
        )
    L += table(
        [
            "Source",
            "Datasets listed",
            "Processed",
            "With marker genes",
            "In a gene tree",
            "Flagged",
            "Failed",
        ],
        rows,
    )
    rows = []
    for g in args.genes:
        oc = Counter(p["flag"] for p in placements[g])
        rows.append(
            [
                g,
                sum(v for k, v in oc.items() if k != "not_in_tree"),
                oc["consistent"],
                oc["genus_mismatch"],
                oc["family_mismatch"],
                oc["outside_focal_clade"],
                oc["unresolved"],
                oc["not_evaluable"],
                ", ".join(cfg["suspect"]["ranks"][g]),
            ]
        )
    w("Sequences per gene tree and how their placements were judged:")
    w("")
    L += table(
        [
            "Gene",
            "Sequences in tree",
            "Consistent",
            "Other genus",
            "Other family",
            "Outside siphonophores",
            "Unresolved",
            "Not evaluable",
            "Ranks checked",
        ],
        rows,
    )

    # --- Flagged datasets
    w("## Flagged datasets")
    w("")
    w(
        "Datasets are ordered by source and then by the strongest flag. Datasets flagged "
        "in more than one gene, or by both a genome and independent data, carry more "
        "weight than a single flag."
    )
    w("")
    flag_rank = {f: i for i, f in enumerate(FLAG_ORDER)}
    src_rank = {"genome_assembly": 0, "sra_run": 1, "ncbi_nucleotide": 2}
    flags.sort(
        key=lambda r: (
            src_rank.get(r["source"], 9),
            flag_rank.get(r["max_flag"], 9),
            -int(r["genes_flagged"] or 0),
            r["accession"],
        )
    )
    rows = []
    for r in flags:
        acc = r["accession"]
        rows.append(
            [
                f"[{acc}](#{anchor(acc)})",
                SOURCE_TEXT.get(r["source"], r["source"]),
                f"*{r['organism']}*",
                r["family"],
                f"{r['genes_flagged']} of {r['genes_evaluated']}",
                flag_text(r["flags"]),
            ]
        )
    L += table(["Dataset", "Source", "Labelled as", "Family", "Genes flagged", "Flags"], rows)
    for r in flags:
        acc, src = r["accession"], r["source"]
        st = status_by.get((src, acc), {})
        w(f"### {acc}")
        w("")
        w(f"*{r['organism']}* ({r['family'] or 'family unknown'}), {SOURCE_TEXT.get(src, src)}.")
        w("")
        w(f"- Record: [{acc}]({dataset_url(src, acc)})")
        if src == "sra_run" and acc in sra_inv:
            inv = sra_inv[acc]
            w(f"- ENA: [{acc}](https://www.ebi.ac.uk/ena/browser/view/{acc})")
            w(
                f"- Library: {inv.get('library_strategy', '')}, "
                f"{inv.get('library_source', '').lower()}, "
                f"selection {inv.get('library_selection', '')}, "
                f"{inv.get('library_layout', '').lower()}, {inv.get('instrument_model', '')}"
            )
            if inv.get("study_title"):
                w(f"- Study: {inv['study_title']}")
        if r.get("project"):
            w(f"- BioProject: [{r['project']}]({project_url(r['project'])})")
        if r.get("voucher"):
            w(f"- Voucher: {r['voucher']}")
        if r.get("title") and src != "sra_run":
            w(f"- Title: {r['title']}")
        if st.get("genes_in_trees"):
            w(f"- Genes in trees: {st['genes_in_trees'].replace(';', ', ')}")
        w("")
        rows = []
        tip_src = TIP_SOURCE.get(src, src)
        own = sorted(
            (
                (g, p)
                for g in args.genes
                for p in placements[g]
                if p["dataset"] == acc and p["source"] == tip_src
            ),
            key=lambda gp: (
                args.genes.index(gp[0]),
                copy_number(gp[1]["tip_id"], tips_by_gene[gp[0]]),
            ),
        )
        with_copies = src == "genome_assembly"
        for g, p in own:
            nn = p["nearest_neighbor"]
            ranks = cfg["suspect"]["ranks"][g]
            row = [g]
            if with_copies:
                row.append(copy_number(p["tip_id"], tips_by_gene[g]))
            row += [
                f"**{FLAG_TEXT.get(p['flag'], p['flag'])}**"
                if p["flag"] in FLAG_ORDER
                else FLAG_TEXT.get(p["flag"], p["flag"]),
                p["length"],
                p["aligned_sites"],
                tip_link(nn, tips_by_gene, g) if nn else "",
                p["nearest_distance"],
                fmt_dist(p["nearest_same_genus_distance"], "genus" in ranks),
                fmt_dist(p["nearest_same_family_distance"], "family" in ranks),
                p["neighbor_families"],
            ]
            rows.append(row)
        w(
            "All placements of this dataset's sequences (distances are along the tree, "
            "in substitutions per site):"
        )
        w("")
        L += table(
            ["Gene"]
            + (["Copy"] if with_copies else [])
            + [
                "Placement",
                "Length (bp)",
                "Aligned sites",
                "Nearest sequence",
                "Distance",
                "Nearest same genus",
                "Nearest same family",
                "Families among nearest",
            ],
            rows,
        )
        if any("another copy consistent" in f for f in r["flags"].split(";")):
            w(
                "Another copy of the same gene from this dataset placed as expected. A "
                "foreign copy alongside a consistent one points to contamination in the "
                "sequenced material, not to a misidentified specimen."
            )
            w("")
        for g, p in own:
            key = p["tip_id"] + "|" + g
            if key in figures:
                w(f"![{g} tree neighbourhood of {p['tip_id']}]({figures[key]})")
                w("")
        w("[Back to flagged datasets](#flagged-datasets)")
        w("")

    # --- How to read
    w("## How to read a flag")
    w("")
    w(
        "Each sequence is compared with its nearest sequences in the gene tree, measured "
        "as distance along the branches. Sequences from the same dataset (for example "
        "two copies from one genome) are ignored as neighbours. The outcomes are:"
    )
    w("")
    defs = [
        [
            "Groups outside siphonophores",
            "Most nearest sequences are not siphonophores, or the nearest one is not and "
            "every siphonophore sequence is clearly farther. Typical of contamination "
            "(prey, symbionts, other samples) or a non-siphonophore labelled as one.",
        ],
        [
            "Groups with another family",
            "Sequences of the labelled family are in the tree, none is among the nearest, "
            "and the nearest of them is clearly farther than the nearest sequence.",
        ],
        [
            "Groups with another genus",
            "As above for the labelled genus. Checked only for 16S and CO1.",
        ],
        [
            "Unresolved",
            "The labelled genus or family is not among the nearest, but is about as close "
            "(within the distance margin below). The gene cannot tell them apart here.",
        ],
        ["Consistent", "The labelled genus and family are among the nearest sequences."],
        [
            "Not evaluable",
            "The label has no genus or family, or it is the only dataset of its genus or "
            "family in the tree.",
        ],
        [
            "Not in tree",
            "The sequence was too short, or kept too few aligned sites after trimming.",
        ],
    ]
    L += table(["Outcome", "Meaning"], defs)
    w("Points to keep in mind:")
    w("")
    w(
        "- **18S and 28S evolve slowly in siphonophores** and often do not differ between "
        "genera, so they are checked at family level only. 16S and CO1 are checked at "
        "genus and family level."
    )
    w(
        "- **A single flag can have causes other than misidentification**: a genus or "
        "family that is not monophyletic, sparse sampling of a group, a short or partial "
        "sequence (see *Aligned sites*), or an error in the comparison sequence instead. "
        "When two sequences are each other's nearest neighbours and disagree, the tree "
        "alone cannot say which is wrong."
    )
    w(
        "- **Agreement across genes and data types is the strongest evidence.** A dataset "
        "flagged in several genes, or whose flagged sequence matches an independent "
        "dataset of another species, is more likely to be misidentified or contaminated."
    )
    w(
        "- **Genome assemblies can contain DNA of other organisms.** Up to "
        f"{cfg['genomes']['max_copies_per_gene']} copies of a gene are taken from each "
        "assembly. When one copy is foreign and another is consistent, the assembly "
        "probably includes contaminating sequence, but its species label is likely "
        "correct."
    )
    w(
        "- **Environmental sequences** carry the taxonomy their submitters assigned, which "
        "may itself be an inference."
    )
    w(
        "- **Species names** are those of the NCBI Taxonomy entry the data are attached "
        "to, and genus and family come from the NCBI lineage."
    )
    w("")

    # --- Methods
    m, t, s, sh = cfg["markers"], cfg["trees"], cfg["suspect"], cfg["sharkmer"]
    w("## Methods")
    w("")
    w(
        f"- **Inventory.** NCBI Nucleotide, ENA (raw reads) and NCBI Datasets (genome "
        f"assemblies) were queried for everything below NCBI Taxonomy ID "
        f"{cfg['taxon']['taxid']} ({cfg['taxon']['name']}) on {args.release}. Nucleotide "
        "records that are pieces of genome assemblies, or shotgun project master records, "
        "are listed but not analysed separately, because their assemblies and reads are "
        "analysed directly."
    )
    w(
        "- **Gene identification.** Each GenBank record, genome assembly and read-derived "
        f"sequence was compared with reference marker sequences using BLAST (`blastn "
        f"-task {m['blast_task']}`, E-value ≤ {m['evalue']}). The references are the "
        f"sharkmer `{sh['panel']}` panel sequences and the annotated genes of "
        f"{len(m['reference_records'])} reference records "
        f"({', '.join(m['reference_records'])}). Gene names follow one vocabulary "
        "(for example 18S, not SSU), with Sequence Ontology and HGNC identifiers."
    )
    w(
        f"- **SRA reads.** For each run, marker genes were assembled from the first "
        f"{sra_max_reads(cfg):,} reads with sharkmer and its `{sh['panel']}` primer "
        "panel, which targets 18S, 28S, 16S and CO1. Reads were streamed from ENA."
    )
    w(
        f"- **Genome assemblies.** Reference markers were searched against each assembly. "
        f"Up to {cfg['genomes']['max_copies_per_gene']} best-matching copies of each gene "
        "were extracted"
        + (
            " ("
            + ", ".join(
                f"{n} for {gname}"
                for gname, n in cfg["genomes"].get("max_copies_by_gene", {}).items()
            )
            + ")"
            if cfg["genomes"].get("max_copies_by_gene")
            else ""
        )
        + "."
    )
    w(
        "- **Gene trees.** For each gene, sequences of at least "
        f"{fmt_by_gene(t['backbone_min_length'], args.genes)} bp were aligned with MAFFT, "
        "and shorter sequences (down to "
        f"{fmt_by_gene(t['min_length'], args.genes)} bp, including short barcodes) were "
        "added to that alignment without changing it (`--addfragments --keeplength`). "
        "Poorly aligned columns were removed with trimAl (`-automated1`) based on the "
        f"full-length sequences. Sequences with fewer than {t['min_aligned_sites']} "
        "remaining sites were left out. Trees were inferred with IQ-TREE "
        f"(model selection `-m {t['iqtree_model']}`, {t['iqtree_bootstrap']} ultrafast "
        "bootstrap replicates). A few non-siphonophore hydrozoan reference sequences are "
        "included so that foreign sequences have somewhere to go."
    )
    w(
        f"- **Placement test.** For each sequence, the {s['k_neighbors']} nearest "
        "sequences from other datasets were found by distance along the tree, plus any "
        "tied with the last of them. Flags require the nearest sequence of the labelled "
        "group to be farther than the nearest neighbour by at least "
        f"{fmt_by_gene(s['min_distance_gap'], args.genes)} substitutions per site; smaller "
        "differences are reported as unresolved."
    )
    w(
        "- **Figures** show the flagged sequence with its nearest sequences and the "
        "nearest sequences of its labelled genus and family, cut from the full tree with "
        "branch lengths kept, and rooted at the midpoint for display. Support values are "
        "those of the corresponding branches in the full tree."
    )
    w("")
    w(
        "The complete workflow is in this repository; [Provenance](#provenance) gives "
        "the exact version and settings."
    )
    w("")

    # --- Unresolved
    w("## Unresolved placements")
    w("")
    w(
        "These sequences are not near their labelled genus or family, but the difference "
        "is too small for the gene to resolve. They are listed for completeness."
    )
    w("")
    rows = []
    for g in args.genes:
        for p in placements[g]:
            if p["flag"] != "unresolved":
                continue
            rows.append(
                [
                    g,
                    f"[{p['dataset']}]({dataset_url(p['source'], p['dataset'])})",
                    f"*{p['organism']}*",
                    p["family"],
                    tip_link(p["nearest_neighbor"], tips_by_gene, g),
                    p["nearest_distance"],
                    fmt_dist(
                        p["nearest_same_genus_distance"], "genus" in cfg["suspect"]["ranks"][g]
                    ),
                    fmt_dist(
                        p["nearest_same_family_distance"], "family" in cfg["suspect"]["ranks"][g]
                    ),
                    p["note"],
                ]
            )
    L += table(
        [
            "Gene",
            "Dataset",
            "Labelled as",
            "Family",
            "Nearest sequence",
            "Distance",
            "Nearest same genus",
            "Nearest same family",
            "Note",
        ],
        rows,
    )

    # --- Coverage
    w("## Coverage")
    w("")
    w(
        "Datasets that were listed but not analysed, by reason (for example sequencing "
        "platforms other than Illumina and MGI, or data types other than those analysed):"
    )
    w("")
    reasons = Counter(
        (SOURCE_TEXT.get(r["source"], r["source"]), r["selection_reason"] or "")
        for r in status
        if r["selected"] != "true"
    )
    L += table(
        ["Source", "Reason", "Datasets"],
        [[a, b, n] for (a, b), n in sorted(reasons.items())],
    )
    w("Marker genes recovered from SRA runs, by library type:")
    w("")
    by_type: dict[str, Counter] = defaultdict(Counter)
    for r in status:
        if r["source"] != "sra_run" or r["selected"] != "true":
            continue
        inv = sra_inv.get(r["accession"], {})
        key = inv.get("library_strategy", "") or "unknown"
        by_type[key]["runs"] += 1
        if r["status"].startswith("failed"):
            by_type[key]["failed"] += 1
        elif r["genes_recovered"]:
            by_type[key]["genes"] += 1
    L += table(
        ["Library type", "Runs analysed", "With at least one marker gene", "Failed"],
        [[k, c["runs"], c["genes"], c["failed"]] for k, c in sorted(by_type.items())],
    )
    w(
        "Transcriptome (RNA-seq) runs, especially those with short single-end reads, "
        "rarely yield marker genes with this method, so most of them are not in the trees."
    )
    w("")
    failed = [r for r in status if r["status"].startswith("failed")]
    if failed:
        w(
            "Datasets whose analysis failed. These are retried in the next release. "
            "sharkmer failures have so far been interrupted or refused downloads from ENA."
        )
        w("")
        L += table(
            ["Dataset", "Source", "Labelled as", "Reason"],
            [
                [
                    f"[{r['accession']}]({dataset_url(r['source'], r['accession'])})",
                    SOURCE_TEXT.get(r["source"], r["source"]),
                    f"*{r['organism']}*",
                    r["status"].removeprefix("failed: "),
                ]
                for r in failed
            ],
        )

    # --- Files
    w("## Files")
    w("")
    w("Everything behind this report is in [`data/`](data/):")
    w("")
    files = [
        ["[`summary.tsv`](data/summary.tsv)", "Counts in the summary table."],
        [
            "[`dataset_flags.tsv`](data/dataset_flags.tsv)",
            "One row per flagged dataset, with its flags across genes.",
        ],
        [
            "[`dataset_status.tsv`](data/dataset_status.tsv)",
            "Every dataset listed: metadata, whether it was analysed, genes recovered, "
            "genes in trees, flags.",
        ],
        [
            "`placements_<gene>.tsv`",
            "Every sequence in a gene tree: outcome, nearest sequences, distances.",
        ],
        [
            "`tips_<gene>.tsv`",
            "Every sequence considered for a gene tree: source, taxonomy, length, and "
            "why it was left out, if it was.",
        ],
        ["`tree_<gene>.nwk`", "Gene tree (Newick, ultrafast bootstrap support)."],
        [
            "`alignment_<gene>.fasta.gz`",
            "Alignment before trimming. Sequence names are the internal ids in "
            "`tips_<gene>.tsv` (column `seq_id`).",
        ],
        [
            "`trimal_columns_<gene>.txt`",
            "Alignment columns kept by trimAl (numbered from 0).",
        ],
        [
            "[`release_record.yaml`](data/release_record.yaml)",
            "Workflow version, tool versions and all settings.",
        ],
    ]
    L += table(["File", "Contents"], files)

    # --- Provenance
    w("## Provenance")
    w("")
    w(f"- Release: {args.release}; analysis completed {record.get('completed', '')}")
    w(
        f"- Workflow commit: `{commit}`"
        + (" (with uncommitted changes)" if str(record.get("git_dirty")) == "true" else "")
    )
    w("- Tools:")
    for name, version in record.get("tools", {}).items():
        w(f"  - {name}: {str(version).strip() or 'version not recorded'}")
    w(f"- sharkmer panel: {sh['panel']} ({str(record.get('sharkmer_panel', '')).strip()})")
    w("- All settings: [`data/release_record.yaml`](data/release_record.yaml)")
    w("")
    w("[All releases](../README.md)")
    (out / "README.md").write_text("\n".join(L).rstrip() + "\n")
    write_index(args.index)


def copy_number(tip_id: str, tips: dict[str, Tip]) -> str:
    t = tips.get(tip_id)
    return (t.copy or "1") if t else ""


def sra_max_reads(cfg: dict) -> int:
    return int(cfg["sra"]["max_reads"])


def fmt_by_gene(values: dict, genes: list[str]) -> str:
    """'1500 (18S), 450 (16S)' style text, collapsed when all genes share a value."""
    vals = {g: values[g] for g in genes if g in values}
    if len(set(vals.values())) == 1:
        return str(next(iter(vals.values())))
    return ", ".join(f"{v} ({g})" for g, v in vals.items())


def write_index(index: Path) -> None:
    """List every release report under the index's directory, newest first."""
    rows = []
    for summary in sorted(index.parent.glob("*/data/summary.tsv"), reverse=True):
        release = summary.parent.parent.name
        c = defaultdict(int)
        for r in read_tsv(summary):
            c[r["measure"]] += int(r["count"])
        rows.append(
            [f"[{release}]({release}/README.md)", c["datasets"], c["in_any_tree"], c["flagged"]]
        )
    lines = [
        "# Release reports",
        "",
        "Each release screens all public siphonophore sequence data available on its date "
        "for datasets whose species label disagrees with their placement in marker gene "
        "trees. Each report is self-contained: it explains the method and gives the "
        "evidence for every flagged dataset.",
        "",
    ]
    lines += table(["Release", "Datasets listed", "In a gene tree", "Flagged"], rows)
    index.write_text("\n".join(lines).rstrip() + "\n")


if __name__ == "__main__":
    main()
