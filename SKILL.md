---
name: syncing-agent-mcp
description: 当 Cursor、Claude Code、Codex、Zcode、Qoder CLI / IDE 的 MCP、项目 skills、AGENTS.md 需要对齐，或 `.agents/mcp.json`、`.mcp.json`、`.cursor/mcp.json`、`.codex/config.toml`、`.zcode/config.json`、`.qoder/settings.json` 漂移时使用；也适用于 `${VAR}` / `${env:VAR}`、Codex http_headers 未展开导致 not logged in，以及 Qoder IDE 手动导入 MCP 的场景。
---

# Syncing Agent MCP

在同一份项目里对齐 Cursor、Claude Code、Codex、Zcode、Qoder 的 MCP、Skills 与开发指引（Qoder CLI 自动同步，IDE 的 MCP 手动导入）。对**项目根目录**运行本 skill 自带的脚本。不要把脚本拷进业务仓库，不要手改生成的 JSON / TOML。

## 布局

| 角色 | 路径 | 说明 |
|------|------|------|
| MCP 源（合并结果） | `.agents/mcp.json` | 合并后写回；有意覆盖时改这里 |
| Claude / Qoder CLI | `.mcp.json` | 通用 MCP JSON；`bearerTokenEnvVar` 转为认证头，也供 IDE 手动导入 |
| Cursor | `.cursor/mcp.json` | `${VAR}` → `${env:VAR}` |
| Codex | `.codex/config.toml` | 认证走 `bearerTokenEnvVar` / `env_http_headers` |
| Zcode | `.zcode/config.json` | 只更新 `mcp.servers`，其它键保留 |
| Qoder CLI | `.qoder/settings.json` | 只更新 `mcpServers`，其它设置保留 |
| Skills 源 | `.agents/skills/` | 各端 `*/skills/`（含 `.qoder/skills/`）通过 symlink 指向这里 |
| 开发指引 | `AGENTS.md` | 权威正文 |
| Claude | `CLAUDE.md` | 固定为 `@AGENTS.md` |

Cursor、Codex 与 Qoder（CLI / IDE）直接读项目根下的 `AGENTS.md`，无需生成 `QODER.md`。

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

1. **MCP**：读取 `.codex/config.toml`、`.zcode/config.json`、`.qoder/settings.json`、`.mcp.json`、`.cursor/mcp.json`、`.agents/mcp.json`，按 server 名合并（后者覆盖前者，`.agents/mcp.json` 优先级最高），写回 `.agents/mcp.json` 并生成各端文件。
2. **Skills**：把各端 `*/skills/<name>/`（须含 `SKILL.md`）收拢到 `.agents/skills/`，再在各端建立指向 `.agents/skills/<name>` 的 symlink。
3. **指引**：把 `AGENTS.md` 与 `CLAUDE.md` 中非 `@AGENTS.md` 的正文合并进 `AGENTS.md`，并将 `CLAUDE.md` 设为 `@AGENTS.md`。

可选参数：

| 参数 | 作用 |
|------|------|
| `--skip-skills` | 跳过 skills 同步；只跑 MCP 时同时传 `--skip-docs` |
| `--skip-docs` | 跳过 AGENTS/CLAUDE |
| `--self-test` | 运行内置测试（无需项目路径） |
| `--source`、`--cursor-out`、`--codex-out`、`--mcp-out`、`--zcode-out`、`--qoder-out` | 覆盖输出路径（高级），不改变输入发现路径 |

任意位置都没有 MCP 配置时会报错退出，不会写入空配置。MCP 渲染校验失败时不会部分写盘（全部渲染完成后再写入）。

## MCP 合并顺序

读取顺序（同名 server **后者覆盖前者**）：

1. `.codex/config.toml`
2. `.zcode/config.json`
3. `.qoder/settings.json`（没有 `mcpServers` 时跳过）
4. `.mcp.json`
5. `.cursor/mcp.json`（规范 JSON 中 `${env:VAR}` → `${VAR}`）
6. `.agents/mcp.json`

## Qoder CLI / IDE

- **CLI**：自动同步 `.qoder/settings.json` 的 `mcpServers`，保留其它设置。CLI 也读取根目录 `.mcp.json`，且同名 server 优先于项目 settings，因此两处生成相同的 MCP 内容。
- **认证**：保留 `${VAR}` 占位符，不把环境变量值写入文件；将 `bearerTokenEnvVar` 转成 `Authorization: Bearer ${VAR}`，移除该扩展字段。显式指定的变量优先于已有 Authorization 头（名称不区分大小写），规范源中的原字段保留。
- **IDE**：运行脚本后，在 Settings → MCP 的 JSON 配置入口合并生成的 `.mcp.json` 中的 `mcpServers`，保留 IDE 已有的其它服务器。官方文档未明确 IDE 的项目级 MCP 文件自动加载路径，不生成臆测的 `.qoder/mcp.json`，也不承诺 IDE 自动加载 CLI 配置。IDE 的环境变量展开需在 IDE 中核验。
- **Skills / 指引**：收集 `.qoder/skills/<name>/` 到 `.agents/skills/`，再建立相对 symlink；同名 skill 以规范源为准。CLI / IDE 直接使用 `AGENTS.md`。
- 不读取或改写用户级 Qoder 配置及 `.qoder/settings.local.json`；本地覆盖和项目 MCP 审批仍由 Qoder 管理。

依据：[CLI MCP](https://docs.qoder.com/cli/mcp-reference.md)、[IDE MCP](https://docs.qoder.com/user-guide/chat/model-context-protocol.md)。

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
- 手改生成的 `.mcp.json`、`.cursor/mcp.json`、`.codex/config.toml`、`.zcode/config.json`、`.qoder/settings.json` 中的 MCP 当作源
- 在 Cursor 生成文件里手写 `${API_KEY}`（源文件 `.agents/mcp.json` 用 `${API_KEY}`，生成结果为 `${env:API_KEY}`）
- 指望 Codex 在 `http_headers` 里展开 `${API_KEY}`
- 把 Qoder CLI 配置文件误当作已验证的 IDE 自动加载入口
- 只在 `.cursor/skills` 下维护 skill 却不跑 sync（规范目录是 `.agents/skills`）
- 把长规则写在 `CLAUDE.md` 而不是 `AGENTS.md`
- 在对话里重写转换逻辑而不运行脚本
- 未传项目根却在错误的工作目录下执行
