import AppKit
import SwiftUI

final class EvePresenceAppDelegate: NSObject, NSApplicationDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        NSWindow.allowsAutomaticWindowTabbing = false
        NSApp.activate(ignoringOtherApps: true)
    }
}

@main
struct EvePresenceApp: App {
    @NSApplicationDelegateAdaptor(EvePresenceAppDelegate.self) private var appDelegate
    @StateObject private var model = EvePresenceModel()

    var body: some Scene {
        WindowGroup {
            EvePresenceRootView()
                .environmentObject(model)
                .preferredColorScheme(.dark)
                .frame(minWidth: 980, minHeight: 860)
        }
        .commands {
            CommandMenu("Presence") {
                Button("Reconnect") {
                    Task { await model.reconnect(forceRestart: true) }
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])

                Button("New Session") {
                    model.startFreshConversation()
                }
                .keyboardShortcut("n")

                Button(model.speakerEnabled ? "Mute Eve" : "Unmute Eve") {
                    model.toggleSpeaker()
                }
                .keyboardShortcut("m")

                Button("Primary Action") {
                    model.primaryAction()
                }
                .keyboardShortcut(.space, modifiers: [])
            }
        }
    }
}
