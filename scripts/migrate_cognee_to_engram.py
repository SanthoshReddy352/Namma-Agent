"""One-shot Cognee → Engram import (MEMORY_SYSTEM_DESIGN.md §12 Phase 2).

Walks the old Cognee knowledge graph and lands it in Engram's native SQLite
store: nodes → ``memory_entities``, edges → ``memory_relations`` + one
sentence-sized ``memory_items`` fact per edge, all tagged
``source='import:cognee'`` so the Memory tab shows exactly where they came
from. Re-running is safe — facts whose text already exists live are skipped.

Three ways to reach the old graph (pick whichever still works for you):

  --json FILE     A ``{nodes, edges}`` dump — the shape the old
                  ``/api/memory/graph`` endpoint returned (and what the Cognee
                  Cloud graph API returns). Works with Cognee fully gone.
  --cloud         Pull straight from Cognee Cloud REST
                  (``GET /api/v1/datasets/{id}/graph``, X-Api-Key auth). The key
                  is read from ``.env.cognee.cloud`` (COGNEE_API_KEY) or the
                  environment; the instance URL from --url or COGNEE_SERVE_URL.
  --local         Spawn the self-hosted cognee MCP container (the ``cognee``
                  entry under ``mcp.servers`` in your config) and parse the
                  graph out of its ``visualize_graph_ui`` HTML — the same path
                  the old Memory tab used. Needs Docker + the old image.

Usage (from the repo root, venv active):
    python scripts/migrate_cognee_to_engram.py --json graph_dump.json
    python scripts/migrate_cognee_to_engram.py --cloud --url https://<id>.cognee.ai
    python scripts/migrate_cognee_to_engram.py --local
    python scripts/migrate_cognee_to_engram.py --json dump.json --dry-run
Options: --db data/namma_agent.db (default) · --dataset namma_agent_memory ·
--dry-run (report only, write nothing).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

# Windows consoles default to cp1252 — make prints crash-proof.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from namma_agent.core.docscan import scan_text          # noqa: E402
from namma_agent.core.engram.store import EngramStore   # noqa: E402
from namma_agent.core.memory import Database            # noqa: E402


# ── fetching the old graph ────────────────────────────────────────────────────

def _read_env_file(path: Path) -> dict:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def _node_label(n: dict) -> str:
    """Display name for a node — cloud nodes carry it in properties.name,
    self-hosted viz nodes in label/type (old memory_graph logic)."""
    props = n.get("properties") or {}
    name = str(props.get("name") or "").strip()
    if name:
        return name
    lab = str(n.get("label") or n.get("name") or "").strip()
    typ = str(n.get("type") or "").strip()
    return typ if (typ and lab.startswith(typ + "_")) else (lab or typ or "")


def _normalize_graph(g: dict) -> tuple[list[dict], list[dict]]:
    """Any of the known dump shapes → (nodes, edges) with id/label/type and
    source/target/relation keys."""
    nodes = []
    for n in g.get("nodes") or []:
        if not isinstance(n, dict) or not n.get("id"):
            continue
        label = _node_label(n)
        if label:
            nodes.append({"id": n["id"], "label": label,
                          "type": str(n.get("type") or "thing")})
    ids = {n["id"] for n in nodes}
    edges = []
    for e in (g.get("edges") or g.get("links") or []):
        if not isinstance(e, dict):
            continue
        src, dst = e.get("source"), e.get("target")
        rel = str(e.get("relation") or e.get("label") or e.get("rel") or "").strip()
        if src in ids and dst in ids:
            edges.append({"source": src, "target": dst,
                          "relation": rel or "related_to"})
    return nodes, edges


def fetch_json(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))


def fetch_cloud(base: str, dataset: str) -> dict:
    key = (os.environ.get("COGNEE_API_KEY")
           or _read_env_file(_REPO / ".env.cognee.cloud").get("COGNEE_API_KEY", "")).strip()
    if not key:
        sys.exit("No Cognee Cloud API key: set COGNEE_API_KEY or .env.cognee.cloud.")
    base = base.rstrip("/")

    def api_get(p: str):
        req = urllib.request.Request(base + p, headers={"X-Api-Key": key})
        with urllib.request.urlopen(req, timeout=40) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    datasets = api_get("/api/v1/datasets/") or []
    ds = next((d for d in datasets if d.get("name") == dataset), None) \
        or (datasets[0] if datasets else None)
    if not ds:
        sys.exit(f"Cognee Cloud has no datasets at {base} — nothing to import.")
    print(f"Dataset: {ds.get('name')} ({ds.get('id')})")
    return api_get(f"/api/v1/datasets/{ds['id']}/graph") or {}


def _balanced_array(html: str, start: int):
    """Parse the JSON array beginning at html[start] == '[' (nesting + strings)."""
    depth, in_str, esc, quote = 0, False, False, ""
    for i in range(start, len(html)):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == quote:
                in_str = False
        elif c in ("\"", "'"):
            in_str, quote = True, c
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[start:i + 1])
                except ValueError:
                    return None
    return None


def _extract_array(html: str, var: str) -> list:
    last: list = []
    for m in re.finditer(rf"\b{var}\s*=\s*\[", html):
        arr = _balanced_array(html, m.end() - 1)
        if isinstance(arr, list):
            if arr:
                return arr
            last = arr
    return last


def fetch_local() -> dict:
    """Boot the cognee MCP container from the config's server entry and pull the
    graph out of visualize_graph_ui — the old Memory-tab path."""
    from namma_agent.config import load_config
    from namma_agent.mcp.client import StdioMCPClient

    servers = (load_config().get("mcp") or {}).get("servers") or []
    srv = next((s for s in servers if isinstance(s, dict)
                and s.get("name") == "cognee"), None)
    if not srv:
        sys.exit("No 'cognee' server under mcp.servers in config — use --json/--cloud.")
    client = StdioMCPClient("cognee", srv.get("command") or [], env=srv.get("env"))
    if not client.connect(timeout=120):
        sys.exit("Couldn't start/connect the cognee MCP container (is Docker up?).")
    try:
        dataset = None
        try:
            info = client.call_tool_raw("get_client_info_json", {}, timeout=30)
            isc = info.get("structuredContent") if isinstance(info, dict) else None
            if isinstance(isc, dict):
                dataset = (isc.get("default_dataset")
                           or (isc.get("client") or {}).get("default_dataset"))
        except Exception:  # noqa: BLE001
            dataset = None
        for args in ([{"dataset_name": dataset}] if dataset else []) + [{}]:
            raw = client.call_tool_raw("visualize_graph_ui", args, timeout=180)
            sc = raw.get("structuredContent") if isinstance(raw, dict) else None
            html = (sc or {}).get("html", "") if isinstance(sc, dict) else ""
            nodes = _extract_array(html, "nodes")
            if nodes:
                return {"nodes": nodes, "edges": _extract_array(html, "links")}
        sys.exit("Cognee returned an empty graph — nothing to import.")
    finally:
        client.close()


# ── importing into Engram ─────────────────────────────────────────────────────

def import_graph(store: EngramStore, nodes: list[dict], edges: list[dict],
                 dry_run: bool = False) -> dict:
    by_id = {n["id"]: n for n in nodes}
    existing = {" ".join((i.get("text") or "").lower().split())
                for i in store.list_items(limit=100_000)}
    report = {"nodes": 0, "facts": 0, "relations": 0, "skipped": 0, "flagged": 0}

    linked: set = set()
    for e in edges:
        src, dst = by_id.get(e["source"]), by_id.get(e["target"])
        if not (src and dst):
            continue
        linked.update((e["source"], e["target"]))
        rel_words = (e["relation"] or "related_to").replace("_", " ").strip()
        text = f"{src['label']} {rel_words} {dst['label']}."
        norm = " ".join(text.lower().split())
        if norm in existing:
            report["skipped"] += 1
            continue
        existing.add(norm)
        flagged = scan_text(text).flagged
        if flagged:
            report["flagged"] += 1
        report["facts"] += 1
        report["relations"] += 1
        if dry_run:
            continue
        item_id = store.add_item(
            text, kind="fact", subject=src["label"], predicate=e["relation"],
            object=dst["label"], importance=0.4, source="import:cognee",
            screen_status=("flagged" if flagged else "ok"))
        store.add_relation(src["label"], e["relation"], dst["label"],
                           item_id=item_id)

    for n in nodes:            # entities that had no surviving edge still count
        if n["id"] not in linked:
            report["nodes"] += 1
            if not dry_run:
                store.upsert_entity(n["label"], type=n.get("type") or "thing")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--json", metavar="FILE", help="import a {nodes,edges} dump")
    src.add_argument("--cloud", action="store_true", help="pull from Cognee Cloud REST")
    src.add_argument("--local", action="store_true", help="pull from the docker MCP container")
    ap.add_argument("--url", default=os.environ.get("COGNEE_SERVE_URL", "https://api.cognee.ai"),
                    help="Cognee Cloud instance URL (with --cloud)")
    ap.add_argument("--dataset", default="namma_agent_memory",
                    help="cloud dataset name (default: namma_agent_memory)")
    ap.add_argument("--db", default=str(_REPO / "data" / "namma_agent.db"),
                    help="Engram SQLite file (default: data/namma_agent.db)")
    ap.add_argument("--dry-run", action="store_true", help="report only, write nothing")
    args = ap.parse_args()

    if args.json:
        graph = fetch_json(args.json)
    elif args.cloud:
        graph = fetch_cloud(args.url, args.dataset)
    else:
        graph = fetch_local()

    nodes, edges = _normalize_graph(graph)
    print(f"Fetched graph: {len(nodes)} node(s), {len(edges)} edge(s)")
    if not nodes:
        sys.exit("Nothing to import.")

    store = EngramStore(Database(args.db))
    report = import_graph(store, nodes, edges, dry_run=args.dry_run)
    verb = "Would import" if args.dry_run else "Imported"
    print(f"{verb}: {report['facts']} fact(s), {report['relations']} relation(s), "
          f"{report['nodes']} standalone entit(ies) → {args.db}")
    if report["skipped"]:
        print(f"Skipped {report['skipped']} duplicate(s) already in memory.")
    if report["flagged"]:
        print(f"Quarantined {report['flagged']} item(s) that failed injection "
              f"screening (screen_status='flagged', out of recall).")


if __name__ == "__main__":
    main()
