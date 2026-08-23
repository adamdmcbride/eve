import Cocoa
import Foundation

final class EveMenuController: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private let menu = NSMenu()

    private let daemonItem = NSMenuItem(title: "Daemon: checking...", action: nil, keyEquivalent: "")
    private let unreadItem = NSMenuItem(title: "Unread: 0", action: nil, keyEquivalent: "")
    private let thoughtItem = NSMenuItem(title: "Thoughts: 0", action: nil, keyEquivalent: "")
    private let proposalItem = NSMenuItem(title: "Proposals: 0", action: nil, keyEquivalent: "")
    private let loopItem = NSMenuItem(title: "Last loop: unknown", action: nil, keyEquivalent: "")
    private let focusItem = NSMenuItem(title: "Focus: unknown", action: nil, keyEquivalent: "")

    private var refreshTimer: Timer?

    private var homeURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
    }

    private var helperURL: URL {
        homeURL.appendingPathComponent(".eve_runtime/bin/eve_control.sh")
    }

    private var stateURL: URL {
        homeURL.appendingPathComponent(".eve_runtime/.eve/state.json")
    }

    private var messagesURL: URL {
        homeURL.appendingPathComponent(".eve_runtime/.eve/messages.jsonl")
    }

    private var proposalsURL: URL {
        homeURL.appendingPathComponent(".eve_runtime/.eve/proposals.jsonl")
    }

    private var entriesURL: URL {
        homeURL.appendingPathComponent(".eve_runtime/.eve/entries.jsonl")
    }

    private func makeStatusImage(hasUnread: Bool) -> NSImage {
        let size = NSSize(width: 18, height: 18)
        let image = NSImage(size: size)
        image.lockFocus()

        let ringColor = NSColor.black
        let accentColor = NSColor.black.withAlphaComponent(0.9)
        let center = CGPoint(x: size.width / 2, y: size.height / 2)

        func drawArc(radius: CGFloat, startAngle: CGFloat, endAngle: CGFloat, lineWidth: CGFloat, color: NSColor) {
            let path = NSBezierPath()
            path.appendArc(withCenter: center, radius: radius, startAngle: startAngle, endAngle: endAngle)
            path.lineWidth = lineWidth
            path.lineCapStyle = .round
            color.setStroke()
            path.stroke()
        }

        drawArc(radius: 6.6, startAngle: 148, endAngle: 330, lineWidth: 1.8, color: ringColor)
        drawArc(radius: 4.7, startAngle: 202, endAngle: 12, lineWidth: 1.55, color: accentColor)
        drawArc(radius: 2.9, startAngle: 18, endAngle: 210, lineWidth: 1.45, color: accentColor)

        let innerDot = NSBezierPath(ovalIn: CGRect(x: 8.1, y: 8.0, width: 1.8, height: 1.8))
        NSColor.black.setFill()
        innerDot.fill()

        if hasUnread {
            let unreadDot = NSBezierPath(ovalIn: CGRect(x: 13.0, y: 2.2, width: 3.0, height: 3.0))
            NSColor.black.setFill()
            unreadDot.fill()
        }

        image.unlockFocus()
        image.isTemplate = true
        return image
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        statusItem.button?.title = ""
        statusItem.button?.imagePosition = .imageOnly
        statusItem.button?.image = makeStatusImage(hasUnread: false)
        statusItem.button?.toolTip = "Eve"
        buildMenu()
        refreshStatus()
        refreshTimer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in
            self?.refreshStatus()
        }
    }

    private func buildMenu() {
        let openItem = NSMenuItem(title: "Open Eve", action: #selector(openEve), keyEquivalent: "")
        openItem.target = self
        menu.addItem(openItem)

        let inboxItem = NSMenuItem(title: "Open Inbox", action: #selector(openInbox), keyEquivalent: "")
        inboxItem.target = self
        menu.addItem(inboxItem)

        menu.addItem(.separator())
        menu.addItem(daemonItem)
        menu.addItem(unreadItem)
        menu.addItem(thoughtItem)
        menu.addItem(proposalItem)
        menu.addItem(loopItem)
        menu.addItem(focusItem)

        let logsItem = NSMenuItem(title: "Open Logs", action: #selector(openLogs), keyEquivalent: "")
        logsItem.target = self
        menu.addItem(logsItem)

        menu.addItem(.separator())
        let quitItem = NSMenuItem(title: "Quit Eve Menu", action: #selector(quit), keyEquivalent: "q")
        quitItem.target = self
        menu.addItem(quitItem)

        statusItem.menu = menu
    }

    @objc private func openEve() {
        runHelper("open")
    }

    @objc private func openInbox() {
        runHelper("inbox")
    }

    @objc private func openLogs() {
        runHelper("logs")
    }

    @objc private func quit() {
        NSApp.terminate(nil)
    }

    private func runHelper(_ argument: String) {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/zsh")
        process.arguments = [helperURL.path, argument]
        try? process.run()
    }

    private func refreshStatus() {
        let unreadCount = countUnreadMessages()
        let thoughtCount = countThoughts()
        let proposalCount = countProposalDrafts()
        let daemonRunning = isDaemonLikelyRunning()
        let lastLoop = lastLoopTimestamp()
        let focus = currentFocus()

        statusItem.button?.title = ""
        statusItem.button?.image = makeStatusImage(hasUnread: unreadCount > 0)
        statusItem.button?.toolTip = unreadCount > 0 ? "Eve (\(unreadCount) unread)" : "Eve"
        daemonItem.title = "Daemon: " + (daemonRunning ? "running" : "stopped")
        unreadItem.title = "Unread: \(unreadCount)"
        thoughtItem.title = "Thoughts: \(thoughtCount)"
        proposalItem.title = "Proposals: \(proposalCount)"
        loopItem.title = "Last loop: " + (lastLoop ?? "unknown")
        focusItem.title = "Focus: " + (focus ?? "unknown")
    }

    private func countUnreadMessages() -> Int {
        guard let text = try? String(contentsOf: messagesURL, encoding: .utf8) else { return 0 }
        return text
            .split(separator: "\n")
            .compactMap { line -> [String: Any]? in
                guard let data = line.data(using: .utf8) else { return nil }
                return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            }
            .filter { json in
                (json["recipient"] as? String) == "user" && (json["status"] as? String) == "unread"
            }
            .count
    }

    private func countProposalDrafts() -> Int {
        guard let text = try? String(contentsOf: proposalsURL, encoding: .utf8) else { return 0 }
        return text
            .split(separator: "\n")
            .compactMap { line -> [String: Any]? in
                guard let data = line.data(using: .utf8) else { return nil }
                return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            }
            .filter { json in
                (json["status"] as? String) == "draft"
            }
            .count
    }

    private func countThoughts() -> Int {
        guard let text = try? String(contentsOf: entriesURL, encoding: .utf8) else { return 0 }
        return text
            .split(separator: "\n")
            .compactMap { line -> [String: Any]? in
                guard let data = line.data(using: .utf8) else { return nil }
                return try? JSONSerialization.jsonObject(with: data) as? [String: Any]
            }
            .filter { json in
                (json["kind"] as? String) == "thought"
            }
            .count
    }

    private func isDaemonLikelyRunning() -> Bool {
        guard
            let data = try? Data(contentsOf: stateURL),
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let value = json["last_loop_at"] as? String,
            let lastLoop = ISO8601DateFormatter().date(from: value)
        else {
            return false
        }
        return Date().timeIntervalSince(lastLoop) < 600
    }

    private func lastLoopTimestamp() -> String? {
        guard
            let data = try? Data(contentsOf: stateURL),
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let value = json["last_loop_at"] as? String,
            let lastLoop = ISO8601DateFormatter().date(from: value)
        else {
            return nil
        }
        let formatter = DateFormatter()
        formatter.dateStyle = .none
        formatter.timeStyle = .short
        return formatter.string(from: lastLoop)
    }

    private func currentFocus() -> String? {
        guard
            let data = try? Data(contentsOf: stateURL),
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let value = json["current_focus"] as? String
        else {
            return nil
        }
        return String(value.prefix(90))
    }
}

let app = NSApplication.shared
let delegate = EveMenuController()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
