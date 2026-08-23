#!/usr/bin/env python3
"""Apply Eve local-private presentation branding to the adopted chat UI.

This patches runtime/static presentation strings only. Eve records the adopted
upstream substrate in project docs and fork metadata, not in user-facing UI.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path


DEFAULT_BRAND_NAME = "Eve"
DEFAULT_BRAND_SLUG = "eve"
FOLLOWUP_SCRIPT_NAME = "eve-chat-followups.js"
FOLLOWUP_SCRIPT_VERSION = "20260508-copilotkit-panel-anchor"
FOLLOWUP_SCRIPT_TAG = (
    f'<script defer src="/{FOLLOWUP_SCRIPT_NAME}?v={FOLLOWUP_SCRIPT_VERSION}" '
    'data-eve-chat-followups="true"></script>'
)
FOLLOWUP_SCRIPT = r"""
(function () {
  if (window.__eveChatFollowups) return;
  window.__eveChatFollowups = true;

  const apiBase =
    window.EVE_CHAT_FOLLOWUP_BASE_URL ||
    window.localStorage.getItem("eveChatFollowupApiBase") ||
    "http://127.0.0.1:8797";
  const hiddenKey = "eveChatFollowupsHidden";
  const insertedKey = "eveChatFollowupsInserted";
  const lastTurnKey = "eveChatLastOpenWebUITurn";
  const activityHiddenKey = "eveChatActivityHidden";
  const copilotKitDemoVisibleKey = "eveChatCopilotKitDemoVisibleChat";
  const copilotKitAguiAutoRunKey = "eveChatCopilotKitAguiAutoRun.20260508PanelAnchor";
  const rendered = new Set();
  let lastActivityJobId = "";
  let lastCopilotKitDemoSignature = "";
  let lastCopilotKitAguiAutoRunSignature = "";

  function readSet(key) {
    try {
      return new Set(JSON.parse(window.localStorage.getItem(key) || "[]"));
    } catch (_) {
      return new Set();
    }
  }

  function writeSet(key, ids) {
    window.localStorage.setItem(key, JSON.stringify(Array.from(ids).slice(-300)));
  }

  function remember(key, id) {
    const ids = readSet(key);
    ids.add(id);
    writeSet(key, ids);
  }

  function hiddenIds() {
    return readSet(hiddenKey);
  }

  function insertedIds() {
    return readSet(insertedKey);
  }

  function currentChatId() {
    const pathMatch = window.location.pathname.match(/\/(?:c|chat)\/([^/?#]+)/);
    if (pathMatch) return decodeURIComponent(pathMatch[1]);
    const query = new URLSearchParams(window.location.search);
    return query.get("chat_id") || query.get("chatId") || "";
  }

  function firstObjectValue(value) {
    if (!value || typeof value !== "object") return "";
    const values = Object.values(value).filter(Boolean);
    return values.length ? String(values[0]) : "";
  }

  function storeTurn(payload) {
    if (!payload || typeof payload !== "object") return;
    const userMessage = payload.user_message || payload.parent_message || {};
    const chatId = String(payload.chat_id || currentChatId() || "");
    const assistantId = String(payload.id || firstObjectValue(payload.message_ids) || "");
    const userMessageId = String(userMessage.id || payload.user_message_id || "");
    const clientRequestId = String(
      payload.user ||
      payload.client_request_id ||
      payload.id ||
      assistantId ||
      userMessageId ||
      ""
    );
    if (!chatId && !assistantId && !userMessageId) return;
    const turn = {
      chat_id: chatId,
      assistant_message_id: assistantId,
      user_message_id: userMessageId,
      client_request_id: clientRequestId,
      captured_at: Date.now()
    };
    window.localStorage.setItem(lastTurnKey, JSON.stringify(turn));
  }

  function parseJsonBody(body) {
    if (!body || typeof body !== "string") return null;
    try {
      return JSON.parse(body);
    } catch (_) {
      return null;
    }
  }

  function installFetchCapture() {
    if (window.__eveChatFollowupFetchCapture) return;
    window.__eveChatFollowupFetchCapture = true;
    const originalFetch = window.fetch.bind(window);
    window.fetch = async function eveChatFollowupFetch(input, init) {
      try {
        const url = typeof input === "string" ? input : String((input || {}).url || "");
        const method = String((init || {}).method || (input || {}).method || "GET").toUpperCase();
        if (
          method === "POST" &&
          url.includes("/api/") &&
          url.includes("chat") &&
          url.includes("completion")
        ) {
          const payload = parseJsonBody((init || {}).body);
          storeTurn(payload);
        }
      } catch (_) {
        /* Capture is best-effort; never block the adopted chat UI. */
      }
      return originalFetch(input, init);
    };
  }

  function lastTurn() {
    try {
      const parsed = JSON.parse(window.localStorage.getItem(lastTurnKey) || "{}");
      if (!parsed || typeof parsed !== "object") return {};
      if (Date.now() - Number(parsed.captured_at || 0) > 30 * 60 * 1000) return {};
      return parsed;
    } catch (_) {
      return {};
    }
  }

  function targetFor(item) {
    const turn = lastTurn();
    return {
      chat_id: String(item.openwebui_chat_id || turn.chat_id || currentChatId() || ""),
      parent_message_id: String(item.openwebui_assistant_message_id || turn.assistant_message_id || ""),
      user_message_id: String(item.openwebui_user_message_id || turn.user_message_id || "")
    };
  }

  function stack() {
    let node = document.getElementById("eve-chat-followup-stack");
    if (node) return node;
    node = document.createElement("section");
    node.id = "eve-chat-followup-stack";
    node.setAttribute("aria-live", "polite");
    Object.assign(node.style, {
      position: "fixed",
      right: "24px",
      bottom: "24px",
      zIndex: "2147483647",
      display: "grid",
      gap: "12px",
      width: "min(420px, calc(100vw - 32px))",
      pointerEvents: "none",
      fontFamily: "ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
    });
    document.body.appendChild(node);
    return node;
  }

  function textNode(tag, text, styles) {
    const node = document.createElement(tag);
    node.textContent = text;
    Object.assign(node.style, styles || {});
    return node;
  }

  function activityHiddenIds() {
    return readSet(activityHiddenKey);
  }

  function removeActivityPanel() {
    const node = document.getElementById("eve-chat-activity-panel");
    if (node) node.remove();
  }

  function activityHost() {
    return (
      document.querySelector('[role="log"]') ||
      document.querySelector('[aria-label="Chat Conversation"]') ||
      document.querySelector("main") ||
      document.body
    );
  }

  function activityInsertionPoint(host) {
    if (!host || !host.querySelectorAll) return { parent: host || document.body, anchor: null };
    const elements = Array.from(host.querySelectorAll("*"));
    for (let index = elements.length - 1; index >= 0; index -= 1) {
      const element = elements[index];
      if (element.id === "eve-chat-activity-panel") continue;
      if (String(element.textContent || "").trim() !== "Follow up") continue;
      const parent = element.parentElement;
      if (parent && parent.id !== "eve-chat-activity-panel") {
        return { parent, anchor: element };
      }
    }
    return { parent: host, anchor: null };
  }

  function latestCopilotKitDemoMessage(host) {
    if (!host || !host.querySelectorAll) return null;
    const markers = [
      "i'm starting the live copilotkit demo now",
      "you should see the ag-ui event stream start below this reply",
      "if the panel does not start on its own",
      "copilotkit_demo: live",
      "copilotkit demo: live"
    ];
    const elements = Array.from(host.querySelectorAll("*"));
    for (let index = elements.length - 1; index >= 0; index -= 1) {
      const element = elements[index];
      if (!element || element.id === "eve-chat-copilotkit-demos") continue;
      if (element.closest && element.closest("#eve-chat-copilotkit-demos")) continue;
      const text = String(element.innerText || element.textContent || "").toLowerCase();
      if (!markers.some((marker) => text.includes(marker))) continue;
      if (["P", "LI", "ARTICLE"].includes(String(element.tagName || "").toUpperCase())) {
        return element;
      }

      let candidate = element;
      let climbs = 0;
      while (
        candidate.parentElement &&
        candidate.parentElement !== host &&
        candidate.parentElement.closest &&
        candidate.parentElement.closest('[role="log"], [aria-label="Chat Conversation"], main') &&
        String(candidate.parentElement.innerText || candidate.parentElement.textContent || "").length < 2400 &&
        climbs < 3
      ) {
        if (candidate.parentElement.id === "eve-chat-copilotkit-demos") break;
        candidate = candidate.parentElement;
        climbs += 1;
        if (candidate.parentElement === host) break;
      }
      return candidate;
    }
    return null;
  }

  function activityPanel() {
    let node = document.getElementById("eve-chat-activity-panel");
    if (!node) {
      node = document.createElement("section");
      node.id = "eve-chat-activity-panel";
      node.setAttribute("aria-live", "polite");
      node.setAttribute("role", "status");
      node.dataset.eveInlineActivity = "true";
      Object.assign(node.style, {
        width: "min(760px, calc(100% - 32px))",
        margin: "8px auto 32px",
        boxSizing: "border-box",
        border: "0",
        borderRadius: "0",
        background: "transparent",
        color: "#243229",
        boxShadow: "none",
        padding: "0",
        fontFamily: "ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        scrollMarginBlockEnd: "132px"
      });
    }
    const host = activityHost();
    if (host) {
      const point = activityInsertionPoint(host);
      const parent = point.parent || host;
      const anchor = point.anchor;
      if (anchor && anchor !== node && node.nextSibling !== anchor) {
        parent.insertBefore(node, anchor);
      } else if (!anchor && node.parentElement !== parent) {
        parent.appendChild(node);
      }
    }
    return node;
  }

  function copilotKitDemoAnchor(host) {
    const activity = document.getElementById("eve-chat-activity-panel");
    if (activity && activity.parentElement) {
      return { parent: activity.parentElement, anchor: activity };
    }
    const demoMessage = latestCopilotKitDemoMessage(host);
    if (demoMessage && demoMessage.parentElement) {
      return { parent: demoMessage.parentElement, after: demoMessage };
    }
    const point = activityInsertionPoint(host);
    return { parent: point.parent || host || document.body, anchor: point.anchor || null };
  }

  function copilotKitDemoPanel() {
    let node = document.getElementById("eve-chat-copilotkit-demos");
    if (!node) {
      node = document.createElement("section");
      node.id = "eve-chat-copilotkit-demos";
      node.dataset.eveCopilotKitDemos = "true";
      node.setAttribute("aria-label", "CopilotKit demos for Eve Chat");
      Object.assign(node.style, {
        width: "min(760px, calc(100% - 32px))",
        margin: "6px auto 32px",
        boxSizing: "border-box",
        fontFamily: "ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        color: "#243229"
      });
    }
    const host = activityHost();
    const point = copilotKitDemoAnchor(host);
    const parent = point.parent || host || document.body;
    if (point.after && node.previousSibling !== point.after) {
      parent.insertBefore(node, point.after.nextSibling);
    } else if (point.anchor && node.nextSibling !== point.anchor) {
      parent.insertBefore(node, point.anchor);
    } else if (!point.after && !point.anchor && node.parentElement !== parent) {
      parent.appendChild(node);
    }
    return node;
  }

  function copilotKitDemoLauncherPanel() {
    let node = document.getElementById("eve-chat-copilotkit-demo-launcher");
    if (!node) {
      node = document.createElement("section");
      node.id = "eve-chat-copilotkit-demo-launcher";
      node.dataset.eveCopilotKitDemoLauncher = "true";
      node.setAttribute("aria-label", "Show CopilotKit demos");
      Object.assign(node.style, {
        width: "min(760px, calc(100% - 32px))",
        margin: "6px auto 14px",
        boxSizing: "border-box",
        fontFamily: "ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
        color: "#243229"
      });
    }
    const host = activityHost();
    const point = copilotKitDemoAnchor(host);
    const parent = point.parent || host || document.body;
    if (point.after && node.previousSibling !== point.after) {
      parent.insertBefore(node, point.after.nextSibling);
    } else if (point.anchor && node.nextSibling !== point.anchor) {
      parent.insertBefore(node, point.anchor);
    } else if (!point.after && !point.anchor && node.parentElement !== parent) {
      parent.appendChild(node);
    }
    return node;
  }

  function rememberCopilotKitDemoVisible() {
    window.localStorage.setItem(copilotKitDemoVisibleKey, currentChatId() || "global");
  }

  function copilotKitDemoPinned() {
    const marker = window.localStorage.getItem(copilotKitDemoVisibleKey) || "";
    const chat = currentChatId() || "global";
    return marker === chat || marker === "global";
  }

  function renderCopilotKitDemoLauncher(hidden) {
    const old = document.getElementById("eve-chat-copilotkit-demo-launcher");
    if (hidden) {
      if (old) old.remove();
      return;
    }
    const node = copilotKitDemoLauncherPanel();
    node.innerHTML = "";

    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Show CopilotKit demos";
    button.addEventListener("click", () => {
      rememberCopilotKitDemoVisible();
      lastCopilotKitDemoSignature = "";
      renderCopilotKitDemos(true);
    });
    Object.assign(button.style, {
      border: "1px solid rgba(31, 107, 70, 0.16)",
      borderRadius: "999px",
      background: "rgba(31, 107, 70, 0.06)",
      color: "#1f6b46",
      padding: "8px 12px",
      fontSize: "12px",
      fontWeight: "650",
      cursor: "pointer"
    });
    node.appendChild(button);
    node.appendChild(textNode("span", " Local Eve previews for AG-UI streams, generative UI cards, frontend tools, and review flows.", {
      marginLeft: "8px",
      fontSize: "12px",
      color: "#6b7770"
    }));
  }

  function currentConversationText() {
    const host = activityHost();
    if (!host || !host.querySelectorAll) return String(document.body.innerText || "");
    const messageNodes = Array.from(host.querySelectorAll('[role="listitem"]'));
    const sourceNodes = messageNodes.length ? messageNodes : Array.from(host.children || []);
    return sourceNodes
      .filter((node) => !node.closest || !node.closest("#eve-chat-copilotkit-demos"))
      .map((node) => String(node.innerText || node.textContent || ""))
      .join("\n");
  }

  function shouldShowCopilotKitDemos() {
    const lower = currentConversationText().toLowerCase();
    return copilotKitDemoPinned() || lower.includes("copilotkit") || lower.includes("ag-ui") || lower.includes("generative ui");
  }

  function copilotKitDemoCard(item) {
    const card = document.createElement("article");
    Object.assign(card.style, {
      border: "1px solid rgba(32, 56, 44, 0.12)",
      borderRadius: "16px",
      background: "linear-gradient(145deg, rgba(255,255,255,0.96), rgba(247,250,248,0.92))",
      padding: "12px 13px",
      minHeight: "128px",
      boxShadow: "0 8px 24px rgba(31, 42, 36, 0.07)"
    });
    card.appendChild(textNode("div", item.label, {
      fontSize: "11px",
      color: "#6f7b73",
      textTransform: "uppercase",
      letterSpacing: "0.08em",
      marginBottom: "6px"
    }));
    card.appendChild(textNode("strong", item.title, {
      display: "block",
      fontSize: "13.5px",
      lineHeight: "1.35",
      color: "#243229",
      marginBottom: "6px"
    }));
    card.appendChild(textNode("p", item.body, {
      margin: "0 0 9px",
      fontSize: "12.5px",
      lineHeight: "1.42",
      color: "#56645c"
    }));
    card.appendChild(textNode("div", item.evePath, {
      borderTop: "1px solid rgba(36, 50, 41, 0.09)",
      paddingTop: "8px",
      fontSize: "11.5px",
      lineHeight: "1.35",
      color: "#7a867f"
    }));
    return card;
  }

  function copilotKitAguiLivePanel() {
    const panel = document.createElement("section");
    Object.assign(panel.style, {
      border: "1px solid rgba(31, 107, 70, 0.13)",
      borderRadius: "16px",
      background: "rgba(255,255,255,0.72)",
      padding: "12px",
      marginTop: "12px"
    });
    const header = document.createElement("div");
    Object.assign(header.style, {
      display: "flex",
      alignItems: "center",
      justifyContent: "space-between",
      gap: "12px",
      marginBottom: "9px"
    });
    const copy = document.createElement("div");
    copy.appendChild(textNode("strong", "Live AG-UI adapter smoke", {
      display: "block",
      fontSize: "13px",
      color: "#20382c",
      marginBottom: "2px"
    }));
    copy.appendChild(textNode("span", "Streams Eve reply-progress and answer events from /api/eve-chat/ag-ui.", {
      fontSize: "12px",
      color: "#6b7770"
    }));
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Run live AG-UI smoke";
    button.id = "eve-chat-copilotkit-agui-run";
    button.addEventListener("click", () => runCopilotKitAguiSmoke(button));
    Object.assign(button.style, {
      border: "0",
      borderRadius: "999px",
      background: "#20382c",
      color: "#fff",
      padding: "8px 12px",
      fontSize: "12px",
      fontWeight: "650",
      cursor: "pointer",
      whiteSpace: "nowrap"
    });
    header.appendChild(copy);
    header.appendChild(button);

    const output = document.createElement("div");
    output.id = "eve-chat-copilotkit-agui-live";
    output.textContent = "Ready to stream AG-UI events from Eve's local runtime.";
    Object.assign(output.style, {
      display: "grid",
      gap: "5px",
      borderTop: "1px solid rgba(36, 50, 41, 0.09)",
      paddingTop: "9px",
      fontSize: "12px",
      lineHeight: "1.35",
      color: "#516059"
    });
    panel.appendChild(header);
    panel.appendChild(output);
    return panel;
  }

  function aguiLiveOutput() {
    return document.getElementById("eve-chat-copilotkit-agui-live");
  }

  function appendAguiLiveEvent(event, replyText) {
    const output = aguiLiveOutput();
    if (!output) return;
    if (output.dataset.empty !== "false") {
      output.textContent = "";
      output.dataset.empty = "false";
    }
    const row = document.createElement("div");
    const type = String((event || {}).type || "EVENT");
    const suffix = type === "TEXT_MESSAGE_CONTENT"
      ? `: ${String((event || {}).delta || "").slice(0, 180)}`
      : type === "ACTIVITY_DELTA"
        ? ": progress update"
        : type === "RUN_FINISHED"
          ? ": completed"
          : "";
    row.textContent = `${type}${suffix}`;
    Object.assign(row.style, {
      borderLeft: "2px solid rgba(31, 107, 70, 0.22)",
      paddingLeft: "8px"
    });
    output.appendChild(row);
    if (replyText) {
      const reply = document.createElement("div");
      reply.textContent = `reply: ${replyText.slice(0, 220)}`;
      Object.assign(reply.style, {
        color: "#20382c",
        fontWeight: "600",
        paddingLeft: "10px"
      });
      output.appendChild(reply);
    }
  }

  async function runCopilotKitAguiSmoke(button) {
    const output = aguiLiveOutput();
    if (output) {
      output.dataset.empty = "true";
      output.textContent = "Connecting to Eve's AG-UI adapter...";
    }
    if (button) {
      button.disabled = true;
      button.textContent = "Streaming...";
      button.style.opacity = "0.7";
    }
    const runId = `eve-chat-agui-${Date.now().toString(36)}`;
    let replyText = "";
    try {
      const response = await fetch("/api/eve-chat/ag-ui", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          threadId: currentChatId() || "eve-chat",
          runId,
          messages: [
            {
              role: "user",
              content: "CopilotKit AG-UI live smoke: reply with exactly agui-live-ok and no other words."
            }
          ]
        })
      });
      if (!response.ok || !response.body) {
        throw new Error(`AG-UI adapter returned ${response.status}`);
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const next = await reader.read();
        if (next.done) break;
        buffer += decoder.decode(next.value, { stream: true });
        const chunks = buffer.split("\n\n");
        buffer = chunks.pop() || "";
        chunks.forEach((chunk) => {
          const data = chunk
            .split("\n")
            .filter((line) => line.startsWith("data:"))
            .map((line) => line.replace(/^data:\s?/, ""))
            .join("\n")
            .trim();
          if (!data) return;
          try {
            const event = JSON.parse(data);
            if (event.type === "TEXT_MESSAGE_CONTENT") {
              replyText += String(event.delta || "");
            }
            appendAguiLiveEvent(event, event.type === "RUN_FINISHED" ? replyText : "");
          } catch (_) {
            /* Ignore malformed keepalive chunks. */
          }
        });
      }
    } catch (error) {
      const target = aguiLiveOutput();
      if (target) {
        target.textContent = `AG-UI smoke failed: ${String(error && error.message ? error.message : error)}`;
      }
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = "Run live AG-UI smoke";
        button.style.opacity = "1";
      }
    }
  }

  function copilotKitAguiAutoRunSignature() {
    const text = currentConversationText().toLowerCase();
    const markerIndex = Math.max(
      text.lastIndexOf("copilotkit_demo: live"),
      text.lastIndexOf("copilotkit demo: live"),
      text.lastIndexOf("i'm starting the live copilotkit demo now"),
      text.lastIndexOf("you should see the ag-ui event stream start below this reply")
    );
    if (markerIndex < 0) return "";
    return `${currentChatId() || "global"}:${markerIndex}`;
  }

  function maybeAutoRunCopilotKitAguiDemo() {
    const signature = copilotKitAguiAutoRunSignature();
    if (!signature) return;
    if (signature === lastCopilotKitAguiAutoRunSignature) return;
    if (window.localStorage.getItem(copilotKitAguiAutoRunKey) === signature) return;
    const button = document.getElementById("eve-chat-copilotkit-agui-run");
    if (!button || button.disabled) return;
    lastCopilotKitAguiAutoRunSignature = signature;
    window.localStorage.setItem(copilotKitAguiAutoRunKey, signature);
    runCopilotKitAguiSmoke(button);
  }

  function renderCopilotKitDemos(force) {
    if (!force && !shouldShowCopilotKitDemos()) {
      const old = document.getElementById("eve-chat-copilotkit-demos");
      if (old) old.remove();
      renderCopilotKitDemoLauncher(false);
      return;
    }
    if (force) rememberCopilotKitDemoVisible();
    renderCopilotKitDemoLauncher(true);
    const signature = `${currentChatId()}:copilotkit-demo-v1`;
    if (!force && signature === lastCopilotKitDemoSignature && document.getElementById("eve-chat-copilotkit-demos")) {
      maybeAutoRunCopilotKitAguiDemo();
      return;
    }
    lastCopilotKitDemoSignature = signature;

    const panel = copilotKitDemoPanel();
    panel.innerHTML = "";

    const shell = document.createElement("div");
    Object.assign(shell.style, {
      border: "1px solid rgba(31, 107, 70, 0.16)",
      borderRadius: "20px",
      background: "linear-gradient(135deg, rgba(250,253,251,0.96), rgba(238,247,242,0.82))",
      padding: "14px",
      boxShadow: "0 12px 36px rgba(31, 42, 36, 0.08)"
    });

    const header = document.createElement("div");
    Object.assign(header.style, {
      display: "flex",
      justifyContent: "space-between",
      gap: "12px",
      alignItems: "start",
      marginBottom: "12px"
    });
    const heading = document.createElement("div");
    heading.appendChild(textNode("div", "CopilotKit demos in Eve Chat", {
      fontWeight: "680",
      fontSize: "14px",
      color: "#20382c",
      marginBottom: "3px"
    }));
    heading.appendChild(textNode("div", "Previewing the surfaces CopilotKit is good at: chat, AG-UI events, generative UI, frontend tools, shared state, and human review.", {
      fontSize: "12.5px",
      lineHeight: "1.35",
      color: "#68746d"
    }));
    header.appendChild(heading);
    header.appendChild(textNode("span", "demo preview", {
      border: "1px solid rgba(31, 107, 70, 0.16)",
      borderRadius: "999px",
      padding: "5px 8px",
      color: "#1f6b46",
      background: "rgba(31, 107, 70, 0.06)",
      fontSize: "11px",
      whiteSpace: "nowrap"
    }));

    const grid = document.createElement("div");
    Object.assign(grid.style, {
      display: "grid",
      gridTemplateColumns: "repeat(auto-fit, minmax(176px, 1fr))",
      gap: "10px"
    });

    [
      {
        label: "agentic chat",
        title: "CopilotChat-style thread",
        body: "A chat surface that can stream agent events instead of only plain text.",
        evePath: "Eve path: map /v1 replies + reply-progress into one same-thread stream."
      },
      {
        label: "ag-ui stream",
        title: "Thinking and tool events",
        body: "Agent activity can arrive as typed UI events, like status, tool-call, result, and completion.",
        evePath: "Eve path: normalize reply-progress into AG-UI-style visible beats."
      },
      {
        label: "generative ui",
        title: "Inline artifact cards",
        body: "The agent can render structured cards, tables, forms, or diagrams inside chat.",
        evePath: "Eve path: render files, evidence, and model evals as local Eve cards."
      },
      {
        label: "frontend tools",
        title: "UI actions Eve can call",
        body: "Frontend actions expose controlled UI capabilities to the agent.",
        evePath: "Eve path: read-only chat UI tools first, then admitted local actions."
      },
      {
        label: "human-in-loop",
        title: "Review before action",
        body: "Approvals and interrupts can appear as first-class review cards.",
        evePath: "Eve path: show Hermes/Codex/governance proposals without changing authority."
      },
      {
        label: "shared state",
        title: "Chat and panels stay in sync",
        body: "Agent state and UI state can update together without separate hidden surfaces.",
        evePath: "Eve path: keep Eve Chat and Eve Monitor reading the same public event summaries."
      }
    ].forEach((item) => grid.appendChild(copilotKitDemoCard(item)));

    const livePanel = copilotKitAguiLivePanel();

    const boundary = textNode("div", "Boundary: these are Eve-owned demo previews. They do not change live model routing, memory authority, hidden tests, or action permissions.", {
      marginTop: "11px",
      fontSize: "11.5px",
      lineHeight: "1.35",
      color: "#7b8780"
    });

    shell.appendChild(header);
    shell.appendChild(grid);
    shell.appendChild(livePanel);
    shell.appendChild(boundary);
    panel.appendChild(shell);
    maybeAutoRunCopilotKitAguiDemo();
  }

  function shortId(value) {
    const text = String(value || "");
    return text.length > 10 ? `${text.slice(0, 8)}...` : text;
  }

  function activityAgeMs(job) {
    const stamp = Date.parse(String(job.finished_at || job.updated_at || job.started_at || ""));
    return Number.isFinite(stamp) ? Date.now() - stamp : 0;
  }

  function compactActivityText(value) {
    return String(value || "")
      .replace(/^Eve is\s+/i, "")
      .replace(/^Eve\s+/i, "")
      .replace(/\.\.\.$/, "")
      .replace(/\.$/, "")
      .trim();
  }

  function activityLabel(item, fallback) {
    const phase = String((item || {}).phase || "").toLowerCase();
    const title = compactActivityText((item || {}).title || "");
    if (phase === "received") return "Received message";
    if (phase === "reading_thread") return "Reading thread";
    if (phase === "gathering_context") return "Checking context";
    if (phase === "planning") return "Planning answer";
    if (phase === "drafting") return "Drafting";
    if (phase === "refining") return "Refining";
    if (phase === "ready") return "Reply ready";
    if (title) return title;
    return fallback || "Thinking";
  }

  function activityRows(job, active) {
    const notes = Array.isArray(job.notes) ? job.notes.filter((note) => note && typeof note === "object") : [];
    let rows = notes.slice(-6);
    const current = {
      phase: job.phase,
      title: job.title || (active ? "Thinking" : "Reply ready"),
      detail: job.detail || ""
    };
    const last = rows[rows.length - 1] || {};
    if (
      !rows.length ||
      String(last.phase || "") !== String(current.phase || "") ||
      String(last.title || "") !== String(current.title || "")
    ) {
      rows.push(current);
    }
    if (!active) {
      const lastReady = rows.map((note) => String(note.phase || "")).lastIndexOf("ready");
      if (lastReady >= 0) {
        rows = rows.filter((note, index) => String(note.phase || "") !== "ready" || index === lastReady);
      }
    }
    return rows.slice(-6);
  }

  function renderActivity(job) {
    if (!job || typeof job !== "object") return removeActivityPanel();
    const id = String(job.id || job.client_request_id || "");
    if (!id || activityHiddenIds().has(id)) return removeActivityPanel();
    const status = String(job.status || "active");
    const active = status === "active";
    if (!active && activityAgeMs(job) > 90 * 1000) return removeActivityPanel();
    const isNewJob = id !== lastActivityJobId;
    lastActivityJobId = id;

    const panel = activityPanel();
    panel.innerHTML = "";

    const rows = activityRows(job, active);
    const stream = document.createElement("div");
    Object.assign(stream.style, {
      display: "grid",
      gap: "7px",
      width: "100%",
      maxWidth: "760px",
      color: "#5d6861"
    });

    rows.forEach((note, index) => {
      const isCurrent = active && index === rows.length - 1;
      const isReady = String(note.phase || "") === "ready" || String(job.phase || "") === "ready";
      const row = document.createElement("div");
      Object.assign(row.style, {
        display: "grid",
        gridTemplateColumns: "18px minmax(0, 1fr)",
        gap: "9px",
        alignItems: "start",
        fontSize: "13px",
        lineHeight: "1.35",
        color: isCurrent ? "#27352d" : "#68746d"
      });

      const marker = document.createElement("span");
      marker.textContent = isCurrent ? ">" : "-";
      Object.assign(marker.style, {
        color: isCurrent ? "#1f6b46" : "#a8b1ab",
        fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
        fontSize: "12px",
        lineHeight: "1.45",
        opacity: isReady && !isCurrent ? "0.7" : "1"
      });

      const copy = document.createElement("div");
      copy.appendChild(textNode("div", activityLabel(note, isCurrent ? "Thinking" : "Progress update"), {
        fontWeight: isCurrent ? "620" : "480",
        letterSpacing: "-0.01em"
      }));
      const detailText = compactActivityText(note.detail || "");
      if (detailText && (isCurrent || index >= rows.length - 3)) {
        copy.appendChild(textNode("div", detailText, {
          color: "#9aa49e",
          marginTop: "2px",
          fontSize: "12px"
        }));
      }
      row.appendChild(marker);
      row.appendChild(copy);
      stream.appendChild(row);
    });

    panel.appendChild(stream);
    if (active && isNewJob) {
      try {
        panel.scrollIntoView({ block: "nearest", inline: "nearest" });
      } catch (_) {
        /* Older embedded WebKit builds may not support options here. */
      }
    }
  }

  async function pollActivity() {
    try {
      const turn = lastTurn();
      const params = new URLSearchParams();
      if (turn.client_request_id) {
        params.set("client_request_id", String(turn.client_request_id));
        params.set("active_only", "0");
      } else {
        params.set("active_only", "1");
      }
      const response = await fetch(`${apiBase}/api/reply-progress?${params.toString()}`, {
        cache: "no-store",
        credentials: "include"
      });
      if (!response.ok) return;
      const payload = await response.json();
      let job = (((payload || {}).data || {}).job || null);
      if (!job && turn.client_request_id) {
        const activeResponse = await fetch(`${apiBase}/api/reply-progress?active_only=1`, {
          cache: "no-store",
          credentials: "include"
        });
        if (activeResponse.ok) {
          const activePayload = await activeResponse.json();
          job = (((activePayload || {}).data || {}).job || null);
        }
      }
      if (!job && turn.client_request_id) {
        const recentResponse = await fetch(`${apiBase}/api/reply-progress?active_only=0`, {
          cache: "no-store",
          credentials: "include"
        });
        if (recentResponse.ok) {
          const recentPayload = await recentResponse.json();
          const recentJob = (((recentPayload || {}).data || {}).job || null);
          if (recentJob && activityAgeMs(recentJob) <= 90 * 1000) {
            job = recentJob;
          }
        }
      }
      if (job) {
        renderActivity(job);
      } else if (!lastActivityJobId) {
        removeActivityPanel();
      }
      renderCopilotKitDemos(false);
    } catch (_) {
      /* Activity trace is best-effort and should never interrupt chat. */
    }
  }

  async function markSeen(id, card) {
    remember(hiddenKey, id);
    try {
      await fetch(`${apiBase}/api/eve-chat/followups/${encodeURIComponent(id)}/seen`, {
        method: "POST",
        credentials: "include"
      });
    } catch (_) {
      /* Local UI should still let the user clear a card if the mark call races. */
    }
    card.remove();
  }

  async function markBackendSeen(id) {
    try {
      await fetch(`${apiBase}/api/eve-chat/followups/${encodeURIComponent(id)}/seen`, {
        method: "POST",
        credentials: "include"
      });
    } catch (_) {
      /* The OpenWebUI insert is the durable user-visible write. */
    }
  }

  function render(item) {
    const id = String(item.id || "");
    if (!id || rendered.has(id) || hiddenIds().has(id)) return;
    rendered.add(id);

    const isFailed = String(item.status || "") === "failed";
    const card = document.createElement("article");
    card.dataset.eveFollowupId = id;
    Object.assign(card.style, {
      pointerEvents: "auto",
      border: `1px solid ${isFailed ? "#f2b6aa" : "#b8d7c1"}`,
      borderRadius: "18px",
      background: "linear-gradient(135deg, rgba(255,255,255,0.98), rgba(245,250,247,0.96))",
      color: "#26332d",
      boxShadow: "0 18px 48px rgba(31, 42, 36, 0.18)",
      padding: "16px 16px 14px",
      backdropFilter: "blur(14px)"
    });

    const header = document.createElement("div");
    Object.assign(header.style, {
      display: "flex",
      justifyContent: "space-between",
      gap: "12px",
      alignItems: "center",
      marginBottom: "8px"
    });
    header.appendChild(textNode("strong", isFailed ? "Eve follow-up hit a blocker" : "Eve is ready", {
      fontSize: "14px",
      letterSpacing: "0.01em"
    }));
    header.appendChild(textNode("span", String(item.requested_action || "follow-up").replaceAll("_", " "), {
      fontSize: "11px",
      color: "#66736c",
      textTransform: "uppercase",
      letterSpacing: "0.08em"
    }));

    const body = textNode("p", String(item.delivery_text || item.failure_reason || "The follow-up finished."), {
      whiteSpace: "pre-wrap",
      margin: "0 0 12px",
      lineHeight: "1.45",
      fontSize: "13px",
      color: "#34423a"
    });

    const footer = document.createElement("div");
    Object.assign(footer.style, {
      display: "flex",
      justifyContent: "space-between",
      gap: "12px",
      alignItems: "center"
    });
    footer.appendChild(textNode("span", item.delivered_at ? `Delivered ${item.delivered_at}` : `Follow-up ${id.slice(0, 8)}`, {
      fontSize: "11px",
      color: "#7b8780"
    }));
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Mark seen";
    Object.assign(button.style, {
      border: "0",
      borderRadius: "999px",
      background: "#20382c",
      color: "white",
      padding: "8px 12px",
      fontSize: "12px",
      cursor: "pointer"
    });
    button.addEventListener("click", () => markSeen(id, card));
    footer.appendChild(button);

    card.appendChild(header);
    card.appendChild(body);
    card.appendChild(footer);
    stack().appendChild(card);
  }

  async function insertIntoCurrentThread(item) {
    const id = String(item.id || "");
    if (!id || hiddenIds().has(id) || insertedIds().has(id)) return;
    const target = targetFor(item);
    if (!target.chat_id) {
      render(item);
      return;
    }

    try {
      const response = await fetch("/api/eve-chat/followups/insert", {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: target.chat_id,
          parent_message_id: target.parent_message_id,
          followup: item
        })
      });
      if (!response.ok) {
        render(item);
        return;
      }
      const payload = await response.json();
      if (!payload || payload.ok === false) {
        render(item);
        return;
      }

      remember(insertedKey, id);
      remember(hiddenKey, id);
      await markBackendSeen(id);

      if (currentChatId() === target.chat_id) {
        window.setTimeout(() => window.location.reload(), 450);
      }
    } catch (_) {
      render(item);
    }
  }

  async function poll() {
    try {
      const response = await fetch(
        `${apiBase}/api/eve-chat/followups?surface=eve_chat_ui&status=delivered,failed&include_seen=0&limit=8`,
        { cache: "no-store", credentials: "include" }
      );
      if (!response.ok) return;
      const payload = await response.json();
      const items = (((payload || {}).data || {}).items || []);
      items.forEach(insertIntoCurrentThread);
    } catch (_) {
      /* The chat UI can be open before Eve's backend is ready. Keep polling quietly. */
    }
  }

  installFetchCapture();
  window.EveChatFollowups = {
    pollNow: poll,
    pollActivityNow: pollActivity,
    showCopilotKitDemos: () => renderCopilotKitDemos(true)
  };
  setTimeout(poll, 1000);
  setTimeout(pollActivity, 600);
  setTimeout(() => renderCopilotKitDemos(false), 900);
  setInterval(poll, 4000);
  setInterval(pollActivity, 1200);
  setInterval(() => renderCopilotKitDemos(false), 2400);
})();
""".strip() + "\n"


def rewrite_text_file(path: Path, replacements: dict[str, str]) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        text = path.read_text(encoding="utf-8", errors="ignore")
    original = text
    for old, new in replacements.items():
        text = text.replace(old, new)
    if text == original:
        return 0
    path.write_text(text, encoding="utf-8")
    return sum(original.count(old) for old in replacements)


def runtime_python_files(app_root: Path) -> list[Path]:
    package_roots = [
        app_root / "open_webui",
        app_root,
    ]
    files: list[Path] = []
    for package_root in package_roots:
        if package_root.name != "open_webui":
            continue
        for path in [
            package_root / "env.py",
            package_root / "main.py",
            package_root / "constants.py",
        ]:
            if path.exists() and path.is_file():
                files.append(path)
    return files


def candidate_files(app_root: Path) -> list[Path]:
    build_roots = [
        app_root / "build",
        app_root / "frontend",
        app_root / "open_webui" / "frontend",
    ]
    package_static_roots = [
        app_root / "open_webui" / "static",
        app_root / "static",
    ]
    files: list[Path] = []

    for build_root in build_roots:
        for path in [
            build_root / "index.html",
            build_root / "manifest.json",
            build_root / "opensearch.xml",
            build_root / "static" / "site.webmanifest",
        ]:
            if path.exists() and path.is_file():
                files.append(path)

        if build_root.exists():
            for suffix in ("*.js", "*.json", "*.html", "*.xml", "*.webmanifest", "*.map"):
                files.extend(path for path in build_root.rglob(suffix) if path.is_file())

    for static_root in package_static_roots:
        for path in [
            static_root / "site.webmanifest",
            static_root / "loader.js",
        ]:
            if path.exists() and path.is_file():
                files.append(path)

    # Stable order and de-duplication keep the report deterministic.
    seen: set[Path] = set()
    ordered: list[Path] = []
    for path in files:
        resolved = path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(path)
    return ordered


def frontend_roots(app_root: Path) -> list[Path]:
    roots = [
        app_root / "build",
        app_root / "frontend",
        app_root / "open_webui" / "frontend",
    ]
    return [root for root in roots if (root / "index.html").exists()]


def install_followup_overlay(app_root: Path) -> dict[str, int]:
    scripts_written = 0
    index_changed = 0
    script_tag_pattern = re.compile(
        r'<script\b(?=[^>]*(?:data-eve-chat-followups|eve-chat-followups\.js))[^>]*></script>',
        re.IGNORECASE,
    )
    for root in frontend_roots(app_root):
        script_path = root / FOLLOWUP_SCRIPT_NAME
        old_script = script_path.read_text(encoding="utf-8") if script_path.exists() else ""
        if old_script != FOLLOWUP_SCRIPT:
            script_path.write_text(FOLLOWUP_SCRIPT, encoding="utf-8")
            scripts_written += 1

        index_path = root / "index.html"
        html = index_path.read_text(encoding="utf-8", errors="ignore")
        html, replaced = script_tag_pattern.subn(FOLLOWUP_SCRIPT_TAG, html)
        if replaced:
            index_path.write_text(html, encoding="utf-8")
            index_changed += 1
            continue
        if "</body>" in html:
            html = html.replace("</body>", f"  {FOLLOWUP_SCRIPT_TAG}\n</body>", 1)
        else:
            html = html.rstrip() + "\n" + FOLLOWUP_SCRIPT_TAG + "\n"
        index_path.write_text(html, encoding="utf-8")
        index_changed += 1
    return {"scripts_written": scripts_written, "index_changed": index_changed}


def apply_branding(app_root: Path, brand_name: str, brand_slug: str, mode: str = "small-scale-local") -> dict[str, object]:
    if mode == "off":
        return {
            "mode": mode,
            "brand_name": brand_name,
            "files_changed": 0,
            "replacements": 0,
        }

    replacements = {
        "Open WebUI": brand_name,
        "OpenWebUI": brand_name,
        "open-webui": brand_slug,
        "api.openwebui.com": f"{brand_slug}.local",
        "openwebui.com": f"{brand_slug}.local",
        "openwebui": brand_slug,
    }

    changed_files = 0
    replacement_count = 0
    for path in candidate_files(app_root):
        changed = rewrite_text_file(path, replacements)
        if changed:
            changed_files += 1
            replacement_count += changed

    runtime_replacements = {
        "WEBUI_NAME += ' (Open WebUI)'": "WEBUI_NAME = WEBUI_NAME",
        "title='Open WebUI'": f"title='{brand_name}'",
        "'Open WebUI: Server Connection Error'": f"'{brand_name}: Server Connection Error'",
    }
    for path in runtime_python_files(app_root):
        changed = rewrite_text_file(path, runtime_replacements)
        if changed:
            changed_files += 1
            replacement_count += changed

    followup_report = install_followup_overlay(app_root)

    return {
        "mode": mode,
        "brand_name": brand_name,
        "files_changed": changed_files,
        "replacements": replacement_count,
        "followup_overlay": followup_report,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrub browser-facing upstream branding for Eve Chat.")
    parser.add_argument("--app-root", default="/app", help="Adopted chat UI app root inside the install.")
    parser.add_argument("--brand-name", default=DEFAULT_BRAND_NAME)
    parser.add_argument("--brand-slug", default=DEFAULT_BRAND_SLUG)
    parser.add_argument(
        "--mode",
        default="small-scale-local",
        choices=("small-scale-local", "off"),
        help="Only small-scale-local applies changes; off only reports.",
    )
    args = parser.parse_args()

    if args.mode == "off":
        print("Eve Chat branding scrubber: off")
        return 0

    app_root = Path(args.app_root)
    brand_name = str(args.brand_name or DEFAULT_BRAND_NAME)
    brand_slug = str(args.brand_slug or DEFAULT_BRAND_SLUG)
    report = apply_branding(app_root, brand_name, brand_slug, args.mode)

    print(
        "Eve Chat branding scrubber: "
        f"brand={brand_name!r} files_changed={report['files_changed']} "
        f"replacements={report['replacements']} followup_overlay={report.get('followup_overlay')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
