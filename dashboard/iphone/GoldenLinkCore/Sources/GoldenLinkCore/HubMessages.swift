import Foundation

// hub ↔ 앱 메시지. dashboard/src/types/dashboard.ts와 hub/schema.py에 맞췄다. 화면에 쓰는 필드만 담고,
// 나머지는 무시한다(디코딩 실패로 메시지를 버리지 않게 거의 전부 Optional).

// MARK: - 앱 -> hub

public struct IdentifyMessage: Encodable {
    public let type = "identify"
    public let role: String  // "ambulance" | "monitor"
    public let id: String
    public init(role: String, id: String) { self.role = role; self.id = id }
}

public struct CallSignalMessage: Encodable {
    public let type = "call_signal"
    public let signal: String  // "call_started" | "call_ended"
    public let timestamp: String
    public let apid: String
    public let caseId: String
    public let hospitalId: String?
    /// hub 스키마가 Literal["phone","tablet"] — 다른 값이면 신호 전체가 거부된다
    public let device = "phone"
    /// 통화 취소(2026-10-05): call_ended와 함께 true면 hub·voice가 이 통화 음성을 처리·전달하지 않는다. nil이면 보내지 않는다
    public let cancelled: Bool?

    public init(signal: String, apid: String, caseId: String, hospitalId: String?, cancelled: Bool? = nil,
                timestamp: String = isoNow()) {
        self.signal = signal; self.apid = apid; self.caseId = caseId; self.hospitalId = hospitalId
        self.cancelled = cancelled; self.timestamp = timestamp
    }
}

/// POST /voice/utterance — hub/schema.py VoiceUtterance
public struct UtteranceMessage: Encodable {
    public let apid: String
    public let caseId: String?
    public let start: Double
    public let end: Double
    public let text: String
    public let source = "ai"
    public init(apid: String, caseId: String?, start: Double, end: Double, text: String) {
        self.apid = apid; self.caseId = caseId; self.start = start; self.end = end; self.text = text
    }
}

// MARK: - hub -> 앱

public struct GPS: Codable, Equatable, Sendable {
    public let lat: Double
    public let lng: Double
}

/// type만 먼저 읽어 갈래를 고른다. 모르는 type은 버린다(hub가 새 메시지를 추가해도 안 깨지게).
public struct InboundEnvelope: Decodable { public let type: String? }

public struct IdentityInfo: Decodable, Equatable {
    public let name: String?
    public let known: Bool
    public let simDispatch: Bool?
    public let gps: GPS?
}

public enum AmbulancePhase: String, Decodable, Sendable {
    case idle, dispatching, on_scene, transporting, at_hospital, rerouting, returning

    public var label: String {
        switch self {
        case .idle: "출동 대기"
        case .dispatching: "현장 출동 중"
        case .on_scene: "현장 도착"
        case .transporting: "병원 이송 중"
        case .at_hospital: "병원 도착"
        case .rerouting: "재선택 대기"
        case .returning: "기지 복귀 중"
        }
    }
}

/// ambulance_phase / ambulance_position
public struct AmbulanceSim: Decodable, Equatable {
    public let apid: String
    public let caseId: String?
    public let phase: AmbulancePhase
    public let gps: GPS?
    public let etaSec: Double?
    public let incident: GPS?
    public let paused: Bool?
    /// 왜 멈췄나(2026-10-05): "manual" 시연 일시정지(조작 잠금) | "call" 이송 중 추가 통화 동안만 이동 멈춤
    public let pauseReason: String?
    /// 이송 중·도착한 병원(이송 확정 병원)
    public let hospitalId: String?
}

public struct BedReliability: Decodable, Equatable {
    /// 지금 이 병상 숫자를 믿어도 될 확률(AI)
    public let authority: Double?
    /// 도착 시점에도 유효할 확률(AI)
    public let rArrive: Double?
}

public struct SceneCandidate: Decodable, Equatable, Identifiable {
    public let hospitalId: String
    public let name: String
    public let distanceKm: Double
    public let roadDistanceKm: Double?
    public let etaMin: Double?
    public let availableBedCount: Int
    public let bedCountUnknown: Bool
    public let bedReliability: BedReliability?
    public let firstCallRecommended: Bool?
    public let emergencyLevel: String?
    public let specialties: [Specialty]?
    public var id: String { hospitalId }

    public struct Specialty: Decodable, Equatable {
        public let department: String
        public let doctorCount: Int
    }
}

public struct SceneCandidates: Decodable, Equatable {
    public let caseId: String
    public let apid: String
    /// 도착 시간순(hub가 정한 순서 그대로 쓴다)
    public let hospitals: [SceneCandidate]
    public let reportedSymptom: String?
}

public struct CallStatus: Decodable, Equatable {
    public let caseId: String
    public let apid: String
    public let hospitalId: String?
    public let hospitalName: String?
    public let device: String?
    public let state: String  // "calling" | "ended"
    public let startedAt: String
    /// 2026-10-05: 같은 사건의 추가 통화인지 · 취소된 통화인지(전달 안 됨)
    public let followup: Bool?
    public let cancelled: Bool?
}

public struct CallTranscriptLine: Decodable, Equatable {
    public let caseId: String?
    public let start: Double
    public let end: Double
    public let text: String
}

/// match_result(또는 type 없음) — 종료 화면의 "후보 병원 N곳에 전달"과, 이송 중 통화할 목적지(확정 병원)에 쓴다
public struct MatchResult: Decodable {
    public let caseId: String
    public let hospitals: [Hospital]
    public struct Hospital: Decodable, Equatable {
        public let hospitalId: String
        public let name: String
        public let status: String  // pending | approved | rejected | confirmed
        public init(hospitalId: String, name: String, status: String) {
            self.hospitalId = hospitalId; self.name = name; self.status = status
        }
    }
}

/// 조작 거부(2026-10-05) — reason "paused"면 시연 일시정지 중
public struct ActionRefused: Decodable {
    public let caseId: String?
    public let reason: String
}

public struct CaseClosed: Decodable { public let caseId: String }
public struct CaseSync: Decodable { public let caseIds: [String] }

public func isoNow(_ date: Date = Date()) -> String {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f.string(from: date)
}
