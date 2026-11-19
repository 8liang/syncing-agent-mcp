#!/usr/bin/env node
/**
 * Unified MCP stdio <-> Streamable HTTP bridge and --workspace dispatcher.
 *
 * Handles all modes in a single Node process (avoiding python3 + multi-shell
 * startup latency):
 *   --expand "string with ${VAR} or ${env:VAR}"
 *   --workspace <server_name> [--fallback-http <url> ["Header: value" ...]]
 *   [--use-mcp-remote] <url> ["Header: value" ...]
 *
 * Static-auth HTTP servers (Authorization / API key headers) and loopback URLs
 * are forwarded directly over Streamable HTTP POST (zero OAuth GET probes).
 * Unauthenticated remote endpoints (OAuth2) or --use-mcp-remote /
 * MCP_BRIDGE_TRANSPORT=mcp-remote delegate to mcp-remote.
 */
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import readline from "node:readline";

const STOP_DIRS = new Set([
  "/",
  fs.realpathSync(os.homedir()),
  "/Users",
  "/home",
  "/tmp",
  "/private",
  "/private/tmp",
  "/var",
]);

const STATIC_AUTH_HEADERS = new Set([
  "authorization",
  "accesstoken",
  "token",
  "x-api-key",
  "api-key",
  "x-auth-token",
]);

function resolveReal(p) {
  try {
    return fs.realpathSync(p);
  } catch {
    return path.resolve(p);
  }
}

function expandHome(p) {
  if (p === "~") return os.homedir();
  if (p.startsWith("~/")) return path.join(os.homedir(), p.slice(2));
  return p;
}

function extractVarNames(str) {
  const names = [];
  const re = /\$\{(?:env:)?([^}]+)\}/g;
  let m;
  while ((m = re.exec(str)) !== null) {
    names.push(m[1]);
  }
  return names;
}

let cachedProfileEnv = null;
function loadProfileEnv() {
  if (cachedProfileEnv !== null) return cachedProfileEnv;
  cachedProfileEnv = {};
  const home = os.homedir();
  const envFile = path.join(home, ".config", "mcp-bridge.env");
  const zshenv = path.join(home, ".zshenv");
  if (!fs.existsSync(envFile) && !fs.existsSync(zshenv)) {
    return cachedProfileEnv;
  }
  const cmd =
    '{ [[ -f "$HOME/.config/mcp-bridge.env" ]] && source "$HOME/.config/mcp-bridge.env"; ' +
    '[[ -f "$HOME/.zshenv" ]] && source "$HOME/.zshenv"; } >/dev/null 2>&1; env -0';
  const res = spawnSync("zsh", ["-c", cmd], {
    env: process.env,
    encoding: "utf8",
    maxBuffer: 4 * 1024 * 1024,
  });
  if (res.status === 0 && res.stdout) {
    for (const entry of res.stdout.split("\0")) {
      const idx = entry.indexOf("=");
      if (idx > 0) {
        cachedProfileEnv[entry.slice(0, idx)] = entry.slice(idx + 1);
      }
    }
  }
  return cachedProfileEnv;
}

function expandTemplate(str, env) {
  const needed = extractVarNames(str);
  let profile = null;
  for (const name of needed) {
    if (!env[name]) {
      profile = loadProfileEnv();
      break;
    }
  }
  return str.replace(/\$\{(?:env:)?([^}]+)\}/g, (_match, name) => {
    if (env[name] !== undefined && env[name] !== "") return String(env[name]);
    if (profile && profile[name] !== undefined) return String(profile[name]);
    return "";
  });
}

