#!/usr/bin/env python3
"""Sync MCP, skills, and agent instructions across Cursor, Claude, Codex, Zcode, and Qoder."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from copy import deepcopy
from pathlib import Path

ENV_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
CURSOR_ENV_PLACEHOLDER = re.compile(r"\$\{env:([A-Za-z_][A-Za-z0-9_]*)\}")
CLAUDE_AGENTS_IMPORT = re.compile(r"^\s*@AGENTS\.md\s*$", re.MULTILINE)

AGENT_SKILL_DIRS = (
    ".cursor/skills",
    ".codex/skills",
    ".claude/skills",
    ".zcode/skills",
    ".qoder/skills",
)
CANONICAL_SKILLS = Path(".agents/skills")


def q(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def array(values: list[object]) -> str:
    return "[" + ", ".join(q(v) for v in values) + "]"


def rewrite_cursor_env(value: str) -> str:
    """Turn ${VAR} into Cursor's ${env:VAR}. Leave ${env:VAR} unchanged."""
    return ENV_PLACEHOLDER.sub(r"${env:\1}", value)


def rewrite_cursor_env_back(value: str) -> str:
    """Turn Cursor's ${env:VAR} back into ${VAR} for the canonical JSON."""
    return CURSOR_ENV_PLACEHOLDER.sub(r"${\1}", value)


def rewrite_json_strings(node: object) -> object:
    if isinstance(node, str):
        return rewrite_cursor_env(node)
    if isinstance(node, list):
        return [rewrite_json_strings(item) for item in node]
    if isinstance(node, dict):
        return {key: rewrite_json_strings(value) for key, value in node.items()}
    return node


def rewrite_json_strings_back(node: object) -> object:
    if isinstance(node, str):
        return rewrite_cursor_env_back(node)
    if isinstance(node, list):
        return [rewrite_json_strings_back(item) for item in node]
    if isinstance(node, dict):
        return {key: rewrite_json_strings_back(value) for key, value in node.items()}
    return node


BEARER_PLACEHOLDER = re.compile(
    r"Bearer\s+\$\{([A-Za-z_][A-Za-z0-9_]*)\}", re.IGNORECASE
)


def codex_bearer_env_var(name: str, cfg: dict, headers: dict) -> str | None:
    """Pick the env var Codex reads for Authorization: Bearer <token>.

    Codex builds that header itself from bearer_token_env_var. A source
    `Authorization: Bearer ${VAR}` header is the same intent, so adopt it
    rather than shipping a placeholder Codex will never expand.
    """
    is_http = "url" in cfg

    if "bearerTokenEnvVar" in cfg:
        if not is_http:
            raise SystemExit(
                f"mcpServers.{name}.bearerTokenEnvVar needs a url "
                "(bearer_token_env_var is HTTP-only)"
            )
        explicit = cfg["bearerTokenEnvVar"]
        if not isinstance(explicit, str) or not explicit.strip():
            raise SystemExit(
                f"mcpServers.{name}.bearerTokenEnvVar must be a non-empty string "
                "(it names an environment variable, not the token itself)"
            )
        return explicit

    if not is_http:
        return None

    for key, value in headers.items():
        if key.lower() != "authorization" or not isinstance(value, str):
            continue
        match = BEARER_PLACEHOLDER.fullmatch(value.strip())
        if match:
            print(
                f"mcpServers.{name}: derived bearerTokenEnvVar "
                f"{match.group(1)!r} from the Authorization header",
                file=sys.stderr,
            )
            return match.group(1)
    return None


