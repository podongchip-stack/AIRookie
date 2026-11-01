package xyz.goldenlink.phone

import android.app.Application
import android.content.pm.PackageManager
import android.util.Log
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
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import okhttp3.Request
import xyz.goldenlink.core.ActionRefused
import xyz.goldenlink.core.AmbulancePhase
import xyz.goldenlink.core.AmbulanceSim
import xyz.goldenlink.core.ApprovalAction
import xyz.goldenlink.core.BodyEdits
import xyz.goldenlink.core.BodyMark
import xyz.goldenlink.core.BodyRegion
import xyz.goldenlink.core.BodySide
import xyz.goldenlink.core.PendingHandover
import xyz.goldenlink.core.RecordHandoverRequest
import xyz.goldenlink.core.RecordImportRequest
import xyz.goldenlink.core.RecordSyncReply
import xyz.goldenlink.core.RecordSyncRequest
import xyz.goldenlink.core.CaseRecord
import xyz.goldenlink.core.Handover
import xyz.goldenlink.core.RecordDates
import xyz.goldenlink.core.RecordHospital
import xyz.goldenlink.core.InjuryMapper
import xyz.goldenlink.core.ExtraNoteMessage
import xyz.goldenlink.core.GPS
import xyz.goldenlink.core.PatientInfo
import xyz.goldenlink.core.PatientOverrideMessage
import xyz.goldenlink.core.isoNow
import xyz.goldenlink.core.CallConnectionMessage
import xyz.goldenlink.core.CallSignalMessage
import xyz.goldenlink.core.FirstCallRequest
import xyz.goldenlink.core.CallStatus
import xyz.goldenlink.core.CallTranscriptLine
import xyz.goldenlink.core.CaseClosed
import xyz.goldenlink.core.CaseSync
import xyz.goldenlink.core.IdentityInfo
import xyz.goldenlink.core.MapOverview
import xyz.goldenlink.core.MatchHospital
import xyz.goldenlink.core.MatchResult
import xyz.goldenlink.core.SceneCandidate
import xyz.goldenlink.core.SceneCandidates
import xyz.goldenlink.core.SceneInputMode
import xyz.goldenlink.core.hubJson
import xyz.goldenlink.core.voiceSummaryMessage
import java.io.File
import java.util.UUID

