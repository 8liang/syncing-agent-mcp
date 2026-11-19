# syncing-agent-mcp

在同一份项目里对齐 Cursor、Claude Code、Codex、Zcode、Qoder 与 Antigravity 的 MCP、Skills 与开发指引（Qoder CLI 自动同步，其 IDE 的 MCP 手动导入；Antigravity 同时同步工作区配置与 `agy` CLI / T3 Code `antigravity-acp` 全局动态分发入口）。

## 布局

| 角色 | 路径 | 说明 |
|------|------|------|
| MCP 源（合并结果） | `.agents/mcp.json` | 脚本合并各端配置后写回 |
| Claude / Qoder CLI | `.mcp.json` | 通用 MCP JSON；`bearerTokenEnvVar` 转为认证头，也供 IDE 手动导入 |
| Cursor | `.cursor/mcp.json` | `${VAR}` → `${env:VAR}` |
| Codex | `.codex/config.toml` | 认证走 `bearerTokenEnvVar` / `env_http_headers` |
| Zcode | `.zcode/config.json` | 只更新 `mcp.servers`，其它键保留；认证 HTTP server 转 stdio bridge（Desktop 不展开 `${VAR}`） |
| Qoder CLI | `.qoder/settings.json` | 只更新 `mcpServers`，其它设置保留 |
| Antigravity 工作区 | `.agents/mcp_config.json` | 只更新 `mcpServers`，其它键保留；`url` → `serverUrl`，去 `type` |
| Antigravity 全局分发 | `~/.gemini/config/mcp_config.json`、`~/.t3/userdata/providers/antigravity/*/config/mcp_config.json` | 注册 `mcp_stdio_bridge --workspace <name>` 按项目 `cwd` 动态分发，保留手写全局项 |
| Skills 源 | `.agents/skills/` | 各端 skills 目录（如 `.cursor/skills/` 等）整目录 symlink 指向这里，Antigravity 原生读取；项目存在指引文档时自动写入通用 `project-bootstrap` skill |
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

如需同时把通用启动 skill `project-bootstrap` 全局安装（对尚未跑过同步脚本的仓库也生效）：

```bash
npx skills add 8liang/syncing-agent-mcp --full-depth --skill project-bootstrap -g -y
```

## 使用

对项目根目录运行 skill 自带脚本（不要拷进业务仓库）：

```bash
python3 scripts/sync_agent_config.py /path/to/project
```

`ROOT` 与 `--root ROOT` 等价，项目根只传一次。省略参数时默认当前工作目录。脚本在 skill 安装目录下（例如 `~/.cursor/skills/syncing-agent-mcp/scripts/`），不要拷进业务仓库。

脚本会依次：

1. **MCP**：读取 `.codex/config.toml`、`.zcode/config.json`、`.qoder/settings.json`、`.mcp.json`、`.cursor/mcp.json`、`.agents/mcp_config.json`、`.agents/mcp.json`，按 server 名合并（后者覆盖前者，`.agents/mcp.json` 优先级最高），写回 `.agents/mcp.json` 并生成各端文件（含 Antigravity 全局 `--workspace` 分发配置）。
2. **指引**：把 `AGENTS.md` 与 `CLAUDE.md` 中非 `@AGENTS.md` 的正文合并进 `AGENTS.md`，并将 `CLAUDE.md` 设为 `@AGENTS.md`。
3. **Skills**：若项目存在 `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` / `.agents/rules/*.md`，自动同步内置的通用 `project-bootstrap` skill 到 `.agents/skills/project-bootstrap/SKILL.md`（帮助初始 `cwd` 偏离仓库根或未自动注入 `AGENTS.md` 的运行环境先定位并载入项目指引），再把各端既有 skills 收拢到 `.agents/skills/`，并将各端 `*/skills` 目录整目录建立指向 `.agents/skills` 的相对 symlink。

可选：

| 参数 | 作用 |
|------|------|
| `--skip-skills` | 跳过 skills 同步（含 `project-bootstrap`）；只跑 MCP 时同时传 `--skip-docs` |
| `--skip-bootstrap-skill` | 跳过自动写入 `.agents/skills/project-bootstrap/SKILL.md` |
| `--skip-docs` | 跳过 AGENTS/CLAUDE |
| `--skip-antigravity-global` | 跳过同步 `~/.gemini` 与 T3 Code Antigravity 全局 `mcp_config.json` |
| `--antigravity-global-out` | 指定合并写入 `--workspace` 分发项的全局 `mcp_config.json` 路径（可重复） |
| `--self-test` | 运行内置测试（无需项目路径） |
| `--qoder-out` | 覆盖 Qoder CLI 输出路径；输入仍从项目默认路径读取 |
| `--antigravity-out` | 覆盖工作区 Antigravity 输出路径；输入仍从项目默认路径读取 |

MCP 校验失败时不会部分写盘；任意位置都没有 MCP 配置时会直接报错退出。

## Qoder CLI / IDE

- **CLI**：自动同步 `.qoder/settings.json` 的 `mcpServers`，保留其它设置；没有该字段的 settings 文件不提供 MCP 输入。CLI 优先读取的根目录 `.mcp.json` 也生成相同 MCP 内容。
- **认证**：两处均将 `bearerTokenEnvVar` 转成 `Authorization: Bearer ${VAR}` 并移除扩展字段；显式变量优先于已有 Authorization 头（名称不区分大小写）。保留 `${VAR}` 占位符，不写入真实环境变量值，`.agents/mcp.json` 保留规范源字段。
- **IDE**：在 Settings → MCP 的 JSON 配置入口合并生成的 `.mcp.json` 中的 `mcpServers`，保留已有其它服务器。官方文档尚未明确 IDE 项目级 MCP 自动加载路径，因此不生成 `.qoder/mcp.json`，不承诺自动加载 CLI 配置；IDE 的环境变量展开需另行核验。
- **共用**：`.qoder/skills` 与其它端一样整目录链接到 `.agents/skills`，指引直接使用 `AGENTS.md`。
- 不读取或改写用户级 Qoder 配置及 `.qoder/settings.local.json`；本地覆盖和项目 MCP 审批仍由 Qoder 管理。