function serveNoopMcp(serverName) {
  const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  rl.on("line", (raw) => {
    const line = raw.trim();
    if (!line) return;
    let msg;
    try {
      msg = JSON.parse(line);
    } catch {
      return;
    }
    if (!msg || typeof msg !== "object" || Array.isArray(msg) || !("id" in msg)) return;
    const reqId = msg.id;
    const method = msg.method || "";
    const params = msg.params && typeof msg.params === "object" && !Array.isArray(msg.params) ? msg.params : {};
    let result;
    if (method === "initialize") {
      const proto = typeof params.protocolVersion === "string" && params.protocolVersion ? params.protocolVersion : "2024-11-05";
      result = {
        protocolVersion: proto,
        capabilities: { tools: {} },
        serverInfo: { name: serverName, version: "0.0.0" },
      };
    } else if (method === "ping") {
      result = {};
    } else if (method === "tools/list") {
      result = { tools: [] };
    } else if (method === "resources/list") {
      result = { resources: [] };
    } else if (method === "resources/templates/list") {
      result = { resourceTemplates: [] };
    } else if (method === "prompts/list") {
      result = { prompts: [] };
    } else {
      process.stdout.write(
        JSON.stringify({
          jsonrpc: "2.0",
          id: reqId,
          error: { code: -32601, message: `Method not found: ${method}` },
        }) + "\n"
      );
      return;
    }
    process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: reqId, result }) + "\n");
  });
}

function spawnPassthrough(cmd, args, opts) {
  const child = spawn(cmd, args, {
    cwd: opts.cwd,
    env: opts.env,
    stdio: "inherit",
  });
  const forwardSig = (sig) => {
    try {
      child.kill(sig);
    } catch {}
  };
  process.on("SIGINT", forwardSig);
  process.on("SIGTERM", forwardSig);
  process.on("SIGHUP", forwardSig);
  child.on("error", (err) => {
    process.stderr.write(`mcp_stdio_bridge: failed to start ${cmd}: ${err.message}\n`);
    process.exit(127);
  });
  child.on("exit", (code, signal) => {
    if (signal) {
      process.kill(process.pid, signal);
    } else {
      process.exit(code ?? 0);
    }
  });
}

function findOnPath(binName, env) {
  const pathVal = env.PATH || "";
  for (const dir of pathVal.split(path.delimiter)) {
    if (!dir) continue;
    const candidate = path.join(dir, binName);
    try {
      fs.accessSync(candidate, fs.constants.X_OK);
      return candidate;
    } catch {}
  }
  return null;
}

function isLoopbackUrl(urlStr) {
  try {
    const u = new URL(urlStr);
    const host = u.hostname.toLowerCase();
    return host === "127.0.0.1" || host === "localhost" || host === "::1" || host === "[::1]";
  } catch {
    return false;
  }
}

