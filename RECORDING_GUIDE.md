# 🎬 Recording guide — the EXACT shoot flow (spoon-fed, both tracks)

Follow this **top to bottom** and you will have **two winning videos**. Every shot tells you
the **SCREEN** to be on, the **exact DO** (click/type), **what you'll SEE**, the **words to
SAY** (voice-over), and **when to RETAKE**. The story/why is in [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md).

## 🅰 vs 🅱 — you are making TWO videos

| | 🅰 **Self-hosted** (Best Use of Open Source) | 🅱 **Cloud** (Best Use of Cognee Cloud) |
|---|---|---|
| Backend | Cognee runs in Docker on your PC (Kuzu + LanceDB + local embeddings) | Managed **Cognee Cloud** (`platform.cognee.ai`) |
| The video | **Core shots 1–10** (the Namma app) with the 🅰 voice-over | **Core shots 1–10** with the 🅱 voice-over **+ the [Cloud Platform Tour](#part-3--cloud-platform-tour-c1c8--track-b-only) (C1–C8)** |
| What's unique | "The open-source engine, running on my machine" | "My agent's memory, fully managed & observable in the cloud console" |

> **Both tracks share the same Core shots 1–10.** The **🅱 cloud video wins on the Platform
> Tour** — a guided walk through the Cognee Cloud console proving Namma's memory is a live,
> managed, observable knowledge base. That tour (Part 3) is the cloud track's crown jewel.

**Shooting order:** record **🅰 self-hosted in full first** (Parts 0–2), then switch the
backend to cloud (Part 4) and shoot **🅱** = the same core shots' backend chrome **+ the
Platform Tour**.

## Three golden rules (apply to every shot)
1. **Picture first, voice-over (VO) later.** Don't talk while clicking. Record clean screen
   captures, then read the **SAY** lines over the finished cut.
2. **One shot = one file.** `shot01.mp4`, `shot02.mp4`, … (cloud tour: `C1.mp4`…). Retakes stay easy.
3. **2 seconds of padding** before and after each action — you'll trim in editing.

---

## 🧭 How the shoot works — READ THIS FIRST (2-minute read)

**You film a silent screen recording, then add your voice on top afterwards.** Nothing is
narrated live. There are **two passes:**

- **Pass 1 — PICTURE (silent).** You screen-record yourself doing the clicks/typing for each
  shot, in order, **saying nothing**. This is your "footage." One file per shot (`shot01.mp4`…).
- **Pass 2 — VOICE-OVER (VO).** *After* the picture is cut together, you sit in a quiet room and
  **read a script out loud**, and lay that voice track *over* the silent footage. "VO" =
  voice-over = the narration. You are **never** talking while clicking.

**So what is the "SAY" line under each shot?** It is simply **that shot's VO script** — the exact
words you read over that shot's picture in Pass 2. That's all "SAY" means.

**Then what is the "origin intro VO" in Part 1?** Same thing — a VO script — just a **longer,
flowing paragraph** that plays over the **first two shots** (the graph + the money shot) to open
the video with your story. Think of it as the SAY lines for Shots 1–2 written out as one smooth
narration. On the final cut, use *either* the flowing origin paragraph *or* the two short SAY
bites for Shots 1–2 — they cover the same beats; pick whichever sounds better.

**The whole flow, start to finish:**
1. Do the **Setup** (Part 0) and hit the green-light gate (10/10).
2. **Pass 1 — picture:** record every shot silently, in order. Retake anything ugly.
3. **Edit:** drop the clips on a timeline in order (Part 5), speed-ramp the waits, no dead air.
4. **Pass 2 — VO:** read each shot's **SAY** (and the origin paragraph) in a quiet take; lay
   each voice clip over its shot.
5. Add captions + soft music + an end card. Export. Done.

> **Why separate them?** It's far easier to click calmly without fumbling words, then narrate
> cleanly without fumbling clicks. Every polished screen-demo is cut this way.

---

## 🎥 One story → TWO videos: what to REUSE, what to RE-SHOOT

You're entering two tracks, so you need two videos — but they're **~85% the same footage.** The
only differences: (a) **which backend is connected** (self-hosted vs cloud — and that's only
*visible* on a few screens), (b) **2–3 VO lines**, and (c) the cloud video adds the Platform Tour.

**The one rule:** *re-shoot a shot only if the backend name is visibly on screen in it.*
Everything else is identical — reuse the exact same file.

| Shot | What's on screen | Going 🅰 → 🅱 |
|---|---|---|
| 1 Graph | Memory tab (header may read "Connected · Self-hosted/Cloud") | **Re-shoot background** (graph itself looks the same) |
| 2 Money shot | Memory tab, same header | **Re-shoot background** |
| 3 PG · 4 Plan · 5 Review · 6 Payoff | just the **chat** — no backend text | ✅ **Reuse the same clips** (chat looks identical either way) |
| 7 Improve | Memory tab, header | **Re-shoot background** |
| 8 Backend toggle | shows Self-hosted ⇄ Cloud | **Re-shoot + different SAY line** |
| 9 Forget | Memory tab | **Re-shoot** (or reuse if the header isn't in frame) |
| 10 Under the hood | terminal + diagram | ✅ **Reuse** (identical) |
| **C1–C8 Platform Tour** | platform.cognee.ai console | 🆕 **Cloud video ONLY — all new** |

**In plain words:**
1. **Shoot 🅰 (self-hosted) completely first** — all of Shots 1–10, picture + VO. That's your
   finished **Track A** video.
2. **For 🅱 (cloud):** switch the backend to Cognee Cloud, then **re-record only the shots where
   the backend name shows** (1, 2, 7, 8, 9 — mostly just the Memory-tab background), **re-read
   the 2–3 cloud VO lines** (Shot 8 changes; the origin line stays the same), and **reuse the
   chat Shots 3–6 and Shot 10 untouched.** Then **shoot the whole Platform Tour (C1–C8)** — the
   new, cloud-only centerpiece. Assemble → your **Track B** video.

That's the whole trick: shoot the story once, swap a few backgrounds + VO lines, add the cloud
tour. Two videos.

---

# Table of contents
- [🧭 How the shoot works (read first)](#-how-the-shoot-works--read-this-first-2-minute-read)
- [🎥 Two videos: reuse vs re-shoot](#-one-story--two-videos-what-to-reuse-what-to-re-shoot)
- [Part 0 — Setup (once per session)](#part-0--setup-do-this-once-per-session)
- [Part 1 — Origin intro VO (shared)](#part-1--the-origin-intro-voice-over-shared-by-both-videos)
- [Part 2 — Core shots 1–10 (both tracks)](#part-2--core-shots-110-both-tracks)
- [Part 3 — Cloud Platform Tour C1–C8 (🅱 only)](#part-3--cloud-platform-tour-c1c8--track-b-only)
- [Part 4 — Make the SECOND (cloud) video](#part-4--make-the-second-cloud-video-)
- [Part 5 — Assembly (edit each cut)](#part-5--assembly-edit-the-cut)
- [Part 6 — Pre-flight checklists](#part-6--pre-flight-checklists-per-track)
- [Part 7 — Backup queries & troubleshooting](#part-7--backup-queries--troubleshooting)

---

## PART 0 — Setup (do this once per session)

### 0.1 Recording tools (Windows)
- **OBS Studio** → **Display Capture** (or Window Capture of the browser). Output **1920×1080,
  30 fps, MP4**.
- **PowerToys → Mouse utilities** → turn **ON** *Mouse Highlighter* + *Find My Mouse*.
- A **mic** for VO (recorded last, over the finished picture).

### 0.2 Start Namma
Open a terminal in `D:\AGI`:
```powershell
scripts\setup_cognee.ps1        # first time only — Docker + Ollama + the cognee image
python -m namma_agent --server  # leave this running the whole session
```
Open **http://127.0.0.1:8000** in Chrome/Edge → **F11** (fullscreen) → zoom **100%** → hide
the bookmarks bar.

### 0.3 Connect the backend for the track you're shooting

**🅰 Self-hosted:**
1. **Settings (gear) → MCP → Cognee → Backend → Self-hosted** → **Reconnect**.
2. Wait for the **green "Connected"** dot (~20–30 s; a fresh volume runs a one-time DB
   migration ~30–60 s — if the first connect fails, click **Reconnect** once more).

**🅱 Cloud:**
1. **Settings → MCP → Cognee → Backend → Cognee Cloud**.
2. Paste your **Instance URL** `https://<your-id>.cognee.ai` + **API key** (from
   platform.cognee.ai, dev plan code `COGNEE-35`) → **Connect to Cognee Cloud**.
   *(You only paste these **once** — the URL and key are now remembered and pre-filled on every
   later connect, even after you switch to Self-hosted and back.)*
3. Wait for **"Connected · Cognee Cloud"** (✂ the ~25 s reconnect in editing).

**Both tracks — Behaviour section (leave these):**
- *Auto-ingest chats* → **ON**
- *Recall in chat* → **OFF** — so the recall tool-call is **visible on camera** in Shots 4 & 6.
  (Only turn it ON if a dry-run doesn't recall.)
- Close Settings.

### 0.4 Seed the graph + verify — **THE GREEN-LIGHT GATE**
In a **second** terminal (keep the app running):

**🅰 Self-hosted:**
```powershell
python scripts\seed_demo_memory.py --backend local --reset --stress
```
**🅱 Cloud:**
```powershell
python scripts\seed_demo_memory.py --backend cloud --serve-url https://<your-id>.cognee.ai --reset --stress
```
**Do not record until you see `✅ All questions land` (10/10).** That is your green light.
Expect **~100+ entities · ~190+ links**. Seeding takes a few minutes.

> **Seed BOTH backends in one go** (handy so every clip works on either video):
> `python scripts\seed_demo_memory.py --backend both --serve-url https://<your-id>.cognee.ai --reset --stress`
>
> **Retakes:** re-verify fast with `python scripts\seed_demo_memory.py --stress-only`
> (no rebuild). Use `--reset --stress` only for a full fresh rebuild.

### 0.5 Open the tabs you'll use (in the Namma app)
- **Memory tab** (left sidebar, graph icon) → click **↻ Refresh** → you should see a **dense,
  connected graph**.
- A **Chat tab** ready (you'll click **New chat** when a shot says so).

### 0.6 Rehearse the 3 live task shots ONCE (Shots 3, 4, 5)
These call live tools (`web_search`, `git diff`) and aren't 100% deterministic. Run each once
now, **off-camera**, so there are no surprises. If a live result is ugly on the real take,
you're allowed to **VO over a good pre-recorded take** — just keep the typed query identical.

### 0.7 🅱 Cloud only — open the Cognee Cloud console & dry-run the 7 pages
After the **cloud** seed lands (0.4), open **https://platform.cognee.ai** and sign in with the
account tied to your API key. Click through these once to confirm each is **populated** before
you shoot the [Platform Tour](#part-3--cloud-platform-tour-c1c8--track-b-only):
`/dashboard` · `/datasets` · `/knowledge-graph` · `/search` · `/schema` · `/sessions` · `/skills`.
You should see the **`namma_agent_memory`** brain everywhere. (Sessions/Skills may be empty —
Part 3 tells you how to populate them.)

---

## PART 1 — The origin intro (voice-over, shared by both videos)

The video **opens** with this origin story, narrated over Shot 1 (the graph) and Shot 2 (the
Compare). Record the VO after you've shot 1 & 2. **Read it exactly:**

> "I built Namma Agent as my personal AI assistant. From day one it had a memory — a single
> **SQLite** database with **keyword search**. And for a while, that was fine.
>
> Then it wasn't. I'd tell Namma *'I use Kuzu for my graph database,'* and the next day ask
> *'which engine do I store relationships in?'* — and it drew a blank. Same fact, different
> words, so keyword search found nothing. My memories sat in **isolated rows with no
> relationships**. The more it remembered, the **noisier** recall got. And every new chat
> started **cold**. It was an assistant with amnesia.
>
> Then the **WeMakeDevs × Cognee** hackathon put **Cognee** in front of me — a hybrid
> **graph + vector** memory engine that recalls by *meaning* and *relationships*, with a real
> lifecycle: remember, recall, improve, forget. It was the exact missing piece. So I wired it
> into Namma — through an MCP container, so it adds **zero dependencies** and can never break
> the app. This is what that looks like."

---

## PART 2 — Core shots 1–10 (both tracks)

For each shot: get on the **SCREEN**, do the **DO**, confirm **YOU SEE**, then read **SAY** as
VO. **CUT** = speed up that wait in editing. **RETAKE IF** = redo it. Lines marked 🅰/🅱 differ
by track.

---

### 🎬 Shot 1 — Cold open: the living graph (~12 s)
**SCREEN:** Namma **Memory tab**, graph filling the frame.
**DO:** 1) Click-drag one node slowly. 2) Scroll to zoom in. 3) Hover a busy node (*namma
agent* or *santhosh*) so its links light up.
**YOU SEE:** a smooth, dense, glowing web of connected nodes.
**SAY (origin VO continues):** "This is Namma Agent's memory now — a living graph of my life
and my work. People, projects, the tools I use, all connected."
**RETAKE IF:** the graph looks sparse → re-run 0.4, then ↻ Refresh.
**NEXT:** stay on the Memory tab.

---

### 🎬 Shot 2 — The money shot: keyword vs Cognee (~22 s) ⭐ MOST IMPORTANT
**SCREEN:** Memory tab → scroll to the **Keyword vs Semantic** panel.
**DO:** 1) Click the input. 2) Type exactly: `which engine do I use to store relationships?`
3) Click **Compare**. Wait ~1–5 s.
**YOU SEE:** **Left card → "Keyword search — No matches."** **Right card → "Cognee — …Kuzu."**
**SAY:** "Here's the before and after on one screen. On the left, exactly how Namma remembered
for months — keyword search over SQLite. Nothing, because I never typed the word 'engine'. On
the right, Cognee answers by meaning: **Kuzu**. That's the whole reason I integrated it."
**RETAKE IF:** the **left** card shows a hit → that keyword is in SQLite; use a backup query
from [Part 7](#part-7--backup-queries--troubleshooting).
**NEXT:** click **New chat**.

---

### 🎬 Shot 3 — Real work #1: "Find me a PG" (~35 s) ⭐
**SCREEN:** a fresh **Chat**.
**DO:** Type exactly (one line), then **Enter**:
`I'm moving to Bengaluru next month — find me a PG near Koramangala under ₹12k with good food reviews.`
**YOU SEE:** tool steps **`web_search` → `web_extract`**, then a **ranked shortlist** of PGs
with one-line reasons, then a **`remember`** step (or auto-ingest) saving your criteria.
**SAY:** "But memory's only half of it — Namma does the *work*. It searched, read the reviews,
and ranked PGs by what I actually care about. And watch — it quietly **remembered my
criteria**: Koramangala, under twelve thousand, food matters. Next time, it won't ask."
**CUT:** speed-ramp the search wait. **RETAKE IF:** result is junk → VO over your rehearsed
take (0.6); keep the query identical for both videos.
**NEXT:** stay in this chat (or New chat — either is fine).

---

### 🎬 Shot 4 — Real work #2: "Break down my project" (~35 s) ⭐
**SCREEN:** a **Chat**.
**DO:** Type exactly, then **Enter**:
`Break the Namma hackathon submission into a plan I can finish solo before the deadline.`
**YOU SEE:** a visible **`mcp_cognee_recall`** step ("Recalled from Cognee memory…"), then
**`add_goal` / `add_task`** steps, then a plan built around what it knows — the **two tracks**,
the **July 5** deadline, the components (record the demo, polish the Memory tab, write the README).
**SAY:** "Now watch it *use* what it knows. Before it plans anything, it **recalls from the
graph** — that I'm building this solo, the two tracks, the July 5 deadline — and builds the
plan around them. It recalled, then acted, then remembered the plan. That's an agent with a
memory, not a chatbot."
**CUT:** trim think time. **RETAKE IF:** no recall step → Settings → Cognee → Behaviour →
*Recall in chat* **ON**, retake.
**NEXT:** stay in chat.

---

### 🎬 Shot 5 — Real work #3: "Review this code" (~30 s)
**SCREEN:** a **Chat**.
**DO:** 1) Type exactly, then **Enter**: `Review the latest changes on this branch and flag
anything risky.` 2) (Optional follow-up) `what did I decide about the web UI?`
**YOU SEE:** a **`run_shell`** (git diff) / **`read_file`** step, a concrete review with risks +
fixes, then a **`remember`** step storing the decision. The follow-up triggers a **`recall`**.
**SAY:** "It reviewed real code, flagged the risks, and stored what I decided. Memory isn't
just facts about me — it's the decisions I make, handed back exactly when they matter."
**CUT:** speed the diff/think waits. **RETAKE IF:** no diff (clean branch) → make a tiny edit
to any file first.
**NEXT:** click **New chat** (the next shot needs an empty chat).

---

### 🎬 Shot 6 — The payoff: a fresh chat stitches the week (~30 s) ⭐⭐ THE WINNING SHOT
**SCREEN:** a brand-**New chat**, zero history.
**DO:** Type exactly, then **Enter**: `Good morning — what should I focus on today?`
**YOU SEE:** a visible **`mcp_cognee_recall`** step, then an answer that **weaves everything**:
the move + PG criteria, the project plan + July 5 deadline, the code-review TODO.
**SAY:** "This is the part that matters. A brand-new chat, no history — and Namma stitches
together my entire week: the move, the project plan, the code review. Because it all lives in
one graph, **nothing resets**. That's the hangover, cured."
**CUT:** trim think time. **RETAKE IF:** answer is generic → *Recall in chat* **ON**, retake.
**Dry-run this one twice before the real take.**
**NEXT:** go to the Memory tab.

---

### 🎬 Shot 7 — Improve: the graph grows live (~22 s)
**SCREEN:** Memory tab → the **Remember** and **Improve memory** cards.
**DO:** 1) In **Remember**, **untick "Build into graph."** 2) Type `I just started learning
Rust for a side project.` → **Remember**. 3) Type `My side project is a CLI tool called Tally.`
→ **Remember**. 4) **Improve memory** now shows **"2 pending"** → click **Consolidate 2 into
graph**. 5) Wait for "Consolidated 2 of 2…" (cognify). 6) Graph **↻ Refresh** → new nodes
(**rust, tally, side project**) appear.
**YOU SEE:** pending badge → consolidate confirmation → new nodes after refresh.
**SAY:** "Remember, recall, **improve**, forget — the full lifecycle. Consolidate runs Cognee's
cognify pipeline — entity extraction and linking — and the graph tightens live."
**CUT:** speed the consolidate wait 4–8× or jump-cut to the refreshed graph.
**RETAKE IF:** no new nodes → ↻ Refresh again (cognify may still be finishing).
**NEXT:** Settings → MCP → Cognee → Backend.

---

### 🎬 Shot 8 — One codebase, two tracks (~25 s) ⭐ (VO differs per video)
**SCREEN:** Settings → MCP → **Cognee → Backend**.
**DO:** 1) Hover the **Self-hosted ⇄ Cloud** toggle so both options show. 2) (Dramatic, optional)
flip it once and let it reconnect — **CUT** the ~25 s reconnect.
**YOU SEE:** the same Memory tab/graph available under either backend.
**SAY (🅰 self-hosted):** "And everything you just saw ran on **my own machine** — the
open-source **Cognee** engine: **Kuzu** graph store, **LanceDB** vectors, and **local
embeddings**. That's the open-source track. The same code is one click from managed cloud."
**SAY (🅱 cloud):** "One switch — the **same code**, now on **managed Cognee Cloud**. Zero local
infrastructure, the same graph, every op against the cloud. And it runs fully self-hosted if I
want it."
**NEXT (🅱):** this is your bridge into the **[Cloud Platform Tour](#part-3--cloud-platform-tour-c1c8--track-b-only)** — jump to the browser and platform.cognee.ai.
**NEXT (🅰):** go to the Memory tab → Forget card (Shot 9).

> **Honesty note (both tracks):** the extraction/recall **LLM** is a hosted model (OpenCode
> `big-pickle`), so don't claim "no API keys." What's genuinely local on 🅰 is the **Cognee
> engine itself** — Kuzu, LanceDB, and the embeddings. That's the accurate open-source story.
> (Want a literally key-free 🅰? Re-pull `qwen2.5:7b` and use the commented local-LLM block in
> `.env.cognee` — slower recall, but "no API keys" becomes true.)

---

### 🎬 Shot 9 — Forget + close (~12 s)
**SCREEN:** Memory tab → the **Forget** card (bottom).
**DO:** (Optional, only after every other shot is done) click **Forget everything** → confirm →
the graph empties. *Or* just show the card while narrating.
**YOU SEE:** the graph clears (proves forget).
**SAY:** "Remember. Recall. Improve. Forget — a complete memory lifecycle, powered by Cognee.
Namma Agent never wakes up with a hangover again."
**AFTER THIS SHOT:** re-seed for any retakes (0.4).

---

### 🎬 Shot 10 — Under the hood (tag, ~10 s)
**SCREEN:** a terminal + the architecture diagram.
**DO:** 1) Off-camera, run `python -m pytest namma_agent/tests/ -q` and **screen-record the
green `528 passed` line** (✂ speed the run). 2) Capture the **mermaid architecture diagram**
from [`SUBMISSION.md`](SUBMISSION.md) (a still is fine).
**SAY:** "Under the hood: Cognee runs containerized through Namma's MCP client — zero Python
dependencies, and it can't degrade the app. One codebase, both tracks. **Five hundred and
twenty-eight** offline tests, green."
**Place** this as a tag over Shot 8 or the close.

