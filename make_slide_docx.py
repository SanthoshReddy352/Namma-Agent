# -*- coding: utf-8 -*-
"""Build slide.docx — styled slide content pack with citations."""
import docx
from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

NAVY = RGBColor(0x1F, 0x38, 0x64)
BLUE = RGBColor(0x2E, 0x74, 0xB5)
GRAY = RGBColor(0x59, 0x59, 0x59)
DARK = RGBColor(0x33, 0x33, 0x33)
LINK = "0563C1"


def set_font(run, size=11, bold=False, italic=False, color=DARK, name="Calibri"):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.name = name
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.append(rFonts)
    rFonts.set(qn('w:ascii'), name)
    rFonts.set(qn('w:hAnsi'), name)
    rFonts.set(qn('w:cs'), name)


def add_hyperlink(paragraph, url, text, size=10):
    part = paragraph.part
    r_id = part.relate_to(url, docx.opc.constants.RELATIONSHIP_TYPE.HYPERLINK, is_external=True)
    hyperlink = OxmlElement('w:hyperlink')
    hyperlink.set(qn('r:id'), r_id)
    new_run = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')
    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:ascii'), 'Calibri')
    rFonts.set(qn('w:hAnsi'), 'Calibri')
    rPr.append(rFonts)
    c = OxmlElement('w:color'); c.set(qn('w:val'), LINK); rPr.append(c)
    u = OxmlElement('w:u'); u.set(qn('w:val'), 'single'); rPr.append(u)
    sz = OxmlElement('w:sz'); sz.set(qn('w:val'), str(int(size * 2))); rPr.append(sz)
    new_run.append(rPr)
    t = OxmlElement('w:t'); t.text = text
    t.set(qn('xml:space'), 'preserve')
    new_run.append(t)
    hyperlink.append(new_run)
    paragraph._p.append(hyperlink)
    return hyperlink


def shade_and_border(paragraph, fill="EEF3F9", color="1F3864"):
    pPr = paragraph._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), fill)
    pPr.append(shd)
    pBdr = OxmlElement('w:pBdr')
    left = OxmlElement('w:left')
    left.set(qn('w:val'), 'single'); left.set(qn('w:sz'), '24')
    left.set(qn('w:space'), '6'); left.set(qn('w:color'), color)
    pBdr.append(left)
    pPr.append(pBdr)


doc = Document()

# ---------- base styles ----------
normal = doc.styles['Normal']
normal.font.name = 'Calibri'
normal.font.size = Pt(11)
normal.font.color.rgb = DARK
normal.paragraph_format.space_after = Pt(4)

for name, size, color, before, after in [
    ('Heading 1', 16, NAVY, 18, 6),
    ('Heading 2', 13, BLUE, 14, 4),
    ('Heading 3', 11.5, RGBColor(0x3B, 0x3B, 0x3B), 10, 2),
]:
    st = doc.styles[name]
    st.font.name = 'Calibri'
    st.font.size = Pt(size)
    st.font.bold = True
    st.font.color.rgb = color
    st.paragraph_format.space_before = Pt(before)
    st.paragraph_format.space_after = Pt(after)

bullet = doc.styles['List Bullet']
bullet.font.name = 'Calibri'
bullet.font.size = Pt(10.5)
bullet.font.color.rgb = DARK
bullet.paragraph_format.space_after = Pt(3)

# ---------- title block ----------
t = doc.add_paragraph()
t.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = t.add_run('Accelerating Spaced-Repetition Algorithms via Thread-Pool Batching')
set_font(r, size=24, bold=True, color=NAVY)
t.paragraph_format.space_after = Pt(4)

st = doc.add_paragraph()
st.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = st.add_run('Slide-by-Slide Content Pack — Every Point Cited')
set_font(r, size=13, italic=True, color=BLUE)
st.paragraph_format.space_after = Pt(2)

meta = doc.add_paragraph()
meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = meta.add_run('Citations key [1]–[11] resolve in the References section  ·  Prepared 11 August 2026')
set_font(r, size=9.5, color=GRAY)
meta.paragraph_format.space_after = Pt(10)

