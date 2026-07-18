# External memory providers (plugins)

Engram (see [MEMORY_SYSTEM_DESIGN.md](MEMORY_SYSTEM_DESIGN.md)) is **THE**
memory — native, in-process, always on. External memory engines are optional
**plugins** on top of it: additive depth, never load-bearing. If a plugin is
slow, offline, or removed, nothing about identity, recall, or learning breaks.

## How a plugin attaches

Any memory engine that speaks MCP (Cognee, Mem0, Zep, …) is attached as a plain
MCP server — **Settings → MCP → Servers** (config: `mcp.servers`). Its tools
register under the server's name (e.g. `mcp_cognee_remember`,
`mcp_cognee_recall`) and the model can call them like any other tool. That's
the whole integration: no special-cased memory backend, no proxying in the
Memory tab, no startup dependency.

```yaml
# config.local.yaml — example: the old self-hosted Cognee container as a plugin
mcp:
  servers:
    - name: cognee
      command: [docker, run, --rm, -i, --name, namma_cognee,
                --env-file, .env.cognee, --network, agi_default,
                -v, cognee-data:/cognee-data, cognee/cognee-mcp:main]
```

Container setup, env files, and the hard-won troubleshooting for Cognee
specifically live in [COGNEE.md](COGNEE.md) (historical, still accurate for
running the container).

## Importing an old Cognee graph

One-shot, safe to re-run (duplicates are skipped):

```
python scripts/migrate_cognee_to_engram.py --json graph_dump.json   # from a {nodes,edges} dump
python scripts/migrate_cognee_to_engram.py --cloud                  # from Cognee Cloud REST
python scripts/migrate_cognee_to_engram.py --local                  # from the docker container
```

Imported facts land in `memory_items` with `source='import:cognee'`, entities
and edges go into the native knowledge graph, and everything passes the same
injection screening as any other memory write. Add `--dry-run` to preview.

## Boundaries

- Plugin tools are **model-invoked** — Engram's prefetch, core-memory block,
  and consolidator never wait on a plugin.
- A plugin's output enters the conversation as tool-result *data*, subject to
  the same provenance framing as retrieved memory.
- Removing a plugin is just removing the server entry; Engram is unaffected.
