import SwiftUI

struct ContentView: View {
    @EnvironmentObject private var appState: AppState

    var body: some View {
        Group {
            if appState.showDashboard, let dbPath = appState.dbPath {
                DashboardView(dbPath: dbPath)
                    .toolbar {
                        ToolbarItem(placement: .navigation) {
                            Button {
                                appState.showDashboard = false
                            } label: {
                                Label("Launcher", systemImage: "chevron.left")
                            }
                            .help("Back to Launcher")
                        }
                    }
                    .navigationTitle("Scouting Stats")
            } else if appState.isSyncing {
                SyncProgressView()
            } else {
                LauncherView()
            }
        }
        .frame(minWidth: 960, minHeight: 640)
    }
}
