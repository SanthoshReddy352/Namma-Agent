# -*- coding: utf-8 -*-
# Part 1 — setup, helpers, cover, executive summary, problem decomposition
import datetime
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

NAVY = RGBColor(0x1F, 0x38, 0x64)
BLUE = RGBColor(0x2E, 0x74, 0xB5)
GRAY = RGBColor(0x59, 0x59, 0x59)
LIGHT = "DCE6F1"
NAVY_H = "1F3864"
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

OUT = r"C:\Users\santh\Desktop\research.docx"

doc = Document()

normal = doc.styles["Normal"]
normal.font.name = "Calibri"
normal.font.size = Pt(10.5)
normal.paragraph_format.space_after = Pt(6)
normal.paragraph_format.line_spacing = 1.15
normal.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")

for name, size, color, before, after in [
    ("Heading 1", 16, NAVY, 14, 6),
    ("Heading 2", 13, BLUE, 12, 4),
    ("Heading 3", 11.5, NAVY, 10, 3),
]:
    st = doc.styles[name]
    st.font.name = "Calibri"
    st.font.size = Pt(size)
    st.font.bold = True
    st.font.color.rgb = color
    st.paragraph_format.space_before = Pt(before)
    st.paragraph_format.space_after = Pt(after)
    st.paragraph_format.keep_with_next = True

for section in doc.sections:
    section.top_margin = Cm(2.1)
    section.bottom_margin = Cm(2.0)
    section.left_margin = Cm(2.2)
    section.right_margin = Cm(2.2)

def shade_paragraph(p, hexfill):
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hexfill)
    pPr.append(shd)

def shade_cell(cell, hexfill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:fill"), hexfill)
    tcPr.append(shd)

def hrule(p, color="2E74B5", sz="12"):
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), sz)
    bottom.set(qn("w:space"), "6")
    bottom.set(qn("w:color"), color)
    pBdr.append(bottom)
    pPr.append(pBdr)

def add_hyperlink(paragraph, url, text, size=9.5, color="0563C1"):
    part = paragraph.part
    r_id = part.relate_to(url, "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink", is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    new_run = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    rFonts = OxmlElement("w:rFonts")
    rFonts.set(qn("w:ascii"), "Calibri")
    rFonts.set(qn("w:hAnsi"), "Calibri")
    rPr.append(rFonts)
    sz = OxmlElement("w:sz")
    sz.set(qn("w:val"), str(int(size * 2)))
    rPr.append(sz)
    col = OxmlElement("w:color")
    col.set(qn("w:val"), color)
    rPr.append(col)
    u = OxmlElement("w:u")
    u.set(qn("w:val"), "single")
    rPr.append(u)
    new_run.append(rPr)
    t = OxmlElement("w:t")
    t.text = text
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)

def meta_par(text, links=()):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(6)
    shade_paragraph(p, LIGHT)
    r = p.add_run(text)
    r.font.size = Pt(9)
    r.font.italic = True
    r.font.color.rgb = GRAY
    for label, url in links:
        p.add_run("   ").font.size = Pt(9)
        add_hyperlink(p, url, label, size=9)
    return p

def bullets(items, style="List Bullet", size=10.5):
    for it in items:
        p = doc.add_paragraph(style=style)
        p.paragraph_format.space_after = Pt(3)
        r = p.add_run(it)
        r.font.size = Pt(size)

def numbered(items, size=10.5):
    for i, it in enumerate(items, 1):
        p = doc.add_paragraph()
        p.paragraph_format.space_after = Pt(4)
        r = p.add_run(str(i) + ".  ")
        r.bold = True
        r.font.size = Pt(size)
        r.font.color.rgb = BLUE
        r = p.add_run(it)
        r.font.size = Pt(size)

def add_paper(title, meta, links, findings, helps):
    doc.add_heading(title, level=3)
    meta_par(meta, links)
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run("Key findings")
    r.bold = True
    r.font.size = Pt(10.5)
    r.font.color.rgb = BLUE
    bullets(findings)
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run("How it helps your paper")
    r.bold = True
    r.font.size = Pt(10.5)
    r.font.color.rgb = NAVY
    bullets(helps)
    doc.add_paragraph()

