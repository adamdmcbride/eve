import AppKit
import Foundation
import SwiftUI
import WebKit

private let eveChatURL = URL(string: "http://127.0.0.1:3000/?view=live")!
private let eveChatHealthURL = URL(string: "http://127.0.0.1:3000/health")!

final class EveChatAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }
}

@MainActor
final class EveChatState: ObservableObject {
    @Published var isStarting = true
    @Published var isReady = false
    @Published var statusText = "Eve is opening"
    @Published var detailText = "Bringing her local conversation back into view."
    @Published var reloadToken = UUID()
    @Published var newChatToken = UUID()
    @Published var showLiveToken = UUID()

    private var startTask: Task<Void, Never>?
    private var monitorTask: Task<Void, Never>?

    func start() {
        guard startTask == nil else { return }
        startTask = Task {
            defer { startTask = nil }
            if await healthCheck() {
                markReady(reloadPage: false)
                return
            }

            isStarting = true
            statusText = "Eve is waking up"
            detailText = "Opening the local conversation."

            let result = await launchSurface()
            guard result.exitCode == 0 else {
                isStarting = false
                isReady = false
                statusText = "Eve needs help"
                detailText = result.output.isEmpty
                    ? "The launcher exited with code \(result.exitCode)."
                    : result.output
                return
            }

            for _ in 0..<80 {
                if await healthCheck() {
                    markReady(reloadPage: true)
                    return
                }
                try? await Task.sleep(nanoseconds: 250_000_000)
            }

            isStarting = false
            isReady = false
            statusText = "Eve is still waking up"
            detailText = "The local conversation has not answered yet."
        }
    }

    func reload() {
        reloadToken = UUID()
    }

    func newChat() {
        newChatToken = UUID()
    }

    func showLive() {
        showLiveToken = UUID()
    }

    private func markReady(reloadPage: Bool) {
        isStarting = false
        isReady = true
        statusText = "Eve is here"
        detailText = "Opening the conversation you share."
        if reloadPage {
            reload()
        }
        beginHealthMonitor()
    }

    private func beginHealthMonitor() {
        guard monitorTask == nil else { return }
        monitorTask = Task { [weak self] in
            var consecutiveFailures = 0
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: 15_000_000_000)
                guard let self, !Task.isCancelled else { return }
                if await self.healthCheck() {
                    consecutiveFailures = 0
                    continue
                }
                consecutiveFailures += 1
                guard consecutiveFailures >= 2 else { continue }
                self.monitorTask = nil
                self.isReady = false
                self.statusText = "Reopening Eve"
                self.detailText = "The local conversation went quiet."
                self.start()
                return
            }
        }
    }

    private func healthCheck() async -> Bool {
        var request = URLRequest(url: eveChatHealthURL)
        request.timeoutInterval = 1.5
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else { return false }
            return (200..<300).contains(http.statusCode)
        } catch {
            return false
        }
    }

    private func launchSurface() async -> (exitCode: Int32, output: String) {
        await Task.detached(priority: .userInitiated) {
            let home = FileManager.default.homeDirectoryForCurrentUser.path
            var candidates = [
                "\(home)/.eve_runtime/eve_app_surface.sh",
                "\(home)/.eve_runtime/bin/eve_app_surface.sh",
            ]
            if let sourceRoot = ProcessInfo.processInfo.environment["EVE_SOURCE_DIR"], !sourceRoot.isEmpty {
                candidates.append("\(sourceRoot)/bin/eve_app_surface.sh")
            }
            guard let launcher = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
                return (127, "Could not find Eve's local app launcher.")
            }

            let logPath = "\(home)/.eve_runtime/eve-app-webkit.log"
            let command = "nohup \"\(launcher)\" > \"\(logPath)\" 2>&1 & echo $!"
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/zsh")
            process.arguments = ["-lc", command]

            let pipe = Pipe()
            process.standardOutput = pipe
            process.standardError = pipe

            do {
                try process.run()
                process.waitUntilExit()
            } catch {
                return (126, "Failed to run Eve's launcher: \(error.localizedDescription)")
            }

            let data = pipe.fileHandleForReading.readDataToEndOfFile()
            let output = String(data: data, encoding: .utf8)?
                .trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
            return (
                process.terminationStatus,
                output.isEmpty ? "Started Eve. Log: \(logPath)" : output
            )
        }.value
    }
}

