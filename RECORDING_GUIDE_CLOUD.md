# 🅱 Track B shoot guide — Cognee Cloud (Best Use of Cognee Cloud)

The **iPhone track**. The **same Namma code** points at **managed Cognee Cloud** instead
of the local stack — the cloud owns its DB + embeddings, so there's **no Ollama, no Kuzu,
no volume**. This guide is the shoot list + the cloud-specific bits; **full per-clip
narration lives in the master** [`RECORDING_GUIDE.md`](RECORDING_GUIDE.md).

> **Cognee Cloud opens July 2, 2026** (the organizers confirmed). Until then it returns *"We're
> at capacity… waitlist."* Plan: shoot Track A in full now; **July 2–5**, switch to Cloud,
> seed it, and re-shoot the backend chrome + re-record VO over the shared footage. The
> switch + cloud graph-sync code is proven working.

---

## Setup (cloud)

```powershell
# Namma already running from the self-hosted shoot? Good — same app, just switch backend.
python -m namma_agent --server          # if not already up → http://127.0.0.1:8000
```

1. **Settings → MCP → Cognee → Backend → Cognee Cloud** card.
2. Paste your **Instance URL** (`https://<id>.cognee.ai`) + **API key**
   (platform.cognee.ai, dev plan code `COGNEE-35`) → **Connect to Cognee Cloud**.
   ✂ the ~25 s reconnect. Status → **Connected · Cognee Cloud**.
3. **Behaviour:** *Auto-ingest chats* **ON**; *Recall in chat* **OFF** (visible recall on
   camera; turn ON only if a dry run is flaky).
4. **Seed + verify the cloud graph:**
   ```powershell
   python scripts\seed_demo_memory.py --backend cloud --serve-url https://<id>.cognee.ai --reset --stress
   ```
   (`--api-key` is reused from `.env.cognee.cloud` if you already connected in the UI.)
   **Gate:** wait for **"✅ All questions land"** (10/10) — same graph, on the cloud.
5. Memory tab → **↻ Refresh** → the graph renders, **synced from the Cognee Cloud REST
   API** (`GET /api/v1/datasets/{id}/graph`). Same Obsidian-style canvas as self-hosted.

> **Seed both backends in one go** (do this once, ideally July 2):
> `python scripts\seed_demo_memory.py --backend both --serve-url https://<id>.cognee.ai --reset --stress`
> — identical graph on each track, so every clip works on either video.

---

## Shoot list (Shot numbers + full click-by-click scripts in the master)

Shots follow the master [`RECORDING_GUIDE.md`](RECORDING_GUIDE.md) (after the **origin
intro** VO). Cloud notes:

| Shot | Name | Cloud note |
|---|---|---|
| 1 | Cold open — the living graph | Same canvas, **synced from Cognee Cloud REST**. |
| 2 | Money shot — keyword vs Cognee ⭐ | Identical UI; Cognee answers from the **cloud** graph. |
| 3 | "Find me a PG" — real work + remember ⭐ | Preference stored into the **cloud** graph. Same query as Track A. |
| 4 | "Break down my project" — recall→plan→remember ⭐ | Recalls the project + July 5 deadline + solo build from the cloud graph. |
| 5 | "Review this code" — read/shell + remember | Decisions stored in the cloud. |
| 6 | Payoff — fresh chat stitches the week ⭐⭐ | The cloud graph carries the whole week. |
| 7 | Improve — graph grows live | Consolidate → cognify routed to the cloud. |
| 8 | **Backend switch** — assert THIS track | **VO (🅱):** "One switch — same code, now on managed Cognee Cloud. Zero local infra. Same graph, every op against the cloud — and the same code runs fully self-hosted too." → **bridge into the Platform Tour.** |
| **C1–C8** | **🌩 Cognee Cloud Platform Tour** ⭐⭐ | **THE cloud differentiator** — see below. |
| 9 | Forget + close | Cloud graph empties (proves forget on cloud). |
| 10 | Under the hood (tag) | **528** tests + architecture + "one codebase, both tracks." |

**Order:** origin VO over 1→2, then 3→4→5→6→7→8, then **C1→C8 (the tour)**, then 9, with 10 over 8/9.

---

## 🌩 The Platform Tour (C1–C8) — what wins Best Use of Cognee Cloud

