import AppKit
import Combine
import Foundation

struct MonitorEnvelope<Payload: Decodable>: Decodable {
    let ok: Bool
    let data: Payload?
    let error: String?
}

struct EveMonitorPayload: Decodable, Equatable {
    let generatedAt: String?
    let status: MonitorStatus?
    let state: MonitorRuntimeState?
    let workspace: MonitorWorkspace?
    let homeostasis: MonitorHomeostasis?
    let governance: MonitorGovernance?
    let fitness: MonitorFitness?
    let activity: MonitorActivity?
    let humanContextSignals: MonitorHumanContextSignals?
    let autonomy: MonitorAutonomy?
    let substrate: MonitorSubstrate?
    let operations: MonitorOperations?
    let conversationSpine: [MonitorConversationTurn]?
    let replyCouncilTurns: [MonitorReplyCouncilTurn]?
}

struct MonitorStatus: Decodable, Equatable {
    let apiVersion: Int?
    let humanContextSignals: MonitorHumanContextSignals?
    let counts: MonitorCounts?
    let daemon: MonitorDaemon?
    let activeReply: MonitorReply?
    let modelHealth: MonitorModelHealth?
    let threadAttention: [MonitorThread]?
}

struct MonitorCounts: Decodable, Equatable {
    let activeThreads: Int?
    let waitingThreads: Int?
    let unreadMessages: Int?
}

struct MonitorDaemon: Decodable, Equatable {
    let running: Bool?
    let awake: Bool?
    let runtimeDir: String?
}

struct MonitorRuntimeState: Decodable, Equatable {
    let serviceHealthSummary: String?
    let openclawSummary: String?
    let systemSummary: String?
    let lastLoopAt: String?
    let lastHeartbeatAt: String?
    let lastPersonalConversationStatus: String?
    let lastPersonalConversationReason: String?
}

struct MonitorReply: Decodable, Equatable {
    let id: String?
    let status: String?
    let phase: String?
    let title: String?
    let detail: String?
    let currentModel: String?
    let updatedAt: String?
}

struct MonitorHumanContextSignals: Decodable, Equatable, Hashable {
    let updatedAt: String?
    let source: String?
    let trust: [String]?
    let repair: [String]?
    let antiSycophancy: [String]?
    let episodicMarkers: [String]?
    let openLoops: [String]?
}

struct MonitorModelHealth: Decodable, Equatable {
    let updatedAt: String?
    let summary: String?
    let lanes: [MonitorLane]?
    let loadedModels: [MonitorLoadedModel]?
    let probes: MonitorLegacyProbes?
}

struct MonitorLane: Decodable, Identifiable, Equatable, Hashable {
    let lane: String?
    let label: String?
    let model: String?
    let host: String?
    let backend: String?
    let loaded: Bool?
    let latencyMs: Double?

    var id: String {
        lane ?? label ?? model ?? "\(backend ?? "lane")-\(host ?? "local")"
    }
}

struct MonitorLoadedModel: Decodable, Identifiable, Equatable, Hashable {
    let name: String?
    let backend: String?
    let host: String?
    let contextLength: Int?
    let sizeVram: Int?

    var id: String {
        name ?? "\(backend ?? "model")-\(host ?? "local")-\(contextLength ?? 0)"
    }
}

struct MonitorLegacyProbes: Decodable, Equatable {
    let fast: MonitorProbe?
    let deep: MonitorProbe?
}

struct MonitorProbe: Decodable, Equatable {
    let ok: Bool?
    let wallMs: Double?
}

struct MonitorWorkspace: Decodable, Equatable {
    let updatedAt: String?
    let summary: String?
    let currentExperience: String?
    let dominantPressures: [String]?
    let workspaceState: MonitorWorkspaceState?
    let continuityThreads: [String]?
    let surpriseSignals: [String]?
    let consequenceTrace: [String]?
    let actionReadiness: [String]?
    let nextRefresh: String?
}

struct MonitorWorkspaceState: Decodable, Equatable {
    let focus: String?
    let mode: String?
    let frontmostApp: String?
    let loadState: String?
}

struct MonitorHomeostasis: Decodable, Equatable {
    let updatedAt: String?
    let summary: String?
    let regulationMode: String?
    let pressures: [MonitorPressure]?
    let discountedSignals: [MonitorDiscountedSignal]?
    let dominantPressures: [String]?
    let nextRegulationStep: String?
}

struct MonitorGovernance: Decodable, Equatable {
    let schemaVersion: String?
    let generatedAt: String?
    let proposalCount: Int?
    let decisionCounts: [String: Int]?
    let typeCounts: [String: Int]?
    let approvalCounts: [String: Int]?
    let canaryCounts: [String: Int]?
    let applicationCounts: [String: Int]?
    let watcherStatus: String?
    let watcherWarningCount: Int?
    let blockingWarningCount: Int?
    let watchers: [MonitorGovernanceWatcher]?
}

struct MonitorGovernanceWatcher: Decodable, Identifiable, Equatable, Hashable {
    let id: String
    let title: String?
    let status: String?
    let maxSeverity: Int?
    let warningCount: Int?
}

struct MonitorFitness: Decodable, Equatable {
    let wholeSystem: MonitorWholeSystemFitness?
    let longRun: MonitorLongRunFitness?
    let manualProbe: MonitorManualProbeFitness?
    let roadmap: MonitorRoadmapFitness?
}

struct MonitorWholeSystemFitness: Decodable, Equatable {
    let status: String?
    let passed: Bool?
    let averageScore: Double?
    let checkCount: Int?
    let failingCheckCount: Int?
    let missingComponentCounts: [String: Int]?
    let finishedAt: String?
    let artifactPath: String?
    let failingChecks: [MonitorFitnessCheck]?
}

struct MonitorFitnessRank: Decodable, Equatable, Hashable {
    let label: String?
    let value: Int?
    let averageScore: Double?
    let minimumScore: Int?
}

struct MonitorLongRunFitness: Decodable, Equatable {
    let status: String?
    let passed: Bool?
    let evaluatedAt: String?
    let windowMinutes: Int?
    let rank: MonitorFitnessRank?
    let runCount: Int?
    let actionTotal: Int?
    let failureRate: Double?
    let verifiedActionRatio: Double?
    let successfulCapabilityCount: Int?
    let artifactPath: String?
    let metrics: [MonitorFitnessMetric]?
}

struct MonitorManualProbeFitness: Decodable, Equatable {
    let passed: Bool?
    let evaluatedAt: String?
    let rank: MonitorFitnessRank?
    let probeCount: Int?
    let hiddenProbeCount: Int?
    let blockerCount: Int?
    let artifactPath: String?
}

struct MonitorRoadmapFitness: Decodable, Equatable {
    let status: String?
    let generatedAt: String?
    let firstPriority: String?
    let wholeSystemStatus: String?
    let wholeSystemAverageScore: Double?
    let openTasks: Int?
    let openCapabilityGaps: Int?
    let latestEvalGaps: Int?
    let priorityQueue: [MonitorRoadmapPriority]?
    let error: String?
}

struct MonitorRoadmapPriority: Decodable, Identifiable, Equatable, Hashable {
    let priority: String?
    let title: String?
    let status: String?
    let nextAction: String?

    var id: String {
        "\(priority ?? "priority")-\(title ?? "roadmap")"
    }
}

struct MonitorFitnessCheck: Decodable, Identifiable, Equatable, Hashable {
    let testId: String?
    let layer: String?
    let title: String?
    let status: String?
    let score: Double?
    let nextAction: String?

    var id: String {
        testId ?? "\(layer ?? "check")-\(title ?? "fitness")"
    }
}

struct MonitorFitnessMetric: Decodable, Identifiable, Equatable, Hashable {
    let name: String?
    let status: String?
    let score: Int?
    let issue: String?
    let nextAction: String?

    var id: String {
        name ?? "\(status ?? "metric")-\(score ?? 0)"
    }
}

struct MonitorPressure: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let label: String?
    let level: Int?
    let trend: String?
    let reason: String?
    let signalCount: Int?
}

struct MonitorDiscountedSignal: Decodable, Equatable, Hashable {
    let id: String?
    let label: String?
    let count: Int?
    let pressureId: String?
    let disposition: String?
    let reason: String?
}

struct MonitorPressureSample: Identifiable, Equatable, Hashable {
    let id = UUID()
    let timestamp: Date
    let pressureID: String
    let label: String
    let level: Int
}

struct MonitorActivity: Decodable, Equatable {
    let updatedAt: String?
    let models: MonitorActivityModels?
    let system: MonitorSystemActivity?
}

struct MonitorActivityModels: Decodable, Equatable {
    let summary: String?
    let activeCalls: [MonitorModelCall]?
    let recentCalls: [MonitorModelCall]?
    let lanes: [MonitorActivityLane]?
}

struct MonitorModelCall: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let timestamp: String?
    let startedAt: String?
    let updatedAt: String?
    let operation: String?
    let backend: String?
    let model: String?
    let host: String?
    let status: String?
    let durationMs: Double?
    let elapsedMs: Double?
    let ok: Bool?
    let messageCount: Int?
    let maxTokens: Int?
    let responseChars: Int?
    let charsPerSecond: Double?
    let error: String?
}

struct MonitorActivityLane: Decodable, Identifiable, Equatable, Hashable {
    let lane: String?
    let label: String?
    let model: String?
    let host: String?
    let backend: String?
    let loaded: Bool?
    let state: String?
    let operation: String?
    let latencyMs: Double?
    let elapsedMs: Double?
    let durationMs: Double?
    let charsPerSecond: Double?
    let lastOk: Bool?

    var id: String {
        lane ?? label ?? model ?? "\(backend ?? "lane")-\(host ?? "local")"
    }
}

struct MonitorSystemActivity: Decodable, Equatable {
    let cpuPercent: Double?
    let cpuCount: Int?
    let loadAverage: [Double]?
    let memory: MonitorMemorySnapshot?
    let disk: MonitorDiskSnapshot?
    let processes: [MonitorProcess]?
    let processCount: Int?
}

