---
name: creating-visuals
description: >
  Explain with visuals: Mermaid diagrams, charts, comparison tables, interactive
  HTML visuals and real photos, woven into the explanation. Use when the user
  asks to explain or teach something "with diagrams", "visually", "with
  visualizations", or when a structure, flow or comparison is easier to see
  than to read.
platforms: [linux, macos, windows]
version: 2.0.0
category: teaching
metadata:
  hermes:
    tags: [visual, diagram, chart, table, explanation, learning-room]
---

# Creating Visuals

Pick the visual that fits each idea, and place it where that idea is explained.

## Pick the form

| The idea is… | Use |
|---|---|
| structure, components, hierarchy | a ```mermaid `flowchart` / `graph` / `mindmap` block |
| a process over time, who talks to whom | a ```mermaid `sequenceDiagram` or `flowchart LR` |
| states and transitions | a ```mermaid `stateDiagram-v2` |
| numbers (sizes, trends, shares) | a ```chart block (bar / line / pie JSON) |
| options side by side | a markdown table |
| something to play with (a simulation, a slider) | `render_visual` with self-contained HTML |
| what a real thing looks like | `fetch_image` |

## Procedure

1. Outline the explanation in 3–5 short `## ` sections.
2. In each section, add the ONE visual that makes that section's point, right
   after the sentence that introduces it, then say what to look at in it.
3. Keep diagrams minimal: the fewest nodes that carry the idea, short labels,
   quoted labels with punctuation (`A["Plan (step 1)"]`).
4. Close with a one-paragraph recap.

## When something doesn't render

- A diagram tool or image fails → write the diagram as a ```mermaid block
  instead; the chat renders it itself.
- A chart idea doesn't fit Mermaid → use a ```chart block or a table.
- Never stop at "I can't draw that" — choose another form from the table above.

## Verification

- More than one kind of visual where the topic has more than one kind of idea.
- Every visual sits inside the section it explains (none dumped at the top).
- Comparisons are tables; numbers are charts; flows are diagrams.
