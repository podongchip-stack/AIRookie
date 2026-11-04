package xyz.goldenlink.core

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonObject

// 실제 양방향 통화(WebRTC, 2026-11-04) — hub/call_sessions.py와 같은 모양.
// 식별자: caseId(사건) / callId(통화 시도 하나, 재전화 시 새로 만든다) / negotiationRevision(연결 협상 세대).
// 구급대 앱이 걸고(call_invite → rtc_offer), 병원 앱이 받는다(call_accept → rtc_answer). 음성은 hub를 거치지 않는다.

// ── 앱 -> hub ──

@Serializable
data class CallInviteMessage(
    val callId: String,
    val caseId: String,
    val hospitalId: String,
    val deviceId: String? = null,
    val timestamp: String = isoNow(),
    val type: String = "call_invite",
    val pipeline: String? = null,
)

@Serializable
data class CallAcceptMessage(val callId: String, val deviceId: String? = null, val type: String = "call_accept")

@Serializable
data class CallRejectMessage(val callId: String, val type: String = "call_reject")

@Serializable
data class CallHangupMessage(val callId: String, val type: String = "call_hangup")

@Serializable
data class CallPipelineFinishMessage(val callId: String, val type: String = "call_pipeline_finish")

/** type: "rtc_offer"(구급대 → 병원) | "rtc_answer"(병원 → 구급대) */
@Serializable
data class RtcSdpMessage(val type: String, val callId: String, val sdp: String, val negotiationRevision: Int = 1)

/** candidate: {sdpMid, sdpMLineIndex, candidate} — hub는 내용을 해석하지 않고 상대에게 그대로 중계한다 */
@Serializable
data class RtcIceMessage(
    val callId: String,
    val candidate: JsonObject,
    val negotiationRevision: Int = 1,
    val type: String = "rtc_ice",
)

/** 이 기기의 WebRTC 연결·오디오 경로가 준비됐다 — 양쪽이 보고해야 hub가 통화 중(active)으로 바꾼다 */
@Serializable
data class MediaReadyMessage(val callId: String, val type: String = "media_ready")

/** (재)접속 때 현재 통화를 묻는다 — callId가 없으면 이 구급대·병원의 살아 있는 통화를 돌려준다 */
@Serializable
data class CallStateSyncMessage(val callId: String? = null, val type: String = "call_state_sync")

// ── hub -> 앱 ──

@Serializable
data class IceServerConfig(val urls: List<String> = emptyList(), val username: String? = null, val credential: String? = null)

/** state: ringing | connecting | active | ended. 끝났을 땐 reason(이 기기 입장의 사유)이 있다 */
@Serializable
data class CallState(
    val callId: String,
    val caseId: String? = null,
    val apid: String? = null,
    val hospitalId: String? = null,
    val hospitalName: String? = null,
    val ambulanceName: String? = null,
    val state: String,
    val sessionRevision: Int = 0,
    val reason: String? = null,
    val detail: String? = null,
    val startedAt: String? = null,
    val endedAt: String? = null,
    val iceServers: List<IceServerConfig>? = null,
    val pipeline: String? = null,
)

/** 병원 앱이 받는 수신 전화 */
@Serializable
data class CallIncoming(
    val callId: String,
    val caseId: String,
    val apid: String? = null,
    val ambulanceName: String? = null,
    val hospitalId: String,
    val hospitalName: String? = null,
    val ringingSec: Double = 30.0,
    val iceServers: List<IceServerConfig> = emptyList(),
)

@Serializable
data class RtcSdpIn(val callId: String, val sdp: String, val negotiationRevision: Int = 1)

@Serializable
data class RtcIceIn(val callId: String, val candidate: JsonObject, val negotiationRevision: Int = 1)

/** hub가 요청을 받아들이지 못했다(늦은 받기 등) — 앱이 수신/통화 화면을 닫는다 */
@Serializable
data class CallError(val callId: String, val op: String? = null, val reason: String? = null)

/** 실제 통화가 끝난 이유를 화면 문구로 — hub의 종료 사유(call_sessions.py)와 같은 이름. 이 기기 입장의 사유가 온다 */
object CallLabels {
    fun endText(reason: String?, detail: String? = null): String = when (reason) {
        "rejected" -> "병원이 통화를 거절했습니다"
        "busy" -> "병원이 다른 통화 중입니다"
        "unavailable" -> "병원 전화 앱이 연결돼 있지 않습니다"
        "no_answer" -> "병원이 응답하지 않았습니다"
        "connection_failed" -> "통화 연결에 실패했습니다"
        "caller_cancelled" -> "발신이 취소됐습니다"
        "local_hangup" -> "통화를 종료했습니다"
        "remote_hangup" -> "상대가 통화를 종료했습니다"
        "network_timeout" -> "네트워크가 끊겨 통화가 종료됐습니다"
        "answered_elsewhere" -> "다른 기기에서 받은 전화입니다"
        "case_closed" -> "사건이 종료돼 통화가 끝났습니다"
        "refused" -> when (detail) {
            "paused" -> "현재 시연 일시정지 중입니다."
            "phase" -> "지금은 전화할 수 없는 단계입니다"
            "case_busy" -> "이 사건은 이미 통화 중입니다"
            "template_mode" -> "콘솔이 정해진 상황 선택 중이라 전화할 수 없습니다."
            "unknown_hospital" -> "알 수 없는 병원입니다"
            "voice_unavailable" -> "음성 인식 서버가 연결되지 않았습니다. 기기 모델 또는 중앙 voice를 준비해 주세요."
            "not_owner" -> "이 사건의 구급대가 아니라 전화할 수 없습니다"
            else -> "통화를 시작할 수 없습니다"
        }
        else -> "통화가 종료됐습니다"
    }
}
