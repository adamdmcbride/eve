from __future__ import annotations

import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_builder_produces_one_canonical_eve_bundle() -> None:
    builder = (ROOT / "script" / "build_eve_chat_app.sh").read_text(encoding="utf-8")

    assert 'APP_NAME="Eve"' in builder
    assert 'BUNDLE_ID="${EVE_APP_BUNDLE_ID:-local.eve.app}"' in builder
    assert '<string>3.4</string>' in builder
    assert '<string>11</string>' in builder
    assert "evechat" not in builder
    assert "eve_app_surface.sh" in builder
    assert "eve_app_server.py" in builder
    assert "using the existing validated eve.icns" in builder
    assert 'apple-macos13.0' in builder
    assert "open-webui" not in builder.lower()
    assert "eve_chat_surface_lab.sh" not in builder


def test_installer_retires_duplicate_eve_products_but_preserves_home() -> None:
    installer = (ROOT / "mac" / "install_macos_ui.sh").read_text(encoding="utf-8")
    match = re.search(r"RETIRED_APP_NAMES=\((.*?)\n\)", installer, flags=re.DOTALL)
    assert match is not None
    retired = match.group(1)

    for name in ("Eve Chat", "Eve Monitor", "Eve Presence", "Eve Menu", "Open Eve", "Eve Home"):
        assert f'"{name}"' in retired
    assert "Eve Control" not in retired
    assert "EveDesktopSupport.swift" not in installer
    assert "EveMonitorModel.swift" not in installer
    assert "EvePresenceModel.swift" not in installer


