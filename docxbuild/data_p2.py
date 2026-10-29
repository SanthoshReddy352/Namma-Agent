# -*- coding: utf-8 -*-
"""Pillar 2 - Batching, CPU Throughput & Latency."""

PAPERS2 = [
 dict(
  title="Discretized Streams: Fault-Tolerant Streaming Computation at Scale",
  authors="Matei Zaharia, Tathagata Das, Haoyuan Li, Timothy Hunter, Scott Shenker, Ion Stoica",
  venue="SOSP 2013 (Spark Streaming / D-Streams)", year="2013",
  link="https://people.csail.mit.edu/matei/papers/2013/sosp_spark_streaming.pdf",
  link_label="SOSP'13 PDF (MIT)",
  summary=("The paper that invented micro-batching as a first-class processing model. Instead of processing each event "
           "individually, D-Streams slice the incoming stream into small, deterministic batches ('discretized streams') "
           "and process each batch in parallel. The batch interval becomes a single knob that trades latency against "
           "throughput and recovery cost."),
  findings=[
   "Micro-batching converts a streaming problem into a sequence of batch jobs - reusing batch processing engines and their fault tolerance.",
   "Fault recovery via recomputation from lineage, dramatically cheaper than hot replication.",
   "The batch interval is the explicit latency/throughput dial: smaller intervals = lower latency, larger intervals = higher throughput and lower overhead.",
  ],
  align=[
   "Your friend's core idea - 'algorithmic batching of spaced-repetition computations' - is exactly micro-batching applied to review events. This paper is the canonical citation for that design pattern.",
   "The batch-interval dial maps 1:1 to the paper's 'maximize throughput vs minimize idle latency' objective: reviews arriving between batches idle until the next batch boundary.",
   "Provides the vocabulary and architecture (ingest, batch, compute, commit) for the proposed system's design section.",
  ]),
 dict(
  title="A Queueing Theoretic Perspective on Low-Latency LLM Inference with Variable Token Length",
  authors="Yuqing Yang, Yuedong Xu, Lei Jiao",
  venue="arXiv 2024 (IEEE WiOpt)", year="2024",
  link="https://arxiv.org/abs/2407.05347", link_label="arxiv.org/abs/2407.05347",
  summary=("A mathematical analysis of batched inference using queueing theory. The authors model inference servers "
           "with an M/G/1 queue and model batched processing as a bulk-service queue where batch time depends on batch "
           "size and the largest job inside the batch. They derive closed-form queueing delays for three batching "
           "policies: dynamic (batch everything buffered), fixed (constant batch size), and elastic (no intra-batch "
           "waiting)."),
  findings=[
   "Exact delay formulas for dynamic, fixed, and elastic batching - validated against event-driven simulation.",
   "A small fraction of long jobs dominates queueing delay (heavy-tail effect); clipping or isolating them helps a lot.",
   "Batching policy choice is a real trade-off: fixed batches cap latency variance, dynamic batches maximize utilization, elastic batches cut head-of-line blocking.",
  ],
  align=[
   "This is the ready-made math toolkit for your friend's analysis section: model review computations as jobs with variable service times (hard vs easy cards), and derive expected delay and throughput for each candidate batching policy.",
   "The three policies (dynamic/fixed/elastic) can be directly proposed and compared in the paper - likely as the central experimental axis.",
   "The 'batch time depends on the max job in the batch' insight transfers perfectly: a batch of review computations finishes when its slowest item (e.g., a hard card needing full RNN inference) finishes.",
  ]),
 dict(
  title="Throughput-Optimal Scheduling Algorithms for LLM Inference and AI Agents",
  authors="J.G. Dai, Tianze Deng, Yueying Li, Tianyi Peng",
  venue="arXiv 2025", year="2025",
  link="https://arxiv.org/abs/2504.07347", link_label="arxiv.org/abs/2504.07347",
  summary=("Builds queueing fundamentals for batched inference systems. The authors prove that any 'work-conserving' "
           "scheduling policy - one that never idles a server while work is waiting - achieves maximum throughput, for "
           "both individual requests and agent workloads with DAG/fork-join topologies. They develop a fluid-limit "
           "framework for multi-class batched processing networks under K-FCFS scheduling."),
  findings=[
   "Work-conserving scheduling is provably throughput-optimal - a simple, testable design principle.",
   "Real systems Orca and Sarathi-Serve are throughput-optimal; FasterTransformer and vanilla vLLM are not maximally stable.",
   "Batch-size limits and cyclic (DAG) routing complicate the throughput picture - open problems at the queueing/systems interface.",
  ],
  align=[
   "Gives your friend a theorem to lean on: as long as the batch scheduler is work-conserving, throughput is maximized - then the remaining design freedom is latency, i.e., batch composition and interval.",
   "The multi-class batched processing network framework fits heterogeneous review workloads (new cards, due reviews, re-learning) - each class can have its own service-time distribution.",
   "Directly supports the title's 'maximizing CPU throughput' claim with formal backing.",
  ]),
 dict(
  title="Efficient Memory Management for Large Language Model Serving with PagedAttention",
  authors="Woosuk Kwon, Zhuohan Li, Siyuan Zhuang, Ying Sheng, Lianmin Zheng, Cody Hao Yu, Joseph E. Gonzalez, Hao Zhang, Ion Stoica",
  venue="SOSP 2023 (vLLM)", year="2023",
  link="https://arxiv.org/abs/2309.06180", link_label="arxiv.org/abs/2309.06180",
  summary=("Shows how to make batching dramatically more efficient in practice. vLLM introduces continuous batching "
           "(new requests join a batch as soon as another finishes) plus paged memory management for the KV cache, "
           "cutting fragmentation. The result: 2-4x higher throughput than state-of-the-art systems at the same "
           "latency."),
  findings=[
   "Continuous (dynamic) batching beats fixed-size batching because the batch is never stalled by stragglers.",
   "Paging eliminates memory fragmentation, which is what actually caps batch size in memory-bound workloads.",
   "2-4x throughput improvement over FasterTransformer and Orca with equal latency.",
  ],
  align=[
   "The 'continuous batching' pattern is the natural evolution of your friend's scheduler: instead of fixed review sessions, batches close whenever a server frees up - maximizing CPU utilization and minimizing idle time.",
   "Paged memory management is a useful analogy if per-item state (RNN hidden states, memory parameters) grows large across many cards.",
   "A strong systems citation showing that batching strategy is where real, quantifiable wins come from - mirroring the friend's thesis.",
  ]),
]
