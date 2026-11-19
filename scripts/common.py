"""Shared helpers for the siph-seq workflow scripts.

Kept small on purpose: web-service access with retries, the gene vocabulary,
identifier sanitizing, and atomic table writing. Analysis logic lives in the
individual scripts.
"""

from __future__ import annotations

import csv
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import requests

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
TOOL_NAME = "siph-seq"


def log(msg: str) -> None:
    """Print a progress message to stderr."""
    print(msg, file=sys.stderr, flush=True)


def http_request(
    method: str, url: str, *, retries: int = 6, timeout: int = 300, **kwargs
) -> requests.Response:
    """Make an HTTP request, retrying transient failures with backoff.

    Raises:
        RuntimeError: when all retries fail.
    """
    last = None
    for attempt in range(retries):
        try:
            r = requests.request(method, url, timeout=timeout, **kwargs)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}: {r.text[:300]}"
            if r.status_code not in (429, 500, 502, 503, 504):
                break
        except requests.RequestException as e:
            last = str(e)
        time.sleep(min(60, 2**attempt))
    raise RuntimeError(f"Request failed: {method} {url}: {last}")


def entrez(endpoint: str, params: dict, post: bool = False) -> requests.Response:
    """Call an NCBI E-utility, respecting the documented request-rate limits.

    Uses NCBI_API_KEY from the environment when set (10 requests/s instead of 3).
    """
    params = dict(params, tool=TOOL_NAME)
    key = os.environ.get("NCBI_API_KEY")
    if key:
        params["api_key"] = key
    time.sleep(0.12 if key else 0.4)
    url = f"{EUTILS}/{endpoint}.fcgi"
    if post:
        return http_request("POST", url, data=params)
    return http_request("GET", url, params=params)


def check_taxon(taxid: int, name: str) -> None:
    """Fail unless NCBI taxonomy gives `name` for `taxid`."""
    r = entrez("esummary", {"db": "taxonomy", "id": taxid, "retmode": "json"})
    found = r.json()["result"][str(taxid)]["scientificname"]
    if found != name:
        raise SystemExit(f"Configured taxid {taxid} is '{found}', not '{name}'")


def write_tsv(path: str | Path, rows: list[dict], columns: list[str]) -> None:
    """Write rows to a TSV atomically, so an interrupted write leaves no file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=columns, delimiter="\t", extrasaction="ignore", lineterminator="\n"
        )
        w.writeheader()
        for row in rows:
            w.writerow({c: ("" if row.get(c) is None else row.get(c)) for c in columns})
    os.replace(tmp, path)


def read_tsv(path: str | Path) -> list[dict]:
    """Read a TSV with a header into a list of dicts."""
    with open(path, newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def atomic_write_text(path: str | Path, text: str) -> None:
    """Write text to a file atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, path)


_UNSAFE = re.compile(r"[^A-Za-z0-9._\-]+")


def sanitize(text: str) -> str:
    """Replace characters that break Newick, FASTA headers, or shells with '_'."""
    return re.sub(r"_+", "_", _UNSAFE.sub("_", text.strip())).strip("_")


def species_prefix(name: str) -> str:
    """Lab tip-label prefix (Genus_species) from an organism name."""
    return sanitize(name) or "unknown"


class Vocabulary:
    """Controlled gene vocabulary from config/gene_vocabulary.tsv.

    Each row gives a gene_id, its compartment, ontology identifiers, and a
    case-insensitive regex that recognizes the gene in free-text annotation.
    Rows are tried in file order, so more specific patterns (ND4L) precede
    more general ones (ND4).
    """

    def __init__(self, path: str | Path):
        self.rows = read_tsv(path)
        self.patterns = [
            (r["gene_id"], r["compartment"], re.compile(r["label_pattern"], re.I))
            for r in self.rows
        ]
        self.by_id = {r["gene_id"]: r for r in self.rows}

    def normalize(self, label: str, compartment: str | None) -> str | None:
        """Return the gene_id for one feature label, or None if unrecognized.

        Args:
            label: free text such as a gene or product qualifier.
            compartment: "mitochondrion", "nuclear", or None when unknown.
                Labels such as "large subunit ribosomal RNA" are ambiguous
                between nuclear 28S and mitochondrial 16S, and are resolved
                by compartment; with an unknown compartment they stay
                unresolved unless only one gene matches.

        Returns:
            The gene_id, or None when no gene or more than one gene matches.
        """
        hits = [g for g, c, p in self.patterns if p.search(label)]
        if not hits:
            return None
        if compartment:
            hits = [g for g in hits if self.by_id[g]["compartment"] == compartment]
        unique = list(dict.fromkeys(hits))
        # A label naming several genes (e.g. a misc_RNA spanning 18S-ITS1-5.8S)
        # does not identify one gene.
        return unique[0] if len(unique) == 1 else None

    def find_all(self, text: str, compartment: str | None) -> list[str]:
        """Return all gene_ids mentioned in a text such as a record title."""
        found = []
        for g, c, p in self.patterns:
            if compartment and c != compartment:
                continue
            if p.search(text) and g not in found:
                found.append(g)
        return found