# footer with page number
footer = doc.sections[0].footer
fp = footer.paragraphs[0]
fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = fp.add_run("Literature Review — Algorithmic Batching of Spaced-Repetition Computations  ·  Page ")
run.font.size = Pt(8)
run.font.color.rgb = GRAY
fld = OxmlElement("w:fldSimple")
fld.set(qn("w:instr"), "PAGE")
rEl = OxmlElement("w:r")
rPr = OxmlElement("w:rPr")
sz = OxmlElement("w:sz")
sz.set(qn("w:val"), "16")
rPr.append(sz)
rEl.append(rPr)
fld.append(rEl)
fp._p.append(fld)

# ================= COVER
for _ in range(5):
    doc.add_paragraph()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("LITERATURE REVIEW  ·  RESEARCH FOUNDATIONS")
r.font.size = Pt(11)
r.font.bold = True
r.font.color.rgb = BLUE

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Algorithmic Batching of Spaced-Repetition Computations")
r.font.size = Pt(21)
r.font.bold = True
r.font.color.rgb = NAVY

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Maximizing CPU Throughput and Minimizing Idle Latency\nin Dynamic Knowledge Graphs")
r.font.size = Pt(14)
r.font.color.rgb = GRAY

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
hrule(p, color="2E74B5", sz="16")

p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
p.paragraph_format.space_before = Pt(10)
r = p.add_run("A curated set of 11 papers — links, findings, and a map of how each one\nhelps you design and defend your solution")
r.font.size = Pt(11)
r.font.color.rgb = GRAY
r.font.italic = True

for _ in range(3):
    doc.add_paragraph()
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Prepared for:  the author's research project")
r.font.size = Pt(10)
r.font.color.rgb = NAVY
p = doc.add_paragraph()
p.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = p.add_run("Prepared by:  Namma Agent   ·   " + datetime.date.today().strftime("%d %B %Y"))
r.font.size = Pt(10)
r.font.color.rgb = NAVY

doc.add_page_break()

# ================= 1. EXECUTIVE SUMMARY
doc.add_heading("1.  Executive Summary", level=1)
doc.add_paragraph(
    "Your paper sits at the intersection of three bodies of work. First, spaced-repetition "
    "scheduling research tells you what has to be computed: predicting each item's memory state "
    "(recall probability, half-life) and updating its next review time. Second, dynamic knowledge-graph "
    "research tells you how those computations should behave when the graph itself is evolving — new "
    "concepts, new prerequisite links, expired items — so that only affected regions are recomputed. "
    "Third, systems and scheduling research (serving systems, batching policies, queueing theory) tells "
    "you how to execute those computations efficiently: grouping work into batches so the CPU is kept "
    "busy and idle latency is minimized."
)
doc.add_paragraph(
    "The gap this review makes visible: nobody treats spaced-repetition computations as a batching "
    "workload. The scheduling papers optimize what to compute; the graph papers optimize how to update "
    "incrementally; the batching papers optimize throughput and latency but for ML inference, not memory "
    "scheduling. Your contribution — an algorithmic batching layer over SR computations on a dynamic "
    "knowledge graph — is genuinely novel, and each paper below gives you a technique, a baseline, or "
    "an argument to build it."
)
doc.add_paragraph(
    "The 11 papers are grouped in three layers (Scheduling & Memory Models, Dynamic Knowledge Graphs, "
    "Batching & Serving Systems). Each entry lists the key findings, the links, and — most importantly — "
    "how the paper aligns with your problem statement and what to borrow from it. A comparison table and "
    "a suggested reading order close the document."
)

# ================= 2. PROBLEM DECOMPOSITION
doc.add_heading("2.  The Problem, Decomposed Into Three Layers", level=1)
doc.add_paragraph("A good literature map starts by decomposing the title into the questions each layer answers.")

