import Charts
import SwiftUI

struct EveMonitorRootView: View {
    @EnvironmentObject private var model: EveMonitorModel
    @SceneStorage("eve.monitor.selectedSection") private var selectedSectionRaw = MonitorSection.overview.rawValue

    private var selectedSection: MonitorSection {
        MonitorSection(rawValue: selectedSectionRaw) ?? .overview
    }

    private var selection: Binding<String?> {
        Binding(
            get: { selectedSection.rawValue },
            set: { selectedSectionRaw = $0 ?? MonitorSection.overview.rawValue }
        )
    }

    var body: some View {
        NavigationSplitView {
            EveMonitorSidebar(selection: selection)
                .navigationTitle("Eve Monitor")
                .navigationSplitViewColumnWidth(min: 210, ideal: 240, max: 280)
        } detail: {
            Group {
                if selectedSection == .services {
                    MonitorDetailView(section: selectedSection)
                } else if model.payload == nil && !model.isConnected {
                    MonitorConnectionView(
                        title: model.statusTitle,
                        detail: model.statusDetail,
                        isPoweredOff: model.isPoweredOff,
                        isPowerChanging: model.isPowerChanging,
                        openServices: { selectedSectionRaw = MonitorSection.services.rawValue },
                        powerOn: { Task { await model.powerOn() } },
                        reconnect: { Task { await model.reconnect(forceRestart: true) } }
                    )
                } else {
                    MonitorDetailView(section: selectedSection)
                }
            }
            .navigationTitle(selectedSection.title)
            .toolbar {
                MonitorToolbar(
                    state: MonitorToolbarState(model: model, selectedSection: selectedSection),
                    togglePower: { Task { await model.togglePower() } },
                    togglePaused: { model.togglePaused() },
                    refresh: {
                        if selectedSection == .services {
                            Task { await model.refreshServiceStatuses() }
                        } else {
                            Task { await model.refreshNow() }
                        }
                    },
                    reconnect: { Task { await model.reconnect(forceRestart: true) } },
                    openWebMonitor: { model.openWebMonitor() }
                )
            }
        }
        .task {
            model.setActiveSection(selectedSection.rawValue)
            await model.start()
        }
        .onChange(of: selectedSectionRaw) { _, newValue in
            model.setActiveSection(MonitorSection(rawValue: newValue)?.rawValue ?? MonitorSection.overview.rawValue)
        }
    }
}

private struct MonitorDetailView: View {
    let section: MonitorSection

    var body: some View {
        Group {
            if section == .chat {
                ChatDetailView()
            } else {
                ScrollViewReader { scrollProxy in
                    ScrollView {
                        Color.clear
                            .frame(height: 0)
                            .id("detail-top")

                        VStack(alignment: .leading, spacing: 18) {
                            switch section {
                            case .overview:
                                OverviewView()
                            case .services:
                                ServicesDetailView()
                            case .chat:
                                EmptyView()
                            case .fromEve:
                                FromEveDetailView()
                            case .activity:
                                ActivityDetailView()
                            case .fitness:
                                FitnessDetailView()
                            case .homeostasis:
                                HomeostasisDetailView()
                            case .records:
                                RecordsDetailView()
                            }
                        }
                        .padding(.horizontal, 28)
                        .padding(.vertical, 24)
                        .frame(maxWidth: detailWidth, alignment: .topLeading)
                    }
                    .onAppear {
                        scrollProxy.scrollTo("detail-top", anchor: .top)
                    }
                }
                .id(section)
                .groupBoxStyle(MonitorPanelGroupBoxStyle())
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            }
        }
    }

    private var detailWidth: CGFloat {
        switch section {
        case .overview, .services:
            return 1040
        case .fromEve, .chat:
            return 1120
        case .activity, .fitness, .homeostasis:
            return 1000
        case .records:
            return 980
        }
    }
}

private struct OverviewView: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var overviewColumns: [GridItem] {
        [
            GridItem(.flexible(minimum: 280), spacing: 16, alignment: .top),
            GridItem(.flexible(minimum: 320), spacing: 16, alignment: .top)
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            OverviewNowPanel()

            ActivityFlowMap(compact: true)

            OverviewFocusPanel()

            LazyVGrid(columns: overviewColumns, alignment: .leading, spacing: 16) {
                OverviewPressurePanel()
                OverviewAttentionPanel()
                OverviewHumanContextSignalPanel()
                OverviewGovernancePanel()
                OverviewFitnessPanel()
                OverviewSystemsPanel()
                OverviewActivityPanel()
            }
        }
    }
}

private struct ServicesDetailView: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var coreRows: [MonitorServiceRow] {
        model.serviceRows.filter { $0.group == "Core" }
    }

    private var laneRows: [MonitorServiceRow] {
        model.serviceRows.filter { $0.group == "Model Lanes" }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            ServicesHeader()

            ServiceGroupPanel(
                title: "Core",
                subtitle: "The local surfaces that make Eve controllable.",
                rows: coreRows
            )

            ServiceGroupPanel(
                title: "Model Lanes",
                subtitle: "The five local llama.cpp servers Eve uses for language, reflection, planning, observation, and relationship.",
                rows: laneRows
            )
        }
        .task {
            await model.refreshServiceStatuses()
        }
    }
}

private struct ServicesHeader: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            ServiceStatusMark(state: model.serviceSummaryState, size: 44, symbolSize: 20)

            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text(model.serviceSummaryTitle)
                        .font(.title.weight(.semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.78)

                    Text(model.serviceLastUpdated)
                        .font(.caption.monospacedDigit().weight(.medium))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 9)
                        .padding(.vertical, 5)
                        .background(.quaternary, in: Capsule())
                }

                Text(model.serviceSummaryDetail)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.primary)

                Text(model.payload?.state?.serviceHealthSummary?.monitorReadable.monitorLimited(to: 220) ?? "Direct local probes check the monitor API, Eve Control, OpenClaw, and the active model substrates backing all five logical lanes.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Spacer(minLength: 0)

            VStack(alignment: .trailing, spacing: 10) {
                HStack(spacing: 7) {
                    ServiceSummaryPill(value: "\(model.serviceOnlineCount)", label: "Online", state: .online)
                    ServiceSummaryPill(value: "\(model.serviceOfflineCount)", label: "Offline", state: .offline)
                }

                Button {
                    Task { await model.refreshServiceStatuses() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .font(.system(size: 15, weight: .semibold))
                }
                .buttonStyle(.borderless)
                .help("Refresh services")
            }
        }
        .padding(16)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: MonitorTheme.panelRadius, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: MonitorTheme.panelRadius, style: .continuous)
                .strokeBorder(MonitorTheme.divider)
        }
    }
}

private struct ServiceSummaryPill: View {
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
        .foregroundStyle(serviceStateColor(state))
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(serviceStateColor(state).opacity(0.10), in: Capsule())
    }
}

private struct ServiceGroupPanel: View {
    let title: String
    let subtitle: String
    let rows: [MonitorServiceRow]

    var body: some View {
        GroupBox(title) {
            VStack(alignment: .leading, spacing: 12) {
                Text(subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                VStack(spacing: 0) {
                    ForEach(Array(rows.enumerated()), id: \.offset) { index, row in
                        if index > 0 { Divider() }
                        ServiceStatusRow(row: row)
                    }
                }
            }
            .padding(.vertical, 2)
        }
    }
}

private struct ServiceStatusRow: View {
    let row: MonitorServiceRow

    var body: some View {
        HStack(alignment: .center, spacing: 11) {
            ServiceStatusMark(state: row.state, size: 26, symbolSize: 12)

            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(row.title)
                        .font(.callout.weight(.semibold))
                    ServiceStateBadge(state: row.state)
                }

                Text(row.detail.monitorReadable.monitorLimited(to: 170))
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

private struct ServiceStatusMark: View {
    let state: MonitorServiceState
    let size: CGFloat
    let symbolSize: CGFloat

    var body: some View {
        ZStack {
            Circle()
                .fill(serviceStateColor(state).opacity(0.11))
            Image(systemName: serviceStateSymbol(state))
                .font(.system(size: symbolSize, weight: .semibold))
                .foregroundStyle(serviceStateColor(state))
        }
        .frame(width: size, height: size)
    }
}

private struct ServiceStateBadge: View {
    let state: MonitorServiceState

    var body: some View {
        Text(serviceStateLabel(state))
            .font(.caption2.weight(.semibold))
            .foregroundStyle(serviceStateColor(state))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(serviceStateColor(state).opacity(0.10), in: Capsule())
    }
}

private struct OverviewNowPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var stateTint: Color {
        if model.isPoweredOff { return .secondary }
        return model.payload?.status?.daemon?.awake == true ? MonitorTheme.accent : MonitorTheme.amber
    }

    private var stateImage: String {
        model.payload?.status?.daemon?.awake == true ? "power.circle.fill" : "power.circle"
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack(alignment: .top, spacing: 18) {
                OverviewStateMark(systemImage: stateImage, tint: stateTint)

                VStack(alignment: .leading, spacing: 9) {
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        Text(model.daemonTitle)
                            .font(.largeTitle.weight(.semibold))
                            .lineLimit(1)
                            .minimumScaleFactor(0.8)

                        OverviewLiveBadge()
                    }

                    Text(activityStateSentence(model: model))
                        .font(.headline)
                        .foregroundStyle(.primary)
                        .fixedSize(horizontal: false, vertical: true)

                    Text("Focus: \(model.workspaceFocus.monitorReadable.monitorLimited(to: 220))")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: 20)

                OverviewConstraintLockup()
            }

            Divider()

            OverviewHeroStats()
        }
        .padding(18)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: MonitorTheme.panelRadius, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: MonitorTheme.panelRadius, style: .continuous)
                .strokeBorder(MonitorTheme.divider)
        }
    }
}

private struct OverviewStateMark: View {
    let systemImage: String
    let tint: Color

    var body: some View {
        ZStack {
            Circle()
                .stroke(tint.opacity(0.18), lineWidth: 10)
                .frame(width: 62, height: 62)
            Circle()
                .fill(tint.opacity(0.12))
                .frame(width: 48, height: 48)
            Image(systemName: systemImage)
                .font(.system(size: 28, weight: .regular))
                .foregroundStyle(tint)
        }
        .frame(width: 66, height: 66)
    }
}

private struct OverviewConstraintLockup: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        VStack(alignment: .trailing, spacing: 8) {
            Label(overviewConstraintDetail(model), systemImage: overviewConstraintImage(model))
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
                .labelStyle(.titleAndIcon)
                .lineLimit(1)

            Text(overviewConstraintValue(model))
                .font(.caption.weight(.semibold))
                .foregroundStyle(overviewConstraintColor(model))
                .lineLimit(1)
                .padding(.horizontal, 10)
                .padding(.vertical, 5)
                .background(overviewConstraintColor(model).opacity(0.12), in: Capsule())
        }
        .frame(minWidth: 132, alignment: .trailing)
        .padding(.top, 4)
    }
}

private struct OverviewHeroStats: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        HStack(spacing: 0) {
            OverviewHeroStat(
                title: "State",
                value: model.daemonTitle,
                detail: model.payload?.status?.daemon?.awake == true ? "daemon awake" : model.statusDetail,
                systemImage: "power.circle",
                tint: model.payload?.status?.daemon?.awake == true ? MonitorTheme.accent : MonitorTheme.amber
            )
            HeroStatDivider()
            OverviewHeroStat(
                title: "Work",
                value: overviewWorkValue(model),
                detail: overviewWorkDetail(model),
                systemImage: model.activeModelCalls.isEmpty ? "ellipsis.message" : "bolt.horizontal.circle",
                tint: model.activeModelCalls.isEmpty ? .secondary : MonitorTheme.amber
            )
            HeroStatDivider()
            OverviewHeroStat(
                title: "Pressure",
                value: "\(model.peakPressure?.level ?? 0)",
                detail: model.peakPressure.map { pressureLabel($0) } ?? "none",
                systemImage: "waveform.path.ecg",
                tint: pressureSeverityColor(model.peakPressure?.level ?? 0)
            )
            HeroStatDivider()
            OverviewHeroStat(
                title: "Attention",
                value: "\(model.payload?.status?.counts?.unreadMessages ?? 0)",
                detail: "\(model.payload?.status?.counts?.waitingThreads ?? 0) waiting",
                systemImage: "text.bubble",
                tint: MonitorTheme.teal
            )
        }
    }
}

private struct HeroStatDivider: View {
    var body: some View {
        Divider()
            .frame(height: 54)
            .padding(.horizontal, 12)
    }
}

private struct OverviewHeroStat: View {
    let title: String
    let value: String
    let detail: String
    let systemImage: String
    let tint: Color

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(value.isEmpty ? "Unknown" : value)
                    .font(.title3.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                Text((detail.isEmpty ? "No detail" : detail).monitorReadable.monitorLimited(to: 56))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        } icon: {
            Image(systemName: systemImage)
                .foregroundStyle(tint)
                .frame(width: 18)
        }
        .labelStyle(.titleAndIcon)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct OverviewStoryHeader: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var mode: String {
        model.payload?.homeostasis?.regulationMode?.capitalized ?? "Monitor"
    }

    private var topPressureText: String {
        guard let pressure = model.peakPressure else { return "no dominant pressure" }
        return "\(pressureLabel(pressure)) \(pressureLevel(pressure))"
    }

    private var story: String {
        activityStateSentence(model: model)
    }

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            Image(systemName: model.payload?.status?.daemon?.awake == true ? "power.circle.fill" : "power.circle")
                .font(.system(size: 32, weight: .regular))
                .foregroundStyle(model.payload?.status?.daemon?.awake == true ? MonitorTheme.accent : MonitorTheme.amber)
                .frame(width: 42)

            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text(model.daemonTitle)
                        .font(.largeTitle.weight(.semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)

                    OverviewLiveBadge()
                }

                Text(story)
                    .font(.headline)
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)

                Text("Focus: \(model.workspaceFocus.monitorReadable.monitorLimited(to: 190))")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

private struct OverviewLiveBadge: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        HStack(spacing: 6) {
            Circle()
                .fill(model.isPaused ? MonitorTheme.amber : MonitorTheme.accent)
                .frame(width: 7, height: 7)
            Text(model.isPaused ? "Paused" : monitorUpdateModeLabel(model.updateMode))
            Text(model.generatedAt)
                .foregroundStyle(.tertiary)
        }
        .font(.caption.weight(.medium))
        .foregroundStyle(.secondary)
        .padding(.horizontal, 9)
        .padding(.vertical, 5)
        .background(.quaternary, in: Capsule())
    }
}

private struct OverviewVitalsStrip: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var columns: [GridItem] {
        [GridItem(.adaptive(minimum: 132), spacing: 10, alignment: .top)]
    }

    var body: some View {
        LazyVGrid(columns: columns, alignment: .leading, spacing: 10) {
            OverviewVital(
                title: "State",
                value: model.daemonTitle,
                detail: model.payload?.status?.daemon?.awake == true ? "daemon awake" : model.statusDetail,
                systemImage: "power.circle",
                tint: model.payload?.status?.daemon?.awake == true ? MonitorTheme.accent : MonitorTheme.amber
            )
            OverviewVital(
                title: "Work",
                value: overviewWorkValue(model),
                detail: overviewWorkDetail(model),
                systemImage: model.activeModelCalls.isEmpty ? "ellipsis.message" : "bolt.horizontal.circle",
                tint: model.activeModelCalls.isEmpty ? .secondary : MonitorTheme.amber
            )
            OverviewVital(
                title: "Pressure",
                value: "\(model.peakPressure?.level ?? 0)",
                detail: model.peakPressure.map { pressureLabel($0) } ?? "none",
                systemImage: "waveform.path.ecg",
                tint: pressureSeverityColor(model.peakPressure?.level ?? 0)
            )
            OverviewVital(
                title: "Constraint",
                value: overviewConstraintValue(model),
                detail: overviewConstraintDetail(model),
                systemImage: overviewConstraintImage(model),
                tint: overviewConstraintColor(model)
            )
        }
    }
}

private struct OverviewVital: View {
    let title: String
    let value: String
    let detail: String
    let systemImage: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            HStack(spacing: 7) {
                Image(systemName: systemImage)
                    .foregroundStyle(tint)
                    .frame(width: 18)
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
            }

