"""Seed Cognee with a coherent — but deliberately *dense* — set of demo memories, so
the knowledge graph looks great, the recall demos are *repeatable*, and the agent can
be **stress-tested** with hard, multi-hop, reworded questions on camera.

It drives the **running Namma app** over HTTP (`/api/memory/*`), so it uses the app's
existing Cognee connection — no second container, no Kuzu-lock clash — and works the
same whether the app is on the self-hosted or the Cognee Cloud backend.

Usage (start the app first: `python -m namma_agent --server`):
    python scripts/seed_demo_memory.py                 # add the demo facts (cognify)
    python scripts/seed_demo_memory.py --reset         # FORGET everything first, then seed
    python scripts/seed_demo_memory.py --reset --stress # seed, then run the stress battery
    python scripts/seed_demo_memory.py --stress-only    # don't seed; just run the battery
    python scripts/seed_demo_memory.py --url http://127.0.0.1:8000

Target a specific backend (switches the app's Cognee backend first, then seeds):
    python scripts/seed_demo_memory.py --backend local --reset --stress
    python scripts/seed_demo_memory.py --backend cloud --reset --stress \
        --serve-url https://<id>.cognee.ai            # --api-key reused from .env.cognee.cloud if set
    python scripts/seed_demo_memory.py --backend both  --reset --stress \
        --serve-url https://<id>.cognee.ai            # seed BOTH (local, then cloud), restore to local

`--backend both` gives you an identical demo graph on each track — so every clip works
on either backend. Cloud is skipped gracefully (not failed) if it can't connect, e.g.
while Cognee Cloud is waitlisted.

The facts tell one connected story — a solo developer (Santhosh, from Nellore), the
project and its components, the tools, and the event — with **explicit cross-relations**,
so the graph has rich, multi-hop structure. That lets a *reworded* recall ("which engine
do I use to store relationships?" → Kuzu) and a *multi-hop* recall ("what does the part of
my app that users actually see run on?" → React) visibly beat keyword search.

Each fact below is a short multi-entity paragraph on purpose: Cognee's cognify links the
entities mentioned together in one extraction pass, so a few rich facts produce a denser,
more connected graph than many one-word atoms (and run fewer slow cognify calls).
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import urllib.error

# Windows consoles default to cp1252, which can't encode the arrows/checkmarks below.
try:  # Python 3.7+: make our own stdout UTF-8 so prints never crash the seed.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001 — older Python / non-reconfigurable stream
    pass

# One connected story → a graph worth showing. Multi-entity sentences on purpose so
# cognify links them. This is a SOLO developer's graph (Santhosh, from Nellore, built
# Namma Agent alone) — every multi-hop chain runs through the person, the project's
# components, and the tools, not a team. NOTE: we intentionally do NOT seed "Rust",
# "Tally", or "side project" — those are added *live* on camera in RECORDING_GUIDE.md
# Shot 7 to show the graph grow, so seeding them would spoil that beat.
FACTS = [
    # — the person (hub) —
    "I'm Santhosh, a solo indie developer from Nellore, and I built Namma Agent on my own "
    "— a cloud-only personal AI assistant. Python is my favourite language and I wrote "
    "every part of Namma Agent in it.",
    # — the project's core stack (web UI = React, the part users see) —
    "Namma Agent's brain is a Claude model from Anthropic, called over the API. Its "
    "backend is built with FastAPI, and the part users actually see — its web UI — is "
    "built in React.",
    # — the memory upgrade + the 'before' (sets up the money shot) —
    "I added Cognee to Namma Agent to give it a semantic, knowledge-graph memory. Before "
    "Cognee, Namma's memory was a single SQLite file using FTS5 keyword search, which "
    "missed anything I reworded.",
    # — how Cognee is wired in (isolation story; reach via MCP) —
    "The way Namma Agent reaches its Cognee memory engine is through MCP, the Model "
    "Context Protocol. Namma uses MCP, and only MCP, to reach Cognee, so Cognee adds no "
    "Python dependencies to Namma and runs fully containerized in Docker.",
    # — the three self-hosted engines (money-shot fact: graph store = Kuzu) —
    "On the self-hosted setup, Cognee keeps memory across three engines: Kuzu as the "
    "graph store, LanceDB as the vector store, and SQLite as the relational store. I "
    "prefer Kuzu for storing how things relate.",
    # — local + free, and the managed alternative —
    "Cognee's embeddings and extraction run locally and free on Ollama, so the "
    "self-hosted track needs no API keys. The managed alternative is Cognee Cloud.",
    # — the event introduced me to Cognee (matches the real origin story) + deadline —
    "The WeMakeDevs x Cognee hackathon, themed 'The Hangover Part AI', is what "
    "introduced me to Cognee. I'm presenting Namma Agent there, and the submission "
    "deadline is July 5, 2026.",
    # — two tracks, one codebase —
    "I'm entering two hackathon tracks with one codebase: Best Use of Open Source for "
    "the self-hosted Cognee setup, and Best Use of Cognee Cloud for the managed one.",
    # — Learning Room → memory loop (study becomes memory) —
    "Namma Agent has a Learning Room that teaches one concept at a time and draws a "
    "diagram for each. When I finish a module, its recap is pushed into the Cognee "
    "knowledge graph, so what I study becomes part of my memory.",
    # — solo build: I made the voice + Telegram bridge myself —
    "Since I build Namma Agent solo, I wrote its voice features and its Telegram "
    "messaging bridge myself.",
    # — Namma does real work (sets up the PG / planning / code-review demos) —
    "Namma Agent does real work for me, not just memory: it searches the web, breaks "
    "projects into tasks and goals, and reviews my code.",
    # — solo workflow: I lean on Namma to plan and review —
    "Building solo for the hackathon, I rely on Namma itself to plan my work, review my "
    "code, and keep track of the decisions I make.",
]

# The stress battery: hard questions that need *semantic* recall and, for most, a
# *multi-hop* graph traversal (person → trait, component → tech, feature → effect).
# `expect` lists acceptable answer tokens (any one, case-insensitive, = a pass).
# `kind` is just for the on-screen/printed label.
STRESS_QUERIES = [
    {"q": "which engine do I use to store relationships?",
     "expect": ["kuzu"], "kind": "reworded (graph store)"},
    {"q": "what introduced me to the memory technology I now use?",
     "expect": ["hackathon", "wemakedevs", "cognee hackathon"], "kind": "2-hop (event→introduced)"},
    {"q": "what does the part of my app that users actually see run on?",
     "expect": ["react"], "kind": "2-hop (component→tech)"},
    {"q": "what did my assistant store memories in before this upgrade?",
     "expect": ["sqlite", "fts5", "keyword"], "kind": "temporal (before-state)"},
    {"q": "where do my finished lessons end up?",
     "expect": ["graph", "cognee"], "kind": "2-hop (feature→effect)"},
    {"q": "what runs my embeddings locally for free?",
     "expect": ["ollama"], "kind": "reworded (tool)"},
    {"q": "which town is the person who built Namma Agent from?",
     "expect": ["nellore"], "kind": "2-hop (person→location)"},
    {"q": "when is the competition I'm presenting at due?",
     "expect": ["july 5", "july 5th", "5 july"], "kind": "reworded (event→date)"},
    {"q": "how does my assistant reach its memory engine without adding dependencies?",
     "expect": ["mcp"], "kind": "reworded (integration)"},
    {"q": "what do I write all my code in?",
     "expect": ["python"], "kind": "reworded (language)"},
]


def post(base: str, path: str, body: dict, timeout: int = 900) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def get(base: str, path: str, timeout: int = 20) -> dict:
    with urllib.request.urlopen(base + path, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def run_stress(base: str) -> int:
    """Fire every stress query through the compare endpoint (keyword vs Cognee) and
    report, per question: did keyword search whiff, and did Cognee return the expected
    answer. Returns the number of FAILED questions (0 = a clean run, ready to record).

    Each Cognee recall runs an LLM graph-completion that can be slow (a reasoning
    model like OpenCode's big-pickle takes ~20-30s; a rate-limited Groq call can
    back off ~128s). Firing all 10 queries back-to-back stacks these slow calls until
    one exceeds its timeout — and the MCP client's watchdog then KILLS the (--rm)
    Cognee container, so every later call fails with 'Errno 22'. So we **pace** the
    battery: a short gap between queries gives each recall room to finish. Tune with
    NAMMA_STRESS_PACE_SEC (raise it if recalls fail; 0 disables pacing on a fast,
    unmetered backend)."""
    import os
    pace = float(os.environ.get("NAMMA_STRESS_PACE_SEC", "10"))
    print("\n" + "=" * 72)
    print("STRESS TEST — multi-hop / reworded recall (keyword vs Cognee)")
    print(f"(pacing {pace:.0f}s between queries so slow recalls don't stack and kill the container)")
    print("=" * 72)
    failed = 0
    clean_whiffs = 0
    for i, item in enumerate(STRESS_QUERIES, 1):
        if i > 1 and pace > 0:
            time.sleep(pace)
        q, expect, kind = item["q"], item["expect"], item["kind"]
        try:
            out = post(base, "/api/memory/compare", {"query": q}, timeout=180)
        except Exception as exc:  # noqa: BLE001
            print(f"[{i:2}/{len(STRESS_QUERIES)}] ERROR calling compare: {exc}")
            failed += 1
            continue
        fts = out.get("fts") or {}
        cog = out.get("cognee") or {}
        kw_count = int(fts.get("count") or 0)
        answer = (cog.get("answer") or "")
        low = answer.lower()
        hit = next((e for e in expect if e.lower() in low), None)
        ok = bool(hit)
        if not ok:
            failed += 1
        if kw_count == 0:
            clean_whiffs += 1
        status = "PASS" if ok else "FAIL"
        kw = "whiff" if kw_count == 0 else f"{kw_count} hit(s)"
        print(f"[{i:2}/{len(STRESS_QUERIES)}] {status}  keyword:{kw:>8}  "
              f"cognee→{(hit or '∅'):<10}  «{kind}»")
        print(f"        Q: {q}")
        snippet = " ".join(answer.split())[:140]
        print(f"        A: {snippet or '(no answer)'}")
    print("-" * 72)
    print(f"Result: {len(STRESS_QUERIES) - failed}/{len(STRESS_QUERIES)} questions "
          f"answered by Cognee; {clean_whiffs} are clean keyword 'whiffs' "
          f"(good money-shot candidates).")
    if failed:
        print(f"⚠  {failed} FAILED — re-run after the graph finishes building, or reword "
              f"the seed fact behind that question. Don't record until this is 0.")
    else:
        print("✅ All questions land. The agent is camera-ready for the stress test.")
    print("Ask these same questions in a fresh CHAT to stress-test the agent end-to-end\n"
          "(it will call mcp_cognee_recall and reason across the hops on screen).")
    return failed


def wait_connected(base: str, attempts: int = 30, every: int = 5) -> bool:
    """Poll /api/memory/status until Cognee reports connected (or give up)."""
    for _ in range(attempts):
        try:
            if get(base, "/api/memory/status").get("connected"):
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(every)
    return False


def ensure_backend(base: str, mode: str, serve_url: str = "", api_key: str = "") -> bool:
    """Switch the app's Cognee backend to ``mode`` (local|cloud) and wait until it's
    connected. Retries the register once — a fresh self-hosted volume makes cognee run
    a one-time DB migration that can eat the first handshake; a cloud reconnect can also
    be slow. Returns True only when Cognee is actually answering on that backend."""
    body = {"mode": mode}
    if mode == "cloud":
        if serve_url:
            body["serve_url"] = serve_url
        if api_key:
            body["api_key"] = api_key
    for attempt in (1, 2):
        print(f"Switching Cognee backend → {mode} (attempt {attempt})…")
        try:
            out = post(base, "/api/cognee/register", body, timeout=150)
        except Exception as exc:  # noqa: BLE001
            print(f"  register call failed: {exc}")
            out = {}
        if not out.get("ok") and out.get("error"):
            print(f"  register said: {out['error']}")
        if wait_connected(base):
            print(f"  ✅ connected on {mode}.")
            return True
        print(f"  not connected yet on {mode} — retrying…" if attempt == 1
              else f"  ✗ could not connect on {mode}.")
    return False


def seed_one(base: str, reset: bool, stress: bool, label: str = "") -> int:
    """Reset (optional) + seed all FACTS + (optional) run the stress battery on the
    CURRENTLY-CONNECTED backend. Returns the number of stress failures (0 if no stress)."""
    tag = f"[{label}] " if label else ""
    if reset:
        print(f"{tag}Resetting memory (forget everything)…")
        print("  ", post(base, "/api/memory/forget", {"everything": True}, timeout=120))

    bad = 0
    for i, fact in enumerate(FACTS, 1):
        t0 = time.time()
        out = post(base, "/api/memory/remember", {"text": fact, "permanent": True})
        content = (out.get("content") or out.get("error") or "")
        # The MCP call can return ok=True with an *error string* as content (e.g. a
        # cloud 409) — treat that as a real failure so a broken backend is obvious.
        real_ok = bool(out.get("ok")) and "error" not in content.lower()
        if not real_ok:
            bad += 1
        msg = content.splitlines()
        print(f"{tag}[{i}/{len(FACTS)}] ({time.time()-t0:.0f}s) ok={real_ok} "
              f"{msg[0][:90] if msg else ''}")
    if bad:
        print(f"{tag}⚠  {bad}/{len(FACTS)} facts failed to store — backend is unhealthy "
              f"(corrupted volume? cloud 409?). See docs/COGNEE.md troubleshooting.")

    g = get(base, "/api/memory/graph", timeout=180)
    print(f"\n{tag}Graph now: {len(g.get('nodes', []))} entities · {len(g.get('edges', []))} links.")
    print(f"{tag}Money-shot try: 'which engine do I use to store relationships?' → Kuzu")
    print(f"{tag}Multi-hop try:  'what does the part of my app that users actually see run on?' → React")

    return run_stress(base) if stress else 0


def main() -> int:
    args = sys.argv[1:]
    reset = "--reset" in args
    stress = "--stress" in args
    stress_only = "--stress-only" in args
    base = "http://127.0.0.1:8000"
    if "--url" in args:
        base = args[args.index("--url") + 1].rstrip("/")
    backend = (args[args.index("--backend") + 1].lower() if "--backend" in args else "")
    serve_url = (args[args.index("--serve-url") + 1] if "--serve-url" in args else "")
    api_key = (args[args.index("--api-key") + 1] if "--api-key" in args else "")

    # Reachability check (independent of which backend is selected).
    try:
        status = get(base, "/api/memory/status")
    except Exception as exc:  # noqa: BLE001
        print(f"Can't reach Namma at {base} — start it first "
              f"(`python -m namma_agent --server`). ({exc})")
        return 1
    print(f"Connected to Namma at {base}.")

    # --- multi-backend mode: switch + seed each requested track --------------
    if backend:
        targets = ["local", "cloud"] if backend == "both" else [backend]
        if backend not in ("local", "cloud", "both"):
            print("--backend must be one of: local | cloud | both")
            return 1
        worst = 0
        for t in targets:
            print("\n" + "#" * 72 + f"\n# BACKEND: {t}\n" + "#" * 72)
            if not ensure_backend(base, t, serve_url, api_key):
                if t == "cloud":
                    print("Cloud unavailable (waitlisted / wrong URL / key) — skipping it. "
                          "Re-run for cloud once it's reachable.")
                    continue
                return 1
            worst = max(worst, seed_one(base, reset, stress, label=t))
        if backend == "both":
            print("\nRestoring app to the self-hosted backend (the always-available default)…")
            ensure_backend(base, "local")
        return 1 if worst else 0

    # --- single, currently-connected backend (original behaviour) ------------
    if not status.get("connected"):
        print("Namma is up but Cognee isn't connected. Settings → MCP → Cognee → "
              "Register / Reconnect (or pass --backend local|cloud), then re-run.")
        return 1
    if stress_only:
        return 1 if run_stress(base) else 0
    rc = seed_one(base, reset, stress)
    if not stress:
        print("\nTip: run with --stress to verify every hard question lands before recording.")
    return 1 if rc else 0


if __name__ == "__main__":
    raise SystemExit(main())
