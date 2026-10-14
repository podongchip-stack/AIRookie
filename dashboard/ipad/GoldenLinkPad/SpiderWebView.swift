import SwiftUI
import WebKit

extension Notification.Name {
    static let spiderReload = Notification.Name("spiderReload")
}

/// 가운데 패널 — spider 서버의 거미줄 3D 실시간 화면(/spider/?mode=live&embed=1). 패널은 숨기고 지도만 받는다.
/// 계산·데이터는 전부 서버 쪽이라 앱은 주소만 가리킨다(spider가 바뀌어도 앱을 다시 빌드하지 않는다).
struct SpiderWebView: UIViewRepresentable {
    var url: URL?

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.defaultWebpagePreferences.allowsContentJavaScript = true
        let web = WKWebView(frame: .zero, configuration: config)
        web.isOpaque = false
        web.backgroundColor = UIColor(Theme.bg)
        web.scrollView.backgroundColor = UIColor(Theme.bg)
        web.scrollView.bounces = false
        web.navigationDelegate = context.coordinator
        context.coordinator.web = web
        context.coordinator.observer = NotificationCenter.default.addObserver(forName: .spiderReload, object: nil, queue: .main) { _ in
            context.coordinator.load(url, force: true)
        }
        context.coordinator.load(url, force: true)
        return web
    }

    func updateUIView(_ web: WKWebView, context: Context) {
        context.coordinator.load(url, force: false)
    }

    static func dismantleUIView(_ web: WKWebView, coordinator: Coordinator) {
        if let o = coordinator.observer { NotificationCenter.default.removeObserver(o) }
    }

    final class Coordinator: NSObject, WKNavigationDelegate {
        weak var web: WKWebView?
        var observer: NSObjectProtocol?
        private var loaded: URL?

        func load(_ url: URL?, force: Bool) {
            guard let url, let web else { return }
            if !force, loaded == url { return }
            loaded = url
            var req = URLRequest(url: url)
            req.cachePolicy = .reloadIgnoringLocalCacheData   // spider 화면이 자주 바뀐다 — 항상 새 버전
            web.load(req)
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            showError(webView, error.localizedDescription)
        }
        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            showError(webView, error.localizedDescription)
        }
        private func showError(_ web: WKWebView, _ msg: String) {
            let html = """
            <html><body style="margin:0;background:#0a1024;color:#f2f1ec;font-family:-apple-system;display:flex;align-items:center;justify-content:center;height:100vh">
            <div style="text-align:center;max-width:520px;padding:24px"><div style="font-size:18px;font-weight:600;margin-bottom:8px">거미줄 3D 화면을 열 수 없습니다</div>
            <div style="color:#b9b8ae;font-size:14px;line-height:1.5">\(msg)<br>설정에서 spider 주소를 확인하고 [새로고침]을 누르세요.<br>(start-all.sh가 spider를 띄우면 hub와 같은 도메인의 /spider/ 로 열립니다)</div></div></body></html>
            """
            web.loadHTMLString(html, baseURL: nil)
            loaded = nil
        }
    }
}
