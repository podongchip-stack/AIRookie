import Foundation

/// 앱 설정(설정 화면에서 바꾼다). 기기에만 저장된다. 아이폰 앱(../iphone/Settings.swift)과 같은 규칙.
enum Settings {
    static let defaultHub = "https://app.rookie-goldenlink.xyz"

    /// hub 주소. 공개 모드 `https://app.rookie-goldenlink.xyz`, 로컬 모드 `http://<맥 IP>:5001`
    static var hubBase: String {
        get { UserDefaults.standard.string(forKey: "hubBase") ?? defaultHub }
        set { UserDefaults.standard.set(newValue, forKey: "hubBase") }
    }

    static var accessCode: String {
        get { UserDefaults.standard.string(forKey: "accessCode") ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: "accessCode") }
    }

    /// 네이티브 아이패드는 A-<구급대 ID> 코드로만 입장한다.
    static func ambulanceID(from code: String) -> String? {
        let value = code.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
        guard value.hasPrefix("A-") else { return nil }
        let id = String(value.dropFirst(2))
        guard !id.isEmpty, id != "AUTO", id.allSatisfy({ $0.isASCII && ($0.isLetter || $0.isNumber) }) else { return nil }
        return id
    }

    /// 이 아이패드가 실린 구급차 ID(SEL0001~) 또는 "auto" — 출동하는 구급차를 자동으로 따라간다(웹 /ambulance?id=auto와 같음)
    static var apid: String {
        get { UserDefaults.standard.string(forKey: "apid") ?? "auto" }
        set { UserDefaults.standard.set(newValue, forKey: "apid") }
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

    /// 거미줄 3D 실시간 화면(패널 없이 지도만). apid를 주면 그 구급차의 사건만 그린다.
    /// screen: 지도 보기(확대·위치)를 화면별로 따로 저장하는 키
    static func spiderURL(apid: String?, screen: String) -> URL? {
        var s = effectiveSpiderBase + "/spider/?mode=live&embed=1&screen=" + screen
        if let apid, !apid.isEmpty { s += "&apid=" + (apid.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? apid) }
        return URL(string: s)
    }
    static var spiderHealthURL: URL? { URL(string: effectiveSpiderBase + "/spider/api/health") }

    /// 정보 생존 모델 라이브 채점 보드 — hub가 info 수신구(5003)의 결과를 그대로 중계한다
    static var liveBoardURL: URL? { httpBase.map { $0.appendingPathComponent("verification/live") } }
    /// [배후역량] — hub GET /hospital-backup?id=<hpid>(웹 대시보드 [배후역량] 버튼과 같은 데이터)
    static func backupURL(_ hospitalId: String) -> URL? {
        guard let base = httpBase, var c = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return nil }
        c.path = "/hospital-backup"; c.queryItems = [URLQueryItem(name: "id", value: hospitalId)]
        return c.url
    }
    /// 좌표 → 주소(2026-10-27) — 인계확인서 "출발지 주소". hub가 카카오를 대신 부른다(키를 앱에 두지 않는다)
    static func reverseGeocodeURL(_ p: GpsPoint) -> URL? {
        guard let base = httpBase, var c = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return nil }
        c.path = "/geocode/reverse"
        c.queryItems = [URLQueryItem(name: "lat", value: String(p.lat)), URLQueryItem(name: "lng", value: String(p.lng))]
        return c.url
    }
    static func identityURL(role: String, id: String) -> URL? {
        guard let base = httpBase, var c = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return nil }
        c.path = "/identity"; c.queryItems = [URLQueryItem(name: "role", value: role), URLQueryItem(name: "id", value: id)]
        return c.url
    }
}
