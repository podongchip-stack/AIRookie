import Foundation
import GoldenLinkCore

/// 앱 설정(설정 화면에서 바꾼다). 기기에만 저장된다.
enum Settings {
    /// hub 주소. 로컬 모드 `http://<맥 IP>:5001`, 공개 모드 `https://app.rookie-goldenlink.xyz`(기본값 — 안드로이드와 동일)
    /// 공개 도메인도 된다 — 온디바이스 요약은 WebSocket(/ws/dashboard)으로 보낸다(2026-10-05, 예전 /voice/* HTTP는 터널이 막아 404)
    static var hubBase: String {
        get { UserDefaults.standard.string(forKey: "hubBase") ?? "https://app.rookie-goldenlink.xyz" }
        set { UserDefaults.standard.set(newValue, forKey: "hubBase") }
    }

    static var kakaoNativeAppKey: String {
        get {
            let local = (UserDefaults.standard.string(forKey: "kakaoNativeAppKey") ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            let value = local.isEmpty ? (Bundle.main.object(forInfoDictionaryKey: "KAKAO_NATIVE_APP_KEY") as? String ?? "") : local
            let key = value.trimmingCharacters(in: .whitespacesAndNewlines)
            return key.contains("$(") || key == "YOUR_NATIVE_APP_KEY" ? "" : key
        }
        set { UserDefaults.standard.set(newValue.trimmingCharacters(in: .whitespacesAndNewlines), forKey: "kakaoNativeAppKey") }
    }

    static var accessCode: String {
        get { UserDefaults.standard.string(forKey: "accessCode") ?? "" }
        set { UserDefaults.standard.set(newValue, forKey: "accessCode") }
    }

    /// 아이폰/아이패드 접근 코드는 같은 구급대 ID로 연결한다.
    static func ambulanceID(from code: String) -> String? {
        guard let access = AccessCode(code), access.role == "ambulance" else { return nil }
        return access.id
    }

    static var hospitalID: String? {
        guard let access = AccessCode(accessCode), access.role == "hospital" else { return nil }
        return access.id
    }

    /// 소속 구급차 ID(SEL0001~) — 첫 실행의 접근 코드 입력으로 정한다. 비어 있으면 아직 코드를 입력하지 않은 것
    /// (예전 버전의 "auto" 설정은 비운 것으로 본다 — 자동 전환은 없앴다)
    static var apid: String {
        get {
            let value = UserDefaults.standard.string(forKey: "apid") ?? ""
            return value.lowercased() == "auto" ? "" : value
        }
        set { UserDefaults.standard.set(newValue, forKey: "apid") }
    }

    /// true: 병원 선택 → [전화]를 실제 WebRTC 통화로 건다(플랫폼과 무관하게 H-코드 병원 앱이 받는다).
    /// 실제 통화 중에는 STT·요약이 연결돼 있지 않다(다음 단계, 2026-11-04)
    static var realCall: Bool {
        get { UserDefaults.standard.object(forKey: "realCall") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "realCall") }
    }

    /// 이 설치본의 기기 식별자(진단용, 인증이 아니다) — 처음 쓸 때 만들어 보관한다
    static var deviceID: String {
        if let value = UserDefaults.standard.string(forKey: "deviceID") { return value }
        let value = UUID().uuidString
        UserDefaults.standard.set(value, forKey: "deviceID")
        return value
    }

    /// true: 기기 안에서 STT·MF_BERT(온디바이스). false: 웹과 같이 음성을 hub로 보내 중앙 voice가 처리
    static var onDevice: Bool {
        get { UserDefaults.standard.object(forKey: "onDevice") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "onDevice") }
    }

    /// 무음 기준(VOICE_SILENCE_RMS). 휴대폰 마이크는 PC와 음량 특성이 달라 실측해서 맞춘다
    static var silenceRMS: Float {
        get { UserDefaults.standard.object(forKey: "silenceRMS") as? Float ?? 0.01 }
        set { UserDefaults.standard.set(newValue, forKey: "silenceRMS") }
    }

    /// 발화 끝 판정 무음 길이(VOICE_UTTERANCE_HOLD_SEC)
    static var holdSec: Double {
        get { UserDefaults.standard.object(forKey: "holdSec") as? Double ?? 0.4 }
        set { UserDefaults.standard.set(newValue, forKey: "holdSec") }
    }

    static var httpBase: URL? { URL(string: hubBase.trimmingCharacters(in: .whitespaces).trimmingCharacters(in: CharacterSet(charactersIn: "/"))) }

    /// http(s)://host -> ws(s)://host/ws/dashboard
    static var wsURL: URL? {
        guard let base = httpBase, var c = URLComponents(url: base, resolvingAgainstBaseURL: false) else { return nil }
        c.scheme = c.scheme == "https" ? "wss" : "ws"
        c.path = "/ws/dashboard"
        return c.url
    }
}
