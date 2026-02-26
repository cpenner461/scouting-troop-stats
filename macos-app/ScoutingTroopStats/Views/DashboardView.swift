import SwiftUI
import WebKit

/// Wraps a WKWebView that loads the existing dashboard.html via a custom
/// `scouting://` URL scheme. A WKURLSchemeHandler serves the HTML and the
/// bundled sql.js WASM assets — no local HTTP server required.
///
/// After the page finishes loading, the coordinator reads the SQLite database
/// from disk and injects its bytes directly into JavaScript, calling the
/// dashboard's own `loadDbBuffer()` function. This is more reliable than the
/// dashboard's fetch-based auto-load because it:
///   • Works whether or not the WKURLSchemeHandler can serve the database
///   • Works whether or not vendor files are present in the app bundle
///   • Is not affected by cross-origin or custom-scheme fetch restrictions
struct DashboardView: NSViewRepresentable {
    let dbPath: String

    func makeNSView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()

        // Register the custom scheme handler for html + vendor assets.
        config.setURLSchemeHandler(
            ScoutingURLSchemeHandler(dbPath: dbPath),
            forURLScheme: "scouting"
        )

        // Inject window.electronAPI so the dashboard uses the bundled sql.js
        // WASM rather than fetching it from CDN (fully offline-capable).
        // readFile is implemented as a simple fetch against our scouting:// scheme.
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
        // Ensure the web view expands to fill its SwiftUI container.
        webView.autoresizingMask = [.width, .height]
        webView.navigationDelegate = context.coordinator
        context.coordinator.dbPath = dbPath

        let request = URLRequest(url: URL(string: "scouting://localhost/dashboard.html")!)
        webView.load(request)
        return webView
    }

    func updateNSView(_ nsView: WKWebView, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator() }

    // MARK: - Coordinator

    final class Coordinator: NSObject, WKNavigationDelegate {
        var dbPath: String = ""

        // Called when the page (and all its blocking scripts) have finished loading.
        // At this point initSQL and loadDbBuffer are guaranteed to be defined.
        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            injectDatabase(into: webView)
        }

        // Also inject after a provisional failure in case of non-fatal errors.
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            print("[DashboardView] Navigation failed: \(error.localizedDescription)")
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation _: WKNavigation!, withError error: Error) {
            print("[DashboardView] Provisional navigation failed: \(error.localizedDescription)")
        }

        func webView(
            _ webView: WKWebView,
            decidePolicyFor navigationAction: WKNavigationAction,
            decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
        ) {
            guard let scheme = navigationAction.request.url?.scheme else {
                decisionHandler(.allow); return
            }
            if scheme == "scouting" || scheme == "about" || scheme == "blob" {
                decisionHandler(.allow)
            } else {
                // Open external links (http/https) in the default browser.
                if let url = navigationAction.request.url {
                    NSWorkspace.shared.open(url)
                }
                decisionHandler(.cancel)
            }
        }

        // MARK: - DB injection

        private func injectDatabase(into webView: WKWebView) {
            guard !dbPath.isEmpty else { return }

            guard let dbData = try? Data(contentsOf: URL(fileURLWithPath: dbPath)) else {
                print("[DashboardView] Could not read database at: \(dbPath)")
                return
            }

            // Base64-encode the database so it can be passed as a JS string literal.
            // Base64 uses only [A-Za-z0-9+/=], so no escaping is needed inside '…'.
            let b64 = dbData.base64EncodedString()

            // Wait for initSQL (the dashboard may still be initialising sql.js from
            // the CDN/vendor), then check whether the DB was already loaded by the
            // dashboard's own auto-load IIFE.  If not, inject our copy.
            let js = """
            (async function __swiftInjectDB() {
                // Poll until initSQL is available (sql.js may still be loading).
                for (let i = 0; i < 100; i++) {
                    if (typeof initSQL === 'function') break;
                    await new Promise(r => setTimeout(r, 50));
                }
                if (typeof initSQL !== 'function') {
                    console.error('[Swift] initSQL not found after waiting 5 s');
                    return;
                }
                // If the dashboard's own auto-load already succeeded, bail out.
                if (typeof db !== 'undefined' && db !== null) return;
                // Try to initialise sql.js (works if vendor files are in bundle).
                try {
                    await initSQL();
                } catch (vendorErr) {
                    // Vendor WASM files may be missing from the app bundle.
                    // Fall back to loading sql.js from CDN.
                    console.warn('[Swift] Vendor sql.js init failed, falling back to CDN:', vendorErr);
                    if (typeof SQL === 'undefined' || SQL === null) {
                        if (typeof initSqlJs === 'undefined') {
                            await new Promise((resolve, reject) => {
                                const s = document.createElement('script');
                                s.src = 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.2/sql-wasm.js';
                                s.onload = resolve;
                                s.onerror = () => reject(new Error('CDN load failed'));
                                document.head.appendChild(s);
                            });
                        }
                        SQL = await initSqlJs({
                            locateFile: f => 'https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.10.2/' + f
                        });
                    }
                }
                if (typeof db !== 'undefined' && db !== null) return;
                try {
                    const b64 = '\(b64)';
                    const bin = atob(b64);
                    const bytes = new Uint8Array(bin.length);
                    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
                    await loadDbBuffer(bytes.buffer, 'scouting_troop.db');
                } catch (e) {
                    console.error('[Swift] DB injection failed:', e);
                }
            })();
            """

            webView.evaluateJavaScript(js) { _, error in
                if let error {
                    print("[DashboardView] JS injection error: \(error.localizedDescription)")
                }
            }
        }
    }
}