struct MonitorMemorySnapshot: Decodable, Equatable, Hashable {
    let totalBytes: Int?
    let usedBytes: Int?
    let freeBytes: Int?
    let usedPercent: Double?
    let pageSize: Int?
}

struct MonitorDiskSnapshot: Decodable, Equatable, Hashable {
    let path: String?
    let totalBytes: Int?
    let usedBytes: Int?
    let freeBytes: Int?
    let usedPercent: Double?
}

struct MonitorProcess: Decodable, Identifiable, Equatable, Hashable {
    let pid: Int?
    let ppid: Int?
    let title: String?
    let kind: String?
    let cpuPercent: Double?
    let memoryBytes: Int?
    let command: String?

    var id: String { "\(pid ?? 0)-\(title ?? "process")" }
}

struct MonitorResourceSample: Identifiable, Equatable, Hashable {
    let id = UUID()
    let timestamp: Date
    let cpuPercent: Double
    let memoryPercent: Double
}

enum MonitorServiceState: String, Equatable, Hashable {
    case online
    case offline
    case warning
    case unknown
}

struct MonitorServiceProbe: Equatable, Hashable {
    let online: Bool
    let detail: String
    let checkedAt: Date
}

struct MonitorServiceRow: Identifiable, Equatable, Hashable {
    let id: String
    let group: String
    let title: String
    let detail: String
    let metadata: String
    let systemImage: String
    let state: MonitorServiceState
}

struct MonitorAutonomy: Decodable, Equatable {
    let state: MonitorAutonomyState?
    let agenda: MonitorAutonomyAgenda?
    let runs: [MonitorAutonomyRun]?
}

struct MonitorAutonomyState: Decodable, Equatable {
    let stage: String?
    let updatedAt: String?
    let note: String?
}

struct MonitorAutonomyAgenda: Decodable, Equatable {
    let updatedAt: String?
    let summary: String?
    let currentFocus: String?
    let activeThreads: [MonitorAutonomyThread]?
    let lastSupervisor: MonitorSupervisor?
    let nextExperiments: [MonitorAutonomyExperiment]?
}

struct MonitorAutonomyThread: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let title: String?
    let family: String?
    let why: String?
    let evidence: String?
    let status: String?
    let preferredAction: String?
    let priority: Int?
    let updatedAt: String?
}

struct MonitorAutonomyExperiment: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let title: String?
    let why: String?
    let preferredAction: String?
    let family: String?
    let status: String?
    let updatedAt: String?
}

struct MonitorSupervisor: Decodable, Equatable, Hashable {
    let score: Int?
    let verdict: String?
    let issues: [String]?
    let strengths: [String]?
}

struct MonitorAutonomyRun: Decodable, Identifiable, Equatable, Hashable {
    let runId: String?
    let style: String?
    let source: String?
    let startedAt: String?
    let finishedAt: String?
    let objective: String?
    let actionCount: Int?
    let claimAuditCount: Int?
    let supervisor: MonitorSupervisor?

    var id: String {
        runId ?? "\(source ?? "run")-\(startedAt ?? finishedAt ?? objective ?? "pending")"
    }
}

struct MonitorSubstrate: Decodable, Equatable {
    let evidence: [MonitorEvidence]?
    let commitments: [MonitorCommitment]?
    let experience: [MonitorExperience]?
}

struct MonitorEvidence: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let observedAt: String?
    let source: String?
    let kind: String?
    let status: String?
    let claim: String?
    let summary: String?
    let confidence: Double?
    let freshness: Int?
    let actionability: String?
}

struct MonitorCommitment: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let updatedAt: String?
    let source: String?
    let kind: String?
    let status: String?
    let text: String?
    let action: String?
    let resultSummary: String?
    let verification: String?
}

struct MonitorExperience: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let timestamp: String?
    let eventType: String?
    let source: String?
    let actor: String?
    let subject: String?
    let summary: String?
    let result: String?
    let learning: String?
}

struct MonitorOperations: Decodable, Equatable {
    let actions: [MonitorAction]?
    let systemTasks: [MonitorSystemTask]?
}

struct MonitorAction: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let createdAt: String?
    let updatedAt: String?
    let action: String?
    let source: String?
    let treeStatus: String?
    let verificationOk: Bool?
    let resultOk: Bool?
    let typedContractOk: Bool?
    let summary: String?
}

struct MonitorSystemTask: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let updatedAt: String?
    let kind: String?
    let title: String?
    let summary: String?
    let status: String?
    let lane: String?
    let priority: Int?
}

struct MonitorThread: Decodable, Identifiable, Equatable, Hashable {
    let threadId: String?
    let subject: String?
    let latestTimestamp: String?
    let latestPreview: String?
    let latestSender: String?
    let messageCount: Int?
    let unreadCount: Int?
    let status: String?
    let attentionScore: Int?

    var id: String {
        threadId ?? "\(subject ?? "thread")-\(latestTimestamp ?? latestPreview ?? "latest")"
    }
}

struct MonitorConversationTurn: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let timestamp: String?
    let createdAt: String?
    let traceId: String?
    let threadId: String?
    let messageId: String?
    let replyTo: String?
    let role: String?
    let direction: String?
    let sender: String?
    let recipient: String?
    let kind: String?
    let subject: String?
    let bodyPreview: String?
    let source: String?
    let sourceLedger: String?
    let sourceMessageId: String?
    let replyTurnReplayId: String?
    let replyCouncilTurnId: String?
    let synthetic: Bool?
    let conversationVisible: Bool?
    let privacyTier: String?
    let model: String?
    let runtime: String?

    var stableID: String {
        id ?? "\(threadId ?? "thread")-\(messageId ?? timestamp ?? "turn")"
    }
}

enum MonitorChatRole: String, Equatable, Hashable {
    case eve
    case user
    case system
}

struct MonitorChatLaneVoice: Identifiable, Equatable, Hashable {
    let id: String
    let title: String
    let detail: String
    let body: String

    static let welcome: [MonitorChatLaneVoice] = [
        MonitorChatLaneVoice(
            id: "fast",
            title: "Fast",
            detail: "ready - eve-fast",
            body: "Keeps the exchange moving and turns the first useful answer into words."
        ),
        MonitorChatLaneVoice(
            id: "deep",
            title: "Deep",
            detail: "ready - eve-deep",
            body: "Checks uncertainty, risk, and whether the answer needs a slower pass."
        ),
        MonitorChatLaneVoice(
            id: "observer",
            title: "Observer",
            detail: "ready - eve-observer",
            body: "Looks for the current evidence instead of guessing from tone alone."
        ),
        MonitorChatLaneVoice(
            id: "planner",
            title: "Planner",
            detail: "ready - eve-planner",
            body: "Names the next move only when the conversation gives enough signal."
        ),
        MonitorChatLaneVoice(
            id: "relationship",
            title: "Relationship",
            detail: "ready - eve-relationship",
            body: "Keeps continuity with you and makes the reply land like one Eve."
        )
    ]
}

struct MonitorChatMessage: Identifiable, Equatable, Hashable {
    let id: String
    let role: MonitorChatRole
    let metadata: String
    let body: String
    let laneVoices: [MonitorChatLaneVoice]
    let laneBadge: String
    let sharedReplyLabel: String

    init(
        id: String,
        role: MonitorChatRole,
        metadata: String,
        body: String,
        laneVoices: [MonitorChatLaneVoice] = [],
        laneBadge: String = "5 lanes",
        sharedReplyLabel: String = "Shared reply"
    ) {
        self.id = id
        self.role = role
        self.metadata = metadata
        self.body = body
        self.laneVoices = laneVoices
        self.laneBadge = laneBadge
        self.sharedReplyLabel = sharedReplyLabel
    }
}

struct MonitorMessageMetadata: Decodable, Equatable, Hashable {
    let model: String?
    let requestedModel: String?
    let streamReplyUsed: Bool?
    let streamTurnId: String?
    let streamPacketCount: Int?
    let streamErrors: [String]?
    let streamParallelEnabled: Bool?
    let streamModels: [String: String]?
    let streamSynthesisModel: String?
    let humanityAdvisoryUsed: Bool?
    let humanityAdvisoryModels: [String: String]?
}

struct MonitorReplyCouncilTurn: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let createdAt: String?
    let threadId: String?
    let sourceMessageId: String?
    let replyMessageId: String?
    let replyTurnReplayId: String?
    let intent: String?
    let currentTopic: String?
    let shortFollowup: Bool?
    let episodeBoundary: Bool?
    let usedModel: String?
    let streamReplyUsed: Bool?
    let streamTurnId: String?
    let selectedStreamLanes: [String]?
    let synthesisModel: String?
    let activeLanes: [String]?
    let abstainedLanes: [String]?
    let deferredLanes: [String]?
    let reason: String?
    let lanes: [MonitorReplyCouncilLane]?
    let neededRepair: Bool?
    let repairSignals: MonitorReplyCouncilRepairSignals?
    let inboundPreview: String?
    let replyPreview: String?
}

struct MonitorReplyCouncilLane: Decodable, Identifiable, Equatable, Hashable {
    let lane: String?
    let model: String?
    let pressure: Double?
    let threshold: Double?
    let stance: String?
    let selected: Bool?
    let reasons: [String]?
    let quarantined: Bool?

    var id: String {
        lane ?? model ?? stance ?? "lane"
    }
}

struct MonitorReplyCouncilRepairSignals: Decodable, Equatable, Hashable {
    let qualityIssues: [String]?
    let semanticIssues: [String]?
    let rewriteApplied: Bool?
    let actionClaimGroundingApplied: Bool?
    let fallbackUsed: Bool?
    let streamErrors: [String]?
}

struct MonitorReplyStreamRecord: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let timestamp: String?
    let turnId: String?
    let stream: String?
    let packet: MonitorReplyStreamPacket?
    let metadata: MonitorReplyStreamMetadata?

    var stableID: String {
        id ?? "\(turnId ?? "turn")-\(stream ?? packet?.stream ?? "stream")-\(timestamp ?? metadata?.model ?? "packet")"
    }
}

