"""
Build one gene tree per common marker gene, spanning all data sources.

Each tree combines GenBank record regions, sharkmer products confirmed by
similarity, genome-extracted regions, and non-siphonophore reference
sequences as outgroups. Short barcodes are included: near full-length
sequences form an alignment backbone, and shorter ones are added to it as
fragments so they do not distort the alignment of the long sequences.

1. Combine one gene's sequences with taxonomy and tip labels, split into
   backbone and fragments: assemble_gene_sequences.
2. Align the backbone, then add fragments: align_backbone_mafft,
   add_fragments_mafft.
3. Choose well-aligned columns on the backbone and apply them to all
   sequences: trim_alignment_trimal.
4. Infer a maximum-likelihood tree and restore tip labels:
   infer_gene_tree_iqtree, relabel_gene_tree.

Next: flag_suspect_placements in reports.smk evaluates each tree.
"""


rule assemble_gene_sequences:
    input:
        taxonomy=f"{REL}/inventory/taxonomy.tsv",
        ncbi_regions=f"{REL}/ncbi/marker_regions.tsv",
        ncbi_fasta=f"{REL}/ncbi/marker_regions.fasta",
        ncbi_metadata=f"{REL}/ncbi/record_metadata.tsv",
        sra_products=f"{REL}/sra/products.tsv",
        sra_regions=f"{REL}/sra/marker_regions.tsv",
        sra_fasta=f"{REL}/sra/marker_regions.fasta",
        sra_inventory=f"{REL}/inventory/sra_runs.tsv",
        genome_regions=lambda wc: expand(
            "results/genomes/{asm}/marker_regions.tsv", asm=selected_genomes()
        ),
        genome_fastas=lambda wc: expand(
            "results/genomes/{asm}/marker_regions.fasta", asm=selected_genomes()
        ),
        genome_inventory=f"{REL}/inventory/genomes.tsv",
        references=f"{REFS}/markers.tsv",
        reference_fasta=f"{REFS}/markers.fasta",
        script="scripts/assemble_gene_sequences.py",
    output:
        backbone=f"{REL}/trees/{{gene}}/backbone.fasta",
        fragments=f"{REL}/trees/{{gene}}/fragments.fasta",
        table=f"{REL}/trees/{{gene}}/tip_metadata.tsv",
    params:
        min_length=lambda wc: config["trees"]["min_length"][wc.gene],
        backbone_min_length=lambda wc: config["trees"]["backbone_min_length"][wc.gene],
    shell:
        """
        python {input.script} --gene {wildcards.gene} --min-length {params.min_length} \
          --backbone-min-length {params.backbone_min_length} \
          --taxonomy {input.taxonomy:q} \
          --ncbi-regions {input.ncbi_regions:q} --ncbi-fasta {input.ncbi_fasta:q} \
          --ncbi-metadata {input.ncbi_metadata:q} \
          --sra-products {input.sra_products:q} --sra-regions {input.sra_regions:q} \
          --sra-fasta {input.sra_fasta:q} --sra-inventory {input.sra_inventory:q} \
          --genome-regions {input.genome_regions:q} --genome-fastas {input.genome_fastas:q} \
          --genome-inventory {input.genome_inventory:q} \
          --references {input.references:q} --reference-fasta {input.reference_fasta:q} \
          --backbone {output.backbone:q} --fragments {output.fragments:q} \
          --table {output.table:q}
        """


rule align_backbone_mafft:
    input:
        f"{REL}/trees/{{gene}}/backbone.fasta",
    output:
        f"{REL}/trees/{{gene}}/backbone_aligned.fasta",
    threads: 8
    resources:
        mem_mb=16000,
        runtime=240,
    log:
        f"{REL}/trees/{{gene}}/mafft_backbone.log",
    shell:
        """
        mafft {config[trees][mafft_args]} --preservecase --thread {threads} {input:q} \
          > {output:q} 2> {log:q}
        """


# --keeplength keeps the backbone's columns, so column choices made on the
# backbone apply directly to the full alignment.
rule add_fragments_mafft:
    input:
        backbone=f"{REL}/trees/{{gene}}/backbone_aligned.fasta",
        fragments=f"{REL}/trees/{{gene}}/fragments.fasta",
    output:
        f"{REL}/trees/{{gene}}/aligned.fasta",
    threads: 8
    resources:
        mem_mb=16000,
        runtime=240,
    log:
        f"{REL}/trees/{{gene}}/mafft_fragments.log",
    shell:
        """
        if [ -s {input.fragments:q} ]; then
          mafft --addfragments {input.fragments:q} --keeplength --preservecase \
            --thread {threads} {input.backbone:q} > {output:q} 2> {log:q}
        else
          cp {input.backbone:q} {output:q}
        fi
        """


rule trim_alignment_trimal:
    input:
        backbone=f"{REL}/trees/{{gene}}/backbone_aligned.fasta",
        alignment=f"{REL}/trees/{{gene}}/aligned.fasta",
        script="scripts/apply_column_mask.py",
    output:
        columns=f"{REL}/trees/{{gene}}/trimal_columns.txt",
        trimmed=f"{REL}/trees/{{gene}}/trimmed.fasta",
        sites=f"{REL}/trees/{{gene}}/aligned_sites.tsv",
    log:
        f"{REL}/trees/{{gene}}/trimal.log",
    shell:
        """
        trimal -in {input.backbone:q} -out /dev/null {config[trees][trimal_args]} \
          -colnumbering > {output.columns:q} 2> {log:q}
        python {input.script} --alignment {input.alignment:q} --columns {output.columns:q} \
          --min-sites {config[trees][min_aligned_sites]} \
          --out {output.trimmed:q} --sites {output.sites:q}
        """


rule infer_gene_tree_iqtree:
    input:
        f"{REL}/trees/{{gene}}/trimmed.fasta",
    output:
        tree=f"{REL}/trees/{{gene}}/iqtree.treefile",
        report=f"{REL}/trees/{{gene}}/iqtree.iqtree",
    params:
        prefix=f"{REL}/trees/{{gene}}/iqtree",
    threads: 8
    resources:
        mem_mb=16000,
        runtime=1440,
    log:
        f"{REL}/trees/{{gene}}/iqtree.stdout.log",
    shell:
        """
        iqtree3 -s {input:q} -m {config[trees][iqtree_model]} -B {config[trees][iqtree_bootstrap]} \
          --seed {config[trees][seed]} -T {threads} --prefix {params.prefix:q} -redo \
          > {log:q} 2>&1
        """


rule relabel_gene_tree:
    input:
        tree=f"{REL}/trees/{{gene}}/iqtree.treefile",
        tips=f"{REL}/trees/{{gene}}/tip_metadata.tsv",
    output:
        f"{REL}/trees/{{gene}}/tree.nwk",
    shell:
        """
        python scripts/relabel_tree.py --tree {input.tree:q} --tips {input.tips:q} \
          --out {output:q}
        """
