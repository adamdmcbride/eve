const state = {
  threadFilter: "all",
  threadSearch: "",
  threads: [],
  selectedThreadId: null,
  selectedThreadSubject: null,
  selectedMessageId: null,
  lastIncomingEveMessageId: null,
  pendingAttachments: [],
};

const nodes = {
  presenceLine: document.querySelector("#presenceLine"),
  focusLine: document.querySelector("#focusLine"),
  humanUpdatedLine: document.querySelector("#humanUpdatedLine"),
  activeMindUpdatedLine: document.querySelector("#activeMindUpdatedLine"),
  activeMindSummary: document.querySelector("#activeMindSummary"),
  activeMindDetails: document.querySelector("#activeMindDetails"),
  identityStatement: document.querySelector("#identityStatement"),
  identityDetails: document.querySelector("#identityDetails"),
  relationshipOverview: document.querySelector("#relationshipOverview"),
  relationshipDetails: document.querySelector("#relationshipDetails"),
  modelUpdatedLine: document.querySelector("#modelUpdatedLine"),
  modelOverview: document.querySelector("#modelOverview"),
  modelDetails: document.querySelector("#modelDetails"),
  threadMeta: document.querySelector("#threadMeta"),
  threadTitle: document.querySelector("#threadTitle"),
  threadView: document.querySelector("#threadView"),
  threadList: document.querySelector("#threadList"),
  threadSearchInput: document.querySelector("#threadSearchInput"),
  wakeBtn: document.querySelector("#wakeBtn"),
  newThreadBtn: document.querySelector("#newThreadBtn"),
  toggleThreadFilterBtn: document.querySelector("#toggleThreadFilterBtn"),
  archiveThreadBtn: document.querySelector("#archiveThreadBtn"),
  composerForm: document.querySelector("#composerForm"),
  messageInput: document.querySelector("#messageInput"),
  fileInput: document.querySelector("#fileInput"),
  attachBtn: document.querySelector("#attachBtn"),
  attachmentTray: document.querySelector("#attachmentTray"),
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
    },
    ...options,
  });
  const contentType = response.headers.get("content-type") || "";
  if (!contentType.includes("application/json")) {
    throw new Error("Eve returned a non-JSON response. Check that the Eve API, not the upstream UI, is open.");
  }
  const payload = await response.json();
  if (!response.ok || !payload.ok) {
    throw new Error(payload.error || "Request failed");
  }
  return payload.data;
}

function setBusy(button, busy, label) {
  if (!button) return;
  button.disabled = busy;
  if (label) {
    button.dataset.originalLabel ||= button.textContent;
    button.textContent = busy ? label : button.dataset.originalLabel;
  }
}

function syncComposerHeight() {
  if (!nodes.messageInput) return;
  nodes.messageInput.style.height = "0px";
  const nextHeight = Math.min(Math.max(nodes.messageInput.scrollHeight, 76), 220);
  nodes.messageInput.style.height = `${nextHeight}px`;
}

function formatDate(value) {
  if (!value) return "Unknown";
  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatThreadStatus(status) {
  return {
    awaiting_user: "Waiting on you",
    active: "You spoke last",
    open: "Open",
    archived: "Archived",
    empty: "Empty",
  }[status] || "Open";
}

function formatThreadMeta(thread) {
  const speaker = thread.latest_sender === "eve" ? "Eve" : "You";
  return `${speaker} · ${formatDate(thread.latest_timestamp)}`;
}

function formatLatency(value) {
  const ms = Number(value || 0);
  if (!ms) return "n/a";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(ms >= 10000 ? 0 : 1)} s`;
}

function formatList(items, fallback = "None recorded yet.") {
  return Array.isArray(items) && items.length ? items.join(" • ") : fallback;
}

function truncateText(value, length = 140) {
  const clean = String(value || "").replace(/\s+/g, " ").trim();
  if (!clean) return "";
  return clean.length > length ? `${clean.slice(0, length - 1)}…` : clean;
}

function threadBadge(thread) {
  if (thread.unread_count) {
    return `${thread.unread_count} new`;
  }
  return formatThreadStatus(thread.status);
}

function composeSubject(body) {
  const words = body.trim().split(/\s+/).filter(Boolean).slice(0, 6);
  const subject = words.join(" ");
  if (subject) return subject.slice(0, 72);
  return state.pendingAttachments.length ? "Attached files for Eve" : "Chat with Eve";
}

function formatBytes(byteCount) {
  const size = Number(byteCount || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(size >= 10240 ? 0 : 1)} KB`;
  return `${(size / 1024 / 1024).toFixed(size >= 10 * 1024 * 1024 ? 0 : 1)} MB`;
}

