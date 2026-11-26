---
name: skill-creator
description: >
  Write a new skill (a reusable procedure) or improve an existing one with
  create_skill / update_skill. Use when the user says "make a skill for…",
  "remember how to do this", "save this workflow", or when a multi-step task
  went well and is likely to recur.
platforms: [linux, macos, windows]
version: 1.0.0
category: meta
metadata:
  hermes:
    tags: [skills, authoring, procedures]
---

# Skill Creator

A skill only helps if the model picks it at the right time and can follow it.

## Write it

1. **Name**: lowercase-with-hyphens, the task it does ("weekly-report").
2. **Description** carries ALL the triggers: what it does, the phrases and
   situations that should load it, and one "Not for …" near-miss. Be generous
   with triggers — skills are more often missed than over-used.
3. **Body**, under ~80 lines:
   - why the procedure matters (one or two lines);
   - numbered steps naming the real tools to call;
   - a table when the approach depends on the case;
   - gotchas learned the hard way;
   - a verification checklist.
4. Explain reasons instead of shouting rules; keep it general, not tied to
   one example.
5. Save with `create_skill` (or `update_skill` to refine).

## Check it

- Every tool it names exists here (check with `tool_search` if unsure).
- Three realistic requests that should trigger it would, and two near-misses
  wouldn't.
