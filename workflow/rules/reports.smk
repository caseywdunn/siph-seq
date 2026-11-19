"""
Flag suspect species identifications and summarize the release.

1. Evaluate whether each sequence sits near others of its genus and family:
   flag_suspect_placements.
2. Summarize each dataset's outcome and flags across genes: report_release.
3. Record what produced the release: record_release_provenance.
4. Write the shareable report, with figures and supporting files, to the
   tracked reports/<release>/ directory: write_release_report. Everything else
   a release produces stays in the untracked results/releases/<release>/.
"""


rule flag_suspect_placements:
    input:
        tree=f"{REL}/trees/{{gene}}/tree.nwk",
        tips=f"{REL}/trees/{{gene}}/tip_metadata.tsv",
        sites=f"{REL}/trees/{{gene}}/aligned_sites.tsv",
        script="scripts/flag_suspect_placements.py",
    output:
        f"{REL}/trees/{{gene}}/placements.tsv",
    params:
        ranks=lambda wc: config["suspect"]["ranks"][wc.gene],
        min_gap=lambda wc: config["suspect"]["min_distance_gap"][wc.gene],
    resources:
        mem_mb=8000,
    shell:
        """
        python {input.script} --tree {input.tree:q} --tips {input.tips:q} --sites {input.sites:q} \
          --k {config[suspect][k_neighbors]} --ranks {params.ranks} \
          --min-gap {params.min_gap} --out {output:q}
        """


rule report_release:
    input:
        manifest=f"{REL}/manifest.tsv",
        ncbi_records=f"{REL}/ncbi/record_genes.tsv",
        sra_status=f"{REL}/sra/run_status.tsv",
        genome_regions=lambda wc: expand(
            "results/genomes/{asm}/marker_regions.tsv", asm=selected_genomes()
        ),
        placements=expand(f"{REL}/trees/{{gene}}/placements.tsv", gene=TREE_GENES),
        script="scripts/report_release.py",
    output:
        status=f"{REL}/reports/dataset_status.tsv",
        flags=f"{REL}/reports/dataset_flags.tsv",
        placements=f"{REL}/reports/suspect_placements.tsv",
        summary=f"{REL}/reports/summary.tsv",
    shell:
        """
        python {input.script} --manifest {input.manifest:q} \
          --ncbi-records {input.ncbi_records:q} --sra-status {input.sra_status:q} \
          --genome-regions {input.genome_regions:q} \
          --placements {input.placements:q} \
          --dataset-status {output.status:q} --dataset-flags {output.flags:q} \
          --suspect-placements {output.placements:q} --summary {output.summary:q}
        """


rule record_release_provenance:
    input:
        rules.report_release.output,
        f"{REFS}/markers.tsv",
    output:
        f"{REL}/release_record.yaml",
    params:
        config_json=json.dumps(config),
    shell:
        """
        {{
          echo "release: {RELEASE}"
          echo "completed: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
          echo "git_commit: $(git rev-parse --verify --quiet HEAD || echo none)"
          echo "git_dirty: $(test -z "$(git status --porcelain 2>/dev/null)" && echo false || echo true)"
          echo "tools:"
          echo "  snakemake: '$(snakemake --version)'"
          echo "  sharkmer: '$(sharkmer --version)'"
          echo "  blastn: '$(blastn -version | head -1)'"
          echo "  mafft: '$(mafft --version 2>&1)'"
          echo "  trimal: '$(trimal --version 2>&1 | grep -m1 trimAl | xargs)'"
          echo "  iqtree: '$(iqtree3 --version | head -1)'"
          echo "  datasets: '$(datasets --version)'"
          echo "sharkmer_panel: '$(grep -m1 '^panel_version' {REFS}/{PANEL}_panel.yaml)'"
          echo "config:"
          python -c "import yaml,sys; print(yaml.safe_dump(yaml.safe_load(sys.argv[1]), sort_keys=False))" {params.config_json:q} | sed 's/^/  /'
        }} > {output:q}
        """


rule write_release_report:
    input:
        record=f"{REL}/release_record.yaml",
        summary=f"{REL}/reports/summary.tsv",
        status=f"{REL}/reports/dataset_status.tsv",
        flags=f"{REL}/reports/dataset_flags.tsv",
        sra_runs=f"{REL}/inventory/sra_runs.tsv",
        trees=expand(f"{REL}/trees/{{gene}}/tree.nwk", gene=TREE_GENES),
        tips=expand(f"{REL}/trees/{{gene}}/tip_metadata.tsv", gene=TREE_GENES),
        placements=expand(f"{REL}/trees/{{gene}}/placements.tsv", gene=TREE_GENES),
        alignments=expand(f"{REL}/trees/{{gene}}/aligned.fasta", gene=TREE_GENES),
        columns=expand(f"{REL}/trees/{{gene}}/trimal_columns.txt", gene=TREE_GENES),
        script="scripts/write_release_report.py",
    output:
        report=f"reports/{RELEASE}/README.md",
        figures=directory(f"reports/{RELEASE}/figures"),
        data=directory(f"reports/{RELEASE}/data"),
        index="reports/README.md",
    shell:
        """
        python {input.script} --release {RELEASE} --release-dir {REL} \
          --genes {TREE_GENES} --out-dir reports/{RELEASE} --index {output.index:q}
        """
