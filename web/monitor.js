const state = {
  paused: false,
  loading: false,
  substrateStream: "evidence",
  lastPayload: null,
  lastRefreshAt: null,
  pressureHistory: [],
};

const nodes = {
  generatedLine: document.querySelector("#generatedLine"),
  pauseBtn: document.querySelector("#pauseBtn"),
  refreshBtn: document.querySelector("#refreshBtn"),
  daemonState: document.querySelector("#daemonState"),
  runtimeDir: document.querySelector("#runtimeDir"),
  lanesReady: document.querySelector("#lanesReady"),
  laneSummary: document.querySelector("#laneSummary"),
  peakPressure: document.querySelector("#peakPressure"),
  peakPressureLabel: document.querySelector("#peakPressureLabel"),
  threadCounts: document.querySelector("#threadCounts"),
  unreadCounts: document.querySelector("#unreadCounts"),
  replyState: document.querySelector("#replyState"),
  replyDetail: document.querySelector("#replyDetail"),
  workspaceUpdated: document.querySelector("#workspaceUpdated"),
  workspaceSummary: document.querySelector("#workspaceSummary"),
  currentExperience: document.querySelector("#currentExperience"),
  continuityList: document.querySelector("#continuityList"),
  readinessList: document.querySelector("#readinessList"),
  surpriseList: document.querySelector("#surpriseList"),
  consequenceList: document.querySelector("#consequenceList"),
  modelUpdated: document.querySelector("#modelUpdated"),
  laneList: document.querySelector("#laneList"),
  regulationMode: document.querySelector("#regulationMode"),
  pulsePath: document.querySelector("#pulsePath"),
  pressureList: document.querySelector("#pressureList"),
  replyTurnCount: document.querySelector("#replyTurnCount"),
  replyTurnList: document.querySelector("#replyTurnList"),
  autonomyStage: document.querySelector("#autonomyStage"),
  autonomyFocus: document.querySelector("#autonomyFocus"),
  autonomyThreads: document.querySelector("#autonomyThreads"),
  runList: document.querySelector("#runList"),
  substrateFeed: document.querySelector("#substrateFeed"),
  actionCount: document.querySelector("#actionCount"),
  actionsTimeline: document.querySelector("#actionsTimeline"),
  systemTasks: document.querySelector("#systemTasks"),
  attentionCount: document.querySelector("#attentionCount"),
  threadAttention: document.querySelector("#threadAttention"),
  segments: Array.from(document.querySelectorAll(".segment")),
};

async function api(path) {
  const response = await fetch(path, { cache: "no-store" });
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || "Request failed");
  }
  return payload.data;
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function asObject(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

function compact(value, fallback = "No signal recorded.", length = 180) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  if (!text) return fallback;
  return text.length > length ? `${text.slice(0, length - 1).trim()}...` : text;
}