function attachmentDetail(attachment) {
  const parts = [];
  if (attachment.type_label) parts.push(attachment.type_label);
  if (attachment.byte_count != null) parts.push(formatBytes(attachment.byte_count));
  if (attachment.extraction_status) parts.push(attachment.extraction_status.replaceAll("_", " "));
  return parts.join(" · ");
}

function stripAttachmentEvidence(body) {
  const marker = "\n\nAttached files for Eve to inspect:\n";
  const index = String(body || "").indexOf(marker);
  return index >= 0 ? String(body || "").slice(0, index) : String(body || "");
}

function parseLegacyAttachments(body) {
  const marker = "\n\nAttached files for Eve to inspect:\n";
  const index = String(body || "").indexOf(marker);
  if (index < 0) return [];
  return String(body || "")
    .slice(index + marker.length)
    .split("\n")
    .filter((line) => line.trim().startsWith("- "))
    .map((line, offset) => {
      const text = line.trim().slice(2);
      const name = text.split(" (")[0] || "attachment";
      const detailMatch = text.match(/\(([^)]+)\)/);
      return {
        id: `legacy-${offset}-${name}`,
        name,
        type_label: detailMatch?.[1] || "",
      };
    });
}

function renderAttachmentTray() {
  if (!nodes.attachmentTray) return;
  nodes.attachmentTray.replaceChildren();
  nodes.attachmentTray.hidden = state.pendingAttachments.length === 0;
  state.pendingAttachments.forEach((attachment) => {
    const chip = document.createElement("span");
    chip.className = "attachment-chip";
    chip.textContent = `${attachment.name} · ${attachment.type_label || "file"} · ${formatBytes(attachment.byte_count)}`;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "attachment-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Remove ${attachment.name}`);
    remove.addEventListener("click", () => {
      state.pendingAttachments = state.pendingAttachments.filter((item) => item.id !== attachment.id);
      renderAttachmentTray();
    });
    chip.append(remove);
    nodes.attachmentTray.append(chip);
  });
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      const value = String(reader.result || "");
      resolve(value.includes(",") ? value.split(",", 2)[1] : value);
    });
    reader.addEventListener("error", () => reject(reader.error || new Error("Could not read file")));
    reader.readAsDataURL(file);
  });
}

async function uploadFile(file) {
  const contentBase64 = await readFileAsBase64(file);
  return api("/api/attachments/upload", {
    method: "POST",
    body: JSON.stringify({
      name: file.name,
      mime_type: file.type,
      content_base64: contentBase64,
    }),
  });
}

function renderThreadFilterButton() {
  nodes.toggleThreadFilterBtn.textContent = state.threadFilter === "waiting" ? "All" : "Waiting";
}

function resetThreadSelection(message = "Choose a chat or send Eve a message.") {
  state.selectedThreadId = null;
  state.selectedThreadSubject = null;
  state.selectedMessageId = null;
  nodes.threadMeta.textContent = "No thread selected";
  nodes.threadTitle.textContent = "New chat";
  nodes.threadView.classList.add("empty-state");
  nodes.threadView.textContent = message;
  nodes.archiveThreadBtn.disabled = true;
  nodes.messageInput.placeholder = "Message Eve";
  state.pendingAttachments = [];
  renderAttachmentTray();
}

