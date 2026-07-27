# Memory Benchmarks

"Grows with you" and "remembers you" are the two most common personal-agent
claims — and almost nobody publishes a number for them. This page is Namma's
number: what we measure, how, the current results, and how to reproduce them
yourself **without an API key**.

## What is measured

The eval answers one concrete question: *if the user states a fact once, does
the agent find it when asked later, phrased differently?*

Implementation: [`namma_agent/core/engram/evaluate.py`](../namma_agent/core/engram/evaluate.py),
runner: [`scripts/memory_eval.py`](../scripts/memory_eval.py).

- A dataset of **12 (fact, question, expected-answer) cases** modeled on real
  personal-agent usage: identity ("my register number is …"), preferences
  ("answers in Telugu"), relationships ("Ravi works at Infosys"), safety
  facts ("allergic to peanuts"), dates, and possessions. The *question* never
  repeats the *fact's* wording — recall has to bridge the paraphrase.
- Every fact is seeded through the **real write pipeline** (salience gate →
  extraction → ADD/UPDATE/DELETE resolution → store) into a fresh in-memory
  database — no fixtures injected behind the pipeline's back.
- Each question then runs the **real recall stack** (BM25 + entity graph +
  optional vector fusion), and a case is a **hit** when the expected answer
  substring appears in the top-*k* recalled texts (default *k* = 5).
- The score is **recall@k = hits / total**.

## Two modes

| Mode | Command | What the score isolates |
|---|---|---|
| **Offline (mock)** | `python scripts/memory_eval.py --mock` | Retrieval quality only. The model is a stub whose extraction returns nothing, so the explicit-remember fallback stores the raw statement — no API key, no network, deterministic. |
| **End-to-end** | `python scripts/memory_eval.py` | The whole pipeline including *your configured model's* extraction and conflict-resolution quality. Uses the provider chain you selected in Settings. |

The offline mode is the regression needle (it's also asserted in the test
suite, `test_memory_eval.py`); the end-to-end mode tells you what *your* brain
model actually delivers.

## Current results

Offline retrieval suite, `k = 5`, run 2026-07-19 on Windows 11, Python venv,
no embeddings endpoint configured (BM25 + graph only):

```
Memory eval — recall@5: 11/12 = 92%
```

The one miss: *"do I have any food allergies?"* against the stored *"I am
allergic to peanuts, never suggest recipes with them"* — recall returns
nothing at all, because no query token appears in the stored text
("allergies" ≠ "allergic" under FTS5's default tokenizer, which doesn't
stem). This is exactly the class of miss the **optional vector-embeddings
channel** exists to close (`memory.embeddings` in
[config.yaml](../namma_agent/config.yaml) — any OpenAI-compatible
`/embeddings` endpoint, including a free local LM Studio or Ollama one).

## Trend, not one-off

The weekly [self-review](../namma_agent/core/self_review.py) re-runs the
offline eval and snapshots the score alongside fact/entity/relation counts,
skill count, tool failure rate, and token spend into
`data/self_review/YYYY-MM-DD.json`. Settings → System → **Learning** renders
the trend — so a memory regression shows up as a falling number, not a
support ticket.

## Reproduce it

```bash
git clone <this repo> && cd <repo>
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r namma_agent/requirements.txt

python scripts/memory_eval.py --mock                # offline, no API key
python scripts/memory_eval.py --mock --min-score 0.8  # CI-style: exit 1 below the bar
python scripts/memory_eval.py                       # end-to-end with your provider
```

The per-case report prints every question, hit/miss, and the top recalled
texts for misses.

## Honest limitations

- **The dataset is small (12 cases) and self-authored.** It's a regression
  needle and a transparency artifact, not a leaderboard entry. It is not
  LongMemEval; scores are not comparable across projects with different
  datasets.
- **Substring scoring is generous** — it checks the answer *surfaced*, not
  that the model would have *used* it correctly in a reply.
- **The offline mode bypasses extraction quality** by design; a weak brain
  model can still score worse end-to-end than the offline number.
- **Single-session seeding.** The eval doesn't yet measure long-horizon
  behavior (consolidation, decay, contradiction over weeks) — the weekly
  snapshots are the current proxy for that.

Contributions of harder cases are welcome — add to `DATASET` in
[`evaluate.py`](../namma_agent/core/engram/evaluate.py) and the same command
scores them.
