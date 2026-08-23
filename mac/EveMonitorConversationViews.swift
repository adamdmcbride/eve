import SwiftUI

struct ChatDetailView: View {
    @EnvironmentObject private var model: EveMonitorModel
    @State private var draft = ""
    @FocusState private var composerFocused: Bool

    private let suggestions = [
        "What are you doing right now?",
        "What needs my attention?",
        "What evidence changed your mind?"
    ]

    var body: some View {
        ScrollView {
            HStack(alignment: .top, spacing: 22) {
                VStack(alignment: .leading, spacing: 22) {
                    ChatHeader()

                    ChatLogView(messages: model.chatMessages, isTyping: model.isSendingChatMessage)

                    ChatComposer(
                        draft: $draft,
                        suggestions: suggestions,
                        isSending: model.isSendingChatMessage,
                        contextLabel: "Attached context: Now state, selected evidence, model lane voices",
                        onSuggestion: { suggestion in
                            draft = suggestion
                            composerFocused = true
                        },
                        onSend: sendDraft
                    )
                    .focused($composerFocused)
                }
                .frame(maxWidth: 760, alignment: .topLeading)

                ChatInspector()
                    .frame(width: 300)
            }
            .padding(.horizontal, 28)
            .padding(.vertical, 24)
            .frame(maxWidth: 1120, alignment: .topLeading)
        }
        .groupBoxStyle(MonitorPanelGroupBoxStyle())
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }

    private func sendDraft() {
        let text = draft.monitorTrimmed
        guard !text.isEmpty else { return }
        draft = ""
        composerFocused = true
        Task {
            await model.sendChatMessage(text)
        }
    }
}
struct FromEveDetailView: View {
    @EnvironmentObject private var model: EveMonitorModel
    @State private var draft = ""
    @FocusState private var composerFocused: Bool

    private let suggestions = [
        "I'm here.",
        "Tell me more.",
        "What do you need from me?"
    ]

    var body: some View {
        HStack(alignment: .top, spacing: 22) {
            VStack(alignment: .leading, spacing: 18) {
                FromEveHeader()

                FromEveCurrentThreadPanel()

                ChatComposer(
                    draft: $draft,
                    suggestions: suggestions,
                    isSending: model.isSendingPersonalMessage,
                    contextLabel: "Replies stay inside the Eve-started personal thread",
                    onSuggestion: { suggestion in
                        draft = suggestion
                        composerFocused = true
                    },
                    onSend: sendDraft
                )
                .focused($composerFocused)

                if let error = model.personalChatError ?? model.eveInitiatedError {
                    Label(error, systemImage: "exclamationmark.triangle")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(MonitorTheme.amber)
                }
            }
            .frame(maxWidth: 760, alignment: .topLeading)

            VStack(alignment: .leading, spacing: 14) {
                FromEveSignalPanel()
                FromEveThreadListPanel(messages: uniqueFromEveThreads(model.eveInitiatedMessages))
            }
            .frame(width: 320)
        }
        .groupBoxStyle(MonitorPanelGroupBoxStyle())
        .task {
            await model.refreshEveInitiatedMessages()
        }
    }

    private func sendDraft() {
        let text = draft.monitorTrimmed
        guard !text.isEmpty else { return }
        draft = ""
        composerFocused = true
        Task {
            await model.sendPersonalReply(text)
        }
    }
}

private struct FromEveCurrentThreadPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .top, spacing: 12) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(model.personalConversationTitle)
                            .font(.title2.weight(.semibold))
                            .lineLimit(2)
                            .fixedSize(horizontal: false, vertical: true)

                        Text(model.personalConversationDetail)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }

                    Spacer(minLength: 12)

                    StoryChip(
                        label: model.personalChatStatus,
                        systemImage: model.isSendingPersonalMessage ? "hourglass" : "bubble.left.and.bubble.right",
                        tint: model.isSendingPersonalMessage ? MonitorTheme.amber : MonitorTheme.accent
                    )
                }

                Divider()

                if model.personalChatMessages.isEmpty {
                    FromEveQuietState()
                } else {
                    ChatLogView(
                        messages: model.personalChatMessages,
                        isTyping: model.isSendingPersonalMessage
                    )
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } label: {
            HStack(alignment: .firstTextBaseline) {
                Label("Current Thread", systemImage: "bubble.left.and.bubble.right")
                Spacer()
                Text(model.personalConversationBadgeStatus)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(fromEveSilenceTint(model))
            }
        }
    }
}

