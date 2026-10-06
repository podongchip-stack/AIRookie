package xyz.goldenlink.phone

import android.app.Application
import android.content.pm.PackageManager
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.core.content.ContextCompat
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.JsonObject
import xyz.goldenlink.core.ActionRefused
import xyz.goldenlink.core.AmbulancePhase
import xyz.goldenlink.core.AmbulanceSim
import xyz.goldenlink.core.CallSignalMessage
import xyz.goldenlink.core.CallStatus
import xyz.goldenlink.core.CallTranscriptLine
import xyz.goldenlink.core.CaseClosed
import xyz.goldenlink.core.CaseSync
import xyz.goldenlink.core.IdentityInfo
import xyz.goldenlink.core.MatchHospital
import xyz.goldenlink.core.MatchResult
import xyz.goldenlink.core.SceneCandidate
import xyz.goldenlink.core.SceneCandidates
import xyz.goldenlink.core.SceneInputMode
import xyz.goldenlink.core.hubJson
import xyz.goldenlink.core.voiceSummaryMessage
import java.io.File

/**
 * 웹 전화 앱(dashboard/src/app/phone/page.tsx + PhoneCallView.tsx)·아이폰 PhoneModel.swift의 상태와 규칙.
 * 휴대폰은 전화만 한다 — 출동·현장 종료·이송 승인은 태블릿/PC 대시보드에서 한다. 사건(caseId)도 만들지 않고
 * hub 출동 상태(ambulance_phase.caseId)를 그대로 쓴다. 통화는 [취소]와 [전송]으로 끝난다 — [전송]을 눌러야만 음성을
 * 처리해 병원에 보낸다. 현장 첫 통화 뒤에도 환자 상태가 바뀌면 추가 통화를 할 수 있고, 새 요약은 환자 정보에 덧붙는다.
 */
class PhoneModel(app: Application) : AndroidViewModel(app) {
    val settings = Settings(app)

    // 연결
    var connection by mutableStateOf(HubSocket.State.CONNECTING)
    var apid by mutableStateOf<String?>(null)  // 지금 보는 구급차. 자동 전환 모드면 바뀐다
    var identity by mutableStateOf<IdentityInfo?>(null)

    // hub가 알려 준 상태
    val sims = mutableStateMapOf<String, AmbulanceSim>()
    val scenes = mutableStateMapOf<String, SceneCandidates>()
    val callStatus = mutableStateMapOf<String, CallStatus>()
    val hubTranscripts = mutableStateMapOf<String, List<CallTranscriptLine>>()
    val sentCount = mutableStateMapOf<String, Int>()  // 매칭 결과의 후보 병원 수
    private val matchVersion = mutableStateMapOf<String, Int>()  // 사건별로 매칭 결과를 받은 횟수 — 추가 통화가 반영됐는지 판단
    private val destinations = mutableStateMapOf<String, MatchHospital?>()  // 사건별 이송 확정 병원
    private val sceneInputMode = mutableStateMapOf<String, String>()  // 사건별 시연 콘솔 ② 현장 확인 방식("voice" | "template")

    // 이 기기의 통화
    var call by mutableStateOf<LocalCall?>(null)
    var session by mutableStateOf<CallSession?>(null)
    var error by mutableStateOf<String?>(null)
    var notice by mutableStateOf<String?>(null)  // 화면 위에 잠깐 뜨는 안내(일시정지 등)
    var modelStatus by mutableStateOf("")
    var wantsExtraCall by mutableStateOf(false)  // 현장에서 전달 뒤 [추가 통화]를 눌러 병원 목록을 다시 연 상태
    var needsMicPermission by mutableIntStateOf(0)  // 올라가면 화면이 권한 요청을 띄운다

    data class LocalCall(
        val caseId: String,
        val hospitalId: String,
        val hospitalName: String,
        val followup: Boolean,
        val phase: Phase,
        val startedAt: Long,
        val endedAt: Long? = null,
        val matchVersionAtSend: Int = 0,
    ) {
        enum class Phase { CONNECTING, IN_CALL, ENDED }
    }

    val models = ModelStore(File(app.getExternalFilesDir(null), "models"))
    private var monitor: HubSocket? = null
    private var ambulance: HubSocket? = null
    private var noticeJob: Job? = null

    val autoFollow: Boolean get() = settings.apid.trim().lowercase() == "auto"