---

## PART 3 — Cloud Platform Tour (C1–C8) — Track B only 🅱

**This is what wins "Best Use of Cognee Cloud."** After Shot 8 flips to cloud, leave the Namma
app and open **https://platform.cognee.ai**. This tour proves Namma's memory isn't a black box
— it's a **live, managed, observable knowledge base** you can browse, search, inspect, and
audit in the Cognee Cloud console. Everything here is the **same `namma_agent_memory` brain**
your agent writes to.

> **Before shooting:** finish the **cloud seed** (0.4 🅱) and the **dry-run** (0.7). Each page
> below should already show your data. Shoot these as `C1.mp4`…`C7.mp4`.

**Bridge VO (say once, over the switch from Namma to the browser):**
> "And because Namma's memory now lives on **Cognee Cloud**, I don't just get a backend — I get
> a whole managed console for it. Let me show you my agent's brain, in the cloud."

---

### 🎬 C1 — Dashboard: the memory command center (~25 s) ⭐
**SCREEN:** `platform.cognee.ai/dashboard`.
**DO:** 1) Slowly pan across the **six counters** (agents · sessions (24h) · API requests ·
**graph entities** · **relationships** · datasets). 2) In the **"Search your memory"** terminal,
type `which engine do I use to store relationships?` → **Enter**. 3) Look at the **Memory
Activity** feed below — your query appears as a new row with a **green success badge**; click it
to **expand** the query + reasoning.
**YOU SEE:** live counts (**100+ entities, 190+ relationships, 1 dataset**), and your search
landing in the activity log in real time.
**SAY:** "This is Namma's memory in Cognee Cloud — every entity, every relationship, and every
search, in one managed dashboard. I ask it a question right here, and it lands in the **live
activity log**, with the answer and the reasoning. My agent's memory is completely observable."
**RETAKE IF:** counters read 0 → the cloud seed didn't land; re-run 0.4 🅱 and Refresh.
**NEXT:** left nav → **Datasets**.

