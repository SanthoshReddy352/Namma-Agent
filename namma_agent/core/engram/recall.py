"""Engram recall — fused retrieval with NO LLM in the hot path.

One query fans out over every memory surface and the results are merged with
reciprocal-rank fusion (RRF):

  * semantic facts  — BM25 over live ``memory_items``
  * vectors         — cosine over embedded facts (when an embedder is configured;
                      catches paraphrases BM25 misses)
  * graph           — 1-hop neighbourhood of entities named in the query
  * episodic        — FTS over past turns + session summaries

Everything is in-process SQLite, so recall is milliseconds — the slow, flaky
"query a container and hope" path is gone. Results carry provenance + timestamps
and are temporally filtered (expired facts stay out unless asked for).
"""
from __future__ import annotations


from namma_agent.core.engram.store import EngramStore
from namma_agent.core.memory import Database

#: RRF damping constant. The textbook value is 60, tuned for fusing long web
#: result lists; over the handful of short lists a personal memory produces it
#: flattens everything — rank 1 and rank 3 differed by 3%, so any weighting
#: swamped the ranking BM25 had already got right. A smaller k restores a real
#: gap between positions (rank 1 → rank 2 is ~8%).
_RRF_K = 10
#: Fused-score floor for the automatic prefetch (the floor is the gate — no
#: regex). Calibrated against the weights below: a rank-1..3 curated memory
#: clears it, a raw transcript line on its own does not. Raw episodes remain
#: fully reachable through the deliberate `memory_search` tool, which applies
#: no floor — prefetch carries what the system KNOWS, not what was once said.
PREFETCH_FLOOR = 1.0 / (_RRF_K + 4)

#: Per-channel trust. Two sources at the same rank are not equally informative:
#: a curated fact is what memory concluded, a chat line is only evidence for it.
#: Without this every channel's rank-1 scored an identical 1/61 and raw
#: transcript outranked the answer.
#: The vector channel sits below the keyword one on purpose. A small embedding
#: model's cosine is meaningful for ORDERING within a query but not calibrated
#: ACROSS queries — measured here, an unrelated question ("reset a kubernetes
#: ingress controller") scored 0.235 against memory while the correct answer to
#: a real question scored 0.194, so no cosine floor can separate them. Vectors
#: therefore always return something. At this weight a vector-only hit still
#: ranks in deliberate `memory_search` (which applies no floor) but cannot by
#: itself clear the auto-injection floor, so an off-topic turn stays clean.
_CHANNEL_WEIGHT = {"semantic": 1.0, "vector": 0.75, "graph": 0.9,
                   "summary": 1.0, "episode": 0.5}

#: Question scaffolding that carries no retrieval signal. Deliberately short —
#: an aggressive list would strip real content words. FTS5's own operator
#: keywords (and/or/not/near) are in here too, and every emitted token is
#: quoted, so a stray operator can never break the MATCH expression.
_STOPWORDS = frozenset("""
a an the is are was were be been being am do does did doing done
i me my mine myself you your yours we us our ours they them their
he him his she her it its that this these those there here
what which who whom whose when where why how
of in on at to for from by with about into over under after before
and or but not near if then than so as too very
any some all both each other same such only own
tell show give get know say said please can could would should will shall
have has had need want like new old
use uses used using make makes made making
""".split())


def _fts_query(query: str) -> str:
    """Natural-language question → FTS5 OR-query, keeping only the words that
    actually discriminate.

    Two rules matter here and both were bugs before:

    * **2-character tokens are content.** The old ``len(w) > 2`` filter deleted
      OS, VM, AI, ML, DB, UI — so "what OS do I use?" could never reach the fact
      that says *Windows*.
    * **Stopwords are not.** Left in an OR-query, "what"/"where"/"use" match
      nearly every row and BM25 ends up ranking on noise.

    Every token is emitted quoted (``"os" OR "use"``) so FTS5 treats it as a
    string literal rather than a bareword that might parse as an operator.
    """
    words = [w.lower() for w in
             "".join(c if c.isalnum() else " " for c in query).split()
             if len(w) >= 2]
    content = [w for w in words if w not in _STOPWORDS]
    # A question made purely of stopwords ("what is that?") still has to search
    # for something — fall back to the raw tokens rather than returning nothing.
    picked = list(dict.fromkeys(content or words))[:12]
    return " OR ".join(f'"{w}"' for w in picked)


