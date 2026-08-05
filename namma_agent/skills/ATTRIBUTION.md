# Attribution

Namma Agent's skill catalog includes procedural playbooks (`SKILL.md` files)
ported from **[NousResearch/hermes-agent](https://github.com/nousresearch/hermes-agent)**,
which is MIT-licensed. A copy of that license is kept here as
[`HERMES-LICENSE`](HERMES-LICENSE).

Ported skills retain their original frontmatter (`author`, `license`, `version`,
`metadata.hermes.*`); a `category:` field was added from the Hermes folder layout
so the web UI can group them. Each skill's own `license` field is authoritative.

Skills authored for Namma Agent (e.g. `creating-simulations`, `deep-research`,
`teaching-with-examples`) are original to this project.

The Hermes **God Mode** skill is intentionally **not** ported — see the "Declined"
section of `Namma_Agent_Port.md`.

## Terminal UI

The terminal UI in [`namma_agent/tui/`](../tui/) follows the **layout and
interaction model** of the same MIT-licensed Hermes Agent CLI: a non-fullscreen
`prompt_toolkit` application with a status bar and ruled input at the bottom, the
transcript in normal scrollback, a two-column startup banner, emoji-prefixed tool
lines, and a skinnable palette. The same `HERMES-LICENSE` covers that lineage.

The implementation is Namma's own — no Hermes source is vendored. The artwork
(the diya emblem), the palette wiring, the runtime-rendered wordmark, and every
integration point (the event bus, `service.run_turn`, `InboundBridge`, the skill
and MCP registries) are specific to this project.
