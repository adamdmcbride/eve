import AppKit
import Foundation
import SwiftUI

enum MonitorTheme {
    static let accent = Color.accentColor
    static let teal = Color(nsColor: .systemTeal)
    static let amber = Color(nsColor: .systemOrange)
    static let red = Color(nsColor: .systemRed)
    static let blue = Color(nsColor: .systemBlue)
    static let surface = Color(nsColor: .controlBackgroundColor)
    static let elevatedSurface = Color(nsColor: .windowBackgroundColor)
    static let divider = Color.primary.opacity(0.10)
    static let secondaryText = Color.secondary
    static let panelRadius: CGFloat = 12
    static let panelPadding: CGFloat = 14

    static func pressureColor(_ value: Int) -> Color {
        if value >= 80 { return red }
        if value >= 55 { return amber }
        return accent
    }

    static func statusColor(_ isGood: Bool) -> Color {
        isGood ? accent : amber
    }
}

struct MonitorPanelGroupBoxStyle: GroupBoxStyle {
    func makeBody(configuration: Configuration) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            configuration.label
                .font(.headline.weight(.semibold))
                .foregroundStyle(.primary)

            configuration.content
        }
        .padding(MonitorTheme.panelPadding)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: MonitorTheme.panelRadius, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: MonitorTheme.panelRadius, style: .continuous)
                .strokeBorder(MonitorTheme.divider)
        }
    }
}

final class EveMonitorAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSWindow.allowsAutomaticWindowTabbing = false
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        guard !flag else { return true }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) {
            guard !NSApp.windows.contains(where: { $0.isVisible }) else { return }
            let opened = NSApp.sendAction(#selector(NSWindow.newWindowForTab(_:)), to: nil, from: nil)
            if !opened {
                NSApp.sendAction(NSSelectorFromString("newWindow:"), to: nil, from: nil)
            }
        }
        return true
    }
}

private enum MonitorTextSanitizer {
    static let headingRegex = try! NSRegularExpression(pattern: #"#{1,6}\s*"#)
    static let whitespaceRegex = try! NSRegularExpression(pattern: #"\s+"#)

    static func removeMarkdownHeadings(from value: String) -> String {
        replace(headingRegex, in: value, with: "")
    }

    static func collapseWhitespace(in value: String) -> String {
        replace(whitespaceRegex, in: value, with: " ")
    }

    private static func replace(_ regex: NSRegularExpression, in value: String, with template: String) -> String {
        let range = NSRange(value.startIndex..<value.endIndex, in: value)
        return regex.stringByReplacingMatches(in: value, options: [], range: range, withTemplate: template)
    }
}

extension String {
    var monitorTrimmed: String {
        trimmingCharacters(in: .whitespacesAndNewlines)
    }

    var monitorReadable: String {
        var clean = replacingOccurrences(of: "```markdown", with: "")
            .replacingOccurrences(of: "```", with: "")
            .replacingOccurrences(of: "`", with: "")
        if clean.contains("#") {
            clean = MonitorTextSanitizer.removeMarkdownHeadings(from: clean)
        }
        return MonitorTextSanitizer.collapseWhitespace(in: clean)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }

    func monitorLimited(to count: Int) -> String {
        let clean = MonitorTextSanitizer.collapseWhitespace(in: self)
            .trimmingCharacters(in: .whitespacesAndNewlines)
        guard clean.count > count else { return clean }
        let index = clean.index(clean.startIndex, offsetBy: max(0, count - 1))
        return String(clean[..<index]).trimmingCharacters(in: .whitespacesAndNewlines) + "..."
    }
}

struct MonitorFormatters {
    private static let isoFormatterWithFractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private static let isoFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private static let clockFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "h:mm:ss a"
        return formatter
    }()

    private static let dateFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateFormat = "MMM d, h:mm a"
        return formatter
    }()

    static func date(from value: String?) -> Date? {
        guard let value, !value.isEmpty else { return nil }
        if let parsed = isoFormatterWithFractional.date(from: value) {
            return parsed
        }
        return isoFormatter.date(from: value)
    }

    static func clock(_ value: String?) -> String {
        guard let date = date(from: value) else { return "never" }
        return clockFormatter.string(from: date)
    }

    static func clock(_ date: Date?) -> String {
        guard let date else { return "never" }
        return clockFormatter.string(from: date)
    }

    static func dateTime(_ value: String?) -> String {
        guard let date = date(from: value) else { return "never" }
        return dateFormatter.string(from: date)
    }

    static func latency(_ value: Double?) -> String {
        guard let value, value > 0 else { return "n/a" }
        if value < 1000 {
            return "\(Int(value.rounded())) ms"
        }
        let seconds = value / 1000
        return seconds >= 10 ? "\(Int(seconds.rounded())) s" : String(format: "%.1f s", seconds)
    }

    static func percent(_ value: Double?) -> String {
        guard let value else { return "n/a" }
        return "\(Int(value.rounded()))%"
    }

    static func bytes(_ value: Int?) -> String {
        guard let value, value > 0 else { return "" }
        let gib = Double(value) / 1024 / 1024 / 1024
        if gib >= 1 {
            return String(format: "%.1f GiB", gib)
        }
        return "\(Int((Double(value) / 1024 / 1024).rounded())) MiB"
    }
}

func monitorUpdateModeLabel(_ value: String) -> String {
    switch value.monitorTrimmed.lowercased() {
    case "polling", "realtime", "streaming":
        return "Live"
    default:
        return value.isEmpty ? "Live" : value.capitalized
    }
}
