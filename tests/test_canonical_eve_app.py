from __future__ import annotations

import os
import re
import signal
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_builder_produces_one_canonical_eve_bundle() -> None:
    builder = (ROOT / "script" / "build_eve_chat_app.sh").read_text(encoding="utf-8")

    assert 'APP_NAME="Eve"' in builder
    assert 'BUNDLE_ID="${EVE_APP_BUNDLE_ID:-local.eve.app}"' in builder
    assert '<string>3.5</string>' in builder
    assert '<string>12</string>' in builder
    assert "evechat" not in builder
    assert "eve_app_surface.sh" in builder
    assert "eve_app_server.py" in builder
    assert "using the existing validated eve.icns" in builder
    assert 'apple-macos13.0' in builder
    for source in ("EveNativeSpeechBridge.swift", "EveNativeIntelligence.swift", "EveAppIntents.swift"):
        assert source in builder
    for framework in ("Speech", "FoundationModels", "AppIntents", "CoreSpotlight"):
        assert f"-framework {framework}" in builder
    assert "appintentsmetadataprocessor" in builder
    assert "extract.actionsdata" in builder
    assert 'grep -q \'"OpenEveIntent"\'' in builder
    assert 'grep -q \'"openAppWhenRun":true\'' in builder
    assert "eve_spotlight_projection.py" in builder
    assert "open-webui" not in builder.lower()
    assert "eve_chat_surface_lab.sh" not in builder


def test_canonical_app_and_runtime_share_typed_conversation_json_boundaries() -> None:
    app_server = (ROOT / "bin" / "eve_app_server.py").read_text(encoding="utf-8")
    runtime = (ROOT / "eve_web.py").read_text(encoding="utf-8")

    assert "import eve_http_json" in app_server
    assert "import eve_http_json" in runtime
    assert 'boolean_field(payload, "stream"' in app_server
    assert 'boolean_field(payload, "stream"' in runtime
    assert 'object_list_field(\n            payload,\n            "attachments"' in runtime
    assert 'bool(payload.get("stream"' not in app_server
    assert 'bool(payload.get("stream"' not in runtime
    assert "message_id[:160]" not in app_server
    assert "body_text[:8000]" not in app_server


def test_builder_restarts_only_a_verified_eve_app_server() -> None:
    builder = (ROOT / "script" / "build_eve_chat_app.sh").read_text(encoding="utf-8")

    assert 'surface_pid_hint="$(cat "${SURFACE_PID_PATH}"' in builder
    assert '"${surface_pid_hint}" =~ ^[1-9][0-9]*$' in builder
    assert '"${surface_pid_hint}" != "1"' in builder
    assert 'surface_pid=""' in builder
    assert 'if [[ "${surface_command}" == *eve_app_server.py* ]]' in builder
    assert 'lsof -tiTCP:3000 -sTCP:LISTEN' in builder
    assert "Port 3000 belongs to an unrelated process; leaving it untouched" in builder


