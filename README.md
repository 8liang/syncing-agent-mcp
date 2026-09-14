# syncing-agent-mcp

一份 MCP 源配置，生成 Claude / Cursor / Codex 各自要用的文件。

| 角色 | 路径 |
|------|------|
| 源（手改） | `.agents/mcp.json` |
| Claude | `.mcp.json` |
| Cursor | `.cursor/mcp.json`（`${VAR}` → `${env:VAR}`） |
| Codex | `.codex/config.toml` |

## 安装

```bash
npx skills add 8liang/syncing-agent-mcp -g -a claude-code -y
```

同时装给 Cursor：

```bash
npx skills add 8liang/syncing-agent-mcp -g -a claude-code -a cursor -y
```

## 使用

改完 `.agents/mcp.json` 后，对项目根目录跑 skill 自带脚本：

```bash
python3 scripts/sync_agent_config.py /path/to/project
```

不要把脚本拷进业务仓库，也不要手改生成文件。
