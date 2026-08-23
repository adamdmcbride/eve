import SwiftUI

private struct PresenceAvatarView: View {
    let mode: PresenceMode
    @State private var pulse = false
    @State private var shimmer = false

    private var orbScale: CGFloat {
        switch mode {
        case .listening:
            return pulse ? 1.03 : 0.96
        case .thinking:
            return pulse ? 1.02 : 0.98
        case .speaking:
            return pulse ? 1.05 : 0.94
        default:
            return pulse ? 1.0 : 0.97
        }
    }

    private var haloOpacity: Double {
        switch mode {
        case .listening:
            return 0.9
        case .thinking:
            return 0.72
        case .speaking:
            return 1.0
        default:
            return 0.5
        }
    }

    var body: some View {
        ZStack {
            ForEach(0..<3, id: \.self) { ring in
                Circle()
                    .stroke(
                        LinearGradient(
                            colors: [
                                PresenceTheme.accent.opacity(0.6 - Double(ring) * 0.12),
                                PresenceTheme.accentWarm.opacity(0.45 - Double(ring) * 0.1),
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        ),
                        lineWidth: ring == 0 ? 1.2 : 0.8
                    )
                    .frame(width: 250 + CGFloat(ring) * 48, height: 250 + CGFloat(ring) * 48)
                    .scaleEffect(pulse ? 1.02 + CGFloat(ring) * 0.015 : 0.96 + CGFloat(ring) * 0.01)
                    .opacity(haloOpacity - Double(ring) * 0.18)
                    .blur(radius: ring == 2 ? 2 : 0)
            }

            Circle()
                .fill(
                    RadialGradient(
                        colors: [
                            Color.white.opacity(0.96),
                            PresenceTheme.accent.opacity(0.92),
                            Color(red: 0.14, green: 0.26, blue: 0.42),
                        ],
                        center: .topLeading,
                        startRadius: 12,
                        endRadius: 170
                    )
                )
                .frame(width: 230, height: 230)
                .overlay(
                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [
                                    Color.white.opacity(0.42),
                                    Color.clear,
                                    PresenceTheme.accentWarm.opacity(0.18),
                                ],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .padding(10)
                )
                .overlay(
                    Circle()
                        .stroke(Color.white.opacity(0.24), lineWidth: 1)
                )
                .shadow(color: PresenceTheme.accent.opacity(0.35), radius: 30, y: 10)
                .scaleEffect(orbScale)

            VStack(spacing: 28) {
                HStack(spacing: 34) {
                    Capsule()
                        .fill(Color.white.opacity(0.9))
                        .frame(width: 18, height: mode == .listening ? 18 : 13)
                    Capsule()
                        .fill(Color.white.opacity(0.9))
                        .frame(width: 18, height: mode == .listening ? 18 : 13)
                }

                if mode == .speaking {
                    HStack(spacing: 7) {
                        ForEach(0..<5, id: \.self) { idx in
                            Capsule()
                                .fill(Color.white.opacity(0.92))
                                .frame(width: 7, height: pulse ? 14 + CGFloat((idx % 3) * 7) : 9 + CGFloat((idx % 3) * 5))
                        }
                    }
                } else if mode == .thinking {
                    HStack(spacing: 10) {
                        ForEach(0..<3, id: \.self) { _ in
                            Circle()
                                .fill(Color.white.opacity(0.86))
                                .frame(width: 9, height: 9)
                        }
                    }
                } else {
                    Capsule()
                        .fill(Color.white.opacity(0.88))
                        .frame(width: mode == .listening ? 54 : 48, height: mode == .listening ? 12 : 8)
                }
            }
            .offset(y: 6)
        }
        .frame(width: 360, height: 360)
        .overlay(
            Circle()
                .stroke(Color.white.opacity(shimmer ? 0.18 : 0.05), lineWidth: 18)
                .blur(radius: 18)
        )
        .onAppear {
            withAnimation(.easeInOut(duration: 2.2).repeatForever(autoreverses: true)) {
                pulse = true
            }
            withAnimation(.easeInOut(duration: 3.1).repeatForever(autoreverses: true)) {
                shimmer = true
            }
        }
    }
}

private struct PresenceStatusBadge: View {
    let text: String
    let color: Color

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(color)
                .frame(width: 8, height: 8)
            Text(text)
                .font(.system(size: 12.5, weight: .semibold))
                .foregroundStyle(PresenceTheme.textPrimary)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(PresenceTheme.panelStrong, in: Capsule())
        .overlay(Capsule().stroke(Color.white.opacity(0.08), lineWidth: 1))
    }
}

private struct PresenceTopBar: View {
    @EnvironmentObject private var model: EvePresenceModel