function runDirectHttpBridge(url, headerPairs) {
  const baseHeaders = {};

  function setHeader(name, value) {
    const key = String(name).trim();
    if (!key) return;
    for (const existing of Object.keys(baseHeaders)) {
      if (existing.toLowerCase() === key.toLowerCase()) {
        delete baseHeaders[existing];
      }
    }
    baseHeaders[key] = String(value);
  }

  function hasHeader(name) {
    const lower = name.toLowerCase();
    return Object.keys(baseHeaders).some((k) => k.toLowerCase() === lower);
  }

  if (process.env.MCP_BRIDGE_HEADERS_JSON) {
    try {
      const parsed = JSON.parse(process.env.MCP_BRIDGE_HEADERS_JSON);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        for (const [k, v] of Object.entries(parsed)) {
          if (v !== undefined && v !== null) setHeader(k, v);
        }
      }
    } catch (err) {
      process.stderr.write(`mcp_http_stdio_bridge: invalid MCP_BRIDGE_HEADERS_JSON: ${err.message}\n`);
      process.exit(2);
    }
    delete process.env.MCP_BRIDGE_HEADERS_JSON;
  }

  const hdrCount = Number(process.env.MCP_BRIDGE_HDR_COUNT || "0");
  if (Number.isInteger(hdrCount) && hdrCount > 0) {
    for (let i = 0; i < hdrCount; i++) {
      const key = "MCP_BRIDGE_HDR_" + i;
      const raw = process.env[key];
      delete process.env[key];
      if (typeof raw !== "string") continue;
      const idx = raw.indexOf(":");
      if (idx <= 0) continue;
      setHeader(raw.slice(0, idx), raw.slice(idx + 1).trim());
    }
  }
  delete process.env.MCP_BRIDGE_HDR_COUNT;

  for (const raw of headerPairs) {
    const idx = raw.indexOf(":");
    if (idx <= 0) continue;
    setHeader(raw.slice(0, idx), raw.slice(idx + 1).trim());
  }

  if (!hasHeader("Content-Type")) setHeader("Content-Type", "application/json");
  if (!hasHeader("Accept")) setHeader("Accept", "application/json, text/event-stream");

  let sessionId = null;
  let stdoutClosed = false;

  process.stdout.on("error", (err) => {
    if (err && err.code === "EPIPE") {
      stdoutClosed = true;
      process.exit(0);
    }
    process.stderr.write(`mcp_http_stdio_bridge: stdout error: ${err?.message || err}\n`);
  });

  function emitJson(obj) {
    if (stdoutClosed || obj === undefined || obj === null) return;
    if (Array.isArray(obj)) {
      for (const item of obj) emitJson(item);
      return;
    }
    process.stdout.write(JSON.stringify(obj) + "\n");
  }

  function hasRpcId(msg) {
    return Boolean(msg && typeof msg === "object" && !Array.isArray(msg) && msg.id !== undefined && msg.id !== null);
  }

  function emitRpcError(msg, message, code = -32000) {
    if (!hasRpcId(msg)) return;
    emitJson({ jsonrpc: "2.0", id: msg.id, error: { code, message } });
  }

  function emitSseEvent(eventText) {
    const dataLines = [];
    for (const line of eventText.split(/\r?\n/)) {
      if (!line || line.startsWith(":")) continue;
      if (line.startsWith("data:")) {
        let data = line.slice(5);
        if (data.startsWith(" ")) data = data.slice(1);
        dataLines.push(data);
      }
    }
    if (!dataLines.length) return;
    const payload = dataLines.join("\n").trim();
    if (!payload || payload === "[DONE]") return;
    try {
      emitJson(JSON.parse(payload));
    } catch (err) {
      process.stderr.write(`mcp_http_stdio_bridge: ignoring non-JSON SSE payload: ${err.message}\n`);
    }
  }

  async function consumeSseStream(body) {
    if (!body) return;
    const decoder = new TextDecoder("utf-8");
    let buffer = "";
    for await (const chunk of body) {
      buffer += decoder.decode(chunk, { stream: true });
      let match;
      while ((match = /\r?\n\r?\n/.exec(buffer)) !== null) {
        const eventBlock = buffer.slice(0, match.index);
        buffer = buffer.slice(match.index + match[0].length);
        emitSseEvent(eventBlock);
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) emitSseEvent(buffer);
  }

  async function forwardMessage(rawLine, msg) {
    const headers = { ...baseHeaders };
    if (sessionId) headers["Mcp-Session-Id"] = sessionId;

    let res;
    try {
      res = await fetch(url, { method: "POST", headers, body: rawLine });
    } catch (err) {
      const detail = err?.cause?.message ? `${err.message}: ${err.cause.message}` : (err?.message || String(err));
      process.stderr.write(`mcp_http_stdio_bridge: POST ${url} failed: ${detail}\n`);
      emitRpcError(msg, `Network error: ${detail}`);
      return;
    }

    const nextSid = res.headers.get("mcp-session-id");
    if (nextSid) sessionId = nextSid;

    if (res.status === 202 || res.status === 204) {
      try {
        await res.body?.cancel();
      } catch {}
      return;
    }

    const contentType = (res.headers.get("content-type") || "").toLowerCase();
    if (res.ok && contentType.includes("text/event-stream")) {
      try {
        await consumeSseStream(res.body);
      } catch (err) {
        process.stderr.write(`mcp_http_stdio_bridge: SSE stream error: ${err?.message || err}\n`);
        emitRpcError(msg, `SSE stream error: ${err?.message || err}`);
      }
      return;
    }

    let text = "";
    try {
      text = (await res.text()).trim();
    } catch (err) {
      process.stderr.write(`mcp_http_stdio_bridge: failed reading response body: ${err?.message || err}\n`);
      emitRpcError(msg, `Response read error: ${err?.message || err}`);
      return;
    }

    if (!text) {
      if (!res.ok) emitRpcError(msg, `HTTP ${res.status} ${res.statusText}`.trim());
      return;
    }

    try {
      const parsed = JSON.parse(text);
      const isRpc =
        (Array.isArray(parsed) && parsed.some((item) => item && typeof item === "object" && "jsonrpc" in item)) ||
        (parsed && typeof parsed === "object" && "jsonrpc" in parsed);
      if (isRpc || res.ok) {
        emitJson(parsed);
        return;
      }
    } catch {}

    const snippet = text.replace(/\s+/g, " ").slice(0, 300);
    process.stderr.write(`mcp_http_stdio_bridge: HTTP ${res.status} from ${url}: ${snippet}\n`);
    emitRpcError(msg, `HTTP ${res.status}: ${snippet}`);
  }

  let initPromise = null;
  const inFlight = new Set();

  function track(promise) {
    inFlight.add(promise);
    promise.finally(() => inFlight.delete(promise));
    return promise;
  }

  const rl = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  rl.on("line", (line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    let msg;
    try {
      msg = JSON.parse(trimmed);
    } catch (err) {
      process.stderr.write(`mcp_http_stdio_bridge: invalid JSON on stdin: ${err.message}\n`);
      return;
    }
    const isInit = Boolean(msg && typeof msg === "object" && !Array.isArray(msg) && msg.method === "initialize");
    if (isInit) {
      const p = forwardMessage(trimmed, msg);
      initPromise = p;
      track(p);
      return;
    }
    if (initPromise) {
      const waitInit = initPromise;
      track(waitInit.finally(() => {}).then(() => forwardMessage(trimmed, msg)));
      return;
    }
    track(forwardMessage(trimmed, msg));
  });

  rl.on("close", async () => {
    if (inFlight.size > 0) {
      await Promise.race([
        Promise.allSettled(Array.from(inFlight)),
        new Promise((resolve) => setTimeout(resolve, 5000)),
      ]);
    }
    process.exit(0);
  });
}

