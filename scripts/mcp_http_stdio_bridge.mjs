#!/usr/bin/env node
/**
 * Lightweight MCP Streamable HTTP <-> stdio bridge without OAuth GET probing.
 *
 * Used by mcp_stdio_bridge when connecting to static-auth (Authorization / API
 * key headers) or loopback HTTP MCP servers so startup skips mcp-remote's
 * 10s + 5s OAuth discovery / auth-challenge GET timeouts.
 *
 * Usage:
 *   MCP_BRIDGE_HEADERS_JSON='{"Authorization":"Bearer ..."}' \
 *     node mcp_http_stdio_bridge.mjs <url> ["Header: value" ...]
 */
import readline from "node:readline";

const url = process.argv[2];
if (!url) {
  process.stderr.write("usage: mcp_http_stdio_bridge.mjs <url> [\"Header: value\" ...]\n");
  process.exit(2);
}

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

for (const raw of process.argv.slice(3)) {
  const idx = raw.indexOf(":");
  if (idx <= 0) continue;
  setHeader(raw.slice(0, idx), raw.slice(idx + 1).trim());
}

if (!hasHeader("Content-Type")) {
  setHeader("Content-Type", "application/json");
}
if (!hasHeader("Accept")) {
  setHeader("Accept", "application/json, text/event-stream");
}

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
  emitJson({
    jsonrpc: "2.0",
    id: msg.id,
    error: { code, message },
  });
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
  if (buffer.trim()) {
    emitSseEvent(buffer);
  }
}

async function forwardMessage(rawLine, msg) {
  const headers = { ...baseHeaders };
  if (sessionId) {
    headers["Mcp-Session-Id"] = sessionId;
  }

  let res;
  try {
    res = await fetch(url, {
      method: "POST",
      headers,
      body: rawLine,
    });
  } catch (err) {
    const detail = err?.cause?.message ? `${err.message}: ${err.cause.message}` : (err?.message || String(err));
    process.stderr.write(`mcp_http_stdio_bridge: POST ${url} failed: ${detail}\n`);
    emitRpcError(msg, `Network error: ${detail}`);
    return;
  }

  const nextSid = res.headers.get("mcp-session-id");
  if (nextSid) {
    sessionId = nextSid;
  }

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
    if (!res.ok) {
      emitRpcError(msg, `HTTP ${res.status} ${res.statusText}`.trim());
    }
    return;
  }

  try {
    const parsed = JSON.parse(text);
    const isRpc =
      (Array.isArray(parsed) && parsed.some((item) => item && typeof item === "object" && "jsonrpc" in item)) ||
      (parsed && typeof parsed === "object" && "jsonrpc" in parsed);
    if (isRpc) {
      emitJson(parsed);
      return;
    }
    if (res.ok) {
      emitJson(parsed);
      return;
    }
  } catch {
    // Non-JSON response; fall through to HTTP error reporting below.
  }

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

const rl = readline.createInterface({
  input: process.stdin,
  crlfDelay: Infinity,
});

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
    track(
      waitInit.finally(() => {}).then(() => forwardMessage(trimmed, msg))
    );
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
