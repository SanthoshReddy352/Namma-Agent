---
name: deep-research
description: >
  Research a topic in depth with parallel sub-agents and deliver a structured,
  sourced report. Use when the user asks to "research", "deep research",
  "investigate", "look into", "compare options", or wants a thorough,
  citation-backed overview rather than a quick fact.
platforms: [linux, macos, windows]
version: 2.1.0
category: research
metadata:
  hermes:
    tags: [research, web, synthesis, delegation]
---

# Deep Research

Thorough research means several angles, real sources and a written synthesis —
not four searches and a paragraph.

## When to Use

- The user asks to research / deep-research / investigate a topic, or to spawn
  sub-agents for it.
- The question has several independent angles (definitions, architecture,
  trade-offs, current state, risks, comparisons).

For a single quick fact, one `web_search` is enough — don't use this.

## Procedure

1. **Plan the angles.** Split the topic into 3–5 independent sub-questions that
   together cover it (e.g. what it is · how it works · who uses it and how ·
   trade-offs and alternatives · open problems / latest developments).
2. **Fan out.** Call `delegate_task` ONCE with `tasks` — one task per
   sub-question — and `toolsets: ["web"]`. Give each task a precise goal and the
   `context` it needs (the user's framing, the date, what to focus on), and ask
   for: key findings, concrete facts/numbers, and the URLs it actually read.
   Give each task `budget: {"max_steps": 8, "max_tokens": 40000}` so one angle
   can't eat the whole research budget; a `partial` report is still useful.
3. **Check the gaps.** Read the reports. If an angle came back thin or two
   reports disagree, run a targeted `web_search` + `web_extract` yourself (or one
   more delegated task) to settle it.
4. **Synthesize** a report:
   - `## Summary` — the bottom line in 3–5 sentences.
   - One `## ` section per angle, with the specifics (names, numbers, dates).
   - A **comparison table** wherever options, approaches or products are compared.
   - A ```mermaid diagram when an architecture or process is central.
   - `## Open questions` (what's uncertain or contested).
   - `## Sources` — the URLs the sub-agents actually read.
5. If a source fails to load, use another from the search results — never stop
   at the first 403.

## Verification

- `delegate_task` was actually called with several tasks (not simulated).
- Every non-obvious claim traces to a source someone opened.
- The report has sections, at least one table or diagram where it helps, and a
  Sources list.
- Disagreements between sources are stated, not hidden.
