import SwiftUI
import WebKit

extension Notification.Name {
    static let spiderReload = Notification.Name("spiderReload")
}

/// 오른쪽 지도 — spider 서버의 거미줄 3D 실시간 화면(/spider/?mode=live&embed=1&apid=…). 패널은 숨기고 지도만 받는다.
/// 계산·데이터는 전부 서버 쪽이라 앱은 주소만 가리킨다(spider가 바뀌어도 앱을 다시 빌드하지 않는다).
///
/// 두 손가락 확대·축소가 튀던 문제(2026-10-14): 손가락 벌리기 한 번에 WKWebView의 페이지 확대(스크롤 뷰 줌)와 지도(deck.gl)
/// 확대가 **동시에** 걸리고, deck.gl 관성까지 더해져 손을 떼도 계속 확대·축소됐다. 그래서 웹뷰의 페이지 확대·스크롤을 끄고
/// (지도만 제스처를 받게) 페이지 쪽에서도 확대를 막고 관성을 껐다(spider/web/app.js의 embed 처리).
struct SpiderWebView: UIViewRepresentable {
    var url: URL?

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.allowsInlineMediaPlayback = true
        config.defaultWebpagePreferences.allowsContentJavaScript = true
        // 접근성 설정의 "확대 허용"이 페이지 viewport의 user-scalable=no를 무시하지 않게
        config.ignoresViewportScaleLimits = false
        let web = WKWebView(frame: .zero, configuration: config)
        web.isOpaque = false
        web.backgroundColor = UIColor(red: 0.04, green: 0.06, blue: 0.14, alpha: 1)
        let sv = web.scrollView
        sv.backgroundColor = web.backgroundColor
        sv.bounces = false
        sv.isScrollEnabled = false              // 페이지 끌림 없음 — 지도만 움직인다
        sv.minimumZoomScale = 1
        sv.maximumZoomScale = 1
        sv.bouncesZoom = false
        sv.pinchGestureRecognizer?.isEnabled = false   // 페이지 확대 끔 — 핀치는 지도(deck.gl)만 받는다
        sv.contentInsetAdjustmentBehavior = .never
        sv.delegate = context.coordinator
        web.allowsBackForwardNavigationGestures = false
        web.allowsLinkPreview = false
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

    final class Coordinator: NSObject, WKNavigationDelegate, UIScrollViewDelegate {
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

        // 페이지 확대 대상 없음 — 혹시 핀치가 스크롤 뷰로 와도 확대되지 않는다
        func viewForZooming(in scrollView: UIScrollView) -> UIView? { nil }
        func scrollViewDidZoom(_ scrollView: UIScrollView) {
            if scrollView.zoomScale != 1 { scrollView.setZoomScale(1, animated: false) }
        }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            webView.scrollView.setZoomScale(1, animated: false)
            webView.scrollView.pinchGestureRecognizer?.isEnabled = false
        }
        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            showError(webView, error.localizedDescription)
        }
        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            showError(webView, error.localizedDescription)
        }
        private func showError(_ web: WKWebView, _ msg: String) {
            let html = """
            <html><head><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no"></head>
            <body style="margin:0;background:#F4F6FA;color:#1B2430;font-family:-apple-system;display:flex;align-items:center;justify-content:center;height:100vh">
            <div style="text-align:center;max-width:520px;padding:24px"><div style="font-size:18px;font-weight:700;margin-bottom:8px;color:#14213D">거미줄 지도를 열 수 없습니다</div>
            <div style="color:#5A6676;font-size:14px;line-height:1.5">\(msg)<br>설정에서 hub·spider 주소를 확인하고 새로고침을 누르세요.<br>(start-all.sh가 spider를 띄우면 hub와 같은 도메인의 /spider/ 로 열립니다)</div></div></body></html>
            """
            web.loadHTMLString(html, baseURL: nil)
            loaded = nil
        }
    }
}