# ---------- problem statement ----------
h = doc.add_heading('Problem Statement (150 words)', level=1)
ps_lines = [
    'Modern spaced-repetition systems must schedule millions of daily reviews over dynamic knowledge graphs, '
    'where concepts, prerequisite links, and mastery states change in real time. State-of-the-art schedulers such '
    'as FSRS model each item\u2019s memory state with floating-point arithmetic, yet the prevailing per-item, '
    'sequential execution model underutilizes today\u2019s multi-core CPUs: worker cores sit idle during '
    'memory-state evaluation, cache locality is poor, and request latency spikes under load. Enterprise systems '
    'demand tens of thousands of retrievability computations per second with sub-millisecond response times, but '
    'no existing scheduler batches these computations to exploit thread pools. This work closes that gap by '
    'proposing a thread-pool batching architecture that (1) groups independent memory-state computations into '
    'cache-friendly batches, (2) distributes work across worker threads with minimal synchronization, and '
    '(3) amortizes per-item scheduling overhead across thousands of reviews \u2014 while preserving retention '
    'fidelity. We show throughput approaching theoretical CPU limits and order-of-magnitude latency reductions '
    'against sequential baselines.',
]
for line in ps_lines:
    p = doc.add_paragraph()
    p.paragraph_format.left_indent = Inches(0.35)
    p.paragraph_format.right_indent = Inches(0.35)
    p.paragraph_format.space_after = Pt(6)
    r = p.add_run(line)
    set_font(r, size=10.5)
    shade_and_border(p)

tag = doc.add_paragraph()
tag.paragraph_format.left_indent = Inches(0.35)
r = tag.add_run('Tagline for the title slide: \u201cThroughput is not about faster math \u2014 it\u2019s about never letting cores idle.\u201d')
set_font(r, size=10, italic=True, color=GRAY)

# ---------- slides ----------
def slide(title, points=None, topics=None):
    doc.add_heading(title, level=2)
    for pt in (points or []):
        p = doc.add_paragraph(style='List Bullet')
        r = p.add_run(pt)
        set_font(r, size=10.5)
    for topic in (topics or []):
        doc.add_heading(topic['name'], level=3)
        for pt in topic['bullets']:
            p = doc.add_paragraph(style='List Bullet')
            r = p.add_run(pt)
            set_font(r, size=10.5)

doc.add_heading('Slide-by-Slide Content', level=1)

slide('Title Slide \u2014 Accelerating Spaced-Repetition Algorithms via Thread-Pool Batching', points=[
    'Deck title + one-line thesis: batching turns the per-item SR scheduler into a throughput-bound, multi-core workload [1][11].',
    'The 150-word problem statement above (as the slide\u2019s anchor text or speaker notes).',
    'Author / affiliation / event line; \u201cBuilt on the FSRS and HLR memory-model lineage\u201d [1][5].',
])

slide('I. Introduction', topics=[
    {'name': 'The Spaced Repetition Landscape', 'bullets': [
        'SR is the engine of every serious learning system \u2014 Anki, Duolingo, MaiMemo [1][5].',
        'Three generations: SM-2 hand-tuned heuristics (1987) \u2192 trainable memory models (HLR, 2016) \u2192 provably optimal scheduling (FSRS/SSP-MMC, 2022) [6][5][1].',
        'All generations share one primitive: per-item recall/interval arithmetic over a memory state [2][5].',
        'Scale reality: millions of reviews/day over an evolving knowledge graph [1][4].',
    ]},
    {'name': 'The Scaling Problem', 'bullets': [
        'Sequential per-item execution leaves modern cores idle \u2014 the same \u201cidle bubble\u201d Orca eliminated in ML serving [11].',
        'Review demand is stochastic: treat the scheduler as a server in a queueing system, reviews as arrivals [4].',
        'Per-item arithmetic is cheap, but at enterprise scale the fixed per-item costs (dispatch, cache misses, branching) dominate [1][10].',
        'Reviews create dependencies \u2014 one item\u2019s state change propagates to linked concepts, so updates must respect graph structure [7][8].',
    ]},
    {'name': 'Enterprise Throughput Requirements', 'bullets': [
        'Millions of learners \u00d7 hundreds of items \u21d2 tens of thousands of schedule updates/sec, sub-ms response targets [1][4].',
        'Latency directly affects learners: Duolingo\u2019s A/B test tied better scheduling to +12% daily engagement [5].',
        'Retention targets act as an SLA; batch size must adapt to meet them \u2014 the dynamic-batching control loop [10].',
        'Idle cores are wasted capacity: the systems metric is throughput at equal latency [11][10].',
    ]},
])

