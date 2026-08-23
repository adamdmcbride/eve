import AppKit
import Combine
import Foundation
import SwiftUI

@main
struct EveDesktopApp: App {
    @NSApplicationDelegateAdaptor(EveAppDelegate.self) private var appDelegate
    @StateObject private var model = EveDesktopModel()

    var body: some Scene {
        WindowGroup {
            EveRootView()
                .environmentObject(model)
                .preferredColorScheme(.dark)
                .tint(EveTheme.accent)
                .frame(minWidth: 1220, minHeight: 820)
        }
        .commands {
            SidebarCommands()

            CommandMenu("Eve") {
                Button("Reconnect") {
                    Task { await model.reconnect(forceRestart: true) }
                }
                .keyboardShortcut("r", modifiers: [.command, .shift])

                Button("New Chat") {
                    model.newChat()
                }
                .keyboardShortcut("n")

                Button("Send Message") {
                    Task { await model.sendCurrentMessage() }
                }
                .keyboardShortcut(.return, modifiers: [.command])
                .disabled(!model.canSendCurrentMessage)
            }
        }
    }
}
