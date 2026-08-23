import AppKit
import Combine
import Foundation
import SwiftUI

struct APIEnvelope<Payload: Decodable>: Decodable {
    let ok: Bool
    let data: Payload?
    let error: String?
}

struct EveCounts: Decodable, Equatable {
    let threads: Int?
    let activeThreads: Int?
    let waitingThreads: Int?
    let unreadMessages: Int?
    let thoughts: Int?
}

struct EveDaemonState: Decodable, Equatable {
    let running: Bool
    let awake: Bool
}

struct EveLoopState: Decodable, Equatable {
    let currentFocus: String?
}

struct EveSelfModel: Decodable, Equatable {
    let identityStatement: String?
    let currentPreoccupations: [String]?
    let groundingPractices: [String]?
}

struct EveRelationshipMemory: Decodable, Equatable {
    let userOverview: String?
    let requestedPractices: [String]?
    let openLoops: [String]?
}

struct EveHumanContext: Decodable, Equatable {
    let updatedAt: String?
    let selfModel: EveSelfModel?
    let relationshipMemory: EveRelationshipMemory?
}

struct EveModelProbe: Decodable, Equatable {
    let ok: Bool?
    let wallMs: Double?
    let signal: String?
    let cached: Bool?
}

struct EveModelResidency: Decodable, Equatable {
    let preferredFastLoaded: Bool?
    let preferredDeepLoaded: Bool?
    let bothPreferredLoaded: Bool?
}

struct EveLoadedModel: Decodable, Equatable {
    let name: String?
    let contextLength: Int?
    let sizeVram: Int?
    let expiresAt: String?
}

struct EveModelProbes: Decodable, Equatable {
    let fast: EveModelProbe?
    let deep: EveModelProbe?
}

struct EveModelHealth: Decodable, Equatable {
    let updatedAt: String?
    let preferredFastModel: String?
    let preferredDeepModel: String?
    let effectiveFastModel: String?
    let effectiveDeepModel: String?
    let effectiveFallbackModel: String?
    let summary: String?
    let residency: EveModelResidency?
    let loadedModels: [EveLoadedModel]?
    let probes: EveModelProbes?
    let recentActions: [String]?
}

struct EveStatusData: Decodable, Equatable {
    let apiVersion: Int
    let counts: EveCounts
    let daemon: EveDaemonState
    let state: EveLoopState
    let activeMind: EveActiveMind?
    let activeMindAudit: [EveActiveMindAuditEvent]?
    let ambientThought: EveAmbientThought?
    let activeReply: EveReplyProgress?
    let humanContext: EveHumanContext?
    let modelHealth: EveModelHealth?
}

struct EveActiveMindLanes: Decodable, Equatable {
    let observer: String?
    let planner: String?
    let relationship: String?
    let grounding: String?
    let selfCheck: String?
}

struct EveActiveMindThread: Decodable, Equatable, Hashable {
    let title: String?
    let detail: String?
    let kind: String?
    let status: String?
    let salience: Int?
    let pressure: Int?
    let lastUpdated: String?
    let evidence: [String]?
    let nextStep: String?
}

struct EveActiveMindAuditEvent: Decodable, Equatable, Hashable {
    let id: String?
    let timestamp: String?
    let source: String?
    let eventKind: String?
    let title: String?
    let detail: String?
    let threadKind: String?
    let threadStatus: String?
    let summary: String?
}

struct EveActiveMind: Decodable, Equatable {
    let updatedAt: String?
    let source: String?
    let model: String?
    let summary: String?
    let currentFocus: String?
    let liveConcerns: [String]?
    let activeThreads: [String]?
    let liveThreads: [EveActiveMindThread]?
    let relationshipPull: [String]?
    let groundingNotes: [String]?
    let lanes: EveActiveMindLanes?
    let nextStep: String?
}

struct EveAmbientThought: Decodable, Equatable {
    let updatedAt: String?
    let status: String?
    let title: String?
    let detail: String?
    let model: String?
    let source: String?
    let threadBeats: [EveAmbientThreadBeat]?
    let notes: [EveReplyProgressNote]?
}

struct EveAmbientThreadBeat: Decodable, Equatable, Hashable {
    let sourceId: String?
    let threadTitle: String?
    let threadKind: String?
    let threadStatus: String?
    let title: String?
    let detail: String?
    let updatedAt: String?
}