            Text(value.isEmpty ? "Unknown" : value)
                .font(.title3.weight(.semibold))
                .lineLimit(1)
                .minimumScaleFactor(0.72)

            Text((detail.isEmpty ? "No detail" : detail).monitorReadable.monitorLimited(to: 52))
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .padding(11)
        .frame(maxWidth: .infinity, minHeight: 96, alignment: .topLeading)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct OverviewFocusPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        GroupBox("Current Work") {
            VStack(alignment: .leading, spacing: 13) {
                HStack(alignment: .firstTextBaseline) {
                    Text(model.workspaceFocus.monitorReadable.monitorLimited(to: 120))
                        .font(.title3.weight(.semibold))
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                    Spacer()
                    Text(MonitorFormatters.clock(model.payload?.workspace?.updatedAt))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }

                Text((model.payload?.homeostasis?.summary ?? model.currentExperience).monitorReadable.monitorLimited(to: 280))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Divider()

                LazyVGrid(
                    columns: [GridItem(.adaptive(minimum: 230), spacing: 12, alignment: .top)],
                    alignment: .leading,
                    spacing: 10
                ) {
                    OverviewInlineSignal(
                        title: "Autonomy",
                        value: model.autonomyFocus,
                        systemImage: "point.3.connected.trianglepath.dotted"
                    )
                    OverviewInlineSignal(
                        title: "Readiness",
                        value: model.payload?.workspace?.actionReadiness?.first ?? "No readiness signal",
                        systemImage: "checkmark.circle"
                    )
                    OverviewInlineSignal(
                        title: "Next",
                        value: model.payload?.homeostasis?.nextRegulationStep ?? model.payload?.workspace?.nextRefresh ?? "No next step",
                        systemImage: "arrow.forward.circle"
                    )
                }
            }
            .padding(.vertical, 2)
        }
    }
}

private struct OverviewInlineSignal: View {
    let title: String
    let value: String
    let systemImage: String

    var body: some View {
        HStack(alignment: .top, spacing: 9) {
            Image(systemName: systemImage)
                .foregroundStyle(MonitorTheme.accent)
                .frame(width: 18)

            VStack(alignment: .leading, spacing: 3) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(value.monitorReadable.monitorLimited(to: 92))
                    .font(.callout)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

private struct OverviewPressurePanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var pressures: [MonitorPressure] {
        (model.payload?.homeostasis?.pressures ?? []).sorted { pressureLevel($0) > pressureLevel($1) }
    }

    var body: some View {
        GroupBox("Homeostasis") {
            VStack(alignment: .leading, spacing: 14) {
                if let top = pressures.first {
                    let level = pressureLevel(top)
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(pressureLabel(top))
                                .font(.title2.weight(.semibold))
                                .lineLimit(1)
                            Text(top.reason?.monitorReadable.monitorLimited(to: 110) ?? "No pressure reason")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .lineLimit(2)
                        }
                        Spacer()
                        Text("\(level)")
                            .font(.system(size: 38, weight: .semibold, design: .rounded).monospacedDigit())
                            .foregroundStyle(pressureSeverityColor(level))
                    }

                    PressureGaugeBar(level: level)

                    OverviewPressureSparkline(samples: model.pressureHistory(for: top), tint: pressureSeverityColor(level))

                    Divider()

                    ForEach(Array(pressures.prefix(4).enumerated()), id: \.offset) { index, pressure in
                        if index > 0 { Divider() }
                        OverviewPressureLine(pressure: pressure)
                    }
                } else {
                    Text("No pressure data yet.")
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .padding(.vertical, 2)
        }
    }
}

private struct OverviewPressureSparkline: View {
    let samples: [MonitorPressureSample]
    let tint: Color

    var body: some View {
        if samples.count >= 2 {
            Chart(samples) { sample in
                LineMark(
                    x: .value("Time", sample.timestamp),
                    y: .value("Level", sample.level)
                )
                .interpolationMethod(.catmullRom)
                .foregroundStyle(tint)
            }
            .chartYScale(domain: 0...100)
            .chartXAxis(.hidden)
            .chartYAxis(.hidden)
            .frame(height: 66)
        }
    }
}

private struct OverviewPressureLine: View {
    let pressure: MonitorPressure

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 9) {
            SeverityDot(level: pressureLevel(pressure))
            Text(pressureLabel(pressure))
                .font(.callout.weight(.medium))
                .lineLimit(1)
            Text(pressure.trend ?? "steady")
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
            Spacer()
            Text("\(pressureLevel(pressure))")
                .font(.callout.monospacedDigit().weight(.semibold))
                .foregroundStyle(pressureSeverityColor(pressureLevel(pressure)))
        }
        .padding(.vertical, 6)
    }
}

private struct OverviewAttentionPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        GroupBox("Attention") {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 18) {
                    OverviewNumberLockup(
                        value: "\(model.payload?.status?.counts?.waitingThreads ?? 0)",
                        label: "waiting",
                        tint: MonitorTheme.teal
                    )
                    OverviewNumberLockup(
                        value: "\(model.payload?.status?.counts?.unreadMessages ?? 0)",
                        label: "unread",
                        tint: MonitorTheme.amber
                    )
                    OverviewNumberLockup(
                        value: "\(model.payload?.status?.counts?.activeThreads ?? 0)",
                        label: "active",
                        tint: MonitorTheme.blue
                    )
                }

                Divider()

                OverviewStatusLine(
                    title: model.activeReplyTitle.capitalized,
                    detail: model.activeReplyDetail,
                    metadata: model.payload?.status?.activeReply?.updatedAt.map { MonitorFormatters.clock($0) } ?? "reply",
                    systemImage: "ellipsis.message",
                    tint: model.payload?.status?.activeReply?.id == nil ? .secondary : MonitorTheme.amber
                )

                if let thread = model.payload?.status?.threadAttention?.first {
                    Divider()
                    OverviewStatusLine(
                        title: thread.subject ?? "Thread needs attention",
                        detail: thread.latestPreview ?? "No thread preview",
                        metadata: thread.status ?? "thread",
                        systemImage: "text.bubble",
                        tint: MonitorTheme.teal
                    )
                }
            }
            .padding(.vertical, 2)
        }
    }
}

private struct OverviewNumberLockup: View {
    let value: String
    let label: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value)
                .font(.title.weight(.semibold).monospacedDigit())
                .foregroundStyle(tint)
                .lineLimit(1)
                .minimumScaleFactor(0.7)
            Text(label)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct OverviewSystemsPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        GroupBox("Systems") {
            VStack(alignment: .leading, spacing: 12) {
                OverviewStatusLine(
                    title: model.lanesReady,
                    detail: model.payload?.status?.modelHealth?.summary ?? "No lane summary",
                    metadata: MonitorFormatters.clock(model.payload?.status?.modelHealth?.updatedAt),
                    systemImage: "cpu",
                    tint: MonitorTheme.blue
                )

                Divider()

                ForEach(Array(model.normalizedLanes.prefix(4).enumerated()), id: \.offset) { index, lane in
                    if index > 0 { Divider() }
                    HStack(alignment: .firstTextBaseline, spacing: 10) {
                        Circle()
                            .fill(lane.loaded == true ? MonitorTheme.accent : MonitorTheme.amber)
                            .frame(width: 8, height: 8)
                        Text(lane.label ?? lane.lane ?? "Lane")
                            .font(.callout.weight(.medium))
                            .lineLimit(1)
                        Spacer()
                        Text(MonitorFormatters.latency(lane.latencyMs))
                            .font(.callout.monospacedDigit())
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 5)
                }
            }
            .padding(.vertical, 2)
        }
    }
}

private struct OverviewActivityPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        GroupBox("Recent Activity") {
            VStack(spacing: 0) {
                if let action = model.payload?.operations?.actions?.first {
                    OverviewStatusLine(
                        title: action.action ?? "Action",
                        detail: action.summary ?? "No action summary",
                        metadata: MonitorFormatters.clock(action.updatedAt ?? action.createdAt),
                        systemImage: action.verificationOk == true || action.resultOk == true ? "checkmark.circle" : "clock",
                        tint: action.verificationOk == true || action.resultOk == true ? MonitorTheme.accent : MonitorTheme.amber
                    )
                }

                if let evidence = model.payload?.substrate?.evidence?.first {
                    Divider()
                    OverviewStatusLine(
                        title: evidence.claim ?? evidence.summary ?? "Evidence",
                        detail: evidence.summary ?? "No evidence summary",
                        metadata: evidence.actionability ?? evidence.status ?? "evidence",
                        systemImage: "tray.full",
                        tint: MonitorTheme.blue
                    )
                }

                if let thread = model.payload?.status?.threadAttention?.first {
                    Divider()
                    OverviewStatusLine(
                        title: thread.subject ?? "Thread",
                        detail: thread.latestPreview ?? "No preview",
                        metadata: thread.status ?? "open",
                        systemImage: "text.bubble",
                        tint: MonitorTheme.teal
                    )
                }
            }
            .padding(.vertical, 2)
        }
    }
}

private struct OverviewHumanContextSignalPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var signals: MonitorHumanContextSignals? {
        model.humanContextSignals
    }

    var body: some View {
        GroupBox("Trust & Repair") {
            VStack(spacing: 0) {
                OverviewStatusLine(
                    title: "Trust",
                    detail: firstSignal(signals?.trust, fallback: "No trust signal recorded yet."),
                    metadata: MonitorFormatters.clock(signals?.updatedAt),
                    systemImage: "checkmark.shield",
                    tint: MonitorTheme.accent
                )

                Divider()

                OverviewStatusLine(
                    title: "Repair",
                    detail: firstSignal(signals?.repair, fallback: "No repair practice recorded yet."),
                    metadata: "memory v2",
                    systemImage: "arrow.triangle.2.circlepath",
                    tint: MonitorTheme.teal
                )

                Divider()

                OverviewStatusLine(
                    title: "Truth Boundary",
                    detail: firstSignal(signals?.antiSycophancy, fallback: "No truth boundary recorded yet."),
                    metadata: signalCountLabel,
                    systemImage: "exclamationmark.bubble",
                    tint: MonitorTheme.amber
                )
            }
            .padding(.vertical, 2)
        }
    }

    private var signalCountLabel: String {
        let count = (signals?.trust?.count ?? 0)
            + (signals?.repair?.count ?? 0)
            + (signals?.antiSycophancy?.count ?? 0)
            + (signals?.episodicMarkers?.count ?? 0)
        return count > 0 ? "\(count) signals" : "quiet"
    }

    private func firstSignal(_ values: [String]?, fallback: String) -> String {
        guard let signal = values?.first?.monitorReadable.monitorLimited(to: 150), !signal.isEmpty else {
            return fallback
        }
        return signal
    }
}

private struct OverviewGovernancePanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var governance: MonitorGovernance? {
        model.payload?.governance
    }

    private var watcherStatus: String {
        governance?.watcherStatus?.monitorReadable.capitalized ?? "Unknown"
    }

    private var warningCount: Int {
        governance?.watcherWarningCount ?? 0
    }

    private var blockingCount: Int {
        governance?.blockingWarningCount ?? 0
    }

    private var proposalCount: Int {
        governance?.proposalCount ?? 0
    }

    private var tint: Color {
        switch governance?.watcherStatus?.lowercased() {
        case "blocking":
            return MonitorTheme.red
        case "review":
            return MonitorTheme.amber
        case "watch":
            return MonitorTheme.blue
        case "clean":
            return MonitorTheme.accent
        default:
            return MonitorTheme.secondaryText
        }
    }

    private var decisionSummary: String {
        let decisions = governance?.decisionCounts ?? [:]
        guard !decisions.isEmpty else { return "No reviewed governance proposals are queued." }
        return decisions
            .sorted { $0.key < $1.key }
            .map { "\($0.key): \($0.value)" }
            .joined(separator: ", ")
            .monitorLimited(to: 150)
    }

    private var watcherSummary: String {
        guard let watchers = governance?.watchers, !watchers.isEmpty else {
            return "No watcher report available yet."
        }
        let active = watchers
            .filter { ($0.warningCount ?? 0) > 0 }
            .sorted { ($0.maxSeverity ?? 0) > ($1.maxSeverity ?? 0) }
        if let top = active.first {
            return "\(top.title ?? top.id): \(top.warningCount ?? 0) warning(s)."
        }
        return "Tool, memory, capability, identity, and data watchers are clean."
    }

    private var lifecycleSummary: String {
        let approvals = governance?.approvalCounts ?? [:]
        let canaries = governance?.canaryCounts ?? [:]
        let applications = governance?.applicationCounts ?? [:]
        let approved = approvals["approved"] ?? 0
        let rejected = approvals["rejected"] ?? 0
        let passed = canaries["passed"] ?? 0
        let applied = applications["applied"] ?? 0
        let rolledBack = applications["rolled_back"] ?? 0
        if approvals.isEmpty && canaries.isEmpty && applications.isEmpty {
            return "No proposal lifecycle records yet."
        }
        return "approved \(approved), rejected \(rejected), canary passed \(passed), applied \(applied), rolled back \(rolledBack)"
            .monitorLimited(to: 150)
    }

    var body: some View {
        GroupBox("Governance") {
            VStack(spacing: 0) {
                OverviewStatusLine(
                    title: "\(watcherStatus) watchers",
                    detail: watcherSummary,
                    metadata: "\(warningCount) warnings",
                    systemImage: blockingCount > 0 ? "exclamationmark.shield" : "checkmark.shield",
                    tint: tint
                )

                Divider()

                OverviewStatusLine(
                    title: "\(proposalCount) queued proposals",
                    detail: decisionSummary,
                    metadata: "CIK",
                    systemImage: "list.bullet.rectangle",
                    tint: MonitorTheme.teal
                )

                Divider()

                OverviewStatusLine(
                    title: "Lifecycle",
                    detail: lifecycleSummary,
                    metadata: "staged",
                    systemImage: "checklist",
                    tint: MonitorTheme.blue
                )

                Divider()

                OverviewStatusLine(
                    title: "\(blockingCount) blocking",
                    detail: blockingCount > 0 ? "Blocking governance warnings need review before live state changes." : "No blocking governance warnings.",
                    metadata: MonitorFormatters.clock(governance?.generatedAt),
                    systemImage: "lock.shield",
                    tint: blockingCount > 0 ? MonitorTheme.red : MonitorTheme.accent
                )
            }
            .padding(.vertical, 2)
        }
    }
}

private struct OverviewFitnessPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var fitness: MonitorFitness? {
        model.payload?.fitness
    }

    private var whole: MonitorWholeSystemFitness? {
        fitness?.wholeSystem
    }

    private var longRun: MonitorLongRunFitness? {
        fitness?.longRun
    }

    private var manual: MonitorManualProbeFitness? {
        fitness?.manualProbe
    }

    private var roadmap: MonitorRoadmapFitness? {
        fitness?.roadmap
    }

    private var wholeStatus: String {
        whole?.status?.monitorReadable.capitalized ?? "Unknown"
    }

    private var tint: Color {
        if whole?.passed == true && longRun?.passed == true && manual?.passed == true {
            return MonitorTheme.accent
        }
        if (whole?.failingCheckCount ?? 0) > 0 || (manual?.blockerCount ?? 0) > 0 {
            return MonitorTheme.red
        }
        return MonitorTheme.amber
    }

    var body: some View {
        GroupBox("Fitness") {
            VStack(spacing: 0) {
                OverviewStatusLine(
                    title: "\(wholeStatus) whole-system",
                    detail: "\(whole?.checkCount ?? 0) checks, \(whole?.failingCheckCount ?? 0) failing.",
                    metadata: fitnessScore(whole?.averageScore),
                    systemImage: whole?.passed == true ? "checkmark.seal" : "exclamationmark.triangle",
                    tint: tint
                )

                Divider()

                OverviewStatusLine(
                    title: longRun?.rank?.label?.monitorReadable.replacingOccurrences(of: "_", with: " ").capitalized ?? "Long-run unknown",
                    detail: "\(longRun?.runCount ?? 0) run(s), \(longRun?.actionTotal ?? 0) action(s), failure rate \(fitnessRatio(longRun?.failureRate)).",
                    metadata: fitnessScore(longRun?.rank?.averageScore),
                    systemImage: "point.3.connected.trianglepath.dotted",
                    tint: longRun?.passed == true ? MonitorTheme.accent : MonitorTheme.amber
                )

                Divider()

                OverviewStatusLine(
                    title: manual?.rank?.label?.monitorReadable.replacingOccurrences(of: "_", with: " ").capitalized ?? "Manual probes unknown",
                    detail: "\(manual?.probeCount ?? 0) fresh probe(s), \(manual?.blockerCount ?? 0) blocker(s).",
                    metadata: fitnessScore(manual?.rank?.averageScore),
                    systemImage: "person.text.rectangle",
                    tint: manual?.passed == true ? MonitorTheme.accent : MonitorTheme.amber
                )

                Divider()

                OverviewStatusLine(
                    title: roadmap?.status?.monitorReadable.capitalized ?? "Roadmap unknown",
                    detail: roadmap?.firstPriority?.monitorReadable.monitorLimited(to: 150) ?? "No roadmap priority surfaced.",
                    metadata: MonitorFormatters.clock(roadmap?.generatedAt),
                    systemImage: "map",
                    tint: roadmap?.status?.lowercased() == "passed" ? MonitorTheme.accent : MonitorTheme.blue
                )
            }
            .padding(.vertical, 2)
        }
    }
}

