package xyz.goldenlink.phone

import android.app.Application
import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.KSerializer
import xyz.goldenlink.core.CallAcceptMessage
import xyz.goldenlink.core.CallError
import xyz.goldenlink.core.CallHangupMessage
import xyz.goldenlink.core.CallIncoming
import xyz.goldenlink.core.CallLabels
import xyz.goldenlink.core.CallRejectMessage
import xyz.goldenlink.core.CallState
import xyz.goldenlink.core.CallStateSyncMessage
import xyz.goldenlink.core.IceServerConfig
import xyz.goldenlink.core.IdentityInfo
import xyz.goldenlink.core.MediaReadyMessage
import xyz.goldenlink.core.RtcIceIn
import xyz.goldenlink.core.RtcIceMessage
import xyz.goldenlink.core.RtcSdpIn
import xyz.goldenlink.core.RtcSdpMessage
import xyz.goldenlink.core.hubJson

/**
 * 병원 모드(2026-11-04) — 병원 접근 코드(`H-<hpid>`)로 들어온 안드로이드가 구급대 앱의 실제 통화(WebRTC)를 받는다.
 * 구급대원 지도·환자 편집 화면은 쓰지 않는다. 수신 대기 → 전화 수신(벨소리·받기·거절) → 연결 중 → 통화 중 → 종료.
 *
 * hub에는 role "hospital", callCapable=true로 접속한다(같은 병원 코드의 웹 대시보드와 구분 — hub는 이 기기에만 울린다).
 * 통화 규칙(받기와 음성 연결 완료의 구분, 늦은 메시지 무시, 중복 종료 한 번)은 hub/call_sessions.py가 정하고, 앱은
 * 현재 callId에 대한 메시지만 따른다. 마이크는 통화 종료를 누르면 hub 응답을 기다리지 않고 바로 끈다.
 */
class HospitalModel(application: Application) : AndroidViewModel(application) {
    val settings = Settings(application)

    enum class Phase { INCOMING, CONNECTING, ACTIVE }
    data class UiCall(val callId: String, val caseId: String, val ambulanceName: String?, val phase: Phase, val activeSince: Long? = null)

    var connection by mutableStateOf(HubSocket.State.CONNECTING)
    var hospitalName by mutableStateOf<String?>(null)
    var call by mutableStateOf<UiCall?>(null)
    var notice by mutableStateOf<String?>(null)
    var speaker by mutableStateOf(false)
    var muted by mutableStateOf(false)

    private var socket: HubSocket? = null
    private var rtc: RtcSession? = null
    private var iceServers: List<IceServerConfig> = emptyList()
    private var negotiation = 1
    private val ringer = Ringer(application)
    private val audio = CallAudio(application)
    private var noticeJob: Job? = null

    val hospitalId: String get() = settings.hospitalId

    fun start() {
        stop()
        val id = settings.hospitalId.trim()
        if (id.isEmpty()) return
        socket = HubSocket(settings.wsUrl, "hospital", id, { t, d -> handle(t, d) }, { s -> onConnectionState(s) }, callCapable = true)
    }

    fun stop() {
        endLocal()
        socket?.close(); socket = null
        hospitalName = null
    }

    override fun onCleared() { stop() }

    private fun onConnectionState(s: HubSocket.State) {
        connection = s
        // (재)접속하면 지금 통화를 묻는다 — 울리는 중이면 다시 울리고, 이미 끝났으면 종료를 알려 화면을 정리한다
        if (s == HubSocket.State.LIVE) send(CallStateSyncMessage.serializer(), CallStateSyncMessage(call?.callId))
    }

    private fun <T> send(serializer: KSerializer<T>, value: T): Boolean =
        socket?.send(hubJson.encodeToJsonElement(serializer, value)) == true

    fun show(text: String) {
        notice = text
        noticeJob?.cancel()
        noticeJob = viewModelScope.launch { delay(3000); notice = null }
    }

    // ── hub 메시지 ──

    private fun handle(type: String, text: String) {
        runCatching {
            when (type) {
                "identity_info" -> hospitalName = hubJson.decodeFromString(IdentityInfo.serializer(), text).name
                "call_incoming" -> onIncoming(hubJson.decodeFromString(CallIncoming.serializer(), text))
                "call_state" -> onCallState(hubJson.decodeFromString(CallState.serializer(), text))
                "rtc_offer" -> onOffer(hubJson.decodeFromString(RtcSdpIn.serializer(), text))
                "rtc_ice" -> hubJson.decodeFromString(RtcIceIn.serializer(), text).let { ice ->
                    if (call?.callId == ice.callId) rtc?.addRemoteIce(ice.candidate)
                }
                "call_error" -> hubJson.decodeFromString(CallError.serializer(), text).let { e ->
                    if (call?.callId == e.callId) {
                        endLocal()
                        show(if (e.reason == "not_ringing") "이미 종료됐거나 다른 기기가 받은 전화입니다" else "통화를 처리하지 못했습니다")
                    }
                }
                else -> Unit  // 병원 모드와 상관없는 메시지(사건·병원 목록 등)는 버린다
            }
        }.onFailure { Log.w("GoldenLink", "병원 모드 hub 메시지($type) 처리 실패", it) }
    }