    init { start() }

    fun start() {
        stop()
        if (autoFollow) {
            monitor = HubSocket(settings.wsUrl, "monitor", "phone-auto", { t, d -> handle(t, d, fromMonitor = true) },
                { s -> if (ambulance == null) connection = s })
        } else {
            follow(settings.apid.trim().uppercase())
        }
        if (settings.onDevice) {
            modelStatus = "온디바이스 모델 불러오는 중…"
            viewModelScope.launch {
                val err = withContext(modelDispatcher) { models.load() }
                // 모델이 없을 때의 문구는 띄우지 않는다(아이폰과 같은 2026-10-05 요청) — 그때는 조용히 서버 음성 인식으로 동작
                modelStatus = if (err == null) "온디바이스 음성 인식·구조화 · ${models.describe()}" else "서버 음성 인식"
            }
        } else {
            modelStatus = "서버 음성 인식"
        }
    }

    fun stop() {
        monitor?.close(); monitor = null
        ambulance?.close(); ambulance = null
        apid = null
    }

    override fun onCleared() { stop() }

    private fun follow(newApid: String?) {
        if (newApid == apid) return
        ambulance?.close()
        ambulance = null
        apid = newApid
        identity = null
        wantsExtraCall = false
        if (newApid == null) return
        ambulance = HubSocket(settings.wsUrl, "ambulance", newApid, { t, d -> handle(t, d, fromMonitor = false) }, { s -> connection = s })
    }

    // ── 화면이 쓰는 값 ──

    val mySim: AmbulanceSim? get() = apid?.let { sims[it] }
    val simOn: Boolean get() = identity?.simDispatch == true
    val caseId: String? get() = if (simOn) mySim?.caseId else null
    val scene: SceneCandidates? get() = caseId?.let { scenes[it] }
    val status: CallStatus? get() = caseId?.let { callStatus[it] }
    val phase: AmbulancePhase get() = mySim?.phaseEnum ?: AmbulancePhase.idle
    val onScene: Boolean get() = simOn && phase == AmbulancePhase.on_scene && caseId != null
    /** 이송 중·재선택 대기 — 목적지(또는 다른) 병원과 추가 통화를 할 수 있는 단계 */
    val inTransport: Boolean get() = simOn && caseId != null && (phase == AmbulancePhase.transporting || phase == AmbulancePhase.rerouting)
    /** 운영자의 시연 일시정지(조작 잠금). 추가 통화로 이동만 멈춘 경우("call")는 통화·전송을 막지 않는다 */
    val paused: Boolean get() = mySim?.paused == true && mySim?.pauseReason != "call"
    /** 이송 중 추가 통화 동안 구급차 이동이 멈춰 있다(통화 내용이 반영되면 hub가 다시 출발시킨다) */
    val transportHeld: Boolean get() = mySim?.paused == true && mySim?.pauseReason == "call"
    val sent: Boolean get() = caseId?.let { sentCount[it] } != null
    /** 콘솔이 "정해진 상황 선택" 중이면 현장 첫 통화를 못 한다(매칭 뒤 추가 통화는 해당 없음) */
    val sceneCallBlocked: Boolean get() = !sent && caseId?.let { sceneInputMode[it] } == "template"
    val destination: MatchHospital?
        get() {
            val id = caseId ?: return null
            destinations[id]?.let { return it }
            val hid = mySim?.hospitalId ?: return null
            val name = scene?.hospitals?.firstOrNull { it.hospitalId == hid }?.name ?: return null
            return MatchHospital(hid, name, "confirmed")
        }

    /** 자막: 온디바이스면 기기에서 인식한 줄, 서버 STT면 hub가 되돌려 준 줄 */
    val transcriptLines: List<String>
        get() {
            val s = session
            if (s != null && models.ready && settings.onDevice && call != null) return s.lines.map { it.text }
            return caseId?.let { hubTranscripts[it] }?.map { it.text } ?: emptyList()
        }

    /** 전송한 통화가 반영됐는가(이 통화를 보낸 뒤 매칭 결과가 새로 왔는가) */
    val delivered: Boolean
        get() {
            val c = call ?: return false
            return c.phase == LocalCall.Phase.ENDED && (matchVersion[c.caseId] ?: 0) > c.matchVersionAtSend
        }

    // ── hub 메시지 ──

    private fun handle(type: String, text: String, fromMonitor: Boolean) {
        runCatching {
            when (type) {
                "identity_info" -> if (!fromMonitor) identity = hubJson.decodeFromString(IdentityInfo.serializer(), text)
                "ambulance_phase", "ambulance_position" -> {
                    val sim = hubJson.decodeFromString(AmbulanceSim.serializer(), text)
                    sims[sim.apid] = sim
                    if (sim.apid == apid && sim.phaseEnum != AmbulancePhase.on_scene) wantsExtraCall = false
                    if (fromMonitor) autoSwitch()
                }
                "scene_candidates" -> if (!fromMonitor) hubJson.decodeFromString(SceneCandidates.serializer(), text).let { scenes[it.caseId] = it }
                "scene_input_mode" -> if (!fromMonitor) hubJson.decodeFromString(SceneInputMode.serializer(), text).let { sceneInputMode[it.caseId] = it.mode }
                "call_status" -> if (!fromMonitor) hubJson.decodeFromString(CallStatus.serializer(), text).let { callStatus[it.caseId] = it }
                "call_transcript" -> if (!fromMonitor) {
                    val l = hubJson.decodeFromString(CallTranscriptLine.serializer(), text)
                    val c = l.caseId
                    if (c != null) hubTranscripts[c] = (hubTranscripts[c] ?: emptyList()) + l
                }
                "match_result" -> if (!fromMonitor) {
                    val m = hubJson.decodeFromString(MatchResult.serializer(), text)
                    sentCount[m.caseId] = m.hospitals.size
                    matchVersion[m.caseId] = (matchVersion[m.caseId] ?: 0) + 1
                    destinations[m.caseId] = m.hospitals.firstOrNull { it.status == "confirmed" }
                }
                "action_refused" -> if (!fromMonitor) {
                    val r = hubJson.decodeFromString(ActionRefused.serializer(), text)
                    show(when (r.reason) {
                        "paused" -> "현재 시연 일시정지 중입니다."
                        "template_mode" -> "콘솔이 정해진 상황 선택 중이라 전화할 수 없습니다."
                        else -> "지금은 통화를 시작할 수 없습니다."
                    })
                    if (call?.phase == LocalCall.Phase.CONNECTING) call = null
                }
                "case_closed" -> forget(hubJson.decodeFromString(CaseClosed.serializer(), text).caseId)
                "case_sync" -> if (!fromMonitor) {
                    val ids = hubJson.decodeFromString(CaseSync.serializer(), text).caseIds.toSet()
                    for (id in (scenes.keys + sentCount.keys) - ids) forget(id)
                }
                else -> Unit  // 모르는 type은 버린다
            }
        }
    }

    private fun forget(caseId: String) {
        scenes.remove(caseId); callStatus.remove(caseId); hubTranscripts.remove(caseId); sentCount.remove(caseId)
        matchVersion.remove(caseId); destinations.remove(caseId); sceneInputMode.remove(caseId)
        if (call?.caseId == caseId && (session == null || call?.phase == LocalCall.Phase.ENDED)) { call = null; session = null }
    }

    /** 웹 PhoneAutoFollow와 같은 규칙: 사건이 진행 중인 구급차로 넘어가되, 지금 보는 구급차의 사건이 진행 중이면 넘어가지 않는다 */
    private fun autoSwitch() {
        fun active(s: AmbulanceSim?) = s?.caseId != null && s.phaseEnum != AmbulancePhase.idle && s.phaseEnum != AmbulancePhase.returning
        if (apid != null && active(sims[apid])) return
        if (call != null && call?.phase != LocalCall.Phase.ENDED) return  // 통화 중 화면 전환 방지
        val next = sims.values.filter { active(it) }.map { it.apid }.sorted().firstOrNull()
        if (next != null || apid != null) follow(next)
    }

    /** 화면 위 안내를 잠깐(2.5초) 띄운다 */
    fun show(text: String) {
        notice = text
        noticeJob?.cancel()
        noticeJob = viewModelScope.launch { delay(2500); notice = null }
    }

    // ── 통화 ──

    fun dial(h: SceneCandidate) = dial(h.hospitalId, h.name)

    /** 병원을 누름 -> "연결 중"(1.5초 연출) -> call_started -> 녹음. 첫 통화든 추가 통화든 같다(추가 통화는 hub가 덧붙인다) */
    fun dial(hospitalId: String, name: String) {
        val caseId = caseId ?: return
        val apid = apid ?: return
        if (call != null) return
        error = null
        if (paused) { show("현재 시연 일시정지 중입니다."); return }
        if (sceneCallBlocked) { show("콘솔이 정해진 상황 선택 중이라 전화할 수 없습니다."); return }
        if (ContextCompat.checkSelfPermission(getApplication(), CallService.PERMISSION) != PackageManager.PERMISSION_GRANTED) {
            needsMicPermission += 1
            return
        }
        val followup = sent
        call = LocalCall(caseId, hospitalId, name, followup, LocalCall.Phase.CONNECTING, System.currentTimeMillis())
        viewModelScope.launch {
            delay(1500)
            if (call?.caseId != caseId || call?.phase != LocalCall.Phase.CONNECTING) return@launch  // 연결 중에 취소함
            // 시작 신호를 먼저 보내야 hub가 이 사건으로 통화를 연다(서버 STT면 음성도 이 사건에 묶는다)
            val socket = ambulance
            if (socket?.send(hubJson.encodeToJsonElement(CallSignalMessage.serializer(),
                    CallSignalMessage("call_started", apid, caseId, hospitalId))) != true) {
                call = null
                error = "hub와 연결이 끊겨 통화를 시작하지 못했습니다. 잠시 뒤 다시 눌러 주세요."
                return@launch
            }
            val onDevice = settings.onDevice && models.ready
            val s = CallSession(getApplication(), caseId, if (onDevice) models else null,
                if (onDevice) null else { pcm -> socket.sendBinary(pcm) },
                { payload -> sendSummary(payload) },
                settings.silenceRms, settings.holdSec, viewModelScope)
            try {
                s.start()
            } catch (t: Throwable) {
                socket.send(hubJson.encodeToJsonElement(CallSignalMessage.serializer(),
                    CallSignalMessage("call_ended", apid, caseId, hospitalId, cancelled = true)))
                call = null
                error = "마이크를 시작하지 못했습니다: ${t.message}"
                return@launch
            }
            session = s
            call = call?.copy(phase = LocalCall.Phase.IN_CALL, startedAt = System.currentTimeMillis())
        }
    }

    /** [취소] — 아무것도 전송하지 않는다. 녹음·인식을 버리고 hub에는 취소로 알려 "통화 중" 표시만 지운다 */
    fun cancelCall() {
        val c = call ?: return
        val apid = apid
        if (c.phase == LocalCall.Phase.IN_CALL && apid != null) {
            ambulance?.send(hubJson.encodeToJsonElement(CallSignalMessage.serializer(),
                CallSignalMessage("call_ended", apid, c.caseId, c.hospitalId, cancelled = true)))
            session?.cancel()
        }
        call = null
        session = null
        show("통화를 취소했습니다 — 전달하지 않았습니다")
    }

    /** [전송] — 통화를 끝내고 이때만 음성을 처리(인식·구조화)해 병원에 보낸다 */
    fun sendCall() {
        val c = call ?: return
        val apid = apid ?: return
        if (c.phase != LocalCall.Phase.IN_CALL) return
        if (paused) { show("현재 시연 일시정지 중입니다."); return }
        ambulance?.send(hubJson.encodeToJsonElement(CallSignalMessage.serializer(),
            CallSignalMessage("call_ended", apid, c.caseId, c.hospitalId)))
        call = c.copy(phase = LocalCall.Phase.ENDED, endedAt = System.currentTimeMillis(), matchVersionAtSend = matchVersion[c.caseId] ?: 0)
        wantsExtraCall = false
        val s = session
        viewModelScope.launch { s?.finish() }
    }

    /** 종료 화면의 [확인] — 다음 화면(전달됨 · 추가 통화)으로 */
    fun dismissEnded() {
        call = null
        session = null
    }

    /** 온디바이스 요약을 hub로 — WebSocket(type "voice_summary")으로 보낸다(공개 도메인은 /voice/ 경로 HTTP를 열지 않는다) */
    private suspend fun sendSummary(payload: JsonObject): String? = withContext(Dispatchers.Main) {
        val socket = ambulance
        when {
            socket == null || !socket.isOpen -> "hub 연결이 끊겨 전달하지 못했습니다"
            socket.send(voiceSummaryMessage(payload)) -> null
            else -> "hub 전송 실패"
        }
    }
}
