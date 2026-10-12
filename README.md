# syncing-agent-mcp

在同一份项目里对齐 Cursor、Claude Code、Codex、Zcode、Qoder 与 Antigravity 的 MCP、Skills 与开发指引（Qoder CLI 自动同步，其 IDE 的 MCP 手动导入；Antigravity 自动加载工作区配置）。

## 布局

| 角色 | 路径 | 说明 |
|------|------|------|
| MCP 源（合并结果） | `.agents/mcp.json` | 脚本合并各端配置后写回 |
| Claude / Qoder CLI | `.mcp.json` | 通用 MCP JSON；`bearerTokenEnvVar` 转为认证头，也供 IDE 手动导入 |
| Cursor | `.cursor/mcp.json` | `${VAR}` → `${env:VAR}` |
| Codex | `.codex/config.toml` | 认证走 `bearerTokenEnvVar` / `env_http_headers` |
| Zcode | `.zcode/config.json` | 只更新 `mcp.servers`，其它键保留 |
| Qoder CLI | `.qoder/settings.json` | 只更新 `mcpServers`，其它设置保留 |
| Antigravity | `.agents/mcp_config.json` | 只更新 `mcpServers`，其它键保留；`url` → `serverUrl`，去 `type` |
| Skills 源 | `.agents/skills/` | 各端 skill 目录（含 `.qoder/skills/`）symlink 到这里，Antigravity 原生读取 |
| 开发指引 | `AGENTS.md` | 权威正文 |
| Claude | `CLAUDE.md` | 固定为 `@AGENTS.md` |

Cursor、Codex、Qoder（CLI / IDE）与 Antigravity 直接读项目根下的 `AGENTS.md`，无需生成 `QODER.md`。

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

1. **MCP**：读取 `.codex/config.toml`、`.zcode/config.json`、`.qoder/settings.json`、`.mcp.json`、`.cursor/mcp.json`、`.agents/mcp_config.json`、`.agents/mcp.json`，按 server 名合并（后者覆盖前者，`.agents/mcp.json` 优先级最高），写回 `.agents/mcp.json` 并生成各端文件。
2. **Skills**：把各端 `*/skills/<name>/` 收拢到 `.agents/skills/`，再在各端建立指向该目录的 symlink。
3. **指引**：把 `AGENTS.md` 与 `CLAUDE.md` 中非 `@AGENTS.md` 的正文合并进 `AGENTS.md`，并将 `CLAUDE.md` 设为 `@AGENTS.md`。

可选：

| 参数 | 作用 |
|------|------|
| `--skip-skills` | 跳过 skills 同步；只跑 MCP 时同时传 `--skip-docs` |
| `--skip-docs` | 跳过 AGENTS/CLAUDE |
| `--self-test` | 运行内置测试（无需项目路径） |
| `--qoder-out` | 覆盖 Qoder CLI 输出路径；输入仍从项目默认路径读取 |
| `--antigravity-out` | 覆盖 Antigravity 输出路径；输入仍从项目默认路径读取 |

MCP 校验失败时不会部分写盘；任意位置都没有 MCP 配置时会直接报错退出。

## Qoder CLI / IDE

- **CLI**：自动同步 `.qoder/settings.json` 的 `mcpServers`，保留其它设置；没有该字段的 settings 文件不提供 MCP 输入。CLI 优先读取的根目录 `.mcp.json` 也生成相同 MCP 内容。
- **认证**：两处均将 `bearerTokenEnvVar` 转成 `Authorization: Bearer ${VAR}` 并移除扩展字段；显式变量优先于已有 Authorization 头（名称不区分大小写）。保留 `${VAR}` 占位符，不写入真实环境变量值，`.agents/mcp.json` 保留规范源字段。
- **IDE**：在 Settings → MCP 的 JSON 配置入口合并生成的 `.mcp.json` 中的 `mcpServers`，保留已有其它服务器。官方文档尚未明确 IDE 项目级 MCP 自动加载路径，因此不生成 `.qoder/mcp.json`，不承诺自动加载 CLI 配置；IDE 的环境变量展开需另行核验。
- **共用**：`.qoder/skills/<name>` 与其它端一样链接到 `.agents/skills/<name>`，指引直接使用 `AGENTS.md`。
- 不读取或改写用户级 Qoder 配置及 `.qoder/settings.local.json`；本地覆盖和项目 MCP 审批仍由 Qoder 管理。

依据：[CLI MCP](https://docs.qoder.com/cli/mcp-reference.md)、[IDE MCP](https://docs.qoder.com/user-guide/chat/model-context-protocol.md)。

## Antigravity

- **工作区 MCP**：自动加载 `.agents/mcp_config.json` 的 `mcpServers`（只更新该键，保留其它顶层键）。远程 server 的 `url` 转成 `serverUrl`，并去掉 `type` 字段（Antigravity 不接受）。
- **认证**：与 Qoder 相同，`bearerTokenEnvVar` 转成 `Authorization: Bearer ${VAR}` 头，显式变量优先于已有 Authorization 头。Antigravity **不展开** `${VAR}`，但脚本内置**通用桥**：HTTP server 的 headers 含 `${VAR}` 时，Antigravity 输出自动转成 stdio 形态，经内置 `scripts/mcp_stdio_bridge` 在运行期从环境（`~/.config/mcp-bridge.env` → `~/.zshenv`）展开 `${VAR}`/`${env:VAR}` 后带真实请求头转发（需 `mcp-remote`：`pnpm add -g mcp-remote`，缺失回退 `npx`；桥为 zsh 脚本）。源配置保持远程形式，其它端与读回均不受影响。也可直接在源里配真实凭据（勿提交敏感值）。
- **启动适配**：Antigravity 从 GUI 启动 MCP server，不继承 shell PATH 且工作目录是程序目录——裸 `command`（如 `npx`、`codegraph`）会启动失败。生成文件会自动把裸命令解析为绝对路径（解析失败会 stderr 告警），并为 stdio server 补充 `env.PATH`（取同步时的 shell PATH）；该文件被作为合并输入读回时这两项自动还原，不污染源与其它端。
- **生效与验证**：以项目根为工作区打开 → 重启 Antigravity 或重载窗口（配置在启动时发现，工作区需已信任）→ 在 MCP Servers 面板核对列表，可点 “View raw config” 对照实际读到的内容。
- **共用**：skills 直接使用 `.agents/skills/`（Antigravity 原生读取，无需 symlink 层），指引直接使用 `AGENTS.md`。
- 不读取或改写全局 `~/.gemini/config/mcp_config.json`；如需把项目配置写到全局，可 `--antigravity-out` 指向该路径（整体覆盖其 `mcpServers`）。

依据：[MCP](https://antigravity.google/docs/mcp/)、[Skills](https://antigravity.google/docs/skills/)、[Rules](https://antigravity.google/docs/rules/)。

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
