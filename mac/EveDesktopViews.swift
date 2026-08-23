import AppKit
import Combine
import Foundation
import SwiftUI

private struct ChatConversationPaneView: View {
    @EnvironmentObject private var model: EveDesktopModel

    var body: some View {
        VStack(spacing: 0) {
            if !model.isConnected && model.chatMessages.isEmpty {
                VStack(spacing: 14) {
                    Image(systemName: "bolt.horizontal.circle")
                        .font(.system(size: 34))
                        .foregroundStyle(EveTheme.textSecondary)
                    Text(model.statusTitle)
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(EveTheme.textPrimary)
                    Text(model.statusDetail)
                        .font(.system(size: 14))
                        .foregroundStyle(EveTheme.textSecondary)
                    Button("Reconnect") {
                        Task {
                            await model.reconnect(forceRestart: true)
                        }
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if model.selectedChatThreadID == nil && model.pendingNewChatMessages.isEmpty {
                EmptyStateView(tab: .chats)
            } else {
                conversationScroll(
                    messages: model.selectedChatThreadID == nil ? model.pendingNewChatMessages : model.chatMessages,
                    attachments: model.currentThreadAttachments,
                    showsThinking: model.isSendingMessage
                )
            }

            Rectangle()
                .fill(EveTheme.divider)
                .frame(height: 1)

            ComposerView(
                text: $model.composerText,
                attachments: model.pendingAttachments,
                isSending: model.isSendingMessage || !model.isConnected,
                statusText: model.chatFooterStatus,
                attachAction: model.attachFiles,
                removeAttachmentAction: model.removePendingAttachment
            ) {
                Task {
                    await model.sendCurrentMessage()
                }
            }
            .padding(.horizontal, 22)
            .padding(.vertical, 18)
            .background(EveTheme.detailBackground)
        }
        .background(EveTheme.detailBackground)
        .backgroundExtensionEffect()
    }

    private func conversationScroll(
        messages: [MessageRecord],
        attachments: [MessageAttachmentRecord],
        showsThinking: Bool
    ) -> some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 18) {
                    if !attachments.isEmpty {
                        ConversationAttachmentShelfView(attachments: attachments)
                            .id("conversation-attachments")
                    }

                    ForEach(messages) { message in
                        MessageBubbleView(
                            message: message,
                            senderLabel: model.displayName(for: message.sender),
                            timestamp: model.formatDate(message.timestamp)
                        )
                        .id(message.id)
                    }

                    if showsThinking {
                        ThinkingBubbleView(
                            title: model.activeReplyStatusText.isEmpty ? "Eve is thinking..." : model.activeReplyStatusText,
                            detail: model.activeReplyStatusDetail,
                            notes: model.activeReplyNotes,
                            formatTimestamp: model.formatDate
                        )
                            .id("conversation-thinking")
                    }

                    Color.clear
                        .frame(height: 1)
                        .id("conversation-bottom")
                }
                .padding(.horizontal, 28)
                .padding(.vertical, 24)
            }
            .background(EveTheme.detailBackground)
            .backgroundExtensionEffect()
            .onAppear {
                proxy.scrollTo("conversation-bottom", anchor: .bottom)
            }
            .onChange(of: messages.last?.id) { _, _ in
                withAnimation(.easeOut(duration: 0.18)) {
                    proxy.scrollTo("conversation-bottom", anchor: .bottom)
                }
            }
            .onChange(of: showsThinking) { _, _ in
                withAnimation(.easeOut(duration: 0.18)) {
                    proxy.scrollTo("conversation-bottom", anchor: .bottom)
                }
            }
        }
    }
}

private struct AgentConversationPaneView: View {
    @EnvironmentObject private var model: EveDesktopModel

    var body: some View {
        VStack(spacing: 0) {
            if model.selectedAgentThreadID == nil {
                EmptyStateView(tab: .agentChats)
            } else {
                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 14) {
                            if let thread = model.selectedAgentThread {
                                ScrollView(.horizontal, showsIndicators: false) {
                                    HStack(spacing: 8) {
                                        ParticipantChipView(label: "Eve")
                                        ForEach(thread.agentParticipants, id: \.self) { participant in
                                            ParticipantChipView(label: model.displayName(for: participant))
                                        }
                                    }
                                    .padding(.horizontal, 28)
                                }
                                .padding(.top, 20)
                            }

                            Text("This is Eve's internal coordination log. Your personal conversation stays in Talk to Eve.")
                                .font(.system(size: 13))
                                .foregroundStyle(EveTheme.textSecondary)
                                .padding(.horizontal, 28)
                                .padding(.top, 20)

                            LazyVStack(spacing: 18) {
                                ForEach(model.agentMessages) { message in
                                    MessageBubbleView(
                                        message: message,
                                        senderLabel: model.displayName(for: message.sender),
                                        timestamp: model.formatDate(message.timestamp)
                                    )
                                    .id(message.id)
                                }

                                Color.clear
                                    .frame(height: 1)
                                    .id("agent-conversation-bottom")
                            }
                            .padding(.horizontal, 28)
                            .padding(.bottom, 22)
                        }
                    }
                    .background(EveTheme.detailBackground)
                    .backgroundExtensionEffect()
                    .onAppear {
                        proxy.scrollTo("agent-conversation-bottom", anchor: .bottom)
                    }
                    .onChange(of: model.agentMessages.last?.id) { _, _ in
                        withAnimation(.easeOut(duration: 0.18)) {
                            proxy.scrollTo("agent-conversation-bottom", anchor: .bottom)
                        }
                    }
                }
            }
        }
        .background(EveTheme.detailBackground)
        .backgroundExtensionEffect()
    }
}

