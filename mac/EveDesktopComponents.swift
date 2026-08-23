import AppKit
import Combine
import Foundation
import SwiftUI

struct WorkspacePickerView: View {
    @Binding var selectedTab: WorkspaceTab

    var body: some View {
        HStack(spacing: 6) {
            ForEach(WorkspaceTab.allCases) { tab in
                Button {
                    selectedTab = tab
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: tab.iconName)
                        Text(tab.displayTitle)
                    }
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(selectedTab == tab ? EveTheme.textPrimary : EveTheme.textSecondary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 7)
                    .background(
                        RoundedRectangle(cornerRadius: 11, style: .continuous)
                            .fill(selectedTab == tab ? EveTheme.surfaceRaised : Color.clear)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 11, style: .continuous)
                            .stroke(selectedTab == tab ? EveTheme.divider : Color.clear, lineWidth: 1)
                    )
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(EveTheme.surfaceSoft, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 13, style: .continuous)
                .stroke(EveTheme.divider, lineWidth: 1)
        )
    }
}

struct SidebarCardView: View {
    let title: String
    let bodyText: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(EveTheme.textTertiary)
                .textCase(.uppercase)
            Text(bodyText)
                .font(.system(size: 12.5, weight: .medium))
                .foregroundStyle(EveTheme.textSecondary)
                .lineLimit(2)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 11)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(EveTheme.surfaceSoft, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(EveTheme.divider, lineWidth: 1)
        )
    }
}

struct SidebarSectionLabelView: View {
    let title: String
    let trailing: String?

    var body: some View {
        HStack {
            Text(title)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(EveTheme.textTertiary)
                .textCase(.uppercase)
            Spacer()
            if let trailing, !trailing.isEmpty {
                Text(trailing)
                    .font(.system(size: 10.5, weight: .medium))
                    .foregroundStyle(EveTheme.textTertiary)
            }
        }
    }
}

struct ThreadRowView: View {
    let displayTitle: String
    let thread: ThreadSummary
    let metaLine: String
    let statusLabel: String
    let agentLine: String?
    let isSelected: Bool
    @State private var isHovered = false

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .center, spacing: 8) {
                Text(displayTitle)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(EveTheme.textPrimary)
                    .lineLimit(1)

                Spacer(minLength: 8)

                if thread.unreadCount > 0 {
                    Text("\(thread.unreadCount)")
                        .font(.system(size: 10.5, weight: .semibold))
                        .foregroundStyle(EveTheme.textPrimary)
                        .padding(.horizontal, 7)
                        .padding(.vertical, 2)
                        .background(EveTheme.accent.opacity(0.28), in: Capsule())
                } else {
                    Text(statusLabel)
                        .font(.system(size: 10.5, weight: .medium))
                        .foregroundStyle(EveTheme.textTertiary)
                        .lineLimit(1)
                }
            }

            if let agentLine, !agentLine.isEmpty {
                Text(agentLine)
                    .font(.system(size: 10.5, weight: .medium))
                    .foregroundStyle(EveTheme.textTertiary)
                    .lineLimit(1)
            }

            Text(thread.latestPreview)
                .font(.system(size: 12.25))
                .foregroundStyle(EveTheme.textSecondary)
                .lineLimit(1)

            Text(metaLine)
                .font(.system(size: 10.5))
                .foregroundStyle(EveTheme.textTertiary)
                .lineLimit(1)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(isSelected ? EveTheme.surfaceRaised.opacity(0.92) : (isHovered ? EveTheme.surfaceSoft : Color.clear))
        )
        .contentShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .onHover { hovering in
            withAnimation(.easeOut(duration: 0.12)) {
                isHovered = hovering
            }
        }
    }
}

struct SidebarNavigationRowView: View {
    let title: String
    var subtitle: String? = nil
    let systemImage: String
    let isSelected: Bool
    let trailingText: String?
    let action: () -> Void
    @State private var isHovered = false