private struct OverviewStatusLine: View {
    let title: String
    let detail: String
    let metadata: String
    let systemImage: String
    let tint: Color

    var body: some View {
        HStack(alignment: .top, spacing: 11) {
            Image(systemName: systemImage)
                .font(.system(size: 15, weight: .regular))
                .foregroundStyle(tint)
                .frame(width: 20)

            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(title.monitorReadable.monitorLimited(to: 92))
                        .font(.callout.weight(.medium))
                        .lineLimit(2)
                    Spacer(minLength: 8)
                    Text(metadata.monitorReadable.monitorLimited(to: 24))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                Text(detail.monitorReadable.monitorLimited(to: 150))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 8)
    }
}

private struct WorkspaceDetailView: View {
    var body: some View {
        WorkspaceSummaryGroup(limit: 8)
    }
}

private struct WorkspaceSummaryGroup: View {
    @EnvironmentObject private var model: EveMonitorModel
    let limit: Int

    var body: some View {
        GroupBox("Workspace") {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    Text("Focus")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(MonitorFormatters.clock(model.payload?.workspace?.updatedAt))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }

                Text(model.workspaceSummary.monitorReadable.monitorLimited(to: 240))
                    .font(.headline)
                    .fixedSize(horizontal: false, vertical: true)

                Text(model.currentExperience.monitorReadable.monitorLimited(to: 360))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Divider()

                LazyVGrid(
                    columns: [GridItem(.adaptive(minimum: 250), spacing: 18, alignment: .top)],
                    alignment: .leading,
                    spacing: 16
                ) {
                    SignalSection(title: "Continuity", items: model.payload?.workspace?.continuityThreads ?? [], limit: limit)
                    SignalSection(title: "Readiness", items: model.payload?.workspace?.actionReadiness ?? [], limit: limit)
                    SignalSection(title: "Surprise", items: model.payload?.workspace?.surpriseSignals ?? [], limit: limit)
                    SignalSection(title: "Trace", items: model.payload?.workspace?.consequenceTrace ?? [], limit: limit)
                }
            }
        }
    }
}

private struct StatusSummaryGrid: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var columns: [GridItem] {
        [GridItem(.adaptive(minimum: 170), spacing: 12, alignment: .top)]
    }

    var body: some View {
        LazyVGrid(columns: columns, alignment: .leading, spacing: 12) {
            SummaryTile(
                title: "Daemon",
                value: model.daemonTitle,
                detail: model.daemonDetail,
                systemImage: "power.circle",
                tint: model.payload?.status?.daemon?.awake == true ? MonitorTheme.accent : MonitorTheme.amber
            )
            SummaryTile(
                title: "Lanes",
                value: model.lanesReady,
                detail: model.payload?.status?.modelHealth?.summary ?? "No lane summary",
                systemImage: "cpu",
                tint: MonitorTheme.blue
            )
            SummaryTile(
                title: "Pressure",
                value: "\(model.peakPressure?.level ?? 0)",
                detail: [model.peakPressure?.label, model.peakPressure?.trend].compactMap { $0 }.joined(separator: " / "),
                systemImage: "waveform.path.ecg",
                tint: MonitorTheme.pressureColor(model.peakPressure?.level ?? 0)
            )
            SummaryTile(
                title: "Threads",
                value: "\(model.payload?.status?.counts?.activeThreads ?? 0)",
                detail: "\(model.payload?.status?.counts?.unreadMessages ?? 0) unread, \(model.payload?.status?.counts?.waitingThreads ?? 0) waiting",
                systemImage: "text.bubble",
                tint: MonitorTheme.teal
            )
            SummaryTile(
                title: "Reply",
                value: model.activeReplyTitle.capitalized,
                detail: model.activeReplyDetail,
                systemImage: "ellipsis.message",
                tint: model.payload?.status?.activeReply?.id == nil ? .secondary : MonitorTheme.amber
            )
        }
    }
}

private struct SummaryTile: View {
    let title: String
    let value: String
    let detail: String
    let systemImage: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 7) {
                Image(systemName: systemImage)
                    .foregroundStyle(tint)
                    .frame(width: 18)
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer(minLength: 0)
            }

            Text(value.isEmpty ? "Unknown" : value)
                .font(.title2.weight(.semibold))
                .lineLimit(1)
                .minimumScaleFactor(0.75)

            Text((detail.isEmpty ? "No detail" : detail).monitorReadable.monitorLimited(to: 74))
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(12)
        .frame(maxWidth: .infinity, minHeight: 112, alignment: .topLeading)
        .background(.quaternary, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

private struct ModelLanesDetailView: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        NativeHeader(
            title: model.lanesReady,
            subtitle: model.payload?.status?.modelHealth?.summary ?? "No lane summary",
            systemImage: "cpu"
        )

        GroupBox("Model Lanes") {
            VStack(spacing: 0) {
                ForEach(Array(model.normalizedLanes.enumerated()), id: \.offset) { index, lane in
                    if index > 0 { Divider() }
                    LaneNativeRow(lane: lane)
                }
            }
        }
    }
}

private struct LaneNativeRow: View {
    let lane: MonitorLane

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 12) {
            Image(systemName: lane.loaded == true ? "circle.fill" : "exclamationmark.circle")
                .foregroundStyle(lane.loaded == true ? MonitorTheme.accent : MonitorTheme.amber)
                .font(.system(size: 9))

            VStack(alignment: .leading, spacing: 3) {
                Text((lane.label ?? lane.lane ?? "Lane").capitalized)
                    .font(.body.weight(.medium))
                Text([lane.model, lane.backend, lane.host].compactMap { $0?.monitorTrimmed }.filter { !$0.isEmpty }.joined(separator: " - "))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer()

            Text(MonitorFormatters.latency(lane.latencyMs))
                .font(.body.monospacedDigit())
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 9)
    }
}

private struct ActivityDetailView: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var supportColumns: [GridItem] {
        [
            GridItem(.flexible(minimum: 330), spacing: 16, alignment: .top),
            GridItem(.flexible(minimum: 330), spacing: 16, alignment: .top)
        ]
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            ActivityControlBriefPanel()

            ActivityFlowMap(compact: true)

            ModelLaneTimelinePanel()

            LazyVGrid(columns: supportColumns, alignment: .leading, spacing: 16) {
                ActivityResourceStoryPanel()
                ActivityEvidencePanel()
            }

            ActivityDetailDrawersPanel()
        }
    }
}

private struct FitnessDetailView: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var columns: [GridItem] {
        [
            GridItem(.flexible(minimum: 430), spacing: 16, alignment: .top),
            GridItem(.flexible(minimum: 330), spacing: 16, alignment: .top)
        ]
    }

    private var fitness: MonitorFitness? {
        model.payload?.fitness
    }

    private var whole: MonitorWholeSystemFitness? {
        fitness?.wholeSystem
    }

    private var longRun: MonitorLongRunFitness? {
        fitness?.longRun
    }

    private var manualProbe: MonitorManualProbeFitness? {
        fitness?.manualProbe
    }

    private var roadmap: MonitorRoadmapFitness? {
        fitness?.roadmap
    }

    private var headerTitle: String {
        if whole?.passed == true && longRun?.passed == true && manualProbe?.passed == true {
            return "Fitness Is Green"
        }
        if (whole?.failingCheckCount ?? 0) > 0 {
            return "Fitness Needs Review"
        }
        return "Fitness Evidence"
    }

    private var headerSubtitle: String {
        let wholeScore = fitnessScore(whole?.averageScore)
        let longScore = fitnessScore(longRun?.rank?.averageScore)
        let manualScore = fitnessScore(manualProbe?.rank?.averageScore)
        return "Whole-system \(wholeScore), long-run \(longScore), manual probes \(manualScore). This is evidence for operators, not permission to change state."
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            NativeHeader(
                title: headerTitle,
                subtitle: headerSubtitle,
                systemImage: "checkmark.seal.text.page"
            )

            LazyVGrid(columns: columns, alignment: .leading, spacing: 16) {
                FitnessSummaryPanel(whole: whole, longRun: longRun, manualProbe: manualProbe, roadmap: roadmap)
                FitnessRoadmapPanel(roadmap: roadmap)
                FitnessLongRunPanel(longRun: longRun)
                FitnessManualProbePanel(manualProbe: manualProbe)
                FitnessFailingChecksPanel(whole: whole)
                FitnessArtifactPanel(whole: whole, longRun: longRun, manualProbe: manualProbe)
            }
        }
    }
}

private struct FitnessSummaryPanel: View {
    let whole: MonitorWholeSystemFitness?
    let longRun: MonitorLongRunFitness?
    let manualProbe: MonitorManualProbeFitness?
    let roadmap: MonitorRoadmapFitness?

    var body: some View {
        GroupBox("Fitness Summary") {
            VStack(spacing: 0) {
                OverviewStatusLine(
                    title: "\(whole?.status?.monitorReadable.capitalized ?? "Unknown") whole-system",
                    detail: "\(whole?.checkCount ?? 0) check(s), \(whole?.failingCheckCount ?? 0) failing, \(missingComponentCount) missing component(s).",
                    metadata: fitnessScore(whole?.averageScore),
                    systemImage: whole?.passed == true ? "checkmark.seal" : "exclamationmark.triangle",
                    tint: fitnessStatusColor(passed: whole?.passed, warnings: whole?.failingCheckCount)
                )

                Divider()

                OverviewStatusLine(
                    title: longRun?.rank?.label?.monitorReadable.replacingOccurrences(of: "_", with: " ").capitalized ?? "Long-run unknown",
                    detail: "\(longRun?.runCount ?? 0) recent run(s), \(longRun?.actionTotal ?? 0) action(s), \(longRun?.successfulCapabilityCount ?? 0) successful capability tryout(s).",
                    metadata: fitnessScore(longRun?.rank?.averageScore),
                    systemImage: "point.3.connected.trianglepath.dotted",
                    tint: fitnessStatusColor(passed: longRun?.passed, warnings: nil)
                )

                Divider()

                OverviewStatusLine(
                    title: manualProbe?.rank?.label?.monitorReadable.replacingOccurrences(of: "_", with: " ").capitalized ?? "Manual probes unknown",
                    detail: "\(manualProbe?.probeCount ?? 0) black-box probe(s), \(manualProbe?.hiddenProbeCount ?? 0) hidden, \(manualProbe?.blockerCount ?? 0) blocker(s).",
                    metadata: fitnessScore(manualProbe?.rank?.averageScore),
                    systemImage: "person.text.rectangle",
                    tint: fitnessStatusColor(passed: manualProbe?.passed, warnings: manualProbe?.blockerCount)
                )

                Divider()

                OverviewStatusLine(
                    title: roadmap?.status?.monitorReadable.capitalized ?? "Roadmap unknown",
                    detail: roadmap?.firstPriority?.monitorReadable.monitorLimited(to: 160) ?? roadmap?.error?.monitorReadable.monitorLimited(to: 160) ?? "No current roadmap status.",
                    metadata: MonitorFormatters.clock(roadmap?.generatedAt),
                    systemImage: "map",
                    tint: roadmap?.status?.lowercased() == "passed" ? MonitorTheme.accent : MonitorTheme.amber
                )
            }
        }
    }

    private var missingComponentCount: Int {
        (whole?.missingComponentCounts ?? [:]).values.reduce(0, +)
    }
}

private struct FitnessRoadmapPanel: View {
    let roadmap: MonitorRoadmapFitness?

    var body: some View {
        GroupBox("Roadmap Queue") {
            VStack(alignment: .leading, spacing: 12) {
                Text("The current priority order from `eval roadmap`, shown read-only.")
                    .font(.callout)
                    .foregroundStyle(.secondary)

                VStack(spacing: 0) {
                    ForEach(Array((roadmap?.priorityQueue ?? []).enumerated()), id: \.offset) { index, item in
                        if index > 0 { Divider() }
                        NativeRecordRow(
                            title: "\(item.priority ?? "P?") \(item.title ?? "Roadmap item")",
                            subtitle: item.nextAction ?? "No next action recorded.",
                            metadata: item.status ?? "watch",
                            systemImage: item.status?.lowercased() == "active" ? "arrow.right.circle" : "eye"
                        )
                    }
                }

                if roadmap?.priorityQueue?.isEmpty != false {
                    RecordsEmptyState(title: "No roadmap queue", detail: "Run the roadmap evaluator to populate this surface.")
                }
            }
        }
    }
}

private struct FitnessLongRunPanel: View {
    let longRun: MonitorLongRunFitness?

    var body: some View {
        GroupBox("Autonomy Long-Run") {
            VStack(alignment: .leading, spacing: 12) {
                Text("Recent autonomous behavior: diversity, verified outcomes, loop avoidance, resource stability, and carry-forward.")
                    .font(.callout)
                    .foregroundStyle(.secondary)

                VStack(spacing: 0) {
                    ForEach(Array((longRun?.metrics ?? []).enumerated()), id: \.offset) { index, metric in
                        if index > 0 { Divider() }
                        NativeRecordRow(
                            title: metric.name?.monitorReadable.capitalized ?? "Metric",
                            subtitle: metric.issue?.isEmpty == false ? metric.issue! : metric.nextAction ?? "No issue recorded.",
                            metadata: "\(metric.score ?? 0)/5",
                            systemImage: metric.status?.lowercased() == "passed" ? "checkmark.circle" : "exclamationmark.circle"
                        )
                    }
                }
            }
        }
    }
}

private struct FitnessManualProbePanel: View {
    let manualProbe: MonitorManualProbeFitness?

    var body: some View {
        GroupBox("Manual Probe Bank") {
            VStack(spacing: 0) {
                OverviewStatusLine(
                    title: manualProbe?.passed == true ? "Black-box probes passed" : "Probe evidence incomplete",
                    detail: "Fresh human-phrased probes scored outside Eve's internal self-test harness.",
                    metadata: MonitorFormatters.dateTime(manualProbe?.evaluatedAt),
                    systemImage: manualProbe?.passed == true ? "checkmark.bubble" : "questionmark.bubble",
                    tint: manualProbe?.passed == true ? MonitorTheme.accent : MonitorTheme.amber
                )

                Divider()

                RecordsMetricRow(metric: RecordsMetric(title: "Average", value: fitnessScore(manualProbe?.rank?.averageScore), detail: manualProbe?.rank?.label ?? "No rank"))
                Divider()
                RecordsMetricRow(metric: RecordsMetric(title: "Minimum", value: "\(manualProbe?.rank?.minimumScore ?? 0)/5", detail: "Lowest probe score"))
                Divider()
                RecordsMetricRow(metric: RecordsMetric(title: "Blockers", value: "\(manualProbe?.blockerCount ?? 0)", detail: "Open probe blockers"))
            }
        }
    }
}

private struct FitnessFailingChecksPanel: View {
    let whole: MonitorWholeSystemFitness?

