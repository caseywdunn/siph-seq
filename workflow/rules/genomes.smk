"""
Download genome assemblies and extract the common marker genes from them.

Assemblies are stored once per versioned accession in data/genomes/<asm>/.
Reference markers are searched against each assembly, and for each gene the
best-scoring regions are extracted (genomes.max_copies_per_gene, with per-gene
exceptions in genomes.max_copies_by_gene). More than one rDNA copy is kept
because the best-scoring copy is not always the siphonophore's own:
contaminant rDNA from other hydrozoans can match the references better.
Every copy goes into the gene trees, where foreign copies are flagged.
Mitochondrial markers (16S, CO1) keep only the best copy, since lower-ranked
hits were nuclear copies or spurious fragments.

1. Download each assembly: download_genome_datasets.
2. Index it for searching and extraction: make_genome_db_blast.
3. Find and extract marker genes: search_genome_markers_blastn,
   assign_genome_marker_regions, extract_genome_marker_regions.

Next: assemble_gene_sequences in trees.smk takes the extracted regions.
"""


def selected_genomes(wildcards=None):
    """Assembly accessions selected in this release's inventory."""
    # Snakemake 9.24 cannot draw --rulegraph once checkpoint outputs exist, so
    # the README graph is drawn with one example accession (rulegraph_example).
    if config.get("rulegraph_example"):
        return ["GCA_032273505.1"]
    path = checkpoints.inventory_genomes.get().output[0]
    with open(path) as f:
        header = f.readline().rstrip("\n").split("\t")
        acc, sel = header.index("accession"), header.index("selected")
        return [
            v[acc] for v in (line.rstrip("\n").split("\t") for line in f) if v[sel] == "true"
        ]


rule download_genome_datasets:
    output:
        fasta="data/genomes/{asm}/genome.fna.gz",
        report="data/genomes/{asm}/assembly_data_report.jsonl",
    params:
        zip="data/genomes/{asm}/download.zip",
    resources:
        runtime=240,
        mem_mb=4000,
    log:
        "data/genomes/{asm}/download.log",
    shell:
        """
        datasets download genome accession {wildcards.asm} --include genome \
          --filename {params.zip:q} > {log:q} 2>&1
        unzip -p {params.zip:q} 'ncbi_dataset/data/{wildcards.asm}/*.fna' | gzip > {output.fasta:q}
        unzip -p {params.zip:q} ncbi_dataset/data/assembly_data_report.jsonl > {output.report:q}
        rm {params.zip:q}
        test -s {output.fasta:q}
        """


rule make_genome_db_blast:
    input:
        "data/genomes/{asm}/genome.fna.gz",
    output:
        directory("data/genomes/{asm}/blastdb"),
    resources:
        runtime=240,
        mem_mb=8000,
    log:
        "data/genomes/{asm}/makeblastdb.log",
    shell:
        """
        mkdir -p {output:q}
        gzip -dc {input:q} | makeblastdb -in - -dbtype nucl -parse_seqids \
          -title {wildcards.asm} -out {output:q}/genome > {log:q} 2>&1
        """


rule search_genome_markers_blastn:
    input:
        markers=f"{REFS}/markers.fasta",
        db="data/genomes/{asm}/blastdb",
    output:
        "results/genomes/{asm}/marker_hits.tsv",
    threads: 8
    resources:
        runtime=720,
        mem_mb=32000,
    shell:
        """
        blastn -task {config[markers][blast_task]} -query {input.markers:q} \
          -db {input.db:q}/genome -evalue {config[markers][evalue]} \
          -max_target_seqs 500 -num_threads {threads} \
          -outfmt "6 qseqid sacc pident length qstart qend sstart send evalue bitscore qlen slen" \
          > {output:q}
        """


rule assign_genome_marker_regions:
    input:
        hits="results/genomes/{asm}/marker_hits.tsv",
        references=f"{REFS}/markers.tsv",
    output:
        "results/genomes/{asm}/marker_regions.tsv",
    params:
        overrides=" ".join(
            f"--max-per-gene-override {gene}={n}"
            for gene, n in config["genomes"].get("max_copies_by_gene", {}).items()
        ),
    shell:
        """
        python scripts/assign_marker_regions.py --blast {input.hits:q} \
          --references {input.references:q} --mode subject-targets \
          --evalue {config[markers][evalue]} --min-hsp-length {config[markers][min_hsp_length]} \
          --max-gap {config[markers][max_chain_gap]} --max-overlap {config[markers][max_gene_overlap]} \
          --max-per-gene {config[genomes][max_copies_per_gene]} --per-gene-scope all \
          {params.overrides} --region-prefix {wildcards.asm}__ --out {output:q}
        """


rule extract_genome_marker_regions:
    input:
        regions="results/genomes/{asm}/marker_regions.tsv",
        db="data/genomes/{asm}/blastdb",
    output:
        "results/genomes/{asm}/marker_regions.fasta",
    shell:
        """
        python scripts/extract_regions.py --regions {input.regions:q} \
          --blastdb {input.db:q}/genome --out {output:q}
        """