function dispatchHttpMode(rawArgs, env, cwd) {
  let forceMcpRemote = false;
  let i = 0;
  if (rawArgs[0] === "--use-mcp-remote") {
    forceMcpRemote = true;
    i = 1;
  }
  const url = rawArgs[i];
  if (!url) {
    process.stderr.write("usage: mcp_stdio_bridge [--use-mcp-remote] <url> ['Header: value' ...]\n");
    process.exit(2);
  }
  const rawHeaders = rawArgs.slice(i + 1);
  const expandedHeaders = [];
  const remoteArgs = [url];
  let hasStaticAuth = false;

  for (const item of rawHeaders) {
    const expanded = expandTemplate(String(item), env);
    expandedHeaders.push(expanded);
    remoteArgs.push("--header", expanded);
    const colonIdx = expanded.indexOf(":");
    if (colonIdx > 0) {
      const key = expanded.slice(0, colonIdx).trim().toLowerCase();
      if (STATIC_AUTH_HEADERS.has(key)) hasStaticAuth = true;
    }
  }

  const transportPref = env.MCP_BRIDGE_TRANSPORT || "auto";
  const useDirect =
    !forceMcpRemote &&
    transportPref !== "mcp-remote" &&
    (transportPref === "direct" || hasStaticAuth || isLoopbackUrl(url));

  if (useDirect) {
    runDirectHttpBridge(url, expandedHeaders);
    return;
  }

  const mcpRemoteBin = findOnPath("mcp-remote", env);
  if (mcpRemoteBin) {
    spawnPassthrough(mcpRemoteBin, remoteArgs, { cwd, env });
  } else {
    spawnPassthrough("npx", ["-y", "mcp-remote", ...remoteArgs], { cwd, env });
  }
}