    var body: some View {
        Button(action: action) {
            HStack(spacing: 10) {
                Image(systemName: systemImage)
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(isSelected ? EveTheme.accent : EveTheme.textSecondary)
                    .frame(width: 18)

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.system(size: 14.5, weight: isSelected ? .semibold : .medium))
                        .foregroundStyle(isSelected ? EveTheme.accent : EveTheme.textPrimary)

                    if let subtitle, !subtitle.isEmpty {
                        Text(subtitle)
                            .font(.system(size: 11.5, weight: .medium))
                            .foregroundStyle(EveTheme.textTertiary)
                            .lineLimit(1)
                    }
                }

                Spacer(minLength: 8)

                if let trailingText, !trailingText.isEmpty {
                    Text(trailingText)
                        .font(.system(size: 11.5, weight: .medium))
                        .foregroundStyle(EveTheme.textTertiary)
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(
                RoundedRectangle(cornerRadius: 13, style: .continuous)
                    .fill(isSelected ? EveTheme.surfaceRaised : (isHovered ? EveTheme.surfaceSoft : Color.clear))
            )
        }
        .buttonStyle(.plain)
        .onHover { hovering in
            withAnimation(.easeOut(duration: 0.12)) {
                isHovered = hovering
            }
        }
    }
}

struct ThoughtPreviewRowView: View {
    let thought: ThoughtEntry
    let timestamp: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(timestamp)
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(EveTheme.textTertiary)
            Text(thought.preview)
                .font(.system(size: 12))
                .foregroundStyle(EveTheme.textSecondary)
                .lineLimit(4)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(EveTheme.surfaceSoft, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

struct EmptyStateView: View {
    let tab: WorkspaceTab

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: tab.iconName)
                .font(.system(size: 34))
                .foregroundStyle(EveTheme.textSecondary)
            Text(tab.emptyTitle)
                .font(.title3.weight(.semibold))
                .foregroundStyle(EveTheme.textPrimary)
            Text(tab.emptyDetail)
                .font(.system(size: 14))
                .foregroundStyle(EveTheme.textSecondary)
                .multilineTextAlignment(.center)
                .frame(maxWidth: 360)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct ParticipantChipView: View {
    let label: String

    var body: some View {
        Text(label)
            .font(.system(size: 11, weight: .medium))
            .foregroundStyle(EveTheme.textSecondary)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(EveTheme.surface, in: Capsule())
            .overlay(Capsule().stroke(EveTheme.divider, lineWidth: 1))
    }
}

struct GlassIconButton: View {
    let systemImage: String
    let tooltip: String
    let disabled: Bool
    let action: () -> Void
    @State private var isHovered = false

    init(systemImage: String, tooltip: String, disabled: Bool = false, action: @escaping () -> Void) {
        self.systemImage = systemImage
        self.tooltip = tooltip
        self.disabled = disabled
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(disabled ? EveTheme.textTertiary : EveTheme.textPrimary)
                .frame(width: 28, height: 28)
        }
        .frame(width: 28, height: 28)
        .contentShape(Circle())
        .background(
            Circle()
                .fill(isHovered && !disabled ? EveTheme.surfaceRaised : Color.clear)
        )
        .buttonStyle(.plain)
        .disabled(disabled)
        .help(tooltip)
        .onHover { hovering in
            withAnimation(.easeOut(duration: 0.12)) {
                isHovered = hovering
            }
        }
    }
}

struct GlassActionClusterView<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        HStack(spacing: 2) {
            content
        }
    }
}

struct AttachmentChipView: View {
    let name: String
    let detail: String
    var removeAction: (() -> Void)? = nil

    var body: some View {
        HStack(spacing: 7) {
            Image(systemName: "doc")
                .font(.system(size: 11, weight: .medium))
                .foregroundStyle(EveTheme.accent)

            VStack(alignment: .leading, spacing: 1) {
                Text(name)
                    .font(.system(size: 11.5, weight: .semibold))
                    .foregroundStyle(EveTheme.textPrimary)
                    .lineLimit(1)
                if !detail.isEmpty {
                    Text(detail)
                        .font(.system(size: 10.5, weight: .medium))
                        .foregroundStyle(EveTheme.textTertiary)
                        .lineLimit(1)
                }
            }

            if let removeAction {
                Button(action: removeAction) {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(EveTheme.textTertiary)
                }
                .buttonStyle(.plain)
                .help("Remove attachment")
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(EveTheme.surfaceSoft, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(EveTheme.divider, lineWidth: 1)
        )
    }
}

struct ConversationAttachmentShelfView: View {
    let attachments: [MessageAttachmentRecord]

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack(spacing: 8) {
                Image(systemName: "tray.full")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(EveTheme.accent)
                Text("\(attachments.count) local file\(attachments.count == 1 ? "" : "s") in this thread")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(EveTheme.textSecondary)
                Spacer(minLength: 8)
                Text("not memory unless Eve proposes it")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(EveTheme.textTertiary)
                    .lineLimit(1)
            }

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(attachments) { attachment in
                        AttachmentChipView(
                            name: attachment.name,
                            detail: shelfDetail(attachment)
                        )
                    }
                }
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(EveTheme.surfaceSoft, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(EveTheme.divider, lineWidth: 1)
        )
    }

