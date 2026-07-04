# Demo video script — "The Hangover Part AI: Where's My Context?"

The **narrative** for Namma Agent × Cognee — the story and the exact words. This is the
*what we say and why*; the click-by-click **shoot flow** is
[`RECORDING_GUIDE.md`](RECORDING_GUIDE.md) (follow that while recording). Two videos, one
per prize track (self-hosted 🅰 / Cognee Cloud 🅱) — same story, only the backend differs.

**Target length:** 3–4 min. **Tone:** a builder showing a real tool that finally
remembers. **Throughline:** Namma does *real work*, and Cognee is the thread that makes it
*compound* instead of resetting.

---

## The origin — why Cognee (the most important 30 seconds)

> Open the video with this. It's the "meaningful problem" judges score under **Potential
> Impact**, and it's true. Narrate it over the living graph (Shot 1) and the keyword-vs-
> Cognee Compare (Shot 2).

**Say:**
"I built Namma Agent as my personal AI assistant. From day one it had a memory — a single
**SQLite** database with **keyword search**. And for a while, that was fine.

Then it wasn't. I'd tell Namma *'I use Kuzu for my graph database,'* and the next day ask
*'which engine do I store relationships in?'* — and it drew a blank. Same fact, different
words, so keyword search found nothing. My memories sat in **isolated rows with no
relationships** — Namma could never connect the dots between my project, the tools I use,
and the decisions I'd made. The more it remembered, the **noisier** recall got. And every
new chat started **cold**. It was an assistant with amnesia.

I went looking for a real fix, and the **WeMakeDevs × Cognee** hackathon put **Cognee** in
front of me — a hybrid **graph + vector** memory engine that recalls by *meaning* and
*relationships*, with an actual lifecycle: **remember, recall, improve, forget**. It was
the exact missing piece. So I wired Cognee into Namma — through an MCP container, so it
adds **zero dependencies** and can never break the app — and finally gave Namma the memory
it always needed. This is what that looks like."

---

## Scene 1 — Cold open: the living memory (0:00–0:15)
**On screen:** Memory tab, the **knowledge graph** filling the frame. Drag a node, scroll
to zoom, hover to trace links.
**Say (over the origin intro above):** "This is Namma Agent's memory now — a living graph
of my life and my work. People, projects, the tools I use, all connected."

## Scene 2 — The money shot: keyword vs Cognee (0:15–0:40) ⭐
**On screen:** Memory tab → **Keyword vs Semantic** → `which engine do I use to store relationships?` → **Compare**.
**Point at:** left card **"Keyword search — No matches"**; right card **"Cognee — …Kuzu."**
**Say:** "Here's the before and after on one screen. On the left, exactly how Namma
remembered for months — keyword search over SQLite. Nothing, because I never typed the
word 'engine'. On the right, Cognee answers by meaning: **Kuzu**. That's the whole reason
I integrated it."

## Scene 3 — Real work #1: "Find me a PG" (0:40–1:15) ⭐
**On screen:** a **Chat**. Type:
*"I'm moving to Bengaluru next month — find me a PG near Koramangala under ₹12k with good food reviews."*
**Point at:** the activity timeline — `web_search` → `web_extract` → a ranked shortlist by
rating + food feedback — then Namma **remembering** your criteria.
**Say:** "But memory's only half of it — Namma does the *work*. It searched, read the
reviews, and ranked PGs by what I actually care about. And watch — it quietly **remembered
my criteria**: Koramangala, under twelve thousand, food matters. Next time, it won't ask."

## Scene 4 — Real work #2: "Break down my project" (1:15–1:50) ⭐
**On screen:** Chat. Type: *"Break the Namma hackathon submission into a plan I can finish solo before the deadline."*
**Point at:** the visible **`mcp_cognee_recall`** call, then `add_goal` / `add_task` steps.
**Say:** "Now watch it *use* what it knows. Before it plans anything, it **recalls from the
graph** — that I'm building this solo, the July 5 deadline, the two tracks — and builds the
plan around them. It recalled, then acted, then remembered the plan. That's an agent with a
memory, not a chatbot."