struct EveReplyProgress: Decodable, Equatable {
    let id: String?
    let clientRequestId: String?
    let threadId: String?
    let sourceMessageId: String?
    let recipient: String?
    let counterpartLabel: String?
    let status: String?
    let phase: String?
    let title: String?
    let detail: String?
    let step: Int?
    let totalSteps: Int?
    let startedAt: String?
    let updatedAt: String?
    let finishedAt: String?
    let requestedModel: String?
    let currentModel: String?
    let fallbackModel: String?
    let replyMessageId: String?
    let notes: [EveReplyProgressNote]?
}

struct EveReplyProgressNote: Decodable, Equatable, Hashable {
    let id: String?
    let timestamp: String?
    let phase: String?
    let kind: String?
    let title: String?
    let detail: String?
}

struct ReplyProgressLookup: Decodable {
    let job: EveReplyProgress?
}

struct ThreadSummary: Decodable, Identifiable, Hashable {
    let threadId: String
    let subject: String
    let latestTimestamp: String?
    let latestPreview: String
    let latestSender: String
    let latestMessageId: String?
    let messageCount: Int
    let unreadCount: Int
    let status: String
    let attentionScore: Int?
    let participants: [String]
    let agentParticipants: [String]
    let audience: String

    var id: String { threadId }
}

struct MessageRecord: Decodable, Identifiable, Hashable {
    let id: String
    let timestamp: String
    let updatedAt: String?
    let threadId: String
    let sender: String
    let recipient: String
    let subject: String
    let body: String
    let kind: String
    let status: String
    let replyTo: String?
    let preview: String
    let metadata: MessageMetadata?

    var attachments: [MessageAttachmentRecord] {
        metadata?.attachments ?? []
    }

    init(
        id: String,
        timestamp: String,
        updatedAt: String?,
        threadId: String,
        sender: String,
        recipient: String,
        subject: String,
        body: String,
        kind: String,
        status: String,
        replyTo: String?,
        preview: String,
        metadata: MessageMetadata? = nil
    ) {
        self.id = id
        self.timestamp = timestamp
        self.updatedAt = updatedAt
        self.threadId = threadId
        self.sender = sender
        self.recipient = recipient
        self.subject = subject
        self.body = body
        self.kind = kind
        self.status = status
        self.replyTo = replyTo
        self.preview = preview
        self.metadata = metadata
    }

    enum CodingKeys: String, CodingKey {
        case id
        case timestamp
        case updatedAt
        case threadId
        case sender
        case recipient
        case subject
        case body
        case kind
        case status
        case replyTo
        case preview
        case metadata
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        timestamp = try container.decode(String.self, forKey: .timestamp)
        updatedAt = try container.decodeIfPresent(String.self, forKey: .updatedAt)
        threadId = try container.decode(String.self, forKey: .threadId)
        sender = try container.decode(String.self, forKey: .sender)
        recipient = try container.decode(String.self, forKey: .recipient)
        subject = try container.decode(String.self, forKey: .subject)
        body = try container.decode(String.self, forKey: .body)
        kind = try container.decode(String.self, forKey: .kind)
        status = try container.decode(String.self, forKey: .status)
        replyTo = try container.decodeIfPresent(String.self, forKey: .replyTo)
        preview = try container.decode(String.self, forKey: .preview)
        metadata = try container.decodeIfPresent(MessageMetadata.self, forKey: .metadata)
    }
}

struct MessageMetadata: Decodable, Hashable {
    let attachments: [MessageAttachmentRecord]?
}

struct MessageAttachmentRecord: Decodable, Identifiable, Hashable {
    let id: String
    let name: String
    let originalPath: String?
    let storedPath: String?
    let byteCount: Int64?
    let typeLabel: String?
    let mimeType: String?
    let sha256: String?
    let createdAt: String?
    let messageId: String?
    let threadId: String?
    let extractionStatus: String?
    let extractedTextPath: String?
    let extractedCharCount: Int?
    let textPreview: String?
    let localOnly: Bool?
    let intakePolicy: String?
}

struct ThoughtEntry: Decodable, Identifiable, Hashable {
    let id: String
    let timestamp: String
    let kind: String
    let body: String
    let preview: String
}

struct ReplyResponse: Decodable {
    let threadId: String
    let messages: [MessageRecord]
}

enum EveAPIError: LocalizedError {
    case invalidResponse
    case server(String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse:
            return "Invalid response from Eve."
        case .server(let message):
            return message
        }
    }
}

