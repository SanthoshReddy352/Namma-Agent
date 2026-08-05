# -*- coding: utf-8 -*-
import json, os

WHITE  = "FBFEFF"
GRAY   = "B4B3B6"
DARK   = "6D676E"
ORANGE = "FAA613"
FONT   = "Segoe UI"

cmds = []

def slide(n, layout="Blank"):
    cmds.append({"command":"add","parent":"/","type":"slide","props":{"layout":layout}})

def shape(n, props):
    cmds.append({"command":"add","parent":f"/slide[{n}]","type":"shape","props":props})

def rect(n, x, y, w, h, fill, line="none", geometry="rect", adj=None, opacity=None, name=None):
    p = {"x":x,"y":y,"width":w,"height":h,"fill":fill,"line":line,"geometry":geometry}
    if adj: p["adj"]=adj
    if opacity is not None: p["opacity"]=opacity
    if name: p["name"]=name
    shape(n, p)

def text(n, t, x, y, w, h, size, color=DARK, bold=False, align="left", valign="top",
         lineSpacing=None, margin=None, autoFit=None, font=FONT):
    p = {"text":t,"x":x,"y":y,"width":w,"height":h,"size":size,"color":color,
         "bold":bold,"font":font,"align":align,"valign":valign}
    if lineSpacing: p["lineSpacing"]=lineSpacing
    if margin: p["margin"]=margin
    if autoFit: p["autoFit"]=autoFit
    shape(n, p)

def card(n, x, y, w, h, line="1.2pt"):
    rect(n, x, y, w, h, WHITE, line=line, geometry="roundRect", adj="adj:val 12000")

def kicker(n, title):
    rect(n, "0.8in","0.55in","0.45in","0.09in", ORANGE)
    text(n, title, "0.8in","0.78in","11.7in","0.9in", 32, bold=True)

def bullet(n, x, y, title, body, w=6.4, tsize=15, bsize=12.5):
    rect(n, x, y+0.06, "0.16in","0.16in", ORANGE)
    text(n, title, f"{x}in+0.3in", f"{y}in", f"{w}in", "0.4in", tsize, bold=True)
    text(n, body, f"{x}in+0.3in", f"{y+0.34}in", f"{w}in", "0.6in", bsize, autoFit="normal")

# ---------------- SLIDE 1 : Title ----------------
slide(1)
rect(1, "0in","0in","13.333in","7.5in", WHITE)
rect(1, "0in","0in","13.333in","0.18in", GRAY)
rect(1, "0in","7.2in","13.333in","0.3in", ORANGE)
rect(1, "1.0in","1.0in","0.55in","0.55in", ORANGE)
text(1, "Namma Agent", "1.0in","1.8in","11.3in","1.2in", 54, bold=True)
text(1, "The trustworthy personal agent that measurably knows you.",
     "1.05in","3.35in","11.0in","0.7in", 22)
chips = ["Self-hosted","Windows-first","Measurable memory","~90 native tools"]
cx = 1.0
for c in chips:
    rect(1, f"{cx}in","4.35in","2.6in","0.55in", ORANGE, geometry="roundRect", adj="adj:16666")
    text(1, c, f"{cx}in","4.35in","2.6in","0.55in", 14, color=WHITE, bold=True, align="center", valign="middle")
    cx += 2.9
text(1, "Pitch Deck  ·  2026", "1.0in","6.55in","6in","0.4in", 12, color=GRAY)
text(1, "MIT Licensed", "10.3in","6.55in","2.0in","0.4in", 12, color=GRAY, align="right")

# ---------------- SLIDE 2 : Problem ----------------
slide(2)
rect(2, 0in,0in,"13.333in","7.5in", WHITE)
kicker(2, "The trust crisis in personal agents")
text(2, "Personal agents are having a moment — and a trust crisis.",
     "0.8in","1.75in","11.7in","0.5in", 16, color=DARK)
probs = [
    ("Prompt-injection attacks",
     "Strangers hide instructions inside emails, pages, and uploads to hijack always-on agents — exfiltration is the category's public wound."),
    ("Untrusted by design",
     "Microsoft's guidance: treat agents as \u201cuntrusted code execution with persistent credentials.\u201d Most projects answer with features, not trust."),
    ("Memory is claimed, never measured",
     "\u201cIt remembers you\u201d is a marketing sentence. No reproducible numbers, no trend line, no audit trail."),
    ("Scheduled, not proactive",
     "Agents wait for prompts. Real proactivity — reaching out when something happens — is rare."),
]
px = [0.8, 6.9]; py = [2.4, 4.75]
for i,(h,b) in enumerate(probs):
    x = px[i%2]; y = py[i//2]
    card(2, x, y, 5.6, 2.15)
    text(2, h, f"{x}in+0.35in", f"{y}in+0.3in", "4.9in","0.5in", 16, bold=True)
    text(2, b, f"{x}in+0.35in", f"{y}in+0.9in", "4.9in","1.1in", 12.5, autoFit="normal")

# ---------------- SLIDE 3 : Solution overview ----------------
slide(3)
rect(3, 0in,0in,"13.333in","7.5in", WHITE)
kicker(3, "Meet Namma Agent")
text(3, "A self-hosted personal AI agent. The brain is a single API call — native Anthropic, OpenAI, Google, or any OpenAI-compatible endpoint (Ollama, LM Studio\u2026).",
     "0.8in","1.75in","11.7in","0.9in", 16)
pillars = [
    ("01","Tool-calling loop","~90 native tools the model calls natively — no intent regex, no routing graph."),
    ("02","In-process memory","Engram: SQLite-backed, zero infrastructure, works fully offline."),
    ("03","Event-driven watchers","Reach out when things happen — files, email, web, calendar."),
    ("04","Layered trust","On by default, visible live in the UI, published threat model."),
]
px = [0.7, 4.15, 7.6, 11.05]
for i,(num,t,b) in enumerate(pillars):
    x = px[i]
    card(3, x, 2.9, 2.85, 3.3)
    text(3, num, f"{x}in+0.3in", "3.2in","1in","0.7in", 22, color=ORANGE, bold=True)
    text(3, t, f"{x}in+0.3in", "3.95in","2.25in","0.6in", 15, bold=True)
    text(3, b, f"{x}in+0.3in", "4.6in","2.25in","1.4in", 12, autoFit="normal")
text(3, "No Docker requirement, no vendor server holding your data — it runs anywhere Python does, from a Windows laptop to a 1 GB VPS.",
     "0.8in","6.5in","11.7in","0.5in", 13, color=DARK)

# ---------------- SLIDE 4 :