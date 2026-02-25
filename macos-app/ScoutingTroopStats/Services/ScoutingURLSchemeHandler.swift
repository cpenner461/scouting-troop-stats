import WebKit
import Foundation

/// Handles `scouting://localhost/*` requests so the dashboard can run fully
/// offline inside a WKWebView without a local HTTP server.
///
/// Serves:
///   scouting://localhost/dashboard.html        → bundled dashboard.html
///   scouting://localhost/vendor/sql-wasm.js    → bundled sql-wasm.js
///   scouting://localhost/vendor/sql-wasm.wasm  → bundled sql-wasm.wasm
///   scouting://localhost/scouting_troop.db     → user's database file
final class ScoutingURLSchemeHandler: NSObject, WKURLSchemeHandler {
    private let dbPath: String

    init(dbPath: String) {
        self.dbPath = dbPath
    }

    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard let url = urlSchemeTask.request.url else {
            urlSchemeTask.didFailWithError(URLError(.badURL))
            return
        }

        let (data, mimeType) = resolve(path: url.path)

        guard let bytes = data else {
            urlSchemeTask.didFailWithError(URLError(.fileDoesNotExist))
            return
        }

        var headers: [String: String] = [
            "Content-Type": mimeType,
            "Content-Length": "\(bytes.count)",
            "Access-Control-Allow-Origin": "*"
        ]
        // Serve WASM with correct MIME so browsers don't reject it.
        if mimeType == "application/wasm" {
            headers["Content-Type"] = "application/wasm"
        }

        let response = HTTPURLResponse(
            url: url,
            statusCode: 200,
            httpVersion: "HTTP/1.1",
            headerFields: headers
        )!
        urlSchemeTask.didReceive(response)
        urlSchemeTask.didReceive(bytes)
        urlSchemeTask.didFinish()
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}

    // MARK: - Path resolution

    private func resolve(path: String) -> (Data?, String) {
        switch path {
        case "/dashboard.html":
            return (bundleData("dashboard", "html"), "text/html; charset=utf-8")

        case "/vendor/sql-wasm.js":
            return (bundleData("sql-wasm", "js"), "text/javascript; charset=utf-8")

        case "/vendor/sql-wasm.wasm":
            return (bundleData("sql-wasm", "wasm"), "application/wasm")

        case "/scouting_troop.db":
            let data = try? Data(contentsOf: URL(fileURLWithPath: dbPath))
            return (data, "application/octet-stream")

        default:
            return (nil, "application/octet-stream")
        }
    }

    private func bundleData(_ name: String, _ ext: String) -> Data? {
        guard let url = Bundle.main.url(forResource: name, withExtension: ext) else {
            return nil
        }
        return try? Data(contentsOf: url)
    }
}