    var body: some View {
        GroupBox("Failing Checks") {
            VStack(alignment: .leading, spacing: 12) {
                if let checks = whole?.failingChecks, !checks.isEmpty {
                    VStack(spacing: 0) {
                        ForEach(Array(checks.enumerated()), id: \.offset) { index, check in
                            if index > 0 { Divider() }
                            NativeRecordRow(
                                title: check.title ?? check.testId ?? "Fitness check",
                                subtitle: check.nextAction ?? "No repair action recorded.",
                                metadata: "\(check.status ?? "check") \(fitnessScore(check.score))",
                                systemImage: "exclamationmark.triangle"
                            )
                        }
                    }
                } else {
                    RecordsEmptyState(title: "No failing checks", detail: "Whole-system fitness has no failing checks in the latest artifact.")
                }
            }
        }
    }
}

private struct FitnessArtifactPanel: View {
    let whole: MonitorWholeSystemFitness?
    let longRun: MonitorLongRunFitness?
    let manualProbe: MonitorManualProbeFitness?

    var body: some View {
        GroupBox("Artifacts") {
            VStack(spacing: 0) {
                NativeRecordRow(
                    title: "Whole-system",
                    subtitle: whole?.artifactPath ?? "No artifact path",
                    metadata: MonitorFormatters.dateTime(whole?.finishedAt),
                    systemImage: "doc.text.magnifyingglass"
                )
                Divider()
                NativeRecordRow(
                    title: "Long-run autonomy",
                    subtitle: longRun?.artifactPath ?? "No artifact path",
                    metadata: MonitorFormatters.dateTime(longRun?.evaluatedAt),
                    systemImage: "doc.text.magnifyingglass"
                )
                Divider()
                NativeRecordRow(
                    title: "Manual probes",
                    subtitle: manualProbe?.artifactPath ?? "No artifact path",
                    metadata: MonitorFormatters.dateTime(manualProbe?.evaluatedAt),
                    systemImage: "doc.text.magnifyingglass"
                )
            }
        }
    }
}

private struct ActivityControlBriefPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var activeCount: Int {
        model.activeModelCalls.count
    }

    private var runningLaneCount: Int {
        model.activityLanes.filter { ($0.state ?? "").lowercased() == "generating" }.count
    }

    private var slowestLane: MonitorActivityLane? {
        model.activityLanes.max { laneTimelineValue($0) < laneTimelineValue($1) }
    }

    private var title: String {
        activeCount > 0 ? "\(activeCount) Running" : "Activity"
    }

    private var tint: Color {
        activeCount > 0 ? MonitorTheme.amber : MonitorTheme.accent
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 17) {
            HStack(alignment: .top, spacing: 16) {
                ZStack {
                    Circle()
                        .stroke(tint.opacity(0.18), lineWidth: 8)
                        .frame(width: 58, height: 58)
                    Circle()
                        .fill(tint.opacity(0.12))
                        .frame(width: 44, height: 44)
                    Image(systemName: activeCount > 0 ? "bolt.fill" : "waveform.and.magnifyingglass")
                        .font(.system(size: 25, weight: .regular))
                        .foregroundStyle(tint)
                }
                .frame(width: 60, height: 60)

                VStack(alignment: .leading, spacing: 8) {
                    HStack(alignment: .firstTextBaseline, spacing: 12) {
                        Text(title)
                            .font(.largeTitle.weight(.semibold))
                            .lineLimit(1)
                            .minimumScaleFactor(0.78)

                        OverviewLiveBadge()
                    }

                    Text(activityStateSentence(model: model))
                        .font(.headline)
                        .foregroundStyle(.primary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer(minLength: 16)
            }

            Divider()

            HStack(spacing: 0) {
                ActivityBriefFact(
                    title: "Current",
                    value: activeCount > 0 ? activityOperationFamily(model.activeModelCalls).capitalized : "Standing By",
                    detail: "\(runningLaneCount) active lane\(runningLaneCount == 1 ? "" : "s")",
                    systemImage: activeCount > 0 ? "bolt.horizontal.circle" : "checkmark.circle",
                    tint: activeCount > 0 ? MonitorTheme.amber : MonitorTheme.accent
                )

                HeroStatDivider()

                ActivityBriefFact(
                    title: "Slowest Lane",
                    value: slowestLane?.label ?? slowestLane?.lane ?? "None",
                    detail: slowestLane.map { laneTiming($0) } ?? "no lane timing",
                    systemImage: "speedometer",
                    tint: slowestLane == nil ? .secondary : MonitorTheme.blue
                )

                HeroStatDivider()

                ActivityBriefFact(
                    title: "Resources",
                    value: computeLoadTitle(model.systemActivity),
                    detail: "\(MonitorFormatters.percent(model.systemActivity?.cpuPercent)) CPU, \(diskRiskLabel(model.systemActivity?.disk).lowercased()) disk",
                    systemImage: "memorychip",
                    tint: activityLoadColor(model.systemActivity?.cpuPercent ?? 0)
                )
            }
        }
        .padding(18)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: MonitorTheme.panelRadius, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: MonitorTheme.panelRadius, style: .continuous)
                .strokeBorder(MonitorTheme.divider)
        }
    }
}

private struct ActivityBriefFact: View {
    let title: String
    let value: String
    let detail: String
    let systemImage: String
    let tint: Color

    var body: some View {
        Label {
            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(value.monitorReadable.monitorLimited(to: 48))
                    .font(.title3.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.72)
                Text(detail.monitorReadable.monitorLimited(to: 72))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        } icon: {
            Image(systemName: systemImage)
                .foregroundStyle(tint)
                .frame(width: 18)
        }
        .labelStyle(.titleAndIcon)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct ActivityNarrativeHeader: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var activeCount: Int {
        model.activeModelCalls.count
    }

    private var runningLaneCount: Int {
        model.activityLanes.filter { ($0.state ?? "").lowercased() == "generating" }.count
    }

    private var title: String {
        activeCount > 0 ? "\(activeCount) Running" : "Activity"
    }

    private var story: String {
        activityStateSentence(model: model)
    }

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            ZStack {
                Circle()
                    .fill((activeCount > 0 ? MonitorTheme.amber : MonitorTheme.accent).opacity(0.14))
                    .frame(width: 54, height: 54)
                Image(systemName: activeCount > 0 ? "bolt.fill" : "waveform.and.magnifyingglass")
                    .font(.system(size: 28, weight: .regular))
                    .foregroundStyle(activeCount > 0 ? MonitorTheme.amber : MonitorTheme.accent)
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text(title)
                        .font(.largeTitle.weight(.semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.78)

                    OverviewLiveBadge()
                }

                Text(story)
                    .font(.headline)
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 14) {
                    StoryChip(label: "\(runningLaneCount) lanes", systemImage: "cpu", tint: runningLaneCount > 0 ? MonitorTheme.amber : .secondary)
                    StoryChip(label: MonitorFormatters.percent(model.systemActivity?.cpuPercent), systemImage: "speedometer", tint: activityLoadColor(model.systemActivity?.cpuPercent ?? 0))
                    StoryChip(label: diskRiskLabel(model.systemActivity?.disk), systemImage: "internaldrive", tint: diskRiskColor(model.systemActivity?.disk))
                }
            }
        }
    }
}

struct StoryChip: View {
    let label: String
    let systemImage: String
    let tint: Color

    var body: some View {
        Label(label, systemImage: systemImage)
            .font(.caption.weight(.medium))
            .foregroundStyle(.secondary)
            .labelStyle(.titleAndIcon)
            .symbolRenderingMode(.hierarchical)
            .padding(.horizontal, 9)
            .padding(.vertical, 5)
            .background(.quaternary, in: Capsule())
            .foregroundStyle(tint)
    }
}

private struct ActivityFlowMap: View {
    @EnvironmentObject private var model: EveMonitorModel
    let compact: Bool

    init(compact: Bool = false) {
        self.compact = compact
    }

    private var nodes: [ActivityFlowNode] {
        [
            ActivityFlowNode(
                title: "Signal",
                detail: "\(model.payload?.status?.counts?.unreadMessages ?? 0) unread",
                systemImage: "dot.radiowaves.left.and.right",
                state: .active
            ),
            ActivityFlowNode(
                title: "Workspace",
                detail: (model.payload?.workspace?.workspaceState?.mode ?? "holding").capitalized,
                systemImage: "rectangle.stack",
                state: model.payload?.workspace == nil ? .quiet : .active
            ),
            ActivityFlowNode(
                title: "Models",
                detail: model.activeModelCalls.isEmpty ? "standing by" : "\(model.activeModelCalls.count) calls",
                systemImage: "cpu",
                state: model.activeModelCalls.isEmpty ? .ready : .generating
            ),
            ActivityFlowNode(
                title: "Action",
                detail: latestActionDetail(model),
                systemImage: "checklist",
                state: latestActionState(model)
            ),
            ActivityFlowNode(
                title: "Evidence",
                detail: "\(model.payload?.substrate?.evidence?.count ?? 0) records",
                systemImage: "tray.full",
                state: (model.payload?.substrate?.evidence ?? []).isEmpty ? .quiet : .ready
            )
        ]
    }

    var body: some View {
        GroupBox("Live Path") {
            Group {
                if compact {
                    HStack(spacing: 0) {
                        ForEach(Array(nodes.enumerated()), id: \.offset) { index, node in
                            ActivityFlowCompactNodeView(node: node)
                            if index < nodes.count - 1 {
                                ActivityFlowCompactConnector(isActive: node.state != .quiet && nodes[index + 1].state != .quiet)
                            }
                        }
                    }
                    .padding(.vertical, 2)
                } else {
                    HStack(spacing: 0) {
                        ForEach(Array(nodes.enumerated()), id: \.offset) { index, node in
                            ActivityFlowNodeView(node: node)
                            if index < nodes.count - 1 {
                                ActivityFlowConnector(isActive: node.state != .quiet && nodes[index + 1].state != .quiet)
                            }
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private enum ActivityFlowState: Hashable {
    case quiet
    case ready
    case active
    case generating
    case warning
}

private struct ActivityFlowNode: Hashable {
    let title: String
    let detail: String
    let systemImage: String
    let state: ActivityFlowState
}

private struct ActivityFlowNodeView: View {
    let node: ActivityFlowNode

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                Circle()
                    .fill(flowColor(node.state).opacity(0.14))
                    .frame(width: 44, height: 44)
                Image(systemName: node.systemImage)
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundStyle(flowColor(node.state))
            }

            Text(node.title)
                .font(.callout.weight(.semibold))
                .lineLimit(1)

            Text(node.detail.monitorReadable.monitorLimited(to: 26))
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
        }
        .frame(minWidth: 108, maxWidth: .infinity)
        .padding(.vertical, 8)
    }
}

private struct ActivityFlowCompactNodeView: View {
    let node: ActivityFlowNode

    var body: some View {
        HStack(alignment: .center, spacing: 8) {
            ZStack {
                RoundedRectangle(cornerRadius: 7, style: .continuous)
                    .fill(flowColor(node.state).opacity(0.12))
                Image(systemName: node.systemImage)
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(flowColor(node.state))
            }
            .frame(width: 25, height: 25)

            VStack(alignment: .leading, spacing: 2) {
                Text(node.title)
                    .font(.caption.weight(.semibold))
                    .lineLimit(1)
                Text(node.detail.monitorReadable.monitorLimited(to: 22))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.vertical, 4)
    }
}

private struct ActivityFlowConnector: View {
    let isActive: Bool

    var body: some View {
        Rectangle()
            .fill(isActive ? MonitorTheme.accent.opacity(0.42) : MonitorTheme.divider)
            .frame(width: 36, height: 2)
            .padding(.horizontal, 2)
            .offset(y: -18)
    }
}

private struct ActivityFlowCompactConnector: View {
    let isActive: Bool

    var body: some View {
        Capsule()
            .fill(isActive ? MonitorTheme.accent.opacity(0.36) : MonitorTheme.divider)
            .frame(width: 18, height: 2)
            .padding(.horizontal, 8)
    }
}

private struct ModelLaneTimelinePanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var referenceElapsedMs: Double {
        model.activityLanes
            .map { laneTimelineValue($0) }
            .max() ?? 1
    }

    var body: some View {
        GroupBox("Model Lanes") {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    Text(model.activeModelCalls.isEmpty ? "No generation in progress" : activityOperationFamily(model.activeModelCalls))
                        .font(.title3.weight(.semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                    Spacer()
                    Text(model.lanesReady)
                        .font(.caption.monospacedDigit().weight(.semibold))
                        .foregroundStyle(.secondary)
                }

                VStack(spacing: 0) {
                    ForEach(Array(model.activityLanes.enumerated()), id: \.offset) { index, lane in
                        if index > 0 { Divider() }
                        LaneTimelineRow(lane: lane, referenceElapsedMs: referenceElapsedMs)
                    }
                }
            }
            .padding(.vertical, 2)
        }
    }
}

private struct LaneTimelineRow: View {
    let lane: MonitorActivityLane
    let referenceElapsedMs: Double

    private var state: String {
        lane.state ?? "ready"
    }

    private var tint: Color {
        activityStateColor(state)
    }

    private var progressFraction: CGFloat {
        let value = laneTimelineValue(lane)
        guard referenceElapsedMs > 0 else { return lane.loaded == true ? 1 : 0.14 }
        return CGFloat(min(1, max(0.08, value / referenceElapsedMs)))
    }

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 7) {
                    Text(lane.label ?? lane.lane ?? "Lane")
                        .font(.callout.weight(.semibold))
                        .lineLimit(1)
                    Text(state.capitalized)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(tint)
                }

                Text([lane.operation, lane.model].compactMap { $0?.monitorTrimmed }.filter { !$0.isEmpty }.joined(separator: " - ").monitorReadable.monitorLimited(to: 86))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            .frame(width: 190, alignment: .leading)

            ZStack(alignment: .leading) {
                Capsule()
                    .fill(.quaternary)
                    .frame(height: 12)
                GeometryReader { proxy in
                    Capsule()
                        .fill(tint.opacity(state == "generating" ? 0.92 : 0.54))
                        .frame(width: proxy.size.width * progressFraction, height: 12)
                }
                .frame(height: 12)
            }
            .frame(maxWidth: .infinity)

            Text(laneTiming(lane))
                .font(.caption.monospacedDigit().weight(.medium))
                .foregroundStyle(.secondary)
                .frame(width: 58, alignment: .trailing)
        }
        .padding(.vertical, 10)
    }
}

private struct ActivityResourceStoryPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var system: MonitorSystemActivity? {
        model.systemActivity
    }

    var body: some View {
        GroupBox("Compute") {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(computeLoadTitle(system))
                            .font(.title3.weight(.semibold))
                        Text(loadAverageDetail(system?.loadAverage))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    ResourceLegend(label: "CPU", tint: MonitorTheme.blue)
                    ResourceLegend(label: "Memory", tint: MonitorTheme.teal)
                }

                ActivityResourceSparkline(samples: model.resourceSamples)
                    .frame(height: 96)

                ActivityMeter(label: "CPU", value: system?.cpuPercent ?? 0, tint: activityLoadColor(system?.cpuPercent ?? 0))
                ActivityMeter(label: "Memory", value: system?.memory?.usedPercent ?? 0, tint: activityLoadColor(system?.memory?.usedPercent ?? 0))

                Divider()

                OverviewStatusLine(
                    title: diskRiskLabel(system?.disk),
                    detail: diskDetail(system?.disk),
                    metadata: MonitorFormatters.percent(system?.disk?.usedPercent),
                    systemImage: "internaldrive",
                    tint: diskRiskColor(system?.disk)
                )
            }
            .padding(.vertical, 2)
        }
    }
}

private struct ActivityEvidencePanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        GroupBox("What Changed") {
            VStack(spacing: 0) {
                if let action = model.payload?.operations?.actions?.first {
                    OverviewStatusLine(
                        title: action.action ?? "Action",
                        detail: action.summary ?? "No action summary",
                        metadata: action.resultOk == true || action.verificationOk == true ? "verified" : "needs check",
                        systemImage: action.resultOk == true || action.verificationOk == true ? "checkmark.circle" : "exclamationmark.triangle",
                        tint: action.resultOk == true || action.verificationOk == true ? MonitorTheme.accent : MonitorTheme.amber
                    )
                }

                if let pressure = model.peakPressure {
                    if model.payload?.operations?.actions?.first != nil { Divider() }
                    OverviewStatusLine(
                        title: pressureLabel(pressure),
                        detail: pressure.reason ?? "No pressure reason",
                        metadata: "\(pressureLevel(pressure))",
                        systemImage: "waveform.path.ecg",
                        tint: pressureSeverityColor(pressureLevel(pressure))
                    )
                }

                if let next = model.payload?.workspace?.actionReadiness?.first {
                    Divider()
                    OverviewStatusLine(
                        title: "Next useful move",
                        detail: next,
                        metadata: "ready",
                        systemImage: "arrow.forward.circle",
                        tint: MonitorTheme.teal
                    )
                }
            }
            .padding(.vertical, 2)
        }
    }
}