function runWorkspaceMode(args, bridgePath) {
  if (!args.length || !args[0] || args[0].startsWith("-")) {
    process.stderr.write(
      'usage: mcp_stdio_bridge --workspace <server_name> [--fallback-http <url> ["Header: value" ...]]\n'
    );
    process.exit(2);
  }
  const serverName = args[0];
  const rest = args.slice(1);
  let fallbackUrl = null;
  let fallbackHeaders = [];
  if (rest.length > 0) {
    if (rest[0] === "--fallback-http" && rest.length >= 2) {
      fallbackUrl = rest[1];
      fallbackHeaders = rest.slice(2);
    } else {
      process.stderr.write(
        'usage: mcp_stdio_bridge --workspace <server_name> [--fallback-http <url> ["Header: value" ...]]\n'
      );
      process.exit(2);
    }
  }

  const rawCwdStr = process.env.MCP_WORKSPACE_DIR || process.cwd();
  const cwd = resolveReal(rawCwdStr);

  let workspaceDir = null;
  let workspaceCfg = null;
  let cur = cwd;
  while (true) {
    if (STOP_DIRS.has(cur)) break;
    const cfgFile = path.join(cur, ".agents", "mcp_config.json");
    if (fs.existsSync(cfgFile) && fs.statSync(cfgFile).isFile()) {
      workspaceDir = cur;
      workspaceCfg = cfgFile;
      break;
    }
    const parent = path.dirname(cur);
    if (parent === cur) break;
    cur = parent;
  }

  if (workspaceCfg && workspaceDir) {
    let data;
    try {
      data = JSON.parse(fs.readFileSync(workspaceCfg, "utf8"));
    } catch (err) {
      process.stderr.write(`mcp_stdio_bridge: failed to parse ${workspaceCfg}: ${err.message}\n`);
      serveNoopMcp(serverName);
      return;
    }
    const servers = data && typeof data === "object" ? data.mcpServers : null;
    const entry = servers && typeof servers === "object" ? servers[serverName] : null;
    if (!entry || typeof entry !== "object" || Array.isArray(entry) || entry.disabled === true) {
      serveNoopMcp(serverName);
      return;
    }

    const childEnv = { ...process.env };
    if (entry.env && typeof entry.env === "object" && !Array.isArray(entry.env)) {
      for (const [k, v] of Object.entries(entry.env)) {
        childEnv[String(k)] = String(v);
      }
    }

    const rawEntryCwd = typeof entry.cwd === "string" && entry.cwd.trim() ? expandHome(entry.cwd.trim()) : workspaceDir;
    const targetCwd = rawEntryCwd;
    try {
      process.chdir(targetCwd);
    } catch {}

    const cmd = entry.command;
    if (typeof cmd === "string" && cmd) {
      const cmdArgs = (Array.isArray(entry.args) ? entry.args : []).filter((a) => a !== null && a !== undefined).map(String);
      if (path.basename(cmd) === path.basename(bridgePath)) {
        if (cmdArgs[0] === "--workspace") {
          process.stderr.write(`mcp_stdio_bridge: ignoring recursive --workspace entry in ${workspaceCfg}\n`);
          serveNoopMcp(serverName);
          return;
        }
        // Handle bundled bridge directly in-process (no extra shell/node hop).
        if (cmdArgs[0] === "--expand") {
          process.stdout.write(expandTemplate(cmdArgs[1] || "", childEnv) + "\n");
          return;
        }
        dispatchHttpMode(cmdArgs, childEnv, targetCwd);
        return;
      }
      spawnPassthrough(cmd, cmdArgs, { cwd: targetCwd, env: childEnv });
      return;
    }

    const url = entry.serverUrl || entry.url;
    if (typeof url === "string" && url.trim()) {
      const hdrs = entry.headers && typeof entry.headers === "object" && !Array.isArray(entry.headers) ? entry.headers : {};
      const hdrArgs = Object.entries(hdrs).map(([k, v]) => `${k}: ${v}`);
      dispatchHttpMode([url.trim(), ...hdrArgs], childEnv, targetCwd);
      return;
    }

    serveNoopMcp(serverName);
    return;
  }

  const isGuiRoot = cwd === "/" || rawCwdStr === "/" || cwd.startsWith("/Applications/");
  if (isGuiRoot && fallbackUrl) {
    dispatchHttpMode([fallbackUrl, ...fallbackHeaders], { ...process.env }, cwd);
    return;
  }

  serveNoopMcp(serverName);
}

// CLI entrypoint
let argv = process.argv.slice(2);
let bridgePath = path.join(path.dirname(resolveReal(process.argv[1])), "mcp_stdio_bridge");
if (argv[0] === "--bridge-path" && argv.length >= 2) {
  bridgePath = argv[1];
  argv = argv.slice(2);
}

if (argv[0] === "--expand") {
  if (argv.length < 2) {
    process.stderr.write("usage: mcp_stdio_bridge --expand <template>\n");
    process.exit(2);
  }
  process.stdout.write(expandTemplate(argv[1], { ...process.env }) + "\n");
  process.exit(0);
}

if (argv[0] === "--workspace") {
  runWorkspaceMode(argv.slice(1), bridgePath);
} else {
  dispatchHttpMode(argv, { ...process.env }, process.cwd());
}
