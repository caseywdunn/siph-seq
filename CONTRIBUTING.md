# Contributing

## Setup

```bash
module load miniconda
conda env create -f environment.yml -p /gpfs/radev/project/dunn/cwd7/conda_envs/siph-seq
conda activate /gpfs/radev/project/dunn/cwd7/conda_envs/siph-seq
git config core.hooksPath .githooks   # once per clone: AI-attribution commit-msg hook
```

## Checks before committing

```bash
ruff format scripts tests
ruff check scripts tests
python -m pytest
snakemake all --snakefile workflow/Snakefile --configfile config/config.yaml \
  --config release=test --dry-run
```

After changing rules, targets, or configuration that affects the graph,
regenerate the README figure with `./scripts/update-rulegraph.sh` and commit
`docs/figures/rulegraph.svg`.

## Conventions

- Rule names follow `<action>_<object>_<tool>` for external tools
  (`search_markers_blastn`, `infer_gene_tree_iqtree`) and `<action>_<object>`
  otherwise. Keep tool commands and their options visible in `shell:` blocks.
- Each rule file begins with a docstring listing its scientific steps with
  rule names, in data-flow order.
- Scripts write outputs atomically (temporary file, then rename), so an
  interrupted job never leaves a file that looks complete.
- Tests cover logic that can change a result: label normalization, HSP
  chaining and overlap resolution, and patristic distances. Keep fixtures
  small and offline.