function renderPresence(status) {
  const activeThreads = Number(status.counts.active_threads || status.counts.threads || 0);
  const waitingThreads = Number(status.counts.waiting_threads || 0);
  if (status.daemon.awake) {
    nodes.presenceLine.textContent = `Awake · ${activeThreads} chats · ${waitingThreads} waiting`;
    document.body.dataset.presence = "awake";
  } else if (status.daemon.running) {
    nodes.presenceLine.textContent = "Starting up...";
    document.body.dataset.presence = "starting";
  } else {
    nodes.presenceLine.textContent = "Sleeping. Wake Eve to start the loop.";
    document.body.dataset.presence = "sleeping";
  }

  nodes.focusLine.textContent = status.state.current_focus
    ? truncateText(status.state.current_focus, 170)
    : "No current focus yet.";
  nodes.activeMindUpdatedLine.textContent = status.active_mind?.updated_at
    ? `Updated ${formatDate(status.active_mind.updated_at)}`
    : "Not refreshed yet";
  nodes.activeMindSummary.textContent =
    status.active_mind?.current_focus || status.active_mind?.summary || "No active mind snapshot yet.";
  const liveThreads = Array.isArray(status.active_mind?.live_threads) ? status.active_mind.live_threads : [];
  const mindAudit = Array.isArray(status.active_mind_audit) ? status.active_mind_audit : [];
  const ambientThreadBeats = Array.isArray(status.ambient_thought?.thread_beats) ? status.ambient_thought.thread_beats : [];
  nodes.activeMindDetails.textContent = truncateText(
    [
      liveThreads.length
        ? `Threads: ${liveThreads
            .map((thread) => `${thread.status || "active"} ${thread.title || thread.detail || "thread"}`)
            .join(" • ")}`
        : "",
      ambientThreadBeats.length
        ? `Thinking now: ${ambientThreadBeats
            .map((beat) => beat.thread_title || beat.title || "thread")
            .join(" • ")}`
        : "",
      mindAudit.length ? `Latest audit: ${mindAudit[mindAudit.length - 1].summary || "thread activity updated"}` : "",
      `Concerns: ${formatList(status.active_mind?.live_concerns, "None recorded yet.")}`,
      `Next: ${status.active_mind?.next_step || "No next step recorded yet."}`,
    ]
      .filter(Boolean)
      .join(" "),
    190
  );
  nodes.humanUpdatedLine.textContent = status.human_context?.updated_at
    ? `Updated ${formatDate(status.human_context.updated_at)}`
    : "Not refreshed yet";
  nodes.identityStatement.textContent =
    status.human_context?.self_model?.identity_statement || "Not enough evidence yet.";
  nodes.identityDetails.textContent = truncateText(
    [
      `Preoccupations: ${formatList(status.human_context?.self_model?.current_preoccupations, "None recorded yet.")}`,
      `Grounding: ${formatList(status.human_context?.self_model?.grounding_practices, "None recorded yet.")}`,
    ].join(" "),
    170
  );
  nodes.relationshipOverview.textContent =
    status.human_context?.relationship_memory?.user_overview || "No durable relationship memory yet.";
  nodes.relationshipDetails.textContent = truncateText(
    [
      `Requested: ${formatList(status.human_context?.relationship_memory?.requested_practices, "None recorded yet.")}`,
      `Open loops: ${formatList(status.human_context?.relationship_memory?.open_loops, "None recorded yet.")}`,
      `Trust: ${formatList(status.human_context?.memory_v2?.trust_ledger, "None recorded yet.")}`,
      `Repair: ${formatList(status.human_context?.memory_v2?.repair_practices, "None recorded yet.")}`,
      `Truth boundary: ${formatList(status.human_context?.memory_v2?.anti_sycophancy_boundaries, "None recorded yet.")}`,
    ].join(" "),
    260
  );

  const modelHealth = status.model_health || {};
  const fastProbe = modelHealth.probes?.fast || {};
  const deepProbe = modelHealth.probes?.deep || {};
  const lanes = Array.isArray(modelHealth.lanes) ? modelHealth.lanes : [];
  const hosts = Array.isArray(modelHealth.hosts) ? modelHealth.hosts : [];
  nodes.modelUpdatedLine.textContent = modelHealth.updated_at
    ? `Checked ${formatDate(modelHealth.updated_at)}`
    : "No checks yet";
  nodes.modelOverview.textContent = modelHealth.summary || "Model health unavailable.";
  const laneSummary = lanes.length
    ? `Lanes: ${lanes
        .map((lane) => `${lane.label || lane.lane} ${lane.loaded ? "ready" : "down"} ${formatLatency(lane.latency_ms)}`)
        .join(" • ")}`
    : "";
  const hostSummary = hosts.length
    ? `Hosts: ${hosts
        .map((host) => {
          const port = String(host.host || "").split(":").pop() || "?";
          const models = Array.isArray(host.visible_models) && host.visible_models.length ? host.visible_models.join(",") : "none";
          return `${port} ${models}`;
        })
        .join(" • ")}`
    : "";
  nodes.modelDetails.textContent = truncateText(
    [
      laneSummary || `Resident: fast ${modelHealth.residency?.preferred_fast_loaded ? "yes" : "no"} • deep ${modelHealth.residency?.preferred_deep_loaded ? "yes" : "no"}`,
      hostSummary,
      lanes.length ? "" : `Latency: fast ${formatLatency(fastProbe.wall_ms)} • deep ${formatLatency(deepProbe.wall_ms)}`,
      modelHealth.recent_actions?.length ? `Actions: ${modelHealth.recent_actions.join(" • ")}` : "",
    ]
      .filter(Boolean)
      .join(" "),
    280
  );
}