tbl = doc.add_table(rows=4, cols=3)
tbl.style = "Table Grid"
tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
headers = ["Layer", "The question it answers", "Papers that answer it"]
rows = [
    ("Scheduling & Memory Models",
     "What computations must run — recall prediction, interval updates, retention-optimal scheduling — and what a single 'schedule update' costs.",
     "Ye et al. (FSRS) · Su et al. (TKDE) · Tabibian et al. (MEMORIZE) · Reddy et al. · Settles & Meeder (HLR) · Wozniak (SM-2)"),
    ("Dynamic Knowledge Graphs",
     "When the graph mutates (new concepts, links, expirations), how do we recompute only the affected items instead of the whole graph?",
     "Wu et al. (DKGE) · Mariappan & Vora (GraphBolt) · Vora et al. (KickStarter)"),
    ("Batching & Serving Systems",
     "How do we group computations so the CPU stays busy, idle latency shrinks, and batch size adapts to load — while meeting quality targets?",
     "Pang et al. (dynamic batching) · Yu et al. (Orca)"),
]
widths = [Cm(3.6), Cm(6.6), Cm(6.4)]
for j, h in enumerate(headers):
    c = tbl.rows[0].cells[j]
    c.text = ""
    p = c.paragraphs[0]
    r = p.add_run(h)
    r.bold = True
    r.font.size = Pt(9.5)
    r.font.color.rgb = WHITE
    shade_cell(c, NAVY_H)
    c.width = widths[j]
for i, row in enumerate(rows, 1):
    for j, val in enumerate(row):
        c = tbl.rows[i].cells[j]
        c.text = ""
        p = c.paragraphs[0]
        r = p.add_run(val)
        r.font.size = Pt(9)
        if j == 0:
            r.bold = True
            r.font.color.rgb = NAVY
        if i % 2 == 0:
            shade_cell(c, "F2F6FB")
        c.width = widths[j]
doc.add_paragraph()

# Part 2 — section 3.1: scheduling & memory models (6 papers)
doc.add_heading("3.  The Papers", level=1)
doc.add_heading("3.1  Scheduling & Memory Models — what to compute", level=2)

add_paper(
    title="A Stochastic Shortest Path Algorithm for Optimizing Spaced Repetition Scheduling (FSRS / SSP-MMC)",
    meta="Junyao Ye, Jingyong Su, Yilong Cao · ACM SIGKDD 2022 · DOI 10.1145/3534678.3539081",
    links=[("Paper", "https://www.maimemo.com/paper/"), ("GitHub + code", "https://github.com/maimemo/SSP-MMC")],
    findings=[
        "Built a memory model with the Markov property from 220 million real student memory-behaviour logs collected from MaiMemo, a production language-learning app.",
        "Formulated review scheduling as a stochastic shortest path (SSP) problem on a Markov chain, producing a scheduler that provably minimizes expected total review cost for a given retention target.",
        "Reports a 12.6% improvement over state-of-the-art schedulers; the algorithm (FSRS) is now the default scheduler in Anki.",
        "Everything is open: the C++ scheduler, the Python memory model, the simulator, and a 1.6 GB dataset of 220M reviews (Dataverse).",
    ],
    helps=[
        "Defines the exact per-item computation your batching layer must execute: recall prediction (DHP model) + interval/state update + policy lookup. This is the 'workload' your paper batches.",
        "The open code and dataset give you a realistic benchmark bed — you can measure the CPU cost of a schedule update and prove that batched execution preserves the scheduler's retention guarantees.",
        "FSRS is the current SOTA baseline. Any credible paper in this space must cite it and benchmark against it.",
    ],
)

add_paper(
    title="Optimizing Spaced Repetition Schedule by Capturing the Dynamics of Memory",
    meta="Jingyong Su, Junyao Ye, et al. · IEEE Transactions on Knowledge and Data Engineering (TKDE), 2023 · DOI 10.1109/TKDE.2023.3251721",
    links=[("IEEE Xplore", "https://ieeexplore.ieee.org/document/10059206/")],
    findings=[
        "Journal extension of the FSRS line of work: proposes a framework that alternates memory prediction (modelling the dynamics of memory) with schedule optimization, showing the two must be coupled.",
        "Argues that methods which only predict memory, or only optimize schedules, leave retention efficiency on the table; the alternation framework improves long-term retention efficiency.",
        "Establishes the standard vocabulary: half-life, forgetting curves, review-state transitions, retention targets.",
    ],
    helps=[
        "Supplies the memory-dynamics modelling layer that determines the compute graph your batching operates on — what state each item carries and how it transitions after every review.",
        "Positioning: your contribution is orthogonal — an execution/systems layer that can sit underneath any such predict-and-optimize scheduler.",
        "A good place to borrow evaluation methodology: retention efficiency vs. number of reviews, on large real traces.",
    ],
)

