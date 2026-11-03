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
    /// 도로 ETA를 시연 화면 시간으로 환산할 배속(hub의 경로 이동과 같은 값).
    public let speedup: Double?
    public let path: [[Double]]?
    /// 구급대 센터(출동 출발지). 현재 이동 위치와 별도로 보존한다.
    public let base: GPS?
    public let incident: GPS?
    public let paused: Bool?
    /// 왜 멈췄나(2026-10-05): "manual" 시연 일시정지(조작 잠금) | "call" 이송 중 추가 통화 동안만 이동 멈춤
    public let pauseReason: String?
    /// 이송 중·도착한 병원(이송 확정 병원)
    public let hospitalId: String?
}

/// 병상 숫자가 아직 유효할 확률(infosurv, AI). 곡선 파라미터(predictedSurvivalSec·bornAt·sigma)가 오면
/// BedLive.of()가 초 단위로 감쇠시킨다. 없으면 authority·rArrive 그대로(정지값) — 아이패드 BedReliabilityMatch와 같다
public struct BedReliability: Decodable, Equatable {
    /// 지금 이 병상 숫자를 믿어도 될 확률(AI)
    public let authority: Double?
    /// 도착 시점에도 유효할 확률(AI)
    public let rArrive: Double?
    public let horizonSec: Double?
    public let predictedSurvivalSec: Double?
    public let bornAt: String?
    public let sigma: Double?
    public let confirmedAgeSec: Double?

    public init(authority: Double?, rArrive: Double?, horizonSec: Double? = nil, predictedSurvivalSec: Double? = nil,
                bornAt: String? = nil, sigma: Double? = nil, confirmedAgeSec: Double? = nil) {
        self.authority = authority; self.rArrive = rArrive; self.horizonSec = horizonSec
        self.predictedSurvivalSec = predictedSurvivalSec; self.bornAt = bornAt; self.sigma = sigma; self.confirmedAgeSec = confirmedAgeSec
    }
}

/// map_overview의 병원 한 곳 — 현장 후보(scene_candidates)에는 좌표가 없어, 지도 핀은 이 목록의 좌표를 hospitalId로 찾아 쓴다
public struct MapHospitalPos: Decodable {
    public let hospitalId: String
    public let gps: GPS
}

public struct MapOverview: Decodable {
    public let hospitals: [MapHospitalPos]
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
    public let supportedKtas: [Int]?
    public let firstCallReason: String?
    public let emergencyLevel: String?
    public let specialties: [Specialty]?
    public var id: String { hospitalId }

    public struct Specialty: Decodable, Equatable {
        public let department: String
        public let doctorCount: Int
    }
}

public struct SceneCandidates: Decodable, Equatable {
    public let zoneActive: [Int]?
    public let caseId: String
    public let apid: String
    /// 도착 시간순(hub가 정한 순서 그대로 쓴다)
    public let hospitals: [SceneCandidate]
    public let callAttempts: [String]?
    public let firstCallExhausted: Bool?
    public let reportedSymptom: String?
}

public struct CallStatus: Decodable, Equatable {
    public let caseId: String
    public let apid: String
    public let hospitalId: String?
    public let hospitalName: String?
    public let device: String?
    public let requestId: String?
    public let state: String  // ringing / calling / ended / no_answer / cancelled
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

public struct SpecialtyMatch: Decodable, Equatable {
    public let department: String?
    public let score: Double?
    public let basis: String?  // exact | embedding | none
    public let doctorCount: Int?
}

/// match_result(또는 type 없음) — 종료 화면의 "후보 병원 N곳에 전달"과, 이송 중 통화할 목적지(확정 병원)·환자 정보·이송 탭에 쓴다
public struct MatchResult: Decodable {
    public let caseId: String
    public let hospitals: [Hospital]
    /// hub 규칙 기반 활성 존. 예전 저장 기록에는 없을 수 있다.
    public let zoneActive: [Int]?
    public let patientInfo: PatientInfo?
    public let apid: String?
    public let paused: Bool?

    /// 매칭 결과의 병원 하나 — 아이패드 HospitalMatch 중 폰 화면(이송 탭)이 쓰는 칸
    public struct Hospital: Decodable, Equatable {
        public let hospitalId: String
        public let name: String
        public let status: String  // pending | approved | rejected | confirmed
        public let distanceKm: Double
        public let roadDistanceKm: Double?
        public let etaMin: Double?
        public let travelMin: Double?
        public let specialtyMatch: SpecialtyMatch?
        public let availableBedCount: Int?
        public let bedCountUnknown: Bool?
        public let bedDataStale: Bool?
        public let erBedCapacity: Int?
        public let erOccupancyPct: Int?
        public let bedReliability: BedReliability?
        public let rejectReason: String?
        public let unavailableReason: String?
        public let demoteReasons: [String]?
        public let excluded: Bool?
        public let emergencyLevel: String?
        public let inFlightCount: Int?
        public let loadPenaltyMin: Double?

