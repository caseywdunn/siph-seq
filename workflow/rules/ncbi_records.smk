"""
Download GenBank gene records and identify the genes they contain.

Records are stored once per accession.version in data/ncbi_nucleotide/ and
reused by later releases. Gene identity comes from sequence similarity to the
reference markers; submitter annotations are normalized to the same gene
vocabulary and compared against it.

1. Download records not yet stored and parse them: fetch_ncbi_records,
   parse_ncbi_records.
2. Identify marker regions by similarity (shared with sharkmer products):
   search_markers_blastn, assign_marker_regions, extract_marker_regions.
3. Compare similarity with annotations: compare_gene_annotations.

Next: assemble_gene_sequences in trees.smk takes the marker regions.
"""


rule fetch_ncbi_records:
    input:
        f"{REL}/inventory/ncbi_nucleotide.tsv",
    output:
        f"{REL}/ncbi/accessions.txt",
    log:
        f"{REL}/logs/fetch_ncbi_records.log",
    shell:
        """
        python scripts/fetch_genbank_records.py --inventory {input:q} \
          --store data/ncbi_nucleotide --out {output:q} 2> {log:q}
        """


rule parse_ncbi_records:
    input:
        accessions=f"{REL}/ncbi/accessions.txt",
        vocabulary="config/gene_vocabulary.tsv",
    output:
        fasta=f"{REL}/ncbi/targets.fasta",
        metadata=f"{REL}/ncbi/record_metadata.tsv",
        annotations=f"{REL}/ncbi/record_annotations.tsv",
    log:
        f"{REL}/logs/parse_ncbi_records.log",
    shell:
        """
        python scripts/parse_genbank_records.py --accessions {input.accessions:q} \
          --store data/ncbi_nucleotide --vocabulary {input.vocabulary:q} \
          --fasta {output.fasta:q} --metadata {output.metadata:q} \
          --annotations {output.annotations:q} 2> {log:q}
        """


# Used for both GenBank records (ncbi) and sharkmer products (sra).
rule search_markers_blastn:
    input:
        targets=f"{REL}/{{collection}}/targets.fasta",
        db=rules.make_marker_db_blast.output,
    output:
        f"{REL}/{{collection}}/marker_hits.tsv",
    threads: 4
    resources:
        mem_mb=8000,
        runtime=120,
    shell:
        """
        blastn -task {config[markers][blast_task]} -query {input.targets:q} -db {REFS}/markers \
          -evalue {config[markers][evalue]} -max_target_seqs 50 -num_threads {threads} \
          -outfmt "6 qseqid sseqid pident length qstart qend sstart send evalue bitscore qlen slen" \
          > {output:q}
        """


rule assign_marker_regions:
    input:
        hits=f"{REL}/{{collection}}/marker_hits.tsv",
        references=f"{REFS}/markers.tsv",
    output:
        f"{REL}/{{collection}}/marker_regions.tsv",
    shell:
        """
        python scripts/assign_marker_regions.py --blast {input.hits:q} \
          --references {input.references:q} --mode query-targets \
          --evalue {config[markers][evalue]} --min-hsp-length {config[markers][min_hsp_length]} \
          --max-gap {config[markers][max_chain_gap]} --max-overlap {config[markers][max_gene_overlap]} \
          --out {output:q}
        """


rule extract_marker_regions:
    input:
        regions=f"{REL}/{{collection}}/marker_regions.tsv",
        targets=f"{REL}/{{collection}}/targets.fasta",
    output:
        f"{REL}/{{collection}}/marker_regions.fasta",
    shell:
        """
        python scripts/extract_regions.py --regions {input.regions:q} \
          --fasta {input.targets:q} --out {output:q}
        """


rule compare_gene_annotations:
    input:
        metadata=f"{REL}/ncbi/record_metadata.tsv",
        annotations=f"{REL}/ncbi/record_annotations.tsv",
        regions=f"{REL}/ncbi/marker_regions.tsv",
        vocabulary="config/gene_vocabulary.tsv",
    output:
        assignments=f"{REL}/ncbi/gene_assignments.tsv",
        records=f"{REL}/ncbi/record_genes.tsv",
    shell:
        """
        python scripts/compare_gene_annotations.py --metadata {input.metadata:q} \
          --annotations {input.annotations:q} --regions {input.regions:q} \
          --vocabulary {input.vocabulary:q} \
          --assignments {output.assignments:q} --records {output.records:q}
        """
