import AppKit
import SwiftUI

@main
struct EveMonitorApp: App {
    @NSApplicationDelegateAdaptor(EveMonitorAppDelegate.self) private var appDelegate
    @StateObject private var model = EveMonitorModel()

    var body: some Scene {
        WindowGroup {
            EveMonitorRootView()
                .environmentObject(model)
                .tint(MonitorTheme.accent)
                .frame(minWidth: 980, minHeight: 700)
        }
        .windowStyle(.titleBar)
        .windowToolbarStyle(.unified)
        .commands {
            CommandMenu("Monitor") {
                Button("Refresh Now") {
                    Task { await model.refreshNow() }
                }
                .keyboardShortcut("r", modifiers: [.command])

                Button(model.isPaused ? "Resume Live Updates" : "Pause Live Updates") {
                    model.togglePaused()
                }
                .keyboardShortcut("p", modifiers: [.command])

                Divider()

                Button("Open Web Monitor") {
                    model.openWebMonitor()
                }
                .keyboardShortcut("m", modifiers: [.command, .shift])

                Button("Reconnect Eve Web") {
                    Task { await model.reconnect(forceRestart: true) }
                }
            }
        }
    }
}
