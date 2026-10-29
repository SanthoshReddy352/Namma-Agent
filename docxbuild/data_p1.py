# -*- coding: utf-8 -*-
"""Pillar 1 - Spaced-Repetition Scheduling & Memory Modeling."""

PAPERS1 = [
 dict(
  title="A Stochastic Shortest Path Algorithm for Optimizing Spaced Repetition Scheduling",
  authors="Junyao Ye, Jingyong Su, Yilong Cao",
  venue="ACM SIGKDD 2022 (FSRS-4)", year="2022",
  link="https://doi.org/10.1145/3534678.3539081", link_label="doi.org/10.1145/3534678.3539081",
  summary=("The foundational FSRS paper. The authors collected 220 million review logs with time-series features and "
           "built a memory model with the Markov property (difficulty, stability, retrievability). They cast "
           "spaced-repetition scheduling as a Stochastic Shortest Path (SSP) problem - finding the review schedule "
           "that minimizes expected review cost for a target recall level - and solve it with a guaranteed-optimal "
           "scheduler. The system is deployed in the MaiMemo app, serving millions of students."),
  findings=[
   "SSP formulation: the scheduler is guaranteed to minimize review cost, unlike the rule-based heuristics of Anki's SM-2.",
   "12.6% improvement in review efficiency over state-of-the-art methods at the time.",
   "Memory model uses the Markov property over time-series logs - the recall/stability state is exactly the per-item state a batch scheduler must update.",
   "Open-sourced as FSRS; adopted by Anki (2023) and other flashcard platforms - the de facto industry baseline.",
  ],
  align=[
   "This is the computation that gets batched in your friend's paper: per review, predict recall, update difficulty/stability, compute next interval. Cite it as the per-item baseline your batching preserves.",
   "FSRS optimizes one card at a time (item-wise SSP). Nothing in the paper considers grouping reviews to improve CPU utilization - that is exactly the gap to claim.",
   "Use FSRS as the reference implementation for correctness and as a performance baseline in experiments.",
  ]),
 dict(
  title="Optimizing Spaced Repetition Schedule by Capturing the Dynamics of Memory",
  authors="Jingyong Su, Junyao Ye, Liqiang Nie, Yilong Cao, Yongyong Chen",
  venue="IEEE TKDE 2023 (FSRS-6)", year="2023",
  link="https://doi.org/10.1109/TKDE.2023.3251721", link_label="doi.org/10.1109/TKDE.2023.3251721",
  summary=("The journal extension of FSRS (FSRS-6). It treats the spaced-repetition system as a whole: the framework "
           "alternates between memory prediction (an RNN-based model over review logs) and schedule optimization (SSP "
           "solved by value iteration). It also releases the first public benchmark dataset with time-series memory "
           "behavior - 220 million rows - making results reproducible."),
  findings=[
   "Alternating prediction + optimization framework improves recall prediction error by 64% and reduces review cost by 17% vs baselines.",
   "Provides the largest public spaced-repetition dataset (220M rows, time-series) - the standard evaluation resource for this area.",
   "The RNN memory model means each review update is a small neural inference - a non-trivial per-item computation, ideal motivation for batching.",
  ],
  align=[
   "The 220M-row dataset (SSP-MMC-Plus) is the natural benchmark for your friend's experiments: batch throughput and latency can be measured on real review workloads.",
   "Because FSRS-6's per-item updates are neural inferences, batching them amortizes fixed costs (kernel launches, memory allocation, Python overhead) - a concrete, measurable speedup story.",
   "Cite FSRS-6 as the state of the art your batching layer sits on top of - it is the strongest 'unbatched baseline'.",
  ]),
 dict(
  title="Enhancing Human Learning via Spaced Repetition Optimization",
  authors="Behzad Tabibian, Utkarsh Upadhyay, Abir De, Ali Zarezade, Bernhard Scholkopf, Manuel Gomez-Rodriguez",
  venue="PNAS 2019 (MEMORIZE)", year="2019",
  link="https://doi.org/10.1073/pnas.1815156116", link_label="doi.org/10.1073/pnas.1815156116",
  summary=("A theory-first paper. It models spaced repetition with marked temporal point processes and frames schedule "
           "design as an optimal control problem for stochastic differential equations with jumps. For two classic "
           "human memory models, the authors prove the optimal review schedule is a threshold on recall probability "
           "itself. They implement this as MEMORIZE, a simple online algorithm, and validate it in a large natural "
           "experiment on Duolingo."),
  findings=[
   "Theoretically proven optimal policy: review an item exactly when its recall probability crosses a threshold - no heuristics needed.",
   "MEMORIZE is online and scalable (O(1) per event), unlike heavy optimization at schedule time.",
   "Duolingo experiment: learners following MEMORIZE schedules memorized more effectively than learners on several heuristics.",
  ],
  align=[
   "This paper gives the theoretical yardstick for 'optimal': your friend can argue that batching preserves (or approximates) the recall-threshold policy - it only reorders work across items, never changing each item's schedule.",
   "The optimal-control framing (cost vs recall trade-off) is the same objective a batch scheduler must respect: batch waiting adds latency, but the schedule semantics stay intact.",
   "Good citation for Related Work to show the field's optimization lineage, from theory (PNAS) to systems (your friend's paper).",
  ]),
 dict(
  title="DAS3H: Modeling Student Learning and Forgetting for Optimally Scheduling Distributed Practice of Skills",
  authors="Benoit Choffin, Fabrice Popineau, Yolaine Bourda, Jill-Jenn Vie",
  venue="EDM 2019 (best-paper invited)", year="2019",
  link="https://arxiv.org/abs/1905.06873", link_label="arxiv.org/abs/1905.06873",
  summary=("DAS3H extends spaced repetition from pure flashcards to skills composed of multiple knowledge components. "
           "It builds on additive factor models and explicitly represents the temporal distribution of past practice "
           "over the skills an item touches, letting learning and forgetting curves differ per skill. This item-skill "
           "structure is effectively a knowledge graph (the q-matrix), making DAS3H the natural bridge between memory "
           "modeling and graph-structured knowledge."),
  findings=[
   "Combines knowledge tracing (item-skill relations) with forgetting curves - outperforms state-of-the-art EDM models on three real datasets.",
   "Shows that scheduling quality depends on the structure between items and skills, not just per-item history.",
   "Demonstrates adaptive, personalized scheduling is possible for multi-skill content, not only single flashcards.",
  ],
  align=[
   "The q-matrix is a knowledge graph: if your friend's 'dynamic knowledge graph' encodes concepts and their dependencies, DAS3H shows how memory state lives on (item, skill) pairs and how schedule decisions depend on graph edges (e.g., prerequisites).",
   "It motivates why KG structure should influence batching: reviews of dependent concepts can be grouped or ordered by graph locality, turning 'which items to batch' into a graph problem.",
   "Useful citation for the motivation section - spaced repetition is no longer card-isolated; it is graph-structured.",
  ]),
]