function threadCardTemplate(thread) {
  const template = document.querySelector("#threadCardTemplate").content.firstElementChild.cloneNode(true);
  template.dataset.threadId = thread.thread_id;
  template.dataset.status = thread.status;
  if (thread.unread_count) {
    template.dataset.unread = "true";
  }
  template.querySelector(".thread-subject").textContent = truncateText(thread.subject, 54);
  template.querySelector(".thread-badge").textContent = threadBadge(thread);
  template.querySelector(".thread-meta").textContent = formatThreadMeta(thread);
  template.querySelector(".thread-preview").textContent = truncateText(thread.latest_preview, 78);
  if (state.selectedThreadId === thread.thread_id) {
    template.classList.add("active");
  }
  template.addEventListener("click", async () => {
    state.selectedThreadId = thread.thread_id;
    state.selectedThreadSubject = thread.subject;
    state.selectedMessageId = thread.latest_message_id;
    renderThreads(state.threads);
    await loadThread(thread.thread_id, thread.subject);
  });
  return template;
}

function renderThreads(threads) {
  const search = state.threadSearch.trim().toLowerCase();
  const visibleThreads = threads
    .filter((thread) => (state.threadFilter === "waiting" ? thread.status === "awaiting_user" : thread.status !== "archived"))
    .filter((thread) => {
      if (!search) return true;
      const haystack = [thread.subject, thread.latest_preview, formatThreadMeta(thread)].join(" ").toLowerCase();
      return haystack.includes(search);
    });

  nodes.threadList.replaceChildren();
  if (!visibleThreads.length) {
    nodes.threadList.textContent = search
      ? "No chats match that search."
      : state.threadFilter === "waiting"
        ? "Nothing is waiting on you."
        : "No chats yet.";
    return;
  }

  visibleThreads.forEach((thread) => nodes.threadList.append(threadCardTemplate(thread)));
}

function bubbleTemplate(message) {
  const template = document.querySelector("#threadBubbleTemplate").content.firstElementChild.cloneNode(true);
  const speaker = message.sender === "user" ? "You" : "Eve";
  template.classList.add(message.sender === "user" ? "user" : "eve");
  template.querySelector(".bubble-meta").textContent = `${speaker} · ${formatDate(message.timestamp)}`;
  template.querySelector(".bubble-body").textContent = stripAttachmentEvidence(message.body) || "Attached files";
  const attachments = message.metadata?.attachments?.length ? message.metadata.attachments : parseLegacyAttachments(message.body);
  if (attachments.length) {
    const row = document.createElement("div");
    row.className = "bubble-attachments";
    attachments.forEach((attachment) => {
      const chip = document.createElement("span");
      chip.className = "attachment-chip readonly";
      chip.textContent = `${attachment.name} · ${attachmentDetail(attachment)}`;
      row.append(chip);
    });
    template.append(row);
  }
  return template;
}

