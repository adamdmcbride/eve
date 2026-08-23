import AppKit
import AVFoundation
import Foundation
import Speech
import SwiftUI

struct PresenceAPIEnvelope<Payload: Decodable>: Decodable {
    let ok: Bool
    let data: Payload?
    let error: String?
}

struct PresenceStatusData: Decodable {
    let apiVersion: Int
}

struct PresenceMessageRecord: Decodable, Identifiable, Hashable {
    let id: String
    let timestamp: String
    let threadId: String
    let sender: String
    let recipient: String
    let subject: String
    let body: String
    let kind: String
    let status: String
    let replyTo: String?
    let preview: String
}

struct PresenceReplyResponse: Decodable {
    let threadId: String
    let reply: PresenceMessageRecord
    let messages: [PresenceMessageRecord]
}

struct PresenceReplyProgress: Decodable, Equatable {
    let id: String?
    let clientRequestId: String?
    let threadId: String?
    let status: String?
    let phase: String?
    let title: String?
    let detail: String?
    let updatedAt: String?
    let notes: [PresenceReplyProgressNote]?
}

struct PresenceReplyProgressNote: Decodable, Equatable, Hashable {
    let id: String?
    let timestamp: String?
    let phase: String?
    let kind: String?
    let title: String?
    let detail: String?
}

struct PresenceReplyProgressLookup: Decodable {
    let job: PresenceReplyProgress?
}

enum PresenceSpeaker: String, Hashable {
    case user
    case eve
    case system
}

struct PresenceTurn: Identifiable, Hashable {
    let id: String
    let speaker: PresenceSpeaker
    let text: String
    let timestamp: Date
}

enum PresenceMode: String {
    case connecting
    case idle
    case listening
    case thinking
    case speaking
    case error
}

enum PresenceTheme {
    static let backgroundTop = Color(red: 0.06, green: 0.08, blue: 0.12)
    static let backgroundBottom = Color(red: 0.03, green: 0.04, blue: 0.07)
    static let panel = Color.white.opacity(0.06)
    static let panelStrong = Color.white.opacity(0.1)
    static let divider = Color.white.opacity(0.09)
    static let textPrimary = Color.white.opacity(0.97)
    static let textSecondary = Color.white.opacity(0.76)
    static let textTertiary = Color.white.opacity(0.5)
    static let accent = Color(red: 0.36, green: 0.67, blue: 1.0)
    static let accentWarm = Color(red: 0.99, green: 0.58, blue: 0.36)
    static let accentSoft = accent.opacity(0.18)
    static let success = Color(red: 0.42, green: 0.82, blue: 0.56)
}

struct PresenceWindowAccessorView: NSViewRepresentable {
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
        if !window.title.isEmpty {
            window.title = ""
        }
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
        if currentSize.width < 1040 || currentSize.height < 880 {
            window.setContentSize(NSSize(width: 1120, height: 940))
            window.center()
        }
    }
}

struct PresenceGlassCard<Content: View>: View {
    let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .background(PresenceTheme.panel, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .stroke(Color.white.opacity(0.08), lineWidth: 1)
            )
    }
}
