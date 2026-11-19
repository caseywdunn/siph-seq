#!/usr/bin/env bash
# Regenerate docs/figures/rulegraph.svg from the workflow (target all).
# Per-run and per-genome jobs normally depend on the SRA and genome inventories
# (Snakemake checkpoints). Snakemake 9.24 fails to draw a rule graph once those
# exist, so the graph is drawn with rulegraph_example=true, which stands in one
# example run and one example genome. No results are read or written.
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p docs/figures
graph_tmp=$(mktemp docs/figures/.rulegraph.XXXXXX)
trap 'rm -f "$graph_tmp"' EXIT

PYTHONHASHSEED=0 snakemake all --snakefile workflow/Snakefile \
  --configfile config/config.yaml --config release=rulegraph rulegraph_example=true \
  --rulegraph 2>/dev/null | dot -Tsvg > "$graph_tmp"

chmod 644 "$graph_tmp"
mv "$graph_tmp" docs/figures/rulegraph.svg