function number(value, fallback = 0) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function formatDate(value) {
  if (!value) return "Unknown";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatShortTime(value) {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "never";
  return date.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatLatency(value) {
  const ms = number(value, 0);
  if (!ms) return "n/a";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)} s`;
}

function formatBytes(value) {
  const bytes = number(value, 0);
  if (!bytes) return "";
  const gib = bytes / 1024 / 1024 / 1024;
  if (gib >= 1) return `${gib.toFixed(1)} GiB`;
  return `${Math.round(bytes / 1024 / 1024)} MiB`;
}

function clear(node) {
  node.replaceChildren();
}

function emptyLine(text) {
  const item = document.createElement("div");
  item.className = "feed-item";
  const strong = document.createElement("strong");
  strong.textContent = text;
  item.append(strong);
  return item;
}

function listItems(node, items, fallback) {
  clear(node);
  const values = asArray(items).filter(Boolean).slice(0, 5);
  if (!values.length) {
    const li = document.createElement("li");
    li.textContent = fallback;
    node.append(li);
    return;
  }
  values.forEach((value) => {
    const li = document.createElement("li");
    li.textContent = compact(value, "No detail.", 220);
    node.append(li);
  });
}

function tag(text, tone = "") {
  const span = document.createElement("span");
  span.className = tone ? `mini-tag ${tone}` : "mini-tag";
  span.textContent = text;
  return span;
}

function badge(text, tone = "") {
  const span = document.createElement("span");
  span.className = tone ? `status-badge ${tone}` : "status-badge";
  span.textContent = text;
  return span;
}

function statusTone(ok, warn = false) {
  if (ok) return "";
  return warn ? "warn" : "bad";
}

function latencyTone(ms) {
  if (!ms) return "warn";
  if (ms > 8000) return "bad";
  if (ms > 2500) return "warn";
  return "";
}

function normalizeLanes(modelHealth) {
  const lanes = asArray(modelHealth.lanes);
  if (lanes.length) {
    return lanes.map((lane) => {
      const laneId = lane.lane || lane.name || lane.label || "lane";
      return {
        id: laneId,
        label: lane.label || laneId,
        model: lane.model || lane.effective_model || lane.visible_model || laneId,
        host: lane.host || "",
        loaded: Boolean(lane.loaded ?? lane.ok),
        latency_ms: number(lane.latency_ms ?? lane.wall_ms, 0),
        backend: lane.backend || "",
      };
    });
  }

  const probes = asObject(modelHealth.probes);
  return asArray(modelHealth.loaded_models).map((model) => {
    const name = model.name || "model";
    const probe = asObject(probes[name]);
    return {
      id: name,
      label: name,
      model: name,
      host: model.host || "",
      loaded: true,
      latency_ms: number(probe.wall_ms, 0),
      backend: model.backend || "llama_cpp",
      size_vram: model.size_vram,
      context_length: model.context_length,
    };
  });
}

function renderHeader(payload) {
  const status = asObject(payload.status);
  const daemon = asObject(status.daemon);
  const generated = payload.generated_at || new Date().toISOString();
  const refreshText = state.paused ? "Paused" : `Live at ${formatShortTime(generated)}`;
  nodes.generatedLine.textContent = `${refreshText} | API ${status.api_version || "?"}`;
  document.body.dataset.live = "live";

  if (daemon.awake) {
    nodes.daemonState.textContent = "Awake";
  } else if (daemon.running) {
    nodes.daemonState.textContent = "Running";
  } else {
    nodes.daemonState.textContent = "Sleeping";
  }
  nodes.runtimeDir.textContent = compact(daemon.runtime_dir, "Runtime directory unknown.", 82);
}

function renderMetrics(payload) {
  const status = asObject(payload.status);
  const counts = asObject(status.counts);
  const modelHealth = asObject(status.model_health);
  const lanes = normalizeLanes(modelHealth);
  const ready = lanes.filter((lane) => lane.loaded).length;
  const pressures = asArray(asObject(payload.homeostasis).pressures);
  const peak = pressures.reduce((best, item) => (number(item.level) > number(best.level) ? item : best), {});
  const activeReply = asObject(status.active_reply);

  nodes.lanesReady.textContent = `${ready} / ${lanes.length}`;
  nodes.laneSummary.textContent = compact(modelHealth.summary, "No model health summary.", 90);
  nodes.peakPressure.textContent = String(number(peak.level, 0));
  nodes.peakPressureLabel.textContent = peak.label ? `${peak.label} | ${peak.trend || "steady"}` : "No pressure data";
  nodes.threadCounts.textContent = `${number(counts.active_threads)} active`;
  nodes.unreadCounts.textContent = `${number(counts.unread_messages)} unread | ${number(counts.waiting_threads)} waiting`;

  if (activeReply.id) {
    nodes.replyState.textContent = activeReply.phase || activeReply.status || "Working";
    nodes.replyDetail.textContent = compact(activeReply.detail || activeReply.title, "Reply in progress.", 92);
  } else {
    nodes.replyState.textContent = "Idle";
    nodes.replyDetail.textContent = "No active reply";
  }
}

function renderWorkspace(payload) {
  const workspace = asObject(payload.workspace);
  nodes.workspaceUpdated.textContent = workspace.updated_at ? formatShortTime(workspace.updated_at) : "Not refreshed";
  nodes.workspaceSummary.textContent = compact(workspace.summary, "Waiting for the global workspace.", 420);
  nodes.currentExperience.textContent = compact(workspace.current_experience, "Current experience will appear here.", 520);
  listItems(nodes.continuityList, workspace.continuity_threads, "No continuity threads.");
  listItems(nodes.readinessList, workspace.action_readiness || workspace.next_refresh, "No readiness signals.");
  listItems(nodes.surpriseList, workspace.surprise_signals, "No surprise signals.");
  listItems(nodes.consequenceList, workspace.consequence_trace, "No consequence trace.");
}

function renderLanes(payload) {
  const modelHealth = asObject(asObject(payload.status).model_health);
  const lanes = normalizeLanes(modelHealth);
  nodes.modelUpdated.textContent = modelHealth.updated_at ? formatShortTime(modelHealth.updated_at) : "No checks";
  clear(nodes.laneList);
  if (!lanes.length) {
    nodes.laneList.append(emptyLine("No lane records available."));
    return;
  }

  lanes.forEach((lane) => {
    const row = document.createElement("div");
    row.className = "lane-row";

    const copy = document.createElement("div");
    copy.className = "lane-title";
    const title = document.createElement("strong");
    title.textContent = lane.label;
    const detail = document.createElement("span");
    const extra = [lane.backend, lane.host, formatBytes(lane.size_vram)].filter(Boolean).join(" | ");
    detail.textContent = compact(`${lane.model || lane.id}${extra ? ` | ${extra}` : ""}`, "No model detail.", 140);
    copy.append(title, detail);

    const meta = document.createElement("div");
    meta.className = "lane-meta";
    meta.append(badge(lane.loaded ? "ready" : "down", statusTone(lane.loaded)));
    const bar = document.createElement("div");
    bar.className = "latency-bar";
    bar.title = formatLatency(lane.latency_ms);
    const fill = document.createElement("span");
    fill.style.setProperty("--bar", `${Math.min(100, Math.max(5, lane.latency_ms / 90))}%`);
    bar.append(fill);
    const latency = document.createElement("span");
    latency.textContent = formatLatency(lane.latency_ms);
    meta.append(bar, latency);

    row.append(copy, meta);
    nodes.laneList.append(row);
  });
}

function renderPressure(payload) {
  const homeostasis = asObject(payload.homeostasis);
  const pressures = asArray(homeostasis.pressures);
  nodes.regulationMode.textContent = homeostasis.regulation_mode || "unknown";
  clear(nodes.pressureList);

  const peak = pressures.reduce((max, pressure) => Math.max(max, number(pressure.level, 0)), 0);
  state.pressureHistory.push(peak);
  state.pressureHistory = state.pressureHistory.slice(-18);
  drawPulse(state.pressureHistory);

  if (!pressures.length) {
    nodes.pressureList.append(emptyLine("No homeostasis pressures available."));
    return;
  }

  pressures.slice(0, 8).forEach((pressure) => {
    const level = Math.max(0, Math.min(100, number(pressure.level, 0)));
    const row = document.createElement("div");
    row.className = "pressure-row";
    const top = document.createElement("div");
    top.className = "pressure-top";
    const name = document.createElement("strong");
    name.textContent = pressure.label || pressure.id || "pressure";
    const value = document.createElement("span");
    value.textContent = `${level} | ${pressure.trend || "steady"}`;
    top.append(name, value);
    const track = document.createElement("div");
    track.className = "pressure-track";
    const fill = document.createElement("span");
    fill.className = level >= 80 ? "bad" : level >= 55 ? "warn" : "";
    fill.style.setProperty("--pressure", `${level}%`);
    track.append(fill);
    const reason = document.createElement("span");
    reason.textContent = compact(pressure.reason, "No reason recorded.", 160);
    row.append(top, track, reason);
    nodes.pressureList.append(row);
  });
}

function drawPulse(values) {
  if (!values.length) {
    nodes.pulsePath.setAttribute("d", "");
    return;
  }
  const width = 320;
  const height = 84;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const points = values.map((value, index) => {
    const x = index * step;
    const y = height - 10 - (Math.max(0, Math.min(100, value)) / 100) * (height - 20);
    return `${index === 0 ? "M" : "L"} ${x.toFixed(1)} ${y.toFixed(1)}`;
  });
  nodes.pulsePath.setAttribute("d", points.join(" "));
}

function renderAutonomy(payload) {
  const autonomy = asObject(payload.autonomy);
  const autonomyState = asObject(autonomy.state);
  const agenda = asObject(autonomy.agenda);
  const runs = asArray(autonomy.runs);

  nodes.autonomyStage.textContent = autonomyState.stage || "observe";
  nodes.autonomyFocus.textContent = compact(agenda.current_focus || agenda.summary, "No autonomy agenda loaded.", 300);
  clear(nodes.autonomyThreads);

  const threads = asArray(agenda.active_threads).slice(0, 4);
  if (!threads.length) {
    nodes.autonomyThreads.append(emptyLine("No active autonomy threads."));
  } else {
    threads.forEach((thread) => {
      const item = document.createElement("div");
      item.className = "thread-item";
      const top = document.createElement("div");
      top.className = "thread-top";
      const title = document.createElement("strong");
      title.textContent = thread.title || "Autonomy thread";
      top.append(title, tag(thread.family || "thread"));
      const detail = document.createElement("span");
      detail.textContent = compact(thread.why || thread.evidence, "No thread detail.", 180);
      item.append(top, detail);
      nodes.autonomyThreads.append(item);
    });
  }

  clear(nodes.runList);
  if (!runs.length) {
    nodes.runList.append(emptyLine("No autonomy runs recorded."));
    return;
  }
  runs.slice(0, 2).forEach((run) => {
    const item = document.createElement("div");
    item.className = "run-item";
    const top = document.createElement("div");
    top.className = "run-top";
    const title = document.createElement("strong");
    title.textContent = run.run_id || "autonomy run";
    const supervisor = asObject(run.supervisor);
    top.append(title, tag(`${supervisor.verdict || "unknown"} ${supervisor.score || 0}`, supervisor.score < 55 ? "warn" : ""));
    const detail = document.createElement("span");
    detail.textContent = compact(run.objective || `${run.action_count} actions`, "No run detail.", 190);
    item.append(top, detail);
    nodes.runList.append(item);
  });
}

function renderSubstrate(payload) {
  const substrate = asObject(payload.substrate);
  const records = asArray(substrate[state.substrateStream]);
  const runtimeTruth = asObject(payload.runtime_source_truth);
  clear(nodes.substrateFeed);
  if (state.substrateStream === "evidence" && runtimeTruth.status) {
    const truthItem = document.createElement("div");
    truthItem.className = "feed-item runtime-truth";
    const top = document.createElement("div");
    top.className = "feed-top";
    const title = document.createElement("strong");
    title.textContent = "Runtime source truth";
    top.append(title, tag(runtimeTruth.status, runtimeTruth.needs_runtime_sync ? "warn" : ""));
    const detail = document.createElement("span");
    detail.textContent = runtimeTruth.needs_runtime_sync
      ? "Runtime bundle differs from source; sync before trusting live behavior."
      : "Runtime bundle matches source for monitored Python entrypoints.";
    truthItem.append(top, detail);
    nodes.substrateFeed.append(truthItem);
  }
  if (!records.length) {
    nodes.substrateFeed.append(emptyLine(`No ${state.substrateStream} records.`));
    return;
  }

  records.slice(0, 8).forEach((record) => {
    const item = document.createElement("div");
    item.className = "feed-item";
    const top = document.createElement("div");
    top.className = "feed-top";
    const title = document.createElement("strong");
    const status = record.status || record.event_type || record.kind || "record";
    title.textContent =
      record.claim ||
      record.text ||
      record.what_happened ||
      record.summary ||
      record.subject ||
      "Substrate record";
    top.append(title, tag(status, record.status === "blocked" || record.status === "capability_gap" ? "warn" : ""));

    const detail = document.createElement("span");
    if (state.substrateStream === "evidence") {
      detail.textContent = `${formatShortTime(record.observed_at)} | freshness ${record.freshness || 0} | ${compact(record.summary, "", 160)}`;
    } else if (state.substrateStream === "commitments") {
      detail.textContent = `${formatShortTime(record.updated_at)} | ${compact(record.result_summary || record.verification || record.action, "", 180)}`;
    } else if (state.substrateStream === "corrections") {
      detail.textContent = `${formatShortTime(record.created_at)} | ${record.issue_type || "correction"} | ${compact(record.summary, "", 180)}`;
    } else if (state.substrateStream === "episodes") {
      detail.textContent = `${formatShortTime(record.created_at)} | You cared about: ${compact(record.what_user_cared_about, "not recorded", 160)}`;
    } else {
      detail.textContent = `${formatShortTime(record.timestamp)} | ${record.actor || "eve"} | ${compact(record.summary, "", 180)}`;
    }
    item.append(top, detail);
    nodes.substrateFeed.append(item);
  });
}

function renderActions(payload) {
  const operations = asObject(payload.operations);
  const actions = asArray(operations.actions);
  const systemTasks = asArray(operations.system_tasks);
  nodes.actionCount.textContent = `${actions.length} actions`;
  clear(nodes.actionsTimeline);
  clear(nodes.systemTasks);

  if (!actions.length) {
    nodes.actionsTimeline.append(emptyLine("No recent action executions."));
  } else {
    actions.slice(0, 9).forEach((action) => {
      const item = document.createElement("div");
      item.className = "timeline-item";
      const top = document.createElement("div");
      top.className = "timeline-top";
      const title = document.createElement("strong");
      title.textContent = action.action || "action";
      const ok = Boolean(action.verification_ok || action.result_ok);
      top.append(title, tag(ok ? "verified" : "check", ok ? "" : "warn"));
      const detail = document.createElement("span");
      detail.textContent = `${formatShortTime(action.updated_at || action.created_at)} | ${compact(action.summary, "No action summary.", 220)}`;
      item.append(top, detail);
      nodes.actionsTimeline.append(item);
    });
  }

  if (!systemTasks.length) {
    nodes.systemTasks.append(emptyLine("No system tasks."));
    return;
  }

  systemTasks.slice(0, 4).forEach((task) => {
    const item = document.createElement("div");
    item.className = "timeline-item";
    const top = document.createElement("div");
    top.className = "timeline-top";
    const title = document.createElement("strong");
    title.textContent = task.title || task.kind || "system task";
    top.append(title, tag(task.status || task.kind || "task", task.status === "blocked" ? "warn" : ""));
    const detail = document.createElement("span");
    detail.textContent = `${formatShortTime(task.updated_at)} | ${compact(task.summary || task.lane, "No task summary.", 180)}`;
    item.append(top, detail);
    nodes.systemTasks.append(item);
  });
}

function renderReplyTurns(payload) {
  const turns = asArray(payload.reply_turns);
  nodes.replyTurnCount.textContent = `${turns.length} turns`;
  clear(nodes.replyTurnList);

  if (!turns.length) {
    nodes.replyTurnList.append(emptyLine("No reply turns recorded yet."));
    return;
  }

  turns.slice(0, 8).forEach((turn) => {
    const item = document.createElement("div");
    item.className = "timeline-item";
    const top = document.createElement("div");
    top.className = "timeline-top";
    const title = document.createElement("strong");
    title.textContent = turn.current_topic || turn.intent || "reply turn";
    const ok = Boolean(turn.semantic_ok);
    top.append(title, tag(ok ? "aligned" : "needs review", ok ? "" : "warn"));

    const detail = document.createElement("span");
    const lanes = asArray(turn.active_lanes).join(", ") || "single";
    const issues = asArray(turn.semantic_issues).concat(asArray(turn.quality_issues)).slice(0, 2).join("; ");
    detail.textContent = `${formatShortTime(turn.created_at)} | ${turn.model || "unknown"} | lanes: ${lanes} | ${compact(issues || turn.inbound_preview, "No replay detail.", 220)}`;
    const inspector = document.createElement("details");
    inspector.className = "reply-inspector";
    const summary = document.createElement("summary");
    summary.textContent = "Why this answer?";
    inspector.append(summary);

    const contract = document.createElement("div");
    contract.className = "inspector-line";
    const stale = asArray(turn.forbidden_stale_topics).join(", ") || "none";
    contract.textContent = `intent=${turn.intent || "unknown"} | topic=${turn.current_topic || "unknown"} | previous=${turn.previous_topic || "none"} | stale background=${stale}`;
    inspector.append(contract);

    const laneWrap = document.createElement("div");
    laneWrap.className = "inspector-lanes";
    asArray(turn.lanes).forEach((lane) => {
      const row = document.createElement("div");
      row.className = "inspector-lane";
      const laneTitle = document.createElement("strong");
      laneTitle.textContent = `${lane.lane || "lane"} ${lane.stance || "unknown"}`;
      const laneMeta = document.createElement("span");
      const learning = Number(lane.learning_adjustment || 0);
      const learningText = Math.abs(learning) > 0.001 ? ` | learn ${learning > 0 ? "+" : ""}${learning.toFixed(2)}` : "";
      const quarantined = lane.quarantined ? " | quarantined" : "";
      laneMeta.textContent = `pressure ${lane.pressure ?? "?"}/${lane.threshold ?? "?"}${learningText}${quarantined} | ${compact(asArray(lane.reasons).join(", "), "no salient cue", 180)}`;
      row.append(laneTitle, laneMeta);
      laneWrap.append(row);
    });
    if (!laneWrap.children.length) {
      laneWrap.append(emptyLine("No lane detail recorded."));
    }
    inspector.append(laneWrap);

    item.append(top, detail, inspector);
    nodes.replyTurnList.append(item);
  });
}

function renderAttention(payload) {
  const threads = asArray(asObject(payload.status).thread_attention);
  nodes.attentionCount.textContent = `${threads.length} tracked`;
  clear(nodes.threadAttention);

  if (!threads.length) {
    nodes.threadAttention.append(emptyLine("No active thread summaries."));
    return;
  }

  threads.slice(0, 7).forEach((thread) => {
    const item = document.createElement("div");
    item.className = "thread-item";
    const top = document.createElement("div");
    top.className = "thread-top";
    const title = document.createElement("strong");
    title.textContent = thread.subject || "Thread";
    top.append(title, tag(thread.status || "open", thread.status === "awaiting_user" ? "warn" : ""));
    const detail = document.createElement("span");
    detail.textContent = `${thread.latest_sender || "unknown"} | ${formatShortTime(thread.latest_timestamp)} | ${compact(thread.latest_preview, "No preview.", 150)}`;
    item.append(top, detail);
    nodes.threadAttention.append(item);
  });
}

function render(payload) {
  state.lastPayload = payload;
  state.lastRefreshAt = new Date();
  renderHeader(payload);
  renderMetrics(payload);
  renderWorkspace(payload);
  renderLanes(payload);
  renderPressure(payload);
  renderAutonomy(payload);
  renderSubstrate(payload);
  renderActions(payload);
  renderReplyTurns(payload);
  renderAttention(payload);
}

async function refresh() {
  if (state.loading) return;
  state.loading = true;
  nodes.refreshBtn.disabled = true;
  try {
    const payload = await api("/api/monitor");
    render(payload);
  } catch (error) {
    console.error(error);
    document.body.dataset.live = "error";
    nodes.generatedLine.textContent = `Monitor error | ${error.message}`;
  } finally {
    state.loading = false;
    nodes.refreshBtn.disabled = false;
  }
}

function checkStale() {
  if (!state.lastRefreshAt || document.body.dataset.live === "error") return;
  const ageMs = Date.now() - state.lastRefreshAt.getTime();
  if (ageMs > 12000 && !state.paused) {
    document.body.dataset.live = "stale";
    nodes.generatedLine.textContent = `Waiting for Eve | last update ${formatShortTime(state.lastRefreshAt)}`;
  }
}

nodes.refreshBtn.addEventListener("click", () => {
  refresh();
});

nodes.pauseBtn.addEventListener("click", () => {
  state.paused = !state.paused;
  nodes.pauseBtn.querySelector("span:last-child").textContent = state.paused ? "Resume" : "Pause";
  nodes.pauseBtn.title = state.paused ? "Resume live updates" : "Pause live updates";
  if (!state.paused) {
    refresh();
  } else {
    nodes.generatedLine.textContent = `Paused | last update ${state.lastRefreshAt ? formatShortTime(state.lastRefreshAt) : "never"}`;
  }
});

nodes.segments.forEach((button) => {
  button.addEventListener("click", () => {
    state.substrateStream = button.dataset.stream || "evidence";
    nodes.segments.forEach((segment) => segment.classList.toggle("active", segment === button));
    if (state.lastPayload) {
      renderSubstrate(state.lastPayload);
    }
  });
});

await refresh();
setInterval(() => {
  if (!state.paused) {
    refresh();
  }
}, 2000);
setInterval(checkStale, 1000);