---

### 🎬 C2 — Datasets (Brains): where the memories live (~25 s) ⭐
**SCREEN:** `/datasets`.
**DO:** 1) Left column → click the **`namma_agent_memory`** brain (green **"Ready"** dot). 2)
Right column → scroll the **ingested documents** (your seeded facts) — each shows type/size/date.
3) (Optional, great beat) click **add text**, paste `My favourite editor is Neovim.`, submit →
watch the status pill go **Processing → Ready** (add + cognify runs in the background).
**YOU SEE:** the brain with its documents; a new note being cognified into the graph live.
**SAY:** "Every memory Namma writes becomes a document in this **brain**, and Cognee Cloud runs
the **add-and-cognify pipeline** on it automatically — turning raw text into graph. I can even
drop a note in here and it's memory in seconds."
**RETAKE IF:** brain shows a red/amber dot → still processing; wait for green or ↻ Refresh.
**NEXT:** left nav → **Knowledge Graph**.

---

### 🎬 C3 — Knowledge Graph: the payoff visual, hosted (~20 s) ⭐
**SCREEN:** `/knowledge-graph`.
**DO:** 1) Select the **`namma_agent_memory`** brain (status pill **green/Ready**). 2)
Drag a node; **scroll to zoom**; **hover** *santhosh* / *namma agent* to reveal labels + entity
types.
**YOU SEE:** the same dense graph as Namma's Memory tab, now rendered **natively by Cognee Cloud**.
**SAY:** "And here's the graph itself, hosted and rendered by Cognee Cloud — the exact same web
of people, projects, and tools that powers Namma's recall, now living entirely in the managed
cloud. Nodes are entities Cognee extracted; edges are the relationships between them."
**RETAKE IF:** empty → status pill not Ready yet, or wrong brain selected → Refresh.
**NEXT:** left nav → **Search**.

