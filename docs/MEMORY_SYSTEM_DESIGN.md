# Namma Agent — Memory System Design Document

**Codename: Engram** — the native memory engine for Namma Agent.

| | |
|---|---|
| **Status** | Implemented — Phases 1, 2 & 3 landed 2026-07-16; remaining gaps (path assist in file tools, Cognee import script, skill drafts, `docs/PLUGINS.md`) closed later the same day. Deviations from the original text are footnoted in place. |
| **Date** | 2026-07-15 |
| **Author** | Drafted with Claude (Fable 5) |
| **Replaces** | Cognee-as-THE-memory ([docs/COGNEE.md](COGNEE.md)) |
| **Owner modules** | `namma_agent/core/memory.py`, new `namma_agent/core/engram/` |

---

## 1. Problem statement

Namma Agent's long-term memory is currently a Cognee MCP server running in Docker.
It was the right call for the WeMakeDevs × Cognee hackathon (deadline 2026-07-05 —
now past), but as the *permanent* memory layer it has structural problems that no
amount of tuning fixes:

1. **Recall is slow and flaky.** Every recall is: MCP stdio → Docker container →
   Cognee search pipeline → extraction-LLM round-trips. The agent loop caps the
   proactive recall at 12 s (`Agent._cognee_recall_context`) and still times out;
   `remember` (cognify) needs a **900 s** timeout. Users experience "recall failed"
   and multi-second identity questions.
2. **The graph only grows when `auto_ingest` is on.** `CogneeIngestor.ingest_async`
   is gated by one flag and ingests the **raw user message** — no salience filter,
   no fact extraction, no dedup, no contradiction handling. Off = the agent learns
   nothing from chat. On = the graph fills with noise.
3. **Wrong model does the memory work.** Cognee's extraction LLM is configured
   separately (local `qwen2.5:7b` via Ollama, or Groq presets) and is *divorced from
   Namma's provider chain*. The primary brain (`big-pickle` via opencode) never
   touches memory. Weak extractors fail Cognee's structured outputs
   ("validation error for SummarizedContent"), Groq hits rate limits, local qwen is
   minutes-per-document on CPU.
4. **Operational fragility.** ~35 GB of images, Kuzu single-writer locks, volume
   corruption requiring full resets, cold-start handshake failures, migrations
   blocking first connect — all documented as "hard-won" troubleshooting in
   COGNEE.md. A *memory* must be boring and always-on.
5. **No always-present memory.** Even the user's name requires a tool call or a
   regex-gated context injection. An agent that has to *query a container* to know
   who it's talking to will always feel amnesiac.
6. **No environment awareness.** The agent repeatedly misinterprets host file-system
   paths (drive letters, separators, home directories). It indexes *apps* but has no
   persistent model of the *machine it runs on*.
7. **Nothing improves over time.** There is no consolidation, no forgetting curve, no
   reflection — the memory does not get better while the agent is idle. A
   self-improving agent needs a self-improving memory.

## 2. Goals and non-goals

### Goals

- **G1 — Instant identity.** Who the user is, their preferences, and standing
  instructions are in the system prompt of *every* turn. Zero tool calls, zero
  latency, zero failure modes.
- **G2 — Fast recall.** p50 < 300 ms, p95 < 1.5 s for memory search, with a hard
  2 s budget on any in-turn injection. Never block a reply on memory.
- **G3 — Always learning.** Every turn is considered for memory *by default* — with
  an LLM salience gate so only durable facts are kept. No single on/off flag between
  the agent and learning.
- **G4 — One brain.** All memory LLM work (extraction, conflict resolution,
  summarization, reflection) routes through Namma's existing provider chain — i.e.
  **whatever model the user selected in Settings** (with its configured fallbacks).
  Nothing is hardcoded; switching the brain in Settings switches memory's brain too.
- **G5 — Self-improving.** A background consolidation cycle ("sleep-time compute")
  that merges, promotes, decays and reflects — memory quality goes *up* while the
  app is idle.
- **G6 — Zero heavy infrastructure.** In-process Python + SQLite. No Docker, no
  Kuzu, no LanceDB, no new native wheels (the venv is Python 3.14 — wheel
  availability burned us before). Works offline; degrades gracefully without
  embeddings.
