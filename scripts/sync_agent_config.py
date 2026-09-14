#!/usr/bin/env python3
"""Generate Codex, Cursor, and project MCP configs from .agents/mcp.json."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ENV_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def q(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def array(values: list[object]) -> str:
    return "[" + ", ".join(q(v) for v in values) + "]"


def rewrite_cursor_env(value: str) -> str:
    """Turn ${VAR} into Cursor's ${env:VAR}. Leave ${env:VAR} unchanged."""
    return ENV_PLACEHOLDER.sub(r"${env:\1}", value)


def rewrite_json_strings(node: object) -> object:
    if isinstance(node, str):
        return rewrite_cursor_env(node)
    if isinstance(node, list):
        return [rewrite_json_strings(item) for item in node]
    if isinstance(node, dict):
        return {key: rewrite_json_strings(value) for key, value in node.items()}
    return node


def render_codex(servers: dict) -> str:
    lines = [
        "# AUTO-GENERATED FROM .agents/mcp.json",
        "# DO NOT EDIT MANUALLY",
        "",
    ]

    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            raise SystemExit(f"mcpServers.{name} must be an object")

        lines.append(f"[mcp_servers.{q(name)}]")

        if "command" in cfg:
            lines.append(f"command = {q(cfg['command'])}")
            if cfg.get("args"):
                lines.append(f"args = {array(cfg['args'])}")

        if "url" in cfg:
            lines.append(f"url = {q(cfg['url'])}")

        env = cfg.get("env")
        if env:
            lines.append("")
            lines.append(f"[mcp_servers.{q(name)}.env]")
            for key, value in env.items():
                lines.append(f"{q(key)} = {q(value)}")

        headers = cfg.get("headers")
        if headers:
            lines.append("")
            lines.append(f"[mcp_servers.{q(name)}.http_headers]")
            for key, value in headers.items():
                lines.append(f"{q(key)} = {q(value)}")

        lines.append("")

    return "\n".join(lines)


def render_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def render_cursor(data: dict) -> str:
    return render_json(rewrite_json_strings(data))


def load_source(source: Path, fallbacks: list[Path]) -> dict:
    if source.exists():
        return json.loads(source.read_text(encoding="utf-8"))

    for fallback in fallbacks:
        if fallback.exists():
            source.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(fallback, source)
            print(f"Bootstrapped {source} from {fallback}", file=sys.stderr)
            return json.loads(source.read_text(encoding="utf-8"))

    names = ", ".join(str(path) for path in fallbacks)
    raise SystemExit(f"Missing source {source} (and no fallback among: {names})")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def sync(
    root: Path,
    source: Path,
    cursor_out: Path,
    codex_out: Path,
    mcp_out: Path,
) -> None:
    data = load_source(source, [cursor_out, mcp_out])
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        raise SystemExit("source JSON must contain an mcpServers object")

    write_text(mcp_out, render_json(data))
    write_text(cursor_out, render_cursor(data))
    write_text(codex_out, render_codex(servers))
    print(f"Generated {mcp_out.relative_to(root)}")
    print(f"Generated {cursor_out.relative_to(root)}")
    print(f"Generated {codex_out.relative_to(root)}")


def self_test() -> None:
    assert rewrite_cursor_env("Bearer ${FNS_API_KEY}") == "Bearer ${env:FNS_API_KEY}"
    assert rewrite_cursor_env("Bearer ${env:FNS_API_KEY}") == "Bearer ${env:FNS_API_KEY}"
    mixed = rewrite_json_strings(
        {"headers": {"Authorization": "Bearer ${TOKEN}", "X": "${env:KEEP}"}}
    )
    assert mixed == {
        "headers": {"Authorization": "Bearer ${env:TOKEN}", "X": "${env:KEEP}"}
    }

    toml = render_codex(
        {
            "codegraph": {"command": "codegraph", "args": ["serve", "--mcp"]},
            "fns": {
                "url": "https://example.invalid/mcp",
                "headers": {"Authorization": "Bearer ${FNS_API_KEY}"},
            },
        }
    )
    assert 'command = "codegraph"' in toml
    assert 'args = ["serve", "--mcp"]' in toml
    assert 'url = "https://example.invalid/mcp"' in toml
    assert "[mcp_servers.\"fns\".http_headers]" in toml
    copied = render_json(
        {"mcpServers": {"fns": {"url": "https://example.invalid", "headers": {"A": "${TOKEN}"}}}}
    )
    assert "${TOKEN}" in copied
    assert "${env:TOKEN}" not in copied
    print("self-test ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate .mcp.json, .cursor/mcp.json, and .codex/config.toml from .agents/mcp.json"
    )
    parser.add_argument(
        "root",
        nargs="?",
        type=Path,
        help="project root (default: current directory)",
    )
    parser.add_argument("--root", dest="root_flag", type=Path, help="alias for positional root")
    parser.add_argument("--source", type=Path)
    parser.add_argument("--cursor-out", type=Path)
    parser.add_argument("--codex-out", type=Path)
    parser.add_argument("--mcp-out", type=Path)
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_test:
        self_test()
        return

    if args.root and args.root_flag and args.root.resolve() != args.root_flag.resolve():
        raise SystemExit("pass the project root once: ROOT or --root ROOT, not both")

    root = (args.root_flag or args.root or Path.cwd()).resolve()
    source = (args.source or root / ".agents" / "mcp.json").resolve()
    cursor_out = (args.cursor_out or root / ".cursor" / "mcp.json").resolve()
    codex_out = (args.codex_out or root / ".codex" / "config.toml").resolve()
    mcp_out = (args.mcp_out or root / ".mcp.json").resolve()
    sync(root, source, cursor_out, codex_out, mcp_out)


if __name__ == "__main__":
    main()
