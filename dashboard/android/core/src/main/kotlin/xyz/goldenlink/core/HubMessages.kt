package xyz.goldenlink.core

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import java.time.Instant

// hub ↔ 앱 메시지. dashboard/src/types/dashboard.ts · hub/schema.py에 맞췄다(아이폰 HubMessages.swift와 같은 범위).
// 화면에 쓰는 필드만 담고 나머지는 무시한다 — 디코딩 실패로 메시지를 버리지 않게 거의 전부 기본값이 있다.

val hubJson = Json { ignoreUnknownKeys = true; explicitNulls = false; encodeDefaults = true; coerceInputValues = true }

// ── 앱 -> hub ──

@Serializable
data class IdentifyMessage(
    val role: String,
    val id: String,
    /** 실제 통화(WebRTC) 수신이 가능한 병원 앱이면 true(2026-11-04) — hub가 이 기기에만 수신 전화를 울린다. null이면 보내지 않는다 */
    val callCapable: Boolean? = null,
    val type: String = "identify",
)

@Serializable
data class CallSignalMessage(
    val signal: String,  // "call_started" | "call_ended"
    val apid: String,
    val caseId: String,
    val hospitalId: String? = null,
    /** 통화 취소(2026-10-05): call_ended와 함께 true면 hub·voice가 이 통화를 처리·전달하지 않는다. null이면 보내지 않는다 */
    val cancelled: Boolean? = null,
    val timestamp: String = isoNow(),
    /** hub 스키마가 Literal["phone","tablet"] — 다른 값이면 신호 전체가 거부된다 */
    val device: String = "phone",
    /** 첫 통화 판단 대기(2026-11-04): call_ended와 함께 true면 hub가 요약을 병원에 보내지 않고 붙잡아 두었다가 [CallDecisionMessage]로 처리한다. null이면 보내지 않는다 */
    val awaitDecision: Boolean? = null,
    val type: String = "call_signal",
)

/** 첫 통화를 마친 구급대원의 판단(2026-11-04) — decision: "confirm"(통화 병원으로 이송 확정, 요약은 그 병원에만) | "reject"(통화 병원은 불가, 요약을 존 전체에) | "cancel"(판단 없이 닫기) */
@Serializable
data class CallDecisionMessage(
    val caseId: String,
    val decision: String,
    val timestamp: String = isoNow(),
    val type: String = "call_decision",
)

/** AI 통화 결과(수용·거절)로 hub가 첫 통화 판단을 대신 골랐다(2026-11-04) — decision: "confirm" | "reject" */
@Serializable
data class CallDecisionAuto(
    val caseId: String,
    val decision: String,
    val callOutcome: String = "",
    val hospitalId: String? = null,
    val hospitalName: String? = null,
)

/** 전화 연결 요청(2026-10-05 hub 중재) — request는 병원 쪽(관제)이 받아 응답할 때까지 "연결 중", 응답하면 hub가 call_started를 중계한다.
 *  operation: "request" | "cancel" | "no_answer" */
@Serializable
data class CallConnectionMessage(
    val operation: String,
    val caseId: String,
    val hospitalId: String,
    val requestId: String,
    val timestamp: String = isoNow(),
    val type: String = "call_connection",
)

/** 첫 통화 추천을 다시 요청한다 — hub가 후보를 추천순으로 다시 보낸다(scene_candidates). noAnswerHospitalId는 미응답 이력 */
@Serializable
data class FirstCallRequest(
    val caseId: String,
    val noAnswerHospitalId: String? = null,
    val type: String = "first_call_request",
)

// ── hub -> 앱 ──

@Serializable
data class GPS(val lat: Double, val lng: Double)

/** map_overview의 병원 한 곳 — 현장 후보(scene_candidates)에는 좌표가 없어, 지도 핀은 이 목록의 좌표를 hospitalId로 찾아 쓴다 */
@Serializable
data class MapHospitalPos(val hospitalId: String, val gps: GPS)

@Serializable
data class MapOverview(val hospitals: List<MapHospitalPos> = emptyList())

@Serializable
data class IdentityInfo(val name: String? = null, val known: Boolean = false, val simDispatch: Boolean? = null, val gps: GPS? = null)

enum class AmbulancePhase(val label: String) {
    idle("출동 대기"), dispatching("현장 출동 중"), on_scene("현장 도착"), transporting("병원 이송 중"),
    at_hospital("병원 도착"), rerouting("재선택 대기"), returning("기지 복귀 중");

    companion object {
        fun of(s: String?): AmbulancePhase = entries.firstOrNull { it.name == s } ?: idle
    }
}

