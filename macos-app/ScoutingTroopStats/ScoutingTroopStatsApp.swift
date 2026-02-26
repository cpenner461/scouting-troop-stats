import SwiftUI

@main
struct ScoutingTroopStatsApp: App {
    @StateObject private var appState = AppState()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .frame(minWidth: 960, minHeight: 640)
        }
        .windowStyle(.titleBar)
        .windowToolbarStyle(.unified)
        .commands {
            CommandGroup(replacing: .newItem) {}
            CommandGroup(after: .appInfo) {
                Button("Open Database…") {
                    openDatabase()
                }
                .keyboardShortcut("o", modifiers: .command)

                if appState.showDashboard {
                    Button("Back to Launcher") {
                        appState.showDashboard = false
                    }
                    .keyboardShortcut("l", modifiers: [.command, .shift])
                }
            }
        }
    }

    private func openDatabase() {
        let panel = NSOpenPanel()
        panel.title = "Open Scouting Database"
        panel.message = "Select a scouting_troop.db file"
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = false
        // UTType(filenameExtension:) is failable; fall back to .database then .data.
        panel.allowedContentTypes = [
            UTType(filenameExtension: "db") ?? .database,
            .database,
        ]
        if panel.runModal() == .OK, let url = panel.url {
            appState.dbPath = url.path
            appState.showDashboard = true
        }
    }
}
