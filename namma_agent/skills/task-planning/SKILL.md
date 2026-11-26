---
name: task-planning
description: >
  Plan and run multi-step work: break a goal into steps, track them in the live
  todo panel, run independent parts in parallel with sub-agents, and verify the
  result. Use when a request needs three or more steps or tools — "set up",
  "organize", "build", "migrate", "prepare", a project-style ask where you will
  create or change things. Not for a single lookup, a one-line answer, or helping
  the user choose between options (offer the choices instead).
platforms: [linux, macos, windows]
version: 1.0.0
category: productivity
metadata:
  hermes:
    tags: [planning, todos, delegation, verification]
---

# Task Planning

The user sees the plan in the todo panel, so a good plan is also good
communication: it shows what will happen and how far along you are.

## Procedure

1. **Restate the goal** in one line and note anything you must assume.
2. **Plan with `update_todos`** — 3–7 concrete steps, the first `in_progress`.
   A step is something you can verify ("create notes.md with the outline"),
   not a vague intention ("work on notes").
3. **Parallelize independent research** with one `delegate_task` call and a
   `tasks` list; keep steps that change files or depend on each other in order.
4. **Work the plan.** After each step, update the todos (`done`, next one
   `in_progress`). If a step reveals sub-steps, add them as `subtasks`.
5. **Verify** before the final answer: re-read written files, list the folder,
   run the check that would fail if the work were wrong.
6. **Report** what was done, what was verified, and anything left open.

## Gotchas

- If a step fails, adapt the plan (another approach, another source) instead
  of stopping — and say what changed.
- Destructive steps (deleting, overwriting, sending) need the user's approval;
  ask before them, not after.
