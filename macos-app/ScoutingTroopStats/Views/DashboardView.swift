import SwiftUI
import WebKit

/// Wraps a WKWebView that loads the existing dashboard.html via a custom
/// `scouting://` URL scheme. A WKURLSchemeHandler serves the HTML, sql.js
/// WASM assets, and the SQLite database — no local HTTP server required.
///
/// A small JavaScript bridge injected at document start defines
/// `window.electronAPI` so the dashboard's existing Electron code path is
/// taken: sql.js and its WASM binary are loaded from the app bundle rather
/// than from the CDN, making the app fully offline-capable.
struct DashboardView: NSViewRepresentable {
    let dbPath: String

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()

        // Register the custom scheme handler before creating the web view.
        config.setURLSchemeHandler(
            ScoutingURLSchemeHandler(dbPath: dbPath),
            forURLScheme: "scouting"
        )

        // Inject window.electronAPI so dashboard.html loads WASM from bundle.
        let bridge = """
        window.electronAPI = {
            getPaths: async () => ({ vendorPath: 'scouting://localhost/vendor' }),
            readFile: async (path) => {
                const resp = await fetch(path);
                if (!resp.ok) throw new Error('HTTP ' + resp.status + ' fetching ' + path);
                return await resp.arrayBuffer();
            },
            navigate: (url) => { window.location.href = url; },
            showOpenDialog: async () => ({ canceled: true, filePaths: [] }),
            syncData: async () => ({ success: false }),
            onSyncProgress: () => {}
        };
        """
        let userScript = WKUserScript(
            source: bridge,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        )
        config.userContentController.addUserScript(userScript)

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator

        let request = URLRequest(url: URL(string: "scouting://localhost/dashboard.html")!)
        webView.load(request)
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator() }

    // MARK: - Coordinator

    final class Coordinator: NSObject, WKNavigationDelegate {
        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            // Allow scouting:// and about:blank; open anything else externally.
            if let scheme = navigationAction.request.url?.scheme,
               scheme == "scouting" || scheme == "about" {
                decisionHandler(.allow)
            } else if let url = navigationAction.request.url {
                NSWorkspace.shared.open(url)
                decisionHandler(.cancel)
            } else {
                decisionHandler(.allow)
            }
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            print("[DashboardView] Navigation failed: \(error.localizedDescription)")
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation _: WKNavigation!, withError error: Error) {
            print("[DashboardView] Provisional navigation failed: \(error.localizedDescription)")
        }
    }
}