add_paper(
    title="Enhancing Human Learning via Spaced Repetition Optimization (MEMORIZE)",
    meta="Behzad Tabibian, Utkarsh Upadhyay, Abir De, Ali Zarezade, Bernhard Schölkopf, Manuel Gomez-Rodriguez · PNAS 116(10), 2019 · DOI 10.1073/pnas.1815156116",
    links=[("PNAS", "https://www.pnas.org/doi/10.1073/pnas.1815156116"), ("PMC (free)", "https://pmc.ncbi.nlm.nih.gov/articles/PMC6410796/"), ("Code", "https://github.com/Networks-Learning/memorize")],
    findings=[
        "Represents spaced repetition with marked temporal point processes and casts schedule design as an optimal-control problem for stochastic differential equations with jumps.",
        "Key theoretical result: to maximize recall probability subject to a cost on reviewing frequency, the optimal reviewing schedule is given by the recall probability itself — yielding a simple, scalable online algorithm (MEMORIZE).",
        "Validated with a large-scale natural experiment on Duolingo: learners following MEMORIZE schedules memorize more effectively than learners on several heuristic schedules.",
    ],
    helps=[
        "Gives you the principled 'what to compute': per-item recall thresholds are cheap and trivially batchable — a strong theoretical base for your throughput claims.",
        "The optimal-control/point-process framing is ideal for your Related Work section's motivation: from optimal schedules (theory) to efficient execution (your paper).",
        "Because MEMORIZE is online and per-item, it is the cleanest example of a scheduler whose per-item computations you can batch and show idle-latency reduction on.",
    ],
)

add_paper(
    title="Unbounded Human Learning: Optimal Scheduling for Spaced Repetition",
    meta="Siddharth Reddy, Igor Labutov, Siddhartha Banerjee, Thorsten Joachims · ACM SIGKDD 2016 · arXiv:1602.07032",
    links=[("arXiv", "https://arxiv.org/abs/1602.07032"), ("DOI", "https://doi.org/10.1145/2939672.2939850")],
    findings=[
        "Mined flashcard-system logs to establish the functional dependence of retention on reinforcement and delay.",
        "Proposed a queueing-network model of the Leitner system for reviewing flashcards, plus a tractable heuristic approximation for review scheduling.",
        "Verified by a Mechanical Turk experiment, including the key qualitative prediction: a sharp phase transition in learning outcomes as the rate of new-item introductions increases.",
    ],
    helps=[
        "This is the paper that treats spaced repetition as a queueing system — exactly your 'CPU throughput' angle. Reviews arrive as stochastic demand; the scheduler is a server; batch size and queue occupancy interact.",
        "The phase-transition result motivates capacity/throughput analysis in your paper: what happens when review demand spikes and your batch buffers grow?",
        "A key citation for modelling review-arrival processes and for arguing your scheduler's throughput under load.",
    ],
)

add_paper(
    title="A Trainable Spaced Repetition Model for Language Learning (Half-Life Regression, HLR)",
    meta="Burr Settles, Brendan Meeder · ACL 2016 · DOI 10.18653/v1/P16-1174",
    links=[("ACL Anthology", "https://aclanthology.org/P16-1174/"), ("PDF", "https://research.duolingo.com/papers/settles.acl16.pdf"), ("Data + code", "https://github.com/duolingo/halflife-regression")],
    findings=[
        "Half-life regression: recall probability follows the Ebbinghaus curve p = 2^(−Δ/h) with half-life h = 2^(Θ·x), where x is a feature vector of the learner's history; weights Θ are trained by SGD/AdaGrad on log data.",
        "Generalizes the Pimsleur and Leitner schedules as special cases with fixed hand-picked weights.",
        "On 12.9 million Duolingo traces it cut prediction error (MAE) by 45%+ versus Leitner/Pimsleur baselines, and in a production A/B test improved daily student engagement by 12%.",
        "The dataset and code are public — one of the few large SR datasets researchers can download.",
    ],
    helps=[
        "The per-item prediction is a tiny dot product — the textbook case for batching: one vectorized matrix multiply over a batch of feature vectors replaces N scalar calls. This is the core of your CPU-throughput argument.",
        "The public Duolingo dataset lets you measure actual per-item compute cost and demonstrate batched vs. per-item wall-clock timings.",
        "The +12% engagement result gives you the user-facing justification: idle latency isn't just a CPU concern, it directly affects the learner experience.",
    ],
)

