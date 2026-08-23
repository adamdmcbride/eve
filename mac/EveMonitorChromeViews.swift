import SwiftUI

enum MonitorSection: String, CaseIterable, Identifiable, Hashable {
    case overview
    case services
    case chat
    case fromEve
    case activity
    case fitness
    case homeostasis
    case records

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview: return "Overview"
        case .services: return "Services"
        case .chat: return "Chat"
        case .fromEve: return "From Eve"
        case .activity: return "Activity"
        case .fitness: return "Fitness"
        case .homeostasis: return "Homeostasis"
        case .records: return "Records"
        }
    }

    var detail: String {
        switch self {
        case .overview: return "Live state"
        case .services: return "Online/offline"
        case .chat: return "Talk to Eve"
        case .fromEve: return "Eve-initiated"
        case .activity: return "Models and system"
        case .fitness: return "Roadmap truth"
        case .homeostasis: return "Pressures"
        case .records: return "Evidence and tasks"
        }
    }

    var systemImage: String {
        switch self {
        case .overview: return "gauge"
        case .services: return "checklist.checked"
        case .chat: return "bubble.left.and.bubble.right"
        case .fromEve: return "sparkles"
        case .activity: return "waveform.and.magnifyingglass"
        case .fitness: return "checkmark.seal.text.page"
        case .homeostasis: return "waveform.path.ecg"
        case .records: return "tray.full"
        }
    }

    static let monitor: [MonitorSection] = [.overview, .services, .chat, .fromEve, .activity, .fitness, .homeostasis, .records]
}

struct EveMonitorSidebar: View {
    @Binding var selection: String?

    var body: some View {
        List(selection: $selection) {
            Section("Monitor") {
                ForEach(MonitorSection.monitor) { section in
                    SidebarRow(section: section)
                        .tag(section.rawValue)
                }
            }
        }
        .listStyle(.sidebar)
    }
}

