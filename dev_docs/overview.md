# Development overview

## Goal

A repeatable inventory of all public siphonophore sequence data, with marker
genes recovered from every data type, cross-source gene trees, and screening
for misidentified datasets. Reruns at regular intervals should only process
new data.

## Data model

Two kinds of output, kept apart so releases can reuse per-dataset work:

| Scope | Location | Keyed by | Depends on |
| --- | --- | --- | --- |
| Per accession (reused by every release) | `data/ncbi_nucleotide/<acc>.gb`, `data/genomes/<asm>/`, `results/sharkmer/<run>/`, `results/genomes/<asm>/` | Versioned accession (immutable) | Configuration and reference markers only, never on release inventories |
| Per release | `results/releases/<release>/` | Release id (date) | Inventories queried for that release |
| Shared references | `results/references/` | Configuration | sharkmer panel export plus `markers.reference_records` |
| Release report (tracked in git) | `reports/<release>/` | Release id | The release's reports, trees and record |

The report groups flagged datasets by study (`describe_studies.py`: GenBank
REFERENCE blocks, ENA study and centre, assembly BioProject) and adds remote
BLAST matches for each flagged sequence (`blast_flagged_sequences.py`, cached in
`results/blast_remote/` by sequence, database and task). Misha has no local
copy of NCBI nt, and remote searches queue at NCBI for tens of minutes, so all
flagged sequences go in one batched search.

The release report is the shareable record of a release. It contains a
self-contained `README.md` (methods, definitions, every flag with evidence),
SVG neighbourhood figures, and copies of the tables, trees and gzipped
alignments, so a URL to it is enough for data submitters or NCBI. Workflow code
and reports are committed separately. `release_record.yaml` captures the
commit at the time the report is built, so code changes are committed before a
release is built, and the report is committed after it.

