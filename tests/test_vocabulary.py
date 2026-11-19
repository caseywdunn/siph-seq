import pytest


@pytest.mark.parametrize(
    "label,compartment,expected",
    [
        ("COX1", "mitochondrion", "CO1"),
        ("cox1", "mitochondrion", "CO1"),
        ("cytochrome c oxidase subunit I", "mitochondrion", "CO1"),
        ("cytochrome oxidase subunit 1", "mitochondrion", "CO1"),
        ("cytochrome c oxidase subunit II", "mitochondrion", "CO2"),
        ("rrnL", "mitochondrion", "16S"),
        ("16S ribosomal RNA", "mitochondrion", "16S"),
        ("large subunit ribosomal RNA", "mitochondrion", "16S"),
        ("large subunit ribosomal RNA", "nuclear", "28S"),
        ("28S large subunit ribosomal RNA", "nuclear", "28S"),
        ("small subunit ribosomal RNA", "mitochondrion", "12S"),
        ("18S ribosomal RNA", "nuclear", "18S"),
        ("nad4L", "mitochondrion", "ND4L"),
        ("NADH dehydrogenase subunit 4L", "mitochondrion", "ND4L"),
        ("NADH dehydrogenase subunit 4", "mitochondrion", "ND4"),
        ("cob", "mitochondrion", "CYTB"),
        ("5.8S ribosomal RNA", "nuclear", "5.8S"),
        ("internal transcribed spacer 2", "nuclear", "ITS2"),
        ("tRNA-Trp", "mitochondrion", None),
    ],
)
def test_normalize_labels(vocab, label, compartment, expected):
    assert vocab.normalize(label, compartment) == expected


def test_multi_gene_label_is_not_one_gene(vocab):
    label = "contains 18S ribosomal RNA, internal transcribed spacer 1, 5.8S ribosomal RNA"
    assert vocab.normalize(label, "nuclear") is None


def test_ambiguous_label_without_compartment_is_unresolved(vocab):
    assert vocab.normalize("large subunit ribosomal RNA", None) is None


def test_title_lists_all_genes(vocab):
    title = (
        "Agalma elegans small subunit ribosomal RNA gene, internal transcribed spacer 1, "
        "5.8S ribosomal RNA gene, internal transcribed spacer 2, and large subunit "
        "ribosomal RNA gene, complete sequence"
    )
    assert vocab.find_all(title, "nuclear") == ["18S", "ITS1", "5.8S", "ITS2", "28S"]