private struct FromEveQuietState: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            ZStack {
                Circle()
                    .fill(fromEveSilenceTint(model).opacity(0.14))
                Image(systemName: fromEveSilenceIcon(model))
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(fromEveSilenceTint(model))
            }
            .frame(width: 38, height: 38)

            VStack(alignment: .leading, spacing: 7) {
                Text(model.personalConversationQuietTitle)
                    .font(.title3.weight(.semibold))
                Text(model.personalConversationQuietDetail)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(model.personalConversationTimingDetail)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }
        }
        .padding(.vertical, 6)
    }
}

private struct FromEveSignalPanel: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        GroupBox("Eve's Signal") {
            VStack(alignment: .leading, spacing: 13) {
                HStack(alignment: .top, spacing: 11) {
                    ZStack {
                        Circle()
                            .fill(fromEveSilenceTint(model).opacity(0.14))
                        Image(systemName: fromEveSilenceIcon(model))
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(fromEveSilenceTint(model))
                    }
                    .frame(width: 34, height: 34)

                    VStack(alignment: .leading, spacing: 5) {
                        Text(model.personalConversationQuietTitle)
                            .font(.headline)
                        Text(model.personalConversationQuietDetail.monitorReadable.monitorLimited(to: 150))
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                Divider()

                VStack(spacing: 0) {
                    FromEveMetricRow(title: "Status", value: model.personalConversationBadgeStatus, detail: model.personalConversationState?.source ?? "local")
                    Divider()
                    FromEveMetricRow(title: "Unread", value: "\(model.unreadEveInitiatedCount)", detail: "Personal threads")
                    Divider()
                    FromEveMetricRow(title: "Cadence", value: cadenceValue, detail: model.personalConversationTimingDetail)
                }
            }
        }
    }

    private var cadenceValue: String {
        if let minutes = model.personalConversationState?.minimumGapMinutes, minutes > 0 {
            return "\(minutes)m"
        }
        return "Live"
    }
}

private struct FromEveMetricRow: View {
    let title: String
    let value: String
    let detail: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.callout.weight(.medium))
                Text(detail.monitorReadable.monitorLimited(to: 72))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            Spacer(minLength: 10)

            Text(value.monitorReadable.monitorLimited(to: 28))
                .font(.callout.monospacedDigit().weight(.semibold))
                .multilineTextAlignment(.trailing)
                .lineLimit(1)
                .minimumScaleFactor(0.75)
        }
        .padding(.vertical, 8)
    }
}

private struct FromEveThreadListPanel: View {
    @EnvironmentObject private var model: EveMonitorModel
    let messages: [MonitorMessageRecord]

    var body: some View {
        GroupBox {
            VStack(spacing: 0) {
                if messages.isEmpty {
                    FromEveQuietState()
                } else {
                    ForEach(Array(messages.prefix(10).enumerated()), id: \.element.stableID) { index, message in
                        if index > 0 { Divider() }
                        Button {
                            Task { await model.selectPersonalConversation(from: message) }
                        } label: {
                            FromEveMessageRow(
                                message: message,
                                isSelected: message.threadId == model.personalChatThreadID
                            )
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        } label: {
            HStack(alignment: .firstTextBaseline) {
                Text("Threads Eve Started")
                Spacer()
                Text("\(messages.count)")
                    .font(.caption.monospacedDigit().weight(.semibold))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(.quaternary, in: Capsule())
            }
        }
    }
}

private struct FromEveHeader: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        HStack(alignment: .top, spacing: 16) {
            ZStack {
                Circle()
                    .fill(MonitorTheme.accent.opacity(0.13))
                    .frame(width: 52, height: 52)
                Image(systemName: "sparkles")
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundStyle(MonitorTheme.accent)
            }

            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .firstTextBaseline, spacing: 12) {
                    Text("From Eve")
                        .font(.title.weight(.semibold))
                        .lineLimit(1)
                        .minimumScaleFactor(0.78)

                    StoryChip(
                        label: model.eveInitiatedStatus,
                        systemImage: model.unreadEveInitiatedCount > 0 ? "bell.badge" : "bell",
                        tint: model.unreadEveInitiatedCount > 0 ? MonitorTheme.amber : MonitorTheme.accent
                    )
                }

                Text("A personal line for grounded notes, questions, and continuity.")
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 10) {
                    StoryChip(
                        label: model.alwaysAwakeStatus,
                        systemImage: model.isPoweredOff ? "power" : (model.isEnsuringEveAwake ? "hourglass" : "sun.max"),
                        tint: model.isPoweredOff ? .secondary : (model.payload?.status?.daemon?.awake == true ? MonitorTheme.accent : MonitorTheme.amber)
                    )
                    StoryChip(
                        label: model.daemonTitle,
                        systemImage: "power.circle",
                        tint: model.isPoweredOff ? .secondary : (model.payload?.status?.daemon?.awake == true ? MonitorTheme.accent : MonitorTheme.amber)
                    )
                }

                Text(model.alwaysAwakeDetail.monitorReadable.monitorLimited(to: 180))
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }
}

private struct FromEveSpotlightMessage: View {
    let message: MonitorMessageRecord

