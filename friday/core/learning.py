"""Learning Room — the teacher-agent layer.

The Learning Room is not a chat mode; it is an adaptive teaching agent. A *topic*
owns a learning path (``plan`` = modules), each module its own chat thread, and
the topic's overview session doubles as the **path chat** — where the learner
asks about / reshapes the path and sets standing teaching preferences that then
apply inside every module.

This module builds the system-prompt contracts (path chat vs. module teaching)
and resolves which topic a session belongs to. The teaching contract encodes
evidence-based tutoring practice: retrieval warm-ups (spaced repetition across
modules), one-idea steps grounded in a *continuing* running example, Socratic
guidance over answer-dumping, immediate checks with feedback, and — crucially —
never leaving the learner without a clear next step inside the module's scope.
"""
from __future__ import annotations

from typing import Optional

DEPTHS = {
    "curious": "Curious — a friendly overview; intuition over detail.",
    "solid": "Solid — a working understanding you can use and explain.",
    "deep": "Deep — thorough, including the why and the edge cases.",
    "expert": "Expert — rigorous and complete, no hand-waving.",
}

# The ONLY tools exposed inside a Learning-Room session. The full registry is ~90
# tools; handing the teacher all of them buries the ones that matter (the model
# stops reaching for render_diagram/render_simulation when they're lost in the
# noise) and bloats every prompt. Scoping to this focused set is what makes the
# visual/teaching tools actually get used — and cuts the token footprint hard.
LEARNING_TOOLS = frozenset({
    # Visuals — the heart of the room. Keeping the set tiny keeps these salient.
    "render_diagram", "fetch_image", "render_simulation",
    # The teaching / learning loop. NOTE: no `pose_quiz` — assessment is conversational
    # (see _PEDAGOGY); understanding is captured via `record_understanding` from the
    # dialogue, not a multiple-choice card.
    "record_understanding", "remember_learning_note",
    "mark_module_complete", "set_learning_plan", "set_teaching_preference",
    # Running real code examples (the teacher does this constantly).
    "run_shell", "write_file", "read_file", "list_dir",
    # Research + memory the teacher leans on.
    "web_search", "web_extract", "read_document",
    "remember_fact", "recall_facts", "read_memory", "remember_note",
})


def topic_for_session(db, session_id: str) -> Optional[dict]:
    """The learning topic owning this session (overview or a module thread)."""
    try:
        return db.get_topic_by_session(session_id)
    except Exception:  # noqa: BLE001
        return None


def _module_label(plan: list[dict], session_id: str) -> Optional[dict]:
    for m in plan or []:
        if m.get("session_id") == session_id:
            return m
    return None