The SRA and genome inventories are Snakemake checkpoints. Their contents decide
which per-accession jobs are needed. Because per-accession rules take no
release-scoped inputs, existing outputs are reused as long as their
parameters and commands are unchanged (Snakemake's default rerun triggers).
The sharkmer rule wraps only the sharkmer command. Its interpretation
(`summarize_sharkmer_run`) is a separate cheap rule, so changing the summary
script does not rerun sharkmer.

GenBank records are fetched in batches by one rule per release, which
downloads only accessions missing from the store. Parsing and BLAST of all
records repeat each release; this takes minutes.

Identifiers:
- Region ids: `<target>__<gene_id>__<rank>`. Genome regions carry an
  `<asm>__` prefix; sharkmer product ids are `<run>__<gene_id>__<product>`.
- Tree tips: `Genus_species@<source>-<dataset>[-n]` (lab convention), with the
  name taken from NCBI taxonomy for the dataset's tax_id.

## Method decisions

- **Taxon**: Siphonophorae is NCBI taxid 42759. Each query checks the taxid
  against the name, because a wrong taxid (316 is a bacterium) would
  otherwise inventory another organism without any error.
- **sharkmer panel**: sharkmer 3.2.1 has no siphonophore panel. `hydrozoa`
  v1.0.9 covers siphonophores and targets exactly 16S, CO1, 18S, 28S. The
  product genes are named `hydrozoa_<gene>` and mapped by
  `sharkmer.gene_map`. Pilot on SRR25099394 (*Agalma elegans*, 2M reads):
  2:53 wall time, 8.9 GB peak RSS, recovered 18S (1785 bp), 28S (3230 bp),
  CO1 (694 bp); 16S failed (node budget exceeded).
- **ENA as the read source**: ENA mirrors SRA and is where sharkmer `--ena`
  streams from. `--no-cache` avoids storing full read files, since only the
  first 2M reads are used.
- **Gene identification**: blastn (`dc-megablast`, for cross-species
  sensitivity) against a reference set built from (a) the sharkmer panel's
  amplicon references and (b) annotated features of reference records spanning
  Cystonectae, Physonectae and Calycophorae. HSPs are chained per gene and
  strand, and overlaps between genes are resolved by score
  (`assign_marker_regions.py`). The same procedure handles GenBank records,
  genome assemblies (subject-target mode) and sharkmer products (to reject
  off-target products).
- **NCBI record classes**: `gene_record` and `mitochondrial_genome` are
  processed. `assembly_component` (chromosomes and WGS contigs of
  assemblies) and `project_master` (TSA/WGS masters) are inventoried only.
  Assemblies are covered by the genome route, and TSA reads are on SRA.
- **Gene vocabulary**: short gene ids, as used by sharkmer and in the
  literature, with SO term IDs (checked against so.obo data-version
  2026-08-07) and HGNC IDs (checked against the HGNC REST API, 2026-11-18).
  ITS1/ITS2 share SO:0000639 (internal_transcribed_spacer_region); SO has no
  separate terms.
- **Trees and short barcodes**: barcodes (≥100 bp) are included. Sequences of
  at least `trees.backbone_min_length` are aligned with MAFFT `--auto`.
  Shorter ones are added with `--addfragments --keeplength`, so the backbone
  columns stay fixed. trimAl `-automated1 -colnumbering` runs on the backbone
  alone, and `apply_column_mask.py` applies its columns to every sequence;
  automated trimming of the full gappy alignment would otherwise remove the
  barcode regions. Sequences with fewer than `trees.min_aligned_sites` after
  trimming are reported as `not_in_tree`. MAFFT runs with `--preservecase`,
  because trimAl 1.5 rejects lowercase ambiguity codes. IQ-TREE 3
  `-m MFP -B 1000`, one search: these trees screen placements and no topology
  hypotheses are compared, so replicate searches are not used.
- **Internal sequence ids**: alignment and tree tools receive `seq00001`-style
  ids, because IQ-TREE rewrites `@` in names. `relabel_tree.py` restores the
  lab tip labels in `tree.nwk`.
- **SLURM CPUs**: the SLURM executor plugin takes CPUs from a rule's
  `threads` unless `cpus_per_task` is set. A `cpus_per_task: 1` default in
  the profile silently gave IQ-TREE and sharkmer 1 CPU, so the profile must
  not set it.
- **SLURM submission rate**: YCRC allows 200 submissions per user per hour.
  Light rules are `localrules`, and the profile caps submissions with
  `max-jobs-per-timespan: 3/1m`. SLURM job arrays (`slurm-array-jobs`) must
  not be used. With snakemake-executor-plugin-slurm 2.8.0 and
  snakemake-executor-plugin-slurm-jobstep 0.6.1, every task of an array ran
  the array's first job (release 2026-11-18). The other jobs' outputs were
  never made, and one run was executed 25 times at once. Arrays of 100 tasks
  were also rejected by sbatch ("Pathname ... too long").
- **Rule graph**: Snakemake 9.24 crashes (`is_edit_notebook_job`,
  `execution_settings` is None) when drawing `--rulegraph` or `--dag` once
  checkpoint outputs exist. `rulegraph_example=true` substitutes one example
  run and genome for drawing only.
- **CO1 fragments in mitochondrial genomes**: several cystonect and
  *Bargmannia* mitochondrial genomes contain a 70-95 bp CO1-like segment
  inside the annotated 16S (cf. the cox1 "structural rearrangement" feature
  in PZ224405.1). These are reported as annotation conflicts in
  `record_genes.tsv`. They are excluded from trees by the length filter.
- **Suspect detection**: k nearest neighbours by patristic distance (k=5,
  plus ties within 1e-4), excluding tips from the same dataset. Mismatches
  are flagged only when the nearest same-rank sequence is at least
  `suspect.min_distance_gap` farther than the nearest neighbour; smaller
  differences are `unresolved`. 18S and 28S evolve slowly in siphonophores
  and lack genus- or species-level resolution (user guidance, 2026-11-18),
  so they are evaluated at family level only; 16S and CO1 at genus and
  family. Tie handling matters most for these slow genes, where many tips
  are identical. Heuristic screening, documented as such in the README.
- **Pilot observations (28S, release `pilot`)**: GenBank EU448095.1 ("Physalia
  physalis" 28S) sits 0.008 from the *Abylopsis tetragona* sharkmer 28S among
  calycophorans, and 0.11 from the *Physalia* Hi-C sharkmer 28S; it is a
  candidate misidentification. The top-scoring 28S copy in the *Nanomia
  bijuga* assembly (GCA_032273505.1) grouped with *Clytia* (likely
  contaminant rDNA). This led to extracting up to 3 copies per gene from
  genomes.
- **Genome copies per gene (release 2026-11-18)**: with 3 copies for every
  gene, lower-ranked CO1 hits in nuclear assemblies were nuclear copies or
  spurious fragments. For example, a 214 bp *Physalia* (GCA_041430235.2)
  "CO1" was 4.5 substitutions per site from its nearest neighbour. These
  produced false flags. 16S and CO1 now keep only the best copy
  (`genomes.max_copies_by_gene`); 18S and 28S keep 3.
- **Retrying cleared sharkmer runs within a release**: Snakemake does not
  rebuild missing intermediate files when the release outputs that depend on
  them exist. It reported "Nothing to be done" after
  `clear_failed_sharkmer_runs.py`. Relaunching with
  `--forcerun collect_sharkmer_products` makes it regenerate them.

## Open choices

- **Transcriptome recovery (deferred by the user, 2026-11-18; focus is genomic
  data)**: in release 2026-11-18, sharkmer recovered at least one gene from
  215 of 218 WGS runs, but only 35 of 210 RNA-seq runs. All 125 runs of
  PRJNA540747 (50 bp single-end) recovered nothing. Paired 100 bp RNA-seq
  worked for 29 of 44. The most common reason was "no start-to-end
  connectivity". Untested: more reads (for example 10M) for short-read
  transcriptomes.

- Whether to add a siphonophore-specific sharkmer panel, for example with
  primers that work for siphonophore 16S and CO1, to improve recovery.
- Whether to include ITS and nuclear protein-coding references so that more
  GenBank genes are identified by similarity instead of by annotation alone.
- Whether to link GenBank records of the same specimen across genes (via
  voucher) so cross-gene evidence covers GenBank as well as SRA and genomes.
- Scheduling: releases are launched by hand with `scripts/run_release.sh`; a
  cron or scrontab entry could automate this.

## Verification status

See the pilot release notes below. Update this section when larger releases run.
