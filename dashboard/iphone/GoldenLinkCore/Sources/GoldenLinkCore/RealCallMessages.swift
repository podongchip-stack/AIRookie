import Foundation

// 실제 양방향 통화(WebRTC, 2026-11-04) — hub/call_sessions.py와 같은 모양(안드로이드 RealCallMessages.kt와 같다).
// 식별자: caseId(사건) / callId(통화 시도 하나, 재전화 시 새로 만든다) / negotiationRevision(연결 협상 세대).
// 구급대 앱(아이폰)이 걸고(call_invite → rtc_offer), 병원 앱(안드로이드 병원 모드)이 받는다. 음성은 hub를 거치지 않는다.

// MARK: - 앱 -> hub

public struct CallInviteMessage: Encodable {
    public let type = "call_invite"
    public let callId: String
    public let caseId: String
    public let hospitalId: String
    public let deviceId: String?
    public let timestamp: String
    public init(callId: String, caseId: String, hospitalId: String, deviceId: String? = nil, timestamp: String = isoNow()) {
        self.callId = callId; self.caseId = caseId; self.hospitalId = hospitalId; self.deviceId = deviceId; self.timestamp = timestamp
    }
}

public struct CallHangupMessage: Encodable {
    public let type = "call_hangup"
    public let callId: String
    public init(callId: String) { self.callId = callId }
}

/// type: "rtc_offer"(구급대 → 병원) | "rtc_answer"(병원 → 구급대)
public struct RtcSdpMessage: Encodable {
    public let type: String
    public let callId: String
    public let sdp: String
    public let negotiationRevision: Int
    public init(type: String, callId: String, sdp: String, negotiationRevision: Int = 1) {
        self.type = type; self.callId = callId; self.sdp = sdp; self.negotiationRevision = negotiationRevision
    }
}

/// ICE 후보 {sdpMid, sdpMLineIndex, candidate} — hub는 내용을 해석하지 않고 상대에게 그대로 중계한다
public struct IceCandidatePayload: Codable, Equatable, Sendable {
    public let sdpMid: String?
    public let sdpMLineIndex: Int
    public let candidate: String
    public init(sdpMid: String?, sdpMLineIndex: Int, candidate: String) {
        self.sdpMid = sdpMid; self.sdpMLineIndex = sdpMLineIndex; self.candidate = candidate
    }
}

public struct RtcIceMessage: Encodable {
    public let type = "rtc_ice"
    public let callId: String
    public let candidate: IceCandidatePayload
    public let negotiationRevision: Int
    public init(callId: String, candidate: IceCandidatePayload, negotiationRevision: Int = 1) {
        self.callId = callId; self.candidate = candidate; self.negotiationRevision = negotiationRevision
    }
}

/// 이 기기의 WebRTC 연결·오디오 경로가 준비됐다 — 양쪽이 보고해야 hub가 통화 중(active)으로 바꾼다
public struct MediaReadyMessage: Encodable {
    public let type = "media_ready"
    public let callId: String
    public init(callId: String) { self.callId = callId }
}

// MARK: - hub -> 앱

public struct IceServerConfig: Decodable, Equatable, Sendable {
    public let urls: [String]
    public let username: String?
    public let credential: String?
}

/// state: ringing | connecting | active | ended. 끝났을 땐 reason(이 기기 입장의 사유)이 있다
public struct CallState: Decodable {
    public let callId: String
    public let caseId: String?
    public let state: String
    public let reason: String?
    public let detail: String?
    public let iceServers: [IceServerConfig]?
}

public struct RtcSdpIn: Decodable {
    public let callId: String
    public let sdp: String
    public let negotiationRevision: Int?
}

public struct RtcIceIn: Decodable {
    public let callId: String
    public let candidate: IceCandidatePayload
    public let negotiationRevision: Int?
}

/// hub가 요청을 받아들이지 못했다(늦은 메시지 등) — 앱이 통화 화면을 닫는다
public struct CallError: Decodable {
    public let callId: String
    public let op: String?
    public let reason: String?
}

/// 실제 통화가 끝난 이유를 화면 문구로 — hub의 종료 사유(call_sessions.py)와 같은 이름. 이 기기 입장의 사유가 온다
public enum CallLabels {
    public static func endText(_ reason: String?, detail: String? = nil) -> String {
        switch reason {
        case "rejected": "병원이 통화를 거절했습니다"
        case "busy": "병원이 다른 통화 중입니다"
        case "unavailable": "병원 전화 앱이 연결돼 있지 않습니다"
        case "no_answer": "병원이 응답하지 않았습니다"
        case "connection_failed": "통화 연결에 실패했습니다"
        case "caller_cancelled": "발신이 취소됐습니다"
        case "local_hangup": "통화를 종료했습니다"
        case "remote_hangup": "상대가 통화를 종료했습니다"
        case "network_timeout": "네트워크가 끊겨 통화가 종료됐습니다"
        case "answered_elsewhere": "다른 기기에서 받은 전화입니다"
        case "case_closed": "사건이 종료돼 통화가 끝났습니다"
        case "refused":
            switch detail {
            case "paused": "현재 시연 일시정지 중입니다."
            case "phase": "지금은 전화할 수 없는 단계입니다"
            case "case_busy": "이 사건은 이미 통화 중입니다"
            case "template_mode": "콘솔이 정해진 상황 선택 중이라 전화할 수 없습니다."
            case "unknown_hospital": "알 수 없는 병원입니다"
            case "not_owner": "이 사건의 구급대가 아니라 전화할 수 없습니다"
            default: "통화를 시작할 수 없습니다"
            }
        default: "통화가 종료됐습니다"
        }
    }
}