/** ambulance_phase / ambulance_position */
@Serializable
data class AmbulanceSim(
    val apid: String,
    val caseId: String? = null,
    val phase: String = "idle",
    val gps: GPS? = null,
    val etaSec: Double? = null,
    val paused: Boolean? = null,
    /** 왜 멈췄나(2026-10-05): "manual" 시연 일시정지(조작 잠금) | "call" 이송 중 추가 통화 동안만 이동 멈춤 */
    val pauseReason: String? = null,
    /** 이송 중·도착한 병원(이송 확정 병원) */
    val hospitalId: String? = null,
    /** 사고 현장 좌표 — 인계확인서 출발지 주소 */
    val incident: GPS? = null,
    /** 도로 ETA를 시연 화면 시간으로 환산한 배속(hub의 경로 이동과 같은 값) */
    val speedup: Double? = null,
    /** hub 카카오 도로 경로 [[lat, lng], ...] — ambulance_position은 생략하므로 앱이 이전 경로를 유지한다 */
    val path: List<List<Double>>? = null,
    /** 구급대 센터(출동 출발지) — 이동 위치와 별도로 보존된다 */
    val base: GPS? = null,
) {
    val phaseEnum: AmbulancePhase get() = AmbulancePhase.of(phase)
}

@Serializable
data class BedReliability(
    /** 지금 이 병상 숫자를 믿어도 될 확률(AI) */
    val authority: Double? = null,
    /** 도착 시점에도 유효할 확률(AI) */
    val rArrive: Double? = null,
    /** 아래는 곡선 파라미터 — 오면 BedLive.of()가 초 단위로 감쇠시킨다. 없으면 위 값 그대로(정지값) */
    val horizonSec: Double = 0.0,
    val predictedSurvivalSec: Double? = null,
    val bornAt: String? = null,
    val sigma: Double? = null,
    val confirmedAgeSec: Double? = null,
)

@Serializable
data class Specialty(val department: String, val doctorCount: Int = 0)

@Serializable
data class SceneCandidate(
    val hospitalId: String,
    val name: String,
    val distanceKm: Double = 0.0,
    val roadDistanceKm: Double? = null,
    val etaMin: Double? = null,
    val availableBedCount: Int = 0,
    val bedCountUnknown: Boolean = false,
    val bedReliability: BedReliability? = null,
    val firstCallRecommended: Boolean? = null,
    val supportedKtas: List<Int>? = null,
    val firstCallReason: String? = null,
    val emergencyLevel: String? = null,
    val specialties: List<Specialty>? = null,
)

@Serializable
data class SceneCandidates(
    val caseId: String,
    val apid: String,
    /** 도착 시간순(hub가 정한 순서 그대로 쓴다) */
    val hospitals: List<SceneCandidate> = emptyList(),
    /** 이 후보 목록이 어느 Pre-KTAS 기준인지 — 앱이 고른 값과 다르면 아직 hub 응답을 기다리는 중 */
    /** 전화가 안 받아 다음 병원으로 넘어간 병원들 */
    val callAttempts: List<String>? = null,
    val firstCallExhausted: Boolean? = null,
    val reportedSymptom: String? = null,
)

@Serializable
data class CallStatus(
    val caseId: String,
    val apid: String,
    val hospitalId: String? = null,
    val hospitalName: String? = null,
    val device: String? = null,
    /** 앱이 보낸 call_connection request의 requestId — 내 요청에 대한 상태인지 가린다 */
    val requestId: String? = null,
    val state: String = "ended",  // "ringing" | "calling" | "ended" | "no_answer" | "cancelled"
    val startedAt: String? = null,
    /** 2026-10-05: 같은 사건의 추가 통화인지 · 취소된 통화인지(전달 안 됨) */
    val followup: Boolean? = null,
    val cancelled: Boolean? = null,
)

@Serializable
data class CallTranscriptLine(val caseId: String? = null, val start: Double = 0.0, val end: Double = 0.0, val text: String = "")

@Serializable
data class SpecialtyMatch(val department: String? = null, val score: Double? = null, val basis: String? = null, val doctorCount: Int? = null)

/** 매칭 결과의 병원 하나 — 아이패드 HospitalMatch 중 폰 화면(이송 탭)이 쓰는 칸 */
@Serializable
data class MatchHospital(
    val hospitalId: String,
    val name: String,
    val status: String = "pending",  // pending | approved | rejected | confirmed
    val distanceKm: Double = 0.0,
    val roadDistanceKm: Double? = null,
    val etaMin: Double? = null,
    val travelMin: Double? = null,
    val specialtyMatch: SpecialtyMatch? = null,
    val availableBedCount: Int? = null,
    val bedCountUnknown: Boolean? = null,
    val bedDataStale: Boolean? = null,
    val erBedCapacity: Int? = null,
    val erOccupancyPct: Int? = null,
    val bedReliability: BedReliability? = null,
    val rejectReason: String? = null,
    val unavailableReason: String? = null,
    val demoteReasons: List<String>? = null,
    val excluded: Boolean? = null,
    val emergencyLevel: String? = null,
    val inFlightCount: Int? = null,
    val loadPenaltyMin: Double? = null,
)

