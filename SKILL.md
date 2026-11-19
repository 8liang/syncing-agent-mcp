---
name: syncing-agent-mcp
description: 对齐 Cursor、Claude Code、Codex、Zcode、Qoder、Antigravity（含 agy CLI / T3 Code）的项目 MCP、skills（含 project-bootstrap）与 AGENTS.md；处理 .agents/mcp.json 等配置漂移、${VAR} 认证展开与桥接、Antigravity 全局分发与 Qoder IDE 手动导入。
---

# Syncing Agent MCP

在同一份项目里对齐 Cursor、Claude Code、Codex、Zcode、Qoder 与 Antigravity 的 MCP、Skills 与开发指引（Qoder CLI 自动同步，其 IDE 的 MCP 手动导入；Antigravity 同时生成工作区配置与按项目 `cwd` 动态分发的全局入口）。对**项目根目录**运行本 skill 自带的脚本。不要把脚本拷进业务仓库，不要手改生成的 JSON / TOML。

## 布局

| 角色 | 路径 | 说明 |
|------|------|------|
| MCP 源（合并结果） | `.agents/mcp.json` | 合并后写回；有意覆盖时改这里 |
| Claude / Qoder CLI | `.mcp.json` | 通用 MCP JSON；`bearerTokenEnvVar` 转为认证头，也供 IDE 手动导入 |
| Cursor | `.cursor/mcp.json` | `${VAR}` → `${env:VAR}` |
| Codex | `.codex/config.toml` | 认证走 `bearerTokenEnvVar` / `env_http_headers` |
| Zcode | `.zcode/config.json` | 只更新 `mcp.servers`，其它键保留；认证 HTTP server 转 stdio bridge（Desktop 不展开 `${VAR}`） |
| Qoder CLI | `.qoder/settings.json` | 只更新 `mcpServers`，其它设置保留 |
| Antigravity 工作区 | `.agents/mcp_config.json` | 只更新 `mcpServers`，其它键保留；`url` → `serverUrl`，去 `type`，不展开 `${VAR}` |
| Antigravity 全局分发 | `~/.gemini/config/mcp_config.json`、`~/.t3/userdata/providers/antigravity/*/config/mcp_config.json` | 为 `agy` CLI 与 T3 Code `antigravity-acp` 注册 `mcp_stdio_bridge --workspace <name>` 动态分发入口，保留非托管手动项 |
| Skills 源 | `.agents/skills/` | 各端 skills 目录（如 `.cursor/skills/` 等）整目录 symlink 指向这里，Antigravity 原生读取；项目存在指引文档时自动写入通用 `project-bootstrap` skill |
| 开发指引 | `AGENTS.md` | 权威正文 |
| Claude | `CLAUDE.md` | 固定为 `@AGENTS.md` |

Cursor、Codex、Qoder（CLI / IDE）与 Antigravity 直接读项目根下的 `AGENTS.md`，无需生成 `QODER.md`。

## 安装（每台机器一次）

Claude Code：

```bash
npx skills add 8liang/syncing-agent-mcp -g -a claude-code -y
```

同时装给 Cursor：

```bash
npx skills add 8liang/syncing-agent-mcp -g -a claude-code -a cursor -y
```

如需把通用启动 skill `project-bootstrap` 也全局安装（对尚未跑过本同步脚本的仓库生效）：

```bash
npx skills add 8liang/syncing-agent-mcp --full-depth --skill project-bootstrap -g -y
```

安装后脚本在 skill 包内（例如 `~/.cursor/skills/syncing-agent-mcp/scripts/sync_agent_config.py`）。始终调用该路径，不要在项目里新建 `scripts/sync_agent_config.py` 副本。

## 使用

先解析**绝对路径**的项目根，再执行：

```bash
python3 scripts/sync_agent_config.py /absolute/path/to/project
```

`ROOT` 与 `--root ROOT` 等价，项目根只传一次，不要同时传。省略参数时默认当前工作目录。

脚本**依次**执行：