/**
 * 웹 전화 앱(dashboard/src/app/phone/page.tsx + PhoneCallView.tsx)·아이폰 PhoneModel.swift의 상태와 규칙.
 * 휴대폰은 통화 + 환자 정보·이송 승인(아이패드 구급차 앱과 같은 화면, 2026-10-29)을 한다 — 출동·현장 종료는 태블릿/PC 대시보드에서 한다. 사건(caseId)도 만들지 않고
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
    val results = mutableStateMapOf<String, MatchResult>()  // 사건별 최신 매칭 결과 — 환자 정보·이송 탭이 쓴다(2026-10-29)
    private val matchVersion = mutableStateMapOf<String, Int>()  // 사건별로 매칭 결과를 받은 횟수 — 추가 통화가 반영됐는지 판단
    private val destinations = mutableStateMapOf<String, MatchHospital?>()  // 사건별 이송 확정 병원
    private val sceneInputMode = mutableStateMapOf<String, String>()  // 사건별 시연 콘솔 ② 현장 확인 방식("voice" | "template")
    private val transportInputMode = mutableStateMapOf<String, String>()  // 사건별 시연 콘솔 ④ 이송 중 통화 방식(2026-10-06)

    // 이 기기의 통화
    var call by mutableStateOf<LocalCall?>(null)
    var session by mutableStateOf<CallSession?>(null)
    var error by mutableStateOf<String?>(null)
    var notice by mutableStateOf<String?>(null)  // 화면 위에 잠깐 뜨는 안내(일시정지 등)
    var wantsExtraCall by mutableStateOf(false)  // 현장에서 전달 뒤 [추가 통화]를 눌러 병원 목록을 다시 연 상태
    var needsMicPermission by mutableIntStateOf(0)  // 올라가면 화면이 권한 요청을 띄운다

    /** 아래 탭 — [통화]는 예전 전화 앱 그대로, [환자 정보]·[이송]은 아이패드 구급차 앱의 두 화면(2026-10-29) */
    enum class Tab { CALL, PATIENT, TRANSPORT, RECORDS }
    var tab by mutableStateOf(Tab.CALL)
    /** 추가 정보 입력 중인 글 — 사건별로 보관해 탭을 옮겨 다녀도 사라지지 않는다 */
    val extraNoteDrafts = mutableStateMapOf<String, String>()
    var extraNoteDraft: String
        get() = caseId?.let { extraNoteDrafts[it] } ?: ""
        set(v) { caseId?.let { extraNoteDrafts[it] = v } }
    var pendingConfirmId by mutableStateOf<String?>(null)  // 이송 승인을 보내고 hub의 확정 응답을 기다리는 병원
    var incidentAddress by mutableStateOf<String?>(null)   // 인계확인서 "출발지 주소" — hub가 좌표를 주소로 바꿔 준다
    /** 통화 화면 지도의 병원 핀 좌표 — hub map_overview(병원 목록)에서 hospitalId로 찾는다. 현장 후보 메시지엔 좌표가 없다 */
    val hospitalGps = mutableStateMapOf<String, GPS>()
    /** 현장에서 구급대원이 고른 Pre-KTAS(1~5). 지금은 화면에만 둔다 — hub 전송은 다음 작업(hub와 정하기로 함) */
    var preKtas by mutableStateOf<Int?>(null)
    var bodyEdits by mutableStateOf(BodyEdits())         // 외상 도해에서 구급대원이 고친 부위·처치 — 새 사건이면 비운다
    var bodySentSignature by mutableStateOf("")            // 마지막으로 병원에 보낸 도해 내용의 지문 — 그 뒤로 또 고쳤는지만 본다
    /** 인계확인서 시각 칸 — 출동 단계가 바뀐 그 순간(epoch ms). hub는 단계만 보내고 시각은 안 보내므로 앱이 기억한다 */
    val phaseTimes = mutableStateMapOf<String, Long>()
    private var trackedSim: AmbulanceSim? = null  // 지금 따라가는 구급차의 직전 상태 — 단계 전환을 알아채는 용도
    private var liveSince = 0L                    // 소켓이 연결된 시각 — 직후 따라잡기(지난 결과 재전송)는 화면을 자동 전환하지 않는다

    data class LocalCall(
        val caseId: String,
        val hospitalId: String,
        val hospitalName: String,
        val followup: Boolean,
        val phase: Phase,
        val startedAt: Long,
        val endedAt: Long? = null,
        val matchVersionAtSend: Int = 0,
        val callRoundAtSend: Int = 0,
    ) {
        enum class Phase { CONNECTING, IN_CALL, ENDED }
    }

    /** 지난 사건 기록(기록 탭) — 날짜별로 기기에 쌓는다. 바뀔 때마다 recordsRev가 올라 화면이 다시 읽는다 */
    val records = RecordStore(File(app.filesDir, "records")) { settings.httpBase }
    var recordsRev by mutableIntStateOf(0)
    var recordSyncStatus by mutableStateOf("구급차를 선택하면 기록을 동기화합니다.")
    var handoverConflict by mutableStateOf<CaseRecord?>(null)
    private var recordRequest: Pair<String, Long>? = null  // 보낸 기록 동기화 요청의 id와 시각 — 20초 안엔 다시 보내지 않는다
    val recordAccess = RecordAccess(settings)
    /** 같은 구급대의 휴대폰·태블릿이 인계확인서·외상 도해 수정을 공유한다 */
    val caseEdits = CaseEditSync(settings)
    val models = ModelStore(File(app.getExternalFilesDir(null), "models"))
    private var monitor: HubSocket? = null
    private var mapSocket: HubSocket? = null
    private var ambulance: HubSocket? = null
    private var noticeJob: Job? = null
    private var tickJob: Job? = null
    private var callRequestId: String? = null  // 지금 보낸 전화 연결 요청 — hub의 call_status가 내 요청에 대한 것인지 가린다

    val autoFollow: Boolean get() = settings.apid.trim().lowercase() == "auto"

    init { start() }

    fun start() {
        stop()
        if (autoFollow) {
            monitor = HubSocket(settings.wsUrl, "monitor", "phone-auto", { t, d -> handle(t, d, fromMonitor = true) },
                { s -> if (ambulance == null) onConnectionState(s) })
        } else {
            follow(settings.apid.trim().uppercase())
            // 병원 좌표(map_overview)만 받는 읽기 전용 소켓 — 다른 메시지는 거른다(구급차 위치가 초당 전 차량분 오므로 해석하지 않는다)
            mapSocket = HubSocket(settings.wsUrl, "monitor", "phone-map", { t, d -> if (t == "map_overview") handle(t, d, fromMonitor = true) }, { })
        }
        // 15초마다: 기록 동기화 재시도 · 기기 간 수정 재전송 · (현장에서 Pre-KTAS를 골랐는데 아직 전화 전이면) hub 추천 갱신(다른 사건의 연락·이송 반영)
        tickJob = viewModelScope.launch {
            while (true) {
                delay(15_000)
                syncRecords()
                caseEdits.tick()
                if (onScene && call == null && !sent && preKtas != null) requestFirstCall()
            }
        }
        // 모델이 없으면 조용히 서버 음성 인식으로 동작한다(아이폰과 같은 2026-10-05 요청)
        if (settings.onDevice) viewModelScope.launch { withContext(modelDispatcher) { models.load() } }
    }

    fun stop() {
        tickJob?.cancel(); tickJob = null; recordRequest = null
        monitor?.close(); monitor = null
        mapSocket?.close(); mapSocket = null
        ambulance?.close(); ambulance = null
        apid = null
        records.configure(null); recordsRev++
    }

    override fun onCleared() { stop() }

    private fun follow(newApid: String?) {
        if (newApid == apid) return
        ambulance?.close()
        ambulance = null
        apid = newApid
        records.configure(newApid)
        recordRequest = null; handoverConflict = null; recordsRev++
        recordSyncStatus = "기록 연결 대기 중"
        identity = null
        wantsExtraCall = false
        trackedSim = null; phaseTimes.clear(); incidentAddress = null; pendingConfirmId = null; resetBody()
        if (newApid == null) return
        ambulance = HubSocket(settings.wsUrl, "ambulance", newApid, { t, d -> handle(t, d, fromMonitor = false) }, { s -> onConnectionState(s) })
    }

    private fun onConnectionState(s: HubSocket.State) {
        val wasLive = connection == HubSocket.State.LIVE
        connection = s
        if (s == HubSocket.State.LIVE && !wasLive) { liveSince = System.currentTimeMillis(); recordRequest = null; syncRecords() }
        else if (s != HubSocket.State.LIVE) recordSyncStatus = "오프라인 · 기기 기록 표시 중"
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
    val result: MatchResult? get() = caseId?.let { results[it] }
    val patient: PatientInfo? get() = result?.patientInfo
    /** 이송이 확정된 병원 */
    val confirmed: MatchHospital? get() = result?.hospitals?.firstOrNull { it.status == "confirmed" }
    /** "사고가 발생했는가" — 출동 중·현장·이송·도착·재선택 중이거나 이 구급차 사건의 결과가 있으면 true */
    val hasIncident: Boolean get() = simOn && caseId != null && (result != null || (phase != AmbulancePhase.idle && phase != AmbulancePhase.returning))
    /** 콘솔 ②가 "정해진 상황 선택" 중이면 현장 첫 통화를 못 한다(이송 중 통화는 ④ 방식을 따른다) */
    val sceneCallBlocked: Boolean get() = !inTransport && !sent && caseId?.let { sceneInputMode[it] } == "template"
    /** 콘솔 ④가 "정해진 상황 선택" 중이면 이송 중 [목적지 병원과 통화]를 못 한다(2026-10-06) */
    val transportCallBlocked: Boolean get() = phase == AmbulancePhase.transporting && caseId?.let { transportInputMode[it] } == "template"
    /** hub 활성 존 중 가장 바깥 존(1 = 0~5km) — 통화 지도의 활성 범위 */
    val activeZone: Int get() = result?.zoneActive?.maxOrNull() ?: 1
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
            val result = results[c.caseId] ?: return false
            return c.phase == LocalCall.Phase.ENDED && (matchVersion[c.caseId] ?: 0) > c.matchVersionAtSend
                && (result.patientInfo?.callRound ?: 1) > c.callRoundAtSend
        }

    // ── hub 메시지 ──

    private fun handle(type: String, text: String, fromMonitor: Boolean) {
        runCatching {
            when (type) {
                "live_case_state", "live_case_error" -> if (!fromMonitor) caseEdits.accept(text)
                "records_changed" -> if (!fromMonitor) syncRecords()
                "record_sync_result", "record_import_result", "record_handover_result", "record_error" -> if (!fromMonitor) handleRecordReply(type, text)
                "map_overview" -> hubJson.decodeFromString(MapOverview.serializer(), text).hospitals.forEach { hospitalGps[it.hospitalId] = it.gps }
                "identity_info" -> if (!fromMonitor) {
                    identity = hubJson.decodeFromString(IdentityInfo.serializer(), text)
                    syncLiveCase()
                    caseEdits.reconnect()
                }
                "ambulance_phase", "ambulance_position" -> {
                    val decoded = hubJson.decodeFromString(AmbulanceSim.serializer(), text)
                    // ambulance_position은 path를 생략한다 — 같은 사건이면 이전 경로(와 센터)를 유지한다
                    val prev = sims[decoded.apid]
                    val sim = if (decoded.path == null && prev != null && prev.caseId == decoded.caseId) decoded.copy(path = prev.path, base = decoded.base ?: prev.base) else decoded
                    sims[sim.apid] = sim
                    if (sim.apid == apid && sim.phaseEnum != AmbulancePhase.on_scene) wantsExtraCall = false
                    if (sim.apid == apid) trackPhase(sim)
                    if (fromMonitor) autoSwitch()
                }
                "call_connection_error" -> if (call?.phase == LocalCall.Phase.CONNECTING) { call = null; callRequestId = null; show("현재 단계에서는 전화할 수 없습니다") }
                "first_call_error" -> show("첫 통화 추천 요청을 처리하지 못했습니다. 현재 사건을 확인해 주세요.")
                "scene_candidates" -> if (!fromMonitor) hubJson.decodeFromString(SceneCandidates.serializer(), text).let {
                    scenes[it.caseId] = it
                    Log.i("GoldenLink", "scene_candidates case=${it.caseId} 내 사건=${it.caseId == caseId} preKtas=${it.preKtas} 내 선택=$preKtas 병원=${it.hospitals.size}")
                    if (it.caseId == caseId && preKtas == null) preKtas = it.preKtas
                }
                "scene_input_mode" -> if (!fromMonitor) hubJson.decodeFromString(SceneInputMode.serializer(), text).let {
                    if (it.stage == "transport") transportInputMode[it.caseId] = it.mode else sceneInputMode[it.caseId] = it.mode
                }
                "call_status" -> if (!fromMonitor) hubJson.decodeFromString(CallStatus.serializer(), text).let { s ->
                    callStatus[s.caseId] = s
                    val c = call
                    // 내 전화 요청에 대한 상태만 따른다 — 관제가 받으면(calling) 그때 녹음을 시작한다
                    if (c != null && s.requestId != null && s.requestId == callRequestId && s.caseId == c.caseId && s.hospitalId == c.hospitalId) {
                        if (s.state == "calling") beginConnectedCall()
                        if (s.state == "no_answer" || s.state == "cancelled") {
                            session?.cancel(); session = null; call = null; callRequestId = null
                            show(if (s.state == "no_answer") "전화 미응답 — 다음 추천 병원을 확인하세요" else "전화 요청이 취소됐습니다")
                        }
                    }
                }
                "call_transcript" -> if (!fromMonitor) {
                    val l = hubJson.decodeFromString(CallTranscriptLine.serializer(), text)
                    val c = l.caseId
                    if (c != null) hubTranscripts[c] = (hubTranscripts[c] ?: emptyList()) + l
                }
                "match_result" -> if (!fromMonitor) {
                    val m = hubJson.decodeFromString(MatchResult.serializer(), text)
                    if (apid != null && m.apid != null && m.apid != apid) return@runCatching  // 다른 구급차 사건
                    // 자동 전환: 이 사건의 매칭 결과가 처음 오면(=음성 요약 도착, 추가 통화 회차 제외) 환자 정보로,
                    // 이송 시작은 ambulance_phase에서 통화 지도로 전환한다. 연결 직후 따라잡기(지난 결과)는 전환하지 않는다
                    val firstForCase = results[m.caseId] == null
                    results[m.caseId] = m
                    val settled = System.currentTimeMillis() - liveSince > 3000
                    if (settled && firstForCase && (m.patientInfo?.callRound ?: 1) <= 1 && phase != AmbulancePhase.transporting) tab = Tab.PATIENT
                    val confirmedId = m.hospitals.firstOrNull { it.status == "confirmed" }?.hospitalId
                    if (pendingConfirmId != null && pendingConfirmId == confirmedId) pendingConfirmId = null
                    sentCount[m.caseId] = m.hospitals.size
                    matchVersion[m.caseId] = (matchVersion[m.caseId] ?: 0) + 1
                    destinations[m.caseId] = m.hospitals.firstOrNull { it.status == "confirmed" }
                    snapshotCase(m.caseId)
                    // 이번 통화의 새 요약이 반영되면 성공 확인 화면을 거치지 않고 환자 정보로.
                    // 병원 응답·주기 갱신만으로는 callRound가 늘지 않으므로 통화 처리를 닫지 않는다.
                    if (call?.caseId == m.caseId && delivered) { dismissEnded(); tab = Tab.PATIENT }
                }
                "action_refused" -> if (!fromMonitor) {
                    val r = hubJson.decodeFromString(ActionRefused.serializer(), text)
                    pendingConfirmId = null
                    show(when (r.reason) {
                        "paused" -> "현재 시연 일시정지 중입니다."
                        "template_mode" -> "콘솔이 정해진 상황 선택 중이라 전화할 수 없습니다."
                        "already_arrived" -> "이미 병원에 도착해 이송 병원을 바꿀 수 없습니다. 현재 병원의 수용 불가 처리 후 다시 선택해 주세요."
                        else -> "지금은 통화를 시작할 수 없습니다."
                    })
                    if (call?.phase == LocalCall.Phase.CONNECTING) call = null
                }
                "case_closed" -> forget(hubJson.decodeFromString(CaseClosed.serializer(), text).caseId)
                "case_sync" -> if (!fromMonitor) {
                    val ids = hubJson.decodeFromString(CaseSync.serializer(), text).caseIds.toSet()
                    for (id in (scenes.keys + sentCount.keys + results.keys) - ids) forget(id)
                }
                else -> Unit  // 모르는 type은 버린다
            }
        }.onFailure { Log.w("GoldenLink", "hub 메시지($type) 처리 실패", it) }
        if (!fromMonitor) syncLiveCase()
    }

    private fun forget(caseId: String) {
        closeRecord(caseId)
        results.remove(caseId)
        scenes.remove(caseId); callStatus.remove(caseId); hubTranscripts.remove(caseId); sentCount.remove(caseId)
        matchVersion.remove(caseId); destinations.remove(caseId); sceneInputMode.remove(caseId)
        transportInputMode.remove(caseId)
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

    /** 현장 Pre-KTAS를 hub에 알리면 KTAS 적합 후보를 추천순으로 다시 보낸다(scene_candidates). 미응답 병원이 있으면 함께 알린다 */
    fun requestFirstCall() {
        val id = caseId ?: return
        val k = preKtas ?: return
        Log.i("GoldenLink", "first_call_request case=$id ktas=$k 소켓연결=${ambulance?.isOpen}")
        if (!sendToHub(hubJson.encodeToJsonElement(FirstCallRequest.serializer(), FirstCallRequest(id, k)))) {
            show("hub 연결을 확인해 주세요. 추천 요청을 보내지 못했습니다.")
        }
    }

    private fun connectionAction(operation: String): Boolean {
        val c = call ?: return false
        val rid = callRequestId ?: return false
        return sendToHub(hubJson.encodeToJsonElement(CallConnectionMessage.serializer(),
            CallConnectionMessage(operation, c.caseId, c.hospitalId, rid)))
    }

    /** 연결 중에 병원이 전화를 받지 않을 때 — hub가 이 병원을 미응답으로 적고 다음 추천 병원을 보낸다 */
    fun noAnswerNext() {
        if (call?.phase != LocalCall.Phase.CONNECTING) return
        if (!connectionAction("no_answer")) show("hub 연결을 확인해 주세요")
    }

    fun dial(h: SceneCandidate) = dial(h.hospitalId, h.name)

    /** hub에 전화 연결을 요청 -> 관제가 전화를 받으면(call_status calling) 그때 녹음 시작. 첫 통화든 추가 통화든 같다(추가 통화는 hub가 덧붙인다) */
    fun dial(hospitalId: String, name: String) {
        val caseId = caseId ?: return
        if (apid == null || call != null) return
        error = null
        if (paused) { show("현재 시연 일시정지 중입니다."); return }
        if (sceneCallBlocked || transportCallBlocked) { show("콘솔이 정해진 상황 선택 중이라 전화할 수 없습니다."); return }
        if (ContextCompat.checkSelfPermission(getApplication(), CallService.PERMISSION) != PackageManager.PERMISSION_GRANTED) {
            needsMicPermission += 1
            return
        }
        call = LocalCall(caseId, hospitalId, name, sent, LocalCall.Phase.CONNECTING, System.currentTimeMillis())
        callRequestId = UUID.randomUUID().toString()
        if (!connectionAction("request")) {
            call = null; callRequestId = null
            error = "hub 연결이 끊겨 전화 요청을 보내지 못했습니다."
        }
    }

    /** 관제가 전화를 받았다 — hub가 call_started를 중계했으니 마이크 녹음과 발화 인식을 시작한다 */
    private fun beginConnectedCall() {
        val c = call ?: return
        val apid = apid ?: return
        if (c.phase != LocalCall.Phase.CONNECTING) return
        call = c.copy(phase = LocalCall.Phase.IN_CALL)
        val socket = ambulance
        val onDevice = settings.onDevice && models.ready
        val s = CallSession(getApplication(), c.caseId, if (onDevice) models else null,
            if (onDevice) null else { pcm -> socket?.sendBinary(pcm) },
            { payload -> sendSummary(payload) },
            settings.silenceRms, settings.holdSec, viewModelScope)
        try {
            s.start()
        } catch (t: Throwable) {
            sendToHub(hubJson.encodeToJsonElement(CallSignalMessage.serializer(),
                CallSignalMessage("call_ended", apid, c.caseId, c.hospitalId, cancelled = true)))
            call = null; callRequestId = null
            error = "마이크를 시작하지 못했습니다: ${t.message}"
            return
        }
        session = s
        call = call?.copy(phase = LocalCall.Phase.IN_CALL, startedAt = System.currentTimeMillis())
    }

    /** [취소] — 아무것도 전송하지 않는다. 녹음·인식을 버리고 hub에는 취소로 알려 "통화 중" 표시만 지운다 */
    fun cancelCall() {
        val c = call ?: return
        val apid = apid
        if (c.phase == LocalCall.Phase.CONNECTING) {
            if (!connectionAction("cancel")) { show("hub 연결을 확인해 주세요"); return }
        }
        if (c.phase == LocalCall.Phase.IN_CALL && apid != null) {
            sendToHub(hubJson.encodeToJsonElement(CallSignalMessage.serializer(),
                CallSignalMessage("call_ended", apid, c.caseId, c.hospitalId, cancelled = true)))
            session?.cancel()
        }
        call = null
        callRequestId = null
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
        val before = results[c.caseId]
        call = c.copy(phase = LocalCall.Phase.ENDED, endedAt = System.currentTimeMillis(), matchVersionAtSend = matchVersion[c.caseId] ?: 0,
            callRoundAtSend = before?.patientInfo?.callRound ?: if (before == null) 0 else 1)
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

    // ── 환자 정보 · 이송 (아이패드 AppModel과 같은 규칙, 2026-10-29) ──

    /** 출동 단계가 바뀐 순간을 인계확인서 시각 칸에 적고, 사고 현장이 정해지면 좌표를 주소로 바꿔 둔다 */
    private fun trackPhase(sim: AmbulanceSim) {
        val prev = trackedSim
        trackedSim = sim
        // 출동·이송·복귀가 시작되면 통화 지도 탭으로 — 경로와 목적지 병원 통화가 거기 있다
        val entered = when (sim.phaseEnum) {
            AmbulancePhase.transporting -> prev?.phaseEnum != AmbulancePhase.transporting || prev?.caseId != sim.caseId || prev?.hospitalId != sim.hospitalId
            AmbulancePhase.dispatching -> prev?.phaseEnum != AmbulancePhase.dispatching || prev?.caseId != sim.caseId
            AmbulancePhase.returning -> prev?.phaseEnum != AmbulancePhase.returning
            else -> false
        }
        if (entered) tab = Tab.CALL
        // 새 출동(다른 caseId)이 시작되면 지난 사건의 시각·주소를 비운다 — 비운 뒤에 이번 단계를 적는다(순서가 반대면 방금 적은 시각이 지워진다)
        if (sim.caseId != null && sim.caseId != prev?.caseId) {
            phaseTimes.clear(); incidentAddress = null; pendingConfirmId = null; resetBody()
            phaseTimes["requestedAt"] = System.currentTimeMillis()
        }
        if (sim.phase != prev?.phase || sim.caseId != prev?.caseId) { recordPhaseTime(sim.phase); sim.caseId?.let { snapshotCase(it) } }
        if (sim.incident?.lat != prev?.incident?.lat || sim.incident?.lng != prev?.incident?.lng) {
            incidentAddress = null
            sim.incident?.let(::fetchIncidentAddress)
        }
    }

    /** 이미 적힌 칸은 덮지 않는다 — 처음 그 단계에 들어간 때가 맞다 */
    private fun recordPhaseTime(phase: String) {
        val now = System.currentTimeMillis()
        val key = when (phase) {
            "dispatching" -> "dispatchedAt"
            "on_scene" -> "sceneArrivedAt"
            "transporting" -> "transportStartedAt"
            "at_hospital" -> "transportEndedAt"
            else -> null
        }
        // 출동 단계 전환을 못 본 채(앱을 늦게 켜거나 재연결) 진행 중인 사건을 받았으면, 적어도 '출동 일시'는 이 사건을 처음 본 때로 적는다
        if (phase in listOf("on_scene", "transporting", "at_hospital", "rerouting") && "dispatchedAt" !in phaseTimes) phaseTimes["dispatchedAt"] = now
        if (key == null || key in phaseTimes) return
        phaseTimes[key] = now
        if ("requestedAt" !in phaseTimes) phaseTimes["requestedAt"] = now
    }

    /** 사고 현장 좌표 -> 주소(hub 대리 호출). 실패하면 조용히 둔다 — 인계확인서가 좌표를 그대로 적는다 */
    private fun fetchIncidentAddress(p: GPS) {
        val url = "${settings.httpBase}/geocode/reverse?lat=${p.lat}&lng=${p.lng}"
        viewModelScope.launch {
            val address = withContext(Dispatchers.IO) {
                runCatching {
                    HubSocket.client.newCall(Request.Builder().url(url).build()).execute().use { r ->
                        if (!r.isSuccessful) null
                        else (hubJson.parseToJsonElement(r.body!!.string()).jsonObject["address"] as? JsonPrimitive)?.contentOrNull
                    }
                }.getOrNull()
            }
            // 늦게 온 응답이 다른 사건을 덮지 않게 — 지금 사건의 좌표일 때만
            if (!address.isNullOrEmpty() && mySim?.incident?.lat == p.lat && mySim?.incident?.lng == p.lng) incidentAddress = address
        }
    }

    private fun sendToHub(element: kotlinx.serialization.json.JsonElement): Boolean = ambulance?.send(element) == true

    /** 이송 승인(구급대원 판단) — 웹 handleApprove와 같은 형식. 병원이 승인한 병원에만 버튼이 열린다 */
    fun approve(hospitalId: String) {
        if (paused) { show("현재 시연 일시정지 중입니다."); return }
        val id = result?.caseId ?: caseId ?: return
        pendingConfirmId = hospitalId
        if (!sendToHub(hubJson.encodeToJsonElement(ApprovalAction.serializer(), ApprovalAction(id, hospitalId, isoNow())))) {
            pendingConfirmId = null
            show("hub에 연결되지 않아 보내지 못했습니다.")
        }
    }

    /** 추가 정보 전송 — 통화 요약에 없는 것을 적어 후보 병원들에 보낸다. 순위 칸이 아니라 재매칭·승인 초기화는 없다. 보냈으면 true */
    fun sendExtraNote(text: String): Boolean {
        val note = text.trim()
        if (paused) { show("현재 시연 일시정지 중입니다."); return false }
        if (note.isEmpty()) return false
        val id = result?.caseId ?: caseId
        if (id == null) { show("진행 중인 사건이 없어 보내지 못했습니다."); return false }
        if (!sendToHub(hubJson.encodeToJsonElement(ExtraNoteMessage.serializer(), ExtraNoteMessage(id, note, isoNow())))) {
            show("hub에 연결되지 않아 보내지 못했습니다."); return false
        }
        show("추가 정보를 병원에 전달했습니다.")
        return true
    }

    /** 이 사건의 지금 상태를 기록에 올린다(없으면 새로, 있으면 갱신). 병원 응답·환자 요약·인계확인서 최종 값을 한 덩이로 둔다 */
    fun snapshotCase(id: String) {
        val r = results[id] ?: return
        val current = id == caseId
        val p = r.patientInfo
        val now = System.currentTimeMillis()
        val old = records.byCase(id)
        // 서버 버전이 있는 복사본은 지연 도착한 실시간 메시지로 덮어쓰지 않는다. 기록 탭은 서버 변경 순번으로만 갱신한다
        if (old?.archiveVersion != null) return
        val started = old?.startedAt ?: (if (current) phaseTimes["requestedAt"] else null) ?: now
        val confirmedHospital = r.hospitals.firstOrNull { it.status == "confirmed" }
        // 지금 따라가는 사건이 아니면 시각·출발지·도해 처치를 새로 만들지 못한다 — 이전 기록 값을 그대로 둔다
        val auto = if (current) Handover.auto(p, confirmedHospital, identity?.name, apid, phaseTimes.toMap(), mySim?.incident, incidentAddress, bodyEdits.careLines)
                   else Handover.auto(p, confirmedHospital, identity?.name, apid, emptyMap(), null, null)
        val values = (old?.handover ?: emptyMap()) + auto + settings.handoverEdits(id)
        records.upsert(CaseRecord(
            caseId = id, apid = r.apid ?: apid, ambulanceName = old?.ambulanceName ?: identity?.name,
            date = RecordDates.of(started), startedAt = started, updatedAt = now,
            symptom = p?.chiefComplaint ?: p?.expectedDiagnosis, expectedDiagnosis = p?.expectedDiagnosis, ktasLevel = p?.ktasLevel,
            hospitals = r.hospitals.map { RecordHospital(it.hospitalId, it.name, it.status, it.rejectReason, it.roadDistanceKm ?: it.distanceKm, it.etaMin) },
            handover = values, closed = old?.closed == true,
            archiveVersion = old?.archiveVersion, archiveEpoch = old?.archiveEpoch, handoverRevision = old?.handoverRevision,
            handoverEdits = old?.handoverEdits, events = old?.events, legacyImport = old?.legacyImport,
        ))
        recordsRev++
    }

    /** 사건이 끝났음을 기록에 남긴다 */
    private fun closeRecord(id: String) {
        val old = records.byCase(id) ?: return
        if (old.archiveVersion == null && !old.closed) { records.upsert(old.copy(closed = true, updatedAt = System.currentTimeMillis())); recordsRev++ }
    }

    private fun resetBody() { bodyEdits = BodyEdits(); bodySentSignature = ""; preKtas = null }

    /** 외상 도해에서 고친 것을 한 번에 병원으로 — 부위는 증상(injuryStatus) 칸, 처치는 추가 정보 한 줄(아이패드 BodyInjuryCard.send와 같다) */
    fun sendBodyEdits(): Boolean {
        val e = bodyEdits
        // 증상 칸 = 통화에서 온 것 중 빼지 않은 것 + 구급대원이 찍은 부위
        val kept = (patient?.injuryStatus ?: emptyList()).filter { text ->
            val marks = InjuryMapper.marks(text)
            marks.isEmpty() || !marks.all { it in e.removed }
        }
        if (!sendPatientOverride(null, kept + e.addedLines, null, null, null)) return false
        if (e.careLines.isNotEmpty()) sendExtraNote("[처치] " + e.careLines.joinToString(" · "))
        bodySentSignature = e.signature
        return true
    }

    /** 통화 요약 확인·수정 — 바뀐 칸만 담아 보낸다. 순위 칸(예상 병명·KTAS·필요 진료과)이 바뀌면 hub가 다시 매칭한다 */
    fun sendPatientOverride(
        expectedDiagnosis: String?, injuryStatus: List<String>?, ktasLevel: Int?, requiredDepartment: String?, chiefComplaint: String?,
    ): Boolean {
        if (paused) { show("현재 시연 일시정지 중입니다."); return false }
        val id = result?.caseId ?: caseId
        if (id == null) { show("진행 중인 사건이 없어 보내지 못했습니다."); return false }
        val msg = PatientOverrideMessage(id, isoNow(), expectedDiagnosis, injuryStatus, ktasLevel, requiredDepartment, chiefComplaint)
        if (!sendToHub(hubJson.encodeToJsonElement(PatientOverrideMessage.serializer(), msg))) {
            show("hub에 연결되지 않아 보내지 못했습니다."); return false
        }
        val changed = listOf(expectedDiagnosis, injuryStatus, ktasLevel, requiredDepartment, chiefComplaint).any { it != null }
        show(if (changed) "수정한 내용을 병원에 전달했습니다." else "통화 요약을 확인했습니다.")
        return true
    }

    // ── 영구 기록 동기화 (변경 순번 / 재접속 / 오프라인 수정 대기열) ──

    fun syncRecords() {
        val apid = apid ?: return
        val socket = ambulance ?: return
        if (!socket.isOpen) return
        val token = recordAccess.token(apid)
        if (token.isEmpty()) { recordSyncStatus = "설정에 구급차별 기록 동기화 키를 입력해 주세요."; return }
        recordRequest?.let { if (System.currentTimeMillis() - it.second < 20_000) return }
        // 기존 설치에만 있던 기록은 20개씩 이관한다. 서버 기록이 있으면 서버 값을 유지한다.
        val legacy = records.legacyRecords()
        val pending = records.pending.firstOrNull()
        val id: String
        val element = when {
            legacy.isNotEmpty() -> {
                id = UUID.randomUUID().toString()
                hubJson.encodeToJsonElement(RecordImportRequest.serializer(), RecordImportRequest(id, token, legacy))
            }
            handoverConflict == null && pending != null -> {
                id = pending.requestId
                hubJson.encodeToJsonElement(RecordHandoverRequest.serializer(), RecordHandoverRequest(pending, token))
            }
            else -> {
                id = UUID.randomUUID().toString()
                val cursor = records.cursor
                hubJson.encodeToJsonElement(RecordSyncRequest.serializer(), RecordSyncRequest(id, token, cursor.cursor, cursor.epoch))
            }
        }
        if (socket.send(element)) { recordRequest = id to System.currentTimeMillis(); recordSyncStatus = "기록 동기화 중…" }
        else { recordRequest = null; recordSyncStatus = "연결되면 기록 동기화를 재시도합니다." }
    }

    private fun applyArchived(record: CaseRecord): Boolean {
        if (record.apid != apid) return false
        // 재전송된 쓰기 영수증/페이지가 더 최신인 로컬 서버 사본을 뒤로 돌리지 않는다.
        val old = records.byCase(record.caseId)
        if (old != null && old.archiveEpoch == record.archiveEpoch && (old.archiveVersion ?: 0) > (record.archiveVersion ?: 0)) return true
        if (!records.upsert(record)) return false
        if (records.pending.none { it.caseId == record.caseId } && !caseEdits.ownsCase(record.caseId)) {
            settings.saveHandoverEdits(record.caseId, record.handoverEdits ?: emptyMap())
        }
        recordsRev++
        return true
    }

    private fun handleRecordReply(type: String, text: String) {
        val reply = runCatching { hubJson.decodeFromString(RecordSyncReply.serializer(), text) }.getOrNull() ?: return
        val requestId = reply.requestId ?: return
        if (recordRequest?.first != requestId) return
        recordRequest = null
        if (type == "record_error") {
            recordSyncStatus = if (reply.error == "unauthorized") "기록 동기화 키 또는 구급차 ID를 확인해 주세요." else "기록 동기화 실패 — 다음 연결 때 다시 시도합니다."
            return
        }
        if (reply.apid != apid) return
        val record = reply.record
        if (type == "record_handover_result" && record != null) {
            if (reply.conflict == true) {
                handoverConflict = record
                applyArchived(record)
                recordSyncStatus = "다른 기기에서 인계확인서를 수정했습니다. 저장할 내용을 선택해 주세요."
                return
            }
            val remaining = records.pending.filter { it.requestId != requestId }.map { p ->
                if (p.caseId == record.caseId) p.copy(revision = record.handoverRevision ?: 0) else p
            }
            if (!records.savePending(remaining) || !applyArchived(record)) { recordSyncStatus = "기기 저장 공간을 확인해 주세요."; return }
        } else {
            for (r in reply.records ?: emptyList()) {
                if (!applyArchived(r)) { recordSyncStatus = "기기 저장 공간을 확인해 주세요."; return }
            }
            if (type == "record_sync_result") {
                val epoch = reply.epoch
                val cursor = reply.cursor
                if (epoch == null || cursor == null || !records.saveCursor(RecordStore.Cursor(epoch, cursor))) {
                    recordSyncStatus = "기록 동기화 위치를 저장하지 못했습니다."; return
                }
            }
        }
        if (reply.hasMore == true || type != "record_sync_result") syncRecords()
        else recordSyncStatus = if (handoverConflict == null) "서버 기록과 동기화됨" else "인계확인서 수정 충돌 확인이 필요합니다."
    }

    fun resolveHandover(useMine: Boolean) {
        val conflict = handoverConflict ?: return
        val mine = records.pending.lastOrNull { it.caseId == conflict.caseId }
        val outbox = records.pending.filter { it.caseId != conflict.caseId }.toMutableList()
        if (useMine && mine != null) outbox.add(PendingHandover(conflict.caseId, conflict.handoverRevision ?: 0, mine.edits))
        if (!records.savePending(outbox)) return
        if (!useMine) settings.saveHandoverEdits(conflict.caseId, conflict.handoverEdits ?: emptyMap())
        handoverConflict = null
        syncRecords()
    }

    // ── 같은 구급대의 휴대폰·태블릿 수동 수정 동기화 ──

    private fun syncLiveCase() {
        caseEdits.onUpdate = {
            caseId?.let { id ->
                settings.saveHandoverEdits(id, caseEdits.handover)
                applySharedBody()
                recordsRev++
            }
        }
        caseEdits.activate(caseId, apid, settings.hubBase, settings.handoverEdits(caseId)) { ambulance?.send(it) == true }
    }

    fun shareHandover(caseId: String, draft: Map<String, String>, auto: Map<String, String>, touched: Set<String>, base: Map<String, String>) {
        val changes = HashMap<String, String?>()
        for (id in touched) {
            val value = (draft[id] ?: "").trim()
            changes["h:$id"] = if (value == (auto[id] ?: "").trim()) null else value
        }
        if (!caseEdits.submit(caseId, changes, base)) show("사건이 변경되어 저장하지 못했습니다.")
    }

    fun shareBody(mark: BodyMark, base: Map<String, String>) {
        val id = caseId ?: return
        val key = "b:" + mark.region.label + ":" + when (mark.side) { BodySide.LEFT -> "좌"; BodySide.RIGHT -> "우"; BodySide.UNKNOWN -> "" }
        val value = SharedBodyValue(mark in bodyEdits.added, mark in bodyEdits.removed, bodyEdits.cares[mark] ?: emptyList())
        caseEdits.submit(id, mapOf(key to hubJson.encodeToString(SharedBodyValue.serializer(), value)), base)
    }

    private fun applySharedBody() {
        var added = emptySet<BodyMark>(); var removed = emptySet<BodyMark>(); var cares = emptyMap<BodyMark, List<String>>()
        for ((key, text) in caseEdits.fields) {
            if (!key.startsWith("b:")) continue
            val parts = key.split(":")
            if (parts.size != 3) continue
            val region = BodyRegion.entries.firstOrNull { it.label == parts[1] } ?: continue
            val value = runCatching { hubJson.decodeFromString(SharedBodyValue.serializer(), text) }.getOrNull() ?: continue
            val mark = BodyMark(region, when (parts[2]) { "좌" -> BodySide.LEFT; "우" -> BodySide.RIGHT; else -> BodySide.UNKNOWN })
            if (value.added) added = added + mark
            if (value.removed) removed = removed + mark
            if (value.cares.isNotEmpty()) cares = cares + (mark to value.cares)
        }
        bodyEdits = BodyEdits(added, removed, cares)
    }
}
