import SwiftUI
import UniformTypeIdentifiers

private let oliveColor = Color(red: 0.29, green: 0.37, blue: 0.16)
private let bgColor    = Color(red: 0.91, green: 0.92, blue: 0.85)
private let goldColor  = Color(red: 0.99, green: 0.73, blue: 0.15)

struct LauncherView: View {
    @EnvironmentObject private var appState: AppState

    @State private var showSyncForm     = false
    @State private var username         = ""
    @State private var password         = ""
    @State private var troopName        = "My Troop"
    @State private var csvURL: URL?     = nil
    @State private var showCSVPicker    = false
    @State private var showDBPicker     = false

    var body: some View {
        VStack(spacing: 0) {
            appHeader
            ScrollView {
                VStack(spacing: 28) {
                    Text("Troop advancement dashboard for Scout leaders")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                        .padding(.top, 8)

                    if showSyncForm {
                        syncFormView
                    } else {
                        actionCards
                    }
                }
                .padding(.vertical, 32)
            }
        }
        .background(bgColor.ignoresSafeArea())
        .fileImporter(
            isPresented: $showDBPicker,
            allowedContentTypes: [UTType(filenameExtension: "db") ?? .data],
            allowsMultipleSelection: false
        ) { result in
            if case .success(let urls) = result, let url = urls.first {
                appState.dbPath = url.path
                appState.showDashboard = true
            }
        }
        .fileImporter(
            isPresented: $showCSVPicker,
            allowedContentTypes: [.commaSeparatedText],
            allowsMultipleSelection: false
        ) { result in
            if case .success(let urls) = result, let url = urls.first {
                csvURL = url
            }
        }
    }

    // MARK: - Header

    private var appHeader: some View {
        HStack(spacing: 12) {
            Text("⚜️").font(.system(size: 28))
            Text("Scouting Stats")
                .font(.system(size: 22, weight: .bold))
                .foregroundColor(.white)
            Spacer()
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 16)
        .background(oliveColor)
    }

    // MARK: - Action cards

    private var actionCards: some View {
        HStack(spacing: 24) {
            ActionCard(
                icon: "folder.fill",
                title: "Open Database",
                description: "Load an existing scouting_troop.db file"
            ) {
                showDBPicker = true
            }
            ActionCard(
                icon: "arrow.down.circle.fill",
                title: "Sign In & Sync",
                description: "Download advancement data from Scouting America"
            ) {
                showSyncForm = true
            }
        }
        .padding(.horizontal, 60)
    }

    // MARK: - Sync form

    private var syncFormView: some View {
        VStack(spacing: 20) {
            HStack {
                Button("← Back") { showSyncForm = false }
                    .buttonStyle(.plain)
                    .foregroundColor(oliveColor)
                Spacer()
                Text("Sign In & Sync")
                    .font(.title3.weight(.semibold))
                Spacer()
                // Spacer to balance the back button
                Color.clear.frame(width: 60)
            }
            .padding(.horizontal, 60)

            VStack(alignment: .leading, spacing: 16) {
                FormField(label: "Username") {
                    TextField("my.scouting.org username", text: $username)
                        .textFieldStyle(.roundedBorder)
                }
                FormField(label: "Password") {
                    SecureField("Password", text: $password)
                        .textFieldStyle(.roundedBorder)
                }
                FormField(label: "Troop Name") {
                    TextField("e.g. Troop 42", text: $troopName)
                        .textFieldStyle(.roundedBorder)
                }
                FormField(label: "Roster CSV (optional)") {
                    HStack {
                        Text(csvURL?.lastPathComponent ?? "No file selected")
                            .foregroundColor(csvURL == nil ? .secondary : .primary)
                            .font(.caption)
                            .lineLimit(1)
                            .truncationMode(.middle)
                        Spacer()
                        Button("Choose…") { showCSVPicker = true }
                            .controlSize(.small)
                    }
                }

                HStack {
                    Spacer()
                    Button("Start Sync") { startSync() }
                        .buttonStyle(.borderedProminent)
                        .tint(oliveColor)
                        .disabled(username.isEmpty || password.isEmpty)
                    Spacer()
                }
                .padding(.top, 4)
            }
            .padding(28)
            .background(Color.white)
            .cornerRadius(12)
            .shadow(color: .black.opacity(0.07), radius: 12, x: 0, y: 4)
            .padding(.horizontal, 60)
        }
    }

    // MARK: - Sync trigger

    private func startSync() {
        let supportDir = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)
            .first?
            .appendingPathComponent("ScoutingTroopStats", isDirectory: true)
        let dbURL = supportDir?.appendingPathComponent("scouting_troop.db")
            ?? URL(fileURLWithPath: "/tmp/scouting_troop.db")

        let dbPath = dbURL.path

        appState.beginSync(dbPath: dbPath)

        let capturedUsername = username
        let capturedPassword = password
        let capturedTroopName = troopName
        let capturedCSVPath = csvURL?.path

        Task {
            let service = SyncService()
            let success = await service.sync(
                username: capturedUsername,
                password: capturedPassword,
                troopName: capturedTroopName,
                dbPath: dbPath,
                csvPath: capturedCSVPath
            ) { message in
                await MainActor.run {
                    appState.appendMessage(message)
                }
            }
            await MainActor.run {
                appState.finishSync(success: success)
            }
        }
    }
}

// MARK: - Reusable subviews

private struct ActionCard: View {
    let icon: String
    let title: String
    let description: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 14) {
                Image(systemName: icon)
                    .font(.system(size: 40))
                    .foregroundColor(Color(red: 0.29, green: 0.37, blue: 0.16))
                Text(title)
                    .font(.headline)
                    .foregroundColor(.primary)
                Text(description)
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
            .padding(32)
            .background(Color.white)
            .cornerRadius(14)
            .shadow(color: .black.opacity(0.07), radius: 12, x: 0, y: 4)
        }
        .buttonStyle(.plain)
    }
}

private struct FormField<Content: View>: View {
    let label: String
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label)
                .font(.caption.weight(.semibold))
                .foregroundColor(.secondary)
            content()
        }
    }
}
