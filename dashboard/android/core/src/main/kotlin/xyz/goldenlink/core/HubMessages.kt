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
data class IdentifyMessage(val role: String, val id: String, val type: String = "identify")

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
    val type: String = "call_signal",
)

// ── hub -> 앱 ──

@Serializable
data class GPS(val lat: Double, val lng: Double)

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
) {
    val phaseEnum: AmbulancePhase get() = AmbulancePhase.of(phase)
}

@Serializable
data class BedReliability(
    /** 지금 이 병상 숫자를 믿어도 될 확률(AI) */
    val authority: Double? = null,
    /** 도착 시점에도 유효할 확률(AI) */
    val rArrive: Double? = null,
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
    val emergencyLevel: String? = null,
    val specialties: List<Specialty>? = null,
)

@Serializable
data class SceneCandidates(
    val caseId: String,
    val apid: String,
    /** 도착 시간순(hub가 정한 순서 그대로 쓴다) */
    val hospitals: List<SceneCandidate> = emptyList(),
    val reportedSymptom: String? = null,
)

@Serializable
data class CallStatus(
    val caseId: String,
    val apid: String,
    val hospitalId: String? = null,
    val hospitalName: String? = null,
    val device: String? = null,
    val state: String = "ended",  // "calling" | "ended"
    val startedAt: String? = null,
    /** 2026-10-05: 같은 사건의 추가 통화인지 · 취소된 통화인지(전달 안 됨) */
    val followup: Boolean? = null,
    val cancelled: Boolean? = null,
)

@Serializable
data class CallTranscriptLine(val caseId: String? = null, val start: Double = 0.0, val end: Double = 0.0, val text: String = "")

@Serializable
data class MatchHospital(val hospitalId: String, val name: String, val status: String = "pending")

/** match_result(또는 type 없음) — 종료 화면의 "후보 병원 N곳에 전달"과, 이송 중 통화할 목적지(확정 병원)에 쓴다 */
@Serializable
data class MatchResult(val caseId: String, val hospitals: List<MatchHospital> = emptyList())

/** 조작 거부(2026-10-05) — reason "paused"면 시연 일시정지 중 */
@Serializable
data class ActionRefused(val caseId: String? = null, val reason: String = "")

/** 시연 콘솔 ② 현장 확인 방식(2026-10-06) — "template"(정해진 상황 선택)이면 현장 통화를 못 한다(hub도 거부) */
@Serializable
data class SceneInputMode(val caseId: String, val mode: String)

@Serializable
data class CaseClosed(val caseId: String)

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
