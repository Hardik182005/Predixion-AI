> **Sample report.** Mode: live. Date: 2026-10-28. Model: gpt-6.1-terra (reasoning effort low). Prompt version: 2026-10-28.3. Produced by `predixion eval --mode live` and exported with the app's Markdown renderer; not edited. Source: `evals/results/live-gpt-6.1-terra-comparison-recheck.json`.

# Compare the top three open-source vector databases for a startup building RAG products.

**Status:** Completed · **Mode:** live · **Model:** gpt-6.1-terra · **Created:** 2026-10-28 11:40 UTC · **Run:** `run_2f541217edf5f563a32343dd`

> Stopped: All required criteria have supporting evidence.

## Short answer

Qdrant, Weaviate and Milvus are reasonable open-source vector database candidates to shortlist for a startup’s RAG product, rather than a definitive ranked top three. All three are described as supporting hybrid search and flexible deployment; Weaviate also has documented LangChain and LlamaIndex integrations in the reviewed evidence. The main uncertainties are their exact licenses, comparative adoption and workload-specific performance. [E4] [E8] [E12]

## Findings

- The selection is based on their inclusion in a vector database comparison and their documented RAG-relevant features, not a measured adoption ranking. Adoption figures were not found. [E8] [E12] *(interpretation)*
- All three are described as open-source vector databases, but the reviewed evidence does not identify their licenses. [E3] [E7] [E13]
- All three are described as supporting hybrid search and metadata filtering. The reviewed evidence names LangChain and LlamaIndex integrations for Weaviate, but does not establish comparable integration coverage for the other two. [E4] [E8] [E11] [E12]
- Qdrant is a candidate to test for frequently updated workloads; the reviewed article says it handles frequent updates well, while Milvus needs an index rebuild for optimal performance after large bulk updates. [E10] *(interpretation)*
- Milvus is a candidate for larger-scale workloads, but a reviewed guide says it requires engineering resources. Weaviate and Qdrant also have managed and self-hosted options. [E1] [E3] [E4] [E13] *(interpretation)*
- Benchmark the shortlist on the startup’s own data, filters, update patterns and tail-latency targets before choosing. [E6] [E10] *(recommendation)*

## Comparison

| Option | Verify that each candidate is a vector database with an open-source core and identify its license. | Establish a transparent basis for selecting three leading candidates using adoption, ecosystem maturity, and RAG relevance. | Compare retrieval capabilities relevant to RAG, including filtering, hybrid search, integrations, and documented performance. | Compare deployment, operational complexity, scalability, managed options, and cost considerations for a startup. |
|---|---|---|---|---|
| Qdrant | Described as an open-source vector database; exact license not found in reviewed sources. [E3] | Included in a multi-database comparison and described as supporting hybrid search. Adoption figures were not found. [E8] [E12] | Filtering and hybrid search are documented; an article says it handles frequent updates well. Specific integrations and comparable benchmark results were not found. [E3] [E10] [E12] | Managed and self-hosted options are available. The reviewed evidence does not quantify operating costs or scaling limits. [E3] |
| Weaviate | Described as an open-source vector database; exact license not found in reviewed sources. [E7] | Included in a multi-database comparison; one source dates its open-source vector search to 2018. Adoption figures were not found. [E8] [E9] | Hybrid search, filtering and LangChain and LlamaIndex integrations are documented. One guide reports efficient performance to 50 million vectors, but provides no comparable benchmark results here. [E2] [E4] | Managed and self-hosted options are available, including Docker and Kubernetes deployment. One guide reports increasing resource requirements beyond 100 million vectors; prices were not found. [E2] [E9] |
| Milvus | Described as an open-source vector database; exact license not found in reviewed sources. [E13] | Included in a multi-database comparison and described as supporting hybrid search. Adoption figures were not found. [E8] [E12] | Hybrid search and metadata filtering are documented. One author ran a 10 million-vector microbenchmark, but the reviewed evidence does not provide its results; specific integrations were not found. [E8] [E11] [E12] [E14] | Zilliz Cloud is a managed service built on Milvus. A guide describes billion-vector scale but says engineering resources are needed; an article says large bulk updates require an index rebuild for optimal performance. Specific prices were not found. [E1] [E10] [E13] |