add_paper(
    title="SuperMemo SM-2 — the classic algorithm (background)",
    meta="Piotr Woźniak · SuperMemo, 1987 (master's thesis, 1990) · public algorithm description",
    links=[("Algorithm SM-2", "https://supermemo.guru/wiki/Algorithm_SM-2")],
    findings=[
        "The first widely deployed spaced-repetition algorithm: hand-tuned easiness factor plus integer interval arithmetic, adjusted on each review.",
        "Heuristic rather than optimized; served as the default Anki scheduler for roughly 15 years before FSRS.",
        "Established the canonical 'one card → one small arithmetic computation per review' pattern that modern systems scale up.",
    ],
    helps=[
        "The historical baseline for your Introduction and Motivation: from hand-tuned heuristics (SM-2) to algorithmic optimization (FSRS) to execution optimization (your paper).",
        "Shows the per-item compute pattern your batching scales: even a single arithmetic operation per item, executed per-item, wastes cycles — batching amortizes dispatch, cache misses, and scheduling overhead.",
    ],
)

# Part 3 — sections 3.2, 3.3, comparison table, reading order, positioning, references
doc.add_heading("3.2  Dynamic Knowledge Graphs — where the computation lives", level=2)

add_paper(
    title="Efficiently Embedding Dynamic Knowledge Graphs (DKGE)",
    meta="Tianxing Wu, Arijit Khan, Melvin Yong, Guilin Qi, Meng Wang · Knowledge-Based Systems, 2022 · arXiv:1910.06708",
    links=[("arXiv", "https://arxiv.org/abs/1910.06708"), ("DOI", "https://doi.org/10.1016/j.knosys.2022.109124")],
    findings=[
        "A dynamic knowledge-graph embedding method with two representations per entity/relation — knowledge embedding and contextual element embedding — learned with two attentive GCNs, a gate strategy, and translation operations.",
        "An online learning algorithm confines the impact of a KG update to local regions, so the embedding can be refreshed quickly without retraining the whole graph; it can also learn from scratch.",
        "Competitive effectiveness on link prediction and question answering in dynamic environments, with large efficiency gains versus static retraining.",
    ],
    helps=[
        "Directly addresses your 'dynamic knowledge graphs': when the graph changes, only a local neighbourhood needs recomputation. Your batching layer can use the same locality principle — recompute SR state only for items whose neighbourhood changed.",
        "Gives you the evaluation protocol for dynamic settings (snapshot-based link prediction over evolving graphs).",
        "A related-work anchor for the graph side of your title — the embedding world's answer to 'incremental computation on a changing graph'.",
    ],
)

add_paper(
    title="GraphBolt: Dependency-Driven Synchronous Processing of Streaming Graphs",
    meta="Mugilan Mariappan, Keval Vora · EuroSys 2019 · DOI 10.1145/3302424.3303974",
    links=[("GitHub", "https://github.com/pdclab/graphbolt"), ("DOI", "https://doi.org/10.1145/3302424.3303974")],
    findings=[
        "First streaming-graph system to guarantee BSP (bulk synchronous parallel) semantics while doing incremental computation over batches of structural mutations.",
        "Dependency-driven processing: tracks how each intermediate value was computed, then propagates only the impact of the change across intermediate values; provides a generalized incremental programming model.",
        "Delivers order-of-magnitude speedups over recomputation from scratch on evolving-graph workloads, across a wide variety of graph analytics.",
    ],
    helps=[
        "This is your systems blueprint: treat a batch of KG mutations (new concepts, new prerequisite links, expired items) as one update unit, then incrementally re-propagate only the affected SR state.",
        "Dependency tracking is exactly what a batched SR scheduler needs — it tells you which items' intervals depend on which graph regions, so you can decide what must recompute and what can be reused.",
        "A strong systems citation showing that batching updates (mutation batches) is standard practice in dynamic-graph processing.",
    ],
)

