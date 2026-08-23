import { spawn } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const HOOK_NAME = "eve-evidence-ingest";
const SELF_ORIGIN_MARKER = "eve-openclaw-evidence-ingest";
const DEFAULT_DEBOUNCE_MS = 15_000;
const MAX_STATE_ENTRIES = 200;
const MAX_STATE_ENTRY_AGE_MS = 60 * 60 * 1000;

function resolveEveRoot(event) {
  const workspaceDir = event?.context?.workspaceDir;
  if (typeof workspaceDir === "string" && workspaceDir.trim()) {
    return path.resolve(workspaceDir, "..");
  }
  if (process.env.EVE_PROJECT_ROOT && process.env.EVE_PROJECT_ROOT.trim()) {
    return process.env.EVE_PROJECT_ROOT.trim();
  }
  return path.join(os.homedir(), ".eve_runtime");
}

function resolveDebounceMs() {
  const raw = Number(process.env.EVE_OPENCLAW_HOOK_DEBOUNCE_MS || "");
  if (!Number.isFinite(raw) || raw < 1000) return DEFAULT_DEBOUNCE_MS;
  return Math.min(raw, 5 * 60 * 1000);
}

function resolveStatePath(eveRoot) {
  if (process.env.EVE_OPENCLAW_HOOK_STATE_PATH?.trim()) {
    return path.resolve(process.env.EVE_OPENCLAW_HOOK_STATE_PATH.trim());
  }
  return path.join(eveRoot, ".eve", "openclaw_hook_ingest_state.json");
}

function normalizeTimestamp(value) {
  if (value instanceof Date) return value.toISOString();
  if (typeof value === "string" && value.trim()) return value.trim();
  return "";
}

function markerMatches(value) {
  return typeof value === "string" && value.toLowerCase().includes(SELF_ORIGIN_MARKER);
}

function isEveOriginatedEvent(event) {
  const context = event?.context;
  if (!context || typeof context !== "object") return false;
  if (context.eveEvidenceIngest === true || context.eveOpenClawEvidenceIngest === true) return true;

  const keys = [
    "source",
    "origin",
    "initiator",
    "senderId",
    "commandSource",
    "requester",
    "requesterId",
    "userAgent",
  ];
  for (const key of keys) {
    if (markerMatches(context[key])) return true;
  }

  const env = context.env || context.processEnv;
  if (env && typeof env === "object") {
    if (env.EVE_OPENCLAW_EVIDENCE_INGEST === "1") return true;
    if (markerMatches(env.EVE_OPENCLAW_HOOK_SOURCE)) return true;
  }

  return markerMatches(event?.sessionKey);
}

function shouldIngest(event) {
  if (!event || typeof event !== "object") return false;
  if (isEveOriginatedEvent(event)) return false;
  if (event.type === "gateway" && event.action === "startup") return true;
  if (event.type === "command") return true;
  return false;
}

function buildFingerprint(event) {
  const context = event?.context && typeof event.context === "object" ? event.context : {};
  const stable = {
    type: event?.type || "",
    action: event?.action || "",
    sessionKey: event?.sessionKey || "",
    commandSource: context.commandSource || "",
    senderId: context.senderId || "",
    sessionId: context.sessionEntry?.sessionId || context.sessionId || "",
  };
  return crypto.createHash("sha256").update(JSON.stringify(stable)).digest("hex");
}

async function readState(statePath) {
  try {
    const raw = await fs.readFile(statePath, "utf-8");
    const parsed = JSON.parse(raw);
    if (parsed && typeof parsed === "object" && Array.isArray(parsed.events)) {
      return parsed;
    }
  } catch {}
  return { version: 1, events: [] };
}

async function writeState(statePath, state) {
  await fs.mkdir(path.dirname(statePath), { recursive: true });
  const tmpPath = `${statePath}.${process.pid}.${Date.now()}.tmp`;
  await fs.writeFile(tmpPath, JSON.stringify(state, null, 2), "utf-8");
  await fs.rename(tmpPath, statePath);
}

