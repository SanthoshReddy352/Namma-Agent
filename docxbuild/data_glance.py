# -*- coding: utf-8 -*-
"""Glance table rows + pillar intro text."""

GLANCE = [
    ("1", "SSP for Spaced Repetition (FSRS)", "KDD 2022", "P1", "Optimal per-item review schedule via stochastic shortest path; the core SR algorithm."),
    ("2", "Capturing the Dynamics of Memory (FSRS-6)", "IEEE TKDE 2023", "P1", "Alternates memory prediction with schedule optimization; releases a 220M-row dataset."),
    ("3", "Enhancing Human Learning via SR Optimization", "PNAS 2019", "P1", "Optimal review policy = recall probability; online MEMORIZE algorithm; Duolingo validation."),
    ("4", "DAS3H", "EDM 2019", "P1", "Student model on item-skill (q-matrix) structure - the bridge from memory models to graphs."),
    ("5", "Discretized Streams (D-Streams)", "SOSP 2013", "P2", "The canonical micro-batching model; batch interval = latency/throughput dial."),
    ("6", "Queueing Theory for Low-Latency Batched Inference", "arXiv 2024", "P2", "Bulk-queue analysis of dynamic / fixed / elastic batching policies."),
    ("7", "Throughput-Optimal Scheduling for Inference", "arXiv 2025", "P2", "Work-conserving scheduling is throughput-optimal; fluid-limit proof framework."),
    ("8", "PagedAttention / vLLM", "SOSP 2023", "P2", "Continuous batching + paged memory: 2-4x throughput at equal latency."),
    ("9", "Survey on Temporal Knowledge Graph Learning", "arXiv 2024", "P3", "Taxonomy, datasets, metrics for time-evolving KGs - the definitional reference."),
    ("10", "GraphBolt", "EuroSys 2019", "P3", "Batched, dependency-driven incremental recomputation on streaming graphs."),
    ("11", "Temporal GraphRAG", "arXiv 2025", "P3", "Incremental graph updates + hierarchical time index; localized recomputation."),
]

PILLAR_INTROS = {
    "P1": ("These four papers define what a spaced-repetition computation actually is: a memory model predicts recall, "
           "and an optimization layer decides the next review time. They are the mathematical core your friend's batch "
           "scheduler will operate on - every batch contains many instances of these per-item computations."),
    "P2": ("These four papers are the systems half of the problem: how to turn a stream of small, independent "
           "computations (the reviews) into efficient batches. They supply the design patterns (micro-batching, "
           "continuous batching), the mathematical analysis (bulk queues, work-conserving scheduling), and the proof "
           "that batching is the right lever."),
    "P3": ("These three papers cover the data-structure side: how to represent knowledge that changes over time, and "
           "how to keep computation current when the graph evolves - without recomputing everything. This is the "
           "pillar that makes the paper stand out from plain 'batch the scheduler' systems work."),
}