---

### 🎬 C4 — Search: recall, straight from the cloud (~25 s) ⭐
**SCREEN:** `/search`.
**DO:** 1) **Scope pill → Company Brain**; **Searching:** dropdown → `namma_agent_memory`. 2)
Type `what does the part of my app that users actually see run on?` → **Enter**. 3) (Optional)
show the **suggestion chips** ("What are the main entities?") and click one.
**YOU SEE:** a natural-language answer (**React**) synthesized from the graph — the same recall
Namma uses in chat, in the cloud console. Past searches list in the left sidebar.
**SAY:** "This is **recall**, straight from the cloud console. The same graph-completion that
answers Namma in chat, I can run right here against my managed memory — by **meaning**, across
**relationships**. Ask it anything about my life and it answers from the graph."
**RETAKE IF:** an "upgrade" banner blocks the input → your plan lapsed; the dev plan
(`COGNEE-35`) must be active.
**NEXT:** left nav → **Schema**.

---

### 🎬 C5 — Schema: memory with structure (~22 s) ⭐
**SCREEN:** `/schema` (Memory Schema).
**DO:** 1) Select the **`namma_agent_memory`** brain. 2) Let the **schema-view** render —
**entity types** as nodes (Person, Project, Tool, Event…), **relations** as edges. 3) Open the
**Model / Prompt / Ontology** dropdowns in the toolbar to show they're configurable (don't
re-process on camera unless you want to show it rebuild).
**YOU SEE:** the **inferred ontology** of Namma's memory + the extraction controls.
**SAY:** "Cognee doesn't just store text — it **infers a schema**. Here are the entity types and
relationships it pulled from my life: person, project, tool, event. I can even swap the
**ontology** and re-process. That's memory with structure, not a pile of notes."
**RETAKE IF:** empty state ("add files first") → the brain has no data yet; finish the seed.
**NEXT:** left nav → **Sessions**.