def test_surface_launcher_does_not_signal_a_reused_unrelated_pid() -> None:
    unrelated = subprocess.Popen(["sleep", "30"])
    surface_pid = None
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            runtime = root / "runtime"
            fake_bin = root / "bin"
            marker = root / "surface-ready"
            runtime.mkdir()
            fake_bin.mkdir()
            (runtime / "eve-app.pid").write_text(f"{unrelated.pid}\n", encoding="utf-8")

            fake_curl = fake_bin / "curl"
            fake_curl.write_text(
                """#!/bin/sh
case "$*" in
  */health*)
    if [ -f "$EVE_TEST_SURFACE_MARKER" ]; then
      printf '%s\n' '{"ok":true,"surface":"eve-app","backend_ok":true}'
    else
      printf '%s\n' '{"ok":false,"surface":"eve-app","backend_ok":false}'
    fi
    ;;
  */v1/models*) printf '%s\n' '{"data":[{"id":"eve"}]}' ;;
  *) exit 1 ;;
esac
""",
                encoding="utf-8",
            )
            fake_python = fake_bin / "python3"
            fake_python.write_text(
                "#!/bin/sh\n: > \"$EVE_TEST_SURFACE_MARKER\"\nsleep 30\n",
                encoding="utf-8",
            )
            fake_curl.chmod(0o755)
            fake_python.chmod(0o755)
            env = {
                **os.environ,
                "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
                "EVE_APP_RUNTIME_ROOT": str(runtime),
                "EVE_APP_PYTHON": str(fake_python),
                "EVE_APP_PORT": "39891",
                "EVE_TEST_SURFACE_MARKER": str(marker),
            }
            result = subprocess.run(
                ["bash", str(ROOT / "bin" / "eve_app_surface.sh")],
                cwd=ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            surface_pid = int((runtime / "eve-app.pid").read_text(encoding="utf-8").strip())

        assert unrelated.poll() is None
        assert f"Ignoring stale Eve app PID {unrelated.pid}" in result.stderr
        assert "Eve is ready" in result.stdout
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=5)
        if surface_pid:
            try:
                os.kill(surface_pid, signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_native_health_monitor_is_activity_aware_and_foreground_eager() -> None:
    source = (ROOT / "mac" / "EveChatApp.swift").read_text(encoding="utf-8")

    assert "NSApp.isActive ? 30_000_000_000 : 120_000_000_000" in source
    assert "failures > 0 && NSApp.isActive" in source
    assert "return 2_000_000_000" in source
    assert "15_000_000_000" not in source
    assert "func verifyHealthNow()" in source
    assert "beginHealthMonitor(checkImmediately: true)" in source
    assert "@Environment(\\.scenePhase)" in source
    assert ".onChange(of: scenePhase)" in source
    assert "phase == .active" in source
    assert "healthMonitorGeneration == generation" in source
    assert "consecutiveFailures >= 2" in source


def test_local_clients_encode_dynamic_ids_as_one_opaque_path_segment() -> None:
    canonical_client = (ROOT / "web" / "eve_app" / "app.js").read_text(encoding="utf-8")
    legacy_client = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    desktop_model = (ROOT / "mac" / "EveDesktopModel.swift").read_text(encoding="utf-8")
    monitor_model = (ROOT / "mac" / "EveMonitorModel.swift").read_text(encoding="utf-8")

    assert "/api/messages/${encodeURIComponent(messageId)}/mark" in canonical_client
    assert "/api/messages/${encodeURIComponent(job.reply_message_id)}" in canonical_client
    assert "/api/thread/${encodeURIComponent(threadId)}" in legacy_client
    assert "/api/thread/${encodeURIComponent(state.selectedThreadId)}" in legacy_client
    assert "/api/messages/${encodeURIComponent(message.id)}/mark" in legacy_client
    assert "routeSegmentCharacters" in desktop_model
    assert "encodedRouteSegment(threadID)" in desktop_model
    assert "routeSegmentCharacters" in monitor_model
    assert "encodedRouteSegment(threadID)" in monitor_model
    assert "components?.percentEncodedPath" in monitor_model
    assert ".urlPathAllowed" not in monitor_model


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
    launcher = (ROOT / "bin" / "eve_app_surface.sh").read_text(encoding="utf-8")
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
    assert "process.executableURL = URL(fileURLWithPath: launcher)" in source
    assert 'URL(fileURLWithPath: "/bin/zsh")' not in source
    assert 'process.arguments = ["-lc", command]' not in source
    assert 'eve-app-launch.log' in source
    assert "process.terminationStatus" in source
    assert "Pipe()" not in source
    assert "openPrivateLaunchLog" in source
    assert "O_NOFOLLOW" in source
    assert "S_IRUSR | S_IWUSR" in source
    assert "Darwin.fchmod" in source
    assert "launchDiagnosticByteLimit: UInt64 = 32 * 1024" in source
    assert "process.standardOutput = logHandle" in source
    assert "process.standardError = logHandle" in source
    assert "readLaunchDiagnosticTail" in source
    assert "handle.seekToEnd()" in source
    assert "handle.seek(toOffset: startOffset)" in source
    assert "readDataToEndOfFile" not in source
    health_check = launcher.split("surface_ready() {", 1)[1].split("\n}", 1)[0]
    assert '"surface": "eve-app"' in health_check
    assert '"backend_ok": true' in health_check
    assert "is_valid_pid" in launcher
    assert "is_eve_app_surface_process" in launcher
    assert "Ignoring stale Eve app PID" in launcher
    assert "Ignoring invalid Eve app PID file contents" in launcher
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
    assert 'styles.css?v=12' in html
    assert 'app.js?v=12' in html
    assert 'id="show-live"' in html
    assert 'id="identity-badge"' in html
    assert 'id="identity-place"' in html
    assert 'class="eve-field"' in html
    assert 'data-eve-state="connecting"' in html
    assert ".eve-field-current" in styles
    assert 'body[data-eve-state="thinking"]' in styles
    assert "@keyframes eve-field-breathe" in styles
    assert "EveNativeSurfaceField" in source
    for bridge_name in ("eveNativeSpeech", "eveNativeIntelligence", "eveNativeIndex"):
        assert bridge_name in source
    assert "configureNativeBridges" in client
    assert "window.EveNativeSpeech" in client
    assert "window.EveNativeIntelligence" in client
    assert "window.EveNativeIndex" in client
    assert 'new Set(["classify", "extract", "observe", "summarize"])' in client
    assert 'postNativeMessage("eveNativeIntelligence", { action: "status" })' in client
    assert "window.EveNativeIntelligence.run(" not in client
    assert 'postNativeMessage("eveNativeIndex", { action: "refresh" })' in client
    assert "startVoiceInput" in client and "stopVoiceInput" in client
    assert "Eve — live" not in client
    assert 'eventType: "thought"' in client
    assert 'eventType: "action"' in client
    assert 'eventType: "reflection"' in client
    assert 'fetchLiveData("/api/eve-app/snapshot")' in client
    assert 'payload.schema !== "eve_app_snapshot.v1"' in client
    assert "/api/messages?" not in client
    assert "/api/thoughts?" not in client
    assert "/api/activity?" not in client
    assert "/api/reflections?" not in client
    assert "/api/personal-conversation/status" not in client
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
    assert "document.hidden ? 60000 : 10000" in client
    assert "setInterval(refreshStatus" not in client
    assert "const refreshed = await refreshLiveStream()" in client
    assert "if (!refreshed)" in client
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
