# syncing-agent-mcp

在同一份项目里对齐 Cursor、Claude Code、Codex、Zcode 的 MCP、Skills 与开发指引。

## 布局

| 角色 | 路径 | 说明 |
|------|------|------|
| MCP 源（合并结果） | `.agents/mcp.json` | 脚本合并各端配置后写回 |
| Claude | `.mcp.json` | 与源一致 |
| Cursor | `.cursor/mcp.json` | `${VAR}` → `${env:VAR}` |
| Codex | `.codex/config.toml` | 认证走 `bearerTokenEnvVar` / `env_http_headers` |
| Zcode | `.zcode/config.json` | 只更新 `mcp.servers`，其它键保留 |
| Skills 源 | `.agents/skills/` | 各端 skill 目录 symlink 到这里 |
| 开发指引 | `AGENTS.md` | 权威正文 |
| Claude | `CLAUDE.md` | 固定为 `@AGENTS.md` |

Cursor 与 Codex 直接读项目根下的 `AGENTS.md`。

## 安装

```bash
npx skills add 8liang/syncing-agent-mcp -g -a claude-code -y
```

同时装给 Cursor：

```bash
npx skills add 8liang/syncing-agent-mcp -g -a claude-code -a cursor -y
```

## 使用

对项目根目录运行 skill 自带脚本（不要拷进业务仓库）：

```bash
python3 scripts/sync_agent_config.py /path/to/project
```

`ROOT` 与 `--root ROOT` 等价，项目根只传一次。省略参数时默认当前工作目录。脚本在 skill 安装目录下（例如 `~/.cursor/skills/syncing-agent-mcp/scripts/`），不要拷进业务仓库。

脚本会依次：

1. **MCP**：读取 `.codex/config.toml`、`.zcode/config.json`、`.mcp.json`、`.cursor/mcp.json`、`.agents/mcp.json`，按 server 名合并（后者覆盖前者，`.agents/mcp.json` 优先级最高），写回 `.agents/mcp.json` 并生成各端文件。
2. **Skills**：把各端 `*/skills/<name>/` 收拢到 `.agents/skills/`，再在各端建立指向该目录的 symlink。
3. **指引**：把 `AGENTS.md` 与 `CLAUDE.md` 中非 `@AGENTS.md` 的正文合并进 `AGENTS.md`，并将 `CLAUDE.md` 设为 `@AGENTS.md`。

可选：

| 参数 | 作用 |
|------|------|
| `--skip-skills` | 只跑 MCP |
| `--skip-docs` | 跳过 AGENTS/CLAUDE |
| `--self-test` | 运行内置测试（无需项目路径） |

MCP 校验失败时不会部分写盘；任意位置都没有 MCP 配置时会直接报错退出。

## Codex 认证

Codex **不会**展开 `http_headers` 里的 `${VAR}`。在源 JSON 里用 `bearerTokenEnvVar`（仅 HTTP）或整值占位符 header：

```json
{
  "mcpServers": {
    "fns": {
      "type": "http",
      "url": "https://example.com/api/mcp",
      "bearerTokenEnvVar": "FNS_API_KEY",
      "headers": { "Content-Type": "application/json" }
    }
  }
}
```

`${VAR}` 出现在 header 字符串中间时脚本会报错，避免生成无法鉴权的配置。
