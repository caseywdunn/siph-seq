import pytest
from assign_marker_regions import Hsp, chain_hsps, main, parse_overrides, resolve

from common import read_tsv


def hsp(target, gene, start, end, score, ref=None, strand="+", ref_len=1000):
    return Hsp(
        target,
        ref or f"{gene}_ref",
        gene,
        start,
        end,
        strand,
        score,
        95.0,
        end - start + 1,
        1,
        end - start + 1,
        ref_len,
    )


def test_nearby_hsps_of_one_gene_form_one_chain():
    chains = chain_hsps([hsp("t", "28S", 1, 500, 800), hsp("t", "28S", 650, 1500, 1200)], 300)
    assert len(chains) == 1
    assert (chains[0].start, chains[0].end) == (1, 1500)


def test_distant_hsps_form_separate_chains():
    chains = chain_hsps([hsp("t", "18S", 1, 500, 800), hsp("t", "18S", 5000, 5500, 800)], 300)
    assert len(chains) == 2


def test_redundant_references_do_not_inflate_score():
    # Two references hitting the same place: score is the best single reference's.
    chains = chain_hsps(
        [hsp("t", "16S", 1, 500, 900, ref="a"), hsp("t", "16S", 1, 500, 850, ref="b")], 300
    )
    ref, score, _, _ = chains[0].best_ref()
    assert (ref, score) == ("a", 900)


def test_adjacent_genes_are_both_kept():
    # 18S and 28S in one rDNA record do not overlap: both are accepted.
    chains = chain_hsps([hsp("t", "18S", 1, 1800, 3000), hsp("t", "28S", 2600, 5900, 5000)], 300)
    assert sorted(c.gene for c, _ in resolve(chains, 0.5)) == ["18S", "28S"]


def test_overlapping_weaker_gene_is_rejected():
    chains = chain_hsps([hsp("t", "16S", 1, 600, 1000), hsp("t", "12S", 50, 400, 200)], 300)
    assert [c.gene for c, _ in resolve(chains, 0.5)] == ["16S"]


def test_strands_are_chained_separately():
    chains = chain_hsps(
        [hsp("t", "CO1", 1, 600, 1000, strand="+"), hsp("t", "CO1", 700, 1200, 900, strand="-")],
        300,
    )
    assert len(chains) == 2


def test_parse_overrides_reads_gene_limits():
    assert parse_overrides(["16S=1", "CO1=1"]) == {"16S": 1, "CO1": 1}


@pytest.mark.parametrize("bad", ["16S", "16S=0", "=1", "16S=x"])
def test_parse_overrides_rejects_malformed(bad):
    with pytest.raises(SystemExit):
        parse_overrides([bad])


def test_per_gene_override_keeps_best_copy_only(tmp_path, monkeypatch):
    # Three 18S and three CO1 hits on different contigs (subject-targets mode).
    refs = tmp_path / "markers.tsv"
    refs.write_text("ref_id\tgene_id\n18S_ref\t18S\nCO1_ref\tCO1\n")
    lines = []
    for gene in ("18S", "CO1"):
        for i, score in enumerate((900, 800, 700), 1):
            lines.append(
                f"{gene}_ref\tcontig{gene}{i}\t95\t500\t1\t500\t1\t500\t1e-50\t{score}\t1000\t5000"
            )
    hits = tmp_path / "hits.tsv"
    hits.write_text("\n".join(lines) + "\n")
    out = tmp_path / "regions.tsv"
    monkeypatch.setattr(
        "sys.argv",
        [
            "x",
            "--blast",
            str(hits),
            "--references",
            str(refs),
            "--mode",
            "subject-targets",
            "--max-per-gene",
            "3",
            "--per-gene-scope",
            "all",
            "--max-per-gene-override",
            "CO1=1",
            "--out",
            str(out),
        ],
    )
    main()
    rows = read_tsv(out)
    kept = sorted((r["gene_id"], r["target"]) for r in rows)
    assert kept == [
        ("18S", "contig18S1"),
        ("18S", "contig18S2"),
        ("18S", "contig18S3"),
        ("CO1", "contigCO11"),
    ]
