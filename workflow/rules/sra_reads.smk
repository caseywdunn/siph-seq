"""
Recover marker genes from SRA reads (genomic and transcriptomic) with sharkmer.

sharkmer streams the first `sra.max_reads` reads of each run from ENA and
assembles the panel's amplicons by in silico PCR. Each run is processed once
and stored under results/sharkmer/<run>/; later releases reuse it.

1. Run in silico PCR on each selected run: run_spcr_sharkmer.
2. Record the run's completion and per-gene outcome: summarize_sharkmer_run.
3. Gather products of all runs in the release: collect_sharkmer_products.

Next: the products go through search_markers_blastn, assign_marker_regions
and extract_marker_regions (ncbi_records.smk, collection "sra") to confirm
they are the targeted gene, then to assemble_gene_sequences in trees.smk.
"""


def selected_runs(wildcards=None):
    """Run accessions selected for sharkmer in this release's inventory."""
    # Snakemake 9.24 cannot draw --rulegraph once checkpoint outputs exist, so
    # the README graph is drawn with one example accession (rulegraph_example).
    if config.get("rulegraph_example"):
        return ["SRR25099394"]
    path = checkpoints.inventory_sra_runs.get().output[0]
    with open(path) as f:
        header = f.readline().rstrip("\n").split("\t")
        acc, sel = header.index("accession"), header.index("selected")
        return [
            v[acc] for v in (line.rstrip("\n").split("\t") for line in f) if v[sel] == "true"
        ]


# sharkmer failures (e.g. an unreachable ENA file) are recorded rather than
# stopping the release; summarize_sharkmer_run marks the run as failed.
# Remove results/sharkmer/<run>/ to retry it (see README).
rule run_spcr_sharkmer:
    output:
        outdir=directory("results/sharkmer/{run}/sharkmer"),
        exit_code="results/sharkmer/{run}/exit_code.txt",
    params:
        panel=PANEL,
        max_reads=config["sra"]["max_reads"],
    threads: config["sharkmer"]["threads"]
    resources:
        mem_mb=16000,
        runtime=180,
    log:
        "results/sharkmer/{run}/sharkmer.log",
    shell:
        """
        set +e
        sharkmer --ena {wildcards.run} --no-cache -s {wildcards.run} -o {output.outdir:q} \
          --pcr-panel {params.panel} --max-reads {params.max_reads} -t {threads} > {log:q} 2>&1
        echo $? > {output.exit_code:q}
        """


rule summarize_sharkmer_run:
    input:
        outdir="results/sharkmer/{run}/sharkmer",
        exit_code="results/sharkmer/{run}/exit_code.txt",
        script="scripts/summarize_sharkmer_run.py",
    output:
        "results/sharkmer/{run}/status.tsv",
    shell:
        """
        python {input.script} --run {wildcards.run} --outdir {input.outdir:q} \
          --exit-code $(cat {input.exit_code:q}) --panel {PANEL} --gene-map {GENE_MAP} \
          --out {output:q}
        """


rule collect_sharkmer_products:
    input:
        lambda wc: expand("results/sharkmer/{run}/status.tsv", run=selected_runs()),
    output:
        fasta=f"{REL}/sra/targets.fasta",
        table=f"{REL}/sra/products.tsv",
        runs=f"{REL}/sra/run_status.tsv",
    params:
        uncertain=(
            "--include-uncertain" if config["sharkmer"]["include_uncertain_products"] else ""
        ),
    shell:
        """
        python scripts/collect_sharkmer_products.py --status {input:q} {params.uncertain} \
          --fasta {output.fasta:q} --table {output.table:q} --run-table {output.runs:q}
        """
