# Cognee Integration — Implementation Tracker

> **Status:** Living document — updated as implementation proceeds.
> **Created:** 2026-06-25
> **Last updated:** 2026-06-25
> **Owner:** Namma Agent (D:\AGI)
> **Source material:**
> - `C:\Users\santh\Desktop\Cognee\Cognee_Complete_Project_Report.md` (Cognee v1.2.1 reference — accurate)
> - `C:\Users\santh\Desktop\Cognee-NammaAgent-Integration\Cognee_NammaAgent_Integration_Plan.md` (proposed integration)

---

## 0. How to read / maintain this file

This is the **single source of truth** for the Cognee add-on. Every phase has
sub-processes with a status box. As work lands, flip the box and append a dated
line to the **Changelog** at the bottom. Never delete history — append.

Status legend: `[ ]` not started · `[~]` in progress · `[x]` done · `[!]` blocked

---

## 1. Verdict (read this first)

**Yes — adding Cognee will make Namma Agent meaningfully better, *if* implemented
in the corrected order below.**

Namma Agent's memory today is a single SQLite file with **FTS5/BM25 keyword
search only**. That genuinely misses semantic recall ("the thing I said about the
data layer" when you now say "database architecture"), entity/relationship graphs,
and cross-session linking. Cognee's vector + graph + relational stores fill exactly
those gaps, and the proposed design is **non-destructive** (sidecar alongside
SQLite, graceful degradation) — which is the right call.

**But the integration plan, as written, has real anomalies (Section 3) that would
degrade or break the system if implemented verbatim.** The most important
correction: Namma Agent is **already MCP-capable** and Cognee **ships its own MCP
server**, so the lowest-risk path is to integrate over MCP *first* (now trivial —
the MCP settings UI was just added), and only then pursue the heavier embedded-SDK
integration. See Section 4 for the corrected phasing.

---

## 2. Pre-flight findings

### 2.1 Is Namma Agent MCP-capable? — YES (verified)

| Evidence | Location |
|---|---|
| Stdio JSON-RPC 2.0 MCP client (persistent process, proper handshake) | `namma_agent/mcp/client.py` |
| MCP manager — connects servers, registers tools as `mcp_<server>_<tool>` | `namma_agent/mcp/manager.py` |
| Wired into the service under the `mcp` toolset | `namma_agent/service.py` (`_build_mcp`) |
| Config-driven servers | `config.yaml` → `mcp.servers` (+ `config.local.yaml` overlay) |
| Tests pass | `namma_agent/tests/test_mcp.py` (6 passed) |

### 2.2 MCP settings UI — DONE (this session)

The user-requested **MCP category** with **Config** and **Servers** sections is
implemented and browser-verified:

| Piece | Location | Notes |
|---|---|---|
| `ToolRegistry.unregister()` | `core/tools.py` | lets reload drop a removed server's tools |
| `service.mcp_detail()` / `service.reload_mcp()` | `service.py` | config JSON + servers/tools; live reconnect, no restart |
| `GET /api/mcp`, `POST /api/mcp/reload` | `server/api.py` | |
| `fetchMcp`, `reloadMcp` | `webui/src/api.js` | (per-tool toggle reuses existing `toggleTool`) |
| **MCP → Config** tab (JSON editor, Save & reconnect) | `webui/src/components/Settings.jsx` (`McpConfigTab`) | writes `mcp` block to `config.local.yaml` |
| **MCP → Servers** tab (servers + tools, per-tool toggles, Reconnect) | `Settings.jsx` (`McpServersTab`) | toggle = same disable mechanism as Toolsets |

**Consequence for Cognee:** Phase 0 below (MCP-server path) is now a *config
edit*, not a code change.

---

## 3. Anomalies in the proposed plan (must address before/while implementing)

These are flagged in priority order. Each is something that would **degrade,
break, or inflate cost** if the plan were implemented verbatim.

### A. Embedding-provider gap — **HIGH** (would silently break init)
The plan sets `cognee.llm.type: auto` and `cognee.embedding.type: auto`
("inherit from main provider"). But Cognee **requires an embedding model**, and
Namma Agent's default brain is **Anthropic/Claude, which has no embeddings API**.
"Auto-inherit" therefore cannot work for the embedding model whenever the main
provider can't embed (Anthropic, most OpenAI-compat chat endpoints).
**Fix:** embeddings must be configured **explicitly** — OpenAI `text-embedding-3-*`
(needs `OPENAI_API_KEY`), or local `ollama`/`fastembed`. Never silently inherit
embeddings from a chat-only provider. Surface a clear setup error if missing.

### B. Recall on every turn uses an LLM call — **HIGH** (latency + cost)
Plan §6.2 / Phase 2.3 inject a "Cognee context block" into `_build_messages` on
**every turn**. Cognee `recall()` **defaults to `GRAPH_COMPLETION`, an
LLM-powered call**. That adds a full extra LLM round-trip (seconds + tokens) to
every single turn's prompt assembly. The plan's "~50–200 ms" figure only holds
for raw vector retrieval (`CHUNKS`).
**Fix:** for prompt-context injection use the cheap retrieval types
(`CHUNKS` / vector-only), gate it behind relevance, and cache. Reserve
`GRAPH_COMPLETION` for explicit `cognee_recall`/`cognee_insights` tool calls.

### C. Auto-ingest of every turn via full pipeline — **HIGH** (cost explosion)
`features.auto_ingest_turns: true` with the permanent-memory pipeline runs
entity-extraction LLM calls + embeddings on **every** turn. The Cognee report
itself warns `cognify` "makes many sequential LLM calls."
**Fix:** default turns to **session memory** (`remember(data, session_id=...)` —
fast cache, no LLM). Promote to permanent (`cognify`/`improve`) only on explicit
save or during idle consolidation.

### D. API surface mismatch between the two docs — **MEDIUM** (rework)
The integration plan's pseudocode / Appendix B call `cognee.add()`,
`cognee.search()`, `cognee.graph()`, `cognee.extract_entities()`,
`cognee.insights()`, `cognee.improve(scope=...)`. The accurate report documents
the real v1.0 surface as `remember / recall / improve / forget / cognify /
search`. **`cognee.graph()`, `cognee.extract_entities()`, `cognee.insights()` do
not exist as top-level functions**, and `improve()` takes `dataset=/session_ids=`,
not `scope=`.
**Fix:** map the 7 proposed tools onto the *real* API: graph/entity/insight tools
become `recall`/`search` with `query_type` in
`{GRAPH_COMPLETION, CYPHER/NATURAL_LANGUAGE, TEMPORAL, SUMMARIES}` plus the
`cognify` pipeline. Validate every call against the installed version.

### E. Sync ↔ async bridge not addressed — **MEDIUM**
Cognee's API is fully `async`; Namma's tool handlers are **sync**
(`Handler = Callable[[dict], Any]`). The plan's `CogneeClient` even mixes sync and
async method signatures.
**Fix:** the wrapper owns a dedicated background event loop (or uses
`asyncio.run` per call off the request thread) so sync handlers can call async
Cognee without blocking the agent loop. Background ingestion uses the same thread
pattern as `memory_extract.py::capture_async`.

### F. Version pin is wrong — **MEDIUM**
`requirements.txt: cognee>=0.1.0` while current is **1.2.1** and the package is
**Beta** ("APIs may still evolve"). `>=0.1.0` can resolve to an incompatible
release.
**Fix:** pin to a tested minor, e.g. `cognee==1.2.*`, and keep Cognee deps behind
an **optional extra** so the base install stays lean (see anomaly G).

### G. Dependency footprint vs. "lean cloud-only" identity — **LOW/MEDIUM**
Cognee pulls in `lancedb, kuzu, litellm, instructor, pypdf, rdflib, networkx,
tiktoken, sqlalchemy, aiosqlite, …` — a heavy native stack for a project that
prides itself on being lean. Not a blocker (it's opt-in), but the base install
must not carry it.
**Fix:** ship as `pip install namma-agent[cognee]` / a documented separate install;
the running process imports Cognee lazily only when `cognee.enabled: true`.

### H. Kuzu concurrency under background writes — **LOW**
Default graph store (Kuzu) is file-locked and "not suitable for concurrent
multi-agent scenarios." Single-user Namma mitigates this, but concurrent async
background writes can still collide.
**Fix:** serialize Cognee writes through a single worker/queue; or use Neo4j if
concurrency ever matters.

### I. Documentation typos — **TRIVIAL**
"Coggee" (report §3.3 heading), "CoggeeClient" (plan §13.1). Cosmetic.

> **None of A–I change the verdict.** They change the *defaults and order*. The
> corrected plan is Section 4.

---

## 4. Corrected phase plan

> The integration plan's own Phases 1–5 are sound in spirit and kept below
> (Phases 1–5), **but** a new **Phase 0** is inserted first because the MCP path
> is now nearly free, and the anomaly fixes (Section 3) are folded into each phase.

### Phase 0 — MCP-server MVP (fastest, lowest-risk) — `[ ]`
**Goal:** Get Cognee memory working through Namma's *existing* MCP client + the new
MCP UI, with **zero new Python deps in Namma's process**.

- `[ ]` 0.1 Run Cognee's MCP server out-of-process (stdio): `cognee-mcp` /
  `docker run cognee/cognee-mcp` (its own venv, its own deps).
- `[ ]` 0.2 Configure embeddings explicitly for that server (anomaly A) — OpenAI
  key or local Ollama/fastembed in *its* env, not Namma's.
- `[ ]` 0.3 In Namma: **Settings → MCP → Config**, add the server
  (`{"name":"cognee","command":[...],"env":{...}}`), Save & reconnect.
- `[ ]` 0.4 Verify in **Settings → MCP → Servers**: Cognee's tools
  (`remember/recall/cognify/search/forget/improve/prune/get_document/...`) appear
  and are toggleable.
- `[ ]` 0.5 Smoke test: store a fact via `mcp_cognee_remember`, recall it
  semantically via `mcp_cognee_recall` with reworded query.
- `[ ]` 0.6 Decide: is MCP-path sufficient, or is deep embedded integration
  (Phases 1–5) worth the extra cost? Record the decision here.

**Deliverable:** Cognee semantic/graph memory usable from the agent with no code
changes to Namma — only config. **Recommended starting point.**

### Phase 1 — Foundation (embedded SDK) — `[ ]`
*(Only if Phase 0.6 says deep integration is wanted.)*
- `[ ]` 1.1 Add Cognee as an **optional extra** (anomaly F/G): pin `cognee==1.2.*`.
- `[ ]` 1.2 Add `cognee` config block (anomaly A: **explicit** embedding provider;
  anomaly C: turns → session memory by default).
- `[ ]` 1.3 `namma_agent/core/cognee_client.py` — wrapper with **its own event
  loop** (anomaly E), lazy import, graceful-degradation (returns None/[] if off).
- `[ ]` 1.4 `namma_agent/tools/cognee.py` — register tools mapped to the **real**
  API (anomaly D). Start with `cognee_remember` + `cognee_recall`.
- `[ ]` 1.5 Wire `CogneeClient` into `NammaAgentService` (conditional on
  `cognee.enabled`); register tools under the `memory` toolset.
- `[ ]` 1.6 Turn ingestion → **session memory** (fast, no LLM) on each turn.
- `[ ]` 1.7 Test: remember/recall round-trip; verify graceful fallback when off.

**Deliverable:** Embedded `cognee_remember`/`cognee_recall`, opt-in, no latency on
the reply path, falls back cleanly.

### Phase 2 — Semantic memory — `[ ]`
- `[ ]` 2.1 One-time migration script for existing `facts` + recent `turns`
  (verify against real `db.all_facts()` / sessions API).
- `[ ]` 2.2 Hybrid `cognee_recall` — cheap vector first, FTS5 fallback.
- `[ ]` 2.3 **Cheap** context block in `_build_messages` (anomaly B: `CHUNKS`/
  vector only, relevance-gated, cached — **not** `GRAPH_COMPLETION`, **not** every
  turn unconditionally).
- `[ ]` 2.4 Background entity extraction during idle (anomaly C), not on the turn.
- `[ ]` 2.5 Optionally route `recall_facts`/`search_conversations` through Cognee.
- `[ ]` 2.6 Edge cases: empty/no-match/partial results.

**Deliverable:** Reworded queries find the right memory; no per-turn LLM tax.

### Phase 3 — Knowledge graph — `[ ]`
- `[ ]` 3.1 Configure graph store (Kuzu default; serialize writes — anomaly H).
- `[ ]` 3.2 `cognee_graph_query` via `recall`/`search` with
  `CYPHER`/`NATURAL_LANGUAGE`/graph query types (anomaly D — no `cognee.graph()`).
- `[ ]` 3.3 Cross-session entity linking (Cognee `cognify`).
- `[ ]` 3.4 `cognee_entities` via the cognify/extraction pipeline.
- `[ ]` 3.5 Optional graph-neighbor injection (cheap, gated).
- `[ ]` 3.6 Relationship trees rendered via existing `render_diagram`.

**Deliverable:** "What projects use Python?" / "How does X relate to Y?" answered
from the graph.

### Phase 4 — Advanced features — `[ ]`
- `[ ]` 4.1 `cognee_improve` (real signature `dataset=/session_ids=` — anomaly D).
- `[ ]` 4.2 `cognee_forget` (approval-gated; destructive=True).
- `[ ]` 4.3 `cognee_insights` via `recall(query_type=SUMMARIES/INSIGHTS-equiv)`.
- `[ ]` 4.4 Temporal classification (`TEMPORAL` retrieval).
- `[ ]` 4.5 Importance scoring → keep important facts in prompt.
- `[ ]` 4.6 Multi-user ACL only if/when Namma goes multi-user (else `user_id="default"`).

**Deliverable:** Full 7-tool set; periodic idle consolidation.

### Phase 5 — Learning Room deep integration — `[ ]`
- `[ ]` 5.1 Concept graph per learning topic.
- `[ ]` 5.2 Prerequisite inference from the graph.
- `[ ]` 5.3 Adaptive curriculum from known concepts.
- `[ ]` 5.4 Knowledge-gap analysis via `cognee_insights`.
- `[ ]` 5.5 Cross-topic concept linking.
- `[ ]` 5.6 Learning artifacts (diagrams/sims) become Cognee-searchable.

**Deliverable:** Self-adapting learning paths grounded in the learner's graph.

---

## 5. Configuration (corrected)

```yaml
# config.yaml — Cognee enhanced memory (optional; install: pip install 'cognee==1.2.*')
cognee:
  enabled: false                 # opt-in master switch
  vector_store: { type: lancedb, path: data/cognee/vectors }
  graph_store:  { type: kuzu,    path: data/cognee/graph }
  relational_store: { type: sqlite, path: data/cognee/metadata.db }
  llm:
    type: openai                 # EXPLICIT — do not silently inherit (anomaly A)
    model: gpt-4o-mini
  embedding:
    type: openai                 # EXPLICIT — chat-only providers (Claude) cannot embed
    model: text-embedding-3-small
    # local alternative: { type: ollama, model: nomic-embed-text }
  features:
    turns_to_session_memory: true   # turns → fast cache, NO per-turn LLM (anomaly C)
    cognify_on: explicit            # explicit | idle  (never every-turn)
    context_block: cheap            # CHUNKS/vector only, relevance-gated (anomaly B)
    entity_extraction: idle         # background, not on the turn
```

```bash
# .env — Cognee needs its OWN embedding-capable key (anomaly A)
COGNEE_LLM_API_KEY=sk-...
COGNEE_EMBEDDING_API_KEY=sk-...      # OpenAI key for text-embedding-3-*  (or use Ollama locally)
```

---

## 6. Acceptance criteria

- `[ ]` With `cognee.enabled: false` (default) Namma behaves **exactly** as today.
- `[ ]` Uninstalling the `cognee` package never crashes startup (lazy import).
- `[ ]` No measurable added latency on the reply path (ingest is async/session).
- `[ ]` Reworded recall ("data layer" ↔ "database architecture") succeeds.
- `[ ]` Disabling Cognee mid-use falls back to SQLite+FTS5 with no data loss.
- `[ ]` Embedding key missing → clear setup error, not a stack trace.

---

## 7. Changelog

- **2026-06-25** — Document created. Verdict: **implement (with corrections)**.
  Validated both source folders against the live codebase; flagged anomalies A–I.
  **Prerequisite complete:** Namma Agent confirmed MCP-capable and the
  **MCP settings UI (Config + Servers)** built & browser-verified — making Phase 0
  (MCP-server path) a config-only step. Cognee phases 0–5: **not started**.