add_paper(
    title="KickStarter: Fast and Accurate Computations on Streaming Graphs via Trimmed Approximations",
    meta="Keval Vora, Rajiv Gupta, Guoqing Xu · ASPLOS 2017 · DOI 10.1145/3037697.3037748",
    links=[("ACM", "https://dl.acm.org/doi/10.1145/3037697.3037748")],
    findings=[
        "Introduces 'trimmed approximations': detects updates whose impact on results is negligible and skips their recomputation, using event-based scheduling and monotonicity detection.",
        "Keeps results fast and accurate — within a bounded error — on evolving graphs for algorithms like PageRank and SSSP, with large speedups over prior streaming systems and over recompute-from-scratch.",
        "Established the accuracy/throughput trade-off as a first-class design axis for dynamic-graph computation.",
    ],
    helps=[
        "Error-bounded skipping is your lever for trading accuracy against throughput: when batch sizes grow, decide which SR recomputations are safe to merge, defer, or skip entirely under a retention-error budget.",
        "Pairs with GraphBolt in your related work: precision (GraphBolt) vs. speed-with-bounded-error (KickStarter) defines the design space your batching policy occupies.",
        "A ready citation for the idea that approximation is a legitimate, principled way to keep a dynamic computation fast.",
    ],
)

doc.add_heading("3.3  Batching & Serving Systems — how to compute fast", level=2)

add_paper(
    title="Optimizing LLM Inference Throughput via Memory-aware and SLA-constrained Dynamic Batching",
    meta="Bowen Pang, Kai Li, Feifan Wang · arXiv:2503.05248, 2025",
    links=[("arXiv", "https://arxiv.org/abs/2503.05248")],
    findings=[
        "Shows that static batching wastes throughput and cannot adapt to changing conditions; proposes a memory-aware batch scheduler plus an SLA-constrained latency feedback mechanism that resizes batches in real time.",
        "Reports throughput gains of 8–28% and capacity improvements of ~22% versus static batching, while remaining compatible with existing inference infrastructure.",
        "Treats batch size as a control variable tuned online, not a fixed hyper-parameter.",
    ],
    helps=[
        "The most direct reference for adaptive batch sizing with latency constraints — your SR batching control loop can mirror this design: monitor load, adjust batch size, and meet a retention 'SLA'.",
        "Fresh (2025) citation that anchors the systems contribution of your paper.",
        "Provides the throughput/batch-size/latency interplay you can reuse in your own analysis and experiments.",
    ],
)

add_paper(
    title="Orca: A Distributed Serving System for Transformer-Based Generative Models",
    meta="Gyeong-In Yu, Joo Seong Jeong, Geon-Woo Kim, Soojeong Kim, Byung-Gon Chun · USENIX OSDI 2022",
    links=[("USENIX (open access)", "https://www.usenix.org/conference/osdi22/presentation/yu")],
    findings=[
        "Identifies the core inefficiency of request-level batching in serving: finished requests block the batch from returning and new requests must wait — creating idle bubbles.",
        "Introduces iteration-level scheduling ('continuous batching'): the scheduler runs only one model iteration per step, so batch membership can change at every step; selective batching applies batching only where it helps.",
        "Achieves a 36.9x throughput improvement over NVIDIA FasterTransformer at the same latency on a GPT-3 175B model.",
    ],
    helps=[
        "The canonical 'minimize idle latency by choosing the right batching granularity' paper. For SR: batch at the granularity of memory-state updates rather than whole per-item recomputations — finished items leave the batch immediately, new ones join, and idle time approaches zero.",
        "Gives you the argument template for your evaluation section: baseline = fixed batch; contribution = adaptive/continuous batching; metric = throughput at equal latency (and vice versa).",
        "A heavyweight systems citation that makes your idle-latency motivation credible to a systems audience.",
    ],
)

# ================= 4. COMPARISON TABLE
doc.add_heading("4.  At-a-Glance Comparison Table", level=1)
doc.add_paragraph("Use this as your quick-reference map while writing the Related Work section.")

ct = doc.add_table(rows=12, cols=5)
ct.style = "Table Grid"
ct.alignment = WD_TABLE_ALIGNMENT.CENTER
chead = ["Paper (short)", "Layer", "Core idea", "Headline result", "Directly reusable"]
cwidths = [Cm(3.4), Cm(2.3), Cm(4.3), Cm(3.6), Cm(3.0)]
for j, h in enumerate(chead):
    c = ct.rows[0].cells[j]
    c.text = ""
    p = c.paragraphs[0]
    r = p.add_run(h)
    r.bold = True
    r.font.size = Pt(9)
    r.font.color.rgb = WHITE
    shade_cell(c, NAVY_H)
    c.width = cwidths[j]
