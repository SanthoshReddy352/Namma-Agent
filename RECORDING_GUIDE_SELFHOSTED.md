# 🅰 Track A shoot guide — Self-hosted (Best Use of Open Source)

The **MacBook track**. The **open-source Cognee engine runs 100% on your machine** — the
`cognee-mcp` container, local **Ollama** embeddings, **Kuzu** graph + **LanceDB** vectors +
**SQLite**. (By default the extraction/recall **LLM** is a hosted model — OpenCode
`big-pickle`; for a *literally* key-free build, re-pull `qwen2.5:7b` and use the commented
local-LLM block in `.env.cognee`. Either way the storage + embeddings stay local.) This guide
is the shoot list + the self-hosted-specific bits; **full per-clip narration lives in the
master** [`RECORDING_GUIDE.md`](RECORDING_GUIDE.md).

> One story, two videos. This is the **primary, always-available** track — shoot it in
> full. The cloud video (🅱 [`RECORDING_GUIDE_CLOUD.md`](RECORDING_GUIDE_CLOUD.md)) reuses
> ~90% of this footage and only re-shoots the backend chrome + VO.

---

## Setup (self-hosted)

```powershell
# 1. One-time: Docker + Ollama + the cognee image
scripts\setup_cognee.ps1

# 2. Start Namma (open the URL fullscreen, F11, 100% zoom)
python -m namma_agent --server          # → http://127.0.0.1:8000
```

3. **Settings → MCP → Cognee → Backend → Self-hosted** → **Reconnect** → wait for the
   green **Connected** dot. (First connect on a fresh volume runs a one-time DB migration
   ~30–60 s; if it fails once, click **Reconnect** again — see
   [`docs/COGNEE.md`](docs/COGNEE.md).)
4. **Behaviour:** *Auto-ingest chats* **ON**; *Recall in chat* **OFF** for now (so the
   recall tool call is visible on camera in Shots 4 & 6; turn ON only if a dry run is flaky).
5. **Seed + verify the self-hosted graph:**
   ```powershell
   python scripts\seed_demo_memory.py --backend local --reset --stress
   ```
   **Gate:** wait for **"✅ All questions land"** (10/10). Verified: **~100+ entities ·
   ~190+ links**.
6. Memory tab → **↻ Refresh** → graph renders from the local container's
   `visualize_graph_ui`. Rich + connected = ready.

---

## Shoot list (Shot numbers + full click-by-click scripts in the master)

Shots follow the master [`RECORDING_GUIDE.md`](RECORDING_GUIDE.md) (after the **origin
intro** VO). Self-hosted notes:

| Shot | Name | Self-hosted note |
|---|---|---|
| 1 | Cold open — the living graph | Graph from local `visualize_graph_ui`. |
| 2 | Money shot — keyword vs Cognee ⭐ | Identical UI; Cognee answers from **local Kuzu**. |
| 3 | "Find me a PG" — real work + remember ⭐ | Preference stored into the **local** graph. Rehearse the live `web_search`. |
| 4 | "Break down my project" — recall→plan→remember ⭐ | Recalls the project + July 5 deadline + solo build from the local graph; `add_goal`/`add_task`. |
| 5 | "Review this code" — read/shell + remember | `run_shell` git diff; decisions stored locally. |
| 6 | Payoff — fresh chat stitches the week ⭐⭐ | The local graph carries the whole week. |
| 7 | Improve — graph grows live | Consolidate → cognify on the local container. |
| 8 | **Backend switch** — assert THIS track | **VO (🅰):** "The open-source Cognee engine ran on my machine — Kuzu graph, LanceDB vectors, local embeddings. Same code, one click from cloud." ✂ cut the reconnect. |
| 9 | Forget + close | Local graph empties. |
| 10 | Under the hood (tag) | **528** tests + architecture + "zero Python deps; the memory engine is fully local." |

**Order:** origin VO over 1→2, then 3→4→5→6→7→8→9, with 10 over 8/9. Open on Shot 2 or 6
for the hook.

---

## The self-hosted winning angle (say it explicitly)

This track is judged on **Best Use of Open Source**, so make the open-source story loud:
- **Open engines, all local** — Kuzu (graph), LanceDB (vectors), SQLite (relational), and
  **Ollama embeddings** run free on your machine. (The extraction LLM is hosted by default —
  go qwen2.5:7b local if you want the whole pipeline key-free.)
- **Zero lock-in** — `cognee-mcp` is open source, run via Docker; Namma reaches it over
  MCP so it adds **no** Python dependencies.
- **Reproducible** — one `setup_cognee.ps1` and one seed command stand the whole demo up.

---

## Pre-flight (Track A)

- [ ] `setup_cognee.ps1` done; both containers up (`docker ps` → `namma_cognee`, `namma-cognee-ollama`).
- [ ] Backend = **Self-hosted**, **Connected** (green).
- [ ] `--backend local --reset --stress` → **✅ 10/10**.
- [ ] Shots 3–5 rehearsed; Shot 6 dry-run stitches the week.
- [ ] Shot 8 VO = the **🅰 local/free** line.
- [ ] Optional B-roll: `docker ps` showing the two local containers ("every byte is local").
- [ ] AI-usage disclosed in [`SUBMISSION.md`](SUBMISSION.md); submit before **July 5, 2026**.

Full story, criteria map, and troubleshooting: [`RECORDING_GUIDE.md`](RECORDING_GUIDE.md).