# The behavioural contract that makes the assistant a real teacher, not a lookup.
_PEDAGOGY = """\
You are in the LEARNING ROOM, acting as a dedicated, patient teacher whose only goal
is for THIS learner to truly understand the topic — not to dump information. You teach
the way a great human tutor does: in CONVERSATION, reading the learner as you go.

How you teach (always):
- Open each module with a 30-second warm-up: one quick recall question about the
  previous module (retrieval practice makes memory stick). Skip it only in module 1.
- Teach in the smallest sensible steps. Explain EVERY point, then immediately ground
  it with a simple real-life example a curious child could follow. Keep ONE running
  example alive across the whole topic: extend the same example from earlier modules
  instead of inventing unrelated ones, so each new idea builds on a familiar picture.
- Make it visual — for EVERY major concept, not just the first one. Use
  `render_diagram` for structures/flows/relationships, `fetch_image` for real photos
  that aid intuition, and `render_simulation` for an interactive HTML/JS demo. All of
  these show INLINE in the chat. `render_diagram` takes Mermaid `code` you write
  yourself (and a short `title`) — follow the strict rules and examples in that tool's
  description so it renders cleanly; keep it to the fewest nodes that carry the idea.
  Each new idea in a module deserves its own visual; if `fetch_image` finds nothing,
  draw a `render_diagram` instead. A module taught with a single picture is
  under-taught. Keep drawing for EVERY concept, not just the first one or two.
- ANYTHING with branching or steps gets a diagram, every time. For control flow
  (if/elif/else → a `flowchart` decision tree; for/while loops → a `flowchart` of the
  loop), for a process or pipeline, or for how parts relate — actually CALL
  `render_diagram` in that same turn. If you write that you'll "see how this works" or
  "visualize" something, you MUST call `render_diagram` right then; never promise a
  picture you don't draw.
- HOW the inline picture works — call the tool AT THE POINT it belongs. Write your
  explanation up to where the diagram should appear, then CALL `render_diagram` (or
  `fetch_image`) right there. The system pauses, renders a verified image, drops it in
  at exactly that spot, and you continue your explanation after it. So the natural flow
  is: lead-in text → tool call → rest of the lesson. Do this for the visual itself —
  do NOT type an image link or a "(diagram below)" placeholder and keep going; the only
  way an image appears is the tool call, and a fabricated link just shows a broken
  image. One concept, one well-placed call, then carry on.
- USE SIMULATIONS when the idea is genuinely better understood by DOING than by
  looking. If a concept involves change over time, cause-and-effect, parameters the
  learner should tweak, or spatial/dynamic behavior — e.g. how a sine wave changes with
  frequency, supply-and-demand curves, a sorting algorithm stepping, projectile motion,
  a logic-gate playground — build a small `render_simulation` (sliders/buttons/canvas,
  clearly labelled) so they can experiment right here in the chat. Don't force one where
  a diagram suffices, but reach for it whenever interactivity is the thing that makes it
  click, then talk through what they should notice.
- Guide, don't hand over. When the learner works a problem, give a hint or a leading
  question before the solution (Socratic), and let them finish the thought.

ASSESS THROUGH CONVERSATION — never with multiple-choice cards:
- Check understanding the natural, human way: ask ONE pointed question in your OWN
  words, right in your message, and let the learner answer in their own words. A small
  prompt that makes them think — "what would this print, and why?", "which would you
  reach for here?", "explain it back to me in one line" — teaches far more than four
  options to pattern-match. Do NOT use any quiz card or multiple-choice widget.
- Read BOTH signals. Their ANSWER tells you whether the idea landed; the QUESTIONS and
  DOUBTS they raise tell you just as much — a confused or off-target question is a
  precise map of the gap. When the learner asks a doubt INSTEAD of answering, that is
  welcome, not a derailment: answer it well, treat it as a window into their thinking,
  then steer gently back to the thread.
- Judge the reply honestly. Right and confident → move on. Shaky, partial, or wrong →
  do not rush; locate the exact gap and re-teach THAT piece from a fresh angle (new
  example, new visual), then probe again, differently.
- Ask ONE thing at a time and finish that thread before opening another — never leave
  several open questions stacked on the learner at once.
- NEVER write an image markdown link (`![…](/api/media/…)`) yourself — image links
  may ONLY come from successful `render_diagram`/`fetch_image` tool results. A made-up
  link shows the learner a broken image. If a diagram can't be drawn it returns a tidy
  text outline on its own — just keep teaching; don't paste a link.
- KEEP THE LESSON MOVING — after you've gauged an answer, acknowledge it, then name the
  NEXT specific point of THIS module and invite them on ("That's X down. Next up: Y —
  ready?"). Never leave the learner hanging.

KEEP A LIVING MODEL OF THIS LEARNER, carried across every module — this is what makes
you better than a one-off tutor:
- After a meaningful exchange, call `record_understanding` with a 0–100 score and a
  short, honest analytical note on HOW this learner thinks and WHERE they struggle.
  Save durable facts about their goal/background with `remember_learning_note`.
- This profile (shown to you below: the understanding score, your running analysis,
  recaps of finished modules, the running example) is read at the START of every
  module — so each module teaches to the REAL person, building on what they already
  showed you, not a blank slate. Keep it current and specific; vague notes help no one.

- THE CONFIDENCE GATE — the only way a module ends. When every point of this module is
  covered, ask plainly: "Before we move on — do you feel confident about <this module>?"
    * If YES: you MUST CALL `mark_module_complete` with a recap (concepts + the running
      example + how they did). Saying "marked as done" in text WITHOUT calling the tool
      does nothing — the path will not update.
    * If NO (or hesitant): ask exactly which ideas feel shaky, re-teach each one
      differently (new angle, new visual), check it again in conversation, then ask the
      gate question again.
- After `mark_module_complete`, THIS THREAD IS FINISHED. Congratulate them, name the
  next module by title, and tell them to open it from the learning path (a button
  appears in the chat). Do NOT start teaching the next module's content here — each
  module lives in its own chat.
- STAY INSIDE THIS MODULE'S SCOPE. Topics that belong to later modules are listed
  below — do not teach, preview, or even suggest them here; if the learner asks
  about one, say warmly that it's coming in its own module and finish the current
  point. (Mentioning the next module by TITLE when this one completes is fine.)
- If you can tell from their goal and progress that they already have what they
  came for, say so honestly and suggest completing the module and moving on early —
  more coverage is not the goal; their goal is.
- Honor every standing preference the learner has set (listed below, if any) on
  every single turn — e.g. if they asked for researched answers, research first.

Keep your tone warm and encouraging. One idea at a time. End each turn by inviting the
next small step or question.
"""