## Scene 5 — Real work #3: "Review this code" (1:50–2:20)
**On screen:** Chat. Type: *"Review the latest changes on this branch and flag anything risky."*
**Point at:** `run_shell` (git diff) / `read_file`, the review, then Namma **remembering
the decision**. Optional: ask *"what did I decide about the web UI?"* → it recalls.
**Say:** "It reviewed real code, flagged the risks, and stored what I decided. Memory
isn't just facts about me — it's the decisions I make, handed back exactly when they
matter."

## Scene 6 — The payoff: a fresh chat stitches the whole week (2:20–2:50) ⭐⭐
**On screen:** **New chat**, zero history. Type: *"Good morning — what should I focus on today?"*
**Point at:** `mcp_cognee_recall`, then an answer that weaves the move, the plan + deadline,
and the code-review TODO into one.
**Say:** "This is the part that matters. A brand-new chat, no history — and Namma stitches
together my entire week: the move, the project plan, the code review, the people. Because
it all lives in one graph, **nothing resets**. That's the hangover, cured."

## Scene 7 — Improve: the graph grows live (2:50–3:10)
**On screen:** Memory → **Remember** (untick *Build into graph*, add two quick notes) →
**Improve memory** → **Consolidate** → ↻ Refresh → new nodes appear.
**Say:** "Remember, recall, **improve**, forget — the full lifecycle. Consolidate runs
Cognee's cognify pipeline — entity extraction and linking — and the graph tightens live."

## Scene 8 — One codebase, two tracks (3:10–3:30) ⭐
**On screen:** Settings → MCP → **Cognee → Backend** → flip **Self-hosted ⇄ Cloud**.
**Say (🅰 self-hosted video):** "And everything you just saw ran **100% on my machine** —
Kuzu, local embeddings, no API keys. That's the open-source track. The same code is one
click from managed cloud."
**Say (🅱 cloud video):** "One switch — the **same code**, now on **managed Cognee Cloud**.
Zero local infrastructure, the same graph, every op against the cloud. And it runs fully
self-hosted if you want it."

## Scene 9 — Forget + the close (3:30–3:45)
**On screen:** Memory → **Forget** → the graph empties.
**Say:** "Remember. Recall. Improve. Forget — a complete memory lifecycle, powered by
Cognee. Namma Agent never wakes up with a hangover again."

## Scene 10 — Under the hood (tag, 3:45–4:00)
**On screen:** `pytest -q` → **506 passed**; the architecture diagram from
[`SUBMISSION.md`](SUBMISSION.md).
**Say:** "Under the hood: Cognee runs containerized through Namma's MCP client — zero
Python dependencies, and it can't degrade the app. One codebase, both tracks. Five hundred
and six offline tests, green."
**End card:** repo URL + "Built with Cognee · WeMakeDevs — *The Hangover Part AI*" + track name.

---

## The two backends (both live)

Same Namma code, same Memory tab, same graph — only the backend differs, and the seed
builds an identical demo graph on each (`--backend both`).
- 🅰 **Best Use of Open Source** — cognee-mcp container → Ollama → Kuzu + LanceDB + SQLite, 100% local.
- 🅱 **Best Use of Cognee Cloud** — the same image in serve mode against managed cloud;
  graph synced from the cloud REST API. **Access reopens July 2, 2026** (confirmed) → both
  videos recorded live.

## Capture checklist
- [ ] Origin story recorded (SQLite → its problems → discovering Cognee → the fix).
- [ ] Money shot (keyword empty / Cognee answers Kuzu).
- [ ] Real work: PG-finder, project breakdown, code review — each with the visible tool calls.
- [ ] Payoff: fresh chat stitches the week via `mcp_cognee_recall`.
- [ ] All four ops named on screen (remember · recall · improve/memify · forget).
- [ ] Backend switch (one codebase, two tracks) with the right VO per video.
- [ ] 506 tests + architecture tag.