    var body: some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 4) {
                Text("Eve Presence")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(PresenceTheme.textPrimary)
                Text("A separate space for speaking with Eve")
                    .font(.system(size: 12.5))
                    .foregroundStyle(PresenceTheme.textTertiary)
            }

            Spacer()

            PresenceStatusBadge(text: model.topStatusText, color: model.topStatusColor)

            Button {
                model.toggleSpeaker()
            } label: {
                Image(systemName: model.speakerEnabled ? "speaker.wave.2.fill" : "speaker.slash.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(PresenceTheme.textPrimary)
                    .frame(width: 40, height: 40)
                    .background(PresenceTheme.panelStrong, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
            .buttonStyle(.plain)
            .help(model.speakerEnabled ? "Mute Eve's spoken reply" : "Enable spoken replies")

            Button {
                model.startFreshConversation()
            } label: {
                Label("New", systemImage: "plus")
                    .font(.system(size: 13.5, weight: .semibold))
                    .foregroundStyle(PresenceTheme.textPrimary)
                    .padding(.horizontal, 14)
                    .frame(height: 40)
                    .background(PresenceTheme.panelStrong, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
            .buttonStyle(.plain)
            .help("Start a fresh voice session")

            Button {
                Task { await model.reconnect(forceRestart: true) }
            } label: {
                Image(systemName: "arrow.clockwise")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(PresenceTheme.textPrimary)
                    .frame(width: 40, height: 40)
                    .background(PresenceTheme.panelStrong, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
            .buttonStyle(.plain)
            .help("Reconnect to Eve")
        }
    }
}

private struct LiveTranscriptCardView: View {
    @EnvironmentObject private var model: EvePresenceModel

    var body: some View {
        PresenceGlassCard {
            VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 10) {
                    Text(model.phaseTitle)
                        .font(.system(size: 28, weight: .semibold))
                        .foregroundStyle(PresenceTheme.textPrimary)

                    Spacer()

                    if model.mode == .listening || model.mode == .thinking || model.mode == .speaking {
                        PresenceStatusBadge(text: model.modeLabel, color: model.topStatusColor)
                    }
                }

                Text(model.phaseDetail)
                    .font(.system(size: 16))
                    .foregroundStyle(PresenceTheme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)

                if model.mode == .listening && !model.liveTranscript.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Live transcript")
                            .font(.system(size: 12.5, weight: .medium))
                            .foregroundStyle(PresenceTheme.textTertiary)
                        Text(model.liveTranscript)
                            .font(.system(size: 19, weight: .medium))
                            .foregroundStyle(PresenceTheme.textPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                } else if model.mode == .thinking && !model.liveNotes.isEmpty {
                    VStack(alignment: .leading, spacing: 10) {
                        Text("Working stream")
                            .font(.system(size: 12.5, weight: .medium))
                            .foregroundStyle(PresenceTheme.textTertiary)

                        ForEach(model.liveNotes, id: \.self) { note in
                            HStack(alignment: .top, spacing: 10) {
                                Circle()
                                    .fill(PresenceTheme.accent.opacity(0.9))
                                    .frame(width: 6, height: 6)
                                    .padding(.top, 6)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(note.title ?? "Thinking")
                                        .font(.system(size: 14.5, weight: .medium))
                                        .foregroundStyle(PresenceTheme.textPrimary)
                                    if let detail = note.detail, !detail.isEmpty {
                                        Text(detail)
                                            .font(.system(size: 13))
                                            .foregroundStyle(PresenceTheme.textSecondary)
                                            .fixedSize(horizontal: false, vertical: true)
                                    }
                                }
                                Spacer()
                                Text(model.formatProgressTimestamp(note.timestamp))
                                    .font(.system(size: 11.5))
                                    .foregroundStyle(PresenceTheme.textTertiary)
                            }
                        }
                    }
                } else if model.mode == .speaking && !model.currentSpokenReply.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Speaking aloud")
                            .font(.system(size: 12.5, weight: .medium))
                            .foregroundStyle(PresenceTheme.textTertiary)
                        Text(model.currentSpokenReply)
                            .font(.system(size: 16.5))
                            .foregroundStyle(PresenceTheme.textPrimary)
                            .lineSpacing(4)
                            .lineLimit(4)
                    }
                }
            }
            .padding(26)
        }
    }
}

private struct PresenceControlButton: View {
    let title: String
    let enabled: Bool
    let mode: PresenceMode
    let action: () -> Void

    private var gradient: LinearGradient {
        switch mode {
        case .listening:
            return LinearGradient(colors: [PresenceTheme.accentWarm, PresenceTheme.accent], startPoint: .topLeading, endPoint: .bottomTrailing)
        case .thinking:
            return LinearGradient(colors: [Color.white.opacity(0.14), Color.white.opacity(0.08)], startPoint: .topLeading, endPoint: .bottomTrailing)
        case .speaking:
            return LinearGradient(colors: [PresenceTheme.accent, PresenceTheme.accentWarm], startPoint: .topLeading, endPoint: .bottomTrailing)
        default:
            return LinearGradient(colors: [PresenceTheme.accent, PresenceTheme.accent.opacity(0.72)], startPoint: .topLeading, endPoint: .bottomTrailing)
        }
    }