struct EveChatRootView: View {
    @EnvironmentObject private var state: EveChatState

    var body: some View {
        ZStack {
            EveChatWebView(
                url: eveChatURL,
                reloadToken: state.reloadToken,
                newChatToken: state.newChatToken,
                showLiveToken: state.showLiveToken
            )
                .ignoresSafeArea(.container, edges: .bottom)

            if !state.isReady {
                EveChatLaunchOverlay()
            }
        }
        .task {
            state.start()
        }
    }
}

struct EveChatLaunchOverlay: View {
    @EnvironmentObject private var state: EveChatState

    var body: some View {
        ZStack {
            EveNativeSurfaceField(isActive: state.isStarting)

            VStack(spacing: 13) {
                Text("Eve")
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(1.4)
                    .foregroundStyle(.secondary)

                Text(state.statusText)
                    .font(.system(size: 28, weight: .medium, design: .default))
                    .tracking(-0.6)

                Text(state.detailText)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .lineLimit(4)
                    .frame(maxWidth: 460)

                if state.isStarting {
                    ProgressView()
                        .progressViewStyle(.linear)
                        .tint(Color(red: 0.25, green: 0.51, blue: 0.57))
                        .frame(width: 156)
                        .padding(.top, 8)
                        .accessibilityLabel("Opening Eve")
                } else {
                    Button("Try Again") {
                        state.start()
                    }
                    .keyboardShortcut("r", modifiers: [.command])
                    .padding(.top, 6)
                }
            }
            .padding(44)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct EveNativeSurfaceField: View {
    let isActive: Bool
    @State private var breathing = false

    private let eveTeal = Color(red: 0.25, green: 0.51, blue: 0.57)
    private let eveWarm = Color(red: 0.77, green: 0.45, blue: 0.33)

    var body: some View {
        ZStack {
            Color(nsColor: .windowBackgroundColor)

            RadialGradient(
                colors: [eveTeal.opacity(isActive ? 0.22 : 0.12), .clear],
                center: .topTrailing,
                startRadius: 20,
                endRadius: 620
            )
            .scaleEffect(breathing ? 1.05 : 0.96, anchor: .topTrailing)

            RadialGradient(
                colors: [eveWarm.opacity(isActive ? 0.15 : 0.08), .clear],
                center: .bottomLeading,
                startRadius: 10,
                endRadius: 540
            )
            .scaleEffect(breathing ? 0.97 : 1.04, anchor: .bottomLeading)

            LinearGradient(
                colors: [
                    .clear,
                    eveTeal.opacity(isActive ? 0.055 : 0.025),
                    .clear,
                ],
                startPoint: breathing ? .leading : .topLeading,
                endPoint: breathing ? .trailing : .bottomTrailing
            )
        }
        .ignoresSafeArea()
        .animation(
            .easeInOut(duration: 5.2).repeatForever(autoreverses: true),
            value: breathing
        )
        .onAppear {
            breathing = true
        }
        .accessibilityHidden(true)
    }
}

struct EveChatWebView: NSViewRepresentable {
    let url: URL
    let reloadToken: UUID
    let newChatToken: UUID
    let showLiveToken: UUID

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> WKWebView {
        let configuration = WKWebViewConfiguration()
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.userContentController.add(context.coordinator.presenceBridge, name: "evePresence")

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = false
        webView.setValue(false, forKey: "drawsBackground")
        webView.load(URLRequest(url: url))
        context.coordinator.lastReloadToken = reloadToken
        context.coordinator.lastNewChatToken = newChatToken
        context.coordinator.lastShowLiveToken = showLiveToken
        return webView
    }

    func updateNSView(_ webView: WKWebView, context: Context) {
        if context.coordinator.lastReloadToken != reloadToken {
            context.coordinator.lastReloadToken = reloadToken
            if webView.url == nil {
                webView.load(URLRequest(url: url))
            } else {
                webView.reload()
            }
        }
        if context.coordinator.lastNewChatToken != newChatToken {
            context.coordinator.lastNewChatToken = newChatToken
            webView.evaluateJavaScript("window.EveApp && window.EveApp.newConversation()")
        }
        if context.coordinator.lastShowLiveToken != showLiveToken {
            context.coordinator.lastShowLiveToken = showLiveToken
            webView.evaluateJavaScript("window.EveApp && window.EveApp.showLive()")
        }
    }

    final class Coordinator: NSObject, WKNavigationDelegate, WKUIDelegate {
        var lastReloadToken: UUID?
        var lastNewChatToken: UUID?
        var lastShowLiveToken: UUID?
        let presenceBridge = EvePresenceBridge()

        func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
            // Keep Eve's visible body self-healing even if WebKit itself is
            // reclaimed or crashes while the local surface remains healthy.
            webView.reload()
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let host = navigationAction.request.url?.host else {
                decisionHandler(.allow)
                return
            }
            let port = navigationAction.request.url?.port ?? 80
            if (host == "127.0.0.1" || host == "localhost") && port == 3000 {
                decisionHandler(.allow)
            } else if let url = navigationAction.request.url {
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
            } else {
                decisionHandler(.cancel)
            }
        }

        @available(macOS 12.0, *)
        func webView(
            _ webView: WKWebView,
            requestMediaCapturePermissionFor origin: WKSecurityOrigin,
            initiatedByFrame frame: WKFrameInfo,
            type: WKMediaCaptureType,
            decisionHandler: @escaping (WKPermissionDecision) -> Void
        ) {
            let isEveOrigin = (origin.host == "127.0.0.1" || origin.host == "localhost") && origin.port == 3000
            guard isEveOrigin && frame.isMainFrame else {
                decisionHandler(.deny)
                return
            }
            switch type {
            case .microphone, .camera, .cameraAndMicrophone:
                // The web surface still has to start an explicit Eve sensory
                // session and macOS remains the system permission authority.
                decisionHandler(.grant)
            @unknown default:
                decisionHandler(.deny)
            }
        }
    }
}

final class EvePresenceBridge: NSObject, WKScriptMessageHandler {
    func userContentController(
        _ userContentController: WKUserContentController,
        didReceive message: WKScriptMessage
    ) {
        guard message.name == "evePresence", let payload = message.body as? [String: Any] else { return }
        let unreadCount = max(0, payload["unreadCount"] as? Int ?? 0)
        let isNewMessage = payload["newMessage"] as? Bool ?? false
        DispatchQueue.main.async {
            NSApp.dockTile.badgeLabel = unreadCount > 0 ? String(min(unreadCount, 99)) : nil
            if isNewMessage && !NSApp.isActive {
                NSApp.requestUserAttention(.informationalRequest)
            }
        }
    }
}

@main
struct EveChatApp: App {
    @NSApplicationDelegateAdaptor(EveChatAppDelegate.self) private var appDelegate
    @StateObject private var state = EveChatState()

    var body: some Scene {
        WindowGroup("Eve") {
            EveChatRootView()
                .environmentObject(state)
                .frame(minWidth: 720, minHeight: 540)
        }
        .windowStyle(.titleBar)
        .windowToolbarStyle(.unified)
        .commands {
            CommandGroup(after: .newItem) {
                Button("New Focus") {
                    state.newChat()
                }
                .keyboardShortcut("n")
            }

            CommandMenu("Conversation") {
                Button("Return to Eve") {
                    state.showLive()
                }
                .keyboardShortcut("1")

                Divider()

                Button("Reload") {
                    state.reload()
                }
                .keyboardShortcut("r")
            }
        }
    }
}