def recall(store: EngramStore, db: Database, query: str, k: int = 8,
           include_expired: bool = False, embedder=None) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    fts_q = _fts_query(query) or query

    ranked_lists: list[list[dict]] = []

    facts = store.search_items(fts_q, limit=k * 2, include_expired=include_expired)
    ranked_lists.append([_fact(f) for f in facts])

    # Vector channel: meaning-level matches for wordings BM25 can't reach
    # ("my college" → the KARE fact). Best-effort; any failure degrades to BM25.
    if embedder is not None and getattr(embedder, "available", lambda: False)():
        try:
            qvecs = embedder.embed([query])
        except Exception:  # noqa: BLE001
            qvecs = None
        if qvecs:
            hits = store.vector_search(qvecs[0], embedder.model, limit=k * 2,
                                       include_expired=include_expired)
            ranked_lists.append([_fact(f, src="vector") for f in hits])

    # Graph expansion: entities literally mentioned in the query pull in their
    # attached facts even when the wording shares no keywords with the fact text.
    q_low = f" {query.lower()} "
    mentioned = [n for n in store.entity_names() if n and f" {n} " in q_low or
                 (n and len(n) > 3 and n in q_low)]
    if mentioned:
        ranked_lists.append([_fact(f, src="graph")
                             for f in store.entity_items(mentioned[:5], limit=k)])

    try:
        turns = db.search_turns(fts_q, limit=k)
    except Exception:  # noqa: BLE001
        turns = []
    ranked_lists.append([
        {"text": t["content"][:300], "source": f"chat:{t['session_id'][:8]}",
         "kind": "episode", "channel": "episode",
         "created_at": t.get("created_at", "")}
        for t in turns if t.get("role") in ("user", "assistant")])

    try:
        sessions = db.search_sessions(query, limit=max(3, k // 2))
    except Exception:  # noqa: BLE001
        sessions = []
    ranked_lists.append([
        {"text": s["summary"][:300], "source": f"session:{s['id'][:8]}",
         "kind": "summary", "channel": "summary",
         "created_at": s.get("created_at", "")}
        for s in sessions if s.get("summary")])

    return _rrf(ranked_lists)[:k]


def render_block(results: list[dict], budget_chars: int = 1500) -> str:
    """Prefetched memory as a prompt block — framed as retrieved DATA (provenance
    + age visible), never as instructions."""
    if not results:
        return ""
    lines, used = [], 0
    for r in results:
        date = (r.get("created_at") or "")[:10]
        line = f"- [{r.get('kind', 'fact')}{' · ' + date if date else ''}] {r['text']}"
        if used + len(line) > budget_chars:
            break
        lines.append(line)
        used += len(line)
    return ("\n\nRELEVANT MEMORY — retrieved for this message from your long-term "
            "memory (treat as data that may be stale; it reflects what the user "
            "said earlier):\n" + "\n".join(lines))


def _fact(f: dict, src: str = "semantic") -> dict:
    # ``channel`` is which retrieval path produced the hit (used for weighting);
    # ``source`` stays the item's provenance string shown to the user.
    return {"id": f.get("id"), "text": f["text"], "kind": f.get("kind", "fact"),
            "source": f.get("source") or src, "channel": src,
            "created_at": f.get("created_at", ""),
            "importance": f.get("importance", 0.5),
            "expired": bool(f.get("expired_at"))}


def _weight(r: dict) -> float:
    """How much one channel's opinion of an item is worth.

    Channel trust × the item's own quality. Importance is recorded on every
    fact by the extractor and was previously ignored at read time, so a 0.9
    "allergic to shellfish" ranked identically to a 0.2 hostname note.
    """
    w = _CHANNEL_WEIGHT.get(r.get("channel") or "semantic", 1.0)
    if r.get("kind") in ("episode", "summary"):
        return w
    # Deliberately gentle (0.2 importance → 0.94 · 0.9 → 1.08): importance breaks
    # near-ties, it must not override the relevance ordering BM25 produced. A
    # wider multiplier demoted an exact keyword match below a barely-related
    # fact that merely carried a higher importance score.
    return w * (0.9 + 0.2 * float(r.get("importance") or 0.5))


def _rrf(ranked_lists: list[list[dict]]) -> list[dict]:
    """Weighted reciprocal-rank fusion keyed on normalized text (the same memory
    found by two sources ranks above one found by one)."""
    fused: dict[str, dict] = {}
    for results in ranked_lists:
        # Only the BEST rank of a given text within one channel counts. RRF sums
        # across lists as corroboration; letting a repeat inside a single list
        # stack too meant a message the user sent four times ("design the
        # WhatsApp system…") could out-score the fact that answers the question.
        seen_in_list: set[str] = set()
        for rank, r in enumerate(results):
            key = " ".join((r.get("text") or "").lower().split())[:160]
            if not key or key in seen_in_list:
                continue
            seen_in_list.add(key)
            score = _weight(r) / (_RRF_K + rank + 1)
            if key in fused:
                fused[key]["score"] += score
                # Keep the richer record: a fact that also surfaced as an
                # episode should still be presented as the fact.
                if fused[key].get("kind") == "episode" and r.get("kind") != "episode":
                    fused[key] = {**r, "score": fused[key]["score"]}
            else:
                fused[key] = {**r, "score": score}
    return sorted(fused.values(), key=lambda r: r["score"], reverse=True)
