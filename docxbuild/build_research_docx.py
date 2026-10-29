# -*- coding: utf-8 -*-
"""Build research.docx - a designed literature survey (python-docx)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.opc.constants import RELATIONSHIP_TYPE as RT

from data_glance import GLANCE, PILLAR_INTROS
from data_p1 import PAPERS1
from data_p2 import PAPERS2
from data_p3 import PAPERS3

DARK = "1F4E79"; MID = "2E74B5"; LIGHT = "DEEBF7"; PALE = "F2F7FB"
GREEN = "2E7D32"; PURPLE = "7B1FA2"; GRAY = "595959"

TARGET = ("Algorithmic Batching of Spaced-Repetition Computations: Maximizing "
          "CPU Throughput and Minimizing Idle Latency in Dynamic Knowledge Graphs")

# ---------------- helpers ----------------
def shade_paragraph(p, fill):
    pPr = p._p.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), fill)
    pPr.append(shd)

def shade_cell(cell, fill):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear'); shd.set(qn('w:color'), 'auto'); shd.set(qn('w:fill'), fill)
    tcPr.append(shd)

def rule_below(p, color=DARK, size="12"):
    pPr = p._p.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single'); bottom.set(qn('w:sz'), size)
    bottom.set(qn('w:space'), '4'); bottom.set(qn('w:color'), color)
    pBdr.append(bottom); pPr.append(pBdr)

def add_hyperlink(paragraph, url, text):
    try:
        part = paragraph.part
        r_id = part.relate_to(url, RT.HYPERLINK, is_external=True)
        hyperlink = OxmlElement('w:hyperlink')
        hyperlink.set(qn('r:id'), r_id)
        run = OxmlElement('w:r'); rPr = OxmlElement('w:rPr')
        c = OxmlElement('w:color'); c.set(qn('w:val'), "0563C1"); rPr.append(c)
        u = OxmlElement('w:u'); u.set(qn('w:val'), 'single'); rPr.append(u)
        sz = OxmlElement('w:sz'); sz.set(qn('w:val'), "19"); rPr.append(sz)
        run.append(rPr)
        t = OxmlElement('w:t'); t.text = text; run.append(t)
        hyperlink.append(run)
        paragraph._p.append(hyperlink)
    except Exception:
        r = paragraph.add_run(text); r.font.color.rgb = RGBColor(0x05, 0x63, 0xC1); r.underline = True

def page_number_footer(section):
    p = section.footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run()
    f1 = OxmlElement('w:fldChar'); f1.set(qn('w:fldCharType'), 'begin')
    it = OxmlElement('w:instrText'); it.set(qn('xml:space'), 'preserve'); it.text = 'PAGE'
    f2 = OxmlElement('w:fldChar'); f2.set(qn('w:fldCharType'), 'end')
    run._r.append(f1); run._r.append(it); run._r.append(f2)
    run.font.size = Pt(9); run.font.color.rgb = RGBColor(0x7F, 0x7F, 0x7F)

def label(doc, text, color=DARK, size=11, before=10, after=2):
    p = doc.add_paragraph(); r = p.add_run(text)
    r.bold = True; r.font.size = Pt(size); r.font.color.rgb = RGBColor.from_string(color)
    p.paragraph_format.space_before = Pt(before); p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.keep_with_next = True
    return p

def body(doc, text, size=10.5, italic=False, color=None, after=6):
    p = doc.add_paragraph(); r = p.add_run(text)
    r.font.size = Pt(size); r.italic = italic
    if color: r.font.color.rgb = RGBColor.from_string(color)
    p.paragraph_format.space_after = Pt(after); p.paragraph_format.line_spacing = 1.15
    return p

def bullets(doc, items, style='List Bullet', size=10.5):
    for it in items:
        p = doc.add_paragraph(style=style); r = p.add_run(it); r.font.size = Pt(size)
        p.paragraph_format.space_after = Pt(3); p.paragraph_format.line_spacing = 1.12

def section_bar(doc, text):
    p = doc.add_paragraph(); r = p.add_run(text)
    r.bold = True; r.font.size = Pt(14); r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    p.paragraph_format.space_before = Pt(16); p.paragraph_format.space_after = Pt(10)
    shade_paragraph(p, DARK)

def align_box(doc, title, items):
    t = doc.add_table(rows=1, cols=1); t.alignment = WD_ALIGN_PARAGRAPH.LEFT
    cell = t.rows[0].cells[0]; shade_cell(cell, LIGHT)
    p = cell.paragraphs[0]; r = p.add_run(title)
    r.bold = True; r.font.size = Pt(10.5); r.font.color.rgb = RGBColor.from_string(DARK)
    p.paragraph_format.space_after = Pt(3)
    for it in items:
        bp = cell.add_paragraph(style='List Bullet'); br = bp.add_run(it); br.font.size = Pt(10)
        bp.paragraph_format.space_after = Pt(2); bp.paragraph_format.line_spacing = 1.12
    doc.add_paragraph().paragraph_format.space_after = Pt(2)

def paper_entry(doc, n, paper):
    p = doc.add_paragraph(); r = p.add_run(f"{n}.  {paper['title']}")
    r.bold = True; r.font.size = Pt(12); r.font.color.rgb = RGBColor.from_string(DARK)
    p.paragraph_format.space_before = Pt(14); p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.keep_with_next = True
    mp = doc.add_paragraph()
    mr = mp.add_run(f"{paper['authors']}  |  {paper['venue']} ({paper['year']})  |  ")
    mr.italic = True; mr.font.size = Pt(9.5); mr.font.color.rgb = RGBColor.from_string(GRAY)
    add_hyperlink(mp, paper['link'], paper['link_label'])
    mp.paragraph_format.space_after = Pt(4); mp.paragraph_format.keep_with_next = True
    label(doc, "Summary", size=10, before=4)
    body(doc, paper['summary'])
    label(doc, "Key findings", size=10, before=4)
    bullets(doc, paper['findings'])
    align_box(doc, "How it aligns & helps your friend's paper", paper['align'])

# ---------------- document ----------------
doc = Document()
normal = doc.styles['Normal']
normal.font.name = 'Calibri'; normal.font.size = Pt(10.5)
normal.paragraph_format.space_after = Pt(6); normal.paragraph_format.line_spacing = 1.15

sec = doc.sections[0]
sec.top_margin = Inches(0.7); sec.bottom_margin = Inches(0.7)
sec.left_margin = Inches(0.8); sec.right_margin = Inches(0.8)
page_number_footer(sec)

cp = doc.core_properties
cp.title = "Research Literature Survey - " + TARGET
cp.author = "Namma Agent"
cp.subject = "Spaced repetition batching, CPU throughput, dynamic knowledge graphs"

# ---- title block ----
tp = doc.add_paragraph(); tr = tp.add_run("LITERATURE RESEARCH REPORT")
tr.bold = True; tr.font.size = Pt(11); tr.font.color.rgb = RGBColor.from_string(MID)
tp.paragraph_format.space_after = Pt(2)

tp2 = doc.add_paragraph(); tr2 = tp2.add_run("Relevant Research Papers for the Problem Statement:")
tr2.font.size = Pt(15); tr2.font.color.rgb = RGBColor.from_string(DARK)
tp2.paragraph_format.space_after = Pt(2)

tp3 = doc.add_paragraph(); tr3 = tp3.add_run(TARGET)
tr3.bold = True; tr3.font.size = Pt(17); tr3.font.color.rgb = RGBColor.from_string(DARK)
tp3.paragraph_format.space_after = Pt(4)

tp4 = doc.add_paragraph()
tr4 = tp4.add_run("A curated survey of 11 papers across three pillars - with links, summaries, key findings, "
                  "and per-paper alignment notes on how each one feeds the design of the proposed solution.")
tr4.italic = True; tr4.font.size = Pt(11); tr4.font.color.rgb = RGBColor.from_string(GRAY)
tp4.paragraph_format.space_after = Pt(6)

tp5 = doc.add_paragraph(); tr5 = tp5.add_run("Compiled by Namma Agent  |  10 August 2026  |  Saved to Desktop as research.docx")
tr5.font.size = Pt(9.5); tr5.font.color.rgb = RGBColor.from_string(GRAY)
tp5.paragraph_format.space_after = Pt(10)
rule_below(tp5)

# ---- executive summary ----
label(doc, "Executive Summary", size=15, before=8)
body(doc, "The target paper sits at the intersection of three research areas, and no single published work covers the "
          "exact combination. That is good news: the gap is real, and the contribution is well-defined. The 11 papers "
          "below give your friend everything needed to build, analyze, and evaluate the solution:")
bullets(doc, [
    "Pillar 1 - Spaced-repetition scheduling & memory modeling (4 papers): the optimal-scheduling theory (FSRS's "
    "stochastic shortest path, PNAS optimal control) and the memory models that define what each review computation actually does.",
    "Pillar 2 - Batching, CPU throughput & latency (4 papers): the systems and queueing-theory toolkit for batching "
    "work to maximize throughput while bounding idle latency (micro-batching, dynamic/continuous batching, bulk queues, work-conserving scheduling).",
    "Pillar 3 - Dynamic & temporal knowledge graphs (3 papers): how to represent, maintain, and recompute state as a "
    "graph evolves - incremental processing, temporal embeddings, and localized updates.",
    "Novelty check: no academic paper was found that batches spaced-repetition computations or couples SR scheduling "
    "with dynamic-knowledge-graph maintenance. Every nearby paper stops one step short - which is precisely the gap this paper can fill.",
])

# ---- problem decomposition ----
label(doc, "The Problem, Decomposed into Three Pillars", size=15, before=14)
body(doc, "Reading the title as three sub-problems makes the literature search systematic. Each sub-problem maps to a "
          "research pillar, and each pillar maps to papers that can be cited, adapted, and extended:")
bullets(doc, [
    "\u201cSpaced-Repetition Computations\u201d - what the scheduler computes per review: recall prediction, difficulty/stability "
    "updates, next-interval decisions. Foundation: Pillar 1.",
    "\u201cBatching - Maximizing CPU Throughput and Minimizing Idle Latency\u201d - the systems objective: group many review "
    "computations into batches to keep cores busy, while keeping per-review latency bounded. Foundation: Pillar 2.",
    "\u201cDynamic Knowledge Graphs\u201d - the data structure the review items live in (concepts, prerequisites, dependencies) "
    "that changes as the learner progresses and as content evolves. Foundation: Pillar 3.",
])

# ---- at a glance ----
label(doc, "The Papers at a Glance", size=15, before=14, after=6)
table = doc.add_table(rows=1, cols=5)
table.style = 'Table Grid'
hdr = table.rows[0].cells
for i, h in enumerate(["#", "Paper", "Venue", "Pillar", "One-line takeaway"]):
    hp = hdr[i].paragraphs[0]; hr = hp.add_run(h)
    hr.bold = True; hr.font.size = Pt(9.5); hr.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    shade_cell(hdr[i], DARK)
widths = [Inches(0.35), Inches(1.75), Inches(0.95), Inches(0.7), Inches(3.15)]
for i, w in enumerate(widths):
    hdr[i].width = w
pc = {"P1": DARK, "P2": GREEN, "P3": PURPLE}
for idx, (num, title, venue, pillar, take) in enumerate(GLANCE):
    row = table.add_row().cells
    vals = [num, title, venue, pillar, take]
    for i, v in enumerate(vals):
        p = row[i].paragraphs[0]; r = p.add_run(v)
        r.font.size = Pt(9)
        if i == 3:
            r.font.color.rgb = RGBColor.from_string(pc[v]); r.bold = True
        if i == 1:
            r.bold = True; r.font.color.rgb = RGBColor.from_string(DARK)
        row[i].width = widths[i]
        if idx % 2 == 1:
            shade_cell(row[i], PALE)
doc.add_paragraph().paragraph_format.space_after = Pt(2)

# ---- pillars ----
for key, papers, titles in (("P1", PAPERS1, "PILLAR 1  |  Spaced-Repetition Scheduling & Memory Modeling"),
                            ("P2", PAPERS2, "PILLAR 2  |  Batching, CPU Throughput & Latency"),
                            ("P3", PAPERS3, "PILLAR 3  |  Dynamic & Temporal Knowledge Graphs")):
    section_bar(doc, titles)
    body(doc, PILLAR_INTROS[key])
    for n, paper in enumerate(papers, 1):
        paper_entry(doc, n, paper)

# ---- synthesis ----
section_bar(doc, "SYNTHESIS  |  How to Use These Papers in Your Friend's Paper")
label(doc, "1.  Related-work map (which section cites what)", size=12, before=6)
map_rows = [
    ("Introduction / Motivation", "DAS3H (graph-structured SR), vLLM (batching wins), Temporal GraphRAG (evolving knowledge)"),
    ("Related work - SR algorithms", "FSRS KDD'22, FSRS-6 TKDE'23, PNAS MEMORIZE, DAS3H"),
    ("Related work - batching systems", "D-Streams, queueing-theory inference, throughput-optimal scheduling, vLLM"),
    ("Related work - dynamic graphs", "TKG survey, GraphBolt, Temporal GraphRAG"),
    ("Method - batch policy design", "D-Streams (micro-batch), queueing-theory paper (dynamic/fixed/elastic), vLLM (continuous batching)"),
    ("Method - KG-aware recomputation", "GraphBolt (dependency-driven windows), Temporal GraphRAG (hierarchical time index)"),
    ("Analysis / formal claims", "PNAS (optimality yardstick), throughput-optimal scheduling (work-conserving theorem), bulk-queue delay formulas"),
    ("Evaluation", "FSRS-6's 220M-row dataset, FSRS-Anki-20k / anki-revlogs-10k for realistic review streams"),
]
t2 = doc.add_table(rows=1, cols=2)
t2.style = 'Table Grid'
h = t2.rows[0].cells
for i, txt in enumerate(["Paper section", "Papers to cite"]):
    p = h[i].paragraphs[0]; r = p.add_run(txt)
    r.bold = True; r.font.size = Pt(9.5); r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
    shade_cell(h[i], DARK)
h[0].width = Inches(2.3); h[1].width = Inches(4.6)
for a, b in map_rows:
    row = t2.add_row().cells
    for i, v in enumerate((a, b)):
        p = row[i].paragraphs[0]; r = p.add_run(v); r.font.size = Pt(9)
        if i == 0:
            r.bold = True
        row[i].width = Inches(2.3 if i == 0 else 4.6)
doc.add_paragraph().paragraph_format.space_after = Pt(2)

label(doc, "2.  The novelty gap (what your friend can claim)", size=12, before=8)
bullets(doc, [
    "FSRS optimizes each card independently - no notion of grouping reviews to improve CPU utilization.",
    "Micro-batching (D-Streams) and inference batching (vLLM, queueing papers) batch generic jobs - none of them batch memory-model updates or review scheduling computations.",
    "Dynamic-graph systems (GraphBolt) batch graph updates - but not the review computations that depend on the graph.",
    "Therefore the paper's contribution is three-fold and non-overlapping: (a) batch policies for spaced-repetition computations, (b) queueing/throughput analysis of those policies, (c) KG-aware incremental recomputation that keeps batches current as the graph evolves.",
])

label(doc, "3.  Suggested reading order", size=12, before=8)
bullets(doc, [
    "Start with FSRS KDD'22 + FSRS-6 TKDE'23 - they define the computation to be batched.",
    "Then D-Streams + the queueing-theory paper - they define the batching design space and its math.",
    "Then throughput-optimal scheduling + vLLM - the formal and practical limits of batching.",
    "Then DAS3H - the bridge into graph-structured memory state.",
    "Finally GraphBolt + Temporal GraphRAG + the TKG survey - the dynamic-knowledge-graph layer.",
    "Keep PNAS MEMORIZE handy - it is the theoretical anchor for 'optimal schedule semantics preserved under batching'.",
])

label(doc, "4.  Useful open resources & datasets", size=12, before=8)
resources = [
    ("FSRS code & docs", "https://github.com/open-spaced-repetition/fsrs4anki"),
    ("Free Spaced Repetition Scheduler (core)", "https://github.com/open-spaced-repetition/free-spaced-repetition-scheduler"),
    ("FSRS-Anki-20k dataset", "https://github.com/open-spaced-repetition/FSRS-Anki-20k"),
    ("anki-revlogs-10k dataset", "https://github.com/open-spaced-repetition/anki-revlogs-10k"),
    ("SSP-MMC-Plus (220M-row dataset + code)", "https://github.com/maimemo/SSP-MMC-Plus"),
    ("MEMORIZE code (PNAS paper)", "https://github.com/Human-Centric-Machine-Learning/memorize"),
    ("GraphBolt code", "https://github.com/pdclab/graphbolt"),
    ("GraphBolt paper PDF", "https://www.cs.sfu.ca/~keval/contents/papers/graphbolt-eurosys19.pdf"),
    ("Spaced repetition overview (Wikipedia)", "https://en.wikipedia.org/wiki/Spaced_repetition"),
]
for name, url in resources:
    p = doc.add_paragraph(style='List Bullet')
    r = p.add_run(name + " - "); r.font.size = Pt(10); r.bold = True
    add_hyperlink(p, url, url)
    p.paragraph_format.space_after = Pt(2)

# ---- sources ----
section_bar(doc, "SOURCES  |  All Papers Referenced")
allpapers = [(p['title'], p['link']) for p in PAPERS1 + PAPERS2 + PAPERS3]
for i, (t, u) in enumerate(allpapers, 1):
    p = doc.add_paragraph(); r = p.add_run(f"{i}.  {t}  -  ")
    r.font.size = Pt(10); r.bold = True
    add_hyperlink(p, u, u)
    p.paragraph_format.space_after = Pt(2)

out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.expanduser("~"), "Desktop", "research.docx")
doc.save(out)
print("SAVED:", out)
