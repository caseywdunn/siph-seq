import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


import pytest  # noqa: E402

from common import Vocabulary  # noqa: E402


@pytest.fixture(scope="session")
def vocab():
    return Vocabulary(ROOT / "config" / "gene_vocabulary.tsv")