private struct ThoughtStreamPaneView: View {
    @EnvironmentObject private var model: EveDesktopModel

    var body: some View {
        VStack(spacing: 0) {
            if model.visibleThoughts.isEmpty {
                ScrollView {
                    VStack(spacing: 18) {
                        ActiveMindCardView(
                            focus: model.activeMindFocus,
                            summary: model.activeMindSummary,
                            liveThreads: model.activeMindLiveThreads,
                            concerns: model.activeMindConcerns,
                            relationshipPull: model.activeMindRelationshipPull,
                            groundingNotes: model.activeMindGroundingNotes,
                            nextStep: model.activeMindNextStep,
                            lanes: model.activeMindLaneRows,
                            updatedAt: model.activeMindUpdatedAt,
                            formatTimestamp: model.formatDate
                        )
                        MindAuditCardView(
                            events: model.activeMindAuditEvents,
                            formatTimestamp: model.formatDate
                        )
                        LiveThoughtStreamCardView(
                            title: model.liveThoughtTitle,
                            detail: model.liveThoughtDetail,
                            threadBeats: model.liveThoughtThreadBeats,
                            notes: model.liveThoughtNotes,
                            updatedAt: model.liveThoughtUpdatedAt,
                            formatTimestamp: model.formatDate
                        )
                        EmptyStateView(tab: .thoughts)
                            .frame(minHeight: 320)
                    }
                    .padding(.horizontal, 28)
                    .padding(.vertical, 24)
                }
                .background(EveTheme.detailBackground)
                .backgroundExtensionEffect()
            } else {
                ScrollView {
                    LazyVStack(spacing: 16) {
                        ActiveMindCardView(
                            focus: model.activeMindFocus,
                            summary: model.activeMindSummary,
                            liveThreads: model.activeMindLiveThreads,
                            concerns: model.activeMindConcerns,
                            relationshipPull: model.activeMindRelationshipPull,
                            groundingNotes: model.activeMindGroundingNotes,
                            nextStep: model.activeMindNextStep,
                            lanes: model.activeMindLaneRows,
                            updatedAt: model.activeMindUpdatedAt,
                            formatTimestamp: model.formatDate
                        )
                        MindAuditCardView(
                            events: model.activeMindAuditEvents,
                            formatTimestamp: model.formatDate
                        )
                        LiveThoughtStreamCardView(
                            title: model.liveThoughtTitle,
                            detail: model.liveThoughtDetail,
                            threadBeats: model.liveThoughtThreadBeats,
                            notes: model.liveThoughtNotes,
                            updatedAt: model.liveThoughtUpdatedAt,
                            formatTimestamp: model.formatDate
                        )

                        ForEach(model.visibleThoughts) { thought in
                            ThoughtCardView(
                                thought: thought,
                                timestamp: model.formatDate(thought.timestamp)
                            )
                        }
                    }
                    .padding(.horizontal, 28)
                    .padding(.vertical, 24)
                }
                .background(EveTheme.detailBackground)
                .backgroundExtensionEffect()
            }
        }
        .background(EveTheme.detailBackground)
        .backgroundExtensionEffect()
    }
}

private struct DetailColumnShell<Content: View>: View {
    @EnvironmentObject private var model: EveDesktopModel
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    private var primaryTitle: String {
        switch model.selectedWorkspaceTab {
        case .chats:
            return "Talk to Eve"
        case .agentChats:
            return "Agent Work"
        case .thoughts:
            return "Mind Activity"
        }
    }

    private var secondaryTitle: String? {
        switch model.selectedWorkspaceTab {
        case .chats:
            guard model.selectedChatThreadID != nil || !model.pendingNewChatMessages.isEmpty else { return nil }
            return model.currentConversationTitle
        case .agentChats:
            guard model.selectedAgentThreadID != nil else { return nil }
            return model.currentConversationTitle
        case .thoughts:
            return nil
        }
    }

    private var statusLine: String? {
        switch model.selectedWorkspaceTab {
        case .chats:
            return model.isSendingMessage ? model.currentConversationMeta : nil
        case .agentChats, .thoughts:
            return nil
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            HStack(alignment: .center, spacing: 14) {
                HStack(spacing: 12) {
                    Text(primaryTitle)
                        .font(.system(size: 17, weight: .medium))
                        .foregroundStyle(EveTheme.textSecondary)

                    if let secondaryTitle, !secondaryTitle.isEmpty {
                        Text("/")
                            .font(.system(size: 17, weight: .medium))
                            .foregroundStyle(EveTheme.textTertiary)

                        Text(secondaryTitle)
                            .font(.system(size: 17, weight: .semibold))
                            .foregroundStyle(EveTheme.textPrimary)
                            .lineLimit(1)
                    }
                }

                Spacer(minLength: 16)

                if let statusLine, !statusLine.isEmpty {
                    HStack(spacing: 8) {
                        if model.isSendingMessage {
                            HStack(spacing: 5) {
                                Circle().fill(EveTheme.accent.opacity(0.95)).frame(width: 5.5, height: 5.5)
                                Circle().fill(EveTheme.accent.opacity(0.7)).frame(width: 5.5, height: 5.5)
                                Circle().fill(EveTheme.accent.opacity(0.45)).frame(width: 5.5, height: 5.5)
                            }
                        }

                        Text(statusLine)
                            .font(.system(size: 12.5, weight: .medium))
                            .foregroundStyle(EveTheme.textSecondary)
                            .lineLimit(1)
                    }
                }

                if model.selectedWorkspaceTab == .chats {
                    GlassActionClusterView {
                        GlassIconButton(
                            systemImage: "doc.on.doc",
                            tooltip: "Copy Current View"
                        ) {
                            model.copyCurrentViewSnapshot()
                        }
                        GlassIconButton(
                            systemImage: "archivebox",
                            tooltip: "Archive Chat",
                            disabled: model.selectedChatThreadID == nil || model.isWorking
                        ) {
                            Task { await model.archiveSelectedChatThread() }
                        }
                    }
                } else {
                    GlassActionClusterView {
                        GlassIconButton(
                            systemImage: "doc.on.doc",
                            tooltip: "Copy Current View"
                        ) {
                            model.copyCurrentViewSnapshot()
                        }
                    }
                }
            }
            .padding(.horizontal, 28)
            .padding(.top, 18)
            .padding(.bottom, 16)

            Rectangle()
                .fill(EveTheme.divider)
                .frame(height: 1)

            content
        }
        .background(EveTheme.detailBackground)
    }
}

struct EveRootView: View {
    @EnvironmentObject private var model: EveDesktopModel
    private let shellCornerRadius: CGFloat = 30

    @ViewBuilder
    private var detailPane: some View {
        switch model.selectedWorkspaceTab {
        case .chats:
            ChatConversationPaneView()
        case .agentChats:
            AgentConversationPaneView()
        case .thoughts:
            ThoughtStreamPaneView()
        }
    }

    var body: some View {
        ZStack {
            GlassPanelBackground(
                material: .underWindowBackground,
                cornerRadius: shellCornerRadius,
                shadowOpacity: 0.28
            )

            RoundedRectangle(cornerRadius: shellCornerRadius, style: .continuous)
                .fill(EveTheme.appBackground.opacity(0.9))

            RoundedRectangle(cornerRadius: shellCornerRadius, style: .continuous)
                .fill(
                    LinearGradient(
                        colors: [
                            Color.white.opacity(0.04),
                            Color.clear,
                            Color.black.opacity(0.14),
                        ],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )

            HStack(spacing: 0) {
                SidebarView()

                Rectangle()
                    .fill(EveTheme.divider)
                    .frame(width: 1)

                DetailColumnShell {
                    detailPane
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: shellCornerRadius, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: shellCornerRadius, style: .continuous)
                .stroke(Color.white.opacity(0.08), lineWidth: 1)
        )
        .padding(10)
        .background(Color.clear)
        .background(WindowAccessorView(title: model.currentConversationTitle).allowsHitTesting(false))
        .task {
            await model.start()
        }
        .onChange(of: model.selectedWorkspaceTab) { _, _ in
            Task {
                await model.refreshAll(
                    preferredChatThreadID: model.selectedChatThreadID,
                    preferredAgentThreadID: model.selectedAgentThreadID
                )
                await model.ensureSelectionForCurrentWorkspace()
            }
        }
    }
}

final class EveAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSWindow.allowsAutomaticWindowTabbing = false
        NSApp.activate(ignoringOtherApps: true)
    }
}