private struct ActivityDetailDrawersPanel: View {
    @EnvironmentObject private var model: EveMonitorModel
    @State private var showCalls = true
    @State private var showRecent = false
    @State private var showProcesses = false

    var body: some View {
        GroupBox("Details") {
            VStack(spacing: 0) {
                DisclosureGroup(isExpanded: $showCalls) {
                    ActiveModelCallsList()
                        .padding(.top, 8)
                } label: {
                    DetailDisclosureLabel(
                        title: "Running Calls",
                        value: "\(model.activeModelCalls.count)",
                        systemImage: "bolt.fill",
                        tint: model.activeModelCalls.isEmpty ? .secondary : MonitorTheme.amber
                    )
                }

                Divider()

                DisclosureGroup(isExpanded: $showRecent) {
                    RecentModelCallsList()
                        .padding(.top, 8)
                } label: {
                    DetailDisclosureLabel(
                        title: "Recent Calls",
                        value: "\(model.recentModelCalls.count)",
                        systemImage: "clock.arrow.circlepath",
                        tint: MonitorTheme.accent
                    )
                }
                .padding(.top, 8)

                Divider()

                DisclosureGroup(isExpanded: $showProcesses) {
                    ProcessList()
                        .padding(.top, 8)
                } label: {
                    DetailDisclosureLabel(
                        title: "Processes",
                        value: "\(model.systemActivity?.processes?.count ?? 0)",
                        systemImage: "list.bullet.rectangle",
                        tint: MonitorTheme.teal
                    )
                }
                .padding(.top, 8)
            }
            .padding(.vertical, 2)
        }
    }
}

private struct DetailDisclosureLabel: View {
    let title: String
    let value: String
    let systemImage: String
    let tint: Color

    var body: some View {
        HStack(spacing: 9) {
            Image(systemName: systemImage)
                .foregroundStyle(tint)
                .frame(width: 18)
            Text(title)
                .font(.callout.weight(.semibold))
            Spacer()
            Text(value)
                .font(.caption.monospacedDigit().weight(.semibold))
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 7)
    }
}

private struct ActivityVitalsStrip: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var system: MonitorSystemActivity? {
        model.systemActivity
    }

    var body: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 142), spacing: 10, alignment: .top)], alignment: .leading, spacing: 10) {
            OverviewVital(
                title: "CPU",
                value: MonitorFormatters.percent(system?.cpuPercent),
                detail: "\(system?.cpuCount ?? 0) cores",
                systemImage: "cpu",
                tint: activityLoadColor(system?.cpuPercent ?? 0)
            )
            OverviewVital(
                title: "Memory",
                value: MonitorFormatters.percent(system?.memory?.usedPercent),
                detail: memoryDetail(system?.memory),
                systemImage: "memorychip",
                tint: activityLoadColor(system?.memory?.usedPercent ?? 0)
            )
            OverviewVital(
                title: "Disk",
                value: MonitorFormatters.percent(system?.disk?.usedPercent),
                detail: diskDetail(system?.disk),
                systemImage: "internaldrive",
                tint: activityLoadColor(system?.disk?.usedPercent ?? 0)
            )
            OverviewVital(
                title: "Models",
                value: "\(model.activeModelCalls.count)",
                detail: model.activeModelCalls.isEmpty ? "no active calls" : "generating now",
                systemImage: "bolt.horizontal.circle",
                tint: model.activeModelCalls.isEmpty ? .secondary : MonitorTheme.amber
            )
            OverviewVital(
                title: "Processes",
                value: "\(system?.processCount ?? 0)",
                detail: "\(model.systemActivity?.processes?.count ?? 0) shown",
                systemImage: "list.bullet.rectangle",
                tint: MonitorTheme.teal
            )
        }
    }
}

private struct ActivityResourcePanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    private var system: MonitorSystemActivity? {
        model.systemActivity
    }

    var body: some View {
        GroupBox("System Load") {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Host resources")
                            .font(.title3.weight(.semibold))
                        Text(loadAverageDetail(system?.loadAverage))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }

                    Spacer()

                    HStack(spacing: 14) {
                        ResourceLegend(label: "CPU", tint: MonitorTheme.blue)
                        ResourceLegend(label: "Memory", tint: MonitorTheme.teal)
                    }
                }

                ActivityResourceSparkline(samples: model.resourceSamples)

                HStack(spacing: 14) {
                    ActivityMeter(label: "CPU", value: system?.cpuPercent ?? 0, tint: activityLoadColor(system?.cpuPercent ?? 0))
                    ActivityMeter(label: "Memory", value: system?.memory?.usedPercent ?? 0, tint: activityLoadColor(system?.memory?.usedPercent ?? 0))
                    ActivityMeter(label: "Disk", value: system?.disk?.usedPercent ?? 0, tint: activityLoadColor(system?.disk?.usedPercent ?? 0))
                }
            }
            .padding(.vertical, 2)
        }
    }
}

private struct ActivityResourceSparkline: View {
    let samples: [MonitorResourceSample]

    private var displayedSamples: [MonitorResourceSample] {
        Array(samples.suffix(48))
    }

    var body: some View {
        if displayedSamples.count >= 2 {
            Chart(displayedSamples) { sample in
                LineMark(
                    x: .value("Time", sample.timestamp),
                    y: .value("CPU", sample.cpuPercent)
                )
                .interpolationMethod(.catmullRom)
                .foregroundStyle(MonitorTheme.blue)
                .lineStyle(StrokeStyle(lineWidth: 1.8, lineCap: .round, lineJoin: .round))

                LineMark(
                    x: .value("Time", sample.timestamp),
                    y: .value("Memory", sample.memoryPercent)
                )
                .interpolationMethod(.catmullRom)
                .foregroundStyle(MonitorTheme.teal)
                .lineStyle(StrokeStyle(lineWidth: 1.8, lineCap: .round, lineJoin: .round))
            }
            .chartYScale(domain: 0...100)
            .chartXAxis(.hidden)
            .chartYAxis(.hidden)
            .chartPlotStyle { plotArea in
                plotArea
                    .background(.quaternary.opacity(0.35))
                    .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            }
            .frame(height: 86)
        } else {
            VStack(spacing: 8) {
                ProgressView()
                    .controlSize(.small)
                Text("Collecting realtime samples")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, minHeight: 86)
            .background(.quaternary.opacity(0.32), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
    }
}

private struct ActivityMeter: View {
    let label: String
    let value: Double
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack {
                Text(label)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Text(MonitorFormatters.percent(value))
                    .font(.caption.monospacedDigit().weight(.semibold))
                    .foregroundStyle(.secondary)
            }

            ProgressView(value: max(0, min(100, value)), total: 100)
                .tint(tint)
        }
        .frame(maxWidth: .infinity)
    }
}

private struct ResourceLegend: View {
    let label: String
    let tint: Color

    var body: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(tint)
                .frame(width: 7, height: 7)
            Text(label)
                .font(.caption.weight(.medium))
                .foregroundStyle(.secondary)
        }
    }
}

private struct ModelWorkPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        GroupBox("Model Work") {
            VStack(spacing: 0) {
                if model.activityLanes.isEmpty {
                    Text("No model lanes reported.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 8)
                } else {
                    ForEach(Array(model.activityLanes.enumerated()), id: \.offset) { index, lane in
                        if index > 0 { Divider() }
                        ActivityLaneRow(lane: lane)
                    }
                }
            }
            .padding(.vertical, 2)
        }
    }
}

private struct ActivityLaneRow: View {
    let lane: MonitorActivityLane

    private var state: String {
        lane.state ?? "ready"
    }

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            ZStack {
                Circle()
                    .fill(activityStateColor(state).opacity(0.16))
                    .frame(width: 30, height: 30)
                Image(systemName: state == "generating" ? "bolt.fill" : (lane.loaded == true ? "checkmark" : "exclamationmark"))
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(activityStateColor(state))
            }

            VStack(alignment: .leading, spacing: 5) {
                HStack(alignment: .firstTextBaseline) {
                    Text(lane.label ?? lane.lane ?? "Lane")
                        .font(.callout.weight(.semibold))
                        .lineLimit(1)
                    Text(state.capitalized)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(activityStateColor(state))
                    Spacer()
                    Text(laneTiming(lane))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }

                Text([lane.operation, lane.model, lane.backend].compactMap { $0?.monitorTrimmed }.filter { !$0.isEmpty }.joined(separator: " - ").monitorLimited(to: 140))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)

                ProgressView(value: laneProgressValue(lane), total: 100)
                    .tint(activityStateColor(state))
            }
        }
        .padding(.vertical, 9)
    }
}

private struct ActiveModelCallsPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        GroupBox("Running Calls") {
            ActiveModelCallsList()
        }
    }
}

private struct RecentModelCallsPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        GroupBox("Recent Calls") {
            RecentModelCallsList()
        }
    }
}

private struct ActiveModelCallsList: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        VStack(spacing: 0) {
            if model.activeModelCalls.isEmpty {
                OverviewStatusLine(
                    title: "Models are idle",
                    detail: "No active generation call is registered right now.",
                    metadata: MonitorFormatters.clock(model.payload?.activity?.updatedAt),
                    systemImage: "checkmark.circle",
                    tint: MonitorTheme.accent
                )
            } else {
                ForEach(Array(model.activeModelCalls.prefix(8).enumerated()), id: \.offset) { index, call in
                    if index > 0 { Divider() }
                    ModelCallRow(call: call, isActive: true)
                }
            }
        }
        .padding(.vertical, 2)
    }
}

private struct RecentModelCallsList: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        VStack(spacing: 0) {
            if model.recentModelCalls.isEmpty {
                Text("No recent model calls recorded.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 8)
            } else {
                ForEach(Array(model.recentModelCalls.prefix(6).enumerated()), id: \.offset) { index, call in
                    if index > 0 { Divider() }
                    ModelCallRow(call: call, isActive: false)
                }
            }
        }
        .padding(.vertical, 2)
    }
}

private struct ModelCallRow: View {
    let call: MonitorModelCall
    let isActive: Bool

    private var title: String {
        let operation = call.operation?.monitorTrimmed ?? ""
        return operation.isEmpty ? "model call" : operation
    }

    private var detail: String {
        [call.model, call.backend, call.host].compactMap { $0?.monitorTrimmed }.filter { !$0.isEmpty }.joined(separator: " - ")
    }

    private var metadata: String {
        if isActive {
            return MonitorFormatters.latency(call.elapsedMs)
        }
        return MonitorFormatters.latency(call.durationMs)
    }

    var body: some View {
        OverviewStatusLine(
            title: title,
            detail: detail.isEmpty ? "No model metadata" : detail,
            metadata: metadata,
            systemImage: isActive ? "bolt.fill" : (call.ok == false ? "xmark.circle" : "checkmark.circle"),
            tint: isActive ? MonitorTheme.amber : (call.ok == false ? MonitorTheme.red : MonitorTheme.accent)
        )
    }
}

private struct ProcessPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        GroupBox("Processes") {
            ProcessList()
        }
    }
}

private struct ProcessList: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        VStack(spacing: 0) {
            let processes = model.systemActivity?.processes ?? []
            if processes.isEmpty {
                Text("No process data available.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 8)
            } else {
                ForEach(Array(processes.prefix(7).enumerated()), id: \.offset) { index, process in
                    if index > 0 { Divider() }
                    ProcessRow(process: process)
                }
            }
        }
        .padding(.vertical, 2)
    }
}

private struct ProcessRow: View {
    let process: MonitorProcess

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Image(systemName: process.kind == "model" ? "cpu" : (process.kind == "eve" ? "sparkle.magnifyingglass" : "app.dashed"))
                .foregroundStyle(process.kind == "model" ? MonitorTheme.blue : (process.kind == "eve" ? MonitorTheme.accent : .secondary))
                .frame(width: 20)