- **G7 — Transparent and editable.** The Memory tab shows exactly what is known,
  where it came from, and lets the user edit/delete anything. The knowledge-graph
  view stays.
- **G8 — Environment memory.** A persistent, auto-refreshed model of the host
  (OS, drives, home, key folders, indexed apps, path conventions) injected into the
  prompt so file paths are never guessed. *(Extended 2026-07-19, STAND_OUT
  Phase 5: on Windows the probe also detects **WSL distros** — they ride the
  HOST block, and the path assist translates `/mnt/<drive>/…` ↔ `<Drive>:\…`
  and passes `\\wsl$\…` UNC paths through untouched.)*

### Non-goals

- Multi-user / multi-tenant memory (Namma is a personal agent).
- Training/fine-tuning the model on memories.
- Replacing project-document RAG (`docindex.py`) — it stays as-is and is *federated
  into* recall, not rebuilt.
- Removing MCP memory servers as an option — external providers (Cognee, Mem0, Zep)
  remain attachable as **plugins**, they just stop being *the* memory.

## 3. Research summary — what the best memory systems do

| System | Core idea we adopt | Reference |
|---|---|---|
| **Hermes Agent** (Namma's ancestor) | Two bounded, curated, always-in-context files (MEMORY.md ~800 tok, USER.md ~500 tok) + `memory` tool (`add`/`replace`/`remove`) + FTS5 session search + skills as procedural memory + external providers as optional plugins. "Memory isn't something the agent retrieves — it's something the agent *is*." Bounded memory forces curation; consolidate at 80% capacity. | glukhov.org, hermes-agent.ai |
| **Mem0** | Two-phase pipeline: **extract** candidate facts from the turn → retrieve similar existing memories → LLM resolves **ADD / UPDATE / DELETE / NOOP**. Keeps the store clean and contradiction-free; ~26% accuracy gain over raw-context baselines. | arxiv 2504.19413 |
| **Zep / Graphiti** | **Bi-temporal knowledge graph**: every fact/edge carries `valid_from`/`valid_to` (true in the world) and `created_at`/`expired_at` (known to the system). Contradictions **invalidate** old edges instead of deleting them → time-aware answers + full audit trail. Leads LongMemEval (63.8%). | arxiv 2501.13956 |
| **Letta (MemGPT)** | OS-style tiers: core memory in-context (RAM) → recall memory (recent, searchable) → archival (unbounded, on demand). Sleep-time agents rewrite/compress memory while the main agent idles. | letta.com |
| **Generative Agents / SAGE / LightMem** | Periodic **reflection** synthesizes higher-level insights from raw episodes; Ebbinghaus-style decay scores (recency × frequency × importance) drive forgetting; offline "sleep" reorganisation improves retrieval. | arxiv 2409.00872 et al. |
| **Claude Code** | Human-readable markdown memory, categorized (user / feedback / project / reference), an index file loaded each session, hybrid BM25 + vector retrieval with RRF fusion. Transparency as a design value. | mem0.ai/blog, milvus.io |

**The convergent lesson:** the winning architecture is *tiered* — a small curated
always-in-context core, plus structured extracted facts with temporal validity, plus
searchable raw episodes, plus procedural skills — maintained by an LLM-driven write
pipeline and an offline consolidation loop. Heavy graph databases are not what makes
these systems good; the *pipeline discipline* is. That is exactly what we build,
natively, on the SQLite file Namma already owns.

## 4. Architecture overview

```
                        ┌────────────────────────────────────────────────┐
                        │                THE AGENT LOOP                  │
                        │  system prompt ◄── L1 Core memory (always)     │
                        │                ◄── L5 Environment block        │
                        │                ◄── recall prefetch (≤2s)       │
                        │  tools: memory_save / memory_search /          │
                        │         memory_forget  (+ legacy aliases)      │
                        └───────┬───────────────────────────▲────────────┘
                                │ post-turn (async)         │ recall
                                ▼                           │
┌──────────────────────── ENGRAM ENGINE (in-process) ───────┴──────────────────────┐
│                                                                                  │
│  WRITE PIPELINE (background worker, provider chain → big-pickle)                 │
│    turn ──► salience gate ──► fact extraction ──► retrieve-similar               │
│                └─ skip           (structured)        │                           │
│                                             ADD / UPDATE(invalidate) /           │
│                                             DELETE / NOOP  + core-memory patch   │
│                                                                                  │
│  STORES (one SQLite file: data/namma_agent.db)                                   │
│    L1 core_memory      — user profile + agent notes (bounded, versioned)         │
│    L3 memory_items     — facts w/ bi-temporal validity + provenance              │
│       memory_entities  — nodes        memory_relations — edges (the graph)       │
│       memory_vectors   — embedding BLOBs (optional)   *_fts — FTS5 (BM25)        │
│    L2 turns/sessions   — episodic (exists)  + session summaries                  │
│    L4 skills           — procedural (exists, skills.py)                          │
│    L5 environment      — host model (OS, drives, folders, apps)                  │
│                                                                                  │
│  RECALL (read path, no LLM in the hot path)                                      │
│    query ──► [BM25 ‖ vector ‖ graph-neighbourhood ‖ episodic ‖ docs]             │
│              ──► RRF fusion ──► temporal filter (valid now) ──► top-k            │
│                                                                                  │
│  CONSOLIDATOR ("sleep-time", idle/scheduled)                                     │
│    summarize sessions · promote episodic→semantic · merge duplicates             │
│    decay & expire (recency·frequency·importance) · reflect → insights            │
│    compact core memory at 80% capacity · refresh environment                     │
│                                                                                  │
│  PLUGINS (optional, off the critical path)                                       │
│    external providers via MCP (cognee / mem0 / zep) — prefetch + sync            │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Everything is **in-process**: no container, no server, no cold start. The only
external dependency of the whole layer is the LLM provider chain Namma already has.

## 5. The six layers

### L1 — Core memory (always in context) — *the headline fix*

Two bounded, curated blocks stored in `core_memory` and injected into **every**
system prompt (chat mode included — this replaces the "user memory is not injected
in chat mode" gap):

| Block | Content | Budget |
|---|---|---|
| `user` | Identity, role, preferences, people, standing instructions ("call me X", "answer in Telugu") | ~500 tokens |
| `agent` | Environment quirks, project conventions, lessons learned, tool gotchas | ~800 tokens |

- Rendered as a fenced block with usage percentage, e.g.
  `## MEMORY (user, 62% full)` — the percentage nudges the model to curate.
- Edited through one `memory_save` tool (see §7) with `add` / `replace` / `remove`
  semantics (substring match for replace/remove — Hermes-proven).
- **Hard caps enforced in code**, not by convention. At >80% the consolidator (or an
  inline rejection message) forces a merge pass: dense single-line entries win.
- Every write is versioned (`core_memory_history`) → the Memory tab gets an undo.
- Writes go through the same injection screen used for documents
  (`docscan.screen_text`) — memory is an injection surface.
- Stored in SQLite (source of truth) **and mirrored to
  `data/memory/USER.md` / `data/memory/AGENT.md`** so the user can read/edit memory
  as plain files; the mirror is re-imported on startup if its mtime is newer
  (transparency à la Claude Code / Hermes).

This alone fixes the worst user-visible failure: *"who am I?" can never fail and
costs zero milliseconds*, because the answer is already in the prompt.

### L2 — Episodic memory (what happened)

Already exists and is good: `sessions` / `turns` + `turns_fts` + session summaries.
Additions:

- **Summaries become first-class recall targets**: embed them (when embeddings are
  on) and include them in fused recall.
- Each consolidation pass summarizes any unsummarized session (this exists —
  `unsummarized_sessions` — but will run on the consolidator's schedule instead of
  opportunistically).
- `search_conversations` / `recall_sessions` tools stay, backed by the same fused
  retrieval.

### L3 — Semantic memory (what is true) — *the Cognee replacement*

Structured facts with **bi-temporal validity**, stored natively:

```sql
-- One atomic memory: a sentence-sized fact with provenance and lifecycle.
CREATE TABLE memory_items (
    id           TEXT PRIMARY KEY,          -- uuid
    text         TEXT NOT NULL,             -- "Santhosh studies B.Tech CSE (AI&ML) at KARE"
    kind         TEXT DEFAULT 'fact',       -- fact | preference | event | insight
    subject      TEXT,                      -- normalized entity name ("santhosh")
    predicate    TEXT,                      -- "studies_at"
    object       TEXT,                      -- "KARE"
    importance   REAL DEFAULT 0.5,          -- 0..1, set by extractor
    frequency    INTEGER DEFAULT 1,         -- times reinforced
    last_seen    TEXT NOT NULL,             -- reinforcement recency
    valid_from   TEXT,                      -- true-in-world window (bi-temporal)
    valid_to     TEXT,                      -- NULL = still true
    created_at   TEXT NOT NULL,             -- known-to-system window
    expired_at   TEXT,                      -- NULL = live; set on invalidation
    superseded_by TEXT,                     -- id of the fact that replaced this one
    source       TEXT,                      -- 'chat:<session_id>' | 'learning:<topic>' | 'manual' | 'import:cognee'
    screen_status TEXT DEFAULT 'ok'         -- injection screening result
);
CREATE VIRTUAL TABLE memory_items_fts USING fts5(text, subject, object);

-- Entities and typed relations = the knowledge graph (feeds the Memory tab view).
CREATE TABLE memory_entities (
    id         TEXT PRIMARY KEY,
    name       TEXT NOT NULL,               -- display name
    norm       TEXT UNIQUE NOT NULL,        -- normalized key
    type       TEXT DEFAULT 'thing',        -- person | place | org | project | tool | concept | ...
    summary    TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE memory_relations (
    id         TEXT PRIMARY KEY,
    src        TEXT NOT NULL,               -- memory_entities.id
    rel        TEXT NOT NULL,               -- "works_on", "friend_of", ...
    dst        TEXT NOT NULL,
    item_id    TEXT,                        -- the memory_item this edge came from
    valid_from TEXT, valid_to TEXT,
    created_at TEXT NOT NULL, expired_at TEXT
);

-- Optional embeddings (float32 BLOBs; brute-force cosine via numpy — fine to ~100k rows).
CREATE TABLE memory_vectors (
    item_id  TEXT PRIMARY KEY,
    model    TEXT NOT NULL,
    dim      INTEGER NOT NULL,
    vec      BLOB NOT NULL
);
```

Key semantics (Zep-style): **contradictions never delete** — the resolver sets
`valid_to`/`expired_at` and `superseded_by` on the old fact. "Where do I work?"
answers with the live fact; "where did I work in 2025?" can still be answered; the
Memory tab can show a fact's full history.

**Why not a graph database:** at personal-agent scale (thousands of facts, not
billions), SQLite joins over `memory_relations` cover every graph query the agent
makes (1–2 hop neighbourhoods for recall, full dump for the tab's visualization).
This is the same judgment Hermes made — the pipeline is the product, not the DB.

### L4 — Procedural memory (how to do things)

Already exists: `skills.py` (SKILL.md store + learning loop). Two integrations:

- The consolidator's **reflection** step may propose a new skill when it detects a
  repeated multi-step workflow in episodes (the Hermes self-improvement loop:
  *extract what worked, write it as a reusable skill*). *Implemented as
  `_step_skill_drafts`: drafts land `category: draft` and **disabled** (persisted
  to `skills.disabled`) — a proposal the user enables in Settings → Skills, not a
  self-granted capability.*
- Skill usage stats feed `importance` on related semantic facts. *Implemented as
  `_step_skill_usage`: `use_skill` audit rows since the last run reinforce
  (frequency + recency — the decay score's counterweights) facts matching the
  skill's name.*

### L5 — Environment memory (where am I running) — *fixes the file-path problem*

A small, auto-maintained model of the host, refreshed at startup and by the
consolidator, stored as one JSON document (`environment` table or
`data/memory/ENVIRONMENT.json`) and rendered as a compact prompt block:

```
## HOST
OS: Windows 11 (win32) · user: santh · home: C:\Users\santh
Path style: backslash, drive letters. NEVER invent POSIX paths like /home or /tmp.
Drives: C:\ (system, 120 GB free) · D:\ (data, 512 GB free)
Key folders: Desktop=C:\Users\santh\Desktop · Documents=... · Downloads=...
Project roots: D:\AGI (namma_agent)
Apps indexed: 214 (see open_app) · Shell: PowerShell 5.1
Temp: C:\Users\santh\AppData\Local\Temp
```

Collected by a new `core/environment.py` probe: `platform` module, `Path.home()`,
`os.environ` (USERPROFILE, TEMP), drive enumeration (`psutil` if present, else
`ctypes`/`shutil.disk_usage`), the existing `AppTracker`/apps index, and known
folder resolution (Windows: `SHGetKnownFolderPath` via ctypes; POSIX: XDG dirs).

Every file-handling tool ALSO gets a validation assist: a helper
`environment.resolve_path(text)` that expands `~`, fixes separator style for the
current OS, resolves "Desktop/Downloads/Documents" names, and rejects paths on
non-existent drives *with the environment block quoted in the error* — so even when
the model guesses wrong, the tool result teaches it the real layout. *Wired into
every `tools/file_ops.py` handler via a module-level default (the Engram facade
registers its instance at construction); `find_binary` is the matching
tool-discovery assist (PATH + well-known install roots), used by e.g. vision.*

### L6 — Plugin providers (optional depth)

The Hermes pattern: a single optional external provider (Cognee, Mem0, Zep — any
memory MCP server) attachable in Settings, operating in `prefetch` (auto-inject),
`tools` (model-invoked), or `hybrid` mode — **additive, never load-bearing**. The
existing Cognee MCP wiring survives here, demoted from THE memory to *a* provider.

## 6. The write pipeline (how memory gets in)

Runs in the existing background-worker pattern (`CogneeIngestor` is refactored into
`engram/writer.py` — same queue, new brain). **Always on** — the `auto_ingest` flag
dies; the salience gate replaces it. Per completed turn:

1. **Salience gate** (cheap, no LLM): skip if user text < 24 chars, pure command
   ("open chrome"), or a paste-dump. Everything else proceeds.
2. **Extraction** (one provider-chain call, on the user-selected model): a structured prompt over
   the turn (+ last few turns for pronoun resolution) returns
   `[{text, kind, subject, predicate, object, importance, valid_from?}]`, or `[]`
   (most turns — that's fine and cheap). Assistant replies are included as context,
   not as fact sources (facts about the *user's world* only).
3. **Retrieve-similar**: top-8 live `memory_items` by BM25 + cosine on each
   candidate.
4. **Resolution** (one provider-chain call, Mem0-style): for each candidate against
   its neighbours → `ADD` | `UPDATE` (new item + invalidate old: `expired_at`,
   `superseded_by`) | `DELETE` (user retracted) | `NOOP` (duplicate → bump
   `frequency`, `last_seen`).
5. **Graph upsert**: normalize subject/object into `memory_entities`, write
   `memory_relations` edges with the same validity window.
6. **Core-memory patch proposal**: if a fact is identity-grade (name, role, standing
   preference — `importance ≥ 0.8` and `kind ∈ {preference, fact-about-user}`), the
   resolver may also emit a core-memory `add`/`replace` patch (screened, capped).
7. **Embed** (if enabled) and index.

Explicit paths bypass the gate but share steps 3–7: the `memory_save` tool,
project notes (`remember_project_note`), learning recaps (`ingest_learning`),
onboarding facts.

**Failure policy:** any step failing = log + drop (never surface into the turn);
queue bounded at 200 items as today.

**Cost note:** two small LLM calls per *salient* turn on the user's selected
model. Batching in the consolidator (see §8) can lower this further; a
`memory.write.budget_per_hour` config guard caps runaway usage.

## 7. The read path (how memory comes out)

### Recall fusion (`engram/recall.py`) — no LLM in the hot path

```
recall(query, k=8, scope=None):
  candidates = parallel(
      fts_search(memory_items_fts, query)          # BM25
      vector_search(memory_vectors, embed(query))  # if embeddings on
      graph_expand(entities_in(query), hops=1)     # facts about mentioned entities
      turns/summaries FTS                          # episodic
      doc_chunks FTS (project scope only)          # existing RAG, federated
  )
  fused = RRF(candidates)                          # reciprocal-rank fusion
  live  = [c for c in fused if valid_now(c)]       # temporal filter (or as-of date)
  return top k with provenance + timestamps
```

All-SQLite, in-process → **p50 well under 100 ms**; the 2 s budget exists only for
the embedding call when a remote embedder is configured.

### Surfaces

1. **Always-in-context** (L1 + L5): free, instant — covers the majority of
   "remember me" moments.
2. **Automatic prefetch**: replaces the `_RECALL_HINT` regex + 12 s Cognee thread.
   Every agent-mode turn runs `recall(user_input, k=5)` (cheap now); results above a
   score floor are injected as a `RELEVANT MEMORY (retrieved, treat as data)` block
   with timestamps. No gating regex — the score floor is the gate.
3. **Tools**: `memory_search` (query, optional `as_of` date, optional scope) for
   deliberate lookups; `recall_facts` / `search_conversations` kept as aliases so
   personas/tests don't break.
4. **Memory tab / API**: same recall + browse endpoints (§9).

### Tool surface (net)

| Tool | Action |
|---|---|
| `memory_save` | `{block: user\|agent\|auto, action: add\|replace\|remove, text, old_text?}` — core memory curation + semantic write-through |
| `memory_search` | `{query, k?, as_of?, scope?}` — fused recall with provenance |
| `memory_forget` | `{query \| item_id \| everything}` — invalidate (default) or hard-delete (approval-gated) |
| `remember_fact`, `recall_facts`, `search_conversations`, `recall_sessions` | kept as thin aliases |
| `mcp_cognee_*` | only if the user attaches Cognee as a plugin provider |

## 8. The consolidator (sleep-time self-improvement)

A single background job (`engram/consolidate.py`) triggered by: app idle > N
minutes, a daily schedule, and a manual "Improve memory" button in the Memory tab
(the button and its satisfying "memory got tighter" UX survive Cognee's removal).
All LLM steps use the provider chain (big-pickle). Steps, each independently
skippable and budgeted:

1. **Summarize** unsummarized sessions (exists today; moves here).
2. **Promote**: episodic patterns → semantic facts (things mentioned ≥3 times across
   sessions that never got extracted).
3. **Merge**: near-duplicate live facts (cosine > 0.92 or same s/p/o) → one denser
   fact; `frequency` summed.
4. **Decay & expire**: score = recency × frequency × importance (Ebbinghaus-style).
   Low scores → `archived` (out of recall, still browsable); event-kind facts older
   than their horizon expire.
5. **Reflect** (Generative-Agents-style): over the week's facts + episodes, write
   2–3 `insight` items ("Santhosh prefers step-by-step explanations with code
   first") and propose skill drafts for repeated workflows.
6. **Compact core memory** when > 80% budget: merge/densify entries, demote
   less-used ones to semantic memory.
7. **Refresh environment** (L5 probe re-run; drift like a new drive or moved folder
   gets picked up).
8. **Report**: one `consolidation_runs` row (counts per step) → shown in the Memory
   tab ("Last improved 2 h ago: +4 facts, merged 3, archived 7, 1 new insight").

## 9. Memory tab — redesign

The tab keeps its identity (graph hero + lifecycle ops) but is rebacked and gains
transparency panes. Backend: same `/api/memory/*` routes, new implementation over
Engram (no MCP proxying).

| Pane | Content | Backing |
|---|---|---|
| **Status ribbon** | "Memory active · N facts · M entities · last consolidation …" — no more "Cognee offline" dead state; native memory is always on | `GET /api/memory/status` |
| **Knowledge graph (hero)** | Same `MemoryGraph.jsx` force layout; nodes = `memory_entities`, edges = live `memory_relations`; expired edges optionally shown dashed ("time-travel" slider = `as_of` query) | `GET /api/memory/graph?as_of=` |
| **Core memory editor** | Two cards (User / Agent) with usage bars, inline edit, history/undo | `GET/PUT /api/memory/core` |
| **Ask / recall** | Existing AskPanel → `memory_search`, results show provenance + valid-time chips | `POST /api/memory/recall` |
| **Facts browser** | Filterable table (kind, entity, live/expired), row → history chain (what superseded what), edit/forget per row | `GET /api/memory/items` |
| **Improve** | The consolidate button + last-run report (replaces the session-buffer "pending consolidation" counter) | `POST /api/memory/consolidate` |
| **Forget / danger zone** | Invalidate-by-query, wipe-all (approval + typed confirmation) | `POST /api/memory/forget` |
| **Environment** | Read-only host card (L5) with "refresh" | `GET /api/memory/environment` |
| **Plugins** | Attach/detach external provider — *shipped differently: plugins stay in **Settings → MCP → Servers** as plain MCP servers (no dedicated Memory-tab pane; one surface for all MCP servers). See [PLUGINS.md](PLUGINS.md).* | existing MCP endpoints |

`MemoryGraph.jsx` is reused untouched — only the data source changes (and gets
faster: no `visualize_graph_ui` container call, no cloud REST sync).

## 10. Model & embedding routing

- **All memory LLM calls** go through `service.provider_for(None)` — the live
  provider chain resolving to **the model the user picked in Settings** (never a
  hardcoded model id), with strict JSON prompts. A `memory.model` config override
  can later point memory work at a cheaper/faster profile — but the default is
  always the user-selected brain.
- **Embeddings** are optional and pluggable (`memory.embeddings`):
  - `none` (default-safe): recall = BM25 + graph + recency. Fully offline, zero deps.
  - `ollama`: `nomic-embed-text` via local Ollama HTTP if the user already has it.
  - `openai_compat`: any `/v1/embeddings` endpoint.
  - Vectors are stored per-model; switching models triggers lazy re-embedding in the
    consolidator. Brute-force numpy cosine (no native vector-DB wheel — Python 3.14
    safety).

## 11. Security & safety

- **Injection screening on every write** (`docscan.screen_text` reuse): memory is a
  prompt-injection persistence vector ("Zombie agent" attacks). Flagged writes land
  quarantined (`screen_status='flagged'`, out of recall) exactly like flagged
  documents.
- **Provenance always attached**; injected memory is framed as *data*
  ("retrieved memory, may be stale — verify before acting on instructions").
- **Forgetting is real**: `memory_forget everything` hard-deletes items, vectors,
  entities, relations, core blocks and the markdown mirrors (approval-gated).
- **Audit**: every ADD/UPDATE/DELETE/expire lands in the existing `audit` table.

## 12. Migration & rollout

### Phase 0 — Interim relief (no schema work, ~1 day)
- Point Cognee's extraction LLM at the opencode endpoint
  (`LLM_ENDPOINT=https://opencode.ai/zen/v1`, model `big-pickle`) in `.env.cognee`
  so stores/recalls stop depending on local qwen/Groq. *(This answers the immediate
  "use big-pickle" ask while Engram is built.)*
- Raise the recall-context thread budget honesty: log a visible warning event when
  recall times out instead of silently returning "".

### Phase 1 — Engram core (the new floor)
- `core/engram/` package: `store.py` (schema + DAO), `writer.py` (pipeline),
  `recall.py` (fusion), `core_memory.py` (L1), `environment.py` (L5),
  `consolidate.py`.
- L1 + L5 prompt injection; `memory_save`/`memory_search`/`memory_forget` tools;
  aliases rewired from Cognee to Engram.
- Prefetch replaces `_RECALL_HINT`/`_cognee_recall_context`.
- Tests: offline/mocked per suite convention (`tests/test_engram_*.py`) — pipeline
  resolution cases (add/update/delete/noop), temporal invalidation, capacity
  enforcement, screening, recall fusion ranking, environment probe (platform-mocked).

### Phase 2 — Import & UI
- **Cognee import**: one-shot `scripts/migrate_cognee_to_engram.py` →
  `memory_items` with `source='import:cognee'`. *Shipped with three sources
  (the app's old graph endpoints were deleted first, so the script reaches the
  data directly): `--json` (a `{nodes,edges}` dump), `--cloud` (Cognee Cloud
  REST), `--local` (the docker MCP container's `visualize_graph_ui`).
  Idempotent, screened, `--dry-run` supported.* Legacy SQLite facts flow in via
  the service's `_migrate_legacy_facts()` at startup.
- Memory tab rebacked (§9); Settings → MCP → Cognee panel becomes the Plugins pane.
- `cognee_ingest.py` deleted; `CogneeIngestor` call-sites switch to
  `engram.writer`; `cognee.*` config keys mapped to `memory.*` with deprecation
  warnings.

### Phase 3 — Self-improvement
- Consolidator scheduling (idle detection + daily), reflection, skill-draft
  proposals, decay tuning, Memory-tab report card, time-travel graph slider.

### Config (new block)

```yaml
memory:
  enabled: true
  write:
    salience_min_chars: 24
    include_replies_as_context: true
    budget_per_hour: 60          # max LLM write-pipeline calls
  recall:
    prefetch: true
    k: 5
    score_floor: 0.35
    timeout_s: 2
  core:
    user_budget_tokens: 500
    agent_budget_tokens: 800
  embeddings:
    backend: none                # none | ollama | openai_compat
  consolidate:
    idle_minutes: 20
    daily_at: "03:30"
  provider_plugin: null          # optional external memory MCP server name
```

## 13. What gets deleted / kept

| Component | Fate |
|---|---|
| `core/cognee_ingest.py` | **Deleted** (Phase 2) — queue pattern lives on in `engram/writer.py` |
| Cognee MCP registration, `.env.cognee`, docker-compose, setup scripts | **Kept but optional** — plugin provider path; how-to in [`docs/PLUGINS.md`](PLUGINS.md), container details stay in [`docs/COGNEE.md`](COGNEE.md) (historical) |
| `service.cognee_*` methods, session-buffer sidecar (`cognee_pending.json`) | **Deleted** — consolidation is native now |
| `_RECALL_HINT` regex + `_cognee_recall_context` | **Replaced** by score-floored prefetch |
| `mcp_cognee_*` steering block in `_build_messages` | **Replaced** by a shorter block describing `memory_search`/`memory_save` |
| SQLite `facts` table + FTS | **Superseded** by `memory_items` (one-time import, then dropped) |
| `turns`/`sessions`/summaries, `docindex`, `skills.py`, scope memory | **Kept** — federated into recall |
| Memory tab graph view | **Kept** — rebacked, faster |
| `docs/COGNEE.md` | Marked historical; superseded by this doc |

## 14. Success metrics

| Metric | Today (Cognee) | Target |
|---|---|---|
| "What's my name?" correct in a fresh chat | tool-call dependent, can fail | 100%, 0 extra latency (in prompt) |
| Recall p50 / p95 | seconds / 12 s timeout | < 100 ms / < 1.5 s |
| Store latency (fact durable) | up to 900 s cognify | < 10 s background, turn unaffected |
| Learning coverage | 0% with auto_ingest off | 100% of salient turns, always on |
| Contradiction handling | none (dup nodes) | UPDATE-with-invalidation, audit trail |
| Infra required | Docker + 35 GB images | none |
| Memory improves while idle | never | every consolidation run |
| File-path misinterpretation | frequent | environment block + `resolve_path` on every file tool |

## 15. Risks & mitigations

| Risk | Mitigation |
|---|---|
| Extraction quality varies with free-tier models | JSON-schema-constrained outputs + provider-chain fallback; NOOP-biased prompts (when unsure, don't write); consolidator cleans up misfires |
| Write-pipeline LLM cost/quota | salience gate + hourly budget + batch mode in consolidator |
| Core memory grows stale/wrong | user-editable everywhere (tab + markdown mirrors), versioned with undo, consolidator re-validates against recent facts |
| Prompt bloat from L1+L5 | hard token budgets (~1,500 total), enforced in code; blocks are stable across turns → prefix-cache friendly |
| Memory poisoning via injected content | write-time screening + quarantine + provenance framing (§11) |
| Losing the hackathon graph | one-shot import (Phase 2) before deleting anything; Cognee stays attachable as a plugin. *In practice the app-side plumbing was deleted before the import script landed — the data itself lives on in the `cognee-data` docker volume / Cognee Cloud, which is exactly what `scripts/migrate_cognee_to_engram.py` reads (run it while those still exist).* |

---

*Related: [ARCHITECTURE.md](ARCHITECTURE.md) · [SKILLS.md](SKILLS.md) ·
[PLUGINS.md](PLUGINS.md) (external providers) · [COGNEE.md](COGNEE.md) (historical)*