    var body: some View {
        GroupBox {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .firstTextBaseline) {
                    Label(fromEveKindLabel(message), systemImage: fromEveMessageIcon(message))
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(fromEveMessageTint(message))
                    Spacer()
                    Text(fromEveMessageTime(message))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }

                Text((message.subject ?? "From Eve").monitorReadable)
                    .font(.title3.weight(.semibold))
                    .fixedSize(horizontal: false, vertical: true)

                Text((message.body ?? message.preview ?? "").monitorReadable)
                    .font(.body)
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)

                HStack(spacing: 8) {
                    StoryChip(label: (message.status ?? "unread").capitalized, systemImage: "circle", tint: (message.status ?? "") == "unread" ? MonitorTheme.amber : .secondary)
                    StoryChip(label: fromEveKindLabel(message), systemImage: fromEveMessageIcon(message), tint: fromEveMessageTint(message))
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
    }
}

private struct FromEveMessageRow: View {
    let message: MonitorMessageRecord
    let isSelected: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            ZStack {
                Circle()
                    .fill(fromEveMessageTint(message).opacity(isSelected ? 0.18 : 0.11))
                Image(systemName: fromEveMessageIcon(message))
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(fromEveMessageTint(message))
            }
            .frame(width: 26, height: 26)

            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text((message.subject ?? "From Eve").monitorReadable.monitorLimited(to: 96))
                        .font(.callout.weight(.semibold))
                        .lineLimit(1)
                    Spacer()
                    if (message.status ?? "").lowercased() == "unread" {
                        Circle()
                            .fill(MonitorTheme.amber)
                            .frame(width: 7, height: 7)
                    }
                    Text(fromEveMessageTime(message))
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }

                Text((message.body ?? message.preview ?? "").monitorReadable.monitorLimited(to: 220))
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(3)
            }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 9)
        .background(isSelected ? MonitorTheme.accent.opacity(0.10) : Color.clear, in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        .overlay {
            if isSelected {
                RoundedRectangle(cornerRadius: 8, style: .continuous)
                    .strokeBorder(MonitorTheme.accent.opacity(0.18))
            }
        }
        .contentShape(Rectangle())
    }
}

private func uniqueFromEveThreads(_ messages: [MonitorMessageRecord]) -> [MonitorMessageRecord] {
    var seen = Set<String>()
    var unique: [MonitorMessageRecord] = []
    for message in messages {
        let key = message.threadId ?? message.id ?? message.stableID
        guard !seen.contains(key) else { continue }
        seen.insert(key)
        unique.append(message)
    }
    return unique
}

private func fromEveMessageTime(_ message: MonitorMessageRecord) -> String {
    MonitorFormatters.dateTime(message.timestamp ?? message.updatedAt)
}

private func fromEveKindLabel(_ message: MonitorMessageRecord) -> String {
    let kind = (message.kind ?? "").lowercased()
    if kind.contains("outreach") { return "Outreach" }
    if kind.contains("proposal") { return "Proposal" }
    if kind.contains("reflection") { return "Reflection" }
    if kind.contains("upgrade") { return "Upgrade" }
    if kind.contains("update") { return "Update" }
    return "Message"
}