    var body: some View {
        Button(action: action) {
            VStack(spacing: 10) {
                Image(systemName: mode == .listening ? "waveform.circle.fill" : "mic.circle.fill")
                    .font(.system(size: 30, weight: .medium))
                Text(title)
                    .font(.system(size: 16, weight: .semibold))
            }
            .foregroundStyle(Color.white.opacity(enabled ? 0.98 : 0.5))
            .frame(width: 220, height: 220)
            .background(gradient, in: Circle())
            .overlay(
                Circle()
                    .stroke(Color.white.opacity(enabled ? 0.18 : 0.08), lineWidth: 1)
            )
            .shadow(color: PresenceTheme.accent.opacity(enabled ? 0.24 : 0.08), radius: 24, y: 14)
        }
        .buttonStyle(.plain)
        .disabled(!enabled)
    }
}

private struct TranscriptTurnRowView: View {
    let turn: PresenceTurn
    let timeText: String

    private var isUser: Bool { turn.speaker == .user }

    var body: some View {
        HStack {
            if !isUser { Spacer(minLength: 110) }

            VStack(alignment: .leading, spacing: 8) {
                Text("\(isUser ? "You" : "Eve") · \(timeText)")
                    .font(.system(size: 11.5, weight: .semibold))
                    .foregroundStyle(PresenceTheme.textTertiary)

                Text(turn.text)
                    .font(.system(size: 18))
                    .foregroundStyle(PresenceTheme.textPrimary)
                    .lineSpacing(4)
                    .fixedSize(horizontal: false, vertical: true)
                    .textSelection(.enabled)
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 16)
            .background(
                isUser ? PresenceTheme.panelStrong : PresenceTheme.panel,
                in: RoundedRectangle(cornerRadius: 22, style: .continuous)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 22, style: .continuous)
                    .stroke(Color.white.opacity(0.08), lineWidth: 1)
            )
            .frame(maxWidth: 760, alignment: isUser ? .trailing : .leading)

            if isUser { Spacer(minLength: 110) }
        }
    }
}

private struct TranscriptPanelView: View {
    @EnvironmentObject private var model: EvePresenceModel

    var body: some View {
        PresenceGlassCard {
            VStack(alignment: .leading, spacing: 18) {
                HStack {
                    Text("Conversation")
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundStyle(PresenceTheme.textPrimary)
                    Spacer()
                    Text("\(model.turns.count) turns")
                        .font(.system(size: 12.5, weight: .medium))
                        .foregroundStyle(PresenceTheme.textTertiary)
                }

                if model.turns.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "waveform.and.mic")
                            .font(.system(size: 34))
                            .foregroundStyle(PresenceTheme.textSecondary)
                        Text("This space is for speaking with Eve.")
                            .font(.system(size: 20, weight: .semibold))
                            .foregroundStyle(PresenceTheme.textPrimary)
                        Text("Tap the center button, talk naturally, and Eve will answer here and out loud.")
                            .font(.system(size: 14.5))
                            .foregroundStyle(PresenceTheme.textSecondary)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: 420)
                    }
                    .frame(maxWidth: .infinity, minHeight: 220)
                } else {
                    ScrollView {
                        LazyVStack(spacing: 16) {
                            ForEach(model.turns.suffix(8)) { turn in
                                TranscriptTurnRowView(turn: turn, timeText: model.formatTime(turn.timestamp))
                            }
                        }
                    }
                    .frame(minHeight: 220, maxHeight: 320)
                }
            }
            .padding(24)
        }
    }
}

struct EvePresenceRootView: View {
    @EnvironmentObject private var model: EvePresenceModel

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [
                    PresenceTheme.backgroundTop,
                    Color(red: 0.05, green: 0.05, blue: 0.08),
                    PresenceTheme.backgroundBottom,
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            Circle()
                .fill(PresenceTheme.accent.opacity(0.14))
                .frame(width: 560, height: 560)
                .blur(radius: 80)
                .offset(x: -120, y: -180)

            Circle()
                .fill(PresenceTheme.accentWarm.opacity(0.12))
                .frame(width: 500, height: 500)
                .blur(radius: 90)
                .offset(x: 280, y: 240)

            VStack(spacing: 26) {
                PresenceTopBar()

                Spacer(minLength: 0)

                VStack(spacing: 18) {
                    PresenceAvatarView(mode: model.mode)

                    PresenceControlButton(
                        title: model.primaryButtonTitle,
                        enabled: model.primaryButtonEnabled,
                        mode: model.mode
                    ) {
                        model.primaryAction()
                    }
                }

                LiveTranscriptCardView()
                    .frame(maxWidth: 760)

                TranscriptPanelView()
                    .frame(maxWidth: 940)

                Spacer(minLength: 0)
            }
            .padding(.horizontal, 34)
            .padding(.top, 24)
            .padding(.bottom, 28)
        }
        .background(PresenceWindowAccessorView().allowsHitTesting(false))
        .task {
            await model.start()
        }
    }
}