    private func shelfDetail(_ attachment: MessageAttachmentRecord) -> String {
        var parts: [String] = []
        if let typeLabel = attachment.typeLabel, !typeLabel.isEmpty {
            parts.append(typeLabel)
        }
        if let byteCount = attachment.byteCount {
            parts.append(ByteCountFormatter.string(fromByteCount: byteCount, countStyle: .file))
        }
        if let status = attachment.extractionStatus, !status.isEmpty {
            parts.append(status == "metadata_only" ? "metadata only" : status.replacingOccurrences(of: "_", with: " "))
        }
        return parts.joined(separator: " · ")
    }
}

private struct MessageAttachmentDisplay: Hashable {
    let name: String
    let detail: String
}

struct MessageBubbleView: View {
    let message: MessageRecord
    let senderLabel: String
    let timestamp: String

    private var isEve: Bool { message.sender == "eve" }
    private let attachmentMarker = "\n\nAttached files for Eve to inspect:\n"

    private var displayBody: String {
        guard let range = message.body.range(of: attachmentMarker) else {
            return message.body
        }
        return String(message.body[..<range.lowerBound])
    }

    private var attachments: [MessageAttachmentDisplay] {
        let structured = message.attachments.map { attachment in
            MessageAttachmentDisplay(
                name: attachment.name,
                detail: attachmentDetail(attachment)
            )
        }
        if !structured.isEmpty {
            return structured
        }
        guard let range = message.body.range(of: attachmentMarker) else { return [] }
        let section = message.body[range.upperBound...]
        return section
            .split(separator: "\n")
            .compactMap { line -> MessageAttachmentDisplay? in
                let text = line.trimmingCharacters(in: .whitespacesAndNewlines)
                guard text.hasPrefix("- ") else { return nil }
                let trimmed = String(text.dropFirst(2))
                let name = trimmed.components(separatedBy: " (").first ?? trimmed
                var detail = ""
                if let open = trimmed.firstIndex(of: "("), let close = trimmed[open...].firstIndex(of: ")") {
                    detail = String(trimmed[trimmed.index(after: open)..<close])
                }
                return MessageAttachmentDisplay(name: name, detail: detail)
            }
    }

    private func attachmentDetail(_ attachment: MessageAttachmentRecord) -> String {
        var parts: [String] = []
        if let typeLabel = attachment.typeLabel, !typeLabel.isEmpty {
            parts.append(typeLabel)
        }
        if let byteCount = attachment.byteCount {
            parts.append(ByteCountFormatter.string(fromByteCount: byteCount, countStyle: .file))
        }
        if let status = attachment.extractionStatus, !status.isEmpty {
            switch status {
            case "extracted":
                parts.append("text indexed")
            case "truncated":
                parts.append("text indexed, truncated")
            case "metadata_only":
                parts.append("metadata only")
            default:
                parts.append(status.replacingOccurrences(of: "_", with: " "))
            }
        }
        return parts.joined(separator: " · ")
    }

    var body: some View {
        HStack {
            if !isEve { Spacer(minLength: 120) }

            VStack(alignment: .leading, spacing: 6) {
                Text("\(senderLabel) · \(timestamp)")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(EveTheme.textTertiary)

                Text(displayBody.isEmpty ? "Attached files" : displayBody)
                    .font(.system(size: 14.5, weight: .regular))
                    .foregroundStyle(EveTheme.textPrimary)
                    .lineSpacing(4)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .textSelection(.enabled)

                if !attachments.isEmpty {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(attachments, id: \.self) { attachment in
                                AttachmentChipView(name: attachment.name, detail: attachment.detail)
                            }
                        }
                        .padding(.top, 4)
                    }
                }
            }
            .padding(.horizontal, isEve ? 0 : 14)
            .padding(.vertical, isEve ? 2 : 12)
            .background(isEve ? Color.clear : EveTheme.surfaceRaised, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay {
                if !isEve {
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .stroke(EveTheme.divider, lineWidth: 1)
                }
            }
            .frame(maxWidth: 720, alignment: isEve ? .leading : .trailing)

            if isEve { Spacer(minLength: 120) }
        }
    }
}

