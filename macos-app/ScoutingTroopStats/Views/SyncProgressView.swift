import SwiftUI

private let oliveColor = Color(red: 0.29, green: 0.37, blue: 0.16)
private let bgColor    = Color(red: 0.91, green: 0.92, blue: 0.85)

struct SyncProgressView: View {
    @EnvironmentObject private var appState: AppState

    private var isComplete: Bool {
        appState.syncMessages.last?.type == .complete
    }

    private var hasError: Bool {
        appState.syncMessages.contains { $0.type == .error }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack(spacing: 12) {
                Text("⚜️").font(.system(size: 28))
                Text("Scouting Stats")
                    .font(.system(size: 22, weight: .bold))
                    .foregroundColor(.white)
                Spacer()
                if isComplete || hasError {
                    Button("Back") {
                        appState.isSyncing = false
                    }
                    .buttonStyle(.plain)
                    .foregroundColor(.white.opacity(0.85))
                    .padding(.trailing, 4)
                }
            }
            .padding(.horizontal, 24)
            .padding(.vertical, 16)
            .background(oliveColor)

            VStack(spacing: 20) {
                if !isComplete {
                    HStack(spacing: 12) {
                        ProgressView()
                        Text("Syncing data from Scouting America…")
                            .font(.headline)
                    }
                    .padding(.top, 4)
                } else if hasError {
                    Label("Sync completed with errors", systemImage: "exclamationmark.triangle.fill")
                        .foregroundColor(.orange)
                        .font(.headline)
                        .padding(.top, 4)
                } else {
                    Label("Sync complete!", systemImage: "checkmark.circle.fill")
                        .foregroundColor(.green)
                        .font(.headline)
                        .padding(.top, 4)
                }

                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 5) {
                            ForEach(appState.syncMessages) { msg in
                                messageRow(msg)
                                    .id(msg.id)
                            }
                        }
                        .padding(14)
                    }
                    .frame(maxWidth: 680)
                    .background(Color.black.opacity(0.04))
                    .cornerRadius(10)
                    .onChange(of: appState.syncMessages.count) { _ in
                        if let last = appState.syncMessages.last {
                            withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                        }
                    }
                }
                .padding(.horizontal, 40)
            }
            .padding(.vertical, 24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(bgColor.ignoresSafeArea())
        }
    }

    @ViewBuilder
    private func messageRow(_ msg: AppState.SyncMessage) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Group {
                switch msg.type {
                case .step:
                    Text("▶").foregroundColor(oliveColor)
                case .error:
                    Text("✗").foregroundColor(.red)
                case .complete:
                    Text("✓").foregroundColor(.green)
                case .log:
                    Text("·").foregroundColor(.secondary)
                }
            }
            .font(.system(.body, design: .monospaced))
            .frame(width: 16, alignment: .leading)

            Text(msg.text)
                .font(.system(.body, design: .monospaced))
                .foregroundColor(msg.type == .error ? .red : .primary)
                .textSelection(.enabled)
                .fixedSize(horizontal: false, vertical: true)

            Spacer()
        }
    }
}