async function loadThread(threadId, subject = null) {
  const thread = await api(`/api/thread/${threadId}`);
  const latestMessage = thread[thread.length - 1];
  const summary = state.threads.find((item) => item.thread_id === threadId);

  state.selectedThreadId = threadId;
  state.selectedMessageId = latestMessage?.id || summary?.latest_message_id || null;
  state.selectedThreadSubject = subject || latestMessage?.subject || summary?.subject || "Conversation";

  nodes.threadTitle.textContent = truncateText(state.selectedThreadSubject, 72);
  nodes.threadMeta.textContent = summary
    ? `${formatThreadStatus(summary.status)} · ${summary.message_count} messages`
    : "Conversation";
  nodes.archiveThreadBtn.disabled = false;
  nodes.threadView.replaceChildren();
  nodes.threadView.classList.remove("empty-state");
  nodes.messageInput.placeholder = "Reply to Eve";

  if (!thread.length) {
    nodes.threadView.classList.add("empty-state");
    nodes.threadView.textContent = "This chat is empty.";
    return;
  }

  thread.forEach((message) => nodes.threadView.append(bubbleTemplate(message)));
  nodes.threadView.scrollTop = nodes.threadView.scrollHeight;
}

function chooseThread(threads, preferredThreadId = null) {
  if (preferredThreadId) {
    const preferred = threads.find((thread) => thread.thread_id === preferredThreadId);
    if (preferred) return preferred;
  }

  if (state.selectedThreadId) {
    const selected = threads.find((thread) => thread.thread_id === state.selectedThreadId);
    if (selected) return selected;
  }

  const firstVisible = threads.find((thread) => thread.status !== "archived");
  return firstVisible || null;
}

async function refreshAll(preferredThreadId = null) {
  try {
    const [status, threads] = await Promise.all([api("/api/status"), api("/api/threads?limit=40")]);

    renderPresence(status);
    state.threads = threads;
    renderThreads(threads);

    const newestThread = threads[0] || null;
    const userIsTyping =
      document.activeElement === nodes.messageInput && nodes.messageInput.value.trim().length > 0;
    let threadToShow = chooseThread(threads, preferredThreadId);

    if (
      newestThread &&
      newestThread.latest_sender === "eve" &&
      newestThread.latest_message_id !== state.lastIncomingEveMessageId
    ) {
      state.lastIncomingEveMessageId = newestThread.latest_message_id;
      if (!userIsTyping) {
        threadToShow = newestThread;
      }
    }

    if (threadToShow) {
      await loadThread(threadToShow.thread_id, threadToShow.subject);
    } else {
      resetThreadSelection(status.daemon.awake ? "Start the first chat with Eve." : "Wake Eve to begin.");
    }
  } catch (error) {
    console.error(error);
    nodes.presenceLine.textContent = error.message;
    resetThreadSelection("The app could not reach Eve.");
  }
}

async function wakeEve() {
  setBusy(nodes.wakeBtn, true, "Waking...");
  try {
    const result = await api("/api/actions/wake", {
      method: "POST",
      body: JSON.stringify({}),
    });
    renderPresence(result.status);
    await refreshAll(result.selected_thread_id || null);
  } catch (error) {
    console.error(error);
    nodes.presenceLine.textContent = error.message;
  } finally {
    setBusy(nodes.wakeBtn, false);
  }
}

async function sendMessage(body, attachments = []) {
  const subject = composeSubject(body);

  if (state.selectedThreadId && state.selectedMessageId) {
    const data = await api("/api/message/reply", {
      method: "POST",
      body: JSON.stringify({
        message_id: state.selectedMessageId,
        body,
        subject,
        attachments,
      }),
    });
    nodes.messageInput.value = "";
    state.pendingAttachments = [];
    renderAttachmentTray();
    syncComposerHeight();
    await refreshAll(data.thread_id);
    return;
  }

  const data = await api("/api/message/ask", {
    method: "POST",
    body: JSON.stringify({
      body,
      subject,
      attachments,
    }),
  });
  nodes.messageInput.value = "";
  state.pendingAttachments = [];
  renderAttachmentTray();
  syncComposerHeight();
  await refreshAll(data.thread_id);
}