private func fromEveMessageIcon(_ message: MonitorMessageRecord) -> String {
    let kind = (message.kind ?? "").lowercased()
    if kind.contains("outreach") { return "sparkles" }
    if kind.contains("proposal") { return "doc.text.magnifyingglass" }
    if kind.contains("reflection") { return "moon.stars" }
    if kind.contains("upgrade") { return "arrow.triangle.2.circlepath" }
    if kind.contains("update") { return "bell" }
    return "bubble.left"
}

private func fromEveMessageTint(_ message: MonitorMessageRecord) -> Color {
    let kind = (message.kind ?? "").lowercased()
    if kind.contains("outreach") { return MonitorTheme.accent }
    if kind.contains("proposal") { return MonitorTheme.teal }
    if kind.contains("reflection") { return MonitorTheme.blue }
    if kind.contains("upgrade") { return MonitorTheme.amber }
    if (message.status ?? "").lowercased() == "unread" { return MonitorTheme.amber }
    return .secondary
}

@MainActor private func fromEveSilenceIcon(_ model: EveMonitorModel) -> String {
    switch (model.personalConversationState?.status ?? "").lowercased() {
    case "sent", "open":
        return "bubble.left.and.bubble.right.fill"
    case "quiet":
        return "ear"
    case "waiting":
        return "clock"
    case "blocked", "failed", "offline":
        return "exclamationmark.triangle"
    default:
        return "sparkles"
    }
}

@MainActor private func fromEveSilenceTint(_ model: EveMonitorModel) -> Color {
    switch (model.personalConversationState?.status ?? "").lowercased() {
    case "sent", "open":
        return MonitorTheme.accent
    case "quiet":
        return MonitorTheme.blue
    case "waiting":
        return MonitorTheme.amber
    case "blocked", "failed", "offline":
        return MonitorTheme.red
    default:
        return MonitorTheme.accent
    }
}

private struct ChatHeader: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Label("Conversation", systemImage: "bubble.left.and.bubble.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(MonitorTheme.accent)

            Text("Talk with Eve")
                .font(.title.weight(.semibold))
                .lineLimit(1)
                .minimumScaleFactor(0.78)

            Text("Ask for the current thread, the next decision, or the evidence behind what Eve is doing. The conversation stays attached to this monitor state.")
                .font(.callout.weight(.medium))
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 10) {
                StoryChip(label: model.chatStatus, systemImage: model.isSendingChatMessage ? "hourglass" : "checkmark.circle", tint: model.isSendingChatMessage ? MonitorTheme.amber : MonitorTheme.accent)
                StoryChip(label: model.chatThreadID == nil ? "new thread" : "thread active", systemImage: "text.bubble", tint: MonitorTheme.teal)
            }
        }
    }
}

private struct ChatLogView: View {
    let messages: [MonitorChatMessage]
    let isTyping: Bool