private struct SidebarRow: View {
    let section: MonitorSection

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 2) {
                Text(section.title)
                    .lineLimit(1)
                Text(section.detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        } icon: {
            Image(systemName: section.systemImage)
                .symbolRenderingMode(.hierarchical)
                .foregroundStyle(.secondary)
                .frame(width: 18)
        }
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

struct MonitorToolbarState: Equatable {
    let isPoweredOff: Bool
    let isPaused: Bool
    let isPowerChanging: Bool
    let canRefreshWhenPoweredOff: Bool
    let updateMode: String
    let generatedAt: String

    @MainActor
    init(model: EveMonitorModel, selectedSection: MonitorSection) {
        self.isPoweredOff = model.isPoweredOff
        self.isPaused = model.isPaused
        self.isPowerChanging = model.isPowerChanging
        self.canRefreshWhenPoweredOff = selectedSection == .services
        self.updateMode = monitorUpdateModeLabel(model.updateMode)
        self.generatedAt = model.generatedAt
    }
}

struct MonitorToolbar: ToolbarContent {
    let state: MonitorToolbarState
    let togglePower: () -> Void
    let togglePaused: () -> Void
    let refresh: () -> Void
    let reconnect: () -> Void
    let openWebMonitor: () -> Void

    var body: some ToolbarContent {
        ToolbarItem {
            HStack(spacing: 6) {
                Circle()
                    .fill(state.isPoweredOff ? .secondary : (state.isPaused ? MonitorTheme.amber : MonitorTheme.accent))
                    .frame(width: 8, height: 8)
                Text(state.isPoweredOff ? "Off" : (state.isPaused ? "Paused" : state.updateMode))
                    .foregroundStyle(.secondary)
                if state.generatedAt != "never" {
                    Text(state.generatedAt)
                        .foregroundStyle(.tertiary)
                }
            }
            .font(.caption)
        }

        ToolbarItemGroup {
            Button(action: togglePower) {
                Label(state.isPoweredOff ? "Power On" : "Power Off", systemImage: state.isPoweredOff ? "power" : "power.circle")
            }
            .disabled(state.isPowerChanging)
            .help(state.isPoweredOff ? "Power Eve on" : "Power Eve off and keep her stopped across login")

            Button(action: togglePaused) {
                Label(state.isPaused ? "Resume" : "Pause", systemImage: state.isPaused ? "play.fill" : "pause.fill")
            }
            .disabled(state.isPoweredOff || state.isPowerChanging)
            .help(state.isPaused ? "Resume live updates" : "Pause live updates")

            Button(action: refresh) {
                Label("Refresh", systemImage: "arrow.clockwise")
            }
            .disabled((state.isPoweredOff && !state.canRefreshWhenPoweredOff) || state.isPowerChanging)
            .keyboardShortcut("r", modifiers: [.command])
            .help("Refresh now")

            Button(action: reconnect) {
                Label("Reconnect", systemImage: "bolt.horizontal")
            }
            .disabled(state.isPoweredOff || state.isPowerChanging)
            .help("Restart Eve web and reconnect")

            Button(action: openWebMonitor) {
                Label("Open Web Monitor", systemImage: "safari")
            }
            .disabled(state.isPoweredOff || state.isPowerChanging)
            .help("Open the browser monitor")
        }
    }
}

struct MonitorConnectionView: View {
    @EnvironmentObject private var model: EveMonitorModel

    let title: String
    let detail: String
    let isPoweredOff: Bool
    let isPowerChanging: Bool
    let openServices: () -> Void
    let powerOn: () -> Void
    let reconnect: () -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                HStack(alignment: .top, spacing: 16) {
                    ConnectionStatusMark(state: model.serviceSummaryState, isPoweredOff: isPoweredOff)

                    VStack(alignment: .leading, spacing: 8) {
                        Text(title)
                            .font(.title.weight(.semibold))
                            .lineLimit(1)
                            .minimumScaleFactor(0.78)

                        Text(connectionMessage)
                            .font(.callout.weight(.medium))
                            .foregroundStyle(.primary)
                            .fixedSize(horizontal: false, vertical: true)

                        Text(detail.monitorReadable.monitorLimited(to: 180))
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    Spacer(minLength: 0)

                    HStack(spacing: 7) {
                        ConnectionSummaryPill(value: "\(model.serviceOnlineCount)", label: "Online", state: .online)
                        ConnectionSummaryPill(value: "\(model.serviceOfflineCount)", label: "Offline", state: .offline)
                    }
                }
                .padding(18)
                .background(.thinMaterial, in: RoundedRectangle(cornerRadius: MonitorTheme.panelRadius, style: .continuous))
                .overlay {
                    RoundedRectangle(cornerRadius: MonitorTheme.panelRadius, style: .continuous)
                        .strokeBorder(MonitorTheme.divider)
                }

                HStack(spacing: 10) {
                    Button(action: powerOn) {
                        Label(isPoweredOff ? "Power On" : "Start Eve", systemImage: "power")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isPowerChanging)

                    Button(action: reconnect) {
                        Label("Reconnect", systemImage: "arrow.clockwise")
                    }
                    .disabled(isPoweredOff || isPowerChanging)

                    Button(action: openServices) {
                        Label("Services", systemImage: "checklist.checked")
                    }
                }
                .controlSize(.large)

                GroupBox("Recovery") {
                    VStack(alignment: .leading, spacing: 12) {
                        Text("The monitor can still probe local services while the main API is unavailable.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)

                        VStack(spacing: 0) {
                            ForEach(Array(connectionRows.enumerated()), id: \.element.id) { index, row in
                                if index > 0 { Divider() }
                                ConnectionServiceRow(row: row)
                            }
                        }

                        Button {
                            Task { await model.refreshServiceStatuses() }
                        } label: {
                            Label("Check Again", systemImage: "arrow.clockwise")
                        }
                        .buttonStyle(.borderless)
                        .font(.callout.weight(.medium))
                    }
                }
            }
            .padding(.horizontal, 28)
            .padding(.vertical, 24)
            .frame(maxWidth: 760, alignment: .topLeading)
        }
        .groupBoxStyle(MonitorPanelGroupBoxStyle())
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .task {
            await model.refreshServiceStatuses()
        }
    }

    private var connectionMessage: String {
        if isPoweredOff {
            return "Eve is intentionally off. Power her on to bring the monitor, model lanes, and control services back."
        }
        if model.serviceOnlineCount > 0 {
            return "Part of Eve is online, but the monitor API is not answering yet."
        }
        return "Eve Monitor is waiting for the local runtime to come online."
    }

    private var connectionRows: [MonitorServiceRow] {
        let preferred = ["monitor-api", "daemon", "eve-control", "openclaw"]
        let rows = model.serviceRows
        let priorityRows = preferred.compactMap { id in rows.first(where: { $0.id == id }) }
        if !priorityRows.isEmpty { return priorityRows }
        return Array(rows.prefix(4))
    }
}