enum WorkspaceTab: String, CaseIterable, Identifiable {
    case chats = "Chats"
    case agentChats = "Agents"
    case thoughts = "Thoughts"

    var id: String { rawValue }

    var displayTitle: String {
        switch self {
        case .chats:
            return "Talk to Eve"
        case .agentChats:
            return "Agent Work"
        case .thoughts:
            return "Mind Activity"
        }
    }

    var iconName: String {
        switch self {
        case .chats:
            return "bubble.left.and.bubble.right"
        case .agentChats:
            return "person.2.wave.2"
        case .thoughts:
            return "sparkles"
        }
    }

    var emptyTitle: String {
        switch self {
        case .chats:
            return "Talk to Eve"
        case .agentChats:
            return "No internal agent work yet"
        case .thoughts:
            return "No mind activity yet"
        }
    }

    var emptyDetail: String {
        switch self {
        case .chats:
            return "This is the personal conversation surface. Eve's background focus and agent work stay separate."
        case .agentChats:
            return "When Eve coordinates with agents or tools, that internal work will appear here without mixing into personal chat."
        case .thoughts:
            return "Eve's background focus, checks, and saved mind notes will appear here as runtime evidence."
        }
    }
}

enum EveTheme {
    static let appBackground = Color(nsColor: NSColor(calibratedRed: 0.102, green: 0.102, blue: 0.108, alpha: 1))
    static let sidebarBackground = Color(nsColor: NSColor(calibratedRed: 0.096, green: 0.096, blue: 0.102, alpha: 1))
    static let detailBackground = Color(nsColor: NSColor(calibratedRed: 0.118, green: 0.118, blue: 0.124, alpha: 1))
    static let surface = Color.white.opacity(0.04)
    static let surfaceRaised = Color.white.opacity(0.065)
    static let surfaceSoft = Color.white.opacity(0.022)
    static let divider = Color.white.opacity(0.085)
    static let textPrimary = Color.white.opacity(0.96)
    static let textSecondary = Color.white.opacity(0.72)
    static let textTertiary = Color.white.opacity(0.48)
    static let accent = Color.accentColor
    static let accentSoft = accent.opacity(0.18)
}

struct VisualEffectGlassView: NSViewRepresentable {
    let material: NSVisualEffectView.Material

    func makeNSView(context: Context) -> NSVisualEffectView {
        let view = NSVisualEffectView()
        view.material = material
        view.blendingMode = .withinWindow
        view.state = .active
        view.isEmphasized = false
        view.appearance = NSAppearance(named: .vibrantDark)
        return view
    }

    func updateNSView(_ nsView: NSVisualEffectView, context: Context) {
        nsView.material = material
        nsView.state = .active
    }
}

struct GlassPanelBackground: View {
    let material: NSVisualEffectView.Material
    let cornerRadius: CGFloat
    var shadowOpacity: Double = 0.22

    var body: some View {
        VisualEffectGlassView(material: material)
            .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            .overlay(
                LinearGradient(
                    colors: [
                        Color.white.opacity(0.16),
                        Color.white.opacity(0.04),
                        Color.clear,
                    ],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )
                .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
            )
            .overlay(
                RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                    .stroke(Color.white.opacity(0.09), lineWidth: 1)
            )
            .shadow(color: Color.black.opacity(shadowOpacity), radius: 18, y: 10)
    }
}

struct WindowAccessorView: NSViewRepresentable {
    let title: String

    final class Coordinator {
        weak var window: NSWindow?
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeNSView(context: Context) -> NSView {
        NSView()
    }

    func updateNSView(_ nsView: NSView, context: Context) {
        guard let window = nsView.window else { return }
        if context.coordinator.window !== window {
            context.coordinator.window = window
            configureWindow(window)
        }
        updateTitle(for: window)
    }

    private func configureWindow(_ window: NSWindow) {
        window.styleMask.insert(.fullSizeContentView)
        window.titlebarAppearsTransparent = true
        window.titleVisibility = .hidden
        window.titlebarSeparatorStyle = .none
        window.isOpaque = false
        window.backgroundColor = .clear
        window.toolbarStyle = .unifiedCompact
        window.isMovableByWindowBackground = true
        let currentSize = window.frame.size
        if currentSize.width < 1180 || currentSize.height < 780 {
            let targetSize = NSSize(width: 1280, height: 860)
            window.setContentSize(targetSize)
            window.center()
        }
    }

    private func updateTitle(for window: NSWindow) {
        if !window.title.isEmpty {
            window.title = ""
        }
    }
}
