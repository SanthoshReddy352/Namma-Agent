# -*- coding: utf-8 -*-
"""Pillar 3 - Dynamic & Temporal Knowledge Graphs."""

PAPERS3 = [
 dict(
  title="A Survey on Temporal Knowledge Graph: Representation Learning and Applications",
  authors="Li Cai, Xin Mao, Yuhao Zhou, Zhaoguang Long, Changxu Wu, Man Lan",
  venue="arXiv 2024", year="2024",
  link="https://arxiv.org/abs/2403.04782", link_label="arxiv.org/abs/2403.04782",
  summary=("A comprehensive survey of temporal knowledge graphs (TKGs) - knowledge graphs whose facts are timestamped "
           "and evolve. It defines the problem, datasets, and metrics, then taxonomizes representation-learning methods "
           "(translational, GNN-based, recurrent/sequential, and more) and lists downstream applications."),
  findings=[
   "A complete taxonomy of TKG representation learning - the reference map of the field.",
   "Compiles standard TKG datasets and evaluation metrics, useful for positioning and benchmarking.",
   "Identifies open challenges: scalability, incremental/streaming learning, and handling unseen entities over time.",
  ],
  align=[
   "Use this as the definitional citation: 'dynamic knowledge graph' is a mature field with agreed terminology - the paper can borrow its formal definition of a temporal KG.",
   "Its identified open problems (incremental learning, scalability, streaming) are precisely where a batching layer adds value - the survey can frame the friend's contribution as a systems answer to those open problems.",
   "If the KG carries learned embeddings, TKG methods show how to update representations over time - background for any embedding-aware scheduling claim.",
  ]),
 dict(
  title="GraphBolt: Dependency-Driven Synchronous Processing of Streaming Graphs",
  authors="Mugilan Mariappan, Keval Vora",
  venue="EuroSys 2019", year="2019",
  link="https://github.com/pdclab/graphbolt", link_label="github.com/pdclab/graphbolt",
  summary=("GraphBolt is a streaming graph processing system that keeps Bulk Synchronous Parallel (BSP) semantics while "
           "the graph changes. It batches incoming edge/vertex updates into synchronous windows and uses "
           "dependency-driven incremental computation - only vertices whose input changed are recomputed. This "
           "delivers both high throughput and low latency for analytics on evolving graphs. (EuroSys 2019; full text: "
           "cs.sfu.ca/~keval/contents/papers/graphbolt-eurosys19.pdf)"),
  findings=[
   "Batching updates into windows is the key to amortizing cost on dynamic graphs - the same principle as the friend's paper, on the graph side.",
   "Dependency-driven recomputation: only affected vertices re-execute, so per-update cost is proportional to the change, not the whole graph.",
   "Keeps deterministic BSP results despite streaming input - correctness is preserved under batching.",
  ],
  align=[
   "This is the closest systems work to 'batching computations on dynamic graphs': it proves the pattern works at scale and gives the architecture (stream ingestor + batched window + incremental recompute) to mirror.",
   "The dependency-driven idea transfers directly: when a review changes a concept's mastery, only that concept's subtree (dependents/prerequisites) needs re-evaluation - schedule it as part of the next batch, not immediately.",
   "Strongest citation for the systems claim that batching + incremental recomputation jointly maximize throughput and minimize idle latency on evolving graphs.",
  ]),
 dict(
  title="RAG Meets Temporal Graphs: Time-Sensitive Modeling and Retrieval for Evolving Knowledge",
  authors="Jiale Han, Austin Cheung, Yubai Wei, Zheng Yu, Xusheng Wang, Bing Zhu, Yi Yang",
  venue="arXiv 2025 (Temporal GraphRAG)", year="2025",
  link="https://arxiv.org/abs/2510.13590", link_label="arxiv.org/abs/2510.13590",
  summary=("Temporal GraphRAG models an evolving corpus as a bi-level temporal graph: a temporal knowledge graph with "
           "timestamped relations plus a hierarchical time graph. New facts are extracted and merged incrementally, "
           "and the time hierarchy means only new leaf time nodes and their ancestors need report regeneration. "
           "Retrieval then gathers a subgraph within the temporal and semantic scope of the query."),
  findings=[
   "Explicit timestamped edges let identical facts at different times coexist without ambiguity - a clean way to represent an evolving knowledge state.",
   "Incremental merging of new facts into the existing graph avoids full re-indexing on every update.",
   "The hierarchical time index localizes recomputation to affected time slices - efficient and provably sufficient.",
  ],
  align=[
   "Shows exactly how to keep a knowledge graph current under a stream of updates with incremental, localized recomputation - the 'minimize idle latency when the KG changes' angle of the friend's title.",
   "The hierarchical indexing idea can be reused: when a concept's mastery changes, only the affected region of the knowledge graph needs its review-state recomputed and re-batched.",
   "Modern, citable evidence that time-aware graph maintenance is an active research direction - strengthens the paper's timeliness.",
  ]),
]