async function rememberIfAllowed(event, eveRoot) {
  const now = Date.now();
  const debounceMs = resolveDebounceMs();
  const statePath = resolveStatePath(eveRoot);
  const fingerprint = buildFingerprint(event);
  const state = await readState(statePath);
  const recent = state.events
    .filter((entry) => entry && typeof entry === "object")
    .filter((entry) => Number.isFinite(entry.lastSeenMs) && now - entry.lastSeenMs <= MAX_STATE_ENTRY_AGE_MS);
  const existing = recent.find((entry) => entry.fingerprint === fingerprint);
  if (existing && now - existing.lastSeenMs < debounceMs) {
    existing.lastSeenMs = now;
    existing.skipped = Number(existing.skipped || 0) + 1;
    state.events = recent.slice(-MAX_STATE_ENTRIES);
    await writeState(statePath, state);
    return false;
  }

  recent.push({
    fingerprint,
    type: event?.type || "",
    action: event?.action || "",
    sessionKey: event?.sessionKey || "",
    timestamp: normalizeTimestamp(event?.timestamp),
    lastSeenMs: now,
    skipped: 0,
  });
  state.events = recent.slice(-MAX_STATE_ENTRIES);
  state.updatedAt = new Date(now).toISOString();
  state.hook = HOOK_NAME;
  await writeState(statePath, state);
  return true;
}

function serializeEvent(event) {
  return {
    ...event,
    timestamp: normalizeTimestamp(event?.timestamp),
    context: {
      ...(event?.context && typeof event.context === "object" ? event.context : {}),
      eveEvidenceObservedBy: HOOK_NAME,
    },
  };
}

function safeStringifyEvent(value) {
  const seen = new WeakSet();
  return JSON.stringify(
    value,
    (_key, entry) => {
      if (typeof entry === "bigint") return entry.toString();
      if (typeof entry === "function") return `[Function ${entry.name || "anonymous"}]`;
      if (typeof entry === "symbol") return entry.toString();
      if (entry && typeof entry === "object") {
        if (seen.has(entry)) return "[Circular]";
        seen.add(entry);
      }
      return entry;
    },
    2,
  );
}

export default async function ingestEveEvidence(event) {
  if (!shouldIngest(event)) return;

  const eveRoot = resolveEveRoot(event);
  if (!(await rememberIfAllowed(event, eveRoot))) return;

  const spoolDir = path.join(os.tmpdir(), "eve-openclaw-hook-events");
  await fs.mkdir(spoolDir, { recursive: true });
  const eventPath = path.join(
    spoolDir,
    `openclaw-hook-${Date.now()}-${process.pid}-${Math.random().toString(16).slice(2)}.json`,
  );
  await fs.writeFile(
    eventPath,
    safeStringifyEvent(serializeEvent(event)),
    "utf-8",
  );

  const child = spawn(
    "python3",
    [
      path.join(eveRoot, "eve.py"),
      "openclaw",
      "evidence",
      "--record-hook-event",
      eventPath,
      "--ingest-activity",
      "--activity-limit",
      "10",
      "--limit",
      "6",
    ],
    {
      cwd: eveRoot,
      detached: true,
      stdio: "ignore",
      env: {
        ...process.env,
        EVE_OPENCLAW_EVIDENCE_INGEST: "1",
        EVE_OPENCLAW_HOOK_SOURCE: SELF_ORIGIN_MARKER,
        EVE_PROJECT_ROOT: eveRoot,
      },
    },
  );
  child.unref();
}

export const __eveEvidenceIngestTest = {
  buildFingerprint,
  isEveOriginatedEvent,
  rememberIfAllowed,
  resolveDebounceMs,
  resolveStatePath,
  serializeEvent,
  safeStringifyEvent,
  shouldIngest,
};