---

### 🎬 C6 — Sessions: full observability into agent memory (~22 s)
**SCREEN:** `/sessions`.
**POPULATE IT FIRST (important):** the Sessions page fills from agent activity tagged with a
`session_id`. The easiest reliable trigger: in Namma's Memory tab do a **Remember with
"Build into graph" OFF** (that writes a `namma_ui` session), *or* run a chat turn, **then**
open Sessions and ↻ Refresh. If it's still empty, narrate C1/C2 instead and skip this shot.
**DO:** 1) Show the **session list** — each row: status dot, **model**, message/tool/token
counts, **USD cost**. 2) Click a session → show the **Recall / Remember** transcript (reads vs
writes) and the **traces bar chart** (which tools it used most).
**YOU SEE:** Namma's memory sessions, split into what it **recalled** vs **remembered**, with
token + cost analytics.
**SAY:** "Every time Namma touches memory, Cognee Cloud logs the **session** — what it recalled,
what it remembered, which tools it used, even the token cost. That's full observability into my
agent's memory, out of the box."
**RETAKE IF:** empty → do the "populate it first" step above, or skip (optional shot).
**NEXT:** left nav → **Skills**.

---

### 🎬 C7 — Skills: procedural memory as a graph (~22 s)
**SCREEN:** `/skills`.
**POPULATE IT FIRST (optional):** click **Upload skill**, drop a short markdown playbook into
the **`namma_agent_memory`** brain (e.g. a 3-line `pg-hunt.md`: *"When asked to find housing:
web_search the area, web_extract reviews, rank by budget + food, then remember the criteria."*).
**DO:** 1) Show the skills browser (brains with skills → skills by maintainer, with version/
license). 2) **Expand** a skill to reveal its **instruction body** + **declared tools**.
**YOU SEE:** a skill registered as **structured, graph-linked procedural memory** — not a loose
markdown file.
**SAY:** "Cognee Cloud even turns Namma's **skills** — its procedural playbooks — into
structured memory: the instructions, the tools it can call, routed by what's worked before.
Memory that doesn't just remember **facts**, but **how to do things**."
**RETAKE IF:** page empty and you don't want to upload → narrate the concept over C3's graph, or
cut this shot.
**NEXT:** back to the Namma app for Shot 9 (Forget), or straight to the close.