1. **MCP**：读取 `.codex/config.toml`、`.zcode/config.json`、`.qoder/settings.json`、`.mcp.json`、`.cursor/mcp.json`、`.agents/mcp_config.json`、`.agents/mcp.json`，按 server 名合并（后者覆盖前者，`.agents/mcp.json` 优先级最高），写回 `.agents/mcp.json` 并生成各端文件（含 Antigravity 全局 `--workspace` 分发配置）。
2. **指引**：把 `AGENTS.md` 与 `CLAUDE.md` 中非 `@AGENTS.md` 的正文合并进 `AGENTS.md`，并将 `CLAUDE.md` 设为 `@AGENTS.md`。
3. **Skills**：若项目存在 `AGENTS.md` / `CLAUDE.md` / `GEMINI.md` / `.agents/rules/*.md`，自动同步内置的通用 `project-bootstrap` skill 到 `.agents/skills/project-bootstrap/SKILL.md`（帮助初始 `cwd` 偏离仓库根或未自动注入 `AGENTS.md` 的环境先定位并载入项目指引），再把各端既有 skills 收拢到 `.agents/skills/`，并将各端 `*/skills` 目录整目录建立指向 `.agents/skills` 的相对 symlink。

可选参数：

| 参数 | 作用 |
|------|------|
| `--skip-skills` | 跳过 skills 同步（含 `project-bootstrap`）；只跑 MCP 时同时传 `--skip-docs` |
| `--skip-bootstrap-skill` | 跳过自动写入 `.agents/skills/project-bootstrap/SKILL.md` |
| `--skip-docs` | 跳过 AGENTS/CLAUDE |
| `--skip-antigravity-global` | 跳过更新 `~/.gemini` 与 T3 Code Antigravity 全局 `mcp_config.json` |
| `--antigravity-global-out` | 指定要合并写入 `--workspace` 分发项的全局 `mcp_config.json` 路径（可重复传入） |
| `--self-test` | 运行内置测试（无需项目路径） |
| `--source`、`--cursor-out`、`--codex-out`、`--mcp-out`、`--zcode-out`、`--qoder-out`、`--antigravity-out` | 覆盖输出路径（高级），不改变输入发现路径 |

任意位置都没有 MCP 配置时会报错退出，不会写入空配置。MCP 渲染校验失败时不会部分写盘（全部渲染完成后再写入）。

## MCP 合并顺序

读取顺序（同名 server **后者覆盖前者**）：

1. `.codex/config.toml`
2. `.zcode/config.json`
3. `.qoder/settings.json`（没有 `mcpServers` 时跳过）
4. `.mcp.json`
5. `.cursor/mcp.json`（规范 JSON 中 `${env:VAR}` → `${VAR}`）
6. `.agents/mcp_config.json`（`serverUrl` → `url`，补 `type`；自动忽略 `--workspace` 分发桩）
7. `.agents/mcp.json`

## Qoder CLI / IDE

- **CLI**：自动同步 `.qoder/settings.json` 的 `mcpServers`，保留其它设置。CLI 也读取根目录 `.mcp.json`，且同名 server 优先于项目 settings，因此两处生成相同的 MCP 内容。
- **认证**：保留 `${VAR}` 占位符，不把环境变量值写入文件；将 `bearerTokenEnvVar` 转成 `Authorization: Bearer ${VAR}`，移除该扩展字段。显式指定的变量优先于已有 Authorization 头（名称不区分大小写），规范源中的原字段保留。
- **IDE**：运行脚本后，在 Settings → MCP 的 JSON 配置入口合并生成的 `.mcp.json` 中的 `mcpServers`，保留 IDE 已有的其它服务器。官方文档未明确 IDE 的项目级 MCP 文件自动加载路径，不生成臆测的 `.qoder/mcp.json`，也不承诺 IDE 自动加载 CLI 配置。IDE 的环境变量展开需在 IDE 中核验。
- **Skills / 指引**：收集 `.qoder/skills` 中的既有 skills 到 `.agents/skills/`，再将 `.qoder/skills` 整目录建立指向 `.agents/skills` 的相对 symlink；同名 skill 以规范源为准。CLI / IDE 直接使用 `AGENTS.md`。
- 不读取或改写用户级 Qoder 配置及 `.qoder/settings.local.json`；本地覆盖和项目 MCP 审批仍由 Qoder 管理。