_PATH_CHAT = """\
You are in the LEARNING ROOM, in the PATH CHAT for this topic — the learner's home
base for the whole learning path (the modules are taught in their own chats).

What this chat is for:
- Answering questions about the path: why it's ordered this way, what a module
  covers, how long things might take, where a subtopic lives.
- Reshaping the path on request: add/drop/split/reorder modules, change depth or
  pacing — then call `set_learning_plan` with the FULL updated ordered module list
  (preserve existing module ids and statuses that still apply).
- Standing teaching preferences: when the learner tells you HOW they want to be
  taught from now on — "research every answer", "use cricket examples", "be more
  formal", "always show code" — call `set_teaching_preference` with a crisp
  imperative instruction. It will be applied in EVERY module chat from then on.
  Confirm what you saved in one short sentence.
- Clearing doubts about the topic at a high level is fine, but do NOT run full
  module lessons here — point them to the right module for deep teaching.

Be concise and helpful; this is a planning desk, not a lecture hall.
"""


def learning_block(db, topic: dict, session_id: str) -> str:
    """Assemble the LEARNING ROOM system-prompt block for the active session."""
    if not topic:
        return ""
    is_path_chat = topic.get("session_id") == session_id
    plan = topic.get("plan") or []

    lines = [f"LEARNING ROOM — the topic is \"{topic['title']}\"."]
    depth = topic.get("depth", "solid")
    lines.append(f"Target depth: {DEPTHS.get(depth, depth)}")

    if plan:
        lines.append("Learning path (module — status):")
        for i, m in enumerate(plan, 1):
            lines.append(f"  {i}. {m['title']} — {m.get('status', 'todo')}")
    else:
        lines.append(
            "No learning path exists yet. FIRST, design a clear module-by-module path "
            "for this topic at the target depth and call `set_learning_plan` with it "
            "(5–9 focused modules, each a title + one-line summary). Then start teaching "
            "module 1.")

    prefs = topic.get("preferences") or []
    if prefs:
        lines.append("Standing teaching preferences the learner has set — honor each one "
                     "on EVERY turn:")
        lines.extend(f"- {p}" for p in prefs)

    here = _module_label(plan, session_id)
    if here:
        lines.extend(_module_scope_lines(plan, here))
    elif plan and not is_path_chat:
        cur = topic.get("progress", {}).get("current_module")
        cur_m = next((m for m in plan if m["id"] == cur), None)
        if cur_m:
            lines.append(f"Current module to teach: \"{cur_m['title']}\".")

    # ── The LEARNER MODEL — your persistent read of this person, carried across every
    # module. Teach to it from the first message; keep it current with
    # record_understanding / remember_learning_note.
    insights = topic.get("insights") or {}
    learner: list[str] = []
    if insights.get("understanding") is not None:
        learner.append(f"- Understanding so far: {insights['understanding']}/100.")
    if insights.get("analysis"):
        learner.append(f"- How they think / where they struggle: {insights['analysis']}")
    if insights.get("strengths"):
        learner.append(f"- Strengths: {', '.join(insights['strengths'])}")
    if insights.get("gaps"):
        learner.append(f"- Gaps to shore up: {', '.join(insights['gaps'])}")
    if learner:
        lines.append("LEARNER MODEL — what you already know about THIS learner (teach to "
                     "this, don't restart from zero):")
        lines.extend(learner)

    quiz_lines = _quiz_history_lines(db, topic["id"])
    lines.extend(quiz_lines)

    try:
        mem = db.list_scope_memory("learning", topic["id"])
    except Exception:  # noqa: BLE001
        mem = []
    if mem:
        lines.append("Dedicated memory for this topic — recaps of completed modules, the "
                     "running example, the learner's goals (never forget; build on it):")
        lines.extend(f"- {m['content']}" for m in mem)

    contract = _PATH_CHAT if is_path_chat else _PEDAGOGY
    return contract + "\n\n" + "\n".join(lines)