---

### 🎬 C8 — Cloud close (~12 s) ⭐
**SCREEN:** back on `/dashboard` (or the knowledge graph).
**SAY:** "One config entry pointed Namma at Cognee Cloud — and my agent's entire memory became
a **managed, searchable, observable** knowledge base: datasets, a live graph, semantic search,
an inferred schema, session analytics, even skills. **Zero infrastructure, total visibility.**
That's Namma Agent on Cognee Cloud."

---

## PART 4 — Make the SECOND (cloud) video 🅱

You do **not** re-shoot the whole story. From your finished 🅰 footage:

1. **Switch + seed cloud** (0.3 🅱 + 0.4 🅱) → wait for **✅ 10/10**.
2. **Re-shoot only these core backgrounds** with the cloud backend connected (so the chrome
   reads "Connected · Cognee Cloud" and the graph is **synced from the cloud REST API** —
   ↻ Refresh if empty):
   - **Shots 1, 2, 7, 9** backgrounds, and **Shot 8** with the **🅱 VO**.
3. **Reuse Shots 3–6** (the conversational tasks — backend-agnostic) from Track A, *or* re-run
   them on cloud if you want the timeline chrome to read "cloud."
4. **Shoot the whole [Cloud Platform Tour](#part-3--cloud-platform-tour-c1c8--track-b-only)
   (C1–C8)** — this is the 🅱 video's centerpiece and biggest differentiator.
5. **Re-record the VO** with the 🅱 lines where they differ (origin intro is identical; Shot 8
   changes; the platform tour is all-new).

---

## PART 5 — Assembly (edit the cut)

**🅰 Self-hosted video order:**
origin VO over **1 → 2**, then **3 → 4 → 5 → 6 → 7 → 8🅰 → 9**, with **10** as a tag over 8/9.

**🅱 Cloud video order:**
origin VO over **1 → 2**, then **3 → 4 → 5 → 6 → 7 → 8🅱**, then the **bridge VO into the
Platform Tour: C1 → C2 → C3 → C4 → C5 → C6 → C7 → C8**, then **9**, with **10** as a tag.
*(The tour is the climax of the cloud video — give it room.)*

**Universal editing rules:**
1. **Hook:** optionally lead with a 3-sec flash of **Shot 6** (payoff) or **Shot 2** (money
   shot) — or, for 🅱, **C1's dashboard** — before the origin intro, then settle in.
2. **Captions (on-screen text):**
   - Shot 2: label the cards **"Keyword (old)"** and **"Cognee (new)."**
   - When a tool runs, caption it: `web_search`, `add_task`, `run_shell`, `mcp_cognee_recall`.
   - Name each op as it appears: **remember · recall · improve / memify · forget.**
   - Platform tour: caption each page **Dashboard · Datasets · Knowledge Graph · Search ·
     Schema · Sessions · Skills** so judges see the breadth.
3. **Cuts:** speed-ramp or jump-cut **every** wait (search, cognify, reconnect, cloud page
   loads). No dead air. Live recall on big-pickle is ~20–30 s — **always** speed-ramp it.
4. **Music:** soft, low bed; duck under the VO. **VO** recorded last, over the finished picture.
5. **End card:** repo URL + "Built with Cognee · WeMakeDevs — *The Hangover Part AI: Where's My
   Context?*" + the **track name** (🅰 *Best Use of Open Source* / 🅱 *Best Use of Cognee Cloud*).

---

## PART 6 — Pre-flight checklists (per track)

**🅰 Self-hosted — before you shoot:**
- [ ] App on latest code (restarted after any change); browser fullscreen (F11), 100% zoom.
- [ ] Cognee **Connected** (green) · Backend = **Self-hosted**.
- [ ] `--backend local --reset --stress` printed **✅ All questions land** (10/10).
- [ ] Shots 3–5 rehearsed once; a good take saved as backup.
- [ ] Shot 6 dry-run **twice** — fresh chat stitches the week via visible `mcp_cognee_recall`.
- [ ] Shot 8 VO = the **🅰** line (open-source engine; **no "no API keys" claim**).
- [ ] PowerToys Mouse Highlighter ON.

**🅱 Cloud — before you shoot:**
- [ ] Backend = **Cognee Cloud**, **Connected** (post-July-2; if "at capacity", wait/retry).
- [ ] `--backend cloud --serve-url … --reset --stress` → **✅ 10/10** on the cloud.
- [ ] Namma Memory tab graph fills from the cloud REST sync (↻ Refresh if empty).
- [ ] **platform.cognee.ai dry-run done (0.7):** `namma_agent_memory` visible on
      Dashboard / Datasets / Knowledge Graph / Search / Schema; Sessions & Skills populated (C6/C7) or planned as skips.
- [ ] Shot 8 VO = the **🅱** line; Platform Tour C1–C8 planned.

**Both — submission paperwork:**
- [ ] AI-usage disclosed in [`SUBMISSION.md`](SUBMISSION.md); repo/video/README public.
- [ ] Submitted before **July 5, 2026**. Quick-ref cards:
      🅰 [`RECORDING_GUIDE_SELFHOSTED.md`](RECORDING_GUIDE_SELFHOSTED.md) ·
      🅱 [`RECORDING_GUIDE_CLOUD.md`](RECORDING_GUIDE_CLOUD.md).

---

## PART 7 — Backup queries & troubleshooting

**Money-shot backups** (if Shot 2's left card shows a hit, use another — all verified 10/10):

| Ask (reworded) | Cognee answers |
|---|---|
| `which engine do I use to store relationships?` | **Kuzu** |
| `what do I write all my code in?` | **Python** |
| `what runs my embeddings locally for free?` | **Ollama** |

**Multi-hop backups** (great for an extra recall beat, and for the cloud **Search** page C4):

| Ask | Answers |
|---|---|
| `what does the part of my app that users actually see run on?` | **React** |
| `what introduced me to the memory technology I now use?` | **the hackathon** |
| `which town is the person who built Namma Agent from?` | **Nellore** |
| `how does my assistant reach its memory engine without adding dependencies?` | **MCP** |

Re-verify any time: `python scripts\seed_demo_memory.py --stress-only`.

**Troubleshooting**
- *Compare left card shows a hit:* that keyword is in SQLite — use a backup query above.
- *No recall step in chat (Shots 4/6):* Settings → Cognee → Behaviour → *Recall in chat* ON.
- *Recall is slow (~20–30 s):* expected — the LLM (OpenCode big-pickle) is a reasoning model;
  **speed-ramp it** in editing. It's free and unmetered, so no rate-limit failures.
- *Stress test fails / container dies mid-battery:* the battery **paces itself**
  (`NAMMA_STRESS_PACE_SEC`, default 10s) so slow recalls don't stack and kill the `--rm`
  container; raise it if you still see failures.
- *Shot 3 web search junk:* VO over your rehearsed good take; keep the query identical.
- *Shot 5 has no diff:* make a tiny file edit first so there's something to review.
- *🅱 Cloud graph empty / "self-hosted-only" overlay:* ↻ Refresh — on cloud it pulls from the
  REST API and should fill.
- *🅱 `remember` returns 409 / "ProgrammingError":* a **Cognee Cloud–side** DB error, not a Namma
  bug; retry or re-run `--backend cloud … --reset --stress`.
- *🅱 platform Sessions/Skills empty:* they need agent `session_id` activity / an uploaded skill
  — see C6/C7 "populate it first," or treat those two shots as optional.
- *Graph sparse / writes failing / fresh-volume migration / model choice:* the full hard-won
  table is in [`docs/COGNEE.md`](docs/COGNEE.md).
