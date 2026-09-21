---
name: syncing-agent-mcp
description: 在 Cursor、Claude Code、Codex、Zcode 之间对齐 MCP、项目 skills、AGENTS.md；当 `.agents/mcp.json`、`.mcp.json`、`.cursor/mcp.json`、`.codex/config.toml`、`.zcode/config.json` 漂移，或 `${VAR}` / `${env:VAR}`、Codex 鉴权（http_headers 未展开的 `${VAR}` 导致 not logged in）出问题时；或需要从项目根重新生成各端配置时使用。
---

# Syncing Agent MCP

在同一份项目里对齐 Cursor、Claude Code、Codex、Zcode 的 MCP、Skills 与开发指引。对**项目根目录**运行本 skill 自带的脚本。不要把脚本拷进业务仓库，不要手改生成的 JSON / TOML。

## 布局

| 角色 | 路径 | 说明 |
|------|------|------|
| MCP 源（合并结果） | `.agents/mcp.json` | 合并后写回；有意覆盖时改这里 |
| Claude | `.mcp.json` | 与源一致 |
| Cursor | `.cursor/mcp.json` | `${VAR}` → `${env:VAR}` |
| Codex | `.codex/config.toml` | 认证走 `bearerTokenEnvVar` / `env_http_headers` |
| Zcode | `.zcode/config.json` | 只更新 `mcp.servers`，其它键保留 |
| Skills 源 | `.agents/skills/` | 各端 `*/skills/` 通过 symlink 指向这里 |
| 开发指引 | `AGENTS.md` | 权威正文 |
| Claude | `CLAUDE.md` | 固定为 `@AGENTS.md` |

Cursor 与 Codex 直接读项目根下的 `AGENTS.md`。

## 安装（每台机器一次）

Claude Code：

```bash
npx skills add 8liang/syncing-agent-mcp -g -a claude-code -y
```

同时装给 Cursor：

```bash
npx skills add 8liang/syncing-agent-mcp -g -a claude-code -a cursor -y
```

安装后脚本在 skill 包内（例如 `~/.cursor/skills/syncing-agent-mcp/scripts/sync_agent_config.py`）。始终调用该路径，不要在项目里新建 `scripts/sync_agent_config.py` 副本。

## 使用

先解析**绝对路径**的项目根，再执行：

```bash
python3 scripts/sync_agent_config.py /absolute/path/to/project
```

`ROOT` 与 `--root ROOT` 等价，项目根只传一次，不要同时传。省略参数时默认当前工作目录。

脚本**依次**执行：

1. **MCP**：读取 `.codex/config.toml`、`.zcode/config.json`、`.mcp.json`、`.cursor/mcp.json`、`.agents/mcp.json`，按 server 名合并（后者覆盖前者，`.agents/mcp.json` 优先级最高），写回 `.agents/mcp.json` 并生成各端文件。
2. **Skills**：把各端 `*/skills/<name>/`（须含 `SKILL.md`）收拢到 `.agents/skills/`，再在各端建立指向 `.agents/skills/<name>` 的 symlink。
3. **指引**：把 `AGENTS.md` 与 `CLAUDE.md` 中非 `@AGENTS.md` 的正文合并进 `AGENTS.md`，并将 `CLAUDE.md` 设为 `@AGENTS.md`。

可选参数：

| 参数 | 作用 |
|------|------|
| `--skip-skills` | 只跑 MCP |
| `--skip-docs` | 跳过 AGENTS/CLAUDE |
| `--self-test` | 运行内置测试（无需项目路径） |
| `--source`、`--cursor-out`、`--codex-out`、`--mcp-out`、`--zcode-out` | 覆盖输出路径（高级） |

任意位置都没有 MCP 配置时会报错退出，不会写入空配置。MCP 渲染校验失败时不会部分写盘（全部渲染完成后再写入）。

## MCP 合并顺序

读取顺序（同名 server **后者覆盖前者**）：

1. `.codex/config.toml`
2. `.zcode/config.json`
3. `.mcp.json`
4. `.cursor/mcp.json`（规范 JSON 中 `${env:VAR}` → `${VAR}`）
5. `.agents/mcp.json`

## Codex 认证

Codex **不会**展开 `http_headers` 里的 `${VAR}`。在 `.agents/mcp.json` 中应使用：

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

转换规则：

| 源（headers / 字段） | Codex 输出 |
|----------------------|------------|
| `"Authorization": "Bearer ${VAR}"` | `bearer_token_env_var` |
| `bearerTokenEnvVar` | `bearer_token_env_var` |
| `"X-Key": "${VAR}"`（整值占位符） | `env_http_headers` |
| 静态 header 值 | `http_headers` |

`bearerTokenEnvVar` 仅用于 HTTP server。header 字符串**中间**夹 `${VAR}` 时脚本会直接报错，避免生成无法鉴权的配置。

## 常见错误

- 把转换脚本拷进业务仓库
- 手改生成的 `.mcp.json`、`.cursor/mcp.json`、`.codex/config.toml`、`.zcode/config.json` 当作源
- 在 Cursor 生成文件里手写 `${API_KEY}`（源文件 `.agents/mcp.json` 用 `${API_KEY}`，生成结果为 `${env:API_KEY}`）
- 指望 Codex 在 `http_headers` 里展开 `${API_KEY}`
- 只在 `.cursor/skills` 下维护 skill 却不跑 sync（规范目录是 `.agents/skills`）
- 把长规则写在 `CLAUDE.md` 而不是 `AGENTS.md`
- 在对话里重写转换逻辑而不运行脚本
- 未传项目根却在错误的工作目录下执行