/** match_result(또는 type 없음) — 종료 화면의 "후보 병원 N곳에 전달"과, 이송 중 통화할 목적지(확정 병원)·환자 정보 탭에 쓴다 */
@Serializable
data class MatchResult(
    val caseId: String,
    val hospitals: List<MatchHospital> = emptyList(),
    val patientInfo: PatientInfo? = null,
    val apid: String? = null,
    /** hub 규칙 기반 활성 존(1 = 0~5km, 2 = 5~10km …). 예전 메시지엔 없다 → 1 */
    val zoneActive: List<Int>? = null,
)

/** 구급대원 이송 승인 — 웹 handleApprove와 같은 형식. 병원이 승인한 병원에만 보낸다 */
@Serializable
data class ApprovalAction(
    val caseId: String,
    val hospital_id: String,
    val timestamp: String,
    val action: String = "final_approval",
    val actor: String = "paramedic",
)

/** 통화 요약 확인·수정 — hub patient_override. 보낸 칸만 바뀐다(null은 JSON에서 빠진다). 칸이 하나도 없으면 "수정 없이 확인" */
@Serializable
data class PatientOverrideMessage(
    val caseId: String,
    val timestamp: String,
    val expectedDiagnosis: String? = null,
    val injuryStatus: List<String>? = null,
    val ktasLevel: Int? = null,
    val requiredDepartment: String? = null,
    val chiefComplaint: String? = null,
    val type: String = "patient_override",
)

/** 추가 정보 전송 — patient_override의 extraNote 칸만 쓴다(요약 칸은 안 보내므로 "확인 도장"도 안 찍힌다) */
@Serializable
data class ExtraNoteMessage(
    val caseId: String,
    val extraNote: String,
    val timestamp: String,
    val type: String = "patient_override",
)

/** 조작 거부(2026-10-05) — reason "paused"면 시연 일시정지 중 */
@Serializable
data class ActionRefused(val caseId: String? = null, val reason: String = "")

/** 시연 콘솔 통화 방식(2026-10-06) — "template"(정해진 상황 선택)이면 그 단계의 통화를 못 한다(hub도 거부).
 *  stage: "scene"(② 현장 확인, 없으면 이것) | "transport"(④ 이송 중 — [목적지 병원과 통화]) */
@Serializable
data class SceneInputMode(val caseId: String, val mode: String, val stage: String? = null)

@Serializable
data class CaseClosed(val caseId: String)

/** 관제 판단 대기(hub 2026-11-04) — 여러 사건의 1순위 수용 병원이 같고 여력이 모자라 상황실이 병원을 정한다.
 *  pending이면 구급대원 이송 승인을 hub가 막는다(action_refused "dispatcher_pending"). 풀리면 pending false. */
@Serializable
data class DispatcherPending(val caseId: String, val pending: Boolean = false, val hospitalId: String? = null, val hospitalName: String? = null)

/** 관제가 구급대원 대신 이송 병원을 확정했다(hub 2026-11-01~, kind "transport_confirmed") */
@Serializable
data class DispatcherNotice(val caseId: String, val kind: String = "", val hospitalId: String? = null, val hospitalName: String? = null)

@Serializable
data class CaseSync(val caseIds: List<String> = emptyList())

/** type만 먼저 읽어 갈래를 고른다. type이 없으면 예전 hub의 매칭 결과다 */
fun messageType(text: String): String? = runCatching {
    val o = hubJson.parseToJsonElement(text).jsonObject
    (o["type"] as? JsonPrimitive)?.contentOrNull ?: "match_result"
}.getOrNull()

/** 온디바이스 요약을 hub WebSocket으로 — {"type":"voice_summary", ...call summary} (공개 도메인은 /voice/ 경로 HTTP를 열지 않는다) */
fun voiceSummaryMessage(callSummary: JsonObject): JsonObject =
    JsonObject(LinkedHashMap<String, kotlinx.serialization.json.JsonElement>().apply {
        put("type", JsonPrimitive("voice_summary")); putAll(callSummary)
    })

fun isoNow(millis: Long = System.currentTimeMillis()): String = Instant.ofEpochMilli(millis).toString()