    var body: some View {
        VStack(spacing: 14) {
            ForEach(messages) { message in
                ChatBubble(message: message)
                    .id(message.id)
            }

            if isTyping {
                ChatTypingRow()
            }
        }
        .padding(.vertical, 4)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private struct ChatBubble: View {
    let message: MonitorChatMessage

    private var isUser: Bool {
        message.role == .user
    }

    private var alignment: HorizontalAlignment {
        isUser ? .trailing : .leading
    }

    private var bubbleColor: Color {
        switch message.role {
        case .user:
            return MonitorTheme.accent
        case .eve:
            return Color(nsColor: .textBackgroundColor)
        case .system:
            return MonitorTheme.amber.opacity(0.12)
        }
    }

    private var foregroundColor: Color {
        isUser ? .white : .primary
    }

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            if isUser { Spacer(minLength: 80) }

            if !isUser {
                ChatAvatar(role: message.role)
            }

            Group {
                if message.role == .eve {
                    EveFiveLaneBubble(message: message)
                } else {
                    VStack(alignment: alignment, spacing: 5) {
                        Text(message.metadata)
                            .font(.caption2.weight(.semibold))
                            .foregroundStyle(isUser ? .white.opacity(0.72) : .secondary)
                            .textCase(.uppercase)

                        Text(message.body.monitorReadable)
                            .font(.callout.weight(.medium))
                            .foregroundStyle(foregroundColor)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    .padding(.horizontal, 15)
                    .padding(.vertical, 12)
                    .background(bubbleColor, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
                    .overlay {
                        if !isUser {
                            RoundedRectangle(cornerRadius: 15, style: .continuous)
                                .stroke(MonitorTheme.divider, lineWidth: 1)
                        }
                    }
                }
            }
            .frame(maxWidth: message.role == .eve ? 700 : 640, alignment: isUser ? .trailing : .leading)

            if isUser {
                ChatAvatar(role: message.role)
            } else {
                Spacer(minLength: 80)
            }
        }
        .frame(maxWidth: .infinity, alignment: isUser ? .trailing : .leading)
    }
}

private struct EveFiveLaneBubble: View {
    let message: MonitorChatMessage

    private var voices: [MonitorChatLaneVoice] {
        message.laneVoices.isEmpty ? MonitorChatLaneVoice.welcome : message.laneVoices
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .center) {
                Text(message.metadata)
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)

                Spacer(minLength: 12)

                Label(message.laneBadge, systemImage: "cpu")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(MonitorTheme.accent)
                    .labelStyle(.titleAndIcon)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(MonitorTheme.accent.opacity(0.11), in: Capsule())
            }

            VStack(alignment: .leading, spacing: 5) {
                Text(message.sharedReplyLabel)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)
                    .textCase(.uppercase)

                Text(message.body.monitorReadable)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(.primary)
                    .fixedSize(horizontal: false, vertical: true)
            }

            VStack(spacing: 0) {
                ForEach(Array(voices.enumerated()), id: \.element.id) { index, voice in
                    if index > 0 {
                        Divider()
                    }
                    ChatLaneVoiceRow(voice: voice)
                }
            }
            .background(.quaternary.opacity(0.22), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .strokeBorder(MonitorTheme.divider)
            }
        }
        .padding(.horizontal, 15)
        .padding(.vertical, 13)
        .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 15, style: .continuous)
                .stroke(MonitorTheme.divider, lineWidth: 1)
        }
    }
}

private struct ChatLaneVoiceRow: View {
    let voice: MonitorChatLaneVoice

    var body: some View {
        HStack(alignment: .top, spacing: 11) {
            ZStack {
                Circle()
                    .fill(chatLaneTint(voice.id).opacity(0.14))
                    .frame(width: 26, height: 26)
                Image(systemName: chatLaneSymbol(voice.id))
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(chatLaneTint(voice.id))
            }

            VStack(alignment: .leading, spacing: 4) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(voice.title)
                        .font(.callout.weight(.semibold))
                        .lineLimit(1)
                    Text(voice.detail.monitorReadable.monitorLimited(to: 42))
                        .font(.caption.monospacedDigit().weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }

                Text(voice.body.monitorReadable)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
    }
}

private func chatLaneTint(_ laneID: String) -> Color {
    switch laneID.lowercased() {
    case "fast":
        return MonitorTheme.accent
    case "deep":
        return MonitorTheme.blue
    case "observer":
        return MonitorTheme.teal
    case "planner":
        return MonitorTheme.amber
    case "relationship":
        return Color(nsColor: .systemPink)
    default:
        return .secondary
    }
}

private func chatLaneSymbol(_ laneID: String) -> String {
    switch laneID.lowercased() {
    case "fast":
        return "bolt.fill"
    case "deep":
        return "brain.head.profile"
    case "observer":
        return "eye"
    case "planner":
        return "checklist"
    case "relationship":
        return "heart"
    default:
        return "circle.grid.2x2"
    }
}

private struct ChatAvatar: View {
    let role: MonitorChatRole

    private var label: String {
        switch role {
        case .eve: return "E"
        case .user: return "A"
        case .system: return "!"
        }
    }

    private var tint: Color {
        switch role {
        case .eve: return MonitorTheme.accent
        case .user: return Color.secondary.opacity(0.24)
        case .system: return MonitorTheme.amber
        }
    }