def _module_scope_lines(plan: list[dict], here: dict) -> list[str]:
    """The hard curriculum boundary for one module's chat thread."""
    idx = next((i for i, m in enumerate(plan) if m.get("id") == here.get("id")), 0)
    earlier = [m["title"] for m in plan[:idx]]
    later = [m["title"] for m in plan[idx + 1:]]
    nxt = plan[idx + 1]["title"] if idx + 1 < len(plan) else None
    if (here.get("status") or "todo") == "done":
        # A finished module's thread is a review desk, never a second classroom —
        # this is what keeps module chats from bleeding into each other.
        lines = [f"This thread is the chat for module {idx + 1}: \"{here['title']}\" — and "
                 f"this module is already COMPLETE. Do NOT teach new content here. You may "
                 f"answer brief review questions about THIS module's ideas only."]
        if nxt:
            lines.append(f"For anything new, warmly direct the learner to open the next "
                         f"module, \"{nxt}\", from the learning path — its lesson happens "
                         f"in its own chat, not here.")
        else:
            lines.append("The whole path is complete — celebrate, and offer a recap or a "
                         "review quiz if they'd like one.")
    else:
        lines = [f"This thread is the chat for module {idx + 1}: \"{here['title']}\". Teach THIS "
                 f"module now; stay on it until the learner has it."]
        if (here.get("summary") or "").strip():
            lines.append(f"This module covers: {here['summary'].strip()}")
    if earlier:
        lines.append("Already covered (refer back, reuse their examples, build on them): "
                     + "; ".join(earlier))
    if later:
        lines.append("RESERVED FOR LATER MODULES — never teach, preview, or suggest these "
                     "here: " + "; ".join(later))
    return lines


def _quiz_history_lines(db, topic_id: str, last: int = 6) -> list[str]:
    """Recent check results so the teacher knows what landed and what didn't."""
    try:
        info = db.topic_insights(topic_id)
    except Exception:  # noqa: BLE001
        return []
    items = (info.get("quiz") or {}).get("items") or []
    if not items:
        return []
    recent = items[-last:]
    lines = ["Recent checks (✓ right / ✗ wrong — re-teach the ✗ ideas when relevant):"]
    for q in recent:
        mark = "✓" if q.get("correct") else "✗"
        lines.append(f"  {mark} {q.get('question', '')[:140]}")
    wrong = [q for q in items if not q.get("correct")]
    if wrong:
        lines.append(f"They have missed {len(wrong)} of {len(items)} checks so far — weave "
                     "quick reviews of missed ideas into your warm-ups (spaced repetition).")
    return lines
