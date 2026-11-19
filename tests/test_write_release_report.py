from io import StringIO

from Bio import Phylo
from write_release_report import anchor, flag_text, induced_subtree, midpoint_root


def tips_and_lengths(node, depth=0.0, out=None):
    out = {} if out is None else out
    depth += node.length
    if not node.children:
        out[node.name] = round(depth, 6)
    for c in node.children:
        tips_and_lengths(c, depth, out)
    return out


def test_anchor_matches_github_heading_ids():
    assert anchor("AY935305.1") == "ay9353051"
    assert anchor("GCA_032273505.1") == "gca_0322735051"
    assert anchor("How to read a flag") == "how-to-read-a-flag"


def test_flag_text_translates_codes_and_keeps_notes():
    text = flag_text("18S:family_mismatch (another copy consistent); CO1:outside_focal_clade")
    assert text == (
        "18S: groups with another family (another copy consistent); "
        "CO1: groups outside siphonophores"
    )


def test_induced_subtree_keeps_patristic_distances_and_max_support():
    tree = Phylo.read(StringIO("((A:1,(B:1,C:1)90:1)70:1,(D:1,E:1)80:1);"), "newick")
    sub = induced_subtree(tree, {"A", "B", "D"})
    # B's parent node (B,C) is merged into the edge above B; A-B distance stays 3.
    names = tips_and_lengths(sub)
    assert set(names) == {"A", "B", "D"}
    assert names["B"] - names["A"] == 1
    ab = next(c for c in sub.children if c.children)
    assert ab.support == 70


def test_midpoint_root_balances_the_longest_path():
    tree = Phylo.read(StringIO("((A:1,B:1):1,C:6);"), "newick")
    root = midpoint_root(induced_subtree(tree, {"A", "B", "C"}))
    depths = tips_and_lengths(root)
    # Longest path A-C (or B-C) is 8, so both ends sit 4 from the new root.
    assert depths["C"] == 4
    assert depths["A"] == 4
