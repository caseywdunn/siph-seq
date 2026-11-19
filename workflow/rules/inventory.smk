"""
List all public siphonophore sequence data and prepare shared references.

1. Query the public databases for the release: inventory_ncbi_nucleotide,
   inventory_sra_runs, inventory_genomes.
2. Build the reference marker set used to identify genes by similarity:
   export_sharkmer_panel, fetch_reference_records, build_marker_references,
   make_marker_db_blast.
3. Resolve NCBI taxonomy for every dataset and reference: resolve_taxonomy.
4. Combine the inventories into one manifest: build_manifest.

Next: ncbi_records.smk, sra_reads.smk and genomes.smk process the selected
datasets; trees.smk uses the references as outgroups.
"""


rule inventory_ncbi_nucleotide:
    output:
        f"{REL}/inventory/ncbi_nucleotide.tsv",
    params:
        types=config["ncbi"]["process_record_types"],
    log:
        f"{REL}/logs/inventory_ncbi_nucleotide.log",
    shell:
        """
        python scripts/inventory_ncbi_nucleotide.py \
          --taxid {TAXON[taxid]} --taxon-name {TAXON[name]:q} \
          --max-record-length {config[ncbi][max_record_length]} \
          --process-record-types {params.types} \
          --batch-size {config[ncbi][batch_size]} \
          --out {output:q} 2> {log:q}
        """


checkpoint inventory_sra_runs:
    output:
        f"{REL}/inventory/sra_runs.tsv",
    params:
        max_runs=(
            f"--max-runs {config['sra']['max_runs']}" if config["sra"]["max_runs"] else ""
        ),
    log:
        f"{REL}/logs/inventory_sra_runs.log",
    shell:
        """
        python scripts/inventory_sra_runs.py \
          --taxid {TAXON[taxid]} --taxon-name {TAXON[name]:q} \
          --platforms {config[sra][platforms]} \
          --strategies {config[sra][library_strategies]} {params.max_runs} \
          --out {output:q} 2> {log:q}
        """


checkpoint inventory_genomes:
    output:
        f"{REL}/inventory/genomes.tsv",
    params:
        include=(
            "--include " + " ".join(config["genomes"]["include"])
            if config["genomes"]["include"]
            else ""
        ),
    log:
        f"{REL}/logs/inventory_genomes.log",
    shell:
        """
        python scripts/inventory_genomes.py \
          --taxid {TAXON[taxid]} --taxon-name {TAXON[name]:q} \
          --prefix {config[genomes][accession_prefix]} {params.include} \
          --out {output:q} 2> {log:q}
        """


rule export_sharkmer_panel:
    output:
        f"{REFS}/{PANEL}_panel.yaml",
    shell:
        "sharkmer --export-panel {PANEL} > {output:q}"


rule fetch_reference_records:
    input:
        panel=f"{REFS}/{PANEL}_panel.yaml",
    output:
        f"{REFS}/reference_records.txt",
    params:
        records=config["markers"]["reference_records"],
    log:
        f"{REFS}/logs/fetch_reference_records.log",
    shell:
        """
        python scripts/fetch_genbank_records.py \
          --accessions {params.records} --panel {input.panel:q} \
          --store data/ncbi_nucleotide --out {output:q} 2> {log:q}
        """


rule build_marker_references:
    input:
        panel=f"{REFS}/{PANEL}_panel.yaml",
        records=f"{REFS}/reference_records.txt",
        vocabulary="config/gene_vocabulary.tsv",
        script="scripts/build_marker_references.py",
    output:
        fasta=f"{REFS}/markers.fasta",
        table=f"{REFS}/markers.tsv",
    params:
        records=config["markers"]["reference_records"],
    log:
        f"{REFS}/logs/build_marker_references.log",
    shell:
        """
        python {input.script} --panel {input.panel:q} --gene-map {GENE_MAP} \
          --records {params.records} --store data/ncbi_nucleotide \
          --vocabulary {input.vocabulary:q} \
          --fasta {output.fasta:q} --table {output.table:q} 2> {log:q}
        """


rule make_marker_db_blast:
    input:
        f"{REFS}/markers.fasta",
    output:
        multiext(f"{REFS}/markers", ".ndb", ".nhr", ".nin", ".nsq"),
    log:
        f"{REFS}/logs/make_marker_db_blast.log",
    shell:
        "makeblastdb -in {input:q} -dbtype nucl -out {REFS}/markers > {log:q} 2>&1"


rule resolve_taxonomy:
    input:
        f"{REL}/inventory/ncbi_nucleotide.tsv",
        f"{REL}/inventory/sra_runs.tsv",
        f"{REL}/inventory/genomes.tsv",
        f"{REFS}/markers.tsv",
    output:
        f"{REL}/inventory/taxonomy.tsv",
    log:
        f"{REL}/logs/resolve_taxonomy.log",
    shell:
        """
        python scripts/resolve_taxonomy.py --tables {input:q} \
          --focal-taxid {TAXON[taxid]} --out {output:q} 2> {log:q}
        """


rule build_manifest:
    input:
        ncbi=f"{REL}/inventory/ncbi_nucleotide.tsv",
        sra=f"{REL}/inventory/sra_runs.tsv",
        genomes=f"{REL}/inventory/genomes.tsv",
        taxonomy=f"{REL}/inventory/taxonomy.tsv",
    output:
        f"{REL}/manifest.tsv",
    shell:
        """
        python scripts/build_manifest.py --ncbi {input.ncbi:q} --sra {input.sra:q} \
          --genomes {input.genomes:q} --taxonomy {input.taxonomy:q} --out {output:q}
        """
