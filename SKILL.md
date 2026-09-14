---
name: syncing-agent-mcp
description: Use when adding, editing, or aligning MCP servers across Cursor, Codex, or Claude; when `.agents/mcp.json`, `.mcp.json`, `.cursor/mcp.json`, or `.codex/config.toml` drift; when MCP env placeholders like `${VAR}` vs `${env:VAR}` fail; or when regenerating those files from a project root.
---

# Syncing Agent MCP

Keep one MCP source of truth and generate editor-specific configs. Run this skill's bundled script against the project root. Do not copy the script into the repo. Never rewrite generated JSON or TOML by hand.

## Source and outputs

| Role | Path | Edit? |
|------|------|-------|
| Source | `.agents/mcp.json` | Yes |
| Project / Claude | `.mcp.json` | No (copy of source) |
| Cursor | `.cursor/mcp.json` | No (generated) |
| Codex | `.codex/config.toml` | No (generated) |

`.mcp.json` is a pretty-printed copy of the source (`${ENV_VAR}` kept as-is). `.cursor/mcp.json` rewrites `${ENV_VAR}` → `${env:ENV_VAR}` (already-prefixed `${env:…}` is left alone). Codex strings are copied as-is, including `headers` → `http_headers`.

## Workflow

1. Resolve the project root.
2. Run this skill's `scripts/sync_agent_config.py`, passing that root:

```bash
python3 scripts/sync_agent_config.py /absolute/path/to/project
```

`ROOT` and `--root ROOT` are equivalent. Paths are relative to that root. If the project has no `.agents/mcp.json`, the script bootstraps from `.cursor/mcp.json` or `.mcp.json`, then regenerates all outputs.

3. Confirm `.mcp.json`, `.cursor/mcp.json`, and `.codex/config.toml` exist. Do not hand-edit them. Do not install a copy under the project's `scripts/`.

## Common mistakes

- Copying the converter into the repo
- Editing `.mcp.json`, `.cursor/mcp.json`, or `.codex/config.toml` as the source of truth
- Writing `${API_KEY}` into Cursor headers (Cursor needs `${env:API_KEY}`)
- Re-implementing the converter in the chat instead of running the script
- Running from the wrong directory without a root argument