依据：[CLI MCP](https://docs.qoder.com/cli/mcp-reference.md)、[IDE MCP](https://docs.qoder.com/user-guide/chat/model-context-protocol.md)。

## Antigravity

- **工作区 MCP**：生成工作区 `.agents/mcp_config.json`（只更新 `mcpServers`，保留其它顶层键；远程 server 的 `url` 转为 `serverUrl`，`type` 字段一律移除）。
- **`agy` CLI 与 T3 Code `antigravity-acp` 全局按项目动态分发**：实测 `agy` CLI（1.5.x）与 T3 Code 内置 `antigravity-acp`（`localharness_external`）均**不读取**项目下的 `.agents/mcp_config.json`，只读取各自 `$GEMINI_HOME/config/mcp_config.json`（T3 Code 将 `GEMINI_HOME` 隔离到 `~/.t3/userdata/providers/antigravity/<hash>`，且校验 `config/mcp_config.json` 必须是普通文件而非 symlink）。同步时脚本会自动将当前项目的 server 以 `mcp_stdio_bridge --workspace <name>` 分发项合并写入 `~/.gemini/config/mcp_config.json` 与 `~/.t3/userdata/providers/antigravity/*/config/mcp_config.json`（写盘前自动解除潜在 symlink 并保持普通文件）：
  - **按项目 `cwd` 精确路由**：`agy` 与 T3 Code `antigravity-acp` 均以项目根目录作为进程 `cwd` 启动 MCP。`mcp_stdio_bridge --workspace <name>` 从 `$PWD`（或 `$MCP_WORKSPACE_DIR`）向上查找 `<workspace>/.agents/mcp_config.json`，切到对应项目目录启动真实 server——多项目各自的 `X-Default-Vault-Name`（如 FNS vault）或本地 `codegraph` 互不串台；若当前项目未配置某全局已注册的 `<name>`，则返回合法的空工具列表（`tools/list -> []`），不报错阻塞会话。
  - **GUI 根进程兜底**：`Antigravity.app` 后台全局语言服务常以 `cwd=/` 运行；对非回环远程 HTTP server，全局分发项附带 `--fallback-http <url>`（自动剥离项目专属 `X-Default-Vault-Name` 头，保留鉴权头占位符并在运行期展开）；回环地址（`127.0.0.1` / `localhost`）与本地 stdio server 在 `cwd=/` 下直接返回空工具列表。
  - **无损合并**：保留全局 `mcp_config.json` 其它顶层键、其它项目的已注册分发项，以及非 `mcp_stdio_bridge` 托管的同名手写全局 server。可用 `--skip-antigravity-global` 关闭全局写入，或用 `--antigravity-global-out` 指定目标。
- **认证**：`bearerTokenEnvVar` 转成 `Authorization: Bearer ${VAR}` 头并移除该扩展字段（与 Qoder 相同，显式变量优先于已有 Authorization 头）。Antigravity 原生不展开 `${VAR}`——脚本内置**通用桥**：HTTP server 的 headers 只要含 `${VAR}`，Antigravity 输出会自动转成 stdio 形态，指向 skill 自带的 `scripts/mcp_stdio_bridge`，由它在运行期展开 `${VAR}`/`${env:VAR}`（环境取自 `~/.config/mcp-bridge.env`、`~/.zshenv`）后带真实请求头转发。源配置保持远程形式即可，其它端不受影响，读回时自动还原为 HTTP 形态。带静态鉴权头或回环地址时自动走内置 `mcp_http_stdio_bridge.mjs`（node 直连 Streamable HTTP，跳过 OAuth `GET` 探测，FNS 启动 <1s）；无静态鉴权的远程 OAuth 端点或 `--use-mcp-remote` 回退 `mcp-remote`（`pnpm add -g mcp-remote`，缺失回退 `npx`）；桥依赖 zsh + python3 + node；桥文件缺失时保持原样并 stderr 告警。也可改源文件直接用真实凭据（勿提交敏感值）。
- **启动适配**：Antigravity 从 GUI 启动 MCP server，不继承 shell PATH 且工作目录可能是程序目录——裸 `command`（如 `npx`、`codegraph`）会启动失败。脚本生成时会自动把裸命令解析为绝对路径（解析失败 stderr 告警），并为 stdio server 补充 `env.PATH`（取同步时的 shell PATH）。读回该文件时自动还原，不影响规范源与其它端输出。
- **生效与验证**：在 `agy` CLI 中运行 `agy mcp list` 核对已注册列表；在 T3 Code 或 Antigravity IDE 中需**新开线程 / 重启窗口**（MCP 在会话初始化时握手发现）。
- **合并细节**：`.agents/mcp_config.json` 在 `.agents/mcp.json` 之前读取，同名 server 以 `.agents/mcp.json` 为准。Antigravity 界面上新增的 server 仅在 canonical 无同名时被收编。
- **Skills / 指引**：Antigravity 原生读取工作区 `.agents/skills/`（T3 Code 同时将全局 skills 链接到 provider `config/skills`），指引直接使用 `AGENTS.md`。

依据：[MCP](https://antigravity.google/docs/mcp/)、[Skills](https://antigravity.google/docs/skills/)、[Rules](https://antigravity.google/docs/rules/)。

## Zcode Desktop

- **工作区 MCP**：自动加载工作区 `.zcode/config.json`（脚本只更新 `mcp.servers`，保留其它顶层键）。`bearerTokenEnvVar` 转成 `Authorization: Bearer ${VAR}` 头（显式变量优先于已有 Authorization 头）。
- **认证**：Zcode Desktop 从 GUI 启动，不继承 shell 环境（`~/.zshenv` 不生效），也不展开 HTTP headers 里的 `${VAR}`——占位符为空导致认证失败，客户端侧表现为 `Version negotiation probe failed` 并无限重试。脚本复用**通用桥**：headers 含 `${VAR}` 的 HTTP server 自动转成 stdio 形态（`type: "stdio"` + skill 自带 `scripts/mcp_stdio_bridge` + `env.PATH`），运行期从 `~/.zshenv` 展开后转发；读回时自动还原为 HTTP 形态。终端里运行的 Zcode 继承 shell 环境，两种形态都可用，统一走 bridge 最稳。
- **schema 注意**：`.zcode/config.json` 的 http 形态要求 `url` 且不接受 `command/args/env`，stdio 形态用 `type: "stdio"` + `command/args/env`；字段组合错误时整个 server 会被**静默跳过**（仅 CLI 日志出现 `config.mcp_server.skipped`）。
- **启动耗时**：带静态鉴权头（如 `Authorization` / API Key）或回环地址的 HTTP server 已改由内置 `mcp_http_stdio_bridge.mjs` 直连 Streamable HTTP，彻底避开 `mcp-remote` 的 10s + 5s OAuth `GET` 超时，FNS 启动从 ~15-20s 降至 <1s；仅无静态鉴权的远程 OAuth 端点走 `mcp-remote`。
- **生效**：MCP 配置在会话启动时读取，改动后需新开会话或重启 Zcode。
- **Skills / 指引**：`.zcode/skills` 与其它端一样整目录 symlink 到 `.agents/skills`，指引直接使用 `AGENTS.md`。

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

- 把转换脚本拷进业务仓库，或运行工作区副本导致生成的 `mcp_stdio_bridge` 路径指向业务目录而非 `~/.agents/skills/syncing-agent-mcp/scripts/`
- 手改生成的 `.mcp.json`、`.cursor/mcp.json`、`.codex/config.toml`、`.zcode/config.json`、`.qoder/settings.json`、`.agents/mcp_config.json` 中的 MCP 当作源
- 在 Cursor 生成文件里手写 `${API_KEY}`（源文件 `.agents/mcp.json` 用 `${API_KEY}`，生成结果为 `${env:API_KEY}`）
- 指望 Codex 在 `http_headers` 里展开 `${API_KEY}`
- 指望 Antigravity 展开 `.agents/mcp_config.json` 里的 `${VAR}`（不会展开，按字面量发送）
- 指望 `agy` CLI 或 T3 Code `antigravity-acp` 自动读取项目 `.agents/mcp_config.json`（两者只读各自 `$GEMINI_HOME/config/mcp_config.json`，需靠脚本同步写入全局 `--workspace` 分发项，且 T3 Code 的 `config/mcp_config.json` 不能做成 symlink）
- 用 `--antigravity-out ~/.gemini/config/mcp_config.json` 强行把单项目配置覆盖进全局（会把特定项目的 `X-Default-Vault-Name` 写死到全局导致多项目串台；应直接正常运行脚本自动合并 `--workspace` 分发项）
- 指望 Zcode Desktop 展开 `.zcode/config.json` HTTP headers 里的 `${VAR}`（GUI 进程不继承 shell 环境，认证失败后无限重试）
- `.zcode/config.json` 里给 stdio server 留着 `type: "http"` 或给 http server 混入 `command/args`（schema 校验失败，整个 server 被**静默跳过**，只看 CLI 日志才能发现）
- Antigravity 里 server 起不来却只检查 JSON 格式（先用 `agy mcp list` 或 MCP 面板 “View raw config” 确认读到哪份配置，再看 stderr 的裸命令解析告警，并确认已新开会话）
- 手改 `.agents/mcp_config.json` 当源（同名 server 会被 `.agents/mcp.json` 覆盖）
- 把真实凭据只填进生成的 `.agents/mcp_config.json`（同名 server 下次同步会被源覆盖）
- 把 Qoder CLI 配置文件误当作已验证的 IDE 自动加载入口
- 只在 `.cursor/skills` 下维护 skill 却不跑 sync（规范目录是 `.agents/skills`）
- 把长规则写在 `CLAUDE.md` 而不是 `AGENTS.md`
- 在对话里重写转换逻辑而不运行脚本
- 未传项目根却在错误的工作目录下执行