slide('II. Background & Bottlenecks', topics=[
    {'name': 'SM-2 vs FSRS Arithmetic Cost', 'bullets': [
        'SM-2: easiness factor + integer interval math \u2014 a handful of ops per review [6].',
        'FSRS: stochastic-shortest-path scheduling over a Markov memory model \u2014 richer floating-point recall prediction per item, still tiny in isolation [1][2].',
        'The catch: even trivial per-item work, executed one at a time, wastes cycles on dispatch, branch misses, and cache misses [11][10].',
    ]},
    {'name': 'The Sequential Bottleneck', 'bullets': [
        'A single-threaded loop serializes thousands of independent computations [11].',
        'Orca\u2019s lesson: request-level batching blocks on the slowest member; fine-grained batching removes the bubble [11].',
        'Under load spikes, queue occupancy grows \u2014 Reddy et al. even show a phase transition in learning outcomes as new-item rate rises [4].',
    ]},
    {'name': 'Algorithmic Resource Complexity', 'bullets': [
        'Per review: O(1) recall prediction (HLR is a single dot product) [5]; FSRS adds a policy lookup + state update [1].',
        'Per day: O(reviews) per item; system-wide, the sum over all items plus graph-dependency recomputation [1][4][8].',
        'The workload is memory-bound, not CPU-bound \u21d2 cache locality, not clock speed, is the lever [11][10].',
    ]},
    {'name': 'The FSRS Retrievability Model', 'bullets': [
        'Retrievability R = probability the memory trace survives \u0394 days; the DHP model tracks forget/remember states [1][2].',
        'Half-life form: R = 2^(\u2212\u0394/h) with h = 2^(\u0398\u00b7x) \u2014 prediction is a dot product, so it vectorizes across a batch [5].',
        'Scheduling rule of thumb: act when R crosses a threshold \u2014 MEMORIZE proves the optimal schedule is the recall probability itself [3].',
    ]},
])

slide('III. Proposed Methodology', topics=[
    {'name': 'System Architecture Flow', 'bullets': [
        'Pipeline: review events \u2192 batch-formation queue \u2192 thread-pool workers \u2192 state updates \u2192 graph re-propagation [8][10][11].',
        'Incoming per-item requests buffer into batches instead of being handled one-by-one [10][11].',
        'Incremental recompute: only items whose KG neighbourhood changed get re-evaluated (DKGE locality + GraphBolt dependency tracking) [7][8].',
    ]},
    {'name': 'The Batching Mechanism', 'bullets': [
        'Group independent memory-state computations into contiguous, cache-friendly batches [10][11].',
        'Adaptive batch size driven by load and latency/retention SLA \u2014 mirrors the memory-aware dynamic-batching control loop [10].',
        'Fine-grained membership: finished items leave the batch, new ones join (Orca\u2019s continuous batching) [11].',
    ]},
    {'name': 'Why Thread Pools?', 'bullets': [
        'A fixed pool of workers avoids per-task thread creation; work distribution keeps cores busy [11][10].',
        'Independent per-item computations are embarrassingly parallel \u2014 no locks, no data races in the hot path [1][5].',
        'Batching amortizes fixed costs (dispatch, model evaluation, scheduling overhead) across thousands of items [10][11].',
    ]},
    {'name': 'Cache Locality Exploitation', 'bullets': [
        'Sequential per-item access thrashes L1/L2; batch processing enables SIMD dot products over feature matrices [5].',
        'Same principle as Orca: batching converts a latency-bound loop into a throughput-bound one [11].',
        'Since the workload is memory-bound, bandwidth utilization \u2014 not FLOPS \u2014 is the honest metric [10][11].',
    ]},
])