## Coverage

| Criterion | Status | Evidence |
|---|---|---|
| K1: Verify that each candidate is a vector database with an open-source core and identify its license. | supported | E3, E4, E5, E7, E12, E13 |
| K2: Establish a transparent basis for selecting three leading candidates using adoption, ecosystem maturity, and RAG relevance. | supported | E4, E8, E9, E12 |
| K3: Compare retrieval capabilities relevant to RAG, including filtering, hybrid search, integrations, and documented performance. | supported | E2, E3, E4, E6, E7, E10, E11, E12, E14 |
| K4: Compare deployment, operational complexity, scalability, managed options, and cost considerations for a startup. | supported | E1, E2, E3, E4, E7, E9, E10, E12, E13 |

## Confidence

**High.** High: 4 of 4 required criteria are supported; 19 of 19 checked claims are fully supported; evidence comes from 5 independent sites.

## Limitations

- Publication dates are provider estimates or dates found in page text and may be inaccurate.
- The reviewed evidence does not identify the core licenses, so recognized-license eligibility remains unverified for all three.
- No adoption figures or systematic ecosystem comparison were provided; the shortlist is not a defensible universal ranking.
- Comparable benchmark results, detailed pricing and specific integration evidence for Qdrant and Milvus were not provided.
- Some operational and scale claims come from undated guides, and managed-offering terms were not reviewed.

## Assumptions

- “Top three” means leading current options selected using a combination of adoption, ecosystem maturity, and relevance to RAG.
- Open source refers to the core database having a recognized open-source license; managed offerings may have different terms.
- The question does not define “top”; the research will use a transparent selection process rather than a single popularity ranking.

## Next steps

- Check each core repository’s current license and the terms of any managed offering before committing.
- Benchmark shortlisted products on representative RAG data, filters, update patterns and tail-latency targets.
- Obtain current managed-service quotes and estimate self-hosting infrastructure and engineering costs.
- Verify the integrations and deployment requirements needed by the startup’s stack.

## Evidence

- **[E1]** Best Vector Databases in 2026: A Complete Comparison Guide (firecrawl.dev): “Milvus / Zilliz Cloud: billions of vectors at lower cost; requires engineering resources.”
- **[E2]** Best Vector Databases in 2026: A Complete Comparison Guide (firecrawl.dev): “Both open-source and managed deployment options provide flexibility. Performance scales efficiently to 50 million vectors, though resource requirements increase beyond 100 million.”
- **[E3]** Best Vector Databases in 2026: A Complete Comparison Guide (firecrawl.dev): “Qdrant Budget-friendly vector database with the best free tier and excellent filtering for moderate-scale projects Type \| Open-source, Rust-based, managed and self-hosted options”
- **[E4]** Best Vector Databases for RAG: Top Picks for 2026 \| TiDB (pingcap.com): “Weaviate \| Managed + self-hosted \| Yes \| Yes \| Strong \| HNSW (+ hybrid features) \| LangChain, LlamaIndex \| Cloud + self-hosted”
- **[E5]** Best Vector Databases for RAG: Top Picks for 2026 \| TiDB (pingcap.com) (contradicts): “Pinecone \| Managed \| No \| Yes \| Strong \| Managed ANN options \| LangChain, LlamaIndex \| Usage-based + tiers”
- **[E6]** Best Vector Databases for RAG: Top Picks for 2026 \| TiDB (pingcap.com): “Use these snapshots to shortlist 2-3 candidates, then benchmark them on your own data and real query patterns, especially the filters and tail-latency targets your app will live or die by.”
- **[E7]** Best Vector Databases for RAG: Top Picks for 2026 \| TiDB (pingcap.com): “Weaviate is an open-source vector database (with managed deployment options) used to store embeddings and perform vector similarity search, often alongside metadata filtering.”
- **[E8]** Vector Database Comparison: Performance, Pricing & Scaling \| Deploybase (deploybase.ai): “Compare Pinecone, Weaviate, Qdrant, Milvus, and ChromaDB.”
- **[E9]** Vector Database Comparison: Performance, Pricing & Scaling \| Deploybase (deploybase.ai): “Weaviate is open-source vector search (since 2018). Available self-hosted on Kubernetes/Docker or via Weaviate Cloud Service (WCS) managed offering.”
- **[E10]** Vector Database Comparison: Performance, Pricing & Scaling \| Deploybase (deploybase.ai): “Pinecone and Qdrant handle frequent updates well. Milvus requires index rebuild for optimal performance after large bulk updates.”
- **[E11]** Vector Database Comparison: Performance, Pricing & Scaling \| Deploybase (deploybase.ai): “All databases support metadata filtering during vector search. Store metadata (tags, timestamps, URLs) alongside vectors.”
- **[E12]** 7 Most Popular Vector Databases: A 2026 Guide (cake.ai): “Open-source options provide better control, scalability, and integration: Milvus, Weaviate, Qdrant, and others support hybrid search, flexible deployment, and production-grade performance.”
- **[E13]** Scaling Vector Search: My Hands-On Comparison of Self-Hosted and Managed Solutions (medium.com): “Specifically, I focused on Milvus (an open-source vector database) and Zilliz Cloud (a fully managed service built on Milvus).”
- **[E14]** Scaling Vector Search: My Hands-On Comparison of Self-Hosted and Managed Solutions (medium.com): “To ground my exploration in something concrete, I ran microbenchmarks on a 10 million-vector dataset using VectorDBBench, an open-source Python tool for benchmarking vector databases.”