nodes.wakeBtn.addEventListener("click", wakeEve);

nodes.newThreadBtn.addEventListener("click", () => {
  resetThreadSelection("Write a message below to start a new chat.");
  nodes.messageInput.focus();
  syncComposerHeight();
});

nodes.toggleThreadFilterBtn.addEventListener("click", () => {
  state.threadFilter = state.threadFilter === "waiting" ? "all" : "waiting";
  renderThreadFilterButton();
  renderThreads(state.threads);
});

nodes.threadSearchInput.addEventListener("input", () => {
  state.threadSearch = nodes.threadSearchInput.value;
  renderThreads(state.threads);
});

nodes.archiveThreadBtn.addEventListener("click", async () => {
  if (!state.selectedThreadId) return;
  const thread = await api(`/api/thread/${state.selectedThreadId}`);
  const userMessages = thread.filter((message) => message.recipient === "user" && message.status !== "archived");
  await Promise.all(
    userMessages.map((message) =>
      api(`/api/messages/${message.id}/mark`, {
        method: "POST",
        body: JSON.stringify({ status: "archived" }),
      })
    )
  );
  resetThreadSelection("Chat archived.");
  await refreshAll();
});

nodes.messageInput.addEventListener("input", syncComposerHeight);

nodes.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    nodes.composerForm.requestSubmit();
  }
});

if (nodes.attachBtn && nodes.fileInput) {
  nodes.attachBtn.addEventListener("click", () => {
    nodes.fileInput.click();
  });
}

async function uploadFiles(files) {
  const queue = Array.from(files || []);
  if (!queue.length) return;
  setBusy(nodes.attachBtn, true);
  nodes.composerForm.dataset.uploading = "true";
  try {
    for (const file of queue) {
      const attachment = await uploadFile(file);
      state.pendingAttachments.push(attachment);
    }
    renderAttachmentTray();
  } finally {
    nodes.composerForm.dataset.uploading = "false";
    setBusy(nodes.attachBtn, false);
  }
}

if (nodes.fileInput) {
  nodes.fileInput.addEventListener("change", async () => {
    const files = Array.from(nodes.fileInput.files || []);
    if (!files.length) return;
    try {
      await uploadFiles(files);
    } catch (error) {
      console.error(error);
      nodes.presenceLine.textContent = error.message;
    } finally {
      nodes.fileInput.value = "";
    }
  });
}

if (nodes.attachBtn && nodes.fileInput) {
  nodes.composerForm.addEventListener("dragover", (event) => {
    event.preventDefault();
    nodes.composerForm.dataset.dragging = "true";
  });

  nodes.composerForm.addEventListener("dragleave", (event) => {
    if (!nodes.composerForm.contains(event.relatedTarget)) {
      nodes.composerForm.dataset.dragging = "false";
    }
  });

  nodes.composerForm.addEventListener("drop", async (event) => {
    event.preventDefault();
    nodes.composerForm.dataset.dragging = "false";
    try {
      await uploadFiles(event.dataTransfer.files);
    } catch (error) {
      console.error(error);
      nodes.presenceLine.textContent = error.message;
    }
  });
}

nodes.composerForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const body = nodes.messageInput.value.trim();
  const attachments = state.pendingAttachments.slice();
  if (!body && !attachments.length) return;
  nodes.composerForm.dataset.sending = "true";
  try {
    await sendMessage(body, attachments);
  } catch (error) {
    console.error(error);
    nodes.presenceLine.textContent = error.message;
  } finally {
    nodes.composerForm.dataset.sending = "false";
  }
});

renderThreadFilterButton();
resetThreadSelection("Waking Eve...");
syncComposerHeight();
await wakeEve();
setInterval(() => {
  refreshAll();
}, 10000);