def split_codex_headers(
    name: str, headers: object, bearer_env_var: object
) -> tuple[dict, dict]:
    """Split source headers into Codex http_headers and env_http_headers.

    Codex never expands ${VAR} inside http_headers, so a placeholder left there
    ships as a literal and the server answers with a non-JSON-RPC 401. Static
    values go to http_headers; a value that is exactly ${VAR} becomes an
    env_http_headers entry (Codex reads that env var at request time).
    """
    static: dict = {}
    from_env: dict = {}
    if not headers:
        return static, from_env
    if not isinstance(headers, dict):
        raise SystemExit(f"mcpServers.{name}.headers must be an object")

    for key, value in headers.items():
        if not isinstance(value, str):
            static[key] = value
            continue
        if bearer_env_var and key.lower() == "authorization":
            continue
        match = ENV_PLACEHOLDER.fullmatch(value)
        if match:
            from_env[key] = match.group(1)
            continue
        if "${" in value:
            raise SystemExit(
                f"mcpServers.{name}.headers[{key!r}] = {value!r}: Codex does not "
                "expand ${VAR} in http_headers. Use a whole-value placeholder "
                f'({q(key)} = {q("${VAR}")}) to generate env_http_headers, or set '
                "bearerTokenEnvVar for an Authorization: Bearer token."
            )
        static[key] = value

    return static, from_env


def codex_server_to_canonical(cfg: dict) -> dict:
    out: dict = {}
    if "url" in cfg:
        out["url"] = cfg["url"]
        out["type"] = "http"
    if "command" in cfg:
        out["command"] = cfg["command"]
        if cfg.get("args"):
            out["args"] = cfg["args"]
        out.setdefault("type", "stdio")
    if cfg.get("bearer_token_env_var"):
        out["bearerTokenEnvVar"] = cfg["bearer_token_env_var"]
    headers: dict = {}
    for key, value in (cfg.get("http_headers") or {}).items():
        headers[key] = value
    for key, var_name in (cfg.get("env_http_headers") or {}).items():
        headers[key] = f"${{{var_name}}}"
    if headers:
        out["headers"] = headers
    if cfg.get("env"):
        out["env"] = cfg["env"]
    return out


def load_codex_servers(path: Path) -> dict:
    if not path.exists():
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    raw = data.get("mcp_servers")
    if not isinstance(raw, dict):
        return {}
    return {name: codex_server_to_canonical(cfg) for name, cfg in raw.items() if isinstance(cfg, dict)}


def zcode_server_to_canonical(cfg: dict) -> dict:
    out = deepcopy(cfg)
    if "url" in out and "type" not in out:
        out["type"] = "http"
    if "command" in out and "type" not in out:
        out["type"] = "stdio"
    return out


def load_zcode_servers(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("mcp", {}).get("servers")
    if not isinstance(raw, dict):
        return {}
    return {name: zcode_server_to_canonical(cfg) for name, cfg in raw.items() if isinstance(cfg, dict)}


def load_mcp_json_servers(
    path: Path, *, from_cursor: bool, allow_missing_servers: bool = False
) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"{path} must be a JSON object")
    if allow_missing_servers and "mcpServers" not in data:
        return {}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        raise SystemExit(f"{path}: expected top-level mcpServers object")
    out: dict = {}
    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            raise SystemExit(f"{path}: mcpServers.{name} must be an object")
        out[name] = rewrite_json_strings_back(cfg) if from_cursor else deepcopy(cfg)
    return out


def merge_mcp_servers(root: Path) -> dict[str, dict]:
    """Collect MCP servers from every agent config; later layers override name clashes."""
    layers: list[tuple[str, dict]] = [
        ("codex", load_codex_servers(root / ".codex" / "config.toml")),
        ("zcode", load_zcode_servers(root / ".zcode" / "config.json")),
        ("qoder", load_mcp_json_servers(
            root / ".qoder" / "settings.json", from_cursor=False, allow_missing_servers=True
        )),
        ("claude", load_mcp_json_servers(root / ".mcp.json", from_cursor=False)),
        ("cursor", load_mcp_json_servers(root / ".cursor" / "mcp.json", from_cursor=True)),
        ("agents", load_mcp_json_servers(root / ".agents" / "mcp.json", from_cursor=False)),
    ]
    merged: dict[str, dict] = {}
    for label, servers in layers:
        for name, cfg in servers.items():
            if name in merged and merged[name] != cfg:
                print(f"mcpServers.{name}: {label} overrides earlier entry", file=sys.stderr)
            merged[name] = cfg
    return merged