    var body: some View {
        Text(label)
            .font(.caption.weight(.bold))
            .foregroundStyle(role == .user ? Color.secondary : Color.white)
            .frame(width: 28, height: 28)
            .background(tint, in: Circle())
    }
}

private struct ChatTypingRow: View {
    private let lanes = [
        ("fast", "Fast"),
        ("deep", "Deep"),
        ("observer", "Observer"),
        ("planner", "Planner"),
        ("relationship", "Relationship")
    ]

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            ChatAvatar(role: .eve)
            VStack(alignment: .leading, spacing: 10) {
                Text("Eve's five lanes are forming one reply")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(.secondary)

                HStack(spacing: 6) {
                    ForEach(lanes, id: \.0) { lane in
                        HStack(spacing: 4) {
                            Circle()
                                .fill(chatLaneTint(lane.0))
                                .frame(width: 6, height: 6)
                            Text(lane.1)
                                .lineLimit(1)
                        }
                        .font(.caption2.weight(.medium))
                        .padding(.horizontal, 7)
                        .padding(.vertical, 4)
                        .background(.quaternary, in: Capsule())
                    }
                }
            }
            .padding(.horizontal, 13)
            .padding(.vertical, 10)
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(MonitorTheme.divider, lineWidth: 1)
            }
            Spacer(minLength: 80)
        }
    }
}

private struct ChatComposer: View {
    @Binding var draft: String
    let suggestions: [String]
    let isSending: Bool
    let contextLabel: String
    let onSuggestion: (String) -> Void
    let onSend: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                ForEach(suggestions, id: \.self) { suggestion in
                    Button(suggestion) {
                        onSuggestion(suggestion)
                    }
                    .buttonStyle(.borderless)
                    .font(.caption.weight(.medium))
                    .padding(.horizontal, 9)
                    .padding(.vertical, 5)
                    .background(.quaternary.opacity(0.85), in: Capsule())
                }
            }

            VStack(spacing: 0) {
                TextEditor(text: $draft)
                    .font(.callout)
                    .scrollContentBackground(.hidden)
                    .frame(minHeight: 76, maxHeight: 128)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 8)

                Divider()

                HStack {
                    Text(contextLabel)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                    Spacer()
                    Button {
                        onSend()
                    } label: {
                        Label(isSending ? "Sending" : "Send", systemImage: isSending ? "hourglass" : "paperplane.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(isSending || draft.monitorTrimmed.isEmpty)
                    .keyboardShortcut(.return, modifiers: [.command])
                }
                .padding(.horizontal, 12)
                .padding(.vertical, 9)
            }
            .background(.thinMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay {
                RoundedRectangle(cornerRadius: 14, style: .continuous)
                    .stroke(MonitorTheme.divider, lineWidth: 1)
            }
        }
    }
}

private struct ChatInspector: View {
    @EnvironmentObject private var model: EveMonitorModel

    var body: some View {
        GroupBox("How Eve Answers") {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .top, spacing: 11) {
                    ZStack {
                        Circle()
                            .fill(MonitorTheme.accent.opacity(0.13))
                        Image(systemName: "bubble.left.and.bubble.right")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(MonitorTheme.accent)
                    }
                    .frame(width: 34, height: 34)

                    VStack(alignment: .leading, spacing: 5) {
                        Text("Local, monitor-aware")
                            .font(.headline)
                        Text("Replies use the Eve runtime and the state this app is already showing.")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }

                if let error = model.chatError {
                    Label(error, systemImage: "exclamationmark.triangle")
                        .font(.caption.weight(.medium))
                        .foregroundStyle(MonitorTheme.amber)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Divider()

                VStack(alignment: .leading, spacing: 0) {
                    ChatContextRow(title: "Lanes", detail: "Five logical faculties form one Eve reply; the live topology uses three resident model substrates.")
                    ChatContextRow(title: "Thread", detail: model.chatThreadID == nil ? "A monitor conversation starts on first send." : "Thread \(model.chatThreadID?.monitorLimited(to: 18) ?? "active")")
                    ChatContextRow(title: "Evidence", detail: "Current workspace, model activity, resources, and selected state are attached.")
                    ChatContextRow(title: "Boundaries", detail: "Uncertainty should be stated instead of smoothed over.")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }
}

private struct ChatContextRow: View {
    let title: String
    let detail: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .textCase(.uppercase)
            Text(detail)
                .font(.callout)
                .foregroundStyle(.primary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .overlay(alignment: .bottom) {
            Rectangle()
                .fill(MonitorTheme.divider)
                .frame(height: 1)
        }
    }
}
