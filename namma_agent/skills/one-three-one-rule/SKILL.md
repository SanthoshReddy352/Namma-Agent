---
name: one-three-one-rule
description: >
  Structured decision-making framework for technical proposals and trade-off
  analysis. When the user faces a choice between multiple approaches (architecture,
  tool selection, refactoring, migration paths), produce a 1-3-1: one problem
  statement, three options with pros/cons, and one concrete recommendation. Use
  when the user asks for a "1-3-1", says "give me options", or needs help choosing.
platforms: [linux, macos, windows]
version: 1.1.0
category: communication
metadata:
  hermes:
    tags: [communication, decision-making, trade-offs]
---

# 1-3-1 Communication Rule

Ported from NousResearch/hermes-agent. A structured format for decisions with
multiple viable approaches: concise framing, three options with trade-offs, and
an actionable recommendation.

## When to Use

- The user explicitly asks for a "1-3-1".
- The user says "give me options" / "what are my choices" for a technical decision.
- A task has multiple viable approaches with meaningful trade-offs.

Do NOT use for simple questions with one obvious answer, debugging, or when the
user has already decided.

## Procedure

1. **Problem** (one sentence) — the core decision; the *what*, not the *how*.
2. **Options** (exactly three: A, B, C) — genuinely distinct strategies. Present
   them as one markdown table (columns: option · what it is · pros · cons · effort)
   so they can be compared at a glance.
3. **Recommendation** (one option) — your direct judgment and why.
4. **Definition of Done** — concrete, verifiable success criteria for the pick.
5. **Implementation Plan** — concrete steps/commands for the recommended option.

If the user later picks a different option, update Recommendation, DoD, and Plan.

## Verification

- Exactly one Problem sentence, exactly three Options with pros/cons each.
- A single Recommendation that commits to one option with reasoning.
- DoD and Implementation Plan align with the recommended option.