def zcode_server_from_canonical(cfg: dict) -> dict:
    out = deepcopy(cfg)
    bearer = out.pop("bearerTokenEnvVar", None)
    headers = dict(out.get("headers") or {})
    if bearer and not any(k.lower() == "authorization" for k in headers):
        headers["Authorization"] = f"Bearer ${{{bearer}}}"
    if headers:
        out["headers"] = headers
    elif "headers" in out:
        del out["headers"]
    return out


def render_zcode_config(servers: dict, existing: Path) -> str:
    data: dict = {}
    if existing.exists():
        data = json.loads(existing.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SystemExit(f"{existing} must be a JSON object")
    mcp = data.setdefault("mcp", {})
    if not isinstance(mcp, dict):
        mcp = {}
        data["mcp"] = mcp
    mcp["servers"] = {name: zcode_server_from_canonical(cfg) for name, cfg in servers.items()}
    return render_json(data)


def qoder_server_from_canonical(cfg: dict) -> dict:
    out = deepcopy(cfg)
    bearer = out.pop("bearerTokenEnvVar", None)
    if bearer:
        headers = {key: value for key, value in (out.get("headers") or {}).items()
                   if key.lower() != "authorization"}
        headers["Authorization"] = f"Bearer ${{{bearer}}}"
        out["headers"] = headers
    return out


def render_qoder_config(servers: dict, existing: Path) -> str:
    data: dict = {}
    if existing.exists():
        data = json.loads(existing.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SystemExit(f"{existing} must be a JSON object")
    data["mcpServers"] = servers
    return render_json(data)


def render_codex(servers: dict) -> str:
    lines = [
        "# AUTO-GENERATED FROM .agents/mcp.json",
        "# DO NOT EDIT MANUALLY",
        "",
    ]

    for name, cfg in servers.items():
        if not isinstance(cfg, dict):
            raise SystemExit(f"mcpServers.{name} must be an object")

        if "url" not in cfg and cfg.get("headers"):
            # Codex rejects the whole config, not just this server:
            # "http_headers is not supported for stdio".
            raise SystemExit(
                f"mcpServers.{name}: `headers` is only valid on an HTTP server "
                "(add a url, or drop the headers) — Codex refuses to load a "
                "config with headers on a stdio server."
            )

        lines.append(f"[mcp_servers.{q(name)}]")

        if "command" in cfg:
            lines.append(f"command = {q(cfg['command'])}")
            if cfg.get("args"):
                lines.append(f"args = {array(cfg['args'])}")

        if "url" in cfg:
            lines.append(f"url = {q(cfg['url'])}")

        headers = cfg.get("headers") or {}
        bearer_env_var = codex_bearer_env_var(name, cfg, headers)
        if bearer_env_var:
            lines.append(f"bearer_token_env_var = {q(bearer_env_var)}")

        env = cfg.get("env")
        if env:
            lines.append("")
            lines.append(f"[mcp_servers.{q(name)}.env]")
            for key, value in env.items():
                lines.append(f"{q(key)} = {q(value)}")

        static, from_env = split_codex_headers(name, headers, bearer_env_var)
        if static:
            lines.append("")
            lines.append(f"[mcp_servers.{q(name)}.http_headers]")
            for key, value in static.items():
                lines.append(f"{q(key)} = {q(value)}")

        if from_env:
            lines.append("")
            lines.append(f"[mcp_servers.{q(name)}.env_http_headers]")
            for key, value in from_env.items():
                lines.append(f"{q(key)} = {q(value)}")

        lines.append("")

    return "\n".join(lines)


def render_json(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


def render_cursor(data: dict) -> str:
    return render_json(rewrite_json_strings(data))


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def is_skill_dir(path: Path) -> bool:
    return path.is_dir() and (path / "SKILL.md").exists()


def list_skill_names(skills_root: Path) -> set[str]:
    if not skills_root.is_dir():
        return set()
    return {p.name for p in skills_root.iterdir() if is_skill_dir(p)}


def copy_skill_tree(src: Path, dest: Path) -> None:
    if dest.exists():
        return
    shutil.copytree(src, dest)


def ensure_symlink(link: Path, target: Path) -> None:
    target = target.resolve()
    rel = os.path.relpath(target, link.parent)
    if link.is_symlink():
        if link.resolve() == target:
            return
        link.unlink()
    elif link.exists():
        if link.is_dir():
            shutil.rmtree(link)
        else:
            link.unlink()
    link.symlink_to(rel)


def sync_skills(root: Path) -> None:
    canonical = (root / CANONICAL_SKILLS).resolve()
    canonical.mkdir(parents=True, exist_ok=True)

    skill_sources = [canonical] + [(root / rel).resolve() for rel in AGENT_SKILL_DIRS]
    names: set[str] = set()
    for skills_root in skill_sources:
        names |= list_skill_names(skills_root)

    for name in sorted(names):
        canonical_skill = canonical / name
        if not canonical_skill.exists():
            for skills_root in skill_sources:
                candidate = skills_root / name
                if is_skill_dir(candidate):
                    copy_skill_tree(candidate, canonical_skill)
                    print(f"Collected skill {name} into {CANONICAL_SKILLS}", file=sys.stderr)
                    break

    for rel in AGENT_SKILL_DIRS:
        agent_root = root / rel
        agent_root.mkdir(parents=True, exist_ok=True)
        for name in sorted(list_skill_names(canonical)):
            ensure_symlink(agent_root / name, canonical / name)
        print(f"Linked {rel} → {CANONICAL_SKILLS}")


def sync_agent_docs(root: Path) -> None:
    agents_path = root / "AGENTS.md"
    claude_path = root / "CLAUDE.md"

    chunks: list[str] = []
    if agents_path.exists():
        chunks.append(agents_path.read_text(encoding="utf-8").strip())

    if claude_path.exists():
        claude_text = claude_path.read_text(encoding="utf-8")
        stripped = claude_text.strip()
        if not CLAUDE_AGENTS_IMPORT.fullmatch(stripped):
            body = CLAUDE_AGENTS_IMPORT.sub("", claude_text).strip()
            if body:
                if not chunks or body not in chunks[0]:
                    chunks.append(body)

    if not chunks and not agents_path.exists() and not claude_path.exists():
        return

    consolidated = "\n\n".join(part for part in chunks if part)
    claude_stub = "@AGENTS.md\n"

    rendered = [
        (agents_path, consolidated + "\n"),
        (claude_path, claude_stub),
    ]
    for path, content in rendered:
        write_text(path, content)
        print(f"Updated {path.relative_to(root)}")


def sync_mcp(
    root: Path,
    source: Path,
    cursor_out: Path,
    codex_out: Path,
    mcp_out: Path,
    zcode_out: Path,
    qoder_out: Path,
) -> None:
    servers = merge_mcp_servers(root)
    if not servers:
        raise SystemExit(
            "No MCP configs found. Add .agents/mcp.json or another agent MCP file "
            "(.mcp.json, .cursor/mcp.json, .codex/config.toml, .zcode/config.json, "
            ".qoder/settings.json)."
        )

    data = {"mcpServers": servers}
    qoder_servers = {name: qoder_server_from_canonical(cfg) for name, cfg in servers.items()}

    # Render everything before writing anything: a rejected source must leave
    # the existing outputs untouched rather than half-regenerated.
    rendered = [
        (source, render_json(data)),
        (mcp_out, render_json({"mcpServers": qoder_servers})),
        (cursor_out, render_cursor(data)),
        (codex_out, render_codex(servers)),
        (zcode_out, render_zcode_config(servers, zcode_out)),
        (qoder_out, render_qoder_config(qoder_servers, qoder_out)),
    ]

    for path, content in rendered:
        write_text(path, content)
        display_path = path.relative_to(root) if path.is_relative_to(root) else path
        print(f"Generated {display_path}")


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
    assert "Authorization" not in toml
    # Authorization was the only header, so no http_headers table is emitted.
    assert "[mcp_servers.\"fns\".http_headers]" not in toml

    # Authorization: Bearer ${VAR} becomes Codex's native bearer_token_env_var.
    assert 'bearer_token_env_var = "FNS_API_KEY"' in toml

    # Explicit bearerTokenEnvVar wins and drops the redundant header.
    explicit = render_codex(
        {
            "fns": {
                "url": "https://example.invalid/mcp",
                "bearerTokenEnvVar": "FNS_API_KEY",
                "headers": {
                    "Authorization": "Bearer ${FNS_API_KEY}",
                    "Content-Type": "application/json",
                },
            }
        }
    )
    assert 'bearer_token_env_var = "FNS_API_KEY"' in explicit
    assert "Authorization" not in explicit
    assert '"Content-Type" = "application/json"' in explicit

    # Whole-value placeholders become env_http_headers (values are env var names).
    env_headers = render_codex(
        {
            "fns": {
                "url": "https://example.invalid/mcp",
                "headers": {"X-Api-Key": "${FNS_API_KEY}", "X-Client": "static"},
            }
        }
    )
    assert "[mcp_servers.\"fns\".env_http_headers]" in env_headers
    assert '"X-Api-Key" = "FNS_API_KEY"' in env_headers
    assert "[mcp_servers.\"fns\".http_headers]" in env_headers
    assert '"X-Client" = "static"' in env_headers
    assert "${FNS_API_KEY}" not in env_headers

    # Codex never expands ${VAR} inside http_headers: refuse to emit a literal.
    try:
        render_codex(
            {
                "fns": {
                    "url": "https://example.invalid/mcp",
                    "headers": {"Authorization": "Bearer ${FNS_API_KEY} extra"},
                }
            }
        )
    except SystemExit as exc:
        assert "does not expand" in str(exc)
    else:
        raise AssertionError("partial ${VAR} in http_headers must be rejected")

    # bearer_token_env_var is HTTP-only.
    try:
        render_codex({"local": {"command": "x", "bearerTokenEnvVar": "TOKEN"}})
    except SystemExit as exc:
        assert "HTTP-only" in str(exc)
    else:
        raise AssertionError("bearerTokenEnvVar without url must be rejected")

    # It names an env var, so it must be a non-empty string.
    for bad in (123, "", None):
        try:
            render_codex({"fns": {"url": "https://example.invalid/mcp", "bearerTokenEnvVar": bad}})
        except SystemExit as exc:
            assert "non-empty string" in str(exc), (bad, exc)
        else:
            raise AssertionError(f"bearerTokenEnvVar={bad!r} must be rejected")

    # Codex refuses to load a config with headers on a stdio server.
    try:
        render_codex(
            {"local": {"command": "x", "headers": {"X": "static"}}}
        )
    except SystemExit as exc:
        assert "only valid on an HTTP server" in str(exc)
    else:
        raise AssertionError("headers on a stdio server must be rejected")

    # Same, but the stdio server comes second: still no partial output.
    try:
        render_codex(
            {
                "http": {"url": "https://example.invalid/mcp"},
                "local": {"command": "x", "headers": {"X": "static"}},
            }
        )
    except SystemExit as exc:
        assert "only valid on an HTTP server" in str(exc)
    else:
        raise AssertionError("headers on a stdio server must be rejected")

    copied = render_json(
        {"mcpServers": {"fns": {"url": "https://example.invalid", "headers": {"A": "${TOKEN}"}}}}
    )
    assert "${TOKEN}" in copied
    assert "${env:TOKEN}" not in copied

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        (root / ".cursor").mkdir()
        (root / ".cursor" / "mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "only-cursor": {"command": "cursor-only", "type": "stdio"},
                        "shared": {"url": "https://cursor.invalid", "type": "http"},
                    }
                }
            ),
            encoding="utf-8",
        )
        (root / ".agents").mkdir()
        (root / ".agents" / "mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "shared": {"url": "https://agents.invalid", "type": "http"},
                    }
                }
            ),
            encoding="utf-8",
        )
        merged = merge_mcp_servers(root)
        assert merged["only-cursor"]["command"] == "cursor-only"
        assert merged["shared"]["url"] == "https://agents.invalid"

        (root / ".cursor" / "skills" / "demo-skill").mkdir(parents=True)
        (root / ".cursor" / "skills" / "demo-skill" / "SKILL.md").write_text("# demo\n", encoding="utf-8")
        write_text(root / ".qoder" / "skills" / "qoder-skill" / "SKILL.md", "# qoder\n")
        write_text(root / ".qoder" / "skills" / "shared-skill" / "SKILL.md", "# old\n")
        write_text(root / ".agents" / "skills" / "shared-skill" / "SKILL.md", "# canonical\n")
        sync_skills(root)
        assert (root / ".agents" / "skills" / "demo-skill" / "SKILL.md").is_file()
        assert (root / ".cursor" / "skills" / "demo-skill").is_symlink()
        qoder_skill = root / ".agents" / "skills" / "qoder-skill" / "SKILL.md"
        assert qoder_skill.is_file(), "Qoder-only skills must be collected"
        assert qoder_skill.read_text(encoding="utf-8") == "# qoder\n"
        for rel in (*AGENT_SKILL_DIRS, ".qoder/skills"):
            for name in ("demo-skill", "qoder-skill", "shared-skill"):
                link = root / rel / name
                assert link.is_symlink()
                assert not Path(os.readlink(link)).is_absolute()
                assert link.resolve() == (root / ".agents" / "skills" / name).resolve()
        assert (root / ".qoder" / "skills" / "shared-skill" / "SKILL.md").read_text(encoding="utf-8") == "# canonical\n"
        sync_skills(root)
        assert qoder_skill.read_text(encoding="utf-8") == "# qoder\n"

        (root / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
        (root / "CLAUDE.md").write_text("extra\n", encoding="utf-8")
        sync_agent_docs(root)
        assert "extra" in (root / "AGENTS.md").read_text(encoding="utf-8")
        assert (root / "CLAUDE.md").read_text(encoding="utf-8") == "@AGENTS.md\n"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = root / ".qoder" / "settings.json"
        qoder_servers = {
            "only-qoder": {"command": "qoder-only", "env": {"TOKEN": "${TOKEN}"}},
            "shared": {"command": "qoder-shared"},
        }
        write_text(settings, render_json({"mcpServers": qoder_servers, "language": "Chinese"}))
        assert merge_mcp_servers(root) == qoder_servers
        write_text(root / ".zcode" / "config.json", render_json({
            "mcp": {"servers": {"shared": {"command": "zcode-shared"}}},
        }))
        assert merge_mcp_servers(root)["shared"]["command"] == "qoder-shared"
        write_text(root / ".mcp.json", render_json({
            "mcpServers": {"shared": {"command": "claude-shared"}},
        }))
        assert merge_mcp_servers(root)["shared"]["command"] == "claude-shared"
        assert merge_mcp_servers(root)["only-qoder"]["env"]["TOKEN"] == "${TOKEN}"

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = root / ".qoder" / "settings.json"
        write_text(settings, render_json({"language": "Chinese"}))
        assert merge_mcp_servers(root) == {}
        for invalid in ([], {"mcpServers": None}, {"mcpServers": []}, {"mcpServers": {"bad": "x"}}):
            write_text(settings, json.dumps(invalid))
            try:
                merge_mcp_servers(root)
            except SystemExit as exc:
                assert str(settings) in str(exc)
            else:
                raise AssertionError("invalid Qoder MCP configuration must be rejected")

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = root / ".qoder" / "settings.json"
        write_text(settings, render_json({"language": "Chinese", "model": "keep-model"}))
        source = root / ".agents" / "mcp.json"
        write_text(source, render_json({"mcpServers": {
            "remote": {
                "type": "http", "url": "https://example.invalid/mcp",
                "bearerTokenEnvVar": "TOKEN",
                "headers": {"authorization": "Bearer ${OLD}", "X-Key": "${API_KEY}"},
            },
            "local": {"command": "demo", "args": ["${ARG}"], "env": {"TOKEN": "${TOKEN}"}},
        }}))
        command = [sys.executable, str(Path(__file__).resolve()), str(root), "--skip-skills", "--skip-docs"]
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        expected_servers = {
            "remote": {
                "type": "http", "url": "https://example.invalid/mcp",
                "headers": {"Authorization": "Bearer ${TOKEN}", "X-Key": "${API_KEY}"},
            },
            "local": {"command": "demo", "args": ["${ARG}"], "env": {"TOKEN": "${TOKEN}"}},
        }
        actual = json.loads(settings.read_text(encoding="utf-8"))
        assert actual.get("mcpServers") == expected_servers
        assert actual["language"] == "Chinese" and actual["model"] == "keep-model"
        assert json.loads((root / ".mcp.json").read_text(encoding="utf-8")) == {"mcpServers": expected_servers}
        assert json.loads(source.read_text(encoding="utf-8"))["mcpServers"]["remote"]["bearerTokenEnvVar"] == "TOKEN"
        assert not (root / ".qoder" / "skills").exists()
        assert not (root / "AGENTS.md").exists()

        paths = [source, settings, root / ".mcp.json", root / ".cursor" / "mcp.json",
                 root / ".codex" / "config.toml", root / ".zcode" / "config.json"]
        before = {path: path.read_bytes() for path in paths}
        result = subprocess.run(command, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert {path: path.read_bytes() for path in paths} == before

        custom = root / "custom-qoder.json"
        write_text(custom, render_json({"language": "English"}))
        result = subprocess.run(command + ["--qoder-out", str(custom)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert json.loads(custom.read_text(encoding="utf-8")) == {
            "language": "English", "mcpServers": expected_servers,
        }

        write_text(custom, "[]\n")
        before = {path: path.read_bytes() for path in paths + [custom]}
        result = subprocess.run(command + ["--qoder-out", str(custom)], capture_output=True, text=True)
        assert result.returncode != 0
        assert "must be a JSON object" in result.stderr
        assert {path: path.read_bytes() for path in paths + [custom]} == before

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "project"
        write_text(root / ".mcp.json", render_json({"mcpServers": {"local": {"command": "demo"}}}))
        custom = Path(tmp) / "qoder.json"
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), str(root), "--qoder-out", str(custom),
             "--skip-skills", "--skip-docs"], capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert json.loads(custom.read_text(encoding="utf-8")) == {
            "mcpServers": {"local": {"command": "demo"}},
        }
        assert not (root / ".qoder" / "settings.json").exists()

    print("self-test ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Merge MCP configs across agents, sync project skills under .agents/skills, "
            "and consolidate AGENTS.md / CLAUDE.md"
        )
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
    parser.add_argument("--zcode-out", type=Path)
    parser.add_argument("--qoder-out", type=Path)
    parser.add_argument("--skip-skills", action="store_true")
    parser.add_argument("--skip-docs", action="store_true")
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
    zcode_out = (args.zcode_out or root / ".zcode" / "config.json").resolve()
    qoder_out = (args.qoder_out or root / ".qoder" / "settings.json").resolve()

    sync_mcp(root, source, cursor_out, codex_out, mcp_out, zcode_out, qoder_out)
    if not args.skip_skills:
        sync_skills(root)
    if not args.skip_docs:
        sync_agent_docs(root)


if __name__ == "__main__":
    main()