依据：[CLI MCP](https://docs.qoder.com/cli/mcp-reference.md)、[IDE MCP](https://docs.qoder.com/user-guide/chat/model-context-protocol.md)。

## Antigravity

- **工作区 MCP**：生成 `.agents/mcp_config.json` 的 `mcpServers`（只更新该键，保留其它顶层键）。远程 server 的 `url` 转成 `serverUrl`，并去掉 `type` 字段（Antigravity 不接受）。
- **`agy` CLI 与 T3 Code 全局按项目分发**：`agy` CLI 与 T3 Code 内置 `antigravity-acp` 不加载项目 `.agents/mcp_config.json`，仅加载各自 `$GEMINI_HOME/config/mcp_config.json`（T3 Code 隔离在 `~/.t3/userdata/providers/antigravity/<hash>/config/mcp_config.json` 且要求为普通文件而非 symlink）。同步时脚本会自动向 `~/.gemini/config/mcp_config.json` 与 T3 Code Antigravity 配置合并写入 `mcp_stdio_bridge --workspace <name>`：运行期按进程 `$PWD` 向上定位 `<workspace>/.agents/mcp_config.json` 并启动对应项目的 server（保留各项目独立的 `X-Default-Vault-Name` 等请求头与本地 `codegraph` 工作目录；未配置该 server 的项目返回空工具列表 `[]`）。当 `Antigravity.app` 后台全局进程以 `cwd=/` 启动时，非回环远程 HTTP server 自动走剥离了 `X-Default-Vault-Name` 的 `--fallback-http` 兜底；手写的非托管全局 server 原样保留。
- **认证**：与 Qoder 相同，`bearerTokenEnvVar` 转成 `Authorization: Bearer ${VAR}` 头，显式变量优先于已有 Authorization 头。Antigravity **不展开** `${VAR}`，但脚本内置**通用桥**：HTTP server 的 headers 含 `${VAR}` 时，Antigravity 输出自动转成 stdio 形态，经内置 `scripts/mcp_stdio_bridge` 在运行期从环境（`~/.config/mcp-bridge.env` → `~/.zshenv`）展开 `${VAR}`/`${env:VAR}` 后带真实请求头转发（需 `mcp-remote`：`pnpm add -g mcp-remote`，缺失回退 `npx`；桥依赖 zsh 与 python3）。源配置保持远程形式，其它端与读回均不受影响。也可直接在源里配真实凭据（勿提交敏感值）。
- **启动适配**：Antigravity 从 GUI 启动 MCP server，不继承 shell PATH 且工作目录可能是程序目录——裸 `command`（如 `npx`、`codegraph`）会启动失败。生成文件会自动把裸命令解析为绝对路径（解析失败会 stderr 告警），并为 stdio server 补充 `env.PATH`（取同步时的 shell PATH）；该文件被作为合并输入读回时这两项自动还原，不污染源与其它端。
- **生效与验证**：终端执行 `agy mcp list` 核对全局分发项；在 T3 Code 或 Antigravity IDE 中需新开会话或重载窗口（配置在会话启动时发现）。
- **共用**：skills 直接使用 `.agents/skills/`（Antigravity 原生读取，无需 symlink 层），指引直接使用 `AGENTS.md`。

依据：[MCP](https://antigravity.google/docs/mcp/)、[Skills](https://antigravity.google/docs/skills/)、[Rules](https://antigravity.google/docs/rules/)。

## Zcode Desktop

- **工作区 MCP**：自动加载 `.zcode/config.json` 的 `mcp.servers`（只更新该键，保留其它顶层键）。`bearerTokenEnvVar` 转成 `Authorization: Bearer ${VAR}` 头，显式变量优先于已有 Authorization 头。
- **认证**：Zcode Desktop 从 GUI 启动，既不继承 shell 环境（`~/.zshenv` 不生效），也不展开 HTTP headers 里的 `${VAR}`——占位符为空导致认证失败，客户端侧表现为 `Version negotiation probe failed` 并无限重试。脚本因此复用**通用桥**：headers 含 `${VAR}` 的 HTTP server 自动转成 stdio 形态（`type: "stdio"` + `mcp_stdio_bridge` + `env.PATH`），运行期从 `~/.zshenv` 展开后转发；读回时自动还原为 HTTP 形态。终端里运行的 Zcode 继承 shell 环境，两种形态都可用，统一走 bridge 最稳。
- **schema 注意**：`.zcode/config.json` 的 http 形态要求 `url` 且不接受 `command/args/env`，stdio 形态用 `type: "stdio"` + `command/args/env`；字段组合错误时整个 server 会被**静默跳过**（仅 CLI 日志出现 `config.mcp_server.skipped`，界面上无提示）。
- **启动耗时**：bridge 内 mcp-remote 的认证探测（等 401）对“不返回 401、GET 长连”的服务器（如 FNS）会各超时一次（10s + 5s），首次响应约 15-20s，之后正常；MCP 连接超时需 ≥30s。
- **生效**：MCP 配置在会话启动时读取，改动后需新开会话或重启 Zcode。

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
