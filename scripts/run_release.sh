#!/usr/bin/env bash
# Build a release of the inventory and analyses on the cluster via SLURM.
# Usage: scripts/run_release.sh [release-id] [extra snakemake options]
# The release id defaults to today's date (YYYY-MM-DD). Rerunning the same id
# resumes that release; a new id re-queries NCBI and ENA and processes only
# datasets that are new since earlier releases.
set -euo pipefail
cd "$(dirname "$0")/.."
release="${1:-$(date +%F)}"
shift || true
mkdir -p logs
snakemake all --snakefile workflow/Snakefile --configfile config/config.yaml \
  --config release="$release" --profile workflow/profiles/slurm "$@" \
  2>&1 | tee "logs/release_${release}.log"
