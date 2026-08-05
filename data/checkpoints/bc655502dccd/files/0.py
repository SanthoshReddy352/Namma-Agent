import subprocess, sys, os

OCLI = r"D:\OfficeCLI\officecli.exe"
DECK = r"C:\Users\santh\Desktop\Namma_Agent_Pitch_Deck.pptx"

# palette
BG    = "#FBFFFE"
INK   = "#6D676E"
LIGHT = "#B4B3B6"
AMBER = "#FAA613"
FONT  = "Calibri"

def run(args):
    r = subprocess.run([OCLI] + args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = (r.stdout + r.stderr).strip()
    if r.returncode not in (0, -1):
        print("ERR", args, "->", r.returncode, out)
    return out

def slide(bg=BG):
    run(["add", DECK, "/", "--type", "slide", "--prop", "layout=Blank", "--prop", f"background={bg}"])

def shape(sn, text, x, y, w, h, size=16, bold=False, color=INK, fill="none", align="left", font=FONT, ls=None, geom="rect"):
    p = ["add", DECK, f"/slide[{sn}]", "--type", "shape",
         "--prop", f"text={text}", "--prop", f"x={x}cm", "--prop", f"y={y}cm",
         "--prop", f"width={w}cm", "--prop", f"height={h}cm",
         "--prop", f"size={size}pt", "--prop", f"bold={str(bold).lower()}",
         "--prop", f"color={color}", "--prop", f"fill={fill}",
         "--prop", f"align={align}", "--prop", f"font={font}",
         "--prop", f"geometry={geom}"]
    if geom == "roundRect":
        p += ["--prop", "adj=adj:val 12000"]
    run(p)

def header(sn, kicker, title, title_size=28):
    # top accent bar
    shape(sn, "", 0, 0, 33.87, 0.32, fill=AMBER)
    # kicker
    shape(sn, kicker, 1.4, 0.95, 31, 0.9, size=13, bold=True, color=AMBER)
    # title
    shape(sn, title, 1.4, 1.7, 31, 1.6, size=title_size, bold=True, color=INK)
    # divider
    shape(sn, "", 1.4, 3.35, 31.07, 0.06, fill=LIGHT)

def footer(sn, total=12):
    shape(sn, "Namma Agent  ·  Pitch Deck", 1.4, 17.9, 20, 0.7, size=10, color=LIGHT)
    shape(sn, f"{sn:02d} / {total}", 28.5, 17.9, 4, 0.7, size=10, color=LIGHT, align="right")

# ---------------- Slide 1 : Title ----------------
slide(BG)
shape(1, "", 0, 0, 33.87, 0.32, fill=AMBER)
shape(1, "", 26.5, 2.2, 9.5, 9.5, fill="#FAA613+alpha12", geom="ellipse")
shape(1, "Namma Agent", 2.0, 5.6, 30, 2.2, size=60, bold=True, color=INK)
shape(1, "", 2.0, 8.15, 6.0, 0.18, fill=AMBER)
shape(1, "The trustworthy personal agent that measurably knows you — first-class on Windows.", 2.0, 8.7, 26, 2.0, size=21, color=INK)
shape(1, "Your Agent.  Your Advantage.", 2.0, 10.9, 26, 1.2, size=17, bold=True, color=AMBER)
# badges
badges = [("Self-hosted", 2.0), ("Open source · MIT", 8.6), ("~90 native tools", 16.2), ("Windows first-class", 24.4)]
for txt, bx in badges:
    shape(1, txt, bx, 12.6, 7.2, 1.5, size=13, bold=True, color=INK, fill="#B4B3B6+alpha30", geom="roundRect", align="center")
shape(1, "Namma Agent  ·  Pitch Deck  ·  2026", 2.0, 17.6, 20, 0.7, size=11, color=LIGHT)

# ---------------- Slide 2 : Problem ----------------
slide(BG)
header(2, "01  ·  THE PROBLEM", "Personal agents are having a trust crisis")
shape(2, "The category's public wound is real — prompt-injection exfiltration and hijacked always-on agents.\n\nBig vendors now advise treating agents as \u201cuntrusted code execution with persistent credentials.\u201d\n\nMost projects answer with features — almost nobody answers with auditable trust.\n\n\u201cIt remembers you\u201d is claimed by everyone; almost nobody publishes a number.",
  1.4, 3.7, 19.5, 12.5, size=17, color=INK, lineSpacing=None)
shape(2, "\u201cMost projects answer with features.\nNobody answers with auditable trust.\u201d", 22.0, 5.2, 10.5, 6.5, size=19, bold=True, color=AMBER, fill="#FAA613+14", geom="roundRect", align="center")
footer(2)

# ---------------- Slide 3 : Solution ----------------
slide(BG)
header(3, "02  ·  THE SOLUTION", "Meet Namma Agent — one API call, everything else is yours")
shape(3, "A self-hosted personal AI agent. The brain is a single API call to the model you choose; everything that makes it an agent lives in-process, on your machine.", 1.4, 3.6, 31, 1.9, size=16, color=INK)
cards3 = [
    ("Any brain", "Native Anthropic, OpenAI, Google — or any OpenAI-compatible endpoint (Ollama, LM Studio). Swap brains with one config key."),
    ("One agent loop", "generate \u2192 call tools \u2192 loop \u2192 answer, with ~90 native tools and native tool-calling. No intent regexes."),
    ("Yours, self-hosted", "No local-model stack, no Docker requirement, no vendor server holding your data. Runs anywhere Python does."),
]
cx = [1.4, 12.15, 22.9]
for (t, b), x in zip(cards3, cx):
    shape(3, "", x, 6.0, 9.5, 9.6, fill="#B4B3B6+26", geom="roundRect")
    shape(3, t, x+0.7, 6.7, 8.1, 1.2, size=19, bold=True, color=AMBER)
    shape(3, b, x+0.7, 8.1, 8.1, 6.6, size=14, color=INK)
footer(3)

# ---------------- Slide 4 : Four pillars ----------------
slide(BG)
header(4, "03  ·  THE POSITION", "Four pillars, one position")
pillars = [
    ("1", "Trust is a product surface", "Layered per-channel trust, injection screening, approval gate, sandboxed shell, secrets vault — on by default, visible live in the UI."),
    ("2", "Memory you can measure", "Engram: native, in-process, offline, SQLite. A published, reproducible recall benchmark — recall@5 = 92% — with a weekly trend line."),
    ("3", "Event-driven, not just scheduled", "Watchers on files, email, web, calendar. Cheap zero-LLM polls, an \u201conly if it matters\u201d gate, and it reaches you over Telegram."),
    ("4", "Windows is first-class", "Job-Object shell sandboxing, Credential Manager secrets, DPAPI-sealed fallbacks, and one-click installers — built on and for Windows."),
]
pos = [(1.4, 3.7), (17.0, 3.7), (1.4, 10.1), (17.0, 10.1)]
for (num, t, b), (x, y) in zip(pillars, pos):
    shape(4, x, y, 15.5, 5.6, fill="#B4B3B6+16", geom="roundRect")
    shape(4, num, x+0.6, y+0.55, 1.6, 1.6, size=22, bold=True, color=AMBER)
    shape(4, t, x+2.5, y+0.55, 12.2, 1.1, size=17, bold=True, color=INK)
    shape(4, b, x+2.5, y+1.75, 12.2, 3.9, size=13, color=INK)
footer(4)

# ---------------- Slide 5 : Trust ----------------
slide(BG)
header(5, "04  ·  TRUST", "Trust you can inspect")
shape(5, "\u2022  Per-channel sender trust — owner / trusted / untrusted\n"
   "\u2022  Injection screening on everything the agent reads (uploads, pages, search, RSS)\n"
   "\u2022  Approval gate with a decline audit trail — destructive tools always declined in autonomous runs\n"
   "\u2022  Sandboxed shell: Windows Job Object (memory cap, fork-bomb guard, kill-on-close)\n"
   "\u2022  Secrets vault: Credential Manager / keyring, with output redaction on every result and log\n"
   "\u2022  All on by default — observable live in Settings \u2192 System \u2192 Security",
   1.4, 3.7, 19.5, 12.5, size=15, color=INK)
layers = ["Per-channel trust", "Injection screening", "Approval gate", "Sandboxed shell", "Secrets vault"]
ly = 4.4
for i, l in enumerate(layers):
    fill = AMBER if i == 0 else ("#FAA613+30" if i == 1 else "#B4B3B6+30")
    shape(5, l, 22.3, ly, 10.2, 1.75, size=14, bold=True, color=INK, fill=fill, geom="roundRect", align="center")
    ly += 2.15
footer(5)

# ---------------- Slide 6 : Memory ----------------
slide(BG)
header(6, "05  ·  MEMORY", "Memory you can measure — Engram")
shape(6, "\u2022  Native, in-process, SQLite-backed — zero infrastructure, works fully offline\n"
   "\u2022  Instant identity: core memory injected into every turn, zero latency\n"
   "\u2022  Always learning: salience gate \u2192 extract \u2192 resolve (add / update / invalidate); facts are bi-temporal\n"
   "\u2022  Fast fused recall: BM25 + entity graph + optional vectors, in milliseconds\n"
   "\u2022  Transparent: the Memory tab shows every fact and entity — searchable, editable, live graph view",
   1.4, 3.7, 19.5, 12.5, size=15, color=INK)
shape(6, "", 22.3, 4.6, 10.2, 9.6, fill="#FAA613+16", geom="roundRect")
shape(6, "92%", 22.3, 5.4, 10.2, 2.6, size=52, bold=True, color=AMBER, align="center")
shape(6, "recall@5", 22.3, 8.2, 10.2, 1.2, size=20, bold=True, color=INK, align="center")
shape(6, "Offline retrieval benchmark — reproducible with no API key:\npython scripts/memory_eval.py --mock", 22.3, 9.6, 10.2, 3.0, size=12, color=INK, align="center")
footer(6)

# ---------------- Slide 7 : Proactive ----------------
slide(BG)
header(7, "06  ·  PROACTIVE", "It reaches out when things happen")
shape(7, "\u2022  Watchers: files, email, web pages, calendar — trigger + condition + action\n"
   "\u2022  Cheap zero-LLM polls; one \u201conly if it matters\u201d pass decides notify / act / ignore\n"
   "\u2022  Reaches you over Telegram, Discord, Slack, WhatsApp, Signal\n"
   "\u2022  Autonomous runs: destructive tools always declined; results delivered as scoped agent runs\n"
   "\u2022  Weekly self-review: mines transcripts \u2192 up to 5 proposals you approve — proposals, never actions",
   1.4, 3.7, 19.5, 12.5, size=15, color=INK)
flow = ["Event happens", "Zero-LLM poll", "\u201cDoes it matter?\u201d gate", "Notify / act", "You (Telegram)"]
fy = 4.4
for i, f in enumerate(flow):
    fill = AMBER if i == 4 else "#B4B3B6+30"
    shape(7, f, 22.3, fy, 9.2, 1.6, size=14, bold=True, color=INK, fill=fill, geom="roundRect", align="center")
    if i < 4:
        shape(7, "\u2193", 25.6, fy+1.6, 1.6, 0.9, size=16, bold=True, color=AMBER, align="center")
    fy += 2.5
footer(7)

# ---------------- Slide 8 : Capabilities ----------------
slide(BG)
header(8, "07  ·  CAPABILITIES", "~90 native tools, one agent loop")
chips = ["Files", "Shell / System", "Web", "Browser & Media", "Network", "Security",
         "Weather / News", "Smart home", "Vision", "Documents", "Memory (Engram)", "Projects",
         "Learning Room", "Skills", "Tasks & Goals", "Focus", "Comms", "Workspace",
         "MCP", "Self-authoring"]
cols, rows = 4, 5
cw, chh, gx, gy = 7.2, 1.7, 0.85, 0.7
x0, y0 = 1.26, 4.5
for i, c in enumerate(chips):
    r, col = divmod(i, cols)
    shape(8, c, x0 + col*(cw+gx), y0 + r*(ch+gy), cw, ch, size=13, bold=True, color=INK,
          fill="#B4B3B6+26", geom="roundRect", align="center")
shape(8, "Model calls tools natively — no intent regexes.  Add a capability = drop one file in namma_agent/tools/.",
   1.4, 16.4, 31, 1.0, size=13, color=INK)
footer(8)

# ---------------- Slide 9 : Comparison table ----------------
slide(BG)
header(9, "08  ·  THE FIELD", "How it compares (honestly)")
data = ("Feature,Namma Agent,Hermes,OpenClaw;"
        "Trust model,Layered, on by default, visible Security tab,Approval prompts; hosted gateway,Plugin permissions; hardening after incidents;"
        "Memory,Native in-process, measured \u2014 recall@5 = 92%,Curated files, unmeasured,Session + integrations;"
        "Proactivity,Watchers + routines,Scheduled routines,Scheduled + some triggers;"
        "Windows,First-class (Job Objects, Credential Manager),Linux & macOS first,macOS-leaning;"
        "Hosting,Self-hosted; $0 free-tier VPS,Self-hosted + hosted gateway,Self-hosted")
run(["add", DECK, "/slide[9]", "--type", "table", "--prop", "rows=6", "--prop", "cols=4",
     "--prop", f"data={data}", "--prop", "headerFill=#6D676E", "--prop", "bodyFill=#FBFFFE",
     "--prop", "colWidths=4.5cm,9.2cm,8.7cm,8.7cm", "--prop", "x=1.4cm", "--prop", "y=3.7cm",
     "--prop", "width=31.1cm", "--prop", "height=12.5cm"])
# header text white
for c in range(1, 5):
    run(["set", DECK, f"/slide[9]/table[1]/table-row[1]/table-cell[{c}]", "--prop", "font.color=#FBFFFE", "--prop", "bold=true"])
footer(9)

# ---------------- Slide 10 : Go to market ----------------
slide(BG)
header(10, "08  ·  GO TO MARKET", "Built to spread")
shape(10, "\u2022  MIT-licensed open source — code, docs, and the benchmark fully public\n"
   "\u2022  One-click installers: Windows (install.bat), macOS, Linux\n"
   "\u2022  Self-host anywhere — even a $0 Oracle free-tier VPS, ~30-minute walkthrough\n"
   "\u2022  Name your assistant anything — one config key, applied everywhere\n"
   "\u2022  Docs site (MkDocs + GitHub Pages), CI-built releases, winget packaging",
   1.4, 3.7, 19.5, 12.5, size=15, color=INK)
stats = [("MIT", "open-source license"), ("$0", "free-tier VPS hosting"), ("~30 min", "to deploy your own")]
sy = 4.6
for big, small in stats:
    shape(10, 22.3, sy, 9.2, 3.3, fill="#B4B3B6+26", geom="roundRect")
    shape(10, big, 22.3, sy+0.4, 9.2, 1.6, size=30, bold=True, color=AMBER, align="center")
    shape(10, small, 22.3, sy+2.0, 9.2, 1.0, size=12, color=INK, align="center")
    sy += 3.9
footer(10)

# ---------------- Slide 11 : Roadmap ----------------
slide(BG)
header(11, "07 ·  ROADMAP", "What's next")
shape(11, "\u2022  Harder memory evaluation — long-horizon recall, contradiction over weeks\n"
   "\u2022  Vector-embeddings channel to close the remaining recall gap\n"
   "\u2022  Community skills & self-review drafts maturing into a marketplace-lite\n"
   "\u2022  Deliberately few channels — each one is attack surface; harden before adding\n"
   "\u2022  Windows-first polish: Action-Center toasts, tray, autostart, winget, installer UX",
   1.4, 3.7, 19.5, 12.5, size=15, color=INK)
shape(11, "\u201cAn always-on agent you can audit — one that quarantines what strangers tell it, sandboxes what it runs, redacts your secrets, and shows you a number for how well it remembers you.\u201d",
   22.0, 5.0, 10.2, 6.5, size=17, bold=True, color=AMBER, fill="#FAA613+14", geom="roundRect", align="center")
footer(11)

# ---------------- Slide 12 : CTA ----------------
slide(BG)
header(12, "06 ·  GET STARTED", "Get started in minutes")
# code box
shape(12, "", 1.4, 4.2, 31.1, 4.4, fill=INK, geom="roundRect")
shape(12, "pip install -r namma_agent/requirements.txt\npython -m namma_agent --server\n\u2192  open  http://127.0.0.1:8000",
   2.2, 4.7, 29, 3.6, size=16, color="#FBFFFE", font="Consolas")
shape(12, "\u2022  One-click installers for Windows / macOS / Linux\n"
   "\u2022  Docs: ARCHITECTURE · SECURITY · BENCHMARKS · DEPLOY\n"
   "\u2022  GitHub: SanthoshReddy352  ·  MIT License",
   1.4, 9.4, 31, 4.0, size=15, color=INK)
shape(12, "Your Agent.  Your Advantage.", 1.4, 14.6, 31, 1.6, size=26, bold=True, color=AMBER, align="center")
footer(12)

run(["save", DECK])
print("DONE")