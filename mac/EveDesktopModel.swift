import AppKit
import Combine
import Foundation
import SwiftUI

struct ActiveMindThreadDisplay: Identifiable, Hashable {
    let id: String
    let title: String
    let detail: String
    let kindLabel: String
    let statusLabel: String
    let pressure: Int?
    let salience: Int?
    let updatedAt: String?
    let evidence: [String]
    let nextStep: String
}

struct ActiveMindAuditDisplay: Identifiable, Hashable {
    let id: String
    let timestamp: String?
    let headline: String
    let detail: String
    let meta: String
}

struct LiveThoughtThreadBeatDisplay: Identifiable, Hashable {
    let id: String
    let title: String
    let detail: String
    let kindLabel: String
    let statusLabel: String
    let updatedAt: String?
}

struct PendingAttachment: Identifiable, Hashable {
    let id: String
    let name: String
    let originalPath: String
    let storedPath: String
    let byteCount: Int64
    let typeLabel: String
}

@MainActor
final class EveDesktopModel: ObservableObject {
    @Published var statusTitle = "Connecting to Eve..."
    @Published var statusDetail = "Opening Eve's local interface."
    @Published var isConnected = false
    @Published var isWorking = false
    @Published var isSendingMessage = false
    @Published var searchText = ""
    @Published var showWaitingOnly = false
    @Published var selectedWorkspaceTab: WorkspaceTab = .chats
    @Published var selectedChatThreadID: String?
    @Published var selectedAgentThreadID: String?
    @Published var chatThreads: [ThreadSummary] = []
    @Published var agentThreads: [ThreadSummary] = []
    @Published var chatMessages: [MessageRecord] = []
    @Published var agentMessages: [MessageRecord] = []
    @Published var thoughts: [ThoughtEntry] = []
    @Published var composerText = ""
    @Published var pendingAttachments: [PendingAttachment] = []
    @Published var currentStatus: EveStatusData?
    @Published var pendingNewChatMessages: [MessageRecord] = []
    @Published var activeReplyStatusText = ""
    @Published var activeReplyStatusDetail = ""
    @Published var activeReplyNotes: [EveReplyProgressNote] = []

    private let requiredAPIVersion = 5
    private let maxPollAttempts = 80
    private let baseURL = URL(string: "http://127.0.0.1:8787")!
    private var hasStarted = false
    private var refreshTask: Task<Void, Never>?
    private var replyStatusTask: Task<Void, Never>?
    private var lastIncomingEveMessageID: String?
    private var isDraftingNewChat = false
    private var loadedChatLatestMessageID: String?
    private var loadedAgentLatestMessageID: String?
    private var formattedDateCache: [String: String] = [:]
    private var refreshCycle = 0
    private var refreshGeneration = 0
    private var chatLoadGeneration = 0
    private var agentLoadGeneration = 0

    private let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    private let isoFormatterWithFractional: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()

    private let isoFormatter: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter
    }()

    private var helperURL: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".eve_runtime/bin/eve_control.sh")
    }

    private var attachmentStoreURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent(".eve_runtime/.eve/attachments", isDirectory: true)
    }

    var visibleChatThreads: [ThreadSummary] {
        filteredThreads(chatThreads, waitingOnly: showWaitingOnly)
    }

    var visibleAgentThreads: [ThreadSummary] {
        filteredThreads(agentThreads, waitingOnly: false)
    }

    var visibleThoughts: [ThoughtEntry] {
        let search = normalizedSearchTerm()
        let filtered = thoughts.filter { entry in
            guard !search.isEmpty else { return true }
            let haystack = [entry.body, entry.preview].joined(separator: " ").lowercased()
            return haystack.contains(search)
        }
        return filtered.reversed()
    }

    var activeMind: EveActiveMind? {
        currentStatus?.activeMind
    }

    var ambientThought: EveAmbientThought? {
        currentStatus?.ambientThought
    }

    var liveThoughtStream: EveReplyProgress? {
        guard let activeReply = currentStatus?.activeReply else { return nil }
        return activeReply.status == "active" ? activeReply : nil
    }

    var liveThoughtTitle: String {
        let title = liveThoughtStream?.title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !title.isEmpty {
            return title
        }
        let ambientTitle = ambientThought?.title?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !ambientTitle.isEmpty {
            return ambientTitle
        }
        let mindFocus = activeMind?.currentFocus?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return mindFocus.isEmpty ? "Current focus" : mindFocus
    }

    var liveThoughtDetail: String {
        let detail = liveThoughtStream?.detail?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !detail.isEmpty {
            return detail
        }
        let ambientDetail = ambientThought?.detail?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !ambientDetail.isEmpty {
            return ambientDetail
        }
        let summary = activeMind?.summary?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !summary.isEmpty {
            return summary
        }
        return focusLine
    }

    var liveThoughtNotes: [EveReplyProgressNote] {
        if let liveThoughtStream {
            return Array((liveThoughtStream.notes ?? []).suffix(8))
        }
        return Array((ambientThought?.notes ?? []).suffix(8))
    }

    var liveThoughtThreadBeats: [LiveThoughtThreadBeatDisplay] {
        guard liveThoughtStream == nil else { return [] }
        return Array((ambientThought?.threadBeats ?? []).prefix(4).enumerated()).compactMap { index, beat in
            let title = (beat.title ?? beat.threadTitle ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let detail = (beat.detail ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !title.isEmpty || !detail.isEmpty else { return nil }
            return LiveThoughtThreadBeatDisplay(
                id: (beat.sourceId ?? "\(index)-\(title)-\(detail)"),
                title: title.isEmpty ? detail : title,
                detail: detail.isEmpty ? title : detail,
                kindLabel: activeMindThreadKindLabel(beat.threadKind),
                statusLabel: activeMindThreadStatusLabel(beat.threadStatus),
                updatedAt: beat.updatedAt
            )
        }
    }

    var liveThoughtUpdatedAt: String? {
        liveThoughtStream?.updatedAt ?? ambientThought?.updatedAt
    }

    var activeMindUpdatedAt: String? {
        activeMind?.updatedAt
    }

    var activeMindSummary: String {
        let summary = activeMind?.summary?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !summary.isEmpty {
            return summary
        }
        return "Eve's active mind will appear here as the runtime keeps her short-horizon context warm."
    }

    var activeMindFocus: String {
        let focus = activeMind?.currentFocus?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !focus.isEmpty {
            return focus
        }
        return focusLine
    }

    var activeMindConcerns: [String] {
        Array((activeMind?.liveConcerns ?? []).prefix(4))
    }

    var activeMindRelationshipPull: [String] {
        Array((activeMind?.relationshipPull ?? []).prefix(4))
    }

    var activeMindGroundingNotes: [String] {
        Array((activeMind?.groundingNotes ?? []).prefix(4))
    }

    var activeMindLiveThreads: [ActiveMindThreadDisplay] {
        Array((activeMind?.liveThreads ?? []).prefix(6).enumerated()).compactMap { index, thread in
            let title = (thread.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let detail = (thread.detail ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            guard !title.isEmpty || !detail.isEmpty else { return nil }
            let nextStep = (thread.nextStep ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            return ActiveMindThreadDisplay(
                id: "\(index)-\(title)-\(detail)",
                title: title.isEmpty ? detail : title,
                detail: detail.isEmpty ? title : detail,
                kindLabel: activeMindThreadKindLabel(thread.kind),
                statusLabel: activeMindThreadStatusLabel(thread.status),
                pressure: thread.pressure,
                salience: thread.salience,
                updatedAt: thread.lastUpdated,
                evidence: (thread.evidence ?? []).filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty },
                nextStep: nextStep
            )
        }
    }

    var activeMindAuditEvents: [ActiveMindAuditDisplay] {
        Array((currentStatus?.activeMindAudit ?? []).suffix(20).reversed()).compactMap { event in
            let summary = (event.summary ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let title = (event.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let detail = (event.detail ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let threadKind = activeMindThreadKindLabel(event.threadKind)
            let threadStatus = activeMindThreadStatusLabel(event.threadStatus)
            let eventLabel = activeMindAuditEventLabel(event.eventKind)
            let headline = summary.isEmpty ? "\(threadStatus) \(threadKind) \(eventLabel)" : summary
            let trailingDetail = detail.isEmpty ? title : detail
            let metaParts = [threadStatus, threadKind, eventLabel, (event.source ?? "").trimmingCharacters(in: .whitespacesAndNewlines)]
                .filter { !$0.isEmpty }
            return ActiveMindAuditDisplay(
                id: event.id ?? "\(event.timestamp ?? "")-\(headline)",
                timestamp: event.timestamp,
                headline: headline,
                detail: trailingDetail,
                meta: metaParts.joined(separator: " · ")
            )
        }
    }

    var activeMindNextStep: String {
        let nextStep = activeMind?.nextStep?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !nextStep.isEmpty {
            return nextStep
        }
        return "No next step recorded yet."
    }

    var activeMindLaneRows: [(String, String)] {
        guard let lanes = activeMind?.lanes else { return [] }
        return [
            ("Observer", lanes.observer ?? ""),
            ("Planner", lanes.planner ?? ""),
            ("Relationship", lanes.relationship ?? ""),
            ("Grounding", lanes.grounding ?? ""),
            ("Self-check", lanes.selfCheck ?? ""),
        ]
        .filter { !$0.1.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
    }

    var selectedChatThread: ThreadSummary? {
        guard let selectedChatThreadID else { return nil }
        return chatThreads.first(where: { $0.threadId == selectedChatThreadID })
    }

    var selectedAgentThread: ThreadSummary? {
        guard let selectedAgentThreadID else { return nil }
        return agentThreads.first(where: { $0.threadId == selectedAgentThreadID })
    }

    var presenceLine: String {
        guard let status = currentStatus else { return statusDetail }
        if status.daemon.awake {
            return "Active now"
        }
        if status.daemon.running {
            return "Runtime online"
        }
        return "Runtime idle"
    }

    var focusLine: String {
        if let focus = currentStatus?.state.currentFocus, !focus.isEmpty {
            return focus
        }
        return "A lightweight window into Eve's live runtime."
    }

    var sidebarSummaryLine: String {
        guard let counts = currentStatus?.counts else {
            return "Connecting"
        }
        let unreadCount = counts.unreadMessages ?? 0
        var parts = ["Eve is online"]
        if unreadCount > 0 {
            parts.append("\(compactUnreadCount(unreadCount)) unread")
        }
        return parts.joined(separator: " · ")
    }

    var identityStatement: String {
        currentStatus?.humanContext?.selfModel?.identityStatement ?? "Listening for evidence."
    }

    var relationshipOverview: String {
        currentStatus?.humanContext?.relationshipMemory?.userOverview ?? "Learning how to relate."
    }

    var sidebarContextLine: String {
        if let updated = currentStatus?.humanContext?.updatedAt {
            return "Context updated \(formatDate(updated))"
        }
        return "Relationship context not refreshed yet."
    }

    var sidebarContextShortLine: String {
        if let updated = currentStatus?.humanContext?.updatedAt {
            return "Updated \(formatDate(updated))"
        }
        return "Not refreshed"
    }

    var modelHealthCardText: String {
        guard let modelHealth = currentStatus?.modelHealth else {
            return "Model health unavailable."
        }
        let fastResident = modelHealth.residency?.preferredFastLoaded == true ? "yes" : "no"
        let deepResident = modelHealth.residency?.preferredDeepLoaded == true ? "yes" : "no"
        let fastLatency = formatLatency(modelHealth.probes?.fast?.wallMs)
        let deepLatency = formatLatency(modelHealth.probes?.deep?.wallMs)
        let actions = (modelHealth.recentActions ?? []).prefix(3).joined(separator: " • ")
        return [
            modelHealth.summary ?? "Model health unavailable.",
            "Resident fast \(fastResident) • deep \(deepResident).",
            "Latency fast \(fastLatency) • deep \(deepLatency).",
            actions.isEmpty ? nil : "Actions \(actions).",
        ]
        .compactMap { $0 }
        .joined(separator: " ")
    }

    var currentConversationTitle: String {
        switch selectedWorkspaceTab {
        case .chats:
            guard let thread = selectedChatThread else { return "New personal chat" }
            return presentedSubject(for: thread)
        case .agentChats:
            guard let thread = selectedAgentThread else { return "Internal coordination" }
            return presentedSubject(for: thread)
        case .thoughts:
            return "Mind Activity"
        }
    }

    var currentConversationMeta: String {
        if isSendingMessage && selectedWorkspaceTab == .chats {
            return activeReplyStatusText.isEmpty ? "Eve is thinking..." : activeReplyStatusText
        }
        switch selectedWorkspaceTab {
        case .chats:
            guard let thread = selectedChatThread else { return "Choose a thread or start a new conversation" }
            return chatConversationMeta(for: thread)
        case .agentChats:
            guard let thread = selectedAgentThread else { return "Internal work stays separate from your chat with Eve" }
            return agentConversationMeta(for: thread)
        case .thoughts:
            if let liveUpdate = liveThoughtUpdatedAt {
                return "Background activity updated \(formatDate(liveUpdate))"
            }
            if let activeMindUpdate = activeMindUpdatedAt {
                return "Current focus updated \(formatDate(activeMindUpdate))"
            }
            if let latest = visibleThoughts.first?.timestamp {
                return "Latest mind note \(formatDate(latest))"
            }
            return "Recent background activity"
        }
    }

    var chatFooterStatus: String {
        if isSendingMessage {
            if !activeReplyStatusDetail.isEmpty {
                return activeReplyStatusDetail
            }
            return activeReplyStatusText.isEmpty ? "Eve is thinking..." : activeReplyStatusText
        }
        if !isConnected {
            return statusDetail
        }
        if selectedWorkspaceTab != .chats {
            return ""
        }
        if !pendingAttachments.isEmpty {
            return "\(pendingAttachments.count) file\(pendingAttachments.count == 1 ? "" : "s") attached for Eve."
        }
        if selectedChatThreadID == nil {
            return "Write to Eve below."
        }
        return "Press Command-Return to send."
    }

    var currentThreadAttachments: [MessageAttachmentRecord] {
        let messages = selectedChatThreadID == nil ? pendingNewChatMessages : chatMessages
        var seen = Set<String>()
        var records: [MessageAttachmentRecord] = []
        for message in messages {
            for attachment in message.attachments where !seen.contains(attachment.id) {
                seen.insert(attachment.id)
                records.append(attachment)
            }
        }
        return records
    }

    var canSendCurrentMessage: Bool {
        selectedWorkspaceTab == .chats
            && !isSendingMessage
            && isConnected
            && (!composerText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || !pendingAttachments.isEmpty)
    }

    var currentThreadSelectionID: String? {
        switch selectedWorkspaceTab {
        case .chats:
            return selectedChatThreadID
        case .agentChats:
            return selectedAgentThreadID
        case .thoughts:
            return nil
        }
    }

    func start() async {
        guard !hasStarted else { return }
        hasStarted = true
        NSApp.activate(ignoringOtherApps: true)
        await reconnect(forceRestart: false)
        startRefreshLoop()
    }

    func reconnect(forceRestart: Bool) async {
        statusTitle = forceRestart ? "Reconnecting to Eve..." : "Connecting to Eve..."
        statusDetail = "Opening Eve's local interface."
        isWorking = true
        isConnected = false

        if forceRestart {
            runHelper("web-restart")
        }

        var restartAttempted = forceRestart

        for attempt in 0..<maxPollAttempts {
            do {
                let status: EveStatusData = try await request("/api/status", timeout: 2)
                if status.apiVersion >= requiredAPIVersion {
                    currentStatus = status
                    isConnected = true
                    isWorking = false
                    statusTitle = "Eve interface live"
                    statusDetail = "Connected to Eve's local runtime."
                    await refreshAll(preferredChatThreadID: nil, preferredAgentThreadID: nil)
                    return
                }
            } catch {
                if attempt == 0 && !restartAttempted {
                    restartAttempted = true
                    runHelper("web-restart")
                }
            }

            try? await Task.sleep(nanoseconds: 250_000_000)
        }

        isConnected = false
        isWorking = false
        statusTitle = "Could not reach Eve"
        statusDetail = "The local interface backend did not start in time."
    }

    func refreshAll(preferredChatThreadID: String? = nil, preferredAgentThreadID: String? = nil) async {
        refreshGeneration += 1
        let refreshID = refreshGeneration

        do {
            refreshCycle += 1
            async let statusRequest: EveStatusData = request("/api/status", timeout: 3)
            async let chatThreadsRequest: [ThreadSummary] = request("/api/threads?limit=50&audience=user", timeout: 4)

            let status = try await statusRequest
            let nextChatThreads = try await chatThreadsRequest
            let shouldFetchAgentThreads = selectedWorkspaceTab == .agentChats || preferredAgentThreadID != nil || selectedAgentThreadID != nil
            let nextAgentThreads = shouldFetchAgentThreads
                ? try await request("/api/threads?limit=50&audience=agent", timeout: 4) as [ThreadSummary]
                : agentThreads
            guard isCurrentRefresh(refreshID) else { return }
            let shouldFetchThoughts = selectedWorkspaceTab == .thoughts || thoughts.isEmpty || refreshCycle % 6 == 0
            let nextThoughts = shouldFetchThoughts ? try await request("/api/thoughts?limit=80", timeout: 4) as [ThoughtEntry] : thoughts
            guard isCurrentRefresh(refreshID) else { return }

            if currentStatus != status {
                currentStatus = status
            }
            if chatThreads != nextChatThreads {
                chatThreads = nextChatThreads
            }
            if agentThreads != nextAgentThreads {
                agentThreads = nextAgentThreads
            }
            if thoughts != nextThoughts {
                thoughts = nextThoughts
            }
            isConnected = true
            statusTitle = "Eve interface live"
            statusDetail = "Connected to Eve's local runtime."

            let userIsDrafting = !composerText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            let shouldPreserveEmptyChat = isDraftingNewChat && preferredChatThreadID == nil
            let shouldSyncChatDetail = selectedWorkspaceTab == .chats || preferredChatThreadID != nil
            let shouldSyncAgentDetail = selectedWorkspaceTab == .agentChats || preferredAgentThreadID != nil

            let newestThread = nextChatThreads.first
            let hasNewIncomingEveMessage = newestThread?.latestSender == "eve" &&
                newestThread?.latestMessageId != nil &&
                newestThread?.latestMessageId != lastIncomingEveMessageID

            if newestThread?.latestSender == "eve" {
                lastIncomingEveMessageID = newestThread?.latestMessageId
            }

            if shouldSyncChatDetail {
                var threadToShow: ThreadSummary? = shouldPreserveEmptyChat
                    ? nil
                    : chooseThread(
                        from: nextChatThreads,
                        preferredThreadID: preferredChatThreadID,
                        selectedThreadID: selectedChatThreadID
                    )

                if
                    !shouldPreserveEmptyChat,
                    selectedWorkspaceTab == .chats,
                    selectedChatThreadID == nil,
                    !userIsDrafting,
                    hasNewIncomingEveMessage,
                    let newestThread
                {
                    threadToShow = newestThread
                }

                if let threadToShow {
                    if shouldReload(
                        thread: threadToShow,
                        selectedID: selectedChatThreadID,
                        cachedMessages: chatMessages,
                        loadedLatestMessageID: loadedChatLatestMessageID
                    ) {
                        await loadChatThread(threadID: threadToShow.threadId)
                        guard isCurrentRefresh(refreshID) else { return }
                    }
                } else {
                    clearChatSelection(preserveDraftState: shouldPreserveEmptyChat)
                }
            }

            if shouldSyncAgentDetail {
                let agentThreadToShow = chooseThread(
                    from: nextAgentThreads,
                    preferredThreadID: preferredAgentThreadID,
                    selectedThreadID: selectedAgentThreadID
                )

                if let agentThreadToShow {
                    if shouldReload(
                        thread: agentThreadToShow,
                        selectedID: selectedAgentThreadID,
                        cachedMessages: agentMessages,
                        loadedLatestMessageID: loadedAgentLatestMessageID
                    ) {
                        await loadAgentThread(threadID: agentThreadToShow.threadId)
                        guard isCurrentRefresh(refreshID) else { return }
                    }
                } else {
                    clearAgentSelection()
                }
            }
        } catch {
            guard isCurrentRefresh(refreshID) else { return }
            isConnected = false
            statusTitle = "Could not reach Eve"
            statusDetail = error.localizedDescription
        }
    }

    func ensureSelectionForCurrentWorkspace() async {
        switch selectedWorkspaceTab {
        case .chats:
            guard !isDraftingNewChat else { return }
            if selectedChatThread == nil, let thread = visibleChatThreads.first {
                await loadChatThread(threadID: thread.threadId)
            }
        case .agentChats:
            if selectedAgentThread == nil, let thread = visibleAgentThreads.first {
                await loadAgentThread(threadID: thread.threadId)
            }
        case .thoughts:
            break
        }
    }

    func selectChatThread(_ threadID: String?) async {
        guard let threadID else {
            clearChatSelection()
            return
        }
        isDraftingNewChat = false
        await loadChatThread(threadID: threadID)
    }

    func selectAgentThread(_ threadID: String?) async {
        guard let threadID else {
            clearAgentSelection()
            return
        }
        await loadAgentThread(threadID: threadID)
    }

    func newChat() {
        selectedWorkspaceTab = .chats
        clearChatSelection(preserveDraftState: true)
        pendingNewChatMessages = []
        pendingAttachments = []
        isDraftingNewChat = true
    }

    func attachFiles() {
        let panel = NSOpenPanel()
        panel.allowsMultipleSelection = true
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.resolvesAliases = true
        panel.title = "Attach Files"
        panel.prompt = "Attach"

        guard panel.runModal() == .OK else { return }
        addAttachments(from: panel.urls)
    }

    func removePendingAttachment(_ attachmentID: String) {
        pendingAttachments.removeAll { $0.id == attachmentID }
    }

    private func addAttachments(from urls: [URL]) {
        guard !urls.isEmpty else { return }

        do {
            try FileManager.default.createDirectory(
                at: attachmentStoreURL,
                withIntermediateDirectories: true
            )

            for url in urls where url.isFileURL {
                let attachment = try copyAttachmentIntoStore(url)
                if !pendingAttachments.contains(where: { $0.storedPath == attachment.storedPath }) {
                    pendingAttachments.append(attachment)
                }
            }
        } catch {
            statusTitle = "Attachment failed"
            statusDetail = error.localizedDescription
        }
    }

    private func copyAttachmentIntoStore(_ url: URL) throws -> PendingAttachment {
        let resourceValues = try url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
        guard resourceValues.isRegularFile != false else {
            throw EveAPIError.server("Only files can be attached.")
        }

        let originalName = url.lastPathComponent.isEmpty ? "attachment" : url.lastPathComponent
        let id = UUID().uuidString
        let storedName = "\(id)-\(safeAttachmentFilename(originalName))"
        let destination = attachmentStoreURL.appendingPathComponent(storedName, isDirectory: false)

        if FileManager.default.fileExists(atPath: destination.path) {
            try FileManager.default.removeItem(at: destination)
        }
        try FileManager.default.copyItem(at: url, to: destination)

        return PendingAttachment(
            id: id,
            name: originalName,
            originalPath: url.path,
            storedPath: destination.path,
            byteCount: Int64(resourceValues.fileSize ?? 0),
            typeLabel: attachmentTypeLabel(for: originalName)
        )
    }

    func sendCurrentMessage() async {
        let typedBody = composerText.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !typedBody.isEmpty || !pendingAttachments.isEmpty else { return }

        let attachmentsForSend = pendingAttachments
        let body = typedBody.isEmpty ? "Please inspect the attached file\(attachmentsForSend.count == 1 ? "" : "s")." : typedBody
        let displayBody = messageBodyWithAttachments(
            typedBody.isEmpty ? "Please inspect the attached file\(attachmentsForSend.count == 1 ? "" : "s")." : typedBody,
            attachments: attachmentsForSend
        )
        let draft = typedBody
        let optimisticMessageID = "local-\(UUID().uuidString)"
        let clientRequestID = UUID().uuidString
        let activeThreadID = selectedChatThreadID
        let replyTargetID = chatMessages.last?.id ?? selectedChatThread?.latestMessageId
        isSendingMessage = true
        startReplyStatusProgress(clientRequestID: clientRequestID)
        defer {
            isSendingMessage = false
            stopReplyStatusProgress()
        }

        let subject = composeSubject(from: body)

        composerText = ""
        pendingAttachments = []
        statusTitle = "Sending message"
        statusDetail = "Waiting for Eve's reply from the local runtime."

        if let threadID = activeThreadID {
            chatMessages.append(
                MessageRecord(
                    id: optimisticMessageID,
                    timestamp: ISO8601DateFormatter().string(from: Date()),
                    updatedAt: nil,
                    threadId: threadID,
                    sender: "user",
                    recipient: "eve",
                    subject: subject,
                    body: displayBody,
                    kind: "user_message",
                    status: "sending",
                    replyTo: nil,
                    preview: displayBody
                )
            )
        } else {
            pendingNewChatMessages = [
                MessageRecord(
                    id: optimisticMessageID,
                    timestamp: ISO8601DateFormatter().string(from: Date()),
                    updatedAt: nil,
                    threadId: "pending-new-chat",
                    sender: "user",
                    recipient: "eve",
                    subject: subject,
                    body: displayBody,
                    kind: "user_message",
                    status: "sending",
                    replyTo: nil,
                    preview: displayBody
                )
            ]
        }

        do {
            let attachmentPayloads = attachmentsForSend.map(attachmentPayload)
            if let replyTargetID {
                let payload: [String: Any] = [
                    "message_id": replyTargetID,
                    "body": body,
                    "subject": subject,
                    "client_request_id": clientRequestID,
                    "attachments": attachmentPayloads,
                ]
                let response: ReplyResponse = try await request("/api/message/reply", method: "POST", jsonObject: payload, timeout: 600)
                isDraftingNewChat = false
                await refreshAll(preferredChatThreadID: response.threadId, preferredAgentThreadID: nil)
            } else {
                let payload: [String: Any] = [
                    "body": body,
                    "subject": subject,
                    "client_request_id": clientRequestID,
                    "attachments": attachmentPayloads,
                ]
                let response: ReplyResponse = try await request("/api/message/ask", method: "POST", jsonObject: payload, timeout: 600)
                isDraftingNewChat = false
                await refreshAll(preferredChatThreadID: response.threadId, preferredAgentThreadID: nil)
            }
            pendingNewChatMessages = []
        } catch {
            chatMessages.removeAll { $0.id == optimisticMessageID }
            pendingNewChatMessages = []
            composerText = draft
            pendingAttachments = attachmentsForSend
            statusTitle = "Message failed"
            statusDetail = error.localizedDescription
        }
    }

    func archiveSelectedChatThread() async {
        guard let threadID = selectedChatThreadID else { return }
        isWorking = true
        defer { isWorking = false }

        do {
            let threadMessages: [MessageRecord] = try await request("/api/thread/\(threadID)", timeout: 8)
            for message in threadMessages where message.recipient == "user" && message.status != "archived" {
                let payload: [String: String] = ["status": "archived"]
                let _: MessageRecord = try await request(
                    "/api/messages/\(message.id)/mark",
                    method: "POST",
                    json: payload,
                    timeout: 8
                )
            }
            composerText = ""
            pendingAttachments = []
            clearChatSelection()
            await refreshAll(preferredChatThreadID: nil, preferredAgentThreadID: nil)
        } catch {
            statusTitle = "Archive failed"
            statusDetail = error.localizedDescription
        }
    }

    func displayName(for participant: String) -> String {
        switch participant {
        case "user":
            return "You"
        case "eve":
            return "Eve"
        default:
            let words = participant
                .replacingOccurrences(of: "_", with: " ")
                .split(separator: " ")
                .map { word in
                    let lower = word.lowercased()
                    return lower.prefix(1).uppercased() + lower.dropFirst()
                }
            return words.joined(separator: " ")
        }
    }

    func threadMetaLine(for thread: ThreadSummary) -> String {
        let speaker = displayName(for: thread.latestSender)
        let time = formatDate(thread.latestTimestamp)
        if thread.audience == "agent" {
            return "\(agentParticipantLine(for: thread)) · \(speaker) · \(time)"
        }
        return "\(speaker) · \(time)"
    }

    func presentedSubject(for thread: ThreadSummary) -> String {
        normalizedSubject(thread.subject, fallback: fallbackThreadTitle(for: thread))
    }

    func agentParticipantLine(for thread: ThreadSummary) -> String {
        let names = thread.agentParticipants.map(displayName(for:)).joined(separator: " · ")
        return names.isEmpty ? "No external agents yet" : names
    }

    func threadStatusLabel(_ status: String) -> String {
        switch status {
        case "awaiting_user":
            return "Waiting on you"
        case "active":
            return "Active"
        case "open":
            return "Open"
        case "archived":
            return "Archived"
        case "empty":
            return "Empty"
        default:
            return "Open"
        }
    }

    func formatDate(_ value: String?) -> String {
        guard let value else { return "Unknown" }
        if let cached = formattedDateCache[value] {
            return cached
        }
        guard let date = parseDate(value) else { return "Unknown" }
        let formatted = date.formatted(date: .abbreviated, time: .shortened)
        formattedDateCache[value] = formatted
        return formatted
    }

    private func filteredThreads(_ threads: [ThreadSummary], waitingOnly: Bool) -> [ThreadSummary] {
        let search = normalizedSearchTerm()
        return threads
            .filter { thread in
                waitingOnly ? thread.status == "awaiting_user" : thread.status != "archived"
            }
            .filter { thread in
                guard !search.isEmpty else { return true }
                let haystack = [
                    presentedSubject(for: thread),
                    thread.latestPreview,
                    threadMetaLine(for: thread),
                    thread.participants.map(displayName(for:)).joined(separator: " "),
                ]
                    .joined(separator: " ")
                    .lowercased()
                return haystack.contains(search)
            }
    }

    private func parseDate(_ value: String) -> Date? {
        if let date = isoFormatterWithFractional.date(from: value) {
            return date
        }
        return isoFormatter.date(from: value)
    }

    private func formatLatency(_ value: Double?) -> String {
        guard let value, value > 0 else { return "n/a" }
        if value < 1000 {
            return "\(Int(value.rounded())) ms"
        }
        if value < 10_000 {
            return String(format: "%.1f s", value / 1000)
        }
        return String(format: "%.0f s", value / 1000)
    }

    private func compactUnreadCount(_ count: Int) -> String {
        count > 99 ? "99+" : "\(count)"
    }

    private func fallbackThreadTitle(for thread: ThreadSummary) -> String {
        let preview = thread.latestPreview.trimmingCharacters(in: .whitespacesAndNewlines)
        if !preview.isEmpty {
            return String(preview.prefix(48))
        }
        return thread.audience == "agent" ? "Internal coordination" : "Conversation"
    }

    private func normalizedSubject(_ raw: String?, fallback: String) -> String {
        var subject = raw ?? ""
        subject = subject.replacingOccurrences(
            of: #"^\s*((re|fw|fwd|aw)\s*:\s*)+"#,
            with: "",
            options: [.regularExpression, .caseInsensitive]
        )
        subject = subject.replacingOccurrences(of: #"\s+"#, with: " ", options: .regularExpression)
        subject = subject.trimmingCharacters(in: .whitespacesAndNewlines)
        if subject.isEmpty || subject == "(no subject)" {
            return fallback
        }
        return String(subject.prefix(96))
    }

    func copyCurrentViewSnapshot() {
        let text = currentViewSnapshotText()
        guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
        let pasteboard = NSPasteboard.general
        pasteboard.clearContents()
        pasteboard.setString(text, forType: .string)
        statusTitle = "Copied current view"
        statusDetail = "The visible Eve snapshot is on your clipboard."
    }

    private func chatConversationMeta(for thread: ThreadSummary) -> String {
        var parts = [threadStatusLabel(thread.status)]
        if thread.latestSender == "eve" {
            parts.append("Eve last replied \(formatDate(thread.latestTimestamp))")
        } else if thread.latestSender == "user" {
            parts.append("You last wrote \(formatDate(thread.latestTimestamp))")
        } else {
            parts.append("Updated \(formatDate(thread.latestTimestamp))")
        }
        if thread.unreadCount > 0 {
            parts.append("\(compactUnreadCount(thread.unreadCount)) unread")
        }
        return parts.joined(separator: " · ")
    }

    private func agentConversationMeta(for thread: ThreadSummary) -> String {
        var parts = [agentParticipantLine(for: thread)]
        if let latest = thread.latestTimestamp {
            parts.append("Updated \(formatDate(latest))")
        }
        return parts.joined(separator: " · ")
    }

    private func loadChatThread(threadID: String) async {
        chatLoadGeneration += 1
        let loadGeneration = chatLoadGeneration

        do {
            let threadMessages: [MessageRecord] = try await request("/api/thread/\(threadID)", timeout: 8)
            guard loadGeneration == chatLoadGeneration else { return }
            isDraftingNewChat = false
            pendingNewChatMessages = []
            selectedChatThreadID = threadID
            loadedChatLatestMessageID = threadMessages.last?.id
            chatMessages = threadMessages
        } catch {
            guard loadGeneration == chatLoadGeneration else { return }
            statusTitle = "Could not load chat"
            statusDetail = error.localizedDescription
        }
    }

    private func loadAgentThread(threadID: String) async {
        agentLoadGeneration += 1
        let loadGeneration = agentLoadGeneration

        do {
            let threadMessages: [MessageRecord] = try await request("/api/thread/\(threadID)", timeout: 8)
            guard loadGeneration == agentLoadGeneration else { return }
            selectedAgentThreadID = threadID
            loadedAgentLatestMessageID = threadMessages.last?.id
            agentMessages = threadMessages
        } catch {
            guard loadGeneration == agentLoadGeneration else { return }
            statusTitle = "Could not load agent chat"
            statusDetail = error.localizedDescription
        }
    }

    private func shouldReload(
        thread: ThreadSummary,
        selectedID: String?,
        cachedMessages: [MessageRecord],
        loadedLatestMessageID: String?
    ) -> Bool {
        if selectedID != thread.threadId {
            return true
        }
        if cachedMessages.isEmpty {
            return true
        }
        return loadedLatestMessageID != thread.latestMessageId
    }

    private func chooseThread(
        from threads: [ThreadSummary],
        preferredThreadID: String?,
        selectedThreadID: String?
    ) -> ThreadSummary? {
        if let preferredThreadID, let preferred = threads.first(where: { $0.threadId == preferredThreadID }) {
            return preferred
        }
        if let selectedThreadID, let selected = threads.first(where: { $0.threadId == selectedThreadID }) {
            return selected
        }
        return threads.first(where: { $0.status != "archived" }) ?? threads.first
    }

    private func composeSubject(from body: String) -> String {
        let words = body.split(whereSeparator: \.isWhitespace).prefix(6)
        let subject = words.joined(separator: " ")
        return subject.isEmpty ? "Chat with Eve" : String(subject.prefix(72))
    }

    private func messageBodyWithAttachments(_ body: String, attachments: [PendingAttachment]) -> String {
        guard !attachments.isEmpty else { return body }
        let attachmentLines = attachments.map { attachment in
            "- \(attachment.name) (\(attachment.typeLabel), \(formatAttachmentSize(attachment.byteCount))) stored_at=\(attachment.storedPath) original_path=\(attachment.originalPath)"
        }
        return [
            body,
            "Attached files for Eve to inspect:",
            attachmentLines.joined(separator: "\n"),
        ].joined(separator: "\n\n")
    }

    private func attachmentPayload(_ attachment: PendingAttachment) -> [String: Any] {
        [
            "id": attachment.id,
            "name": attachment.name,
            "original_path": attachment.originalPath,
            "stored_path": attachment.storedPath,
            "byte_count": attachment.byteCount,
            "type_label": attachment.typeLabel,
        ]
    }

    private func safeAttachmentFilename(_ name: String) -> String {
        let cleaned = name.replacingOccurrences(
            of: #"[^A-Za-z0-9._-]+"#,
            with: "-",
            options: .regularExpression
        )
        .trimmingCharacters(in: CharacterSet(charactersIn: ".-"))
        return cleaned.isEmpty ? "attachment" : cleaned
    }

    private func attachmentTypeLabel(for name: String) -> String {
        let ext = URL(fileURLWithPath: name).pathExtension.trimmingCharacters(in: .whitespacesAndNewlines)
        return ext.isEmpty ? "file" : ext.uppercased()
    }

    func formatAttachmentSize(_ byteCount: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: byteCount, countStyle: .file)
    }

    private func currentViewSnapshotText() -> String {
        switch selectedWorkspaceTab {
        case .chats:
            return chatSnapshotText()
        case .agentChats:
            return agentSnapshotText()
        case .thoughts:
            return thoughtsSnapshotText()
        }
    }

    private func chatSnapshotText() -> String {
        let messages = selectedChatThreadID == nil ? pendingNewChatMessages : chatMessages
        let lines = [
            "View: Talk to Eve",
            "Title: \(currentConversationTitle)",
            "Meta: \(currentConversationMeta)",
            "",
            messages.isEmpty
                ? "No messages loaded."
                : messages.map { message in
                    "\(displayName(for: message.sender)) (\(formatDate(message.timestamp))):\n\(message.body)"
                }.joined(separator: "\n\n"),
        ]
        return lines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func agentSnapshotText() -> String {
        let lines = [
            "View: Agent Work",
            "Title: \(currentConversationTitle)",
            "Meta: \(currentConversationMeta)",
            "",
            agentMessages.isEmpty
                ? "No agent messages loaded."
                : agentMessages.map { message in
                    "\(displayName(for: message.sender)) (\(formatDate(message.timestamp))):\n\(message.body)"
                }.joined(separator: "\n\n"),
        ]
        return lines.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func thoughtsSnapshotText() -> String {
        var sections = [
            "View: Mind Activity",
            "Focus: \(activeMindFocus)",
            "Summary: \(activeMindSummary)",
        ]

        if !activeMindLiveThreads.isEmpty {
            sections.append("")
            sections.append("Background focus:")
            sections.append(
                activeMindLiveThreads.map { item in
                    var lines = [
                        "- [\(item.statusLabel)] \(item.kindLabel)"
                            + (item.pressure.map { " · P \($0)" } ?? "")
                            + (item.salience.map { " · S \($0)" } ?? "")
                            + ": \(item.title)"
                            + (item.detail == item.title ? "" : " - \(item.detail)")
                    ]
                    if !item.evidence.isEmpty {
                        lines.append("  Evidence: \(item.evidence.joined(separator: " | "))")
                    }
                    if !item.nextStep.isEmpty {
                        lines.append("  Next: \(item.nextStep)")
                    }
                    if let updatedAt = item.updatedAt {
                        lines.append("  Updated: \(formatDate(updatedAt))")
                    }
                    return lines.joined(separator: "\n")
                }.joined(separator: "\n")
            )
        }
        if !activeMindAuditEvents.isEmpty {
            sections.append("")
            sections.append("Mind audit:")
            sections.append(
                activeMindAuditEvents.map { item in
                    let stamp = formatDate(item.timestamp)
                    return "- \(item.headline) (\(stamp))\(item.detail == item.headline ? "" : ": \(item.detail)")"
                }.joined(separator: "\n")
            )
        }
        if !liveThoughtThreadBeats.isEmpty {
            sections.append("")
            sections.append("Thinking now:")
            sections.append(
                liveThoughtThreadBeats.map { item in
                    let updated = item.updatedAt.map { " (\(formatDate($0)))" } ?? ""
                    return "- [\(item.statusLabel)] \(item.kindLabel): \(item.title)\(updated)\n  \(item.detail)"
                }.joined(separator: "\n")
            )
        }
        if !activeMindConcerns.isEmpty {
            sections.append("Live concerns: " + activeMindConcerns.joined(separator: " | "))
        }
        if !activeMindRelationshipPull.isEmpty {
            sections.append("Relationship pull: " + activeMindRelationshipPull.joined(separator: " | "))
        }
        if !activeMindGroundingNotes.isEmpty {
            sections.append("Grounding notes: " + activeMindGroundingNotes.joined(separator: " | "))
        }
        if !activeMindLaneRows.isEmpty {
            sections.append("")
            sections.append("Mind lanes:")
            sections.append(activeMindLaneRows.map { "\($0.0): \($0.1)" }.joined(separator: "\n"))
        }
        sections.append("")
        sections.append("Next step: \(activeMindNextStep)")

        if !liveThoughtNotes.isEmpty {
            sections.append("")
            sections.append("Current activity notes:")
            sections.append(
                liveThoughtNotes.map { note in
                    let title = (note.title ?? "Thinking...").trimmingCharacters(in: .whitespacesAndNewlines)
                    let detail = (note.detail ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                    let stamp = formatDate(note.timestamp)
                    return detail.isEmpty ? "- \(title) (\(stamp))" : "- \(title) (\(stamp)): \(detail)"
                }.joined(separator: "\n")
            )
        }

        let recentThoughts = Array(visibleThoughts.prefix(8))
        sections.append("")
        sections.append("Saved mind notes:")
        sections.append(
            recentThoughts.isEmpty
                ? "No saved thoughts loaded."
                : recentThoughts.map { thought in
                    "\(formatDate(thought.timestamp)):\n\(thought.body)"
                }.joined(separator: "\n\n")
        )
        return sections.joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func activeMindThreadKindLabel(_ value: String?) -> String {
        switch (value ?? "").lowercased() {
        case "focus":
            return "Focus"
        case "conversation":
            return "Personal context"
        case "concern":
            return "Concern"
        case "relationship":
            return "Relationship"
        case "grounding":
            return "Grounding"
        case "self_check":
            return "Self-check"
        case "next_step":
            return "Next step"
        default:
            return "Focus"
        }
    }

    private func activeMindThreadStatusLabel(_ value: String?) -> String {
        switch (value ?? "").lowercased() {
        case "active":
            return "Active"
        case "waiting":
            return "Waiting"
        case "watching":
            return "Watching"
        case "relating":
            return "Relating"
        case "grounding":
            return "Grounding"
        case "monitoring":
            return "Monitoring"
        case "queued":
            return "Queued"
        default:
            return "Live"
        }
    }

    private func activeMindAuditEventLabel(_ value: String?) -> String {
        switch (value ?? "").lowercased() {
        case "appeared":
            return "appeared"
        case "updated":
            return "shifted"
        case "resolved":
            return "resolved"
        default:
            return "updated"
        }
    }

    private func startRefreshLoop() {
        refreshTask?.cancel()
        refreshTask = Task { [weak self] in
            while let self, !Task.isCancelled {
                let hasLiveThoughtStream = self.liveThoughtStream != nil
                let delay: UInt64
                if self.selectedWorkspaceTab == .thoughts || hasLiveThoughtStream {
                    delay = 2_000_000_000
                } else if NSApp.isActive {
                    delay = 12_000_000_000
                } else {
                    delay = 30_000_000_000
                }
                try? await Task.sleep(nanoseconds: UInt64(delay))
                if Task.isCancelled { break }
                if self.isSendingMessage {
                    continue
                }
                await self.refreshAll(
                    preferredChatThreadID: self.selectedChatThreadID,
                    preferredAgentThreadID: self.selectedAgentThreadID
                )
            }
        }
    }

    private func normalizedSearchTerm() -> String {
        searchText.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }

    private func clearChatSelection(preserveDraftState: Bool = false) {
        chatLoadGeneration += 1
        if !preserveDraftState {
            isDraftingNewChat = false
        }
        pendingNewChatMessages = []
        selectedChatThreadID = nil
        loadedChatLatestMessageID = nil
        chatMessages = []
    }

    private func clearAgentSelection() {
        agentLoadGeneration += 1
        selectedAgentThreadID = nil
        loadedAgentLatestMessageID = nil
        agentMessages = []
    }

    private func isCurrentRefresh(_ refreshID: Int) -> Bool {
        refreshID == refreshGeneration
    }

    private func startReplyStatusProgress(clientRequestID: String) {
        stopReplyStatusProgress()
        activeReplyStatusText = "Eve received your message..."
        activeReplyStatusDetail = "Holding the thread open while the reply starts."
        replyStatusTask = Task { @MainActor [weak self] in
            guard let self else { return }
            let encodedRequestID = clientRequestID.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? clientRequestID
            while self.isSendingMessage && !Task.isCancelled {
                do {
                    let lookup: ReplyProgressLookup = try await self.request(
                        "/api/reply-progress?client_request_id=\(encodedRequestID)",
                        timeout: 2
                    )
                    guard self.isSendingMessage, !Task.isCancelled else { return }
                    if let job = lookup.job {
                        let title = (job.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                        let detail = (job.detail ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                        if !title.isEmpty {
                            self.activeReplyStatusText = title
                        }
                        self.activeReplyStatusDetail = detail
                        self.activeReplyNotes = Array((job.notes ?? []).suffix(5))
                    }
                } catch {
                    guard self.isSendingMessage, !Task.isCancelled else { return }
                }
                try? await Task.sleep(nanoseconds: 650_000_000)
            }
            if let activeReply = self.currentStatus?.activeReply {
                let title = (activeReply.title ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                let detail = (activeReply.detail ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                if !title.isEmpty {
                    self.activeReplyStatusText = title
                }
                if !detail.isEmpty {
                    self.activeReplyStatusDetail = detail
                }
                self.activeReplyNotes = Array((activeReply.notes ?? []).suffix(5))
            }
        }
    }

    private func stopReplyStatusProgress() {
        replyStatusTask?.cancel()
        replyStatusTask = nil
        activeReplyStatusText = ""
        activeReplyStatusDetail = ""
        activeReplyNotes = []
    }

    private func runHelper(_ argument: String) {
        guard FileManager.default.isExecutableFile(atPath: helperURL.path) else { return }
        let helperPath = helperURL.path
        DispatchQueue.global(qos: .userInitiated).async {
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/bin/zsh")
            process.arguments = [helperPath, argument]
            try? process.run()
        }
    }

    private func request<Payload: Decodable>(
        _ path: String,
        method: String = "GET",
        json: [String: String]? = nil,
        timeout: TimeInterval
    ) async throws -> Payload {
        let bodyData = try json.map { try JSONSerialization.data(withJSONObject: $0) }
        return try await request(path, method: method, bodyData: bodyData, timeout: timeout)
    }

    private func request<Payload: Decodable>(
        _ path: String,
        method: String = "GET",
        jsonObject: [String: Any],
        timeout: TimeInterval
    ) async throws -> Payload {
        let bodyData = try JSONSerialization.data(withJSONObject: jsonObject)
        return try await request(path, method: method, bodyData: bodyData, timeout: timeout)
    }

    private func request<Payload: Decodable>(
        _ path: String,
        method: String = "GET",
        bodyData: Data?,
        timeout: TimeInterval
    ) async throws -> Payload {
        guard let url = URL(string: path, relativeTo: baseURL) else {
            throw EveAPIError.invalidResponse
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = timeout
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = bodyData

        let (data, response) = try await URLSession.shared.data(for: request)
        guard let httpResponse = response as? HTTPURLResponse, (200..<300).contains(httpResponse.statusCode) else {
            if let envelope = try? decoder.decode(APIEnvelope<Payload>.self, from: data), let error = envelope.error {
                throw EveAPIError.server(error)
            }
            throw EveAPIError.invalidResponse
        }

        let envelope = try decoder.decode(APIEnvelope<Payload>.self, from: data)
        guard envelope.ok else {
            throw EveAPIError.server(envelope.error ?? "Request failed")
        }
        guard let payload = envelope.data else {
            throw EveAPIError.invalidResponse
        }
        return payload
    }
}