struct ThinkingBubbleView: View {
    let title: String
    let detail: String
    let notes: [EveReplyProgressNote]
    let formatTimestamp: (String?) -> String
    @State private var pulse = false

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 8) {
                Text(title)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(EveTheme.textTertiary)

                if !detail.isEmpty {
                    Text(detail)
                        .font(.system(size: 12.5))
                        .foregroundStyle(EveTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if !notes.isEmpty {
                    VStack(alignment: .leading, spacing: 7) {
                        ForEach(notes, id: \.self) { note in
                            VStack(alignment: .leading, spacing: 2) {
                                HStack(alignment: .firstTextBaseline, spacing: 8) {
                                    Text(note.title ?? "Thinking...")
                                        .font(.system(size: 12.5, weight: .medium))
                                        .foregroundStyle(EveTheme.textPrimary)
                                    if let timestamp = note.timestamp {
                                        Text(formatTimestamp(timestamp))
                                            .font(.system(size: 11))
                                            .foregroundStyle(EveTheme.textTertiary)
                                    }
                                }
                                if let detail = note.detail, !detail.isEmpty {
                                    Text(detail)
                                        .font(.system(size: 11.5))
                                        .foregroundStyle(EveTheme.textSecondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                        }
                    }
                    .padding(.top, 2)
                }

                HStack(spacing: 6) {
                    ForEach(0..<3, id: \.self) { index in
                        Circle()
                            .fill(EveTheme.textSecondary.opacity(0.8))
                            .frame(width: 7, height: 7)
                            .scaleEffect(pulse ? 1.0 : 0.72)
                            .opacity(pulse ? 0.95 : 0.45)
                            .animation(
                                .easeInOut(duration: 0.7)
                                    .repeatForever()
                                    .delay(Double(index) * 0.12),
                                value: pulse
                            )
                    }
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(EveTheme.surfaceSoft, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(EveTheme.divider, lineWidth: 1)
            )
            .frame(maxWidth: 720, alignment: .leading)

            Spacer(minLength: 120)
        }
        .onAppear { pulse = true }
        .textSelection(.enabled)
    }
}

struct ThoughtCardView: View {
    let thought: ThoughtEntry
    let timestamp: String

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Label("Thought", systemImage: "sparkles")
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(EveTheme.textSecondary)
                Spacer()
                Text(timestamp)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(EveTheme.textTertiary)
            }

            Text(thought.body)
                .font(.system(size: 14.5))
                .foregroundStyle(EveTheme.textPrimary)
                .lineSpacing(4)
                .textSelection(.enabled)
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(EveTheme.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(EveTheme.divider, lineWidth: 1)
        )
    }
}

struct LiveThoughtStreamCardView: View {
    let title: String
    let detail: String
    let threadBeats: [LiveThoughtThreadBeatDisplay]
    let notes: [EveReplyProgressNote]
    let updatedAt: String?
    let formatTimestamp: (String?) -> String
    @State private var pulse = false

    private var isLive: Bool {
        !notes.isEmpty || updatedAt != nil
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(spacing: 8) {
                        Circle()
                            .fill(EveTheme.accent.opacity(0.9))
                            .frame(width: 8, height: 8)
                            .scaleEffect(pulse ? 1.0 : 0.72)
                            .opacity(pulse ? 0.95 : 0.55)
                            .animation(.easeInOut(duration: 0.9).repeatForever(), value: pulse)
                        Text(isLive ? "Thinking Now" : "Current Focus")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundStyle(EveTheme.textSecondary)
                            .textCase(.uppercase)
                    }

                    Text(title)
                        .font(.system(size: 19, weight: .semibold))
                        .foregroundStyle(EveTheme.textPrimary)

                    Text(detail)
                        .font(.system(size: 13.5))
                        .foregroundStyle(EveTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer()

                if let updatedAt {
                    Text(formatTimestamp(updatedAt))
                        .font(.system(size: 11.5, weight: .medium))
                        .foregroundStyle(EveTheme.textTertiary)
                }
            }

            if !threadBeats.isEmpty {
                VStack(alignment: .leading, spacing: 12) {
                    Text("Live Thread Beats")
                        .font(.system(size: 11.5, weight: .semibold))
                        .foregroundStyle(EveTheme.textSecondary)
                        .textCase(.uppercase)

                    ForEach(threadBeats) { beat in
                        VStack(alignment: .leading, spacing: 7) {
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text(beat.kindLabel)
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundStyle(EveTheme.textSecondary)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 4)
                                    .background(EveTheme.surfaceRaised, in: Capsule())

                                Text(beat.statusLabel)
                                    .font(.system(size: 11.5, weight: .medium))
                                    .foregroundStyle(EveTheme.textTertiary)

                                Spacer()

                                if let updatedAt = beat.updatedAt {
                                    Text(formatTimestamp(updatedAt))
                                        .font(.system(size: 11))
                                        .foregroundStyle(EveTheme.textTertiary)
                                }
                            }

                            Text(beat.title)
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(EveTheme.textPrimary)

                            Text(beat.detail)
                                .font(.system(size: 12))
                                .foregroundStyle(EveTheme.textSecondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(EveTheme.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                }
            }

            if notes.isEmpty {
                Text("No background activity is active right now. Saved mind notes will still appear below as Eve writes them to memory.")
                    .font(.system(size: 12.5))
                    .foregroundStyle(EveTheme.textTertiary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    if !threadBeats.isEmpty {
                        Text("Recent Activity")
                            .font(.system(size: 11.5, weight: .semibold))
                            .foregroundStyle(EveTheme.textSecondary)
                            .textCase(.uppercase)
                    }
                    ForEach(notes, id: \.self) { note in
                        HStack(alignment: .top, spacing: 10) {
                            Circle()
                                .fill(EveTheme.textTertiary.opacity(0.7))
                                .frame(width: 5, height: 5)
                                .padding(.top, 6)

                            VStack(alignment: .leading, spacing: 3) {
                                HStack(alignment: .firstTextBaseline, spacing: 8) {
                                    Text(note.title ?? "Thinking...")
                                        .font(.system(size: 13, weight: .medium))
                                        .foregroundStyle(EveTheme.textPrimary)
                                    if let timestamp = note.timestamp {
                                        Text(formatTimestamp(timestamp))
                                            .font(.system(size: 11))
                                            .foregroundStyle(EveTheme.textTertiary)
                                    }
                                }
                                if let detail = note.detail, !detail.isEmpty {
                                    Text(detail)
                                        .font(.system(size: 12))
                                        .foregroundStyle(EveTheme.textSecondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                            }
                        }
                    }
                }
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(EveTheme.surfaceSoft, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(EveTheme.divider, lineWidth: 1)
        )
        .onAppear { pulse = true }
        .textSelection(.enabled)
    }
}

struct ActiveMindCardView: View {
    let focus: String
    let summary: String
    let liveThreads: [ActiveMindThreadDisplay]
    let concerns: [String]
    let relationshipPull: [String]
    let groundingNotes: [String]
    let nextStep: String
    let lanes: [(String, String)]
    let updatedAt: String?
    let formatTimestamp: (String?) -> String

    private func sectionLabel(_ title: String) -> some View {
        Text(title)
            .font(.system(size: 11.5, weight: .semibold))
            .foregroundStyle(EveTheme.textSecondary)
            .textCase(.uppercase)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 6) {
                    Label("Current Focus", systemImage: "brain.head.profile")
                        .font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(EveTheme.textSecondary)

                    Text(focus)
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(EveTheme.textPrimary)

                    Text(summary)
                        .font(.system(size: 13.5))
                        .foregroundStyle(EveTheme.textSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer()

                if let updatedAt {
                    Text(formatTimestamp(updatedAt))
                        .font(.system(size: 11.5, weight: .medium))
                        .foregroundStyle(EveTheme.textTertiary)
                }
            }

            if !liveThreads.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    sectionLabel("Background Focus")
                    ForEach(liveThreads) { item in
                        VStack(alignment: .leading, spacing: 8) {
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text(item.kindLabel)
                                    .font(.system(size: 11, weight: .semibold))
                                    .foregroundStyle(EveTheme.textSecondary)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 4)
                                    .background(EveTheme.surfaceRaised, in: Capsule())

                                Text(item.statusLabel)
                                    .font(.system(size: 11.5, weight: .medium))
                                    .foregroundStyle(EveTheme.textTertiary)

                                Spacer()

                                if let pressure = item.pressure {
                                    Text("P \(pressure)")
                                        .font(.system(size: 11, weight: .semibold))
                                        .foregroundStyle(EveTheme.textPrimary)
                                        .padding(.horizontal, 8)
                                        .padding(.vertical, 4)
                                        .background(EveTheme.surfaceRaised, in: Capsule())
                                }

                                if let salience = item.salience {
                                    Text("S \(salience)")
                                        .font(.system(size: 11, weight: .medium))
                                        .foregroundStyle(EveTheme.textSecondary)
                                }
                            }

                            Text(item.title)
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(EveTheme.textPrimary)

                            if item.detail != item.title {
                                Text(item.detail)
                                    .font(.system(size: 12))
                                    .foregroundStyle(EveTheme.textSecondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }

                            if !item.evidence.isEmpty {
                                Text("Evidence: \(item.evidence.joined(separator: " · "))")
                                    .font(.system(size: 11.5))
                                    .foregroundStyle(EveTheme.textTertiary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }

                            if !item.nextStep.isEmpty {
                                Text("Next: \(item.nextStep)")
                                    .font(.system(size: 11.5, weight: .medium))
                                    .foregroundStyle(EveTheme.textSecondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }

                            if let updatedAt = item.updatedAt {
                                Text("Updated \(formatTimestamp(updatedAt))")
                                    .font(.system(size: 11))
                                    .foregroundStyle(EveTheme.textTertiary)
                            }
                        }
                        .padding(12)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(EveTheme.surfaceSoft, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                }
            }

            if !concerns.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    sectionLabel("Open Concerns")
                    ForEach(concerns, id: \.self) { item in
                        Text(item)
                            .font(.system(size: 12.5))
                            .foregroundStyle(EveTheme.textPrimary)
                    }
                }
            }

            if !relationshipPull.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    sectionLabel("Relationship Pull")
                    ForEach(relationshipPull, id: \.self) { item in
                        Text(item)
                            .font(.system(size: 12.5))
                            .foregroundStyle(EveTheme.textPrimary)
                    }
                }
            }

            if !groundingNotes.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    sectionLabel("Grounding Notes")
                    ForEach(groundingNotes, id: \.self) { item in
                        Text(item)
                            .font(.system(size: 12.5))
                            .foregroundStyle(EveTheme.textPrimary)
                    }
                }
            }

            if !lanes.isEmpty {
                VStack(alignment: .leading, spacing: 10) {
                    sectionLabel("Mind Lanes")
                    ForEach(Array(lanes.enumerated()), id: \.offset) { _, lane in
                        VStack(alignment: .leading, spacing: 3) {
                            Text(lane.0)
                                .font(.system(size: 12.5, weight: .medium))
                                .foregroundStyle(EveTheme.textPrimary)
                            Text(lane.1)
                                .font(.system(size: 12))
                                .foregroundStyle(EveTheme.textSecondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
            }

            VStack(alignment: .leading, spacing: 6) {
                sectionLabel("Next Step")
                Text(nextStep)
                    .font(.system(size: 12.5))
                    .foregroundStyle(EveTheme.textPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(EveTheme.surface, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(EveTheme.divider, lineWidth: 1)
        )
        .textSelection(.enabled)
    }
}

struct MindAuditCardView: View {
    let events: [ActiveMindAuditDisplay]
    let formatTimestamp: (String?) -> String

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            Label("Mind Audit", systemImage: "list.bullet.rectangle.portrait")
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(EveTheme.textSecondary)

            if events.isEmpty {
                Text("No thread changes recorded yet.")
                    .font(.system(size: 12.5))
                    .foregroundStyle(EveTheme.textSecondary)
            } else {
                VStack(alignment: .leading, spacing: 12) {
                    ForEach(events) { event in
                        VStack(alignment: .leading, spacing: 5) {
                            HStack(alignment: .firstTextBaseline, spacing: 8) {
                                Text(event.headline)
                                    .font(.system(size: 13, weight: .medium))
                                    .foregroundStyle(EveTheme.textPrimary)
                                Spacer()
                                Text(formatTimestamp(event.timestamp))
                                    .font(.system(size: 11.5))
                                    .foregroundStyle(EveTheme.textTertiary)
                            }
                            if event.detail != event.headline {
                                Text(event.detail)
                                    .font(.system(size: 12))
                                    .foregroundStyle(EveTheme.textSecondary)
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                            if !event.meta.isEmpty {
                                Text(event.meta)
                                    .font(.system(size: 11))
                                    .foregroundStyle(EveTheme.textTertiary)
                            }
                        }
                        .padding(.bottom, 2)
                    }
                }
            }
        }
        .padding(18)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(EveTheme.surfaceSoft, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .stroke(EveTheme.divider, lineWidth: 1)
        )
        .textSelection(.enabled)
    }
}

struct ComposerView: View {
    @Binding var text: String
    let attachments: [PendingAttachment]
    let isSending: Bool
    let statusText: String
    let attachAction: () -> Void
    let removeAttachmentAction: (String) -> Void
    let sendAction: () -> Void

    private var isEmpty: Bool {
        text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var canSend: Bool {
        !isSending && (!isEmpty || !attachments.isEmpty)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if !attachments.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(attachments) { attachment in
                            AttachmentChipView(
                                name: attachment.name,
                                detail: "\(attachment.typeLabel) · \(ByteCountFormatter.string(fromByteCount: attachment.byteCount, countStyle: .file))"
                            ) {
                                removeAttachmentAction(attachment.id)
                            }
                        }
                    }
                    .padding(.vertical, 1)
                }
            }

            HStack(alignment: .bottom, spacing: 12) {
                Button(action: attachAction) {
                    Image(systemName: "paperclip")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(EveTheme.textSecondary)
                        .frame(width: 32, height: 32)
                }
                .frame(width: 32, height: 32)
                .contentShape(Circle())
                .background(EveTheme.surfaceSoft, in: Circle())
                .buttonStyle(.plain)
                .disabled(isSending)
                .help("Attach files")

                TextField("Message Eve", text: $text, axis: .vertical)
                    .textFieldStyle(.plain)
                    .font(.system(size: 15))
                    .foregroundStyle(EveTheme.textPrimary)
                    .lineLimit(1...4)

                Button(action: sendAction) {
                    Group {
                        if isSending {
                            ProgressView()
                                .progressViewStyle(.circular)
                                .tint(EveTheme.textPrimary)
                                .scaleEffect(0.72)
                        } else {
                            Image(systemName: "arrow.up")
                                .font(.system(size: 13, weight: .bold))
                                .foregroundStyle(EveTheme.textPrimary)
                        }
                    }
                    .frame(width: 32, height: 32)
                }
                .frame(width: 32, height: 32)
                .contentShape(Circle())
                .background(canSend ? EveTheme.surfaceRaised : EveTheme.surfaceSoft, in: Circle())
                .buttonStyle(.plain)
                .disabled(!canSend)
            }

            if !statusText.isEmpty {
                HStack(spacing: 8) {
                    if isSending {
                        HStack(spacing: 5) {
                            Circle().fill(EveTheme.accent.opacity(0.9)).frame(width: 6, height: 6)
                            Circle().fill(EveTheme.accent.opacity(0.65)).frame(width: 6, height: 6)
                            Circle().fill(EveTheme.accent.opacity(0.4)).frame(width: 6, height: 6)
                        }
                    }

                    Text(statusText)
                        .font(.system(size: 11.5, weight: .medium))
                        .foregroundStyle(isSending ? EveTheme.textSecondary : EveTheme.textTertiary)
                        .lineLimit(1)
                }
            }
        }
        .padding(12)
        .background(EveTheme.surface, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 16, style: .continuous)
                .stroke(EveTheme.divider, lineWidth: 1)
        )
    }
}

struct SearchFieldView: View {
    let placeholder: String
    @Binding var text: String

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .font(.system(size: 12, weight: .medium))
                .foregroundStyle(EveTheme.textTertiary)

            TextField(placeholder, text: $text)
                .textFieldStyle(.plain)
                .font(.system(size: 13.5))
                .foregroundStyle(EveTheme.textPrimary)

            if !text.isEmpty {
                Button {
                    text = ""
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .font(.system(size: 12))
                        .foregroundStyle(EveTheme.textTertiary)
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(EveTheme.surfaceSoft, in: RoundedRectangle(cornerRadius: 11, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: 11, style: .continuous)
                .stroke(EveTheme.divider, lineWidth: 1)
        )
    }
}

struct SidebarView: View {
    @EnvironmentObject private var model: EveDesktopModel

    private var searchPlaceholder: String {
        switch model.selectedWorkspaceTab {
        case .chats:
            return "Search chat history"
        case .agentChats:
            return "Search internal work"
        case .thoughts:
            return "Search mind notes"
        }
    }

    private var primaryListTitle: String {
        switch model.selectedWorkspaceTab {
        case .chats:
            return "Chat History"
        case .agentChats:
            return "Internal Work"
        case .thoughts:
            return "Mind Notes"
        }
    }

    private var primaryListCount: String {
        switch model.selectedWorkspaceTab {
        case .chats:
            return "\(model.visibleChatThreads.count)"
        case .agentChats:
            return "\(model.visibleAgentThreads.count)"
        case .thoughts:
            return "\(min(model.visibleThoughts.count, 16))"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            VStack(alignment: .leading, spacing: 14) {
                HStack(alignment: .center, spacing: 10) {
                    Text(model.sidebarSummaryLine)
                        .font(.system(size: 11.5, weight: .medium))
                        .foregroundStyle(EveTheme.textTertiary)
                        .lineLimit(1)

                    Spacer()

                    if model.isConnected {
                        Circle()
                            .fill(EveTheme.accent.opacity(0.9))
                            .frame(width: 6, height: 6)
                    }

                    Button {
                        model.newChat()
                    } label: {
                        Image(systemName: "square.and.pencil")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(EveTheme.textSecondary)
                            .frame(width: 24, height: 24)
                    }
                    .buttonStyle(.plain)
                    .help("New personal chat")
                }

                SearchFieldView(placeholder: searchPlaceholder, text: $model.searchText)

                VStack(alignment: .leading, spacing: 4) {
                    SidebarSectionLabelView(title: "Personal", trailing: nil)

                    SidebarNavigationRowView(
                        title: "Talk to Eve",
                        subtitle: "Personal conversation",
                        systemImage: "bubble.left.and.bubble.right",
                        isSelected: model.selectedWorkspaceTab == .chats,
                        trailingText: nil
                    ) {
                        model.selectedWorkspaceTab = .chats
                    }
                }

                VStack(alignment: .leading, spacing: 4) {
                    SidebarSectionLabelView(title: "Internal", trailing: nil)

                    SidebarNavigationRowView(
                        title: "Agent Work",
                        subtitle: "Tools and coordination",
                        systemImage: "person.2.wave.2",
                        isSelected: model.selectedWorkspaceTab == .agentChats,
                        trailingText: nil
                    ) {
                        model.selectedWorkspaceTab = .agentChats
                    }

                    SidebarNavigationRowView(
                        title: "Mind Activity",
                        subtitle: "Background focus",
                        systemImage: "brain.head.profile",
                        isSelected: model.selectedWorkspaceTab == .thoughts,
                        trailingText: nil
                    ) {
                        model.selectedWorkspaceTab = .thoughts
                    }
                }

                if model.selectedWorkspaceTab == .chats {
                    VStack(alignment: .leading, spacing: 4) {
                        SidebarSectionLabelView(title: "Filters", trailing: nil)

                        SidebarNavigationRowView(
                            title: "Waiting on you",
                            systemImage: model.showWaitingOnly ? "checkmark.circle.fill" : "circle",
                            isSelected: model.showWaitingOnly,
                            trailingText: nil
                        ) {
                            model.showWaitingOnly.toggle()
                        }
                    }
                }

                VStack(alignment: .leading, spacing: 8) {
                    SidebarSectionLabelView(title: primaryListTitle, trailing: primaryListCount)

                    Group {
                        switch model.selectedWorkspaceTab {
                        case .chats:
                            ScrollView {
                                LazyVStack(spacing: 6) {
                                    ForEach(model.visibleChatThreads) { thread in
                                        Button {
                                            Task { await model.selectChatThread(thread.threadId) }
                                        } label: {
                                            ThreadRowView(
                                                displayTitle: model.presentedSubject(for: thread),
                                                thread: thread,
                                                metaLine: model.threadMetaLine(for: thread),
                                                statusLabel: model.threadStatusLabel(thread.status),
                                                agentLine: nil,
                                                isSelected: model.selectedChatThreadID == thread.threadId
                                            )
                                        }
                                        .buttonStyle(.plain)
                                    }
                                }
                                .padding(.vertical, 1)
                            }
                        case .agentChats:
                            ScrollView {
                                LazyVStack(spacing: 6) {
                                    ForEach(model.visibleAgentThreads) { thread in
                                        Button {
                                            Task { await model.selectAgentThread(thread.threadId) }
                                        } label: {
                                            ThreadRowView(
                                                displayTitle: model.presentedSubject(for: thread),
                                                thread: thread,
                                                metaLine: model.threadMetaLine(for: thread),
                                                statusLabel: model.threadStatusLabel(thread.status),
                                                agentLine: model.agentParticipantLine(for: thread),
                                                isSelected: model.selectedAgentThreadID == thread.threadId
                                            )
                                        }
                                        .buttonStyle(.plain)
                                    }
                                }
                                .padding(.vertical, 1)
                            }
                        case .thoughts:
                            ScrollView {
                                LazyVStack(spacing: 6) {
                                    ForEach(model.visibleThoughts.prefix(16)) { thought in
                                        ThoughtPreviewRowView(thought: thought, timestamp: model.formatDate(thought.timestamp))
                                    }
                                }
                                .padding(.vertical, 1)
                            }
                        }
                    }
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 44)
            .padding(.bottom, 16)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        }
        .frame(minWidth: 286, idealWidth: 304, maxWidth: 338, maxHeight: .infinity, alignment: .top)
        .padding(.leading, 6)
        .padding(.trailing, 8)
        .padding(.top, 8)
        .padding(.bottom, 8)
        .background(EveTheme.sidebarBackground)
    }
}