            VStack(alignment: .leading, spacing: 2) {
                Text(process.title ?? "Process")
                    .font(.callout.weight(.medium))
                    .lineLimit(1)
                Text(process.command?.monitorLimited(to: 96) ?? "pid \(process.pid ?? 0)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 2) {
                Text(MonitorFormatters.percent(process.cpuPercent))
                    .font(.caption.monospacedDigit().weight(.semibold))
                Text(MonitorFormatters.bytes(process.memoryBytes))
                    .font(.caption2.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 8)
    }
}

private func activityLoadColor(_ value: Double) -> Color {
    if value >= 85 { return MonitorTheme.red }
    if value >= 65 { return MonitorTheme.amber }
    return MonitorTheme.blue
}

private func activityStateColor(_ state: String?) -> Color {
    switch (state ?? "").lowercased() {
    case "generating", "running":
        return MonitorTheme.amber
    case "ready", "loaded":
        return MonitorTheme.accent
    case "offline", "error":
        return MonitorTheme.red
    default:
        return .secondary
    }
}

private func serviceStateColor(_ state: MonitorServiceState) -> Color {
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

private func serviceStateLabel(_ state: MonitorServiceState) -> String {
    switch state {
    case .online:
        return "Online"
    case .warning:
        return "Partial"
    case .offline:
        return "Offline"
    case .unknown:
        return "Unknown"
    }
}

private func fitnessScore(_ value: Double?) -> String {
    guard let value else { return "n/a" }
    return String(format: "%.2f/5", value)
}

private func fitnessRatio(_ value: Double?) -> String {
    guard let value else { return "n/a" }
    return "\(Int((value * 100).rounded()))%"
}

private func fitnessStatusColor(passed: Bool?, warnings: Int?) -> Color {
    if warnings ?? 0 > 0 { return MonitorTheme.amber }
    if passed == true { return MonitorTheme.accent }
    if passed == false { return MonitorTheme.red }
    return MonitorTheme.blue
}

private func serviceStateSymbol(_ state: MonitorServiceState) -> String {
    switch state {
    case .online:
        return "checkmark.circle.fill"
    case .warning:
        return "exclamationmark.triangle.fill"
    case .offline:
        return "xmark.circle.fill"
    case .unknown:
        return "questionmark.circle"
    }
}

private func flowColor(_ state: ActivityFlowState) -> Color {
    switch state {
    case .quiet:
        return .secondary
    case .ready:
        return MonitorTheme.accent
    case .active:
        return MonitorTheme.blue
    case .generating:
        return MonitorTheme.amber
    case .warning:
        return MonitorTheme.red
    }
}

@MainActor private func activityStateSentence(model: EveMonitorModel) -> String {
    let mode = model.payload?.homeostasis?.regulationMode?.lowercased() ?? "holding"
    let activeCount = model.activeModelCalls.count
    let laneCount = model.activityLanes.filter { ($0.state ?? "").lowercased() == "generating" }.count
    let family = activityOperationFamily(model.activeModelCalls)
    let slowLane = model.activityLanes.max { ($0.elapsedMs ?? 0) < ($1.elapsedMs ?? 0) }
    let slowText = slowLane.map { "\($0.label ?? $0.lane ?? "One lane") is the slowest lane." } ?? ""
    let compute = computeLoadTitle(model.systemActivity).lowercased()
    let disk = diskRiskLabel(model.systemActivity?.disk).lowercased()
    let modeText = "\(mode) mode"
    if activeCount > 0 {
        return "Eve is in \(modeText), running \(family) across \(laneCount) model lane\(laneCount == 1 ? "" : "s"). \(slowText) Compute is \(compute); disk is \(disk)."
    }
    return "Eve is in \(modeText) and waiting for a real signal. Compute is \(compute); disk is \(disk)."
}

private func activityOperationFamily(_ calls: [MonitorModelCall]) -> String {
    let operations = calls.compactMap { $0.operation?.monitorTrimmed }.filter { !$0.isEmpty }
    guard let first = operations.first else { return "model work" }
    let laneSuffixes = ["_fast", "_deep", "_observer", "_planner", "_relationship", "_synthesis", "_grounding", "_self_check"]
    var base = first
    for suffix in laneSuffixes where base.hasSuffix(suffix) {
        base.removeLast(suffix.count)
        break
    }
    let readable = base.replacingOccurrences(of: "_", with: " ")
    return readable.isEmpty ? "model work" : readable
}

@MainActor private func overviewWorkValue(_ model: EveMonitorModel) -> String {
    if !model.activeModelCalls.isEmpty {
        return "\(model.activeModelCalls.count) calls"
    }
    if model.payload?.status?.activeReply?.id != nil {
        return model.activeReplyTitle.capitalized
    }
    return "Holding"
}

@MainActor private func overviewWorkDetail(_ model: EveMonitorModel) -> String {
    if !model.activeModelCalls.isEmpty {
        return activityOperationFamily(model.activeModelCalls)
    }
    if model.payload?.status?.activeReply?.id != nil {
        return model.activeReplyDetail
    }
    return "\(model.payload?.status?.counts?.waitingThreads ?? 0) waiting threads"
}

@MainActor private func overviewConstraintValue(_ model: EveMonitorModel) -> String {
    let disk = model.systemActivity?.disk
    if (disk?.usedPercent ?? 0) >= 85 {
        return diskRiskLabel(disk)
    }
    let memory = model.systemActivity?.memory
    if (memory?.usedPercent ?? 0) >= 75 {
        return MonitorFormatters.percent(memory?.usedPercent)
    }
    return "\(model.payload?.status?.counts?.unreadMessages ?? 0)"
}

@MainActor private func overviewConstraintDetail(_ model: EveMonitorModel) -> String {
    let disk = model.systemActivity?.disk
    if (disk?.usedPercent ?? 0) >= 85 {
        return diskDetail(disk)
    }
    let memory = model.systemActivity?.memory
    if (memory?.usedPercent ?? 0) >= 75 {
        return memoryDetail(memory)
    }
    return "unread signals"
}

@MainActor private func overviewConstraintImage(_ model: EveMonitorModel) -> String {
    let disk = model.systemActivity?.disk
    if (disk?.usedPercent ?? 0) >= 85 { return "internaldrive" }
    let memory = model.systemActivity?.memory
    if (memory?.usedPercent ?? 0) >= 75 { return "memorychip" }
    return "text.bubble"
}

@MainActor private func overviewConstraintColor(_ model: EveMonitorModel) -> Color {
    let disk = model.systemActivity?.disk
    if (disk?.usedPercent ?? 0) >= 85 { return diskRiskColor(disk) }
    let memory = model.systemActivity?.memory
    if (memory?.usedPercent ?? 0) >= 75 { return activityLoadColor(memory?.usedPercent ?? 0) }
    return MonitorTheme.teal
}

@MainActor private func latestActionDetail(_ model: EveMonitorModel) -> String {
    guard let action = model.payload?.operations?.actions?.first else { return "idle" }
    if action.resultOk == true || action.verificationOk == true { return "verified" }
    if action.treeStatus?.localizedCaseInsensitiveContains("fail") == true { return "blocked" }
    return action.treeStatus?.lowercased() ?? "pending"
}

@MainActor private func latestActionState(_ model: EveMonitorModel) -> ActivityFlowState {
    guard let action = model.payload?.operations?.actions?.first else { return .quiet }
    if action.resultOk == true || action.verificationOk == true { return .ready }
    if action.treeStatus?.localizedCaseInsensitiveContains("fail") == true { return .warning }
    return .active
}

private func computeLoadTitle(_ system: MonitorSystemActivity?) -> String {
    let cpu = system?.cpuPercent ?? 0
    let memory = system?.memory?.usedPercent ?? 0
    if cpu >= 85 || memory >= 90 { return "Hot" }
    if cpu >= 60 || memory >= 75 { return "Busy" }
    return "Steady"
}

private func diskRiskLabel(_ disk: MonitorDiskSnapshot?) -> String {
    let used = disk?.usedPercent ?? 0
    if used >= 95 { return "Tight" }
    if used >= 85 { return "Watch" }
    return "Comfortable"
}

private func diskRiskColor(_ disk: MonitorDiskSnapshot?) -> Color {
    let used = disk?.usedPercent ?? 0
    if used >= 95 { return MonitorTheme.red }
    if used >= 85 { return MonitorTheme.amber }
    return MonitorTheme.accent
}

private func memoryDetail(_ memory: MonitorMemorySnapshot?) -> String {
    let used = MonitorFormatters.bytes(memory?.usedBytes)
    let total = MonitorFormatters.bytes(memory?.totalBytes)
    if used.isEmpty || total.isEmpty { return "host memory" }
    return "\(used) of \(total)"
}

private func diskDetail(_ disk: MonitorDiskSnapshot?) -> String {
    let free = MonitorFormatters.bytes(disk?.freeBytes)
    if free.isEmpty { return "runtime volume" }
    return "\(free) free"
}

private func loadAverageDetail(_ values: [Double]?) -> String {
    let values = values ?? []
    guard !values.isEmpty else { return "Load average unavailable" }
    return "Load average " + values.prefix(3).map { String(format: "%.2f", $0) }.joined(separator: " / ")
}

private func laneTiming(_ lane: MonitorActivityLane) -> String {
    if (lane.state ?? "").lowercased() == "generating" {
        return MonitorFormatters.latency(lane.elapsedMs)
    }
    if let duration = lane.durationMs, duration > 0 {
        return MonitorFormatters.latency(duration)
    }
    return MonitorFormatters.latency(lane.latencyMs)
}

private func laneProgressValue(_ lane: MonitorActivityLane) -> Double {
    if (lane.state ?? "").lowercased() == "generating" {
        return min(96, max(8, (lane.elapsedMs ?? 0) / 1000 * 4))
    }
    if lane.loaded == true { return 100 }
    return 14
}

private func laneTimelineValue(_ lane: MonitorActivityLane) -> Double {
    if (lane.state ?? "").lowercased() == "generating" {
        return max(1, lane.elapsedMs ?? 0)
    }
    if let duration = lane.durationMs, duration > 0 {
        return duration
    }
    if let latency = lane.latencyMs, latency > 0 {
        return latency
    }
    return lane.loaded == true ? 1 : 0
}

private struct HomeostasisDetailView: View {
    @EnvironmentObject private var model: EveMonitorModel
    @State private var selectedPressureID: String?

    private var pressures: [MonitorPressure] {
        (model.payload?.homeostasis?.pressures ?? [])
            .sorted { ($0.level ?? 0) > ($1.level ?? 0) }
    }

    private var discountedSignals: [MonitorDiscountedSignal] {
        model.payload?.homeostasis?.discountedSignals ?? []
    }

    private var selectedPressure: MonitorPressure? {
        if let selectedPressureID,
           let pressure = pressures.first(where: { model.pressureKey($0) == selectedPressureID }) {
            return pressure
        }
        return pressures.first
    }

    private var criticalPressures: [MonitorPressure] {
        Array(allCriticalPressures.prefix(4))
    }

    private var allCriticalPressures: [MonitorPressure] {
        pressures.filter { ($0.level ?? 0) >= 70 }
    }

    private var watchCount: Int {
        pressures.filter { ($0.level ?? 0) >= 40 && ($0.level ?? 0) < 70 }.count
    }

    private var fallingCount: Int {
        pressures.filter { ($0.trend ?? "").localizedCaseInsensitiveContains("fall") }.count
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HomeostasisStoryHeader(
                mode: model.payload?.homeostasis?.regulationMode?.capitalized ?? "Homeostasis",
                summary: model.payload?.homeostasis?.summary ?? "No pressure summary",
                criticalCount: allCriticalPressures.count,
                watchCount: watchCount,
                fallingCount: fallingCount,
                topPressure: pressures.first
            )

            PressureLandscapeChart(
                pressures: pressures,
                selectedPressureID: selectedPressureID ?? selectedPressure.map { model.pressureKey($0) },
                selectPressure: { selectedPressureID = model.pressureKey($0) }
            )

            if !discountedSignals.isEmpty {
                DiscountedSignalsPanel(signals: discountedSignals)
            }

            LazyVGrid(
                columns: [
                    GridItem(.flexible(minimum: 260, maximum: 380), spacing: 16, alignment: .top),
                    GridItem(.flexible(minimum: 360), spacing: 16, alignment: .top)
                ],
                alignment: .leading,
                spacing: 16
            ) {
                PressureResponsePanel(
                    pressures: criticalPressures,
                    selectedPressure: selectedPressure
                )

                SelectedPressurePanel(pressure: selectedPressure)
            }

            GroupBox("All Pressures") {
                VStack(spacing: 0) {
                    ForEach(Array(pressures.enumerated()), id: \.offset) { index, pressure in
                        if index > 0 { Divider() }
                        PressureStoryRow(
                            pressure: pressure,
                            isSelected: model.pressureKey(pressure) == (selectedPressureID ?? selectedPressure.map { model.pressureKey($0) }),
                            selectPressure: { selectedPressureID = model.pressureKey(pressure) }
                        )
                    }
                }
            }
        }
        .onChange(of: pressures.map { model.pressureKey($0) }) { _, keys in
            if selectedPressureID == nil || !keys.contains(selectedPressureID ?? "") {
                selectedPressureID = keys.first
            }
        }
    }
}

private struct DiscountedSignalsPanel: View {
    let signals: [MonitorDiscountedSignal]

    var body: some View {
        GroupBox("Discounted / Deferred") {
            VStack(spacing: 0) {
                ForEach(Array(signals.enumerated()), id: \.offset) { index, signal in
                    if index > 0 { Divider() }
                    HStack(alignment: .top, spacing: 11) {
                        Image(systemName: signalIcon(signal))
                            .font(.body.weight(.semibold))
                            .foregroundStyle(signalTint(signal))
                            .frame(width: 20)
                            .padding(.top, 2)

                        VStack(alignment: .leading, spacing: 4) {
                            HStack(alignment: .firstTextBaseline, spacing: 7) {
                                Text(signal.label ?? signal.id ?? "Signal")
                                    .font(.body.weight(.medium))
                                    .fixedSize(horizontal: false, vertical: true)

                                Text(signal.disposition ?? "discounted")
                                    .font(.caption.weight(.semibold))
                                    .foregroundStyle(signalTint(signal))
                                    .lineLimit(1)
                            }

                            Text((signal.reason ?? "No reason recorded.").monitorReadable.monitorLimited(to: 180))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }

                        Spacer(minLength: 12)

                        VStack(alignment: .trailing, spacing: 2) {
                            Text("\(signal.count ?? 0)")
                                .font(.title3.monospacedDigit().weight(.semibold))
                                .foregroundStyle(signalTint(signal))
                            if let pressureId = signal.pressureId, !pressureId.isEmpty {
                                Text(pressureId.replacingOccurrences(of: "_", with: " "))
                                    .font(.caption2.weight(.medium))
                                    .foregroundStyle(.tertiary)
                                    .lineLimit(1)
                            }
                        }
                    }
                    .padding(.vertical, 8)
                }
            }
        }
    }
}

private func signalIcon(_ signal: MonitorDiscountedSignal) -> String {
    let key = [signal.id, signal.disposition, signal.pressureId].compactMap { $0?.lowercased() }.joined(separator: " ")
    if key.contains("resource") { return "thermometer.sun" }
    if key.contains("synthetic") { return "square.stack.3d.up.slash" }
    return "tray.and.arrow.down"
}

private func signalTint(_ signal: MonitorDiscountedSignal) -> Color {
    let key = [signal.id, signal.disposition, signal.pressureId].compactMap { $0?.lowercased() }.joined(separator: " ")
    if key.contains("resource") { return MonitorTheme.amber }
    if key.contains("synthetic") { return MonitorTheme.blue }
    return .secondary
}

private struct PressureResponsePanel: View {
    @EnvironmentObject private var model: EveMonitorModel
    let pressures: [MonitorPressure]
    let selectedPressure: MonitorPressure?

    private var criticalCount: Int {
        pressures.count
    }

    private var watchCount: Int {
        (model.payload?.homeostasis?.pressures ?? [])
            .filter { pressureLevel($0) >= 40 && pressureLevel($0) < 70 }
            .count
    }

    private var easingCount: Int {
        (model.payload?.homeostasis?.pressures ?? [])
            .filter { ($0.trend ?? "").localizedCaseInsensitiveContains("fall") }
            .count
    }

    var body: some View {
        GroupBox("Response") {
            VStack(alignment: .leading, spacing: 13) {
                if let selectedPressure {
                    OverviewStatusLine(
                        title: "Most urgent: \(pressureLabel(selectedPressure))",
                        detail: selectedPressure.reason ?? "No reason recorded.",
                        metadata: "\(pressureLevel(selectedPressure))",
                        systemImage: "exclamationmark.triangle",
                        tint: pressureSeverityColor(pressureLevel(selectedPressure))
                    )

                    Divider()
                }

                OverviewStatusLine(
                    title: "Next regulation step",
                    detail: model.payload?.homeostasis?.nextRegulationStep ?? model.payload?.workspace?.actionReadiness?.first ?? "No next step recorded.",
                    metadata: "ready",
                    systemImage: "arrow.forward.circle",
                    tint: MonitorTheme.teal
                )

                Divider()

                HStack(spacing: 0) {
                    PressureResponseCount(value: "\(criticalCount)", label: "critical", tint: MonitorTheme.red)
                    PressureResponseDivider()
                    PressureResponseCount(value: "\(watchCount)", label: "watch", tint: MonitorTheme.amber)
                    PressureResponseDivider()
                    PressureResponseCount(value: "\(easingCount)", label: "easing", tint: MonitorTheme.blue)
                }
            }
            .padding(.vertical, 2)
        }
    }
}

private struct PressureResponseCount: View {
    let value: String
    let label: String
    let tint: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value)
                .font(.title2.weight(.semibold).monospacedDigit())
                .foregroundStyle(tint)
            Text(label)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct PressureResponseDivider: View {
    var body: some View {
        Divider()
            .frame(height: 38)
            .padding(.horizontal, 12)
    }
}

private struct HomeostasisStoryHeader: View {
    let mode: String
    let summary: String
    let criticalCount: Int
    let watchCount: Int
    let fallingCount: Int
    let topPressure: MonitorPressure?

    private var story: String {
        let top = topPressure?.label ?? topPressure?.id ?? "no dominant pressure"
        return "\(criticalCount) critical, \(watchCount) watch, \(fallingCount) easing. Most urgent: \(top)."
    }

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            Image(systemName: "waveform.path.ecg")
                .font(.system(size: 31, weight: .regular))
                .foregroundStyle(MonitorTheme.accent)
                .frame(width: 40)

            VStack(alignment: .leading, spacing: 8) {
                Text(mode)
                    .font(.largeTitle.weight(.semibold))
                    .lineLimit(1)

                Text(story)
                    .font(.headline)
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)

                Text(summary.monitorReadable.monitorLimited(to: 220))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

private struct PressureLandscapeChart: View {
    let pressures: [MonitorPressure]
    let selectedPressureID: String?
    let selectPressure: (MonitorPressure) -> Void

    private var criticalCount: Int {
        pressures.filter { pressureLevel($0) >= 70 }.count
    }

    private var watchCount: Int {
        pressures.filter { pressureLevel($0) >= 40 && pressureLevel($0) < 70 }.count
    }

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    VStack(alignment: .leading, spacing: 3) {
                        Text("Pressure Map")
                            .font(.headline)
                        Text("\(criticalCount) above critical, \(watchCount) in watch, \(pressures.count) total signals.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    HStack(spacing: 8) {
                        SeverityLegend(label: "Stable", color: MonitorTheme.blue)
                        SeverityLegend(label: "Watch", color: MonitorTheme.amber)
                        SeverityLegend(label: "Critical", color: MonitorTheme.red)
                    }
                }

                VStack(spacing: 10) {
                    ThresholdRuler()

                    ForEach(pressures, id: \.self) { pressure in
                        PressureGaugeRow(
                            pressure: pressure,
                            isSelected: selectedPressureID == pressureStableID(pressure),
                            selectPressure: { selectPressure(pressure) }
                        )
                    }
                }
            }
            .padding(.vertical, 2)
        }
    }
}

