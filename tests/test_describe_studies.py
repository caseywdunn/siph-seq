import datetime as dt

from blast_flagged_sequences import cache_key, read_cache
from describe_studies import first_author


def test_first_author_handles_lists_and_single_names():
    assert first_author("Bergmeier,F.S., Ostermair,L. and Jorger,K.M.") == "Bergmeier et al."
    assert first_author("He,J.R. and Cao,W.Q.") == "He et al."
    assert first_author("Dunn,C.W.") == "Dunn"


def test_cache_key_ignores_case_but_not_database():
    assert cache_key("acgt", "core_nt", "megablast") == cache_key("ACGT", "core_nt", "megablast")
    assert cache_key("ACGT", "core_nt", "megablast") != cache_key("ACGT", "nt", "megablast")


def test_read_cache_expires_old_searches(tmp_path):
    path = tmp_path / "k.tsv"
    old = (dt.date.today() - dt.timedelta(days=200)).isoformat()
    path.write_text(f"# searched {old}\nAB1\t99.0\t500\t100\t0.0\t900\n")
    assert read_cache(path, max_age_days=180) is None
    searched, hits = read_cache(path, max_age_days=365)
    assert searched == old
    assert hits[0]["sacc"] == "AB1"