After Shot 8 flips to cloud, leave the Namma app, open **platform.cognee.ai**, and walk the
console — proving Namma's memory is a **live, managed, observable** knowledge base. Full
click-by-click scripts + narration are in [`RECORDING_GUIDE.md` → Part 3](RECORDING_GUIDE.md#part-3--cloud-platform-tour-c1c8--track-b-only). Every page shows the same **`namma_agent_memory`** brain.

| Clip | Page | Show / say (short) |
|---|---|---|
| **C1** | `/dashboard` ⭐ | 6 live counters; type a query in "Search your memory" → it lands in the **Memory Activity** log. "Every entity, relationship, and search — one managed dashboard." |
| **C2** | `/datasets` ⭐ | the `namma_agent_memory` **brain** + its ingested docs; paste a note → **Processing→Ready**. "Add-and-cognify turns text into graph automatically." |
| **C3** | `/knowledge-graph` ⭐ | the same dense graph, **hosted & rendered by Cognee Cloud**. "The web that powers recall, living in the cloud." |
| **C4** | `/search` ⭐ | Company-Brain scope → ask a multi-hop question → answer synthesized from the graph. "Recall, straight from the cloud console." |
| **C5** | `/schema` ⭐ | the **inferred ontology** — Person/Project/Tool/Event types + relations; Model/Prompt/Ontology controls. "Memory with structure." |
| **C6** | `/sessions` | agent sessions split into **recall vs remember**, with token + **USD cost**. "Full observability." *(Populate via a session_id write first; optional.)* |
| **C7** | `/skills` | upload a short skill md → **procedural memory as a graph** (instructions + tools). "Not just facts — how to do things." *(Optional.)* |
| **C8** | close | "One config entry → a managed, searchable, observable brain. Zero infra, total visibility." |

> **Populate before shooting:** finish the cloud seed, then dry-run all 7 pages (Setup 0.7 in
> the master). Sessions/Skills may need a nudge (C6/C7 notes) — treat them as optional if empty.

**Fastest path:** you do **not** re-shoot the whole story. Re-shoot **Shot 8** (the cloud
chrome), the **Memory tab** showing **Connected · Cognee Cloud** + the cloud-synced graph
(Shots 1/2/7/9 backgrounds), and **re-record the VO** with the cloud emphasis. The
conversational task shots (3–6) are backend-agnostic — reuse the Track A takes, or re-run
them on cloud if you want the timeline chrome to read "cloud."

---

## The cloud winning angle (say it explicitly)

This track is judged on **Best Use of Cognee Cloud**, so make the managed-cloud story loud:
- **One config entry** flips the entire memory layer to the cloud — no code change.
- **Zero local infrastructure** — no Ollama, no Kuzu, no volume; the cloud owns DB +
  embeddings + the graph.
- **Graph parity** — the same Obsidian-style canvas, synced live from the cloud REST API.
- **Same four ops, same agent loop** — remember/recall/improve/forget all route to the
  cloud through the identical MCP entry.
- **⭐ Deep platform engagement (the clincher)** — the **Platform Tour (C1–C8)** shows Namma's
  memory as a fully managed product: **Dashboard** metrics + live activity, **Datasets/Brains**,
  hosted **Knowledge Graph**, cloud **Search**, inferred **Schema/ontology**, **Sessions**
  analytics, and **Skills**. Judges want *depth* of Cognee use — this is it, on screen.

---

## Pre-flight (Track B)

- [ ] Cognee Cloud reachable (post-**July 2**); Backend = **Cognee Cloud**, **Connected**.
- [ ] `--backend cloud --serve-url … --reset --stress` → **✅ 10/10** on the cloud.
- [ ] Memory tab graph fills from the cloud REST sync (↻ Refresh if empty).
- [ ] **platform.cognee.ai dry-run done** — `namma_agent_memory` shows on Dashboard / Datasets /
      Knowledge Graph / Search / Schema; Sessions & Skills populated (C6/C7) or planned as skips.
- [ ] Shot 8 VO = the **🅱 managed/cloud** line; **Platform Tour C1–C8** planned/shot.
- [ ] If reusing Track A task footage, captions still read correctly (no "self-hosted" text on screen).
- [ ] AI-usage disclosed in [`SUBMISSION.md`](SUBMISSION.md); submit before **July 5, 2026**.

---

## If cloud misbehaves (it was intermittent in prep)

- *Graph empty / "self-hosted-only" overlay:* ↻ Refresh — on cloud it pulls from the REST
  API and should fill.
- *`remember` returns 409 / "ProgrammingError":* a **Cognee Cloud–side** DB error (not a
  Namma bug); retry, or re-run `--backend cloud … --reset --stress`. The `seed_one` check
  now flags these as real failures so you'll see them immediately.
- *Switch seems stuck:* it force-removes the old container first; give it ~25 s, then
  **Reconnect**.

Full story, criteria map, and troubleshooting: [`RECORDING_GUIDE.md`](RECORDING_GUIDE.md)
and [`docs/COGNEE.md`](docs/COGNEE.md).
