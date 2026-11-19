# siph-seq agent instructions

Inventory of all public siphonophore sequence data (GenBank, SRA, genome
assemblies), marker-gene recovery, cross-source gene trees, and flagging of
suspect species identifications. Snakemake workflow; Python scripts.

## Layout

- `workflow/Snakefile`: thin entry point; stages in `workflow/rules/*.smk`
  (inventory, ncbi_records, sra_reads, genomes, trees, reports). Each rule
  file starts with a docstring listing its steps and rule names; keep it
  current when rules change.
- `scripts/`: one focused script per transformation; shared helpers in
  `scripts/common.py`.
- `config/config.yaml`: all settings; `config/gene_vocabulary.tsv`: gene
  vocabulary with ontology IDs and annotation patterns; `config/pilot.yaml`:
  bounded pilot overrides.
- `data/`, `results/`, `logs/`: generated, git-ignored.
- `reports/<release>/`: the shareable report of each release, written by
  `write_release_report` and committed after a release. It is generated: do
  not edit it by hand; change `scripts/write_release_report.py` instead.
  Keep workflow code (mechanics) and run reports in separate commits.

## Design rules

- Release-scoped outputs live under `results/releases/<release>/`.
  Per-accession work (`data/ncbi_nucleotide/`, `data/genomes/`,
  `results/sharkmer/`, `results/genomes/`) must not depend on release files,
  so new releases reuse it. Do not add release inputs to those rules.
- Gene identity comes from similarity (`assign_marker_regions.py`), shared by
  GenBank records, genomes, and sharkmer products. Annotation is secondary.
- Never run heavy jobs on login nodes; use the SLURM profile.

## Commands

```bash
module load miniconda
conda activate /gpfs/radev/project/dunn/cwd7/conda_envs/siph-seq
python -m pytest                     # unit tests
ruff format scripts tests && ruff check scripts tests
snakemake all --snakefile workflow/Snakefile --configfile config/config.yaml \
  --config release=test --dry-run    # parse/check the DAG
./scripts/update-rulegraph.sh        # after changing rules
```

## Commits

- End every commit message you write with
  `Co-Authored-By: <model name and version> <noreply address>`, naming the
  exact model you are running as.

## Documentation

- [README.md](README.md): purpose, outputs, how to run, limitations.
- [CONTRIBUTING.md](CONTRIBUTING.md): development setup, tests, formatting.
- [dev_docs/overview.md](dev_docs/overview.md): design decisions, data
  model, open choices, and verification status.