    private fun onIncoming(incoming: CallIncoming) {
        val current = call
        if (current != null) {
            // 이미 같은 전화를 울리고 있으면 재전송이다. 다른 전화가 오면 지금 통화 중이라 거절한다
            if (current.callId != incoming.callId) send(CallRejectMessage.serializer(), CallRejectMessage(incoming.callId))
            return
        }
        iceServers = incoming.iceServers
        call = UiCall(incoming.callId, incoming.caseId, incoming.ambulanceName, Phase.INCOMING)
        ringer.start()
    }

    private fun onCallState(s: CallState) {
        val c = call
        if (c == null || c.callId != s.callId) {
            // 우리가 모르는 통화가 hub에서는 살아 있다(앱이 다시 켜지며 음성 연결을 잃은 경우) — 병원이 계속 통화 중으로 묶이지 않게 끊는다
            if (s.state == "connecting" || s.state == "active") send(CallHangupMessage.serializer(), CallHangupMessage(s.callId))
            return
        }
        when (s.state) {
            "ended" -> { endLocal(); show(CallLabels.endText(s.reason, s.detail)) }
            "connecting" -> {
                s.iceServers?.takeIf { it.isNotEmpty() }?.let { iceServers = it }
                if (c.phase == Phase.INCOMING) call = c.copy(phase = Phase.CONNECTING)
            }
            "active" -> {
                ringer.stop()
                call = c.copy(phase = Phase.ACTIVE, activeSince = c.activeSince ?: System.currentTimeMillis())
            }
        }
    }

    private fun onOffer(offer: RtcSdpIn) {
        val c = call ?: return
        if (offer.callId != c.callId || c.phase == Phase.INCOMING) return
        negotiation = offer.negotiationRevision
        rtc?.close()
        val session = runCatching { RtcSession(getApplication(), iceServers, listenerFor(c.callId)) }.getOrElse {
            Log.w("GoldenLink", "WebRTC 연결 준비 실패", it)
            failCall(c.callId, "통화 연결을 준비하지 못했습니다")
            return
        }
        rtc = session
        session.acceptOffer(offer.sdp) { answer ->
            viewModelScope.launch {
                if (call?.callId == c.callId) send(RtcSdpMessage.serializer(), RtcSdpMessage("rtc_answer", c.callId, answer, negotiation))
            }
        }
    }

    /** WebRTC 스레드의 콜백을 메인으로 옮기고, 지금 통화(callId)에 대한 것만 따른다 */
    private fun listenerFor(callId: String) = object : RtcSession.Listener {
        override fun onLocalIce(candidate: kotlinx.serialization.json.JsonObject) {
            viewModelScope.launch { if (call?.callId == callId) send(RtcIceMessage.serializer(), RtcIceMessage(callId, candidate, negotiation)) }
        }

        override fun onMediaReady() {
            viewModelScope.launch { if (call?.callId == callId) send(MediaReadyMessage.serializer(), MediaReadyMessage(callId)) }
        }

        override fun onFailed(reason: String) {
            viewModelScope.launch { failCall(callId, "통화 연결에 실패했습니다") }
        }
    }

    private fun failCall(callId: String, message: String) {
        if (call?.callId != callId) return
        send(CallHangupMessage.serializer(), CallHangupMessage(callId))
        endLocal()
        show(message)
    }

    // ── 사용자 조작 ──

    /** [전화 받기] — 마이크 권한은 화면이 먼저 받아 둔다. 받은 뒤 hub가 연결 중으로 바꾸고 구급대 앱이 offer를 보낸다 */
    fun accept() {
        val c = call ?: return
        if (c.phase != Phase.INCOMING) return
        if (socket?.isOpen != true) { show("hub 연결을 확인해 주세요. 전화를 받지 못했습니다."); return }
        ringer.stop()
        audio.start()
        send(CallAcceptMessage.serializer(), CallAcceptMessage(c.callId, settings.deviceId))
        call = c.copy(phase = Phase.CONNECTING)
    }

    fun reject() {
        val c = call ?: return
        if (c.phase != Phase.INCOMING) return
        send(CallRejectMessage.serializer(), CallRejectMessage(c.callId))
        endLocal()
    }

    /** [통화 종료] — 마이크·연결을 바로 정리하고 hub에 알린다(hub 응답이 늦어도 마이크는 이미 꺼져 있다) */
    fun hangup() {
        val c = call ?: return
        send(CallHangupMessage.serializer(), CallHangupMessage(c.callId))
        endLocal()
        show("통화를 종료했습니다")
    }

    fun toggleSpeaker() { speaker = !speaker; audio.setSpeaker(speaker) }
    fun toggleMute() { muted = !muted; rtc?.setMicMuted(muted) }

    /** 이 기기의 통화 자원(벨소리·마이크·연결·오디오 경로)을 모두 정리하고 수신 대기로 돌아간다. 여러 번 불러도 안전하다 */
    private fun endLocal() {
        ringer.stop()
        rtc?.close(); rtc = null
        audio.stop()
        call = null
        speaker = false; muted = false
    }
}