comp_rows = [
    ("FSRS / SSP-MMC", "Scheduling", "SSP-minimized review cost over a Markov memory model", "12.6% over SOTA; deployed; open code + 220M logs", "Scheduler, dataset, simulator"),
    ("TKDE 2023 (Su et al.)", "Scheduling", "Alternating memory prediction + schedule optimization", "Improved long-term retention efficiency", "Framework & vocabulary"),
    ("MEMORIZE (PNAS)", "Scheduling", "Optimal control; recall-probability threshold policy", "Better memorization in a Duolingo natural experiment", "Theory + simple online rule"),
    ("Unbounded Learning", "Scheduling", "Queueing-network model of the Leitner system", "MTurk-verified phase transition", "Arrival-process modelling"),
    ("HLR (ACL 2016)", "Memory model", "Trainable half-life regression (Ebbinghaus curve)", "45%+ lower MAE; +12% engagement", "Public dataset + code"),
    ("SM-2 (1987)", "Memory model", "Classic hand-tuned interval heuristics", "Industry standard for decades", "Historical baseline"),
    ("DKGE", "Dynamic KG", "Online embedding with local, gated updates", "Fast updates, strong link prediction", "Locality principle, eval protocol"),
    ("GraphBolt", "Dynamic KG", "Dependency-driven incremental processing with BSP", "Order-of-magnitude speedups", "Mutation-batch abstraction"),
    ("KickStarter", "Dynamic KG", "Trimmed approximations; skip negligible updates", "Bounded-error large speedups", "Accuracy–throughput trade-off"),
    ("Dynamic batching (2025)", "Systems", "Memory-aware, SLA-constrained adaptive batch size", "8–28% more throughput, 22% capacity", "Control-loop design"),
    ("Orca (OSDI 22)", "Systems", "Iteration-level continuous batching", "36.9x throughput vs FasterTransformer", "Idle-latency elimination"),
]
for i, row in enumerate(comp_rows, 1):
    for j, val in enumerate(row):
        c = ct.rows[i].cells[j]
        c.text = ""
        p = c.paragraphs[0]
        r = p.add_run(val)
        r.font.size = Pt(8.5)
        if j == 0:
            r.bold = True
            r.font.color.rgb = NAVY
        if i % 2 == 0:
            shade_cell(c, "F2F6FB")
        c.width = cwidths[j]
doc.add_paragraph()

# ================= 5. READING ORDER
doc.add_heading("5.  Suggested Reading Order", level=1)
doc.add_paragraph("Read in four phases so each paper builds on the previous one:")
numbered([
    "Phase 1 — The computation you will batch. Read HLR (Settles & Meeder) first: it defines the per-item recall prediction and gives you a public dataset. Then FSRS (Ye et al.): the modern SOTA scheduler, its cost model, and the open simulator. Optionally the TKDE journal version for the predict-and-optimize framing.",
    "Phase 2 — Theory and the workload lens. MEMORIZE (Tabibian et al.) for optimal-scheduling theory; Reddy et al. for the queueing view of review demand (this is your throughput vocabulary); SM-2 as the historical baseline.",
    "Phase 3 — The dynamic graph substrate. DKGE for locality of updates in a knowledge graph, then GraphBolt (dependency-driven incremental recompute) and KickStarter (error-bounded trimming) for the systems techniques on evolving graphs.",
    "Phase 4 — The batching systems layer. Orca for fine-grained (iteration-level) batching that kills idle latency, then the 2025 dynamic-batching paper for adaptive batch sizing under constraints.",
])