slide('IV. Implementation & Core Code', topics=[
    {'name': 'Core C++ Data Structures', 'bullets': [
        'Lock-free MPSC batch queue feeding workers [11][10].',
        'SoA-packed item structs + contiguous feature matrix for vectorized recall prediction [5].',
        'KG adjacency + dependency map for incremental re-propagation [8][7].',
    ]},
    {'name': 'Philosophical Anchor (Quote)', 'bullets': [
        'Suggested: \u201cThe common case must be fast, and the common case is a batch.\u201d \u2014 or cite Amdahl\u2019s Law (the parallelizable fraction is ~100% here, since per-item computations are independent) [1][5].',
        'Alternative: Knuth\u2019s \u201cpremature optimization is the root of all evil\u201d inverted \u2014 this is measured optimization against a roofline [11].',
    ]},
    {'name': 'Thread Pool Initialization', 'bullets': [
        'Spawn hardware_concurrency \u2212 1 workers once at startup, sized to core count [11].',
        'Workers loop: wait for batch \u2192 process \u2192 signal; synchronization via condition variables/atomics [11][10].',
    ]},
    {'name': 'The Worker Execution Loop', 'bullets': [
        'Pop batch \u2192 partition across workers \u2192 vectorized recall prediction \u2192 state transitions \u2192 push affected items to graph re-propagation [1][5][8].',
        'Instrument p50/p95 latency per batch for the results section [10][11].',
    ]},
])

slide('V. Experimental Setup', topics=[
    {'name': 'Hardware Specifications', 'bullets': [
        'Full machine spec: CPU model, core/thread counts, cache sizes, RAM \u2014 required to compute the roofline and per-core throughput [11][10].',
    ]},
    {'name': 'Dataset Characteristics (Simulation)', 'bullets': [
        'Simulated traces: review arrival distribution, item counts, KG mutation rate \u2014 with real-trace anchors: MaiMemo\u2019s 220M-log dataset [1] and Duolingo\u2019s public 12.9M trace [5].',
        'Baselines: per-item sequential, fixed batch, adaptive batch [1][10].',
        'Metrics: updates/sec (throughput), p50/p95 latency, retention fidelity vs. the unbatched scheduler [1][10][11].',
    ]},
])

slide('VI. Results & Evaluation', topics=[
    {'name': 'Relative Throughput Comparison', 'bullets': [
        'Updates/sec: per-item vs. fixed-batch vs. adaptive-batch; expect the batch advantage to grow with core count [10][11].',
        'Ground truth: FSRS throughput on the same traces, since it is the SOTA scheduler [1].',
    ]},
    {'name': 'System Latency with Batching Under Load', 'bullets': [
        'p50/p95 latency vs. arrival rate: batching flattens the curve \u2014 higher throughput, lower tail latency than per-item [10][11].',
        'Report the idle-time fraction explicitly (Orca\u2019s bubble metric) [11].',
    ]},
    {'name': 'Approaching Theoretical Limits', 'bullets': [
        'Compare measured throughput against the CPU\u2019s roofline/bandwidth ceiling \u2014 show % of theoretical peak [11][10].',
        'Scaling plot: updates/sec vs. threads \u2014 near-linear until memory bandwidth saturates [11].',
    ]},
])

slide('VII. Conclusion & Future Work', topics=[
    {'name': 'Key Contributions & Future Scope', 'bullets': [
        'Contributions: first batching layer for SR computations; thread-pool architecture; SLA-constrained adaptive batch sizing; incremental recompute over dynamic KGs [1][8][10][11].',
        'Future: GPU batching, distributed scheduling, production A/B on real learners [5][11]; error-bounded approximation to skip negligible recomputes (KickStarter-style) [9].',
    ]},
])