private struct ConnectionStatusMark: View {
    let state: MonitorServiceState
    let isPoweredOff: Bool

    var body: some View {
        ZStack {
            Circle()
                .fill(tint.opacity(0.14))
            Image(systemName: isPoweredOff ? "power" : connectionServiceSymbol(state))
                .font(.system(size: 25, weight: .semibold))
                .foregroundStyle(tint)
        }
        .frame(width: 54, height: 54)
    }

    private var tint: Color {
        if isPoweredOff { return .secondary }
        return connectionServiceColor(state)
    }
}

private struct ConnectionSummaryPill: View {
    let value: String
    let label: String
    let state: MonitorServiceState

    var body: some View {
        HStack(spacing: 5) {
            Text(value)
                .font(.caption.monospacedDigit().weight(.semibold))
            Text(label)
                .font(.caption.weight(.medium))
        }
        .foregroundStyle(connectionServiceColor(state))
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(connectionServiceColor(state).opacity(0.10), in: Capsule())
    }
}

private struct ConnectionServiceRow: View {
    let row: MonitorServiceRow

    var body: some View {
        HStack(alignment: .center, spacing: 11) {
            ZStack {
                Circle()
                    .fill(connectionServiceColor(row.state).opacity(0.11))
                Image(systemName: row.systemImage)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(connectionServiceColor(row.state))
            }
            .frame(width: 26, height: 26)

            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(row.title)
                        .font(.callout.weight(.semibold))
                    Text(connectionServiceLabel(row.state))
                        .font(.caption2.weight(.semibold))
                        .foregroundStyle(connectionServiceColor(row.state))
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(connectionServiceColor(row.state).opacity(0.10), in: Capsule())
                }

                Text(row.detail.monitorReadable.monitorLimited(to: 180))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 12)

            Text(row.metadata.monitorReadable.monitorLimited(to: 28))
                .font(.caption.monospacedDigit().weight(.medium))
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .padding(.vertical, 9)
    }
}

private func connectionServiceColor(_ state: MonitorServiceState) -> Color {
    switch state {
    case .online:
        return MonitorTheme.accent
    case .warning:
        return MonitorTheme.amber
    case .offline:
        return MonitorTheme.red
    case .unknown:
        return .secondary
    }
}

private func connectionServiceLabel(_ state: MonitorServiceState) -> String {
    switch state {
    case .online:
        return "Online"
    case .warning:
        return "Partial"
    case .offline:
        return "Offline"
    case .unknown:
        return "Checking"
    }
}

private func connectionServiceSymbol(_ state: MonitorServiceState) -> String {
    switch state {
    case .online:
        return "checkmark.circle.fill"
    case .warning:
        return "exclamationmark.triangle.fill"
    case .offline:
        return "xmark.circle.fill"
    case .unknown:
        return "waveform.path.ecg"
    }
}
