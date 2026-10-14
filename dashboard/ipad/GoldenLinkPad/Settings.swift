import Foundation

/// 앱 설정(설정 화면에서 바꾼다). 기기에만 저장된다. 아이폰 앱(../iphone/Settings.swift)과 같은 규칙.
enum Settings {
    static let defaultHub = "https://app.rookie-goldenlink.xyz"

    /// hub 주소. 공개 모드 `https://app.rookie-goldenlink.xyz`, 로컬 모드 `http://<맥 IP>:5001`
    static var hubBase: String {
        get { UserDefaults.standard.string(forKey: "hubBase") ?? defaultHub }
        set { UserDefaults.standard.set(newValue, forKey: "hubBase") }
    }

    /// spider 서버 주소. 비우면 자동 — 공개 도메인이면 hub와 같은 호스트(터널이 /spider/를 spider로 보낸다),
    /// 로컬 모드(포트 5001)면 같은 IP의 2700번
    static var spiderBase: String {
        get { UserDefaults.standard.string(forKey: "spiderBase") ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: "spiderBase") }
    }

    private static func trimmed(_ s: String) -> String {
        s.trimmingCharacters(in: .whitespaces).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    static var httpBase: URL? { URL(string: trimmed(hubBase)) }

    /// http(s)://host -> ws(s)://host/ws/dashboard
    static var wsURL: URL? {
        guard let base = httpBase, var c = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return nil }
        c.scheme = c.scheme == "https" ? "wss" : "ws"
        c.path = "/ws/dashboard"
        return c.url
    }

    static func autoSpiderBase(for hub: String) -> String {
        guard let u = URL(string: trimmed(hub)), var c = URLComponents(url: u, resolvingAgainstBaseURL: false) else { return trimmed(hub) }
        if c.port == 5001 { c.port = 2700 }   // 로컬 모드: hub 5001 → spider 2700
        return c.url?.absoluteString ?? trimmed(hub)
    }

    static var effectiveSpiderBase: String {
        let s = trimmed(spiderBase)
        return s.isEmpty ? autoSpiderBase(for: hubBase) : s
    }

    /// 거미줄 3D 실시간 화면(패널 없이 지도만)
    static var spiderURL: URL? { URL(string: effectiveSpiderBase + "/spider/?mode=live&embed=1") }
    static var spiderHealthURL: URL? { URL(string: effectiveSpiderBase + "/spider/api/health") }

    /// 정보 생존 모델 라이브 채점 보드 — hub가 info 수신구(5003)의 결과를 그대로 중계한다
    static var liveBoardURL: URL? { httpBase.map { $0.appendingPathComponent("verification/live") } }
    static var identityURL: URL? {
        guard let base = httpBase, var c = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return nil }
        c.path = "/identity"; c.queryItems = [URLQueryItem(name: "role", value: "hospital"), URLQueryItem(name: "id", value: "_")]
        return c.url
    }
}