## Sources

- **S1** Best Vector Databases in 2026: A Complete Comparison Guide · medium · <https://www.firecrawl.dev/blog/best-vector-databases>
- **S4** 7 Most Popular Vector Databases: A 2026 Guide · medium · <https://www.cake.ai/blog/best-vector-databases>
- **S5** Best Vector Databases for RAG: Top Picks for 2026 \| TiDB · medium · <https://www.pingcap.com/compare/best-vector-database>
- **S11** Vector Database Comparison: Performance, Pricing & Scaling \| Deploybase · medium · <https://deploybase.ai/articles/vector-database-comparison>
- **S12** Scaling Vector Search: My Hands-On Comparison of Self-Hosted and Managed Solutions · medium · <https://medium.com/@aefselinates/scaling-vector-search-my-hands-on-comparison-of-self-hosted-and-managed-solutions-8efb68fe8c8e>
- **S2** We Tried and Tested 10 Best Vector Databases for RAG Pipelines - ZenML Blog · low · <https://www.zenml.io/blog/vector-databases-for-rag>
- **S3** What Is a Vector Database? Top 10 Open Source Options · low · <https://www.instaclustr.com/education/vector-database/top-10-open-source-vector-databases>
- **S6** Best vector database to use with RAG - ChatGPT - OpenAI Developer Community · medium · <https://community.openai.com/t/best-vector-database-to-use-with-rag/615350>
- **S7** How Vector Databases Enable RAG and 9 Tools to Know in 2026 · medium · <https://www.instaclustr.com/education/vector-database/how-vector-databases-enable-rag-and-9-tools-to-know-in-2026>
- **S8** Best vector databases for RAG in 2026 - Articles - Braintrust · medium · <https://www.braintrust.dev/articles/best-vector-databases-for-rag-2026>
- **S9** Comparing the best open source vector databases (2026) · medium · <https://redis.io/blog/best-open-source-vector-databases-comparison>
- **S10** Best 8 Vector Databases in 2026 · low · <https://data4ai.com/blog/tool-comparisons/best-vector-databases?md=1>
- **S13** Self-Hosted vs Managed Vector Databases — The AI Database Blog · medium · <https://theaidatabaseblog.com/learn/self-hosted-vs-managed-vector-databases>
- **S14** Vector Databases Compared (11 Tools) (2026) \| AI Calculator Pro · medium · <https://aicalculatorpro.com/ai-stack/vector-databases>
- **S15** LanceDB Pricing 2026: Free Open Source & Cloud Plans · medium · <https://costbench.com/software/vector-databases/lancedb>

## Execution

- Rounds: 1; searches: 3; pages read: 5; model calls: 4
- Tokens: 12439 in / 4187 out; estimated cost: $0.0654
- Duration: 58.8 s; prompt version 2026-10-28.3
- Verification: 19/19 claims supported