struct MonitorReplyStreamPacket: Decodable, Equatable, Hashable {
    let stream: String?
    let lane: String?
    let observation: String?
    let evidence: [String]?
    let risk: String?
    let recommendation: String?
    let response: String?
    let summary: String?
    let nextStep: String?
    let confidence: String?
    let sourceStreams: [String]?
}

struct MonitorReplyStreamMetadata: Decodable, Equatable, Hashable {
    let model: String?
    let replyPosture: String?
}

struct MonitorMessageRecord: Decodable, Identifiable, Equatable, Hashable {
    let id: String?
    let timestamp: String?
    let updatedAt: String?
    let threadId: String?
    let sender: String?
    let recipient: String?
    let subject: String?
    let body: String?
    let kind: String?
    let status: String?
    let replyTo: String?
    let preview: String?
    let metadata: MonitorMessageMetadata?
    let streamPackets: [MonitorReplyStreamRecord]?
    let replyCouncilTurn: MonitorReplyCouncilTurn?

    var stableID: String {
        id ?? "\(threadId ?? "thread")-\(sender ?? "message")-\(timestamp ?? updatedAt ?? subject ?? preview ?? "record")"
    }
}

struct MonitorChatResponse: Decodable, Equatable {
    let threadId: String?
    let reply: MonitorMessageRecord?
    let messages: [MonitorMessageRecord]?
}

struct MonitorPersonalConversationState: Decodable, Equatable {
    let status: String?
    let reason: String?
    let lastCheckAt: String?
    let lastSentAt: String?
    let nextCheckAt: String?
    let source: String?
    let messageId: String?
    let threadId: String?
    let subject: String?
    let minimumGapMinutes: Int?
}

struct MonitorWakeResponse: Decodable, Equatable {
    let completed: [String]?
    let selectedThreadId: String?
    let awakened: Bool?
}

private struct MonitorChatAskRequest: Encodable {
    let body: String
    let subject: String
    let clientRequestID: String
}

private struct MonitorChatReplyRequest: Encodable {
    let messageID: String
    let body: String
    let subject: String
    let clientRequestID: String
}

private struct MonitorPersonalInitiateRequest: Encodable {
    let allowNone: Bool
    let notify: Bool
}

private struct MonitorEmptyRequest: Encodable {}

enum MonitorAPIError: LocalizedError {
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

enum MonitorStream: String, CaseIterable, Identifiable {
    case evidence = "Evidence"
    case commitments = "Commitments"
    case experience = "Experience"

    var id: String { rawValue }
}

@MainActor
final class EveMonitorModel: ObservableObject {
    @Published var payload: EveMonitorPayload?
    @Published var statusTitle = "Connecting to Eve"
    @Published var statusDetail = "Opening the local monitor surface."
    @Published var isConnected = false
    @Published var isPaused = false
    @Published var updateMode = "Connecting"
    @Published var selectedStream: MonitorStream = .evidence
    @Published var pressureSamples: [MonitorPressureSample] = []
    @Published var resourceSamples: [MonitorResourceSample] = []
    @Published var activeSectionID = "overview"
    @Published var chatMessages: [MonitorChatMessage] = [
        MonitorChatMessage(
            id: "welcome",
            role: .eve,
            metadata: "Eve - ready",
            body: "I am here. Ask me what I am doing, what needs attention, or what evidence changed the current state.",
            laneVoices: MonitorChatLaneVoice.welcome
        )
    ]
    @Published var chatThreadID: String?
    @Published var chatStatus = "Ready"
    @Published var chatError: String?
    @Published var isSendingChatMessage = false
    @Published var eveInitiatedMessages: [MonitorMessageRecord] = []
    @Published var eveInitiatedStatus = "Listening"
    @Published var eveInitiatedError: String?
    @Published var personalConversationState: MonitorPersonalConversationState?
    @Published var personalChatMessages: [MonitorChatMessage] = []
    @Published var personalChatThreadID: String?
    @Published var personalChatStatus = "Listening"
    @Published var personalChatError: String?
    @Published var isSendingPersonalMessage = false
    @Published var isEnsuringEveAwake = false
    @Published var eveAwakeError: String?
    @Published var isPowerChanging = false
    @Published var isPoweredOff = UserDefaults.standard.bool(forKey: "eve.monitor.poweredOff")
    @Published var powerError: String?
    @Published var serviceProbeResults: [String: MonitorServiceProbe] = [:]
    @Published var serviceStatusUpdatedAt: Date?

    private let requiredAPIVersion = 5
    private let powerStateKey = "eve.monitor.poweredOff"
    private let baseURL = URL(string: "http://127.0.0.1:8787")!
    private let compactMonitorQuery = [URLQueryItem(name: "compact", value: "1")]
    private let coreServiceProbeTargets: [(id: String, url: URL)] = [
        ("monitor-api", URL(string: "http://127.0.0.1:8787/api/monitor?compact=1")!),
        ("eve-control", URL(string: "http://127.0.0.1:8765/v1/health")!),
        ("openclaw", URL(string: "http://127.0.0.1:19011/health")!)
    ]
    private var streamTask: Task<Void, Never>?
    private var refreshTask: Task<Void, Never>?
    private var messageRefreshTask: Task<Void, Never>?
    private var hasStarted = false
    private var chatReplyTargetID: String?
    private var personalChatReplyTargetID: String?
    private var lastEveAwakeEnsureAt: Date?
    private var lastStreamFrameAt: Date?
    private var lastPressureSampleSignature: String?
    private var lastResourceSampleSignature: String?

    private let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    private let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        return encoder
    }()

    private func setIfChanged<Value: Equatable>(_ keyPath: ReferenceWritableKeyPath<EveMonitorModel, Value>, _ value: Value) {
        if self[keyPath: keyPath] != value {
            self[keyPath: keyPath] = value
        }
    }