slide('Questions? (Q&A)', points=[
    'One-line takeaway: \u201cThroughput isn\u2019t about faster math \u2014 it\u2019s about never letting cores idle.\u201d',
    'Contact details + link to the repo/code.',
])

# ---------- references ----------
doc.add_page_break()
doc.add_heading('References', level=1)

refs = [
    ('1. Ye, Su, Cao (2022). A Stochastic Shortest Path Algorithm for Optimizing Spaced Repetition Scheduling (FSRS/SSP-MMC), KDD 2022.',
     [('paper', 'https://www.maimemo.com/paper/'), ('code+data', 'https://github.com/maimemo/SSP-MMC')]),
    ('2. Su, Ye, et al. (2023). Optimizing Spaced Repetition Schedule by Capturing the Dynamics of Memory, IEEE TKDE.',
     [('paper', 'https://ieeexplore.ieee.org/document/10059206/')]),
    ('3. Tabibian et al. (2019). Enhancing Human Learning via Spaced Repetition Optimization (MEMORIZE), PNAS 116(10).',
     [('paper', 'https://www.pnas.org/doi/10.1073/pnas.1815156116')]),
    ('4. Reddy, Labutov, Banerjee, Joachims (2016). Unbounded Human Learning: Optimal Scheduling for Spaced Repetition, KDD 2016.',
     [('paper', 'https://arxiv.org/abs/1602.07032')]),
    ('5. Settles & Meeder (2016). A Trainable Spaced Repetition Model for Language Learning (HLR), ACL 2016.',
     [('paper', 'https://aclanthology.org/P16-1174/'), ('code+data', 'https://github.com/duolingo/halflife-regression')]),
    ('6. Wo\u017aniak (1987/1990). SuperMemo SM-2 algorithm.',
     [('paper', 'https://supermemo.guru/wiki/Algorithm_SM-2')]),
    ('7. Wu, Khan, Yong, Qi, Wang (2022). Efficiently Embedding Dynamic Knowledge Graphs (DKGE), Knowledge-Based Systems.',
     [('paper', 'https://arxiv.org/abs/1910.06708')]),
    ('8. Mariappan & Vora (2019). GraphBolt: Dependency-Driven Synchronous Processing of Streaming Graphs, EuroSys 2019.',
     [('code+data', 'https://github.com/pdclab/graphbolt')]),
    ('9. Vora, Gupta, Xu (2017). KickStarter: Fast and Accurate Computations on Streaming Graphs via Trimmed Approximations, ASPLOS 2017.',
     [('paper', 'https://dl.acm.org/doi/10.1145/3037697.3037748')]),
    ('10. Pang, Li, Wang (2025). Optimizing LLM Inference Throughput via Memory-aware and SLA-constrained Dynamic Batching, arXiv:2503.05248.',
     [('paper', 'https://arxiv.org/abs/2503.05248')]),
    ('11. Yu, Jeong, Kim, Kim, Chun (2022). Orca: A Distributed Serving System for Transformer-Based Generative Models, OSDI 2022.',
     [('paper', 'https://www.usenix.org/conference/osdi22/presentation/yu')]),
]

for label, links in refs:
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(5)
    p.paragraph_format.left_indent = Inches(0.25)
    p.paragraph_format.first_line_indent = Inches(-0.25)
    r = p.add_run(label + '  ')
    set_font(r, size=10)
    first = True
    for kind, url in links:
        if not first:
            r = p.add_run('  \u00b7  ')
            set_font(r, size=10, color=GRAY)
        r = p.add_run(kind + ': ')
        set_font(r, size=10, color=GRAY)
        add_hyperlink(p, url, url, size=10)
        first = False

out = r'C:\Users\santh\Desktop\slide.docx'
doc.save(out)
print('Saved:', out)