        public init(hospitalId: String, name: String, status: String, distanceKm: Double = 0, roadDistanceKm: Double? = nil,
                    etaMin: Double? = nil, travelMin: Double? = nil, specialtyMatch: SpecialtyMatch? = nil,
                    availableBedCount: Int? = nil, bedCountUnknown: Bool? = nil, bedDataStale: Bool? = nil,
                    erBedCapacity: Int? = nil, erOccupancyPct: Int? = nil, bedReliability: BedReliability? = nil,
                    rejectReason: String? = nil, unavailableReason: String? = nil, demoteReasons: [String]? = nil,
                    excluded: Bool? = nil, emergencyLevel: String? = nil, inFlightCount: Int? = nil, loadPenaltyMin: Double? = nil) {
            self.hospitalId = hospitalId; self.name = name; self.status = status; self.distanceKm = distanceKm
            self.roadDistanceKm = roadDistanceKm; self.etaMin = etaMin; self.travelMin = travelMin
            self.specialtyMatch = specialtyMatch; self.availableBedCount = availableBedCount; self.bedCountUnknown = bedCountUnknown
            self.bedDataStale = bedDataStale; self.erBedCapacity = erBedCapacity; self.erOccupancyPct = erOccupancyPct
            self.bedReliability = bedReliability; self.rejectReason = rejectReason; self.unavailableReason = unavailableReason
            self.demoteReasons = demoteReasons; self.excluded = excluded; self.emergencyLevel = emergencyLevel
            self.inFlightCount = inFlightCount; self.loadPenaltyMin = loadPenaltyMin
        }
    }
}

/// 구급대원 이송 승인 — 웹 handleApprove와 같은 형식. 병원이 승인한 병원에만 보낸다
public struct ApprovalAction: Encodable {
    public let caseId: String
    public let action = "final_approval"
    public let hospital_id: String
    public let actor = "paramedic"
    public let timestamp: String
    public init(caseId: String, hospitalId: String, timestamp: String) {
        self.caseId = caseId; self.hospital_id = hospitalId; self.timestamp = timestamp
    }
}

/// 통화 요약 확인·수정 전송 — hub patient_override. **보낸 칸만** 바뀌므로 바뀐 칸만 채운다(nil은 JSON에서 빠진다).
/// 칸을 하나도 안 채우면 "수정 없이 확인"이고, 순위 칸(예상 병명·KTAS·필요 진료과)이 바뀌면 hub가 다시 매칭한다
public struct PatientOverrideMessage: Encodable {
    public let type = "patient_override"
    public let caseId: String
    public let timestamp: String
    public let expectedDiagnosis: String?
    public let injuryStatus: [String]?
    public let ktasLevel: Int?
    public let requiredDepartment: String?
    public let chiefComplaint: String?
    public init(caseId: String, timestamp: String, expectedDiagnosis: String?, injuryStatus: [String]?,
                ktasLevel: Int?, requiredDepartment: String?, chiefComplaint: String?) {
        self.caseId = caseId; self.timestamp = timestamp; self.expectedDiagnosis = expectedDiagnosis
        self.injuryStatus = injuryStatus; self.ktasLevel = ktasLevel; self.requiredDepartment = requiredDepartment
        self.chiefComplaint = chiefComplaint
    }
}

/// 추가 정보 전송 — patient_override의 extraNote 칸만 쓴다(요약 칸은 안 보내므로 "확인 도장"도 안 찍힌다)
public struct ExtraNoteMessage: Encodable {
    public let type = "patient_override"
    public let caseId: String
    public let extraNote: String
    public let timestamp: String
    public init(caseId: String, extraNote: String, timestamp: String) {
        self.caseId = caseId; self.extraNote = extraNote; self.timestamp = timestamp
    }
}

/// 조작 거부(2026-10-05) — reason "paused"면 시연 일시정지 중
public struct ActionRefused: Decodable {
    public let caseId: String?
    public let reason: String
}

/// scene_input_mode(2026-10-06) — 시연 콘솔 통화 방식. "template"(정해진 상황 선택)이면 그 단계의 통화를 못 한다(hub도 거부)
public struct SceneInputMode: Decodable {
    public let caseId: String
    public let mode: String  // "voice" | "template"
    /// "scene"(② 현장 확인, 없으면 이것) | "transport"(④ 이송 중 — [목적지 병원과 통화])
    public let stage: String?
}

public struct CaseClosed: Decodable { public let caseId: String }
public struct CaseSync: Decodable { public let caseIds: [String] }

public func isoNow(_ date: Date = Date()) -> String {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
    return f.string(from: date)
}
