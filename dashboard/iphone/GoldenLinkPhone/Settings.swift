import Foundation

/// 앱 설정(설정 화면에서 바꾼다). 기기에만 저장된다.
enum Settings {
    /// hub 주소. 로컬 모드 `http://<맥 IP>:5001`, 공개 모드 `https://app.rookie-goldenlink.xyz`
    /// ⚠ 공개 도메인은 /voice/* 를 막아 두어(인증 없음) 온디바이스 모드의 자막·요약 전송이 404가 난다 — README "네트워크" 참고
    static var hubBase: String {
        get { UserDefaults.standard.string(forKey: "hubBase") ?? "http://192.168.0.10:5001" }
        set { UserDefaults.standard.set(newValue, forKey: "hubBase") }
    }

    /// 구급차 ID(SEL0001~) 또는 "auto"(출동하는 구급차를 자동으로 따라감 — 웹 P-AUTO)
    static var apid: String {
        get { UserDefaults.standard.string(forKey: "apid") ?? "auto" }
        set { UserDefaults.standard.set(newValue, forKey: "apid") }
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
