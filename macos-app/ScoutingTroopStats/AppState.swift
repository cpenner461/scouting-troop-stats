import Foundation
import Combine

/// Central application state shared across all views.
class AppState: ObservableObject {
    /// Path to the current SQLite database file.
    @Published var dbPath: String? = nil
    /// Whether the dashboard WebView is visible.
    @Published var showDashboard: Bool = false

    init() {
        // Auto-open the synced database if one already exists.
        if let url = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first?
            .appendingPathComponent("ScoutingTroopStats/scouting_troop.db"),
           FileManager.default.fileExists(atPath: url.path) {
            dbPath = url.path
            showDashboard = true
        }
    }
    /// Whether a sync operation is in progress.
    @Published var isSyncing: Bool = false
    /// Ordered log messages from the current/last sync.
    @Published var syncMessages: [SyncMessage] = []

    struct SyncMessage: Identifiable {
        let id = UUID()
        let type: MessageType
        let text: String

        enum MessageType {
            case step, log, error, complete
        }
    }

    func beginSync(dbPath: String) {
        self.dbPath = dbPath
        self.isSyncing = true
        self.syncMessages = []
    }

    func appendMessage(_ message: SyncMessage) {
        syncMessages.append(message)
    }

    func finishSync(success: Bool) {
        if success {
            isSyncing = false
            showDashboard = true
        }
        // On failure: leave isSyncing = true so SyncProgressView stays visible
        // with the error messages. The user dismisses it via the "Back" button.
    }
}