private struct ThresholdRuler: View {
    var body: some View {
        VStack(spacing: 5) {
            GeometryReader { proxy in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(.quinary)
                        .frame(height: 4)

                    Capsule()
                        .fill(MonitorTheme.blue.opacity(0.42))
                        .frame(width: proxy.size.width * 0.40, height: 4)

                    Capsule()
                        .fill(MonitorTheme.amber.opacity(0.54))
                        .frame(width: proxy.size.width * 0.30, height: 4)
                        .offset(x: proxy.size.width * 0.40)

                    Capsule()
                        .fill(MonitorTheme.red.opacity(0.58))
                        .frame(width: proxy.size.width * 0.30, height: 4)
                        .offset(x: proxy.size.width * 0.70)
                }
            }
            .frame(height: 4)

            HStack {
                Text("0")
                Spacer()
                Text("40 watch")
                Spacer()
                Text("70 critical")
                Spacer()
                Text("100")
            }
            .font(.caption2.monospacedDigit())
            .foregroundStyle(.tertiary)
        }
        .padding(.bottom, 2)
    }
}

private struct PressureGaugeRow: View {
    let pressure: MonitorPressure
    let isSelected: Bool
    let selectPressure: () -> Void

    private var level: Int {
        pressureLevel(pressure)
    }

    var body: some View {
        Button(action: selectPressure) {
            HStack(alignment: .center, spacing: 12) {
                SeverityDot(level: level)

                VStack(alignment: .leading, spacing: 7) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text(pressureLabel(pressure))
                            .font(.body.weight(.medium))
                            .lineLimit(1)

                        Text(pressure.trend ?? "steady")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(.secondary)
                            .lineLimit(1)

                        Spacer(minLength: 8)

                        Text("\(level)")
                            .font(.body.monospacedDigit().weight(.semibold))
                            .foregroundStyle(pressureSeverityColor(level))
                    }

                    PressureGaugeBar(level: level)
                }
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .background(
            (isSelected ? MonitorTheme.accent.opacity(0.10) : Color.clear),
            in: RoundedRectangle(cornerRadius: 9, style: .continuous)
        )
    }
}

private struct PressureGaugeBar: View {
    let level: Int

    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(.quinary)

                Capsule()
                    .fill(pressureSeverityColor(level).opacity(level >= 70 ? 0.72 : 0.84))
                    .frame(width: max(6, proxy.size.width * CGFloat(level) / 100))
            }
        }
        .frame(height: 7)
    }
}

private struct CriticalNowPanel: View {
    let pressures: [MonitorPressure]
    let selectedPressureID: String?
    let selectPressure: (MonitorPressure) -> Void

    var body: some View {
        GroupBox("Critical Now") {
            VStack(spacing: 0) {
                if pressures.isEmpty {
                    Text("No critical pressures right now.")
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.vertical, 8)
                } else {
                    ForEach(Array(pressures.enumerated()), id: \.offset) { index, pressure in
                        if index > 0 { Divider() }
                        Button {
                            selectPressure(pressure)
                        } label: {
                            HStack(alignment: .top, spacing: 10) {
                                SeverityDot(level: pressureLevel(pressure))
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(pressureLabel(pressure))
                                        .font(.body.weight(.medium))
                                    Text((pressure.reason ?? "No reason recorded.").monitorReadable.monitorLimited(to: 96))
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(2)
                                }
                                Spacer()
                                Text("\(pressureLevel(pressure))")
                                    .font(.title3.monospacedDigit().weight(.semibold))
                                    .foregroundStyle(pressureSeverityColor(pressureLevel(pressure)))
                            }
                            .padding(.vertical, 9)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .opacity(selectedPressureID == pressureStableID(pressure) ? 1 : 0.82)
                    }
                }
            }
        }
    }
}

private struct SelectedPressurePanel: View {
    @EnvironmentObject private var model: EveMonitorModel
    let pressure: MonitorPressure?

    var body: some View {
        GroupBox("Why It Matters") {
            if let pressure {
                let level = pressureLevel(pressure)
                let history = model.pressureHistory(for: pressure)
                VStack(alignment: .leading, spacing: 14) {
                    HStack(alignment: .firstTextBaseline) {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(pressureLabel(pressure))
                                .font(.title2.weight(.semibold))
                            Text(pressureSeverityLabel(level))
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(pressureSeverityColor(level))
                        }
                        Spacer()
                        Text("\(level)")
                            .font(.system(size: 42, weight: .semibold, design: .rounded).monospacedDigit())
                            .foregroundStyle(pressureSeverityColor(level))
                    }

                    Text((pressure.reason ?? "No reason recorded.").monitorReadable.monitorLimited(to: 260))
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)

                    MiniPressureTrend(samples: history, level: level)

                    Divider()

                    LabeledContent("Trend", value: pressure.trend ?? "steady")
                    if let delta = model.pressureDelta(for: pressure) {
                        LabeledContent("Last Change", value: delta == 0 ? "unchanged" : "\(delta > 0 ? "+" : "")\(delta)")
                    }
                    LabeledContent("Signals", value: "\(pressure.signalCount ?? 0)")
                }
                .padding(.vertical, 4)
            } else {
                Text("No pressure selected.")
                    .foregroundStyle(.secondary)
            }
        }
    }
}

private struct MiniPressureTrend: View {
    let samples: [MonitorPressureSample]
    let level: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack {
                Text("Live Trend")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Spacer()
                Text("\(samples.count) samples")
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }

            Chart(samples) { sample in
                AreaMark(
                    x: .value("Time", sample.timestamp),
                    y: .value("Level", sample.level)
                )
                .foregroundStyle(pressureSeverityColor(level).opacity(0.14))

                LineMark(
                    x: .value("Time", sample.timestamp),
                    y: .value("Level", sample.level)
                )
                .interpolationMethod(.catmullRom)
                .foregroundStyle(pressureSeverityColor(level))
            }
            .chartYScale(domain: 0...100)
            .chartXAxis(.hidden)
            .chartYAxis {
                AxisMarks(values: [0, 50, 100]) { value in
                    AxisGridLine()
                        .foregroundStyle(.secondary.opacity(0.12))
                    AxisValueLabel {
                        if let intValue = value.as(Int.self) {
                            Text("\(intValue)")
                        }
                    }
                }
            }
            .frame(height: 120)
        }
    }
}

private struct PressureStoryRow: View {
    let pressure: MonitorPressure
    let isSelected: Bool
    let selectPressure: () -> Void

    private var level: Int {
        pressureLevel(pressure)
    }

    var body: some View {
        Button {
            selectPressure()
        } label: {
            HStack(alignment: .center, spacing: 12) {
                SeverityDot(level: level)
                VStack(alignment: .leading, spacing: 4) {
                    HStack(alignment: .firstTextBaseline) {
                        Text(pressureLabel(pressure))
                            .font(.body.weight(.medium))
                        Text(pressureSeverityLabel(level))
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(pressureSeverityColor(level))
                    }
                    Text((pressure.reason ?? "No reason recorded.").monitorReadable.monitorLimited(to: 140))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                Spacer()
                Text("\(level)")
                    .font(.title3.monospacedDigit().weight(.semibold))
                    .foregroundStyle(pressureSeverityColor(level))
                Text(pressure.trend ?? "steady")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.secondary)
            }
            .padding(.vertical, 9)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .background(isSelected ? MonitorTheme.accent.opacity(0.08) : Color.clear, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    }
}

private struct SeverityLegend: View {
    let label: String
    let color: Color

    var body: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
    }
}

private struct SeverityDot: View {
    let level: Int

    var body: some View {
        Circle()
            .fill(pressureSeverityColor(level))
            .frame(width: 10, height: 10)
            .padding(.top, 5)
    }
}

private func pressureLevel(_ pressure: MonitorPressure) -> Int {
    max(0, min(100, pressure.level ?? 0))
}

private func pressureLabel(_ pressure: MonitorPressure) -> String {
    pressure.label ?? pressure.id ?? "Pressure"
}

private func pressureStableID(_ pressure: MonitorPressure) -> String {
    pressure.id ?? pressure.label ?? "pressure"
}

private func pressureSeverityLabel(_ level: Int) -> String {
    if level >= 70 { return "Critical" }
    if level >= 40 { return "Watch" }
    return "Stable"
}

private func pressureSeverityColor(_ level: Int) -> Color {
    if level >= 70 { return MonitorTheme.red }
    if level >= 40 { return MonitorTheme.amber }
    return MonitorTheme.blue
}

private enum RecordsPane: String, CaseIterable, Identifiable {
    case autonomy = "Autonomy"
    case substrate = "Substrate"
    case operations = "Operations"
    case spine = "Spine"
    case threads = "Threads"

    var id: String { rawValue }

    var subtitle: String {
        switch self {
        case .autonomy:
            return "What Eve intends to keep moving."
        case .substrate:
            return "What Eve has evidence for."
        case .operations:
            return "What Eve has done or queued."
        case .spine:
            return "What Eve heard, said, and traced."
        case .threads:
            return "What still has human or system attention."
        }
    }

    var systemImage: String {
        switch self {
        case .autonomy:
            return "point.3.connected.trianglepath.dotted"
        case .substrate:
            return "tray.full"
        case .operations:
            return "checklist"
        case .spine:
            return "point.3.filled.connected.trianglepath.dotted"
        case .threads:
            return "text.bubble"
        }
    }
}

private let recordsStoryColumns: [GridItem] = [
    GridItem(.flexible(minimum: 560), spacing: 14, alignment: .top),
    GridItem(.flexible(minimum: 260, maximum: 320), spacing: 14, alignment: .top)
]

private struct RecordsDetailView: View {
    @State private var selectedPane: RecordsPane = .substrate

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            RecordsStoryHeader(selectedPane: selectedPane)

            RecordsModePicker(selectedPane: $selectedPane)

            switch selectedPane {
            case .autonomy:
                AutonomyDetailView()
            case .substrate:
                SubstrateDetailView()
            case .operations:
                OperationsDetailView()
            case .spine:
                ConversationSpineDetailView()
            case .threads:
                ThreadsDetailView()
            }
        }
    }
}

private struct RecordsStoryHeader: View {
    @EnvironmentObject private var model: EveMonitorModel
    let selectedPane: RecordsPane

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            ZStack {
                Circle()
                    .fill(MonitorTheme.accent.opacity(0.16))
                Image(systemName: selectedPane.systemImage)
                    .font(.system(size: 22, weight: .semibold))
                    .foregroundStyle(MonitorTheme.accent)
            }
            .frame(width: 46, height: 46)

            VStack(alignment: .leading, spacing: 7) {
                Text("Records")
                    .font(.title.weight(.semibold))
                    .lineLimit(1)
                Text("What Eve noticed, promised, did, and still owes attention.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 8) {
                    RecordsSummaryCapsule(value: "\(selectedPaneCount)", label: selectedPane.rawValue)
                    RecordsSummaryCapsule(value: "\(recordTotal)", label: "Total")
                    RecordsSummaryCapsule(value: "\(threadCount)", label: "Threads")
                }
                .padding(.top, 2)
            }

            Spacer(minLength: 12)

            VStack(alignment: .trailing, spacing: 6) {
                Text(selectedPane.subtitle)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                Text(latestSignal)
                    .font(.callout.weight(.medium))
                    .multilineTextAlignment(.trailing)
                    .lineLimit(3)
                    .fixedSize(horizontal: false, vertical: true)
            }
            .frame(maxWidth: 300, alignment: .trailing)
        }
        .padding(16)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: MonitorTheme.panelRadius, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: MonitorTheme.panelRadius, style: .continuous)
                .strokeBorder(MonitorTheme.divider)
        }
    }

    private var recordTotal: Int {
        autonomyCount + substrateCount + operationsCount + spineCount + threadCount
    }

    private var selectedPaneCount: Int {
        switch selectedPane {
        case .autonomy:
            return autonomyCount
        case .substrate:
            return substrateCount
        case .operations:
            return operationsCount
        case .spine:
            return spineCount
        case .threads:
            return threadCount
        }
    }

    private var autonomyCount: Int {
        (model.payload?.autonomy?.agenda?.activeThreads?.count ?? 0)
            + (model.payload?.autonomy?.runs?.count ?? 0)
    }

    private var substrateCount: Int {
        (model.payload?.substrate?.evidence?.count ?? 0)
            + (model.payload?.substrate?.commitments?.count ?? 0)
            + (model.payload?.substrate?.experience?.count ?? 0)
    }

    private var operationsCount: Int {
        (model.payload?.operations?.actions?.count ?? 0)
            + (model.payload?.operations?.systemTasks?.count ?? 0)
    }

    private var spineCount: Int {
        model.payload?.conversationSpine?.count ?? 0
    }

    private var threadCount: Int {
        model.payload?.status?.threadAttention?.count ?? 0
    }

    private var latestSignal: String {
        if let turn = model.payload?.conversationSpine?.first?.bodyPreview?.monitorTrimmed, !turn.isEmpty {
            return "Latest turn: \(turn.monitorLimited(to: 140))"
        }
        if let thread = model.payload?.status?.threadAttention?.first?.subject?.monitorTrimmed, !thread.isEmpty {
            return "Latest thread: \(thread.monitorLimited(to: 140))"
        }
        if let action = model.payload?.operations?.actions?.first?.action?.monitorTrimmed, !action.isEmpty {
            return "Latest action: \(action.monitorLimited(to: 140))"
        }
        if let evidence = model.payload?.substrate?.evidence?.first?.claim?.monitorTrimmed, !evidence.isEmpty {
            return "Latest evidence: \(evidence.monitorReadable.monitorLimited(to: 140))"
        }
        return "Waiting for the next recorded signal."
    }
}

private struct RecordsModePicker: View {
    @Binding var selectedPane: RecordsPane

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 2) {
                Text(selectedPane.rawValue)
                    .font(.headline.weight(.semibold))
                Text(selectedPane.subtitle)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer(minLength: 12)

            Picker("Records", selection: $selectedPane) {
                ForEach(RecordsPane.allCases) { pane in
                    Text(pane.rawValue).tag(pane)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(minWidth: 360, idealWidth: 500, maxWidth: 520)
        }
        .padding(10)
        .background(Color.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

private struct RecordsSummaryCapsule: View {
    let value: String
    let label: String

    var body: some View {
        HStack(spacing: 5) {
            Text(value)
                .font(.caption.monospacedDigit().weight(.semibold))
                .foregroundStyle(.primary)
            Text(label)
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 9)
        .padding(.vertical, 5)
        .background(.quaternary, in: Capsule())
    }
}

private struct AutonomyDetailView: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        LazyVGrid(columns: recordsStoryColumns, alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 14) {
                RecordsTrailPanel(
                    title: model.payload?.autonomy?.state?.stage?.capitalized ?? "Agenda",
                    subtitle: model.autonomyFocus,
                    items: agendaRecords,
                    emptyTitle: "No active autonomy threads",
                    emptyDetail: "Eve has not recorded an active agenda thread yet."
                )

                RecordsTrailPanel(
                    title: "Runs",
                    subtitle: "Recent autonomous passes and their supervisor result.",
                    items: runRecords,
                    emptyTitle: "No autonomy runs",
                    emptyDetail: "No completed autonomy run has been recorded yet."
                )
            }

            RecordsBriefPanel(
                title: "Autonomy Brief",
                subtitle: model.payload?.autonomy?.agenda?.summary ?? "No autonomy summary yet.",
                metrics: [
                    RecordsMetric(title: "Threads", value: "\(model.payload?.autonomy?.agenda?.activeThreads?.count ?? 0)", detail: "Active"),
                    RecordsMetric(title: "Runs", value: "\(model.payload?.autonomy?.runs?.count ?? 0)", detail: "Recorded"),
                    RecordsMetric(title: "Stage", value: model.payload?.autonomy?.state?.stage?.capitalized ?? "Unknown", detail: MonitorFormatters.dateTime(model.payload?.autonomy?.state?.updatedAt))
                ]
            )
        }
    }

    private var agendaRecords: [StreamRecord] {
        (model.payload?.autonomy?.agenda?.activeThreads ?? []).prefix(8).map { thread in
            StreamRecord(
                title: thread.title ?? "Autonomy thread",
                detail: thread.why ?? thread.evidence ?? "No thread detail",
                metadata: thread.family ?? thread.status ?? "thread",
                systemImage: "circle.dotted"
            )
        }
    }

    private var runRecords: [StreamRecord] {
        (model.payload?.autonomy?.runs ?? []).prefix(6).map { run in
            StreamRecord(
                title: run.runId ?? "Autonomy run",
                detail: run.objective ?? "\(run.actionCount ?? 0) action(s)",
                metadata: "\(run.supervisor?.verdict ?? "run") \(run.supervisor?.score ?? 0)",
                systemImage: "arrow.triangle.2.circlepath"
            )
        }
    }
}

