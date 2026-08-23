import AVFoundation
import AppKit
import Combine
import Foundation
import Speech
import SwiftUI

@MainActor
final class EvePresenceModel: NSObject, ObservableObject, @preconcurrency AVSpeechSynthesizerDelegate {
    @Published var mode: PresenceMode = .connecting
    @Published var phaseTitle = "Connecting to Eve"
    @Published var phaseDetail = "Opening Eve's local voice presence."
    @Published var isConnected = false
    @Published var speakerEnabled = true
    @Published var speechAuthorized = false
    @Published var microphoneAuthorized = false
    @Published var liveTranscript = ""
    @Published var currentSpokenReply = ""
    @Published var turns: [PresenceTurn] = []
    @Published var liveNotes: [PresenceReplyProgressNote] = []

    private let requiredAPIVersion = 5
    private let baseURL = URL(string: "http://127.0.0.1:8787")!
    private let synthesizer = AVSpeechSynthesizer()
    private let audioEngine = AVAudioEngine()
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

    private var hasStarted = false
    private var currentThreadID: String?
    private var lastMessageID: String?
    private var progressTask: Task<Void, Never>?
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private var speechRecognizer = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))

    private var helperURL: URL {
        FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".eve_runtime/bin/eve_control.sh")
    }

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    var modeLabel: String {
        switch mode {
        case .connecting:
            return "Connecting"
        case .idle:
            return "Ready"
        case .listening:
            return "Listening"
        case .thinking:
            return "Thinking"
        case .speaking:
            return "Speaking"
        case .error:
            return "Needs attention"
        }
    }

    var topStatusText: String {
        if !isConnected {
            return "Offline"
        }
        switch mode {
        case .connecting:
            return "Connecting"
        case .idle:
            return "Live"
        case .listening:
            return "Listening"
        case .thinking:
            return "Thinking"
        case .speaking:
            return "Speaking"
        case .error:
            return "Attention"
        }
    }

    var topStatusColor: Color {
        switch mode {
        case .idle:
            return PresenceTheme.success
        case .listening:
            return PresenceTheme.accent
        case .thinking:
            return PresenceTheme.accentWarm
        case .speaking:
            return PresenceTheme.accent
        case .connecting:
            return PresenceTheme.textTertiary
        case .error:
            return Color.red.opacity(0.9)
        }
    }

    var primaryButtonTitle: String {
        switch mode {
        case .connecting:
            return "Reconnect"
        case .idle, .error:
            return "Talk to Eve"
        case .listening:
            return "Send to Eve"
        case .thinking:
            return "Eve is thinking"
        case .speaking:
            return "Interrupt and speak"
        }
    }

    var primaryButtonEnabled: Bool {
        mode != .thinking
    }

    func start() async {
        guard !hasStarted else { return }
        hasStarted = true
        await requestPermissions()
        await reconnect(forceRestart: false)
    }

    func reconnect(forceRestart: Bool) async {
        mode = .connecting
        phaseTitle = forceRestart ? "Reconnecting to Eve" : "Connecting to Eve"
        phaseDetail = "Opening Eve's local voice presence."
        isConnected = false

        if forceRestart {
            runHelper("web-restart")
        }

        var restartAttempted = forceRestart

        for attempt in 0..<40 {
            do {
                let status: PresenceStatusData = try await request("/api/status", timeout: 2)
                if status.apiVersion >= requiredAPIVersion {
                    isConnected = true
                    mode = .idle
                    phaseTitle = "Eve is here"
                    phaseDetail = "Tap the center button and speak."
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

        mode = .error
        isConnected = false
        phaseTitle = "Could not reach Eve"
        phaseDetail = "The local Eve interface did not start in time."
    }

    func startFreshConversation() {
        stopSpeaking()
        stopReplyProgress()
        stopListening(resetTranscript: true)
        currentThreadID = nil
        lastMessageID = nil
        currentSpokenReply = ""
        liveNotes = []
        turns = []
        mode = isConnected ? .idle : .connecting
        phaseTitle = isConnected ? "Eve is here" : "Connecting to Eve"
        phaseDetail = isConnected ? "Tap the center button and speak." : "Opening Eve's local voice presence."
    }

    func toggleSpeaker() {
        speakerEnabled.toggle()
        if !speakerEnabled {
            stopSpeaking()
        }
    }

    func primaryAction() {
        switch mode {
        case .connecting:
            Task { await reconnect(forceRestart: true) }
        case .idle, .error:
            Task { await beginListening() }
        case .listening:
            Task { await finishListeningAndSend() }
        case .speaking:
            stopSpeaking()
            Task { await beginListening() }
        case .thinking:
            break
        }
    }

    private func requestPermissions() async {
        speechAuthorized = await requestSpeechAuthorization()
        microphoneAuthorized = await requestMicrophoneAuthorization()
        if !speechAuthorized || !microphoneAuthorized {
            mode = .error
            phaseTitle = "Voice permissions needed"
            phaseDetail = "Allow microphone and speech recognition to talk with Eve."
        }
    }

    private func requestSpeechAuthorization() async -> Bool {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status == .authorized)
            }
        }
    }

    private func requestMicrophoneAuthorization() async -> Bool {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            return true
        case .notDetermined:
            return await withCheckedContinuation { continuation in
                AVCaptureDevice.requestAccess(for: .audio) { granted in
                    continuation.resume(returning: granted)
                }
            }
        default:
            return false
        }
    }

    private func beginListening() async {
        guard isConnected else {
            await reconnect(forceRestart: true)
            return
        }
        guard speechAuthorized && microphoneAuthorized else {
            await requestPermissions()
            return
        }

        stopSpeaking()
        stopReplyProgress()
        currentSpokenReply = ""
        liveNotes = []
        liveTranscript = ""
        phaseTitle = "Listening"
        phaseDetail = "Speak naturally, then tap again when you're ready to send."
        mode = .listening

        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest = SFSpeechAudioBufferRecognitionRequest()

        guard let recognitionRequest else {
            mode = .error
            phaseTitle = "Listening failed"
            phaseDetail = "Could not start speech recognition."
            return
        }

        recognitionRequest.shouldReportPartialResults = true
        let inputNode = audioEngine.inputNode
        let format = inputNode.outputFormat(forBus: 0)
        inputNode.removeTap(onBus: 0)
        inputNode.installTap(onBus: 0, bufferSize: 1024, format: format) { [weak self] buffer, _ in
            self?.recognitionRequest?.append(buffer)
        }

        audioEngine.prepare()
        do {
            try audioEngine.start()
        } catch {
            stopListening(resetTranscript: false)
            mode = .error
            phaseTitle = "Listening failed"
            phaseDetail = error.localizedDescription
            return
        }

        recognitionTask = speechRecognizer?.recognitionTask(with: recognitionRequest) { [weak self] result, error in
            guard let self else { return }
            Task { @MainActor in
                if let result {
                    self.liveTranscript = result.bestTranscription.formattedString
                }
                if let error {
                    self.stopListening(resetTranscript: false)
                    if self.liveTranscript.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                        self.mode = .error
                        self.phaseTitle = "Listening failed"
                        self.phaseDetail = error.localizedDescription
                    }
                }
            }
        }
    }

    private func finishListeningAndSend() async {
        let transcript = liveTranscript.trimmingCharacters(in: .whitespacesAndNewlines)
        stopListening(resetTranscript: false)

        guard !transcript.isEmpty else {
            mode = .idle
            phaseTitle = "I didn't catch anything"
            phaseDetail = "Tap again and try speaking a little longer."
            return
        }

        turns.append(PresenceTurn(id: UUID().uuidString, speaker: .user, text: transcript, timestamp: Date()))
        liveTranscript = ""
        await sendTranscript(transcript)
    }

    private func sendTranscript(_ transcript: String) async {
        let clientRequestID = UUID().uuidString
        mode = .thinking
        phaseTitle = "Eve is receiving you"
        phaseDetail = "Starting a reply through the local runtime."
        startReplyProgress(clientRequestID: clientRequestID)

        let subject = "Voice conversation"

        do {
            let response: PresenceReplyResponse
            if let lastMessageID {
                response = try await request(
                    "/api/message/reply",
                    method: "POST",
                    json: [
                        "message_id": lastMessageID,
                        "body": transcript,
                        "subject": subject,
                        "client_request_id": clientRequestID,
                    ],
                    timeout: 600
                )
            } else {
                response = try await request(
                    "/api/message/ask",
                    method: "POST",
                    json: [
                        "body": transcript,
                        "subject": subject,
                        "client_request_id": clientRequestID,
                    ],
                    timeout: 600
                )
            }

            stopReplyProgress()
            currentThreadID = response.threadId
            lastMessageID = response.messages.last?.id ?? response.reply.id

            let replyText = response.reply.body.trimmingCharacters(in: .whitespacesAndNewlines)
            turns.append(PresenceTurn(id: response.reply.id, speaker: .eve, text: replyText, timestamp: parseDate(response.reply.timestamp) ?? Date()))
            currentSpokenReply = replyText

            if speakerEnabled && !replyText.isEmpty {
                speak(replyText)
            } else {
                mode = .idle
                phaseTitle = "Eve answered"
                phaseDetail = "Tap again whenever you want to keep going."
            }
        } catch {
            stopReplyProgress()
            mode = .error
            phaseTitle = "Reply failed"
            phaseDetail = error.localizedDescription
        }
    }

    private func startReplyProgress(clientRequestID: String) {
        stopReplyProgress()
        progressTask = Task { [weak self] in
            guard let self else { return }
            let encoded = clientRequestID.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? clientRequestID
            while !Task.isCancelled {
                do {
                    let lookup: PresenceReplyProgressLookup = try await self.request(
                        "/api/reply-progress?client_request_id=\(encoded)",
                        timeout: 4
                    )
                    guard !Task.isCancelled else { return }
                    if let job = lookup.job {
                        self.applyProgress(job)
                        if job.status != "active" {
                            return
                        }
                    }
                } catch {
                    return
                }
                try? await Task.sleep(nanoseconds: 650_000_000)
            }
        }
    }

    private func stopReplyProgress() {
        progressTask?.cancel()
        progressTask = nil
    }

    private func applyProgress(_ job: PresenceReplyProgress) {
        mode = .thinking
        if let title = job.title?.trimmingCharacters(in: .whitespacesAndNewlines), !title.isEmpty {
            phaseTitle = title
        } else {
            phaseTitle = "Eve is thinking"
        }
        if let detail = job.detail?.trimmingCharacters(in: .whitespacesAndNewlines), !detail.isEmpty {
            phaseDetail = detail
        } else {
            phaseDetail = "Working through the reply."
        }
        liveNotes = Array((job.notes ?? []).suffix(5))
    }

    private func speak(_ text: String) {
        guard !text.isEmpty else {
            mode = .idle
            phaseTitle = "Ready"
            phaseDetail = "Tap to speak with Eve again."
            return
        }

        synthesizer.stopSpeaking(at: .immediate)
        let utterance = AVSpeechUtterance(string: text)
        utterance.rate = 0.47
        utterance.pitchMultiplier = 0.98
        utterance.voice = AVSpeechSynthesisVoice(language: "en-US")
        mode = .speaking
        phaseTitle = "Eve is speaking"
        phaseDetail = "Tap again if you want to interrupt and answer back."
        synthesizer.speak(utterance)
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in
            if self.mode == .speaking {
                self.mode = .idle
                self.phaseTitle = "Eve is here"
                self.phaseDetail = "Tap again whenever you want to keep going."
            }
        }
    }

    func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in
            if self.mode == .speaking {
                self.mode = .idle
                self.phaseTitle = "Interrupted"
                self.phaseDetail = "You can speak again right away."
            }
        }
    }

    private func stopSpeaking() {
        if synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }
    }

    private func stopListening(resetTranscript: Bool) {
        audioEngine.stop()
        audioEngine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
        recognitionTask?.cancel()
        recognitionTask = nil
        recognitionRequest = nil
        if resetTranscript {
            liveTranscript = ""
        }
    }

    private func runHelper(_ command: String) {
        let process = Process()
        process.executableURL = helperURL
        process.arguments = [command]
        process.standardOutput = Pipe()
        process.standardError = Pipe()
        try? process.run()
    }

    private func parseDate(_ value: String?) -> Date? {
        guard let value else { return nil }
        if let date = isoFormatterWithFractional.date(from: value) {
            return date
        }
        return isoFormatter.date(from: value)
    }

    func formatTime(_ date: Date) -> String {
        date.formatted(date: .omitted, time: .shortened)
    }

    func formatProgressTimestamp(_ value: String?) -> String {
        guard let date = parseDate(value) else { return "Now" }
        return formatTime(date)
    }

    private func request<T: Decodable>(
        _ path: String,
        method: String = "GET",
        json: [String: String]? = nil,
        timeout: TimeInterval = 30
    ) async throws -> T {
        guard let url = URL(string: path.hasPrefix("/") ? path : "/\(path)", relativeTo: baseURL) else {
            throw NSError(domain: "EvePresence", code: 0, userInfo: [NSLocalizedDescriptionKey: "Invalid Eve request URL"])
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = timeout
        if let json {
            request.httpBody = try JSONSerialization.data(withJSONObject: json, options: [])
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw NSError(domain: "EvePresence", code: 0, userInfo: [NSLocalizedDescriptionKey: "Invalid response from Eve"])
        }
        let envelope = try decoder.decode(PresenceAPIEnvelope<T>.self, from: data)
        if (200..<300).contains(http.statusCode), let payload = envelope.data {
            return payload
        }
        let message = envelope.error ?? HTTPURLResponse.localizedString(forStatusCode: http.statusCode)
        throw NSError(domain: "EvePresence", code: http.statusCode, userInfo: [NSLocalizedDescriptionKey: message])
    }
}
