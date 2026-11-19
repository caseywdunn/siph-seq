import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "apply_column_mask.py"


def test_mask_applies_backbone_columns_and_drops_short(tmp_path):
    aln = tmp_path / "aln.fasta"
    aln.write_text(
        ">a\nACGTACGTAC\n>b\nACGTACGTAC\n>c\nACGAACGTAC\n>d\nACGTTCGTAC\n>frag\n------GTAC\n"
    )
    cols = tmp_path / "cols.txt"
    cols.write_text("#ColumnsMap\t0, 1, 2, 3, 4, 5\n")  # frag has no sites here
    out, sites = tmp_path / "trim.fasta", tmp_path / "sites.tsv"
    subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--alignment",
            str(aln),
            "--columns",
            str(cols),
            "--min-sites",
            "3",
            "--out",
            str(out),
            "--sites",
            str(sites),
        ],
        check=True,
    )
    assert out.read_text().count(">") == 4
    assert ">a\nACGTAC\n" in out.read_text()
    assert "frag\t0\tfalse" in sites.read_text()
