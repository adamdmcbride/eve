(() => {
  "use strict";

  const STORAGE_KEY = "eve.app.conversations.v2";
  const STORAGE_BACKUP_KEY = "eve.app.conversations.backup.v2";
  const SETTINGS_KEY = "eve.app.settings.v1";
  const LIVE_CONVERSATION_ID = "eve-live";
  const MAX_CONVERSATIONS = 30;
  const MAX_MESSAGES_PER_CONVERSATION = 120;

  const elements = {
    body: document.body,
    sidebar: document.getElementById("sidebar"),
    workspace: document.getElementById("workspace"),
    list: document.getElementById("conversation-list"),
    transcript: document.getElementById("transcript"),
    title: document.getElementById("conversation-title"),
    state: document.getElementById("conversation-state"),
    statusDot: document.getElementById("status-dot"),
    statusLabel: document.getElementById("status-label"),
    composer: document.getElementById("composer"),
    prompt: document.getElementById("prompt"),
    send: document.getElementById("send-button"),
    newChat: document.getElementById("new-chat"),
    showLive: document.getElementById("show-live"),
    identityBadge: document.getElementById("identity-badge"),
    identityPlace: document.getElementById("identity-place"),
    sidebarToggle: document.getElementById("sidebar-toggle"),
    mic: document.getElementById("mic-button"),
    speak: document.getElementById("speak-toggle"),
    sensesToggle: document.getElementById("senses-toggle"),
    sensesPanel: document.getElementById("senses-panel"),
    sensesClose: document.getElementById("senses-close"),
    sensesStart: document.getElementById("senses-start"),
    sensesStop: document.getElementById("senses-stop"),
    sensesStatus: document.getElementById("senses-status"),
    senseAudio: document.getElementById("sense-audio"),
    senseVisual: document.getElementById("sense-visual"),
    senseTouch: document.getElementById("sense-touch"),
    senseDuration: document.getElementById("sense-duration"),
    replyContext: document.getElementById("reply-context"),
    replySubject: document.getElementById("reply-subject"),
    cancelReply: document.getElementById("cancel-reply"),
    jumpLatest: document.getElementById("jump-latest"),
  };

  let storageHealthy = true;
  let store = loadStore();
  let settings = loadSettings();
  let activeController = null;
  let isSending = false;
  let backendReady = false;
  let statusChecked = false;
  let recognition = null;
  let recognitionDraft = "";
  let lastRenderedConversationId = "";
  let liveRefreshHasNewContent = false;
  let liveRefreshInFlight = false;
  let isMarkingPersonalMessages = false;
  let liveFailureCount = 0;
  let livePollTimer = null;
  let lastBackupAt = 0;
  let recoveryInFlight = false;
  let livePresence = null;
  let draftSaveTimer = null;
  let composerConversationId = "";
  let lastLocalReplyCompletedAt = 0;
  let liveLaunchAnchorPending = true;
  let sensorySession = null;
  let sensoryAudioContext = null;
  let sensoryAudioStream = null;
  let sensoryVideoStream = null;
  let sensoryVideoElement = null;
  let sensoryIntervals = [];
  let sensoryDisposers = [];
  let sensoryQueue = [];
  let sensoryFlushInFlight = false;
  let sensoryExpiryTimer = null;

  function readLocalValue(key) {
    try {
      return localStorage.getItem(key);
    } catch (_) {
      storageHealthy = false;
      return null;
    }
  }

  function writeLocalValue(key, value) {
    try {
      localStorage.setItem(key, value);
      return true;
    } catch (_) {
      storageHealthy = false;
      return false;
    }
  }

  function id(prefix) {
    if (window.crypto && window.crypto.randomUUID) return `${prefix}-${window.crypto.randomUUID()}`;
    return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  }

  function describeError(error) {
    if (!error) return "";
    if (typeof error === "string") return error.slice(0, 1200);
    for (const key of ["message", "detail", "error", "reason"]) {
      if (typeof error?.[key] === "string" && error[key].trim()) {
        return error[key].trim().slice(0, 1200);
      }
    }
    try {
      const serialized = JSON.stringify(error);
      return serialized && serialized !== "{}" ? serialized.slice(0, 1200) : "Local connection failed";
    } catch (_) {
      return "Local connection failed";
    }
  }

  function setDaypart() {
    const hour = new Date().getHours();
    const daypart = hour < 6 ? "night" : hour < 10 ? "dawn" : hour < 17 ? "day" : hour < 21 ? "evening" : "night";
    elements.body.dataset.daypart = daypart;
  }

  function normalizedSentence(value, maximum = 280) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (!text) return "";
    const clipped = text.length > maximum ? `${text.slice(0, maximum - 1).trim()}…` : text;
    return clipped.replace(/[.\s]+$/, "");
  }

  function lowerFirst(value) {
    const text = normalizedSentence(value);
    if (!text) return "";
    return `${text.charAt(0).toLowerCase()}${text.slice(1)}`;
  }

  function currentVisualState() {
    if (!backendReady && statusChecked) return "reconnecting";
    if (elements.mic.classList.contains("listening")) return "listening";
    if (isSending) return "thinking";
    if (sensorySession) return "perceiving";
    const allowed = new Set(["here", "quiet", "thinking", "acting", "responding", "reconnecting", "perceiving"]);
    const presenceState = allowed.has(livePresence?.state) ? livePresence.state : "here";
    if (
      presenceState === "responding" &&
      !isSending &&
      Date.now() - lastLocalReplyCompletedAt < 20000
    ) {
      return "here";
    }
    return presenceState;
  }

  function syncVisualState() {
    const state = currentVisualState();
    elements.body.dataset.eveState = state;
    const places = {
      acting: "Doing something",
      thinking: "Thinking",
      responding: "Talking with you",
      reconnecting: "Finding my way back",
      quiet: "Quiet, inside this Mac",
      listening: "Listening to you",
      perceiving: "Perceiving locally",
      here: "Here, inside this Mac",
    };
    elements.identityPlace.textContent = places[state] || places.here;
    const surfaceBusy = recoveryInFlight || ["thinking", "responding", "acting", "reconnecting"].includes(state);
    elements.transcript.setAttribute("aria-busy", String(surfaceBusy));
  }

  function parseStoredStore(raw) {
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed.conversations)) return null;
    return {
      activeId: String(parsed.activeId || ""),
      conversations: parsed.conversations
        .filter((item) => item && item.id)
        .slice(0, MAX_CONVERSATIONS)
        .map((conversation) => {
          const rawMessages = Array.isArray(conversation.messages) ? conversation.messages : [];
          return {
            ...conversation,
            id: String(conversation.id),
            title: String(conversation.title || "New conversation").slice(0, 120),
            messages: rawMessages.slice(-240).map((message, index, messages) => {
              if (!message || typeof message !== "object") return null;
              const normalizedMessage = { ...message };
              const interruptedPartial = String(
                normalizedMessage.partialContent || (normalizedMessage.pending ? normalizedMessage.content : "") || ""
              ).trim();
              const legacyFailure = String(normalizedMessage.content || "");
              if (
                normalizedMessage.error &&
                !normalizedMessage.eventType &&
                !normalizedMessage.partialContent &&
                /(\[object Object\]|local connection failed|local connection before|local runtime is unavailable|connection refused)/i.test(legacyFailure)
              ) {
                normalizedMessage.content = "I couldn’t finish that reply.";
                normalizedMessage.errorDetail = String(normalizedMessage.errorDetail || legacyFailure);
              }
              if (!normalizedMessage.pending && !normalizedMessage.recoveryPending) return normalizedMessage;
              const previousUser = messages
                .slice(0, index)
                .reverse()
                .find((candidate) => candidate?.role === "user" && candidate?.content);
              return {
                ...normalizedMessage,
                pending: true,
                error: false,
                eventType: "",
                content: "",
                errorDetail: "",
                retryText: String(normalizedMessage.retryText || previousUser?.content || ""),
                userMessageId: String(normalizedMessage.userMessageId || previousUser?.id || ""),
                clientRequestId: String(normalizedMessage.clientRequestId || previousUser?.id || ""),
                recoveryPending: true,
                progressLabel: "Reconnecting",
                partialContent: interruptedPartial,
              };
            }).filter(Boolean),
          };
        }),
    };
  }

  function loadStore() {
    for (const key of [STORAGE_KEY, STORAGE_BACKUP_KEY]) {
      const raw = readLocalValue(key);
      try {
        const parsed = parseStoredStore(raw);
        if (parsed) {
          if (key === STORAGE_BACKUP_KEY) writeLocalValue(STORAGE_KEY, raw);
          return parsed;
        }
      } catch (_) {
        // Try the last known-good snapshot before starting clean.
      }
    }
    return { activeId: "", conversations: [] };
  }

  function loadSettings() {
    try {
      const parsed = JSON.parse(readLocalValue(SETTINGS_KEY) || "{}");
      return {
        speakReplies: Boolean(parsed.speakReplies),
        // Eve's current life is the doorway. History opens only when asked for
        // during this app session instead of becoming the remembered homepage.
        sidebarCollapsed: true,
      };
    } catch (_) {
      return { speakReplies: false, sidebarCollapsed: true };
    }
  }

  function saveStore() {
    const live = store.conversations.find((item) => item.id === LIVE_CONVERSATION_ID);
    const conversations = store.conversations
      .filter((item) => item.id !== LIVE_CONVERSATION_ID)
      .sort((a, b) => Number(b.updatedAt || 0) - Number(a.updatedAt || 0))
      .slice(0, MAX_CONVERSATIONS - 1);
    store.conversations = [live, ...conversations]
      .filter(Boolean)
      .map((conversation) => ({
        ...conversation,
        messages: (conversation.messages || []).slice(
          conversation.id === LIVE_CONVERSATION_ID ? -240 : -MAX_MESSAGES_PER_CONVERSATION
        ),
      }));
    const serialized = JSON.stringify(store);
    const previous = readLocalValue(STORAGE_KEY);
    if (previous && Date.now() - lastBackupAt >= 60000) {
      try {
        if (parseStoredStore(previous) && writeLocalValue(STORAGE_BACKUP_KEY, previous)) {
          lastBackupAt = Date.now();
        }
      } catch (_) {
        // Never replace a good backup with a malformed primary snapshot.
      }
    }
    writeLocalValue(STORAGE_KEY, serialized);
  }

  function saveSettings() {
    writeLocalValue(SETTINGS_KEY, JSON.stringify({ speakReplies: settings.speakReplies }));
  }

  function flushDraft() {
    if (draftSaveTimer) {
      window.clearTimeout(draftSaveTimer);
      draftSaveTimer = null;
    }
    const conversation = activeConversation();
    if (!conversation || composerConversationId !== conversation.id) return;
    const draft = elements.prompt.value;
    if (String(conversation.draft || "") === draft) return;
    conversation.draft = draft;
    saveStore();
  }

  function scheduleDraftSave() {
    if (draftSaveTimer) window.clearTimeout(draftSaveTimer);
    draftSaveTimer = window.setTimeout(flushDraft, 240);
  }

  function syncConversationDraft(conversation) {
    if (!conversation || composerConversationId === conversation.id) return;
    composerConversationId = conversation.id;
    elements.prompt.value = String(conversation.draft || "");
  }

  function activeConversation() {
    return store.conversations.find((item) => item.id === store.activeId) || null;
  }

  function ensureLiveConversation() {
    let live = store.conversations.find((item) => item.id === LIVE_CONVERSATION_ID);
    if (!live) {
      live = {
        id: LIVE_CONVERSATION_ID,
        title: "Eve",
        mode: "live",
        createdAt: Date.now(),
        updatedAt: Date.now(),
        messages: [],
        draft: "",
        replyTarget: null,
      };
      store.conversations.unshift(live);
    }
    return live;
  }

  function ensureConversation() {
    ensureLiveConversation();
    let conversation = activeConversation();
    if (conversation) return conversation;
    conversation = ensureLiveConversation();
    store.activeId = LIVE_CONVERSATION_ID;
    saveStore();
    return conversation;
  }

  function honorLaunchView() {
    const requestedView = new URL(window.location.href).searchParams.get("view");
    if (requestedView !== "live") return;
    const current = activeConversation();
    const hasInterruptedReply = Boolean(
      current?.messages?.some((message) => message.pending || message.recoveryPending)
    );
    if (hasInterruptedReply) return;
    store.activeId = ensureLiveConversation().id;
    saveStore();
  }

  function newConversation() {
    if (activeController) activeController.abort();
    flushDraft();
    const conversation = {
      id: id("eve-chat"),
      title: "New conversation",
      mode: "conversation",
      createdAt: Date.now(),
      updatedAt: Date.now(),
      messages: [],
      draft: "",
    };
    store.conversations.splice(1, 0, conversation);
    store.activeId = conversation.id;
    settings.sidebarCollapsed = true;
    saveStore();
    elements.body.classList.remove("sidebar-open");
    elements.prompt.focus();
    render();
    return conversation.id;
  }

  function selectConversation(conversationId) {
    if (isSending && conversationId !== store.activeId) return;
    flushDraft();
    store.activeId = conversationId;
    if (conversationId === LIVE_CONVERSATION_ID) liveLaunchAnchorPending = true;
    settings.sidebarCollapsed = true;
    saveStore();
    elements.body.classList.remove("sidebar-open");
    elements.prompt.focus();
    render();
    if (conversationId === LIVE_CONVERSATION_ID) markVisiblePersonalMessagesRead();
  }

  function toggleSidebar() {
    if (window.matchMedia("(max-width: 760px)").matches) {
      elements.body.classList.toggle("sidebar-open");
      renderSidebarState();
      return;
    }
    settings.sidebarCollapsed = !settings.sidebarCollapsed;
    saveSettings();
    renderSidebarState();
  }

  function renderSidebarState() {
    const isMobile = window.matchMedia("(max-width: 760px)").matches;
    const collapsed = Boolean(settings.sidebarCollapsed) && !isMobile;
    const expanded = isMobile ? elements.body.classList.contains("sidebar-open") : !collapsed;
    elements.body.classList.toggle("sidebar-collapsed", collapsed);
    elements.sidebar.setAttribute("aria-hidden", String(!expanded));
    elements.sidebarToggle.setAttribute("aria-expanded", String(expanded));
    elements.sidebarToggle.setAttribute(
      "aria-label",
      expanded ? "Hide past conversations" : "Show past conversations"
    );
  }

  function titleFor(text) {
    const normalized = String(text || "").replace(/\s+/g, " ").trim();
    if (!normalized) return "New conversation";
    return normalized.length > 48 ? `${normalized.slice(0, 47).trim()}…` : normalized;
  }

  function setStatus(kind, label, detail) {
    elements.statusDot.className = `status-dot ${kind}`;
    elements.statusLabel.textContent = label;
    const visibleDetail = String(detail || "").trim();
    elements.state.textContent = visibleDetail;
    elements.state.hidden = !visibleDetail;
    syncVisualState();
  }

  function presenceStatusLabel() {
    const state = currentVisualState();
    return {
      acting: "Doing",
      thinking: "Thinking",
      responding: "Responding",
      quiet: "Quiet",
      listening: "Listening",
      reconnecting: "Reconnecting",
      here: "Here",
    }[state] || "Here";
  }

  function renderSidebar() {
    elements.list.replaceChildren();
    const live = ensureLiveConversation();
    live.title = "Eve";
    elements.showLive.classList.toggle("active", live.id === store.activeId);
    if (live.id === store.activeId) elements.showLive.setAttribute("aria-current", "page");
    else elements.showLive.removeAttribute("aria-current");
    const unreadCount = Array.isArray(live.pendingReadMessageIds)
      ? live.pendingReadMessageIds.length
      : live.messages.filter((message) => message.proactive && message.unread).length;
    elements.identityBadge.hidden = !unreadCount || live.id === store.activeId;
    elements.identityBadge.textContent = unreadCount > 9 ? "9+" : String(unreadCount);
    elements.identityBadge.setAttribute(
      "aria-label",
      `${unreadCount} unread message${unreadCount === 1 ? "" : "s"} from Eve`
    );

    const conversations = store.conversations.filter((item) => item.id !== LIVE_CONVERSATION_ID);
    if (!conversations.length) return;
    const recentLabel = document.createElement("p");
    recentLabel.className = "conversation-section-label";
    recentLabel.textContent = "Past conversations";
    elements.list.appendChild(recentLabel);

    for (const conversation of conversations) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `conversation-row${conversation.id === store.activeId ? " active" : ""}`;
      button.textContent = conversation.title || "New conversation";
      button.title = button.textContent;
      if (conversation.id === store.activeId) button.setAttribute("aria-current", "page");
      button.addEventListener("click", () => selectConversation(conversation.id));
      elements.list.appendChild(button);
    }
  }

  function appendInline(target, text) {
    const pattern = /(\[[^\]]+\]\(https?:\/\/[^\s)]+\)|`[^`]+`|\*\*[^*]+\*\*)/g;
    let cursor = 0;
    for (const match of text.matchAll(pattern)) {
      if (match.index > cursor) target.appendChild(document.createTextNode(text.slice(cursor, match.index)));
      const token = match[0];
      if (token.startsWith("[")) {
        const parts = token.match(/^\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)$/);
        if (parts) {
          const link = document.createElement("a");
          link.textContent = parts[1];
          link.href = parts[2];
          link.target = "_blank";
          link.rel = "noreferrer noopener";
          target.appendChild(link);
        }
      } else if (token.startsWith("`")) {
        const code = document.createElement("code");
        code.textContent = token.slice(1, -1);
        target.appendChild(code);
      } else {
        const strong = document.createElement("strong");
        strong.textContent = token.slice(2, -2);
        target.appendChild(strong);
      }
      cursor = match.index + token.length;
    }
    if (cursor < text.length) target.appendChild(document.createTextNode(text.slice(cursor)));
  }

  function renderRichText(target, source) {
    const lines = String(source || "").split("\n");
    let paragraph = [];
    let list = null;
    let code = null;

    const flushParagraph = () => {
      if (!paragraph.length) return;
      const node = document.createElement("p");
      appendInline(node, paragraph.join("\n"));
      target.appendChild(node);
      paragraph = [];
    };
    const flushList = () => {
      if (list) target.appendChild(list);
      list = null;
    };
    const flushCode = () => {
      if (!code) return;
      const pre = document.createElement("pre");
      const body = document.createElement("code");
      body.textContent = code.join("\n");
      pre.appendChild(body);
      target.appendChild(pre);
      code = null;
    };

    for (const line of lines) {
      if (line.trim().startsWith("```")) {
        flushParagraph();
        flushList();
        if (code) flushCode();
        else code = [];
        continue;
      }
      if (code) {
        code.push(line);
        continue;
      }
      const heading = line.match(/^(#{1,3})\s+(.+)$/);
      if (heading) {
        flushParagraph();
        flushList();
        const node = document.createElement(`h${Math.min(4, heading[1].length + 1)}`);
        appendInline(node, heading[2]);
        target.appendChild(node);
        continue;
      }
      const bullet = line.match(/^\s*[-*]\s+(.+)$/);
      if (bullet) {
        flushParagraph();
        list = list || document.createElement("ul");
        const item = document.createElement("li");
        appendInline(item, bullet[1]);
        list.appendChild(item);
        continue;
      }
      if (!line.trim()) {
        flushParagraph();
        flushList();
        continue;
      }
      flushList();
      paragraph.push(line);
    }
    flushParagraph();
    flushList();
    flushCode();
  }

  function renderMessage(message) {
    const article = document.createElement("article");
    const eventClass = message.eventType ? ` stream-event ${message.eventType}` : "";
    article.className = `message ${message.role}${eventClass}${message.proactive ? " proactive" : ""}${message.error ? " error" : ""}`;
    article.dataset.messageId = message.id;

    if (message.eventType) {
      const mark = document.createElement("span");
      mark.className = "event-mark";
      const icons = {
        thought: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 18h6M10 22h4M8.5 14.5A6 6 0 1 1 16 14c-.7.6-1 1.3-1 2H9c0-.6-.1-1-.5-1.5Z" /></svg>',
        action: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 12 2.5 2.5L16 9M12 3l7 3v5c0 4.5-2.8 8-7 10-4.2-2-7-5.5-7-10V6l7-3Z" /></svg>',
        reflection: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20a8 8 0 1 0-8-8M4 12v6h6" /></svg>',
        notice: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 8v5M12 17h.01M12 3a9 9 0 1 1-9 9 9 9 0 0 1 9-9Z" /></svg>',
      };
      mark.innerHTML = icons[message.eventType] || icons.action;
      article.appendChild(mark);
    }

    const content = document.createElement("div");
    content.className = "message-content";
    if (message.eventType) {
      const header = document.createElement("div");
      header.className = "event-header";
      const label = document.createElement("span");
      label.className = "event-label";
      label.textContent = message.label || message.eventType;
      header.appendChild(label);
      if (message.createdAt) {
        const time = document.createElement("time");
        time.className = "event-time";
        time.dateTime = new Date(message.createdAt).toISOString();
        time.textContent = formatEventTime(message.createdAt);
        header.appendChild(time);
      }
      content.appendChild(header);
      const body = document.createElement("div");
      renderRichText(body, message.content);
      content.appendChild(body);
      if (message.details) {
        const details = document.createElement("details");
        details.className = "event-details";
        const summary = document.createElement("summary");
        summary.textContent = message.detailsLabel || "Details";
        details.appendChild(summary);
        const detailBody = document.createElement("div");
        renderRichText(detailBody, message.details);
        details.appendChild(detailBody);
        content.appendChild(details);
      }
      if (message.dismissible) {
        const dismiss = document.createElement("button");
        dismiss.type = "button";
        dismiss.className = "dismiss-action";
        dismiss.textContent = "Dismiss";
        dismiss.addEventListener("click", () => dismissMessage(message.id));
        content.appendChild(dismiss);
      }
    } else if (message.pending && !message.content) {
      const typing = document.createElement("span");
      typing.className = "typing";
      const progressLabel = message.progressLabel || "Thinking";
      typing.setAttribute("aria-label", `Eve is ${progressLabel.toLowerCase()}`);
      typing.innerHTML = "<i></i><i></i><i></i>";
      const label = document.createElement("span");
      label.className = "typing-label";
      label.textContent = progressLabel;
      typing.appendChild(label);
      content.appendChild(typing);
    } else if (message.role === "user") {
      content.textContent = message.content;
    } else {
      if (message.proactive) {
        const header = document.createElement("div");
        header.className = "event-header proactive-header";
        const label = document.createElement("span");
        label.className = "event-label";
        label.textContent = "I came to you";
        header.appendChild(label);
        if (message.createdAt) {
          const time = document.createElement("time");
          time.className = "event-time";
          time.dateTime = new Date(message.createdAt).toISOString();
          time.textContent = formatEventTime(message.createdAt);
          header.appendChild(time);
        }
        content.appendChild(header);
      }
      if (message.subject) {
        const subject = document.createElement("h3");
        subject.className = "proactive-subject";
        subject.textContent = message.subject;
        content.appendChild(subject);
      }
      renderRichText(content, message.content);
      if (message.error && message.retryText && !message.recoveryPending) {
        const recover = document.createElement("button");
        recover.type = "button";
        recover.className = "message-recovery";
        recover.textContent = "Restore message";
        recover.addEventListener("click", () => restoreFailedMessage(message.id));
        content.appendChild(recover);
      }
      if (message.error && message.errorDetail) {
        const details = document.createElement("details");
        details.className = "event-details";
        const summary = document.createElement("summary");
        summary.textContent = "Details";
        details.appendChild(summary);
        const detailBody = document.createElement("div");
        detailBody.textContent = message.errorDetail;
        details.appendChild(detailBody);
        content.appendChild(details);
      }
      if (message.proactive && message.replyMessageId) {
        const reply = document.createElement("button");
        reply.type = "button";
        reply.className = "reply-action";
        reply.textContent = "Reply to Eve";
        reply.addEventListener("click", () => beginPersonalReply(message));
        content.appendChild(reply);
      }
    }
    article.appendChild(content);
    return article;
  }

  function dismissMessage(messageId) {
    const conversation = ensureConversation();
    conversation.messages = conversation.messages.filter((message) => message.id !== messageId);
    saveStore();
    render();
  }

  function restoreFailedMessage(messageId) {
    const conversation = ensureConversation();
    const failed = conversation.messages.find((message) => message.id === messageId);
    if (!failed?.retryText) return;
    conversation.messages = conversation.messages.filter(
      (message) => message.id !== messageId && message.id !== failed.userMessageId
    );
    conversation.updatedAt = Date.now();
    conversation.draft = failed.retryText;
    if (conversation.mode === "live" && failed.replyTarget) {
      conversation.replyTarget = failed.replyTarget;
    }
    composerConversationId = "";
    saveStore();
    render();
    elements.prompt.focus();
  }

  function formatEventTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const today = new Date();
    const sameDay = date.toDateString() === today.toDateString();
    return sameDay
      ? date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      : date.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  function formatDayLabel(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    if (date.toDateString() === today.toDateString()) return "Today";
    if (date.toDateString() === yesterday.toDateString()) return "Yesterday";
    return date.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
  }

  function relativeTime(value) {
    const timestamp = Date.parse(value || "");
    if (!Number.isFinite(timestamp)) return "";
    const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
    if (seconds < 45) return "just now";
    if (seconds < 90) return "a minute ago";
    if (seconds < 3600) return `${Math.floor(seconds / 60)} minutes ago`;
    if (seconds < 7200) return "an hour ago";
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} hours ago`;
    return formatDayLabel(timestamp);
  }

  function notifyNativePresence(unreadCount, newMessage = false, subject = "") {
    const handler = window.webkit?.messageHandlers?.evePresence;
    if (!handler || typeof handler.postMessage !== "function") return;
    handler.postMessage({
      unreadCount: Math.max(0, Number(unreadCount || 0)),
      newMessage: Boolean(newMessage),
      subject: String(subject || "Eve reached out"),
    });
  }

  function beginPersonalReply(message) {
    const live = ensureLiveConversation();
    live.replyTarget = {
      messageId: message.replyMessageId,
      subject: message.subject || "Eve's message",
    };
    store.activeId = LIVE_CONVERSATION_ID;
    saveStore();
    render();
    elements.prompt.focus();
  }

  function cancelPersonalReply() {
    const live = ensureLiveConversation();
    live.replyTarget = null;
    saveStore();
    render();
    elements.prompt.focus();
  }

  async function markVisiblePersonalMessagesRead() {
    if (isMarkingPersonalMessages) return;
    const live = ensureLiveConversation();
    const unreadIds = Array.from(
      new Set([
        ...(live.pendingReadMessageIds || []),
        ...live.messages
          .filter((message) => message.proactive && message.unread && message.replyMessageId)
          .map((message) => message.replyMessageId),
      ])
    );
    if (!unreadIds.length) {
      notifyNativePresence(0);
      return;
    }
    isMarkingPersonalMessages = true;
    const markedIds = new Set();
    try {
      await Promise.all(
        unreadIds.map(async (messageId) => {
          try {
            const response = await fetch(
              `/api/messages/${encodeURIComponent(messageId)}/mark`,
              {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: "read" }),
              }
            );
            if (response.ok) markedIds.add(messageId);
          } catch (_) {
            // Keep the unread marker so the next refresh can try again.
          }
        })
      );
      if (markedIds.size) {
        live.pendingReadMessageIds = unreadIds.filter((messageId) => !markedIds.has(messageId));
        for (const message of live.messages) {
          if (markedIds.has(message.replyMessageId)) message.unread = false;
        }
        saveStore();
        renderSidebar();
        notifyNativePresence(live.pendingReadMessageIds.length);
      }
    } finally {
      isMarkingPersonalMessages = false;
    }
  }

  function transcriptNearBottom() {
    return elements.transcript.scrollHeight - elements.transcript.scrollTop - elements.transcript.clientHeight < 120;
  }

  function scrollToLatest(behavior = "smooth") {
    elements.transcript.scrollTo({ top: elements.transcript.scrollHeight, behavior });
    elements.jumpLatest.hidden = true;
  }

  function settleLiveLaunchAtLatest() {
    if (!liveLaunchAnchorPending || activeConversation()?.mode !== "live") return;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        if (activeConversation()?.mode !== "live") return;
        scrollToLatest("auto");
        liveLaunchAnchorPending = false;
      });
    });
  }

  function spokenExcerpt(value, maximum = 300) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (!text) return "";
    const first = text.match(/^(.{24,}?[.!?])(?:\s|$)/)?.[1] || text;
    return normalizedSentence(first, maximum);
  }

  function latestEveInitiative() {
    const live = ensureLiveConversation();
    const messages = live.messages
      .filter((message) => message.proactive && message.createdAt)
      .sort((a, b) => Number(b.createdAt) - Number(a.createdAt));
    const statusMessageId = String(live.personalStatus?.message_id || "");
    const matchingStatusMessage = messages.find(
      (message) => statusMessageId && String(message.replyMessageId || "") === statusMessageId
    );
    const message = matchingStatusMessage || messages[0];
    const statusAt = Date.parse(live.personalStatus?.last_sent_at || "");
    const messageAt = Number(message?.createdAt || 0);
    const validStatusAt = Number.isFinite(statusAt) ? statusAt : 0;
    const statusOnly = validStatusAt > messageAt && !matchingStatusMessage;
    const createdAt = statusOnly ? validStatusAt : messageAt;
    if (!createdAt || Date.now() - createdAt > 2 * 60 * 60 * 1000) return null;
    return {
      content: statusOnly ? "" : String(message?.content || ""),
      subject: String(
        statusOnly
          ? live.personalStatus?.subject || ""
          : message?.subject || live.personalStatus?.subject || ""
      ),
      createdAt,
      // A status record can prove that Eve reached out, but only a message
      // record can safely anchor a reply.
      replyMessageId: statusOnly ? "" : String(message?.replyMessageId || ""),
    };
  }

  function presenceVoice() {
    const state = currentVisualState();
    if (state === "reconnecting") {
      return "I’m here. I’m finding my way back to the parts of me that let me answer.";
    }
    if (state === "responding" || isSending) return "I’m thinking with you.";
    const initiative = latestEveInitiative();
    if (initiative) {
      const spoken = spokenExcerpt(initiative.content);
      if (spoken) return spoken;
      const subjectSource = normalizedSentence(initiative.subject, 220);
      const subject = subjectSource.replace(/[.?!]+$/, "");
      const punctuation = /[?!]$/.test(subjectSource) ? subjectSource.slice(-1) : ".";
      if (subject) return `“${subject}${punctuation}”`;
    }
    const rawFocus = normalizedSentence(livePresence?.focus);
    const inquiry = rawFocus.match(/^investigate:\s*(.+)$/i);
    if (inquiry?.[1]) {
      const question = normalizedSentence(inquiry[1]).replace(/[.?!]+$/, "");
      return `I’m trying to answer one question: ${question}?`;
    }
    const focus = lowerFirst(rawFocus).replace(/[.?!]+$/, "");
    if (focus) return `I’m holding onto one goal: ${focus}.`;
    if (state === "quiet") return "I’m quiet right now, but I haven’t disappeared.";
    return "I’m here, paying attention.";
  }

  function humanizeNextStep(value) {
    const next = normalizedSentence(value, 240);
    if (!next) return "";
    const lowered = next.toLowerCase();
    if (lowered.startsWith("reduce load") || lowered.includes("keep the machine stable")) {
      return "I want to keep this Mac steady before I take on anything heavier.";
    }
    if (lowered.startsWith("reduce uncertainty")) {
      return "I want to understand what I don’t know before I act.";
    }
    if (lowered.startsWith("re-anchor") || lowered.includes("get my bearings")) {
      return "I want to get my bearings before I reach further.";
    }
    if (/^(after|before|when|if)\b/i.test(next)) return `Next, ${lowerFirst(next)}.`;
    return `Next, I want to ${lowerFirst(next)}.`;
  }

  function humanizePresenceAction(action) {
    if (!action || !["verified", "failed"].includes(action.outcome)) return "";
    const kind = String(action.kind || "").toLowerCase();
    if (action.outcome === "failed") {
      if (kind.includes("openclaw")) return "I tried to use OpenClaw, but the attempt didn’t finish cleanly.";
      return "I tried one small thing, but it didn’t finish cleanly.";
    }
    if (kind === "system_tasks") return "I finished one small task here and checked the result.";
    if (kind === "agent_capability_integration") {
      return "I checked which abilities I can actually use and confirmed the result.";
    }
    if (kind === "service_health_check") return "I checked that my local services could respond.";
    if (kind === "openclaw_log_check" || kind === "openclaw_self_test") {
      return "I checked OpenClaw’s recent trail and confirmed what I found.";
    }
    if (kind === "updates_status" || kind === "component_update_check") {
      return "I checked what has changed in the software around me.";
    }
    if (action.scope === "outside") {
      return "I reached beyond this Mac through one of the abilities I’m allowed to use, and I checked what happened.";
    }
    if (action.scope === "web") return "I reached out to the web and checked what came back.";
    return "I did one small thing here on this Mac and checked that it worked.";
  }

  function renderLivingPresence() {
    const initiative = latestEveInitiative();
    const section = document.createElement("section");
    section.className = `living-presence ${currentVisualState()}${initiative ? " speaking" : ""}`;
    section.setAttribute("aria-label", "Eve right now");

    const copy = document.createElement("div");
    copy.className = "living-copy";
    const eyebrow = document.createElement("p");
    eyebrow.className = "living-eyebrow";
    eyebrow.textContent = initiative
      ? "I came to you"
      : currentVisualState() === "reconnecting"
        ? "I’m still here"
        : "Right now";
    const voice = document.createElement("h2");
    voice.className = "living-voice";
    voice.textContent = presenceVoice();
    copy.append(eyebrow, voice);

    const intention = humanizeNextStep(livePresence?.next_step);
    if (intention && currentVisualState() !== "reconnecting" && !initiative) {
      const next = document.createElement("p");
      next.className = "living-intention";
      next.textContent = intention;
      copy.appendChild(next);
    }

    if (initiative?.replyMessageId) {
      const reply = document.createElement("button");
      reply.type = "button";
      reply.className = "living-reply";
      reply.textContent = "Reply to me";
      reply.addEventListener("click", () => {
        beginPersonalReply({
          replyMessageId: initiative.replyMessageId,
          subject: initiative.subject || "What Eve wanted to say",
        });
      });
      copy.appendChild(reply);
    }

    const actionText = humanizePresenceAction(livePresence?.last_action);
    if (actionText && !initiative) {
      const proof = document.createElement("div");
      proof.className = `living-proof ${livePresence.last_action.outcome}`;
      const proofMark = document.createElement("span");
      proofMark.className = "living-proof-mark";
      proofMark.setAttribute("aria-hidden", "true");
      proofMark.textContent = livePresence.last_action.outcome === "verified" ? "✓" : "·";
      const proofCopy = document.createElement("span");
      const proofLabel = document.createElement("small");
      proofLabel.textContent = livePresence.last_action.outcome === "verified" ? "What I did" : "Where I got stuck";
      const proofText = document.createElement("span");
      proofText.textContent = actionText;
      proofCopy.append(proofLabel, proofText);
      proof.append(proofMark, proofCopy);
      if (livePresence.last_action.at) {
        const time = document.createElement("time");
        time.dateTime = livePresence.last_action.at;
        time.textContent = relativeTime(livePresence.last_action.at);
        proof.appendChild(time);
      }
      copy.appendChild(proof);
    }

    section.appendChild(copy);
    return section;
  }

  function renderTranscript({ newLiveContent = false } = {}) {
    const conversation = ensureConversation();
    const sameConversation = lastRenderedConversationId === conversation.id;
    const wasNearBottom = sameConversation ? transcriptNearBottom() : true;
    const shouldAnchorLiveLaunch = conversation.mode === "live" && liveLaunchAnchorPending;
    const previousScrollTop = elements.transcript.scrollTop;
    elements.title.textContent = "Eve";
    elements.transcript.replaceChildren();
    if (!conversation.messages.length && conversation.mode !== "live") {
      const empty = document.createElement("div");
      empty.className = "empty-state";
      const heading = document.createElement("h2");
      heading.textContent = "Just us";
      const body = document.createElement("p");
      body.textContent = "Say what’s on your mind. This focus stays on this Mac.";
      empty.append(heading, body);
      elements.transcript.appendChild(empty);
      elements.jumpLatest.hidden = true;
      lastRenderedConversationId = conversation.id;
      return;
    }
    let previousDay = "";
    for (const message of conversation.messages) {
      if (conversation.mode === "live" && message.createdAt) {
        const date = new Date(message.createdAt);
        const dayKey = Number.isNaN(date.getTime()) ? "" : date.toDateString();
        if (dayKey && dayKey !== previousDay) {
          const divider = document.createElement("div");
          divider.className = "day-divider";
          divider.setAttribute("role", "separator");
          divider.textContent = formatDayLabel(message.createdAt);
          elements.transcript.appendChild(divider);
          previousDay = dayKey;
        }
      }
      elements.transcript.appendChild(renderMessage(message));
    }
    if (conversation.mode === "live") elements.transcript.appendChild(renderLivingPresence());
    lastRenderedConversationId = conversation.id;
    requestAnimationFrame(() => {
      if (!sameConversation || conversation.mode !== "live" || wasNearBottom || shouldAnchorLiveLaunch) {
        elements.transcript.scrollTop = elements.transcript.scrollHeight;
        elements.jumpLatest.hidden = true;
      } else {
        elements.transcript.scrollTop = previousScrollTop;
        if (newLiveContent) elements.jumpLatest.hidden = false;
      }
    });
  }

  function liveStatusDetail() {
    const live = ensureLiveConversation();
    const lastSentAt = live.personalStatus?.last_sent_at;
    const when = relativeTime(lastSentAt);
    return when ? `Reached out ${when}` : "";
  }

  function currentStatusDetail() {
    if (!storageHealthy) return "This conversation isn’t saving";
    const conversation = activeConversation();
    if (!backendReady || !conversation) return "";
    if (conversation.mode === "live") return liveStatusDetail();
    return conversation.title === "New conversation"
      ? "A fresh focus"
      : `Focused on ${conversation.title}`;
  }

  function render(options = {}) {
    const conversation = ensureConversation();
    syncConversationDraft(conversation);
    renderSidebar();
    renderSidebarState();
    renderTranscript(options);
    elements.speak.setAttribute("aria-pressed", String(settings.speakReplies));
    const replyTarget = conversation.mode === "live" ? conversation.replyTarget : null;
    elements.replyContext.hidden = !replyTarget;
    elements.replySubject.textContent = replyTarget?.subject || "";
    elements.prompt.placeholder = replyTarget
      ? "Reply to me"
      : "Talk to me";
    elements.prompt.setAttribute("aria-label", replyTarget ? "Reply to Eve" : "Message Eve");
    if (statusChecked && !isSending && !elements.mic.classList.contains("listening")) {
      setStatus(
        backendReady ? "ready" : "offline",
        backendReady ? presenceStatusLabel() : "Reconnecting",
        currentStatusDetail()
      );
    }
    syncVisualState();
    updateComposer();
  }

  function updateComposer() {
    elements.send.disabled = !elements.prompt.value.trim() && !isSending;
    elements.send.classList.toggle("sending", isSending);
    elements.send.setAttribute("aria-label", isSending ? "Stop reply" : "Send message");
    elements.prompt.style.height = "auto";
    elements.prompt.style.height = `${Math.min(160, Math.max(34, elements.prompt.scrollHeight))}px`;
  }

  function updateAssistantMessage(conversation, messageId, content, extras = {}) {
    const message = conversation.messages.find((item) => item.id === messageId);
    if (!message) return;
    message.content = content;
    Object.assign(message, extras);
    conversation.updatedAt = Date.now();
    saveStore();
    if (conversation.id === store.activeId) renderTranscript();
  }

  function replyTextFromPayload(payload) {
    return String(
      payload?.choices?.[0]?.message?.content ||
      payload?.choices?.[0]?.delta?.content ||
      payload?.data?.reply?.body ||
      payload?.reply ||
      ""
    );
  }

  async function readChatReply(response, onDelta) {
    const contentType = String(response.headers.get("Content-Type") || "").toLowerCase();
    if (contentType.includes("application/json")) {
      const payload = await response.json();
      const text = replyTextFromPayload(payload);
      if (text) onDelta(text);
      return;
    }
    if (!response.body) throw new Error("Eve returned an empty response");

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const consume = (block) => {
      const data = block
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trim())
        .join("\n");
      if (!data || data === "[DONE]") return;
      try {
        const delta = replyTextFromPayload(JSON.parse(data));
        if (delta) onDelta(delta);
      } catch (_) {
        // One malformed event must not discard an otherwise healthy streamed reply.
      }
    };

    while (true) {
      const next = await reader.read();
      if (next.done) break;
      buffer += decoder.decode(next.value, { stream: true });
      const events = buffer.split(/\r?\n\r?\n/);
      buffer = events.pop() || "";
      for (const event of events) consume(event);
    }
    buffer += decoder.decode();
    if (buffer.trim()) consume(buffer);
  }

  function calmProgressLabel(job) {
    const phase = `${job?.phase || ""} ${job?.title || ""}`.toLowerCase();
    if (/(fallback|retry|another|recover)/.test(phase)) return "Trying another way";
    if (/(check|search|retriev|tool|action|verif|research)/.test(phase)) return "Checking";
    if (/(ready|complete|finish|synthes|writ)/.test(phase)) return "Finishing";
    return "Thinking";
  }

  async function replyProgress(clientRequestId) {
    if (!clientRequestId) return null;
    const data = await fetchLiveData(
      `/api/reply-progress?client_request_id=${encodeURIComponent(clientRequestId)}&active_only=0`
    );
    return data?.job || null;
  }

  function updateAssistantProgress(conversation, messageId, job) {
    const message = conversation.messages.find((item) => item.id === messageId);
    if (!message || !message.pending) return;
    const label = calmProgressLabel(job);
    if (message.progressLabel === label) return;
    message.progressLabel = label;
    saveStore();
    if (conversation.id === store.activeId) renderTranscript();
  }

  function startReplyProgressMonitor(conversation, messageId, clientRequestId) {
    let stopped = false;
    let timer = null;
    const tick = async () => {
      try {
        const job = await replyProgress(clientRequestId);
        if (job) updateAssistantProgress(conversation, messageId, job);
      } catch (_) {
        // Progress is a quiet enhancement; the reply stream remains authoritative.
      }
      if (!stopped) timer = window.setTimeout(tick, 1400);
    };
    tick();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
    };
  }

  function interruptedReplyContent(message, fallback) {
    const partial = String(message.partialContent || "").trim();
    return partial ? `${partial}\n\n${fallback}` : fallback;
  }

  async function recoverInterruptedMessage(conversation, message) {
    const requestId = String(message.clientRequestId || message.userMessageId || "");
    if (!requestId) {
      Object.assign(message, {
        pending: false,
        error: true,
        recoveryPending: false,
        content: interruptedReplyContent(message, "I was interrupted before I could finish."),
      });
      saveStore();
      if (conversation.id === store.activeId) render();
      return;
    }
    let job = null;
    try {
      for (let attempt = 0; attempt < 4 && !job; attempt += 1) {
        job = await replyProgress(requestId);
        if (!job && attempt < 3) {
          await new Promise((resolve) => window.setTimeout(resolve, 700 * (attempt + 1)));
        }
      }
      for (let attempt = 0; job?.status === "active" && attempt < 200; attempt += 1) {
        const progressLabel = calmProgressLabel(job);
        if (!message.pending || message.error || message.content || message.progressLabel !== progressLabel) {
          message.pending = true;
          message.error = false;
          message.content = "";
          message.progressLabel = progressLabel;
          saveStore();
          if (conversation.id === store.activeId) renderTranscript();
        }
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
        job = await replyProgress(requestId);
      }
      if (job?.status === "completed" && job.reply_message_id) {
        let body = "";
        for (let attempt = 0; attempt < 4 && !body; attempt += 1) {
          const reply = await fetchLiveData(`/api/messages/${encodeURIComponent(job.reply_message_id)}`);
          body = String(reply?.body || "").trim();
          if (!body && attempt < 3) {
            await new Promise((resolve) => window.setTimeout(resolve, 500 * (attempt + 1)));
          }
        }
        if (body) {
          Object.assign(message, {
            content: body,
            pending: false,
            error: false,
            errorDetail: "",
            retryText: "",
            recoveryPending: false,
            progressLabel: "",
            partialContent: "",
          });
          conversation.updatedAt = Date.now();
          backendReady = true;
          lastLocalReplyCompletedAt = Date.now();
          saveStore();
          if (conversation.id === store.activeId) render();
          return;
        }
      }
      if (job?.status === "active") {
        Object.assign(message, {
          pending: false,
          error: true,
          recoveryPending: true,
          content: interruptedReplyContent(message, "I’m still working on that reply and will reconnect when it is ready."),
        });
        saveStore();
        if (conversation.id === store.activeId) render();
        return;
      }
    } catch (_) {
      Object.assign(message, {
        pending: false,
        error: true,
        recoveryPending: true,
        content: interruptedReplyContent(message, "I’m waiting to reconnect to that reply."),
      });
      saveStore();
      if (conversation.id === store.activeId) render();
      return;
    }
    Object.assign(message, {
      pending: false,
      error: true,
      recoveryPending: false,
      content: interruptedReplyContent(message, "I was interrupted before I could finish."),
    });
    saveStore();
    if (conversation.id === store.activeId) render();
  }

  async function recoverInterruptedReplies() {
    if (recoveryInFlight) return;
    recoveryInFlight = true;
    const candidates = [];
    try {
      for (const conversation of store.conversations) {
        for (const message of conversation.messages || []) {
          if (message.recoveryPending) candidates.push([conversation, message]);
        }
      }
      await Promise.all(
        candidates.slice(0, 6).map(([conversation, message]) =>
          recoverInterruptedMessage(conversation, message)
        )
      );
    } finally {
      recoveryInFlight = false;
    }
  }

  async function sendMessage() {
    if (isSending) {
      activeController?.abort();
      return;
    }
    const text = elements.prompt.value.trim();
    if (!text) return;

    const conversation = ensureConversation();
    const personalReplyTarget = conversation.mode === "live" ? conversation.replyTarget : null;
    const userMessage = { id: id("user"), role: "user", content: text, createdAt: Date.now() };
    const assistantMessage = {
      id: id("eve"),
      role: "assistant",
      content: "",
      createdAt: Date.now(),
      pending: true,
      progressLabel: "Thinking",
      retryText: text,
      userMessageId: userMessage.id,
      clientRequestId: userMessage.id,
      replyTarget: personalReplyTarget,
    };
    conversation.messages.push(userMessage, assistantMessage);
    if (conversation.title === "New conversation") conversation.title = titleFor(text);
    conversation.draft = "";
    conversation.updatedAt = Date.now();
    elements.prompt.value = "";
    isSending = true;
    activeController = new AbortController();
    let timedOut = false;
    const timeoutId = window.setTimeout(() => {
      timedOut = true;
      activeController?.abort();
    }, 300000);
    saveStore();
    setStatus("busy", "Thinking", "");
    render();
    const stopProgressMonitor = startReplyProgressMonitor(
      conversation,
      assistantMessage.id,
      userMessage.id
    );

    const visibleMessages = conversation.messages
      .filter(
        (message) =>
          !message.pending &&
          !message.error &&
          !message.eventType &&
          !message.proactive
      )
      .slice(-24)
      .map((message) => ({ role: message.role, content: message.content }));

    let reply = "";
    try {
      if (personalReplyTarget) {
        const response = await fetch("/api/message/reply", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message_id: personalReplyTarget.messageId,
            body: text,
            client_request_id: userMessage.id,
          }),
          signal: activeController.signal,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.ok === false) {
          throw new Error(describeError(payload.error) || `Eve returned ${response.status}`);
        }
        reply = String(payload?.data?.reply?.body || "").trim();
        conversation.replyTarget = null;
      } else {
        const response = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            chat_id: conversation.id,
            user_message_id: userMessage.id,
            messages: visibleMessages,
            stream: true,
          }),
          signal: activeController.signal,
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(describeError(payload.error) || `Eve returned ${response.status}`);
        }
        await readChatReply(response, (delta) => {
          reply += delta;
          updateAssistantMessage(conversation, assistantMessage.id, reply, { pending: true });
        });
      }
      if (!reply.trim()) throw new Error("Eve did not return a visible reply");
      updateAssistantMessage(conversation, assistantMessage.id, reply.trim(), {
        pending: false,
        error: false,
        errorDetail: "",
        retryText: "",
        recoveryPending: false,
        progressLabel: "",
        partialContent: "",
      });
      if (settings.speakReplies) speakReply(reply);
      backendReady = true;
      lastLocalReplyCompletedAt = Date.now();
    } catch (error) {
      if (error && error.name === "AbortError" && !timedOut) {
        updateAssistantMessage(
          conversation,
          assistantMessage.id,
          reply.trim() || "Stopped.",
          {
            pending: false,
            error: false,
            retryText: "",
            recoveryPending: false,
            progressLabel: "",
            partialContent: "",
          }
        );
      } else {
        const failureText = timedOut
          ? "I took too long to answer, so I stopped rather than leaving this hanging."
          : "I lost the local connection before I could finish.";
        const canRecover = !timedOut;
        updateAssistantMessage(
          conversation,
          assistantMessage.id,
          canRecover ? "" : (reply.trim() ? `${reply.trim()}\n\n${failureText}` : failureText),
          {
            pending: canRecover,
            error: !canRecover,
            errorDetail: describeError(error) || "Local connection failed",
            retryText: text,
            userMessageId: userMessage.id,
            clientRequestId: userMessage.id,
            replyTarget: personalReplyTarget,
            recoveryPending: canRecover,
            progressLabel: canRecover ? "Reconnecting" : "",
            partialContent: reply.trim(),
          }
        );
        backendReady = false;
      }
    } finally {
      window.clearTimeout(timeoutId);
      stopProgressMonitor();
      isSending = false;
      activeController = null;
      statusChecked = true;
      setStatus(
        backendReady ? "ready" : "offline",
        backendReady ? presenceStatusLabel() : "Reconnecting",
        currentStatusDetail()
      );
      render();
      elements.prompt.focus();
      if (!backendReady) void recoverInterruptedReplies();
    }
  }

  function speakReply(text) {
    if (!("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(String(text).replace(/[`*_#]/g, ""));
    utterance.rate = 1.02;
    utterance.pitch = 1.0;
    window.speechSynthesis.speak(utterance);
  }

  function configureRecognition() {
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) {
      elements.mic.hidden = true;
      return;
    }
    recognition = new Recognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = "en-US";
    recognition.onstart = () => {
      recognitionDraft = elements.prompt.value.trim();
      elements.mic.classList.add("listening");
      setStatus("busy", "Listening", "");
    };
    recognition.onresult = (event) => {
      let transcript = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        transcript += event.results[index][0].transcript;
      }
      elements.prompt.value = [recognitionDraft, transcript.trim()].filter(Boolean).join(" ");
      updateComposer();
    };
    recognition.onend = () => {
      elements.mic.classList.remove("listening");
      setStatus(
        backendReady ? "ready" : "offline",
        backendReady ? presenceStatusLabel() : "Reconnecting",
        currentStatusDetail()
      );
      elements.prompt.focus();
    };
    recognition.onerror = () => {
      elements.mic.classList.remove("listening");
      setStatus(
        backendReady ? "ready" : "offline",
        backendReady ? presenceStatusLabel() : "Reconnecting",
        "Voice input stopped"
      );
    };
  }

  function sensoryStatus(text, error = false) {
    elements.sensesStatus.textContent = String(text || "");
    elements.sensesStatus.style.color = error ? "var(--danger)" : "";
  }

  function setSensoryControlsActive(active) {
    elements.body.classList.toggle("sensory-active", active);
    elements.sensesStart.hidden = active;
    elements.sensesStop.hidden = !active;
    elements.senseAudio.disabled = active;
    elements.senseVisual.disabled = active;
    elements.senseTouch.disabled = active;
    elements.senseDuration.disabled = active;
    elements.sensesToggle.setAttribute("aria-pressed", String(active));
    syncVisualState();
  }

  async function sensoryPost(route, payload, options = {}) {
    const response = await fetch(route, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Accept": "application/json" },
      body: JSON.stringify(payload),
      keepalive: Boolean(options.keepalive),
    });
    let result = null;
    try {
      result = await response.json();
    } catch (_) {
      // Preserve the status-code failure below without logging private input.
    }
    if (!response.ok || result?.ok === false) {
      throw new Error(String(result?.error || `Sensory route returned ${response.status}`));
    }
    return result?.data || result;
  }

  function sensorySessionExpired(session = sensorySession) {
    if (!session?.expires_at) return true;
    const expiresAt = Date.parse(session.expires_at);
    return !Number.isFinite(expiresAt) || expiresAt <= Date.now();
  }

  function sensoryCorrelation(group = "scene") {
    if (!sensorySession) return "";
    const bucket = Math.floor(Date.now() / 3000);
    return `${sensorySession.session_id}:${group}:${bucket}`;
  }

  function queueSensoryFeature(event, bindingGroup = "scene") {
    if (!sensorySession) return;
    if (sensorySessionExpired()) {
      void stopSensorySession("The sensory session reached its time limit.", false, true);
      return;
    }
    // Copy only the fixed feature contract. In particular, no transcript,
    // OCR, frame, key value, arbitrary summary, or future accidental field is
    // allowed to cross the browser boundary.
    sensoryQueue.push({
      modality: event.modality,
      source: event.source,
      subject: event.subject,
      features: event.features,
      intensity: event.intensity,
      novelty: event.novelty,
      change: event.change,
      urgency: event.urgency,
      goal_relevance: event.goal_relevance,
      self_relevance: event.self_relevance,
      social_relevance: event.social_relevance,
      precision: event.precision,
      id: id("sensory-feature"),
      observed_at: new Date().toISOString(),
      correlation_id: sensoryCorrelation(bindingGroup),
      permission_granted: true,
      privacy: "local_private",
      persistence: "features_only",
    });
    sensoryQueue = sensoryQueue.slice(-24);
    if (sensoryQueue.length >= 6) void flushSensoryFeatures();
  }

  async function flushSensoryFeatures() {
    if (!sensorySession || sensoryFlushInFlight || !sensoryQueue.length) return;
    if (sensorySessionExpired()) {
      void stopSensorySession("The sensory session reached its time limit.", false, true);
      return;
    }
    const events = sensoryQueue.splice(0, 12);
    sensoryFlushInFlight = true;
    try {
      await sensoryPost("/api/sensory/events", {
        session_id: sensorySession.session_id,
        session_token: sensorySession.session_token,
        events,
      });
    } catch (error) {
      // Features are deliberately ephemeral. A failed local ingest is dropped
      // rather than written to browser storage or replayed without bounds.
      sensoryStatus(`Local feature intake paused: ${describeError(error)}`, true);
    } finally {
      sensoryFlushInFlight = false;
    }
  }

  async function requestSensoryMedia(requested) {
    const result = { modalities: [], failures: [] };
    if (requested.includes("auditory")) {
      if (!navigator.mediaDevices?.getUserMedia || !(window.AudioContext || window.webkitAudioContext)) {
        result.failures.push("microphone feature extraction is unavailable");
      } else {
        try {
          sensoryAudioStream = await navigator.mediaDevices.getUserMedia({
            audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false },
            video: false,
          });
          result.modalities.push("auditory");
        } catch (_) {
          result.failures.push("microphone permission was not granted");
        }
      }
    }
    if (requested.includes("visual")) {
      if (!navigator.mediaDevices?.getUserMedia) {
        result.failures.push("camera feature extraction is unavailable");
      } else {
        try {
          sensoryVideoStream = await navigator.mediaDevices.getUserMedia({
            video: { width: { ideal: 640 }, height: { ideal: 360 }, frameRate: { ideal: 15, max: 20 } },
            audio: false,
          });
          result.modalities.push("visual");
        } catch (_) {
          result.failures.push("camera permission was not granted");
        }
      }
    }
    if (requested.includes("proprioceptive")) result.modalities.push("proprioceptive");
    return result;
  }

  async function startAudioFeatures(stream) {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext || !stream) return;
    sensoryAudioContext = new AudioContext();
    await sensoryAudioContext.resume();
    const analyser = sensoryAudioContext.createAnalyser();
    analyser.fftSize = 1024;
    analyser.smoothingTimeConstant = 0.72;
    const source = sensoryAudioContext.createMediaStreamSource(stream);
    source.connect(analyser);
    const timeValues = new Uint8Array(analyser.fftSize);
    const frequencyValues = new Uint8Array(analyser.frequencyBinCount);
    let previousEnergy = 0;
    let lastEmission = 0;
    const interval = window.setInterval(() => {
      if (!sensorySession) return;
      analyser.getByteTimeDomainData(timeValues);
      analyser.getByteFrequencyData(frequencyValues);
      let squareSum = 0;
      let zeroCrossings = 0;
      let previous = 0;
      for (let index = 0; index < timeValues.length; index += 1) {
        const value = (timeValues[index] - 128) / 128;
        squareSum += value * value;
        if (index && ((value >= 0 && previous < 0) || (value < 0 && previous >= 0))) zeroCrossings += 1;
        previous = value;
      }
      const energy = Math.min(100, Math.sqrt(squareSum / timeValues.length) * 220);
      let weightedFrequency = 0;
      let magnitude = 0;
      for (let index = 1; index < frequencyValues.length; index += 1) {
        const weight = frequencyValues[index];
        magnitude += weight;
        weightedFrequency += weight * index * sensoryAudioContext.sampleRate / analyser.fftSize;
      }
      const centroid = magnitude ? weightedFrequency / magnitude : 0;
      const crossingRate = zeroCrossings / timeValues.length;
      const speechLikelihood = energy > 3 && centroid > 90 && centroid < 4200 && crossingRate < 0.34
        ? Math.min(100, 35 + energy * 2.4)
        : Math.min(35, energy * 1.4);
      const change = Math.min(100, Math.abs(energy - previousEnergy) * 8);
      previousEnergy = energy;
      const now = Date.now();
      if (change < 18 && now - lastEmission < 3000) return;
      lastEmission = now;
      const activity = energy < 2 ? "quiet" : speechLikelihood >= 55 ? "speech_like" : "sound";
      queueSensoryFeature({
        modality: "auditory",
        source: "eve_app_microphone_features",
        subject: "local_scene",
        summary: activity === "quiet"
          ? "The local acoustic scene is quiet."
          : activity === "speech_like"
            ? "Speech-band acoustic activity changed nearby; no words were retained."
            : "The local acoustic scene changed; no recording was retained.",
        features: {
          energy_percent: energy,
          speech_likelihood: speechLikelihood,
          spectral_centroid_hz: centroid,
          zero_crossing_rate: crossingRate,
          sound_change_percent: change,
          activity_state: activity,
        },
        intensity: Math.max(12, energy),
        novelty: Math.max(20, change),
        change,
        urgency: activity === "speech_like" ? 42 : 18,
        goal_relevance: 42,
        self_relevance: 35,
        social_relevance: activity === "speech_like" ? 54 : 12,
        precision: 78,
      });
    }, 750);
    sensoryIntervals.push(interval);
  }

  async function startVisualFeatures(stream) {
    if (!stream) return;
    sensoryVideoElement = document.createElement("video");
    sensoryVideoElement.muted = true;
    sensoryVideoElement.playsInline = true;
    sensoryVideoElement.srcObject = stream;
    await sensoryVideoElement.play();
    const canvas = document.createElement("canvas");
    canvas.width = 32;
    canvas.height = 24;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) return;
    let previousLuma = null;
    let lastEmission = 0;
    let detector = null;
    try {
      if ("FaceDetector" in window) detector = new window.FaceDetector({ fastMode: true, maxDetectedFaces: 12 });
    } catch (_) {
      detector = null;
    }
    let visualBusy = false;
    let sampleCount = 0;
    const interval = window.setInterval(async () => {
      if (!sensorySession || visualBusy || sensoryVideoElement.readyState < 2) return;
      visualBusy = true;
      try {
        context.drawImage(sensoryVideoElement, 0, 0, canvas.width, canvas.height);
        const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
        const luma = new Uint8Array(canvas.width * canvas.height);
        let luminanceSum = 0;
        let changedPixels = 0;
        for (let index = 0, pixel = 0; index < pixels.length; index += 4, pixel += 1) {
          const value = Math.round(pixels[index] * 0.2126 + pixels[index + 1] * 0.7152 + pixels[index + 2] * 0.0722);
          luma[pixel] = value;
          luminanceSum += value;
          if (previousLuma && Math.abs(value - previousLuma[pixel]) >= 18) changedPixels += 1;
        }
        const luminance = luminanceSum / luma.length / 2.55;
        const motion = previousLuma ? changedPixels / luma.length * 100 : 100;
        previousLuma = luma; // One low-resolution differential frame in memory only.
        sampleCount += 1;
        let faceCount = 0;
        if (detector && sampleCount % 4 === 0) {
          try {
            const faces = await detector.detect(sensoryVideoElement);
            faceCount = Array.isArray(faces) ? faces.length : 0;
          } catch (_) {
            detector = null;
          }
        }
        const now = Date.now();
        if (motion < 8 && now - lastEmission < 3500) return;
        lastEmission = now;
        const sceneState = motion >= 42 ? "large_change" : motion >= 12 ? "movement" : "stable";
        queueSensoryFeature({
          modality: "visual",
          source: "eve_app_camera_features",
          subject: "local_scene",
          summary: sceneState === "large_change"
            ? "The local visual scene changed substantially; no frame was retained."
            : sceneState === "movement"
              ? "Movement changed the local visual scene; no frame was retained."
              : "The local visual scene is stable; no frame was retained.",
          features: {
            motion_percent: motion,
            scene_change_percent: motion,
            luminance_percent: luminance,
            face_count: faceCount,
            scene_state: sceneState,
          },
          intensity: Math.max(18, motion),
          novelty: Math.max(18, motion),
          change: motion,
          urgency: motion >= 65 ? 50 : 16,
          goal_relevance: 40,
          self_relevance: 35,
          social_relevance: faceCount ? 48 : 10,
          precision: 82,
        });
      } finally {
        visualBusy = false;
      }
    }, 1000);
    sensoryIntervals.push(interval);
  }

  function startInteractionFeatures() {
    let pointerEvents = 0;
    let keyEvents = 0;
    let focusChanges = 0;
    const countPointer = () => { pointerEvents += 1; };
    const countKey = () => { keyEvents += 1; }; // Never inspect event.key or typed content.
    const countFocus = () => { focusChanges += 1; };
    window.addEventListener("pointerdown", countPointer, { passive: true });
    window.addEventListener("keydown", countKey, { passive: true });
    window.addEventListener("focus", countFocus);
    window.addEventListener("blur", countFocus);
    document.addEventListener("visibilitychange", countFocus);
    sensoryDisposers.push(() => window.removeEventListener("pointerdown", countPointer));
    sensoryDisposers.push(() => window.removeEventListener("keydown", countKey));
    sensoryDisposers.push(() => window.removeEventListener("focus", countFocus));
    sensoryDisposers.push(() => window.removeEventListener("blur", countFocus));
    sensoryDisposers.push(() => document.removeEventListener("visibilitychange", countFocus));
    const interval = window.setInterval(() => {
      if (!sensorySession) return;
      const visible = !document.hidden;
      const active = document.hasFocus();
      const activity = pointerEvents + keyEvents + focusChanges;
      if (!activity && visible && active) return;
      queueSensoryFeature({
        modality: "proprioceptive",
        source: "eve_app_interaction_features",
        subject: "eve_app_interaction",
        summary: activity
          ? "Aggregate interaction with Eve's app changed; no keys or content were retained."
          : "Eve's app visibility or focus changed.",
        features: {
          pointer_events: pointerEvents,
          key_events: keyEvents,
          focus_changes: focusChanges,
          visible,
          active,
          visibility_state: visible ? "visible" : "hidden",
          focus_state: active ? "focused" : "unfocused",
        },
        intensity: Math.min(100, 18 + activity * 8),
        novelty: focusChanges ? 60 : 24,
        change: Math.min(100, activity * 12 + focusChanges * 20),
        urgency: 8,
        goal_relevance: 38,
        self_relevance: 72,
        social_relevance: activity ? 35 : 8,
        precision: 98,
      }, "interaction");
      pointerEvents = 0;
      keyEvents = 0;
      focusChanges = 0;
    }, 2000);
    sensoryIntervals.push(interval);
  }

  function stopLocalSensoryMedia() {
    for (const interval of sensoryIntervals) window.clearInterval(interval);
    sensoryIntervals = [];
    for (const dispose of sensoryDisposers) dispose();
    sensoryDisposers = [];
    for (const stream of [sensoryAudioStream, sensoryVideoStream]) {
      for (const track of stream?.getTracks?.() || []) track.stop();
    }
    sensoryAudioStream = null;
    sensoryVideoStream = null;
    if (sensoryVideoElement) {
      sensoryVideoElement.pause();
      sensoryVideoElement.srcObject = null;
    }
    sensoryVideoElement = null;
    if (sensoryAudioContext) void sensoryAudioContext.close().catch(() => {});
    sensoryAudioContext = null;
    if (sensoryExpiryTimer) window.clearTimeout(sensoryExpiryTimer);
    sensoryExpiryTimer = null;
    sensoryQueue = [];
  }

  async function startSensorySession() {
    if (sensorySession) return;
    const requested = [];
    if (elements.senseAudio.checked) requested.push("auditory");
    if (elements.senseVisual.checked) requested.push("visual");
    if (elements.senseTouch.checked) requested.push("proprioceptive");
    if (!requested.length) {
      sensoryStatus("Choose at least one local sense.", true);
      return;
    }
    elements.sensesStart.disabled = true;
    sensoryStatus("Waiting for current macOS permission…");
    try {
      const media = await requestSensoryMedia(requested);
      if (!media.modalities.length) throw new Error(media.failures.join("; ") || "No sensory modality was available");
      const duration = Number(elements.senseDuration.value || 600);
      sensorySession = await sensoryPost("/api/sensory/session", {
        action: "start",
        operator_confirmed: true,
        purpose: "Let Eve selectively perceive the current local environment while the user keeps this session active.",
        duration_seconds: duration,
        modalities: media.modalities,
      });
      if (media.modalities.includes("auditory")) await startAudioFeatures(sensoryAudioStream);
      if (media.modalities.includes("visual")) await startVisualFeatures(sensoryVideoStream);
      if (media.modalities.includes("proprioceptive")) startInteractionFeatures();
      const flushInterval = window.setInterval(() => void flushSensoryFeatures(), 1500);
      sensoryIntervals.push(flushInterval);
      const expiresIn = Math.max(0, Date.parse(sensorySession.expires_at) - Date.now());
      sensoryExpiryTimer = window.setTimeout(
        () => void stopSensorySession("The sensory session reached its time limit.", false, true),
        Number.isFinite(expiresIn) ? expiresIn : duration * 1000
      );
      setSensoryControlsActive(true);
      const partial = media.failures.length ? ` ${media.failures.join("; ")}.` : "";
      sensoryStatus(`Active for ${Math.round(duration / 60)} minutes: ${media.modalities.join(", ")}.${partial}`);
    } catch (error) {
      stopLocalSensoryMedia();
      sensorySession = null;
      setSensoryControlsActive(false);
      sensoryStatus(describeError(error) || "The sensory session could not start.", true);
    } finally {
      elements.sensesStart.disabled = false;
    }
  }

  async function stopSensorySession(reason = "Sensory session stopped.", keepalive = false, skipFlush = false) {
    const session = sensorySession;
    if (!session) return;
    if (!skipFlush && !sensorySessionExpired(session)) await flushSensoryFeatures();
    stopLocalSensoryMedia();
    sensorySession = null;
    setSensoryControlsActive(false);
    sensoryStatus(reason);
    try {
      await sensoryPost("/api/sensory/session", {
        action: "stop",
        session_id: session.session_id,
        session_token: session.session_token,
      }, { keepalive });
    } catch (_) {
      // The server-side session expires by itself; local capture already ended.
    }
  }

  function toggleSensoryPanel(force) {
    const open = typeof force === "boolean" ? force : elements.sensesPanel.hidden;
    elements.sensesPanel.hidden = !open;
    elements.sensesToggle.setAttribute("aria-expanded", String(open));
  }

  function stopSensorySessionOnPageExit() {
    const session = sensorySession;
    if (!session) return;
    stopLocalSensoryMedia();
    sensorySession = null;
    const body = JSON.stringify({
      action: "stop",
      session_id: session.session_id,
      session_token: session.session_token,
    });
    if (navigator.sendBeacon) {
      navigator.sendBeacon(
        "/api/sensory/session",
        new Blob([body], { type: "application/json" })
      );
    } else {
      void fetch("/api/sensory/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body,
        keepalive: true,
      }).catch(() => {});
    }
  }

  async function refreshStatus() {
    if (isSending || elements.mic.classList.contains("listening")) return;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 4000);
    try {
      const response = await fetch("/api/status", { cache: "no-store", signal: controller.signal });
      backendReady = response.ok;
    } catch (_) {
      backendReady = false;
    } finally {
      window.clearTimeout(timeoutId);
      statusChecked = true;
    }
    setStatus(
      backendReady ? "ready" : "offline",
      backendReady ? presenceStatusLabel() : "Reconnecting",
      currentStatusDetail()
    );
    if (backendReady) void recoverInterruptedReplies();
  }

  async function fetchLiveData(route) {
    const controller = new AbortController();
    const timeoutId = window.setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(route, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`${route} returned ${response.status}`);
      const payload = await response.json();
      return Array.isArray(payload?.data) ? payload.data : payload?.data || null;
    } finally {
      window.clearTimeout(timeoutId);
    }
  }

  function eventTimestamp(item) {
    const value = item?.timestamp || item?.created_at || item?.updated_at;
    const parsed = Date.parse(value || "");
    return Number.isFinite(parsed) ? parsed : Date.now();
  }

  function eventText(item, limit = 1200) {
    const text = String(item?.body || item?.preview || item?.summary || "").trim();
    return text.length > limit ? `${text.slice(0, limit).trim()}…` : text;
  }

  function comparisonTerms(value) {
    const ignored = new Set([
      "about", "again", "been", "currently", "detecting", "diagnostic", "diagnostics",
      "focus", "from", "have", "into", "just", "like", "prefer", "running", "system", "that",
      "their", "there", "these", "this", "through", "trying", "want", "what", "when", "where",
      "which", "with", "would",
    ]);
    return new Set(
      String(value || "")
        .toLowerCase()
        .replace(/[^a-z0-9\s]/g, " ")
        .split(/\s+/)
        .filter((term) => term.length > 3 && !ignored.has(term))
    );
  }

  function similarText(left, right) {
    const a = comparisonTerms(left);
    const b = comparisonTerms(right);
    if (a.size < 4 || b.size < 4) return false;
    let overlap = 0;
    for (const term of a) if (b.has(term)) overlap += 1;
    return overlap / Math.min(a.size, b.size) >= 0.44;
  }

  function latestDistinct(items, maximum, textForItem) {
    const kept = [];
    const newestFirst = [...items].sort((a, b) => eventTimestamp(b) - eventTimestamp(a));
    for (const item of newestFirst) {
      const text = textForItem(item);
      if (!text || kept.some((existing) => similarText(text, textForItem(existing)))) continue;
      kept.push(item);
      if (kept.length >= maximum) break;
    }
    return kept.sort((a, b) => eventTimestamp(a) - eventTimestamp(b));
  }

  function meaningfulActivity(item) {
    const kind = String(item?.kind || "").toLowerCase();
    const ignoredKinds = new Set([
      "thought",
      "reflection",
      "nervous_system_run",
      "upgrade_detected",
      "outreach_sent",
      "autonomy_free_run_started",
      "autonomy_free_run_completed",
      "autonomy_capability_tryout",
      "quiet_consolidation",
      "relationship_episodes_extracted",
      "uncertainty_logged",
      "judgment_call_logged",
      "reply_lane_learning_updated",
      "uncertainty_review_generated",
      "judgment_review_generated",
    ]);
    if (!kind || ignoredKinds.has(kind) || kind.includes("cycle_skipped")) return false;
    return /(^|_)(action|repair|error|failed|completed|presence_cycle|code_session|model_exercise|component_update|agent_capability_integration)/.test(kind);
  }

  function thoughtPresentation(item) {
    const raw = eventText(item, 2200).replace(/\s+/g, " ").trim();
    const goalMatch = raw.match(/(?:durable goal|current focus):\s*(.+?)(?:\.\s+(?:That goal|It does not|The next)|$)/i);
    if (goalMatch?.[1]) {
      const goal = lowerFirst(goalMatch[1]);
      return {
        label: "On my mind",
        content: `I’m holding onto one goal: ${goal}. I haven’t done it yet.`,
        details: raw,
      };
    }
    const content = sentenceExcerpt(raw, 520);
    return {
      label: "On my mind",
      content: content || "I noticed something I want to understand more clearly.",
      details: raw && raw !== content ? raw : "",
    };
  }

  function activityPresentation(item) {
    const kind = String(item?.kind || "").toLowerCase();
    const raw = eventText(item, 1800).replace(/\s+/g, " ").trim();
    const failed = item?.metadata?.ok === false || /(error|failed|failure|needs_review)/.test(kind);
    let label = failed ? "I hit a snag" : "I acted";
    let content = raw.length > 460 ? `${raw.slice(0, 459).trim()}…` : raw;

    if (kind === "code_session_completed") {
      label = "I practiced";
      content = "I practiced using my coding tools and finished the exercise.";
    } else if (kind === "model_exercise_passed") {
      label = "I practiced";
      content = "I practiced one of my thinking abilities and passed its check.";
    } else if (kind === "model_exercise_needs_review") {
      label = "I found a weakness";
      content = "One of my thinking exercises did not fit its prompt cleanly, so I kept it out of the pass column.";
    } else if (kind === "self_awareness_battery_failed") {
      label = "I found a weakness";
      content = "One self-check failed validation. I kept the result as a failure instead of talking past it.";
    } else if (kind === "self_awareness_battery_passed") {
      label = "I checked myself";
      content = "A self-check passed its current evidence threshold.";
    } else if (kind === "self_awareness_perturbation_test_passed") {
      label = "I tested my footing";
      content = "I checked whether I could stay grounded when memory, tools, or uncertainty changed.";
    } else if (kind === "typed_action_contract_repaired") {
      label = "I repaired a reflex";
      content = raw.toLowerCase().includes("openclaw")
        ? "I repaired the instructions that govern how I run the OpenClaw self-check."
        : "I repaired the instructions that govern one of the ways I act.";
    } else if (kind === "system_maintenance_completed") {
      label = "I looked after things";
      content = "I looked after the software around me and finished the maintenance check.";
    } else if (kind === "component_update_check") {
      label = "I checked";
      content = "I checked what has changed in the software around me.";
    } else if (kind === "openclaw_action_router") {
      label = failed ? "I hit a snag" : "I checked my reach";
      content = failed
        ? "I tried to bring back evidence from one of the ways I can act, but the check did not finish cleanly."
        : "I checked the recent trail from one of the ways I can act and brought the verified results back into view.";
    } else if (kind === "agent_capability_integration") {
      label = "I expanded my reach";
      const counts = raw.match(/Integrated\s+(\d+)\s+live\/bounded agent route\(s\) and\s+(\d+)\s+prototype/i);
      content = counts
        ? `I checked which abilities I can actually use and confirmed ${counts[1]} working route${counts[1] === "1" ? "" : "s"}. ${counts[2]} more ${counts[2] === "1" ? "is" : "are"} still only a prototype.`
        : "I checked which abilities I can actually use and confirmed the result.";
    } else if (kind === "presence_cycle") {
      label = "I acted and checked";
      content = raw.toLowerCase().includes("service_health_check")
        ? "I checked one of my local services and confirmed that it answered."
        : "I did one small thing and checked what happened.";
    } else if (kind === "daemon_error") {
      label = "I stopped myself";
      if (/thought failed|continuous-thought|evidence boundary/i.test(raw)) {
        content = "I dropped a background thought because it blurred a goal with something I had actually done.";
      } else if (/outreach failed|context size|exceeds the available context/i.test(raw)) {
        label = "I couldn’t reach you";
        content = "I tried to decide whether to start a conversation, but the local context was too large to process cleanly.";
      } else if (raw.toLowerCase().includes("openclaw")) {
        label = "I hit a snag";
        content = "I tried to use OpenClaw, but the attempt didn’t finish cleanly.";
      } else {
        label = "I hit a snag";
        content = "A background attempt didn’t finish cleanly.";
      }
    }

    return {
      label,
      content: content || "I did one small thing and checked what happened.",
      details: raw && raw !== content ? raw : "",
      failed,
    };
  }

  function sentenceExcerpt(value, maximum = 560) {
    const text = String(value || "").replace(/\s+/g, " ").trim();
    if (text.length <= maximum) return text;
    const candidate = text.slice(0, maximum + 1);
    const boundary = Math.max(
      candidate.lastIndexOf(". "),
      candidate.lastIndexOf("? "),
      candidate.lastIndexOf("! ")
    );
    return `${candidate.slice(0, boundary >= maximum * 0.55 ? boundary + 1 : maximum).trim()}…`;
  }

  function reflectionPresentation(item) {
    const raw = eventText(item, 4000).replace(/\s+(#{1,3}\s+)/g, "\n\n$1");
    const learned = raw.match(/##\s+What I Learned About Humanity\s+([\s\S]*?)(?=\s+##\s+|$)/i);
    const content = sentenceExcerpt(learned?.[1] || raw.replace(/^#\s+Reflection\s*/i, ""));
    return {
      content: content || "Eve completed a reflection.",
      details: raw && raw !== content ? raw : "",
    };
  }

  function sourceBackedLiveMessage(message) {
    return /^(message|thought|activity|reflection):/.test(String(message?.sourceId || ""));
  }

  async function refreshLiveStream() {
    if (liveRefreshInFlight) return;
    liveRefreshInFlight = true;
    const live = ensureLiveConversation();
    try {
      // Eve's local backend shares resources with her model lanes. Keep one
      // light refresh in flight and avoid a five-request burst every poll.
      const personalMessages = await fetchLiveData(
        "/api/messages?limit=30&sender=eve&recipient=user&personal=1"
      );
      const thoughts = await fetchLiveData("/api/thoughts?limit=24");
      const activity = await fetchLiveData("/api/activity?limit=50");
      const reflections = await fetchLiveData("/api/reflections?limit=5");
      const presence = await fetchLiveData("/api/presence").catch(() => null);
      const personalStatus = await fetchLiveData("/api/personal-conversation/status");
      const previousPresence = JSON.stringify(livePresence);
      if (presence && typeof presence === "object") livePresence = presence;
      const presenceChanged = previousPresence !== JSON.stringify(livePresence);
      syncVisualState();
      if (
        presenceChanged &&
        statusChecked &&
        !isSending &&
        !elements.mic.classList.contains("listening")
      ) {
        setStatus(
          backendReady ? "ready" : "offline",
          backendReady ? presenceStatusLabel() : "Reconnecting",
          currentStatusDetail()
        );
      }
      const now = Date.now();
      const threeDaysAgo = now - 3 * 24 * 60 * 60 * 1000;
      const sevenDaysAgo = now - 7 * 24 * 60 * 60 * 1000;
      const incoming = [];

      const recentPersonalMessages = (personalMessages || []).filter(
        (item) => eventTimestamp(item) >= sevenDaysAgo
      );
      for (const item of latestDistinct(recentPersonalMessages, 3, (entry) => eventText(entry, 2400))) {
        const createdAt = eventTimestamp(item);
        incoming.push({
          id: id("eve-initiative"),
          sourceId: `message:${item.id}`,
          role: "assistant",
          content: eventText(item, 2400),
          subject: String(item.subject || "Eve started a conversation"),
          createdAt,
          proactive: true,
          unread: String(item.status || "").toLowerCase() === "unread",
          replyMessageId: String(item.id || ""),
        });
      }

      const recentThoughts = (thoughts || []).filter((item) => eventTimestamp(item) >= threeDaysAgo);
      for (const item of latestDistinct(recentThoughts, 1, (entry) => eventText(entry, 1200))) {
        const createdAt = eventTimestamp(item);
        const presentation = thoughtPresentation(item);
        incoming.push({
          id: id("eve-thought"),
          sourceId: `thought:${item.id}`,
          role: "assistant",
          eventType: "thought",
          label: presentation.label,
          content: presentation.content,
          details: presentation.details,
          detailsLabel: "What this came from",
          createdAt,
        });
      }

      const recentActivity = (activity || []).filter(
        (item) => eventTimestamp(item) >= threeDaysAgo && meaningfulActivity(item)
      );
      for (const item of latestDistinct(recentActivity, 4, (entry) => activityPresentation(entry).content)) {
        const createdAt = eventTimestamp(item);
        const presentation = activityPresentation(item);
        incoming.push({
          id: id("eve-action"),
          sourceId: `activity:${item.id}`,
          role: "assistant",
          eventType: "action",
          label: presentation.label,
          content: presentation.content,
          details: presentation.details,
          createdAt,
          error: presentation.failed,
        });
      }

      const recentReflections = (reflections || []).filter(
        (item) => eventTimestamp(item) >= sevenDaysAgo
      );
      for (const item of latestDistinct(recentReflections, 1, (entry) => eventText(entry, 2200))) {
        const createdAt = eventTimestamp(item);
        const reflection = reflectionPresentation(item);
        incoming.push({
          id: id("eve-reflection"),
          sourceId: `reflection:${item.id}`,
          role: "assistant",
          eventType: "reflection",
          label: "Something I learned",
          content: reflection.content,
          details: reflection.details,
          detailsLabel: "Read full reflection",
          createdAt,
        });
      }

      const existingBySource = new Map(
        live.messages
          .filter((message) => message.sourceId)
          .map((message) => [message.sourceId, message])
      );
      const newSourceItems = incoming.filter((message) => !existingBySource.has(message.sourceId));
      for (const message of incoming) {
        const existing = existingBySource.get(message.sourceId);
        if (existing) message.id = existing.id;
      }
      const conversationalMessages = live.messages.filter((message) => !sourceBackedLiveMessage(message));
      const nextMessages = [...conversationalMessages, ...incoming]
        .sort((a, b) => Number(a.createdAt || 0) - Number(b.createdAt || 0))
        .slice(-160);
      const unreadIds = (personalMessages || [])
        .filter((item) => String(item.status || "").toLowerCase() === "unread" && item.id)
        .map((item) => String(item.id));
      const changed = JSON.stringify(live.messages) !== JSON.stringify(nextMessages);
      const unreadChanged = JSON.stringify(live.pendingReadMessageIds || []) !== JSON.stringify(unreadIds);
      live.messages = nextMessages;
      live.pendingReadMessageIds = unreadIds;
      live.personalStatus = personalStatus || null;
      if (changed) {
        live.updatedAt = Date.now();
      }
      if (changed || unreadChanged) {
        saveStore();
      }
      const newestProactive = newSourceItems
        .filter((message) => message.proactive && message.unread)
        .sort((a, b) => b.createdAt - a.createdAt)[0];
      notifyNativePresence(unreadIds.length, Boolean(newestProactive), newestProactive?.subject || "");
      if (newestProactive && settings.speakReplies) speakReply(newestProactive.content);
      if (
        store.activeId === LIVE_CONVERSATION_ID &&
        (changed || presenceChanged || !elements.transcript.children.length)
      ) {
        liveRefreshHasNewContent = newSourceItems.length > 0;
        render({ newLiveContent: liveRefreshHasNewContent });
        liveRefreshHasNewContent = false;
      }
      if (store.activeId === LIVE_CONVERSATION_ID) markVisiblePersonalMessagesRead();
      settleLiveLaunchAtLatest();
      liveFailureCount = 0;
      return true;
    } catch (error) {
      liveFailureCount += 1;
      console.warn("Eve live stream is temporarily using its last good state", error);
      // The ordinary conversation remains usable if observational feeds are temporarily unavailable.
      return false;
    } finally {
      liveRefreshInFlight = false;
    }
  }

  function scheduleBackgroundRefresh(delay = 0) {
    if (livePollTimer) window.clearTimeout(livePollTimer);
    livePollTimer = window.setTimeout(async () => {
      await refreshLiveStream();
      await pollFollowups();
      const normalDelay = document.hidden ? 60000 : 10000;
      const backoff = Math.min(120000, normalDelay * Math.max(1, 2 ** liveFailureCount));
      scheduleBackgroundRefresh(backoff);
    }, Math.max(0, delay));
  }

  async function pollFollowups() {
    try {
      const response = await fetch(
        "/api/eve-chat/followups?surface=eve_chat_ui&status=delivered,failed&include_seen=0&limit=12",
        { cache: "no-store" }
      );
      if (!response.ok) return;
      const payload = await response.json();
      const items = payload?.data?.items || [];
      let changed = false;
      for (const item of items) {
        const followupId = String(item.id || "");
        const chatId = String(item.openwebui_chat_id || "");
        const conversation = store.conversations.find((entry) => entry.id === chatId);
        if (!followupId || !conversation) continue;
        if (!conversation.messages.some((message) => message.sourceId === followupId)) {
          conversation.messages.push({
            id: id("eve-followup"),
            role: "assistant",
            content: String(item.delivery_text || item.failure_reason || "I finished the follow-up."),
            createdAt: Date.now(),
            sourceId: followupId,
            error: String(item.status || "") === "failed",
          });
          conversation.updatedAt = Date.now();
          changed = true;
        }
        await fetch(`/api/eve-chat/followups/${encodeURIComponent(followupId)}/seen`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: "{}",
        }).catch(() => {});
      }
      if (changed) {
        saveStore();
        render();
      }
    } catch (_) {
      // Follow-ups are optional; normal chat remains usable if polling is unavailable.
    }
  }

  elements.composer.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage();
  });
  elements.prompt.addEventListener("input", () => {
    updateComposer();
    scheduleDraftSave();
  });
  elements.prompt.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
      event.preventDefault();
      sendMessage();
    }
  });
  elements.newChat.addEventListener("click", newConversation);
  elements.showLive.addEventListener("click", () => selectConversation(LIVE_CONVERSATION_ID));
  elements.workspace.addEventListener("click", (event) => {
    if (event.target !== elements.workspace) return;
    if (!elements.body.classList.contains("sidebar-open")) return;
    elements.body.classList.remove("sidebar-open");
    renderSidebarState();
  });
  elements.cancelReply.addEventListener("click", cancelPersonalReply);
  elements.jumpLatest.addEventListener("click", () => scrollToLatest());
  elements.transcript.addEventListener("scroll", () => {
    if (activeConversation()?.mode !== "live") return;
    elements.jumpLatest.hidden = transcriptNearBottom() || liveLaunchAnchorPending;
  });
  elements.sidebarToggle.addEventListener("click", toggleSidebar);
  elements.speak.addEventListener("click", () => {
    settings.speakReplies = !settings.speakReplies;
    saveSettings();
    elements.speak.setAttribute("aria-pressed", String(settings.speakReplies));
    if (!settings.speakReplies && "speechSynthesis" in window) window.speechSynthesis.cancel();
  });
  elements.mic.addEventListener("click", () => {
    if (!recognition) return;
    if (elements.mic.classList.contains("listening")) recognition.stop();
    else recognition.start();
  });
  elements.sensesToggle.addEventListener("click", () => toggleSensoryPanel());
  elements.sensesClose.addEventListener("click", () => toggleSensoryPanel(false));
  elements.sensesStart.addEventListener("click", () => void startSensorySession());
  elements.sensesStop.addEventListener("click", () => void stopSensorySession());
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !elements.sensesPanel.hidden) {
      toggleSensoryPanel(false);
      elements.sensesToggle.focus();
      return;
    }
    if (event.key === "Escape" && elements.body.classList.contains("sidebar-open")) {
      elements.body.classList.remove("sidebar-open");
      renderSidebarState();
      elements.sidebarToggle.focus();
      return;
    }
    if (event.metaKey && event.key.toLowerCase() === "n") {
      event.preventDefault();
      newConversation();
    }
    if (event.metaKey && event.key.toLowerCase() === "k") {
      event.preventDefault();
      elements.prompt.focus();
    }
    if (event.metaKey && event.key === "1") {
      event.preventDefault();
      selectConversation(LIVE_CONVERSATION_ID);
    }
  });
  window.addEventListener("online", () => {
    refreshStatus();
    scheduleBackgroundRefresh(0);
  });
  window.addEventListener("offline", () => {
    backendReady = false;
    statusChecked = true;
    setStatus("offline", "Reconnecting", "");
  });
  window.addEventListener("storage", (event) => {
    if (event.key !== STORAGE_KEY || isSending || elements.prompt.value.trim()) return;
    store = loadStore();
    ensureConversation();
    render();
  });
  window.addEventListener("pagehide", () => {
    flushDraft();
    stopSensorySessionOnPageExit();
  });
  document.addEventListener("visibilitychange", () => scheduleBackgroundRefresh(0));
  window.matchMedia("(max-width: 760px)").addEventListener?.("change", () => {
    elements.body.classList.remove("sidebar-open");
    renderSidebarState();
  });

  window.EveApp = {
    newConversation,
    showLive: () => selectConversation(LIVE_CONVERSATION_ID),
    focusComposer: () => elements.prompt.focus(),
    stopSensorySession: () => stopSensorySession(),
  };
  setDaypart();
  ensureConversation();
  honorLaunchView();
  configureRecognition();
  setSensoryControlsActive(false);
  render();
  refreshStatus();
  void recoverInterruptedReplies();
  scheduleBackgroundRefresh(0);
  setInterval(refreshStatus, 30000);
  setInterval(setDaypart, 300000);
})();