    private var helperURL: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".eve_runtime/bin/eve_control.sh")
    }

    private var serviceProbeTargets: [(id: String, url: URL)] {
        let runtimeTargets = normalizedLanes.compactMap { lane -> (id: String, url: URL)? in
            guard
                let laneID = lane.lane?.lowercased(),
                !laneID.isEmpty,
                let host = lane.host?.monitorTrimmed,
                !host.isEmpty,
                let url = URL(string: host + "/v1/models")
            else {
                return nil
            }
            return ("lane-\(laneID)", url)
        }
        if !runtimeTargets.isEmpty {
            return coreServiceProbeTargets + runtimeTargets
        }
        let fallbackTargets: [(id: String, url: URL)] = [
            ("lane-fast", URL(string: "http://127.0.0.1:8080/v1/models")!),
            ("lane-deep", URL(string: "http://127.0.0.1:8081/v1/models")!),
            ("lane-observer", URL(string: "http://127.0.0.1:8082/v1/models")!),
            ("lane-planner", URL(string: "http://127.0.0.1:8082/v1/models")!),
            ("lane-relationship", URL(string: "http://127.0.0.1:8080/v1/models")!)
        ]
        return coreServiceProbeTargets + fallbackTargets
    }

    var generatedAt: String {
        MonitorFormatters.clock(payload?.generatedAt)
    }

    var daemonTitle: String {
        if isPoweredOff { return "Off" }
        let daemon = payload?.status?.daemon
        if daemon?.awake == true { return "Awake" }
        if daemon?.running == true { return "Running" }
        return "Sleeping"
    }

    var daemonDetail: String {
        if isPoweredOff { return "Background service disabled" }
        return payload?.status?.daemon?.runtimeDir?.monitorLimited(to: 52) ?? "Runtime unavailable"
    }

    var normalizedLanes: [MonitorLane] {
        let lanes = payload?.status?.modelHealth?.lanes ?? []
        if !lanes.isEmpty { return lanes }
        let loaded = payload?.status?.modelHealth?.loadedModels ?? []
        return loaded.map {
            MonitorLane(
                lane: $0.name,
                label: $0.name,
                model: $0.name,
                host: $0.host,
                backend: $0.backend,
                loaded: true,
                latencyMs: nil
            )
        }
    }

    var lanesReady: String {
        let lanes = normalizedLanes
        let ready = lanes.filter { $0.loaded == true }.count
        return "\(ready) / \(lanes.count)"
    }

    var activityLanes: [MonitorActivityLane] {
        let lanes = payload?.activity?.models?.lanes ?? []
        if !lanes.isEmpty { return lanes }
        return normalizedLanes.map {
            MonitorActivityLane(
                lane: $0.lane,
                label: $0.label,
                model: $0.model,
                host: $0.host,
                backend: $0.backend,
                loaded: $0.loaded,
                state: $0.loaded == true ? "ready" : "offline",
                operation: nil,
                latencyMs: $0.latencyMs,
                elapsedMs: nil,
                durationMs: nil,
                charsPerSecond: nil,
                lastOk: nil
            )
        }
    }

    var activeModelCalls: [MonitorModelCall] {
        payload?.activity?.models?.activeCalls ?? []
    }

    var recentModelCalls: [MonitorModelCall] {
        payload?.activity?.models?.recentCalls ?? []
    }

    var systemActivity: MonitorSystemActivity? {
        payload?.activity?.system
    }

    var humanContextSignals: MonitorHumanContextSignals? {
        payload?.humanContextSignals ?? payload?.status?.humanContextSignals
    }

    var serviceRows: [MonitorServiceRow] {
        let coreRows = [
            MonitorServiceRow(
                id: "daemon",
                group: "Core",
                title: "Eve Daemon",
                detail: daemonServiceDetail,
                metadata: daemonServiceMetadata,
                systemImage: "power.circle",
                state: daemonServiceState
            ),
            serviceRow(
                id: "monitor-api",
                group: "Core",
                title: "Monitor API",
                fallbackDetail: "Local realtime API on port 8787.",
                fallbackMetadata: isConnected ? "connected" : "waiting",
                systemImage: "display",
                fallbackOnline: payload != nil || isConnected
            ),
            serviceRow(
                id: "eve-control",
                group: "Core",
                title: "Eve Control",
                fallbackDetail: "Headless control runtime on port 8765.",
                fallbackMetadata: "local",
                systemImage: "house.and.flag",
                fallbackOnline: nil
            ),
            serviceRow(
                id: "openclaw",
                group: "Core",
                title: "OpenClaw",
                fallbackDetail: payload?.state?.openclawSummary ?? "Gateway on port 19011.",
                fallbackMetadata: openClawMetadata,
                systemImage: "wrench.and.screwdriver",
                fallbackOnline: openClawFallbackOnline
            )
        ]

        return coreRows + modelLaneServiceRows
    }

    var serviceOnlineCount: Int {
        serviceRows.filter { $0.state == .online }.count
    }

    var serviceOfflineCount: Int {
        serviceRows.filter { $0.state == .offline }.count
    }

    var serviceWarningCount: Int {
        serviceRows.filter { $0.state == .warning }.count
    }

    var serviceKnownCount: Int {
        serviceRows.filter { $0.state != .unknown }.count
    }

    var serviceSummaryTitle: String {
        if serviceOnlineCount == serviceRows.count {
            return "Everything Online"
        }
        if serviceOnlineCount > 0 {
            return "Partly Online"
        }
        if serviceKnownCount > 0 {
            return "Offline"
        }
        return "Checking Services"
    }

    var serviceSummaryDetail: String {
        let total = serviceRows.count
        if total == 0 { return "No services configured." }
        let warning = serviceWarningCount > 0 ? ", \(serviceWarningCount) warning" : ""
        return "\(serviceOnlineCount) online, \(serviceOfflineCount) offline\(warning), \(total) tracked."
    }

    var serviceLastUpdated: String {
        MonitorFormatters.clock(serviceStatusUpdatedAt)
    }

    var serviceSummaryState: MonitorServiceState {
        if serviceOnlineCount == serviceRows.count { return .online }
        if serviceOnlineCount > 0 { return .warning }
        if serviceKnownCount > 0 { return .offline }
        return .unknown
    }

    private var daemonServiceState: MonitorServiceState {
        if payload?.status?.daemon?.running == true { return .online }
        if serviceProbeResults["monitor-api"]?.online == true { return .warning }
        return isPoweredOff ? .offline : .unknown
    }

    private var daemonServiceDetail: String {
        if payload?.status?.daemon?.awake == true {
            return "Daemon loop is running and awake."
        }
        if payload?.status?.daemon?.running == true {
            return "Daemon process is running, but active state is still settling."
        }
        return payload == nil ? "Waiting for monitor state." : "Daemon is not reporting as running."
    }

    private var daemonServiceMetadata: String {
        if payload?.status?.daemon?.awake == true { return "awake" }
        if payload?.status?.daemon?.running == true { return "running" }
        if isPoweredOff { return "off" }
        return "unknown"
    }

    private var openClawFallbackOnline: Bool? {
        guard let summary = payload?.state?.openclawSummary?.lowercased(), !summary.isEmpty else {
            return nil
        }
        if summary.contains("unreachable") || summary.contains("not reachable") {
            return false
        }
        if summary.contains("reachable") {
            return true
        }
        return nil
    }

    private var openClawMetadata: String {
        guard let summary = payload?.state?.openclawSummary?.lowercased(), !summary.isEmpty else {
            return "gateway"
        }
        if summary.contains("degraded") { return "degraded" }
        if summary.contains("reachable") { return "reachable" }
        return "gateway"
    }

    private var modelLaneServiceRows: [MonitorServiceRow] {
        let lanes = [
            ("lane-fast", "fast", "Fast Lane", "eve-fast", "http://127.0.0.1:8080"),
            ("lane-deep", "deep", "Deep Lane", "eve-deep", "http://127.0.0.1:8081"),
            ("lane-observer", "observer", "Observer Lane", "eve-observer", "http://127.0.0.1:8082"),
            ("lane-planner", "planner", "Planner Lane", "eve-observer", "http://127.0.0.1:8082"),
            ("lane-relationship", "relationship", "Relationship Lane", "eve-fast", "http://127.0.0.1:8080")
        ]
        return lanes.map { item in
            let id = item.0
            let laneID = item.1
            let title = item.2
            let fallbackModel = item.3
            let fallbackHost = item.4
            let lane = laneContext(for: laneID)
            let modelName = lane?.model?.monitorReadable.monitorLimited(to: 42) ?? fallbackModel
            let host = lane?.host?.monitorReadable.monitorLimited(to: 52) ?? fallbackHost
            let latency = MonitorFormatters.latency(lane?.latencyMs)
            return serviceRow(
                id: id,
                group: "Model Lanes",
                title: title,
                fallbackDetail: "\(modelName) via \(host).",
                fallbackMetadata: latency == "n/a" ? (lane?.state ?? "lane") : latency,
                systemImage: "cpu",
                fallbackOnline: lane?.loaded
            )
        }
    }

    private var hasOnlineServiceEvidence: Bool {
        if serviceProbeResults.values.contains(where: { $0.online }) { return true }
        if payload?.status?.daemon?.running == true { return true }
        if normalizedLanes.contains(where: { $0.loaded == true }) { return true }
        return false
    }

    private func serviceRow(
        id: String,
        group: String,
        title: String,
        fallbackDetail: String,
        fallbackMetadata: String,
        systemImage: String,
        fallbackOnline: Bool?
    ) -> MonitorServiceRow {
        if let probe = serviceProbeResults[id] {
            return MonitorServiceRow(
                id: id,
                group: group,
                title: title,
                detail: probe.online ? fallbackDetail : probe.detail,
                metadata: MonitorFormatters.clock(probe.checkedAt),
                systemImage: systemImage,
                state: probe.online ? .online : .offline
            )
        }

        let state: MonitorServiceState
        if let fallbackOnline {
            state = fallbackOnline ? .online : .offline
        } else {
            state = isPoweredOff ? .offline : .unknown
        }

        return MonitorServiceRow(
            id: id,
            group: group,
            title: title,
            detail: fallbackDetail,
            metadata: fallbackMetadata,
            systemImage: systemImage,
            state: state
        )
    }

    var peakPressure: MonitorPressure? {
        (payload?.homeostasis?.pressures ?? []).max { ($0.level ?? 0) < ($1.level ?? 0) }
    }

    func pressureKey(_ pressure: MonitorPressure) -> String {
        pressure.id ?? pressure.label ?? "pressure"
    }

    func pressureHistory(for pressure: MonitorPressure) -> [MonitorPressureSample] {
        let key = pressureKey(pressure)
        return Array(pressureSamples.filter { $0.pressureID == key }.suffix(48))
    }

    func pressureDelta(for pressure: MonitorPressure) -> Int? {
        let history = pressureHistory(for: pressure)
        guard history.count >= 2, let current = history.last?.level else { return nil }
        let previous = history.dropLast().last?.level ?? current
        return current - previous
    }

    var activeReplyTitle: String {
        guard let reply = payload?.status?.activeReply, reply.id != nil else { return "Idle" }
        return reply.phase ?? reply.status ?? "Working"
    }

    var activeReplyDetail: String {
        guard let reply = payload?.status?.activeReply, reply.id != nil else { return "No active reply" }
        return (reply.detail ?? reply.title ?? "Reply in progress").monitorLimited(to: 92)
    }

    var workspaceSummary: String {
        let summary = payload?.workspace?.summary?.monitorTrimmed ?? ""
        return summary.isEmpty ? "Waiting for the global workspace." : summary
    }

    var workspaceFocus: String {
        let focus = payload?.workspace?.workspaceState?.focus?.monitorTrimmed ?? ""
        let noisyFocus = focus.contains("```") || focus.localizedCaseInsensitiveContains("proposal")
        if !focus.isEmpty && !noisyFocus { return focus }
        let autonomy = autonomyFocus.monitorTrimmed
        if !autonomy.isEmpty && autonomy != "No autonomy agenda loaded." { return autonomy }
        return workspaceSummary
    }

    var currentExperience: String {
        let experience = payload?.workspace?.currentExperience?.monitorTrimmed ?? ""
        return experience.isEmpty ? "No current experience snapshot yet." : experience
    }

    var latestEveInitiatedMessage: MonitorMessageRecord? {
        eveInitiatedMessages.first
    }

    var unreadEveInitiatedCount: Int {
        eveInitiatedMessages.filter { ($0.status ?? "").lowercased() == "unread" }.count
    }

    var personalConversationTitle: String {
        if let selected = eveInitiatedMessages.first(where: { $0.threadId == personalChatThreadID }),
           let subject = selected.subject?.monitorReadable,
           !subject.isEmpty {
            return subject
        }
        if let latest = latestEveInitiatedMessage?.subject?.monitorReadable, !latest.isEmpty {
            return latest
        }
        return "Eve can start here"
    }

    var personalConversationDetail: String {
        if let threadID = personalChatThreadID {
            return "Personal thread \(threadID.monitorLimited(to: 18))"
        }
        return "When Eve has something grounded to say, it becomes a replyable conversation here."
    }

    var personalConversationQuietTitle: String {
        switch (personalConversationState?.status ?? "").lowercased() {
        case "sent", "open":
            return "Eve opened a thread"
        case "quiet":
            return "Eve checked in quietly"
        case "waiting":
            return "Eve is waiting for room"
        case "blocked", "failed":
            return "Eve needs attention"
        default:
            return "Eve is listening"
        }
    }

    var personalConversationBadgeStatus: String {
        switch (personalConversationState?.status ?? "").lowercased() {
        case "sent", "open":
            return "Open"
        case "quiet":
            return "Quiet"
        case "waiting":
            return "Waiting"
        case "blocked", "failed", "offline":
            return "Needs attention"
        default:
            return "Listening"
        }
    }

    var personalConversationQuietDetail: String {
        let reason = personalConversationState?.reason?.monitorReadable.monitorTrimmed ?? ""
        if !reason.isEmpty { return reason }
        return "When Eve has something grounded to say or ask, it appears here as a conversation."
    }

    var personalConversationTimingDetail: String {
        let lastCheck = MonitorFormatters.dateTime(personalConversationState?.lastCheckAt)
        let nextCheck = MonitorFormatters.dateTime(personalConversationState?.nextCheckAt)
        if lastCheck != "never" && nextCheck != "never" {
            return "Last checked \(lastCheck). Next check \(nextCheck)."
        }
        if lastCheck != "never" {
            return "Last checked \(lastCheck)."
        }
        return "Waiting for the daemon's first personal check."
    }

    var alwaysAwakeStatus: String {
        if isPoweredOff { return "Powered off" }
        if isPowerChanging { return "Changing power" }
        if isEnsuringEveAwake { return "Keeping awake" }
        if payload?.status?.daemon?.awake == true { return "Always awake" }
        if payload?.status?.daemon?.running == true { return "Re-centering" }
        return "Starting Eve"
    }

    var alwaysAwakeDetail: String {
        if isPoweredOff {
            return "Eve is fully stopped until you turn her on again from the monitor."
        }
        if let powerError {
            return "Power control needs attention: \(powerError)"
        }
        if let eveAwakeError {
            return "Always-on check needs attention: \(eveAwakeError)"
        }
        if payload?.status?.daemon?.awake == true {
            return "Eve's daemon is running; new messages can appear here without a manual prompt."
        }
        if payload?.status?.daemon?.running == true {
            return "The daemon is running, and the monitor is refreshing Eve's active state automatically."
        }
        return "The monitor will try to reconnect Eve's local runtime automatically."
    }

    var autonomyFocus: String {
        let agenda = payload?.autonomy?.agenda
        let focus = agenda?.currentFocus?.monitorTrimmed ?? ""
        if !focus.isEmpty { return focus }
        return agenda?.summary ?? "No autonomy agenda loaded."
    }

    func start() async {
        guard !hasStarted else { return }
        hasStarted = true
        await refreshServiceStatuses()
        if isPoweredOff {
            if hasOnlineServiceEvidence {
                reconcileSavedPowerOff(reason: "Some Eve services are already online.")
            } else {
                setPoweredOffState(detail: "Use Power On when you want Eve running again.")
                return
            }
        }
        await reconnect(forceRestart: false)
        await ensureEveAwakeIfNeeded(force: true)
    }

    func setActiveSection(_ sectionID: String) {
        guard activeSectionID != sectionID else { return }
        activeSectionID = sectionID
        if let payload {
            if sectionID == "overview" || sectionID == "homeostasis" {
                recordPressureSamples(from: payload)
            }
            if sectionID == "activity" {
                recordResourceSample(from: payload)
            }
        }
        if sectionID == "fromEve" {
            Task { await refreshEveInitiatedMessages(includeThread: true) }
        }
        if sectionID == "services" {
            Task { await refreshServiceStatuses() }
        }
    }

    func reconnect(forceRestart: Bool) async {
        if isPoweredOff {
            await refreshServiceStatuses()
            guard !isPoweredOff else {
                setPoweredOffState(detail: "Eve is off; reconnect will stay quiet until you power her on.")
                return
            }
        }
        stopRealtimeUpdates()
        if forceRestart {
            runHelper("web-restart")
        }
        statusTitle = forceRestart ? "Reconnecting to Eve" : "Connecting to Eve"
        statusDetail = "Opening the local monitor surface."
        updateMode = "Connecting"
        isConnected = false

        var restartAttempted = forceRestart
        for attempt in 0..<50 {
            do {
                let next: EveMonitorPayload = try await request("/api/monitor", queryItems: compactMonitorQuery, timeout: 2)
                let apiVersion = next.status?.apiVersion ?? 0
                if apiVersion >= requiredAPIVersion {
                    apply(next, mode: "Polling")
                    startRealtimeUpdates()
                    return
                }
            } catch {
                if attempt == 0 && !restartAttempted {
                    restartAttempted = true
                    runHelper("web-restart")
                }
                statusDetail = error.localizedDescription
            }
            try? await Task.sleep(nanoseconds: 300_000_000)
        }

        statusTitle = "Could not reach Eve"
        statusDetail = "The local monitor API did not start in time."
        updateMode = "Offline"
        isConnected = false
    }

    func refreshNow(mode overrideMode: String? = nil) async {
        if activeSectionID == "services" || isPoweredOff {
            await refreshServiceStatuses()
        }
        guard !isPoweredOff else {
            setPoweredOffState(detail: "Live refresh is paused while Eve is powered off.")
            return
        }
        do {
            let next: EveMonitorPayload = try await request("/api/monitor", queryItems: compactMonitorQuery, timeout: 4)
            apply(next, mode: overrideMode ?? (updateMode == "Realtime" ? "Realtime" : "Polling"))
        } catch {
            isConnected = false
            statusTitle = "Monitor needs attention"
            statusDetail = error.localizedDescription
            updateMode = "Offline"
        }
    }

    func togglePaused() {
        isPaused.toggle()
        if isPaused {
            stopRealtimeUpdates()
            setIfChanged(\.updateMode, "Paused")
            setIfChanged(\.statusDetail, "Live updates are paused.")
        } else {
            setIfChanged(\.statusDetail, "Live updates resumed.")
            Task { await reconnect(forceRestart: false) }
        }
    }

    func openWebMonitor() {
        guard !isPoweredOff else { return }
        NSWorkspace.shared.open(baseURL.appendingPathComponent("monitor"))
    }

    func togglePower() async {
        if isPoweredOff {
            await powerOn()
        } else {
            await powerOff()
        }
    }

    func powerOn() async {
        guard !isPowerChanging else { return }
        isPowerChanging = true
        powerError = nil
        isPoweredOff = false
        UserDefaults.standard.set(false, forKey: powerStateKey)
        statusTitle = "Powering Eve on"
        statusDetail = "Enabling the background service and local monitor API."
        updateMode = "Starting"

        do {
            try await runHelperAndWait("power-on")
            await refreshServiceStatuses()
            await reconnect(forceRestart: false)
            await ensureEveAwakeIfNeeded(force: true)
        } catch {
            powerError = error.localizedDescription
            isPoweredOff = true
            UserDefaults.standard.set(true, forKey: powerStateKey)
            setPoweredOffState(detail: "Power on failed: \(error.localizedDescription)")
        }

        isPowerChanging = false
    }

    func powerOff() async {
        guard !isPowerChanging else { return }
        isPowerChanging = true
        powerError = nil
        statusTitle = "Powering Eve off"
        statusDetail = "Stopping background services and the local monitor API."
        updateMode = "Stopping"
        stopRealtimeUpdates()

        do {
            try await runHelperAndWait("power-off")
            isPoweredOff = true
            UserDefaults.standard.set(true, forKey: powerStateKey)
            setPoweredOffState(detail: "Eve will stay off across login and reboot until you power her on.")
            await refreshServiceStatuses()
        } catch {
            powerError = error.localizedDescription
            statusTitle = "Power off needs attention"
            statusDetail = error.localizedDescription
            updateMode = "Attention"
        }

        isPowerChanging = false
    }

    private func ensureEveAwakeIfNeeded(force: Bool = false) async {
        guard !isPoweredOff else { return }
        if payload?.status?.daemon?.awake == true {
            eveAwakeError = nil
            return
        }
        guard !isEnsuringEveAwake else { return }
        if !force, let lastEveAwakeEnsureAt, Date().timeIntervalSince(lastEveAwakeEnsureAt) < 60 {
            return
        }

        isEnsuringEveAwake = true
        lastEveAwakeEnsureAt = Date()
        eveInitiatedError = nil

        do {
            let _: MonitorWakeResponse = try await post(
                "/api/actions/wake",
                body: MonitorEmptyRequest(),
                timeout: 180
            )
            await refreshNow()
            await refreshEveInitiatedMessages(includeThread: activeSectionID == "fromEve")
            eveAwakeError = nil
        } catch {
            eveAwakeError = error.localizedDescription
        }

        isEnsuringEveAwake = false
    }

    func sendChatMessage(_ text: String) async {
        let trimmed = text.monitorTrimmed
        guard !trimmed.isEmpty, !isSendingChatMessage else { return }
        guard !isPoweredOff else {
            chatError = "Eve is powered off."
            chatStatus = "Off"
            return
        }

        let optimisticMessage = MonitorChatMessage(
            id: "pending-\(UUID().uuidString)",
            role: .user,
            metadata: "You - sending",
            body: trimmed
        )
        chatMessages.append(optimisticMessage)
        chatError = nil
        chatStatus = "Waiting for Eve"
        isSendingChatMessage = true

        do {
            let response: MonitorChatResponse
            let requestID = UUID().uuidString
            if let replyTargetID = chatReplyTargetID {
                response = try await post(
                    "/api/message/reply",
                    body: MonitorChatReplyRequest(
                        messageID: replyTargetID,
                        body: trimmed,
                        subject: "Eve Monitor Chat",
                        clientRequestID: requestID
                    ),
                    timeout: 180
                )
            } else {
                response = try await post(
                    "/api/message/ask",
                    body: MonitorChatAskRequest(
                        body: trimmed,
                        subject: "Eve Monitor Chat",
                        clientRequestID: requestID
                    ),
                    timeout: 180
                )
            }
            applyChatResponse(response)
        } catch {
            chatError = error.localizedDescription
            chatStatus = "Could not reach Eve"
            chatMessages.append(
                MonitorChatMessage(
                    id: "error-\(UUID().uuidString)",
                    role: .system,
                    metadata: "Monitor - error",
                    body: "I could not send that to Eve: \(error.localizedDescription)"
                )
            )
        }

        isSendingChatMessage = false
    }

    func selectPersonalConversation(from message: MonitorMessageRecord) async {
        guard let threadID = message.threadId, !threadID.isEmpty else { return }
        await loadPersonalConversation(threadID: threadID)
    }

    func sendPersonalReply(_ text: String) async {
        let trimmed = text.monitorTrimmed
        guard !trimmed.isEmpty, !isSendingPersonalMessage else { return }
        guard !isPoweredOff else {
            personalChatError = "Eve is powered off."
            personalChatStatus = "Off"
            return
        }
        guard let replyTargetID = personalChatReplyTargetID ?? latestEveInitiatedMessage?.id else {
            personalChatError = "Eve has not opened a personal thread yet."
            personalChatStatus = "Waiting for Eve"
            return
        }

        personalChatMessages.append(
            MonitorChatMessage(
                id: "personal-pending-\(UUID().uuidString)",
                role: .user,
                metadata: "You - sending",
                body: trimmed
            )
        )
        personalChatError = nil
        personalChatStatus = "Waiting for Eve"
        isSendingPersonalMessage = true

        do {
            let response: MonitorChatResponse = try await post(
                "/api/message/reply",
                body: MonitorChatReplyRequest(
                    messageID: replyTargetID,
                    body: trimmed,
                    subject: "Personal conversation with Eve",
                    clientRequestID: UUID().uuidString
                ),
                timeout: 180
            )
            applyPersonalChatResponse(response)
            await refreshEveInitiatedMessages()
        } catch {
            personalChatError = error.localizedDescription
            personalChatStatus = "Could not reach Eve"
            personalChatMessages.append(
                MonitorChatMessage(
                    id: "personal-error-\(UUID().uuidString)",
                    role: .system,
                    metadata: "Monitor - error",
                    body: "I could not send that to Eve: \(error.localizedDescription)"
                )
            )
        }

        isSendingPersonalMessage = false
    }

    func askEveToOpenPersonalConversation() async {
        guard !isSendingPersonalMessage else { return }
        guard !isPoweredOff else {
            personalChatError = "Eve is powered off."
            personalChatStatus = "Off"
            return
        }
        personalChatError = nil
        personalChatStatus = "Listening"
        isSendingPersonalMessage = true

        do {
            let response: MonitorChatResponse = try await post(
                "/api/message/initiate",
                body: MonitorPersonalInitiateRequest(allowNone: false, notify: true),
                timeout: 180
            )
            applyPersonalChatResponse(response)
            await refreshEveInitiatedMessages()
        } catch {
            personalChatError = error.localizedDescription
            personalChatStatus = "Could not ask Eve"
        }

        isSendingPersonalMessage = false
    }

    func refreshServiceStatuses() async {
        let targets = serviceProbeTargets
        let results: [(String, MonitorServiceProbe)] = await withTaskGroup(of: (String, MonitorServiceProbe).self) { group in
            for target in targets {
                group.addTask {
                    (target.id, await Self.probeService(url: target.url))
                }
            }

            var collected: [(String, MonitorServiceProbe)] = []
            for await result in group {
                collected.append(result)
            }
            return collected
        }

        var next = serviceProbeResults
        for (id, probe) in results {
            next[id] = probe
        }
        setIfChanged(\.serviceProbeResults, next)
        setIfChanged(\.serviceStatusUpdatedAt, Date())

        if isPoweredOff && next.values.contains(where: { $0.online }) {
            reconcileSavedPowerOff(reason: "Some Eve services are already online.")
        }
    }

    nonisolated private static func probeService(url: URL) async -> MonitorServiceProbe {
        var request = URLRequest(url: url)
        request.timeoutInterval = 1.4
        do {
            let (_, response) = try await URLSession.shared.data(for: request)
            guard let http = response as? HTTPURLResponse else {
                return MonitorServiceProbe(online: false, detail: "No HTTP response.", checkedAt: Date())
            }
            let online = 200..<500 ~= http.statusCode
            let detail = online ? "Responded with HTTP \(http.statusCode)." : "HTTP \(http.statusCode)."
            return MonitorServiceProbe(online: online, detail: detail, checkedAt: Date())
        } catch {
            return MonitorServiceProbe(
                online: false,
                detail: error.localizedDescription.monitorReadable.monitorLimited(to: 120),
                checkedAt: Date()
            )
        }
    }

    private func reconcileSavedPowerOff(reason: String) {
        guard isPoweredOff else { return }
        isPoweredOff = false
        UserDefaults.standard.set(false, forKey: powerStateKey)
        powerError = nil
        statusTitle = "Eve is partly online"
        statusDetail = reason
        updateMode = serviceProbeResults["monitor-api"]?.online == true ? "Checking" : "Partial"
    }

    private func apply(_ next: EveMonitorPayload, mode: String) {
        if isPoweredOff {
            reconcileSavedPowerOff(reason: "The monitor API returned a live Eve state.")
        }
        guard !isPoweredOff else { return }
        let apiVersion = next.status?.apiVersion ?? 0
        guard apiVersion >= requiredAPIVersion else { return }
        if activeSectionID == "overview" || activeSectionID == "homeostasis" {
            recordPressureSamples(from: next)
        }
        if activeSectionID == "activity" {
            recordResourceSample(from: next)
        }
        setIfChanged(\.payload, next)
        setIfChanged(\.isConnected, true)
        setIfChanged(\.statusTitle, "Eve Monitor is live")
        setIfChanged(\.statusDetail, "Last update \(MonitorFormatters.clock(next.generatedAt))")
        setIfChanged(\.updateMode, mode)
        if next.status?.daemon?.awake == true {
            eveAwakeError = nil
        } else {
            Task { await ensureEveAwakeIfNeeded() }
        }
    }

    private func setPoweredOffState(detail: String) {
        stopRealtimeUpdates()
        setIfChanged(\.payload, nil)
        setIfChanged(\.isConnected, false)
        setIfChanged(\.updateMode, "Off")
        setIfChanged(\.statusTitle, "Eve is powered off")
        setIfChanged(\.statusDetail, detail)
        setIfChanged(\.eveAwakeError, nil)
        setIfChanged(\.eveInitiatedError, nil)
        setIfChanged(\.eveInitiatedStatus, "Off")
        setIfChanged(\.personalChatStatus, "Off")
        setIfChanged(\.personalChatError, nil)
    }

    private func applyChatResponse(_ response: MonitorChatResponse) {
        chatThreadID = response.threadId ?? chatThreadID
        let records = response.messages ?? [response.reply].compactMap { $0 }
        let mapped = records.map(chatMessage(from:))
        if !mapped.isEmpty {
            setIfChanged(\.chatMessages, mapped)
        }
        chatReplyTargetID = records.last { ($0.sender ?? "").lowercased() == "eve" }?.id ?? response.reply?.id ?? chatReplyTargetID
        chatStatus = "Connected"
        chatError = nil
    }

    func refreshEveInitiatedMessages(includeThread: Bool = true) async {
        guard !isPoweredOff else {
            eveInitiatedStatus = "Off"
            return
        }
        do {
            await refreshPersonalConversationState()
            let records: [MonitorMessageRecord] = try await request(
                "/api/messages",
                queryItems: [
                    URLQueryItem(name: "limit", value: "24"),
                    URLQueryItem(name: "sender", value: "eve"),
                    URLQueryItem(name: "recipient", value: "user"),
                    URLQueryItem(name: "initiated", value: "1"),
                    URLQueryItem(name: "personal", value: "1")
                ],
                timeout: 4
            )
            let initiated = records
                .filter(isEveInitiatedMessage)
                .sorted { lhs, rhs in
                    let left = MonitorFormatters.date(from: lhs.timestamp ?? lhs.updatedAt) ?? .distantPast
                    let right = MonitorFormatters.date(from: rhs.timestamp ?? rhs.updatedAt) ?? .distantPast
                    return left > right
            }
            let nextMessages = Array(initiated.prefix(24))
            setIfChanged(\.eveInitiatedMessages, nextMessages)
            setIfChanged(\.eveInitiatedError, nil)
            let unread = nextMessages.filter { ($0.status ?? "").lowercased() == "unread" }.count
            setIfChanged(\.eveInitiatedStatus, unread > 0 ? "\(unread) unread" : personalConversationBadgeStatus)
            guard includeThread else { return }
            if let selectedThreadID = personalChatThreadID,
               initiated.contains(where: { $0.threadId == selectedThreadID }) {
                await loadPersonalConversation(threadID: selectedThreadID)
            } else if let latestThreadID = eveInitiatedMessages.first?.threadId {
                await loadPersonalConversation(threadID: latestThreadID)
            } else if personalChatMessages.isEmpty {
                personalChatStatus = "Listening"
            }
        } catch {
            eveInitiatedError = error.localizedDescription
            if eveInitiatedMessages.isEmpty {
                eveInitiatedStatus = "Offline"
            }
        }
    }

    private func refreshPersonalConversationState() async {
        do {
            let state: MonitorPersonalConversationState = try await request(
                "/api/personal-conversation/status",
                timeout: 4
            )
            setIfChanged(\.personalConversationState, state)
        } catch {
            if personalConversationState == nil {
                setIfChanged(\.personalConversationState, MonitorPersonalConversationState(
                    status: "offline",
                    reason: error.localizedDescription,
                    lastCheckAt: nil,
                    lastSentAt: nil,
                    nextCheckAt: nil,
                    source: nil,
                    messageId: nil,
                    threadId: nil,
                    subject: nil,
                    minimumGapMinutes: nil
                ))
            }
        }
    }

    private func isEveInitiatedMessage(_ record: MonitorMessageRecord) -> Bool {
        guard (record.sender ?? "").lowercased() == "eve", (record.recipient ?? "").lowercased() == "user" else {
            return false
        }
        let kind = (record.kind ?? "").lowercased()
        if kind == "reply" && record.replyTo != nil {
            return false
        }
        return record.replyTo == nil
            || kind == "proactive_outreach"
            || kind.contains("update")
            || kind.contains("outreach")
    }

    private func loadPersonalConversation(threadID: String) async {
        do {
            let safeThreadID = threadID.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? threadID
            let records: [MonitorMessageRecord] = try await request(
                "/api/thread/\(safeThreadID)",
                timeout: 4
            )
            applyPersonalThread(records, fallbackThreadID: threadID)
        } catch {
            personalChatError = error.localizedDescription
            if personalChatMessages.isEmpty {
                personalChatStatus = "Offline"
            }
        }
    }

    private func applyPersonalChatResponse(_ response: MonitorChatResponse) {
        let records = response.messages ?? [response.reply].compactMap { $0 }
        applyPersonalThread(records, fallbackThreadID: response.threadId)
        personalChatError = nil
    }

    private func applyPersonalThread(_ records: [MonitorMessageRecord], fallbackThreadID: String?) {
        let ordered = records.sorted { lhs, rhs in
            let left = MonitorFormatters.date(from: lhs.timestamp ?? lhs.updatedAt) ?? .distantPast
            let right = MonitorFormatters.date(from: rhs.timestamp ?? rhs.updatedAt) ?? .distantPast
            return left < right
        }
        if let threadID = ordered.first?.threadId ?? fallbackThreadID {
            setIfChanged(\.personalChatThreadID, threadID)
        }
        if !ordered.isEmpty {
            setIfChanged(\.personalChatMessages, ordered.map(chatMessage(from:)))
        }
        personalChatReplyTargetID = ordered.last { ($0.sender ?? "").lowercased() == "eve" }?.id
        let unread = ordered.filter {
            ($0.sender ?? "").lowercased() == "eve"
                && ($0.recipient ?? "").lowercased() == "user"
                && ($0.status ?? "").lowercased() == "unread"
        }.count
        setIfChanged(\.personalChatStatus, unread > 0 ? "\(unread) waiting" : (ordered.isEmpty ? "Listening" : "Open"))
    }

    private func chatMessage(from record: MonitorMessageRecord) -> MonitorChatMessage {
        let sender = (record.sender ?? "").lowercased()
        let role: MonitorChatRole = sender == "user" ? .user : (sender == "eve" ? .eve : .system)
        let name = role == .user ? "You" : (role == .eve ? "Eve" : "Monitor")
        let time = MonitorFormatters.clock(record.timestamp ?? record.updatedAt)
        let body = (record.body ?? record.preview ?? "").monitorReadable
        let streamReplyUsed = record.metadata?.streamReplyUsed == true
        return MonitorChatMessage(
            id: record.stableID,
            role: role,
            metadata: "\(name) - \(time)",
            body: body,
            laneVoices: role == .eve ? fiveLaneVoices(for: body, record: record) : [],
            laneBadge: streamReplyUsed ? "5 lanes" : "context",
            sharedReplyLabel: streamReplyUsed ? "Shared reply" : "Reply + context"
        )
    }

    private func fiveLaneVoices(for body: String, record: MonitorMessageRecord?) -> [MonitorChatLaneVoice] {
        let cleanBody = body.monitorReadable
        let packets = record?.streamPackets ?? []
        let council = record?.replyCouncilTurn
        let fast = streamPacket(["fast", "synthesis"], in: packets)
        let deep = streamPacket(["deep", "skeptic"], in: packets)
        let observer = streamPacket(["observer", "factual"], in: packets)
        let planner = streamPacket(["planner", "factual"], in: packets)
        let relationship = streamPacket(["relationship", "listener"], in: packets)

        let focus = workspaceFocus.monitorReadable.monitorLimited(to: 170)
        let pressure = payload?.homeostasis?.summary?.monitorReadable.monitorLimited(to: 170)
        let nextMove = payload?.workspace?.actionReadiness?.first?.monitorReadable.monitorLimited(to: 170)
            ?? payload?.homeostasis?.nextRegulationStep?.monitorReadable.monitorLimited(to: 170)

        let fastBody = packetText(
            fast,
            preferred: ["response"],
            fallback: councilLaneBody(for: "fast", council: council, fallback: chatSentence(cleanBody, fallback: "Waiting for the shared reply.", limit: 180))
        )
        let deepBody = packetText(
            deep,
            preferred: ["risk", "recommendation", "observation"],
            fallback: councilLaneBody(for: "deep", council: council, fallback: pressure ?? "No separate deep-lane concern was returned for this turn.")
        )
        let observerBody = packetText(
            observer,
            preferred: ["evidence", "observation", "recommendation"],
            fallback: councilLaneBody(for: "observer", council: council, fallback: focus.isEmpty ? "No separate observer evidence was returned for this turn." : focus)
        )
        let plannerBody = packetText(
            planner,
            preferred: ["recommendation"],
            fallback: councilLaneBody(for: "planner", council: council, fallback: nextMove ?? "No separate planner next step was returned for this turn.")
        )
        let relationshipBody = packetText(
            relationship,
            preferred: ["observation", "recommendation"],
            fallback: councilLaneBody(for: "relationship", council: council, fallback: cleanBody.monitorLimited(to: 180))
        )

        return [
            MonitorChatLaneVoice(
                id: "fast",
                title: "Fast",
                detail: laneDetail(for: "fast", record: record, streams: ["fast", "synthesis"], fallback: "eve-fast", council: council),
                body: fastBody
            ),
            MonitorChatLaneVoice(
                id: "deep",
                title: "Deep",
                detail: laneDetail(for: "deep", record: record, streams: ["deep", "skeptic"], fallback: "eve-deep", council: council),
                body: deepBody
            ),
            MonitorChatLaneVoice(
                id: "observer",
                title: "Observer",
                detail: laneDetail(for: "observer", record: record, streams: ["observer", "factual"], fallback: "eve-observer", council: council),
                body: observerBody
            ),
            MonitorChatLaneVoice(
                id: "planner",
                title: "Planner",
                detail: laneDetail(for: "planner", record: record, streams: ["planner", "factual"], fallback: "eve-planner", council: council),
                body: plannerBody
            ),
            MonitorChatLaneVoice(
                id: "relationship",
                title: "Relationship",
                detail: laneDetail(for: "relationship", record: record, streams: ["relationship", "listener"], fallback: "eve-relationship", council: council),
                body: relationshipBody
            )
        ]
    }

    private func streamPacket(_ streams: [String], in packets: [MonitorReplyStreamRecord]) -> MonitorReplyStreamRecord? {
        for stream in streams {
            if let packet = streamPacket(stream, in: packets) {
                return packet
            }
        }
        return nil
    }

    private func streamPacket(_ stream: String, in packets: [MonitorReplyStreamRecord]) -> MonitorReplyStreamRecord? {
        let target = stream.lowercased()
        return packets.first { record in
            [record.stream, record.packet?.stream]
                .compactMap { $0?.lowercased() }
                .contains(target)
        }
    }

    private func packetText(_ record: MonitorReplyStreamRecord?, preferred fields: [String], fallback: String) -> String {
        guard let packet = record?.packet else {
            return fallback.monitorReadable.monitorLimited(to: 190)
        }
        for field in fields {
            let value: String?
            switch field {
            case "response":
                value = packet.response
            case "risk":
                value = packet.risk
            case "recommendation":
                value = packet.recommendation ?? packet.nextStep
            case "observation":
                value = packet.observation ?? packet.summary ?? packet.lane
            case "evidence":
                value = packet.evidence?.filter { !$0.monitorTrimmed.isEmpty }.joined(separator: " ")
            default:
                value = nil
            }
            let clean = value?.monitorReadable.monitorTrimmed ?? ""
            if !clean.isEmpty {
                return clean.monitorLimited(to: 190)
            }
        }
        return fallback.monitorReadable.monitorLimited(to: 190)
    }

    private func laneDetail(for laneID: String, record: MonitorMessageRecord?, streams: [String], fallback: String, council: MonitorReplyCouncilTurn? = nil) -> String {
        let streamTargets = Set(streams.map { $0.lowercased() })
        let streamModel = record?.metadata?.streamModels?.first { streamTargets.contains($0.key.lowercased()) }?.value
            ?? record?.streamPackets?.first { streamTargets.contains(($0.stream ?? $0.packet?.stream ?? "").lowercased()) }?.metadata?.model
        let councilLane = councilLane(for: laneID, council: council)
        let modelName = streamModel?.monitorReadable.monitorLimited(to: 32)
            ?? councilLane?.model?.monitorReadable.monitorLimited(to: 32)
            ?? laneContext(for: laneID)?.model?.monitorReadable.monitorLimited(to: 32)
            ?? fallback
        let state = councilLaneState(laneID, lane: councilLane, council: council, streamUsed: record?.metadata?.streamReplyUsed == true)
        if let pressure = councilLane?.pressure {
            return "\(state) \(Int((pressure * 100).rounded()))% - \(modelName)"
        }
        return "\(state) - \(modelName)"
    }

    private func councilLane(for laneID: String, council: MonitorReplyCouncilTurn?) -> MonitorReplyCouncilLane? {
        let target = laneID.lowercased()
        return council?.lanes?.first { ($0.lane ?? "").lowercased() == target }
    }

    private func councilLaneState(_ laneID: String, lane: MonitorReplyCouncilLane?, council: MonitorReplyCouncilTurn?, streamUsed: Bool) -> String {
        let target = laneID.lowercased()
        let active = Set(council?.activeLanes?.map { $0.lowercased() } ?? [])
        let streamed = Set(council?.selectedStreamLanes?.map { $0.lowercased() } ?? [])
        let deferred = Set(council?.deferredLanes?.map { $0.lowercased() } ?? [])
        let abstained = Set(council?.abstainedLanes?.map { $0.lowercased() } ?? [])
        if lane?.quarantined == true { return "Quarantined" }
        if streamUsed && (streamed.contains(target) || lane?.selected == true || active.contains(target)) { return "Generated" }
        if active.contains(target) { return "Admitted" }
        if deferred.contains(target) { return "Deferred" }
        if abstained.contains(target) { return "Abstained" }
        return streamUsed ? "Stream" : "Context"
    }

    private func councilLaneBody(for laneID: String, council: MonitorReplyCouncilTurn?, fallback: String) -> String {
        guard let lane = councilLane(for: laneID, council: council) else {
            return fallback.monitorReadable.monitorLimited(to: 190)
        }
        let reasons = lane.reasons?.filter { !$0.monitorTrimmed.isEmpty }.joined(separator: ", ") ?? ""
        if !reasons.isEmpty {
            return reasons.monitorReadable.monitorLimited(to: 190)
        }
        if let reason = council?.reason?.monitorTrimmed, !reason.isEmpty {
            return reason.monitorReadable.monitorLimited(to: 190)
        }
        return fallback.monitorReadable.monitorLimited(to: 190)
    }

    private func laneContext(for laneID: String) -> MonitorActivityLane? {
        let target = laneID.lowercased()
        return activityLanes.first { lane in
            [lane.lane, lane.label, lane.model]
                .compactMap { $0?.lowercased() }
                .contains { $0.contains(target) }
        }
    }

    private func chatSentence(_ text: String, fallback: String, limit: Int) -> String {
        let clean = text.monitorReadable
        guard !clean.isEmpty else { return fallback }
        if let range = clean.rangeOfCharacter(from: CharacterSet(charactersIn: ".!?")) {
            let end = clean.index(after: range.lowerBound)
            return String(clean[..<end]).monitorLimited(to: limit)
        }
        return clean.monitorLimited(to: limit)
    }

    private func recordPressureSamples(from next: EveMonitorPayload) {
        let pressures = next.homeostasis?.pressures ?? []
        guard !pressures.isEmpty else { return }
        let timestamp = MonitorFormatters.date(from: next.generatedAt) ?? Date()
        let newest = pressures.map { pressure in
            MonitorPressureSample(
                timestamp: timestamp,
                pressureID: pressure.id ?? pressure.label ?? "pressure",
                label: pressure.label ?? pressure.id ?? "Pressure",
                level: max(0, min(100, pressure.level ?? 0))
            )
        }
        let signature = "\(next.generatedAt ?? "")|" + newest
            .map { "\($0.pressureID):\($0.level)" }
            .joined(separator: ",")
        guard signature != lastPressureSampleSignature else { return }
        lastPressureSampleSignature = signature
        pressureSamples.append(contentsOf: newest)
        if pressureSamples.count > 520 {
            pressureSamples = Array(pressureSamples.suffix(520))
        }
    }

    private func recordResourceSample(from next: EveMonitorPayload) {
        let system = next.activity?.system
        let cpu = max(0, min(100, system?.cpuPercent ?? 0))
        let memory = max(0, min(100, system?.memory?.usedPercent ?? 0))
        guard cpu > 0 || memory > 0 else { return }
        let timestamp = MonitorFormatters.date(from: next.generatedAt) ?? Date()
        let signature = "\(next.generatedAt ?? "")|\(Int(cpu.rounded()))|\(Int(memory.rounded()))"
        guard signature != lastResourceSampleSignature else { return }
        lastResourceSampleSignature = signature
        resourceSamples.append(MonitorResourceSample(timestamp: timestamp, cpuPercent: cpu, memoryPercent: memory))
        if resourceSamples.count > 240 {
            resourceSamples = Array(resourceSamples.suffix(240))
        }
    }

    private func startRealtimeUpdates() {
        guard !isPoweredOff else { return }
        streamTask?.cancel()
        streamTask = nil
        stopPolling()
        stopMessageRefresh()
        updateMode = "Realtime"
        streamTask = Task { [weak self] in
            await self?.monitorStreamLoop()
        }
        startPolling()
        startMessageRefresh()
    }

    private func stopRealtimeUpdates() {
        streamTask?.cancel()
        streamTask = nil
        stopPolling()
        stopMessageRefresh()
    }

    private func startPolling() {
        guard refreshTask == nil else { return }
        refreshTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                if !isPaused {
                    if activeSectionID == "services" {
                        await refreshServiceStatuses()
                    }
                    if shouldRunFallbackPoll() {
                        await refreshNow(mode: "Polling")
                    }
                }
                try? await Task.sleep(nanoseconds: 6_000_000_000)
            }
        }
    }

    private func stopPolling() {
        refreshTask?.cancel()
        refreshTask = nil
    }

    private func shouldRunFallbackPoll() -> Bool {
        guard updateMode == "Realtime" else { return true }
        guard let lastStreamFrameAt else { return true }
        return Date().timeIntervalSince(lastStreamFrameAt) > 10
    }

    private func startMessageRefresh() {
        guard messageRefreshTask == nil else { return }
        messageRefreshTask = Task { [weak self] in
            guard let self else { return }
            while !Task.isCancelled {
                if !isPaused {
                    let includeThread = activeSectionID == "fromEve"
                    await refreshEveInitiatedMessages(includeThread: includeThread)
                }
                let interval: UInt64 = activeSectionID == "fromEve" ? 5_000_000_000 : 30_000_000_000
                try? await Task.sleep(nanoseconds: interval)
            }
        }
    }

    private func stopMessageRefresh() {
        messageRefreshTask?.cancel()
        messageRefreshTask = nil
    }

    private func monitorStreamLoop() async {
        while !Task.isCancelled {
            do {
                try await consumeMonitorStream()
            } catch {
                guard !Task.isCancelled else { return }
                statusTitle = "Realtime stream interrupted"
                statusDetail = "Falling back to polling while Eve reconnects."
                isConnected = payload != nil
                startPolling()
                try? await Task.sleep(nanoseconds: 3_000_000_000)
            }
        }
    }

    private func consumeMonitorStream() async throws {
        var components = URLComponents(url: baseURL.appendingPathComponent("api/monitor/stream"), resolvingAgainstBaseURL: false)!
        components.queryItems = [
            URLQueryItem(name: "interval_ms", value: "3000"),
            URLQueryItem(name: "compact", value: "1")
        ]
        guard let url = components.url else { throw MonitorAPIError.invalidResponse }

        var request = URLRequest(url: url)
        request.timeoutInterval = 65
        request.setValue("text/event-stream", forHTTPHeaderField: "Accept")

        let (bytes, response) = try await URLSession.shared.bytes(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            throw MonitorAPIError.invalidResponse
        }

        updateMode = "Realtime"
        statusTitle = "Eve Monitor is live"
        statusDetail = "Receiving realtime updates."

        var dataLines: [String] = []
        for try await line in bytes.lines {
            if Task.isCancelled { return }
            lastStreamFrameAt = Date()
            if line.isEmpty {
                try applyStreamFrame(dataLines)
                dataLines.removeAll(keepingCapacity: true)
            } else if line.hasPrefix("data:") {
                dataLines.append(String(line.dropFirst(5)).trimmingCharacters(in: .whitespaces))
            } else if line.hasPrefix(":") {
                if !isPaused {
                    setIfChanged(\.updateMode, "Realtime")
                }
            }
        }
    }

    private func applyStreamFrame(_ dataLines: [String]) throws {
        guard !dataLines.isEmpty else { return }
        let payloadText = dataLines.joined(separator: "\n")
        guard let data = payloadText.data(using: .utf8) else { throw MonitorAPIError.invalidResponse }
        let envelope = try decoder.decode(MonitorEnvelope<EveMonitorPayload>.self, from: data)
        if envelope.ok, let next = envelope.data {
            lastStreamFrameAt = Date()
            if !isPaused {
                apply(next, mode: "Realtime")
            }
            return
        }
        throw MonitorAPIError.server(envelope.error ?? "Eve returned an error.")
    }

    private func request<Payload: Decodable>(
        _ path: String,
        queryItems: [URLQueryItem] = [],
        timeout: TimeInterval
    ) async throws -> Payload {
        let endpoint = baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
        var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)
        components?.queryItems = queryItems.isEmpty ? nil : queryItems
        guard let url = components?.url else { throw MonitorAPIError.invalidResponse }
        var request = URLRequest(url: url)
        request.timeoutInterval = timeout
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            throw MonitorAPIError.invalidResponse
        }
        let envelope = try decoder.decode(MonitorEnvelope<Payload>.self, from: data)
        if envelope.ok, let data = envelope.data {
            return data
        }
        throw MonitorAPIError.server(envelope.error ?? "Eve returned an error.")
    }

    private func post<Payload: Decodable, Body: Encodable>(_ path: String, body: Body, timeout: TimeInterval) async throws -> Payload {
        let url = baseURL.appendingPathComponent(path.trimmingCharacters(in: CharacterSet(charactersIn: "/")))
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.timeoutInterval = timeout
        request.setValue("application/json; charset=utf-8", forHTTPHeaderField: "Content-Type")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.httpBody = try encoder.encode(body)
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse, 200..<300 ~= http.statusCode else {
            throw MonitorAPIError.invalidResponse
        }
        let envelope = try decoder.decode(MonitorEnvelope<Payload>.self, from: data)
        if envelope.ok, let data = envelope.data {
            return data
        }
        throw MonitorAPIError.server(envelope.error ?? "Eve returned an error.")
    }

    private func runHelper(_ command: String) {
        guard FileManager.default.isExecutableFile(atPath: helperURL.path) else { return }
        let process = Process()
        process.executableURL = helperURL
        process.arguments = [command]
        try? process.run()
    }

    private func runHelperAndWait(_ command: String) async throws {
        let url = helperURL
        guard FileManager.default.isExecutableFile(atPath: url.path) else {
            throw NSError(
                domain: "EveMonitorHelper",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "Eve helper is not installed at \(url.path)."]
            )
        }

        try await Task.detached(priority: .userInitiated) {
            let process = Process()
            process.executableURL = url
            process.arguments = [command]
            try process.run()
            process.waitUntilExit()
            guard process.terminationStatus == 0 else {
                throw NSError(
                    domain: "EveMonitorHelper",
                    code: Int(process.terminationStatus),
                    userInfo: [NSLocalizedDescriptionKey: "Eve helper command \(command) exited with status \(process.terminationStatus)."]
                )
            }
        }.value
    }
}
