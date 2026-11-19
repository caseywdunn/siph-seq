import csv
import io
import subprocess
import sys
from pathlib import Path

import numpy as np
from Bio import Phylo
from flag_suspect_placements import patristic_matrix


def test_patristic_matrix_matches_bio_phylo():
    nwk = "((A:1,B:2):0.5,(C:1,(D:0.5,E:0.25):1):2,F:3);"
    tree = Phylo.read(io.StringIO(nwk), "newick")
    names, D = patristic_matrix(tree)
    for i, a in enumerate(names):
        for j, b in enumerate(names):
            expected = 0.0 if a == b else tree.distance(a, b)
            assert np.isclose(D[i, j], expected), (a, b)


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "flag_suspect_placements.py"
TIP_COLS = [
    "tip_id",
    "seq_id",
    "gene_id",
    "source",
    "dataset",
    "organism",
    "genus",
    "family",
    "in_focal_clade",
    "length",
    "included",
]


def run_flags(tmp_path, nwk, families, min_gap):
    (tmp_path / "t.nwk").write_text(nwk)
    lines = ["\t".join(TIP_COLS)]
    for i, (tip, fam) in enumerate(families.items()):
        lines.append(
            "\t".join([tip, f"s{i}", "28S", "ncbi", tip, tip, "", fam, "true", "900", "true"])
        )
    (tmp_path / "tips.tsv").write_text("\n".join(lines) + "\n")
    (tmp_path / "sites.tsv").write_text("seq_id\taligned_sites\tin_tree\n")
    out = tmp_path / "out.tsv"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--tree",
            str(tmp_path / "t.nwk"),
            "--tips",
            str(tmp_path / "tips.tsv"),
            "--sites",
            str(tmp_path / "sites.tsv"),
            "--k",
            "1",
            "--ranks",
            "family",
            "--min-gap",
            str(min_gap),
            "--out",
            str(out),
        ],
        check=True,
    )
    return {r["tip_id"]: r["flag"] for r in csv.DictReader(open(out), delimiter="\t")}


FAMILIES = {"q": "F", "x": "G", "y": "G", "f2": "F"}


def test_unresolved_difference_is_not_flagged(tmp_path):
    # q sits next to family G, but its family member is only 0.005 farther.
    nwk = "((q:0.001,x:0.001):0.001,y:0.01,f2:0.004);"
    assert run_flags(tmp_path, nwk, FAMILIES, 0.01)["q"] == "unresolved"


def test_resolved_difference_is_flagged(tmp_path):
    nwk = "((q:0.001,x:0.001):0.001,y:0.01,f2:0.5);"
    assert run_flags(tmp_path, nwk, FAMILIES, 0.01)["q"] == "family_mismatch"


def test_tied_neighbours_are_all_considered(tmp_path):
    # x (family G) and f2 (family F) are equally close to q; with k=1 an
    # arbitrary tie-break must not produce a mismatch.
    nwk = "(q:0.001,x:0.001,f2:0.001,y:0.3);"
    assert run_flags(tmp_path, nwk, FAMILIES, 0.0)["q"] == "consistent"


def test_foreign_nearest_neighbour_is_flagged(tmp_path):
    # q's nearest neighbour is an outgroup reference; siphonophores are far.
    families = {"q": "F", "x": "G", "y": "G", "f2": "F", "o": "Out"}
    (tmp_path / "t.nwk").write_text("((q:0.01,o:0.01):0.2,x:0.05,y:0.05,f2:0.05);")
    lines = ["\t".join(TIP_COLS)]
    for i, (tip, fam) in enumerate(families.items()):
        focal = "false" if tip == "o" else "true"
        source = "ref" if tip == "o" else "ncbi"
        lines.append(
            "\t".join([tip, f"s{i}", "28S", source, tip, tip, "", fam, focal, "900", "true"])
        )
    (tmp_path / "tips.tsv").write_text("\n".join(lines) + "\n")
    (tmp_path / "sites.tsv").write_text("seq_id\taligned_sites\tin_tree\n")
    out = tmp_path / "out.tsv"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--tree",
            str(tmp_path / "t.nwk"),
            "--tips",
            str(tmp_path / "tips.tsv"),
            "--sites",
            str(tmp_path / "sites.tsv"),
            "--k",
            "5",
            "--ranks",
            "family",
            "--min-gap",
            "0.01",
            "--out",
            str(out),
        ],
        check=True,
    )
    flags = {r["tip_id"]: r["flag"] for r in csv.DictReader(open(out), delimiter="\t")}
    assert flags["q"] == "outside_focal_clade"
