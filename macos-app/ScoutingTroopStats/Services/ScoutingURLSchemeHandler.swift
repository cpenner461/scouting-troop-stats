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
            let html = bundleData("dashboard", "html") ?? Self.setupErrorHTML
            return (html, "text/html; charset=utf-8")

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
        // 1. Production path: resource copied into the app bundle (XcodeGen or
        //    manual "Copy Bundle Resources" build phase).
        if let url = Bundle.main.url(forResource: name, withExtension: ext) {
            return try? Data(contentsOf: url)
        }

        // 2. Development fallback: the build setting SCOUTING_SOURCE_ROOT is
        //    written into Info.plist as ScoutingSourceRoot = $(SRCROOT)/..
        //    This lets the scheme handler find repo-root files without copying
        //    them into the bundle.  Guard against unexpanded build-variable
        //    strings that indicate the setting wasn't configured.
        if let root = Bundle.main.object(forInfoDictionaryKey: "ScoutingSourceRoot") as? String,
           !root.isEmpty, !root.hasPrefix("$(") {
            let rootURL = URL(fileURLWithPath: root)
            // Try repo root (for dashboard.html)
            let direct = rootURL.appendingPathComponent("\(name).\(ext)")
            if let data = try? Data(contentsOf: direct) { return data }
            // Try vendor sub-directory (for sql-wasm.js / sql-wasm.wasm)
            let vendor = rootURL.appendingPathComponent("vendor/\(name).\(ext)")
            if let data = try? Data(contentsOf: vendor) { return data }
        }

        return nil
    }

    // HTML page shown when dashboard.html cannot be found in the bundle or
    // via the ScoutingSourceRoot fallback.
    private static let setupErrorHTML: Data = {
        let html = """
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="UTF-8">
          <title>Resource Not Found</title>
          <style>
            body { font-family: -apple-system, sans-serif; padding: 40px; max-width: 600px; margin: auto; }
            h1   { color: #c0392b; }
            code { background: #f0f0f0; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }
            pre  { background: #f0f0f0; padding: 12px; border-radius: 6px; overflow-x: auto; }
          </style>
        </head>
        <body>
          <h1>Dashboard resources not found</h1>
          <p>The app could not locate <code>dashboard.html</code> or the sql.js WASM files.</p>
          <h2>Quick fix</h2>
          <p>In Xcode, add the three files to the <strong>Copy Bundle Resources</strong> build phase:</p>
          <pre>dashboard.html
        vendor/sql-wasm.js
        vendor/sql-wasm.wasm</pre>
          <p>They live in the repository root (one level above <code>macos-app/</code>).</p>
          <h2>Recommended: use XcodeGen</h2>
          <pre>brew install xcodegen
        cd macos-app
        xcodegen generate
        open ScoutingTroopStats.xcodeproj</pre>
          <p>XcodeGen automatically adds the three files to the bundle.</p>
        </body>
        </html>
        """
        return Data(html.utf8)
    }()
}