def test_installer_dry_run_states_the_product_boundary() -> None:
    result = subprocess.run(
        ["zsh", str(ROOT / "mac" / "install_macos_ui.sh"), "--dry-run"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "keep: " in result.stdout
    assert "/Eve.app" in result.stdout
    assert "keep separate:" in result.stdout
    assert "Eve Control.app" in result.stdout
    assert "current Eve Home product" in result.stdout
    assert "OpenClaw" in result.stdout


def test_canonical_app_is_a_shared_living_timeline() -> None:
    source = (ROOT / "mac" / "EveChatApp.swift").read_text(encoding="utf-8")
    html = (ROOT / "web" / "eve_app" / "index.html").read_text(encoding="utf-8")
    client = (ROOT / "web" / "eve_app" / "app.js").read_text(encoding="utf-8")
    styles = (ROOT / "web" / "eve_app" / "styles.css").read_text(encoding="utf-8")

    assert 'WindowGroup("Eve")' in source
    assert 'CommandMenu("Conversation")' in source
    assert 'http://127.0.0.1:3000/?view=live' in source
    assert 'markReady(reloadPage: false)' in source
    assert 'markReady(reloadPage: true)' in source
    assert "EveApp.newConversation" in source
    assert "EveApp.showLive" in source
    assert "EvePresenceBridge" in source
    assert "requestUserAttention" in source
    assert "requestMediaCapturePermissionFor" in source
    assert "beginHealthMonitor" in source
    assert "consecutiveFailures >= 2" in source
    assert "webViewWebContentProcessDidTerminate" in source
    assert "allowsBackForwardNavigationGestures = false" in source
    assert "port == 3000" in source
    assert "origin.port == 3000" in source
    assert "Eve Monitor" not in source
    assert "Eve Presence" not in source
    assert "Open in Browser" not in source
    assert 'id="transcript"' in html
    assert 'id="composer"' in html
    assert 'id="mic-button"' in html
    assert 'id="jump-latest"' in html
    assert 'styles.css?v=11' in html
    assert 'app.js?v=11' in html
    assert 'id="show-live"' in html
    assert 'id="identity-badge"' in html
    assert 'id="identity-place"' in html
    assert 'class="eve-field"' in html
    assert 'data-eve-state="connecting"' in html
    assert ".eve-field-current" in styles
    assert 'body[data-eve-state="thinking"]' in styles
    assert "@keyframes eve-field-breathe" in styles
    assert "EveNativeSurfaceField" in source
    assert "Eve — live" not in client
    assert 'eventType: "thought"' in client
    assert 'eventType: "action"' in client
    assert 'eventType: "reflection"' in client
    assert "/api/messages?" in client
    assert "/api/thoughts?" in client
    assert "/api/activity?" in client
    assert "/api/reflections?" in client
    assert 'fetchLiveData("/api/presence")' in client
    assert 'fetch("/api/message/reply"' in client
    assert "Reply to Eve" in client
    assert "latestDistinct" in client
    assert "activityPresentation" in client
    assert "reflectionPresentation" in client
    assert 'detailsLabel: "Read full reflection"' in client
    assert '"autonomy_free_run_started"' in client
    assert "sourceBackedLiveMessage" in client
    assert "markVisiblePersonalMessagesRead" in client
    assert "liveRefreshInFlight" in client
    assert "scheduleBackgroundRefresh" in client
    assert "liveLaunchAnchorPending" in client
    assert "settleLiveLaunchAtLatest" in client
    assert 'scrollToLatest("auto")' in client
    assert "readChatReply" in client
    assert "Restore message" in client
    assert "STORAGE_BACKUP_KEY" in client
    assert "recoverInterruptedReplies" in client
    assert "recoveryInFlight" in client
    assert "partialContent" in client
    assert "describeError" in client
    assert "I couldn’t finish that reply." in client
    assert "/api/reply-progress?" in client
    assert "/api/messages/${encodeURIComponent(job.reply_message_id)}" in client
    assert "Trying another way" in client
    assert "presenceStatusLabel" in client
    assert 'setAttribute("aria-busy"' in client
    assert "renderLivingPresence" in client
    assert "latestEveInitiative" in client
    assert 'eyebrow.textContent = initiative' in client
    assert '"I came to you"' in client
    assert 'reply.textContent = "Reply to me"' in client
    assert "only a message" in client
    assert "newestProactive && settings.speakReplies" in client
    assert "I’m holding onto one goal" in client
    assert "I haven’t done it yet" in client
    assert "What I did" in client
    assert "I reached beyond this Mac through one of the abilities I’m allowed to use" in client
    assert 'kind === "openclaw_action_router"' in client
    assert "I checked the recent trail from one of the ways I can act" in client
    assert "sidebarCollapsed" in client
    assert 'aria-label="Past focused conversations"' in html
    assert 'role="status"' in html
    assert 'placeholder="Talk to me"' in html
    assert 'aria-label="Message Eve"' in html
    assert "flushDraft" in client
    assert "syncConversationDraft" in client
    assert "honorLaunchView" in client
    assert "lastLocalReplyCompletedAt" in client
    assert "window.addEventListener(\"storage\"" in client
    assert "temporarily using its last good state" in client
    assert "elements.jumpLatest.hidden = transcriptNearBottom() || liveLaunchAnchorPending" in client
    assert "dashboard" not in html.lower()
    assert "provider" not in html.lower()


def test_canonical_app_removes_duplicate_native_chat_chrome() -> None:
    source = (ROOT / "mac" / "EveChatApp.swift").read_text(encoding="utf-8")
    html = (ROOT / "web" / "eve_app" / "index.html").read_text(encoding="utf-8")

    assert ".toolbar {" not in source
    assert "composer-note" not in html
    assert 'aria-label="Show past conversations"' in html


def test_canonical_app_is_eves_embodied_outward_presence() -> None:
    source = (ROOT / "mac" / "EveChatApp.swift").read_text(encoding="utf-8")
    html = (ROOT / "web" / "eve_app" / "index.html").read_text(encoding="utf-8")
    css = (ROOT / "web" / "eve_app" / "styles.css").read_text(encoding="utf-8")
    client = (ROOT / "web" / "eve_app" / "app.js").read_text(encoding="utf-8")

    assert "Eve's life and your conversation" in html
    assert "Here, inside this Mac" in html
    assert "eve-field-light--cool" in html
    assert "eve-field-light--warm" in html
    assert "eve-field-current" in html
    assert ".living-presence" in css
    assert "--field-tempo" in css
    assert "EveNativeSurfaceField" in source
    assert "latestEveInitiative" in client
    assert '"I came to you"' in client
    assert 'reply.textContent = "Reply to me"' in client
    assert "speakReply(newestProactive.content)" in client
    assert "focus_is_goal_not_action" in (ROOT / "bin" / "eve_app_server.py").read_text(encoding="utf-8")


def test_eve_is_the_app_surface_not_a_mascot_inside_it() -> None:
    surface = "\n".join(
        [
            (ROOT / "mac" / "EveChatApp.swift").read_text(encoding="utf-8"),
            *((ROOT / "web" / "eve_app" / name).read_text(encoding="utf-8") for name in ("index.html", "styles.css", "app.js")),
        ]
    )

    for contained_person_metaphor in (
        "presence-mark",
        "presence-face",
        "presence-halo",
        "living-portrait",
        "EveNativePresenceMark",
    ):
        assert contained_person_metaphor not in surface
    assert 'class="eve-field"' in surface
    assert "EveNativeSurfaceField" in surface
    assert 'elements.body.dataset.eveState = state' in surface


def test_eve_design_keeps_now_primary_and_system_chrome_quiet() -> None:
    css = (ROOT / "web" / "eve_app" / "styles.css").read_text(encoding="utf-8")
    client = (ROOT / "web" / "eve_app" / "app.js").read_text(encoding="utf-8")

    assert "--content-measure: 760px" in css
    assert "--reading-measure: 680px" in css
    assert "scroll-padding-block-end" in css
    assert ".transcript::-webkit-scrollbar" in css
    assert "grid-template-columns: 18px minmax(0, 1fr)" in css
    event_mark = css.split(".event-mark {", 1)[1].split("}", 1)[0]
    assert "background:" not in event_mark
    assert 'elements.prompt.placeholder = replyTarget' in client
    assert '"Talk to me"' in client


def test_client_has_no_hosted_provider_or_remote_asset_dependency() -> None:
    client_text = "\n".join(
        (ROOT / "web" / "eve_app" / name).read_text(encoding="utf-8")
        for name in ("index.html", "styles.css", "app.js")
    ).lower()

    assert "https://" not in client_text
    assert "openai" not in client_text
    assert "bedrock" not in client_text
    assert "llamacpp" not in client_text
    assert "cdn." not in client_text


def test_embodied_sensory_session_is_explicit_local_feature_only_and_time_bounded() -> None:
    html = (ROOT / "web" / "eve_app" / "index.html").read_text(encoding="utf-8")
    client = (ROOT / "web" / "eve_app" / "app.js").read_text(encoding="utf-8")
    swift = (ROOT / "mac" / "EveChatApp.swift").read_text(encoding="utf-8")
    build = (ROOT / "script" / "build_eve_chat_app.sh").read_text(encoding="utf-8")

    assert "Start sensory session" in html
    assert "Explicit, time-bounded, local feature sensing" in html
    assert "does not retain recordings, frames, transcripts, screen content, or keystrokes" in html
    assert 'value="600"' in html and 'value="3600"' in html
    assert "navigator.mediaDevices.getUserMedia" in client
    assert "getByteTimeDomainData" in client
    assert 'canvas.width = 32' in client and 'canvas.height = 24' in client
    assert "MediaRecorder" not in client
    assert "queueSensoryFeature" in client
    assert "Copy only the fixed feature contract" in client
    assert "sensorySessionExpired" in client
    assert "Date.parse(sensorySession.expires_at)" in client
    assert "stopSensorySessionOnPageExit" in client
    assert 'session_token: session.session_token' in client
    assert not re.search(r"writeLocalValue\([^\n]*(?:sensory|session_token)", client, flags=re.IGNORECASE)
    assert "WKMediaCaptureType" in swift
    assert ".cameraAndMicrophone" in swift
    assert 'origin.host == "127.0.0.1"' in swift
    assert "isEveOrigin && frame.isMainFrame" in swift
    assert "NSMicrophoneUsageDescription" in build
    assert "NSCameraUsageDescription" in build