# ================= 6. POSITIONING
doc.add_heading("6.  Positioning Your Contribution (gap analysis)", level=1)
p = doc.add_paragraph()
p.paragraph_format.space_after = Pt(4)
r = p.add_run("The gap: ")
r.bold = True
r.font.color.rgb = NAVY
bullets([
    "The SR literature optimizes the schedule (what to compute) but assumes each computation is trivially cheap and executed per-item, one at a time.",
    "The dynamic-KG literature handles structural change efficiently (incremental, local, bounded-error) but not the batching of many small per-item computations for CPU efficiency.",
    "The serving-systems literature perfects batching for ML inference but has never considered spaced-repetition scheduling as a workload.",
    "Your novelty: an algorithmic batching layer — batch-formation policies, incremental recompute over a dynamic KG, and adaptive batch sizing — with CPU throughput and idle latency as first-class metrics, evaluated against retention fidelity.",
])
doc.add_paragraph(
    "Suggested evaluation recipe for your paper: take an SR model (FSRS or HLR) as the compute unit; "
    "a dynamic KG (synthetic mutations, or real traces — MaiMemo's 220M-log dataset or Duolingo's public "
    "data); then compare per-item execution, fixed-batch execution, and adaptive/continuous batching "
    "(GraphBolt-style incremental recompute plus an Orca-style fine-grained batch policy). Metrics: "
    "schedule-updates per second (throughput), p50/p95 idle and response latency, and retention fidelity "
    "(how close the batched scheduler's recall stays to the unbatched one). That design is exactly what "
    "the literature above leaves open — and it makes a clean, defensible contribution."
)

# ================= REFERENCES
doc.add_heading("7.  Full Reference List", level=1)
refs = [
    ("Ye, J., Su, J., Cao, Y. (2022). A Stochastic Shortest Path Algorithm for Optimizing Spaced Repetition Scheduling. KDD 2022.", "https://www.maimemo.com/paper/", "github.com/maimemo/SSP-MMC"),
    ("Su, J., Ye, J., et al. (2023). Optimizing Spaced Repetition Schedule by Capturing the Dynamics of Memory. IEEE TKDE.", "https://ieeexplore.ieee.org/document/10059206/", ""),
    ("Tabibian, B., et al. (2019). Enhancing Human Learning via Spaced Repetition Optimization. PNAS 116(10): 3988–3993.", "https://www.pnas.org/doi/10.1073/pnas.1815156116", ""),
    ("Reddy, S., Labutov, I., Banerjee, S., Joachims, T. (2016). Unbounded Human Learning: Optimal Scheduling for Spaced Repetition. KDD 2016.", "https://arxiv.org/abs/1602.07032", ""),
    ("Settles, B., Meeder, B. (2016). A Trainable Spaced Repetition Model for Language Learning. ACL 2016.", "https://aclanthology.org/P16-1174/", "github.com/duolingo/halflife-regression"),
    ("Woźniak, P. (1987/1990). SuperMemo SM-2 algorithm description.", "https://supermemo.guru/wiki/Algorithm_SM-2", ""),
    ("Wu, T., Khan, A., Yong, M., Qi, G., Wang, M. (2022). Efficiently Embedding Dynamic Knowledge Graphs. Knowledge-Based Systems.", "https://arxiv.org/abs/1910.06708", ""),
    ("Mariappan, M., Vora, K. (2019). GraphBolt: Dependency-Driven Synchronous Processing of Streaming Graphs. EuroSys 2019.", "https://github.com/pdclab/graphbolt", ""),
    ("Vora, K., Gupta, R., Xu, G. (2017). KickStarter: Fast and Accurate Computations on Streaming Graphs via Trimmed Approximations. ASPLOS 2017.", "https://dl.acm.org/doi/10.1145/3037697.3037748", ""),
    ("Pang, B., Li, K., Wang, F. (2025). Optimizing LLM Inference Throughput via Memory-aware and SLA-constrained Dynamic Batching.", "https://arxiv.org/abs/2503.05248", ""),
    ("Yu, G.-I., Jeong, J. S., Kim, G.-W., Kim, S., Chun, B.-G. (2022). Orca: A Distributed Serving System for Transformer-Based Generative Models. OSDI 2022.", "https://www.usenix.org/conference/osdi22/presentation/yu", ""),
]
for i, (txt, url, extra) in enumerate(refs, 1):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(3)
    r = p.add_run(str(i) + ".  ")
    r.bold = True
    r.font.size = Pt(9)
    r.font.color.rgb = BLUE
    r = p.add_run(txt)
    r.font.size = Pt(9)
    add_hyperlink(p, url, "  [link]", size=9)
    if extra:
        add_hyperlink(p, "https://" + extra, "  [" + extra + "]", size=9)

doc.save(OUT)
print("SAVED:", OUT)