private struct SubstrateDetailView: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            SubstrateStreamPicker(selectedStream: $model.selectedStream)

            LazyVGrid(columns: recordsStoryColumns, alignment: .leading, spacing: 14) {
                RecordsTrailPanel(
                    title: "\(model.selectedStream.rawValue) Trail",
                    subtitle: streamSubtitle,
                    items: streamRecords,
                    emptyTitle: "No \(model.selectedStream.rawValue.lowercased()) yet",
                    emptyDetail: "The substrate has not recorded this stream yet."
                )

                RecordsBriefPanel(
                    title: "Substrate Brief",
                    subtitle: "The proof Eve is carrying forward.",
                    metrics: [
                        RecordsMetric(title: "Evidence", value: "\(model.payload?.substrate?.evidence?.count ?? 0)", detail: "Claims"),
                        RecordsMetric(title: "Commitments", value: "\(model.payload?.substrate?.commitments?.count ?? 0)", detail: "Promises"),
                        RecordsMetric(title: "Experience", value: "\(model.payload?.substrate?.experience?.count ?? 0)", detail: "Events")
                    ]
                )
            }
        }
    }

    private var streamSubtitle: String {
        switch model.selectedStream {
        case .evidence:
            return "Observed claims and their freshness."
        case .commitments:
            return "Promises, actions, and verification results."
        case .experience:
            return "Remembered events and what Eve learned from them."
        }
    }

    private var streamRecords: [StreamRecord] {
        switch model.selectedStream {
        case .evidence:
            return (model.payload?.substrate?.evidence ?? []).prefix(14).map { record in
                StreamRecord(
                    title: record.claim ?? record.summary ?? "Evidence",
                    detail: record.summary ?? "No evidence summary",
                    metadata: "\(record.actionability ?? record.status ?? "evidence") - freshness \(record.freshness ?? 0)",
                    systemImage: "tray.full"
                )
            }
        case .commitments:
            return (model.payload?.substrate?.commitments ?? []).prefix(14).map { record in
                StreamRecord(
                    title: record.text ?? "Commitment",
                    detail: record.resultSummary ?? record.verification ?? record.action ?? "No result recorded",
                    metadata: record.status ?? "commitment",
                    systemImage: "checkmark.seal"
                )
            }
        case .experience:
            return (model.payload?.substrate?.experience ?? []).prefix(14).map { record in
                StreamRecord(
                    title: record.subject ?? record.eventType ?? "Experience",
                    detail: record.summary ?? "No experience summary",
                    metadata: record.actor ?? record.eventType ?? "event",
                    systemImage: "sparkle.magnifyingglass"
                )
            }
        }
    }
}

private struct OperationsDetailView: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        LazyVGrid(columns: recordsStoryColumns, alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 14) {
                RecordsTrailPanel(
                    title: "Actions",
                    subtitle: "Concrete work Eve has attempted or verified.",
                    items: actionRecords,
                    emptyTitle: "No recent actions",
                    emptyDetail: "Eve has not recorded an action in this window yet."
                )

                RecordsTrailPanel(
                    title: "System Tasks",
                    subtitle: "Maintenance work, queues, and internal tasks.",
                    items: taskRecords,
                    emptyTitle: "No system tasks",
                    emptyDetail: "No queued system task is visible in the monitor payload."
                )
            }

            RecordsBriefPanel(
                title: "Operations Brief",
                subtitle: model.payload?.state?.systemSummary ?? "No system summary yet.",
                metrics: [
                    RecordsMetric(title: "Actions", value: "\(model.payload?.operations?.actions?.count ?? 0)", detail: "Recent"),
                    RecordsMetric(title: "Tasks", value: "\(model.payload?.operations?.systemTasks?.count ?? 0)", detail: "System"),
                    RecordsMetric(title: "OpenClaw", value: openClawValue, detail: model.payload?.state?.openclawSummary ?? "No OpenClaw summary")
                ]
            )
        }
    }

    private var actionRecords: [StreamRecord] {
        (model.payload?.operations?.actions ?? []).prefix(14).map { action in
            StreamRecord(
                title: action.action ?? "Action",
                detail: action.summary ?? "No action summary",
                metadata: MonitorFormatters.clock(action.updatedAt ?? action.createdAt),
                systemImage: action.verificationOk == true || action.resultOk == true ? "checkmark.circle" : "clock"
            )
        }
    }

    private var taskRecords: [StreamRecord] {
        (model.payload?.operations?.systemTasks ?? []).prefix(10).map { task in
            StreamRecord(
                title: task.title ?? task.kind ?? "System task",
                detail: task.summary ?? task.lane ?? "No task summary",
                metadata: task.status ?? task.kind ?? "task",
                systemImage: "gearshape.2"
            )
        }
    }

    private var openClawValue: String {
        let summary = model.payload?.state?.openclawSummary?.lowercased() ?? ""
        if summary.contains("degraded") { return "Degraded" }
        if summary.contains("unreachable") || summary.contains("not reachable") { return "Offline" }
        if summary.contains("reachable") { return "Reachable" }
        return "Unknown"
    }
}

private struct ConversationSpineDetailView: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        LazyVGrid(columns: recordsStoryColumns, alignment: .leading, spacing: 14) {
            RecordsTrailPanel(
                title: "Conversation Spine",
                subtitle: "The canonical inbound/outbound turns Eve can use to prove what was live, synthetic, or internal.",
                items: spineRecords,
                emptyTitle: "No conversation spine yet",
                emptyDetail: "Eve has not mirrored visible conversation turns into the spine payload yet."
            )

            RecordsBriefPanel(
                title: "Spine Brief",
                subtitle: "This is the proof trail tying the latest user signal to replies, lane records, and trace export.",
                metrics: [
                    RecordsMetric(title: "Turns", value: "\(model.payload?.conversationSpine?.count ?? 0)", detail: "Visible"),
                    RecordsMetric(title: "Trace", value: latestTraceValue, detail: latestTraceDetail),
                    RecordsMetric(title: "Synthetic", value: "\(syntheticCount)", detail: "Shown only when included")
                ]
            )
        }
    }

    private var spineRecords: [StreamRecord] {
        (model.payload?.conversationSpine ?? []).prefix(14).map { turn in
            let role = turn.role?.capitalized ?? "Turn"
            let direction = turn.direction?.capitalized ?? "Unknown"
            let subject = turn.subject?.monitorTrimmed ?? ""
            let title = subject.isEmpty ? "\(role) \(direction)" : subject
            let metadata = MonitorFormatters.clock(turn.timestamp ?? turn.createdAt)
            return StreamRecord(
                title: title,
                detail: turn.bodyPreview ?? turn.messageId ?? "No turn preview",
                metadata: metadata.isEmpty ? (turn.source ?? turn.runtime ?? "spine") : metadata,
                systemImage: spineSystemImage(turn)
            )
        }
    }

    private var latestTraceValue: String {
        model.payload?.conversationSpine?.first?.traceId?.monitorLimited(to: 42) ?? "None"
    }

    private var latestTraceDetail: String {
        let turn = model.payload?.conversationSpine?.first
        return turn?.runtime ?? turn?.source ?? "No latest trace"
    }

    private var syntheticCount: Int {
        (model.payload?.conversationSpine ?? []).filter { $0.synthetic == true }.count
    }

    private func spineSystemImage(_ turn: MonitorConversationTurn) -> String {
        if turn.synthetic == true { return "testtube.2" }
        switch turn.direction?.lowercased() {
        case "inbound":
            return "person.crop.circle"
        case "outbound":
            return "sparkles"
        case "internal":
            return "brain.head.profile"
        default:
            return "point.3.connected.trianglepath.dotted"
        }
    }
}

private struct ThreadsDetailView: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        LazyVGrid(columns: recordsStoryColumns, alignment: .leading, spacing: 14) {
            RecordsTrailPanel(
                title: "Thread Attention",
                subtitle: "The conversations or loops that still carry attention.",
                items: threadRecords,
                emptyTitle: "No threads need attention",
                emptyDetail: "The monitor has no thread attention records right now."
            )

            RecordsBriefPanel(
                title: "Attention Brief",
                subtitle: model.payload?.status?.activeReply?.detail ?? model.payload?.status?.activeReply?.title ?? "No active reply detail yet.",
                metrics: [
                    RecordsMetric(title: "Active", value: "\(model.payload?.status?.counts?.activeThreads ?? 0)", detail: "Threads"),
                    RecordsMetric(title: "Waiting", value: "\(model.payload?.status?.counts?.waitingThreads ?? 0)", detail: "Threads"),
                    RecordsMetric(title: "Unread", value: "\(model.payload?.status?.counts?.unreadMessages ?? 0)", detail: "Signals")
                ]
            )
        }
    }

    private var threadRecords: [StreamRecord] {
        (model.payload?.status?.threadAttention ?? []).prefix(14).map { thread in
            StreamRecord(
                title: thread.subject ?? "Thread",
                detail: "\(thread.latestSender ?? "unknown") - \(thread.latestPreview ?? "No preview")",
                metadata: thread.status ?? "open",
                systemImage: thread.status == "awaiting_user" ? "person.crop.circle.badge.exclamationmark" : "text.bubble"
            )
        }
    }
}

private struct SubstrateStreamPicker: View {
    @Binding var selectedStream: MonitorStream

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "rectangle.stack")
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(.secondary)

            Picker("Substrate", selection: $selectedStream) {
                ForEach(MonitorStream.allCases) { stream in
                    Text(stream.rawValue).tag(stream)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
            .frame(width: 360)
        }
    }
}

private struct RecordsMetric: Identifiable {
    let title: String
    let value: String
    let detail: String

    var id: String { title }
}

private struct RecordsBriefPanel: View {
    let title: String
    let subtitle: String
    let metrics: [RecordsMetric]

    var body: some View {
        GroupBox(title) {
            VStack(alignment: .leading, spacing: 12) {
                Text(subtitle.monitorReadable.monitorLimited(to: 220))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                Divider()

                VStack(spacing: 0) {
                    ForEach(Array(metrics.enumerated()), id: \.element.id) { index, metric in
                        if index > 0 { Divider() }
                        RecordsMetricRow(metric: metric)
                    }
                }
            }
        }
    }
}

private struct RecordsMetricRow: View {
    let metric: RecordsMetric

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(metric.title)
                    .font(.callout.weight(.medium))
                Text(metric.detail.monitorReadable.monitorLimited(to: 80))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            Spacer(minLength: 10)

            Text(metric.value.monitorLimited(to: 42))
                .font(.callout.monospacedDigit().weight(.semibold))
                .multilineTextAlignment(.trailing)
                .lineLimit(2)
                .minimumScaleFactor(0.75)
        }
        .padding(.vertical, 8)
    }
}

private struct RecordsTrailPanel: View {
    let title: String
    let subtitle: String
    let items: [StreamRecord]
    let emptyTitle: String
    let emptyDetail: String

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 12) {
                Text(subtitle.monitorReadable.monitorLimited(to: 240))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                if let first = items.first {
                    LatestRecordSpotlight(record: first)

                    if items.count > 1 {
                        Divider()

                        VStack(spacing: 0) {
                            ForEach(Array(items.dropFirst().enumerated()), id: \.offset) { index, item in
                                if index > 0 { Divider() }
                                NativeRecordRow(
                                    title: item.title,
                                    subtitle: item.detail,
                                    metadata: item.metadata,
                                    systemImage: item.systemImage
                                )
                            }
                        }
                    }
                } else {
                    RecordsEmptyState(title: emptyTitle, detail: emptyDetail)
                }
            }
        } label: {
            HStack(alignment: .firstTextBaseline) {
                Text(title)
                Spacer()
                Text("\(items.count)")
                    .font(.caption.monospacedDigit().weight(.semibold))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(.quaternary, in: Capsule())
            }
        }
    }
}

private struct LatestRecordSpotlight: View {
    let record: StreamRecord

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            RoundedRectangle(cornerRadius: 2, style: .continuous)
                .fill(MonitorTheme.accent)
                .frame(width: 3)

            Image(systemName: record.systemImage)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(MonitorTheme.accent)
                .frame(width: 24)

            VStack(alignment: .leading, spacing: 7) {
                HStack(alignment: .firstTextBaseline, spacing: 10) {
                    Text(record.title.monitorReadable.monitorLimited(to: 140))
                        .font(.headline.weight(.semibold))
                        .lineLimit(2)

                    Spacer(minLength: 10)

                    Text(record.metadata.monitorReadable.monitorLimited(to: 34))
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 4)
                        .background(.quaternary, in: Capsule())
                }

                Text(record.detail.monitorReadable.monitorLimited(to: 260))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 4)
    }
}

private struct RecordsEmptyState: View {
    let title: String
    let detail: String

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "tray")
                .font(.system(size: 17, weight: .medium))
                .foregroundStyle(.secondary)
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.callout.weight(.medium))
                Text(detail)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 8)
    }
}

private struct SignalSection: View {
    let title: String
    let items: [String]
    let limit: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text(title)
                .font(.headline)

            if items.isEmpty {
                Text("No signals yet.")
                    .foregroundStyle(.secondary)
            } else {
                ForEach(Array(items.prefix(limit).enumerated()), id: \.offset) { _, item in
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Image(systemName: "circle.fill")
                            .font(.system(size: 5))
                            .foregroundStyle(.tertiary)
                        Text(item.monitorReadable.monitorLimited(to: 180))
                            .foregroundStyle(.secondary)
                            .font(.callout)
                            .lineLimit(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
        }
    }
}

private struct StreamRecord: Identifiable {
    let id = UUID()
    let title: String
    let detail: String
    let metadata: String
    let systemImage: String
}

private struct StreamListView: View {
    let items: [StreamRecord]

    var body: some View {
        VStack(spacing: 0) {
            if items.isEmpty {
                Text("No records in this stream yet.")
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 8)
            } else {
                ForEach(Array(items.enumerated()), id: \.offset) { index, item in
                    if index > 0 { Divider() }
                    NativeRecordRow(
                        title: item.title,
                        subtitle: item.detail,
                        metadata: item.metadata,
                        systemImage: item.systemImage
                    )
                }
            }
        }
    }
}

private struct NativeHeader: View {
    let title: String
    let subtitle: String
    let systemImage: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: systemImage)
                .font(.system(size: 28, weight: .regular))
                .foregroundStyle(MonitorTheme.accent)
                .frame(width: 36)

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.largeTitle.weight(.semibold))
                    .lineLimit(1)
                    .minimumScaleFactor(0.8)
                Text(subtitle.monitorLimited(to: 240))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.bottom, 2)
    }
}

private struct LabeledStatusRow: View {
    let label: String
    let value: String
    let detail: String

    var body: some View {
        LabeledContent {
            VStack(alignment: .trailing, spacing: 2) {
                Text(value.isEmpty ? "Unknown" : value)
                    .font(.body.weight(.medium))
                Text(detail.isEmpty ? "No detail" : detail)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
        } label: {
            Text(label)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 8)
    }
}

private struct NativeRecordRow: View {
    let title: String
    let subtitle: String
    let metadata: String
    let systemImage: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: systemImage)
                .font(.system(size: 16, weight: .regular))
                .foregroundStyle(.secondary)
                .frame(width: 20)

            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline) {
                Text(title.monitorLimited(to: 120))
                        .font(.body.weight(.medium))
                        .lineLimit(2)
                    Spacer()
                    Text(metadata.monitorLimited(to: 34))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }

                Text(subtitle.monitorReadable.monitorLimited(to: 220))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(.vertical, 9)
    }
}
