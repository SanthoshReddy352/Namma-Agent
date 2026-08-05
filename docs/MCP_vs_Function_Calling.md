# MCP vs OpenAI Function Calling — 1-Page Brief

*Last updated: 22 July 2026*

---

## What They Are

**OpenAI Function Calling** (also called "tool use" by Anthropic, "tool use" by Google) is a **model-level primitive**. You define tools as JSON Schemas in your API request, the LLM decides which tool to call and with what arguments, and your application executes it. It's tightly coupled to the provider's API — each vendor (OpenAI, Anthropic, Google) has its own flavour.

**Model Context Protocol (MCP)** is an **open, transport-agnostic protocol** (originally from Anthropic, Nov 2024, now community-governed) that sits *between* the model and the tools. It introduces a client-server architecture where tool servers advertise capabilities dynamically, and any MCP-compatible host can discover and invoke them. Think of it as a "USB-C for AI tools" — a universal adapter.

---

## Key Differences

| Dimension | Function Calling | MCP |
|---|---|---|
| **Ownership** | Proprietary (each vendor defines their own) | Open standard (community-governed) |
| **Architecture** | Model outputs structured JSON; app executes inline | Client ↔ tool-server over JSON-RPC (stdio / SSE / HTTP) |
| **Tool discovery** | Static — you declare tools per request | Dynamic — servers advertise tools at runtime |
| **Model portability** | Low — OpenAI schemas ≠ Anthropic schemas ≠ Google schemas | High — write tool once, use with any MCP-compatible model |
| **Latency** | Minimal (native to API call) | Small extra round-trip to tool server (~sub-10 ms local) |
| **Setup complexity** | Low — single API call with JSON Schema | Medium — requires running MCP servers + client wiring |
| **Ecosystem** | Mature, tightly integrated with LangChain, Assistants API | Growing fast — 1,000+ community servers (2025-26) |
| **Best for** | Single-model apps, fast prototypes, latency-critical paths | Multi-model pipelines, reusable tool infra, vendor-neutral setups |

---

## When to Use Which

- **Function Calling** → You're building on one provider, want the fastest path to production, and need minimal overhead. The tool definitions live in your app code.
- **MCP** → You need vendor independence, plan to swap models, want to build reusable tool servers shared across teams/products, or are running local/open-source LLMs.
- **Both together** → Common hybrid pattern: your tools are MCP servers for portability, but a latency-critical surface mounts them as direct function calls.

---

## How They Complement Each Other

They aren't mutually exclusive. MCP defines *how tools are discovered and exposed*; function calling defines *how the model expresses intent to use them*. In a typical MCP setup, the MCP client still uses the model's native function/tool-calling mechanism to route requests — MCP adds the standardisation and discovery layer on top.

---

## Namma Agent

Namma Agent uses **function calling (tool use)** as its core mechanism. It defines tools with JSON Schemas and sends them to whichever provider is active (Anthropic Claude, OpenAI, Google, or an OpenAI-compatible backend). The model returns structured tool calls, and Namma executes them. It also has an `mcp_list_servers` capability, suggesting MCP awareness for external tool servers, but the primary tool-calling loop is native function/tool use — provider-agnostic at the agent layer, but protocol-specific at the model API layer.
