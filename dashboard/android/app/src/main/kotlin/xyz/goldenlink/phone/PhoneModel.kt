package xyz.goldenlink.phone

import android.app.Application
import android.content.pm.PackageManager
import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableLongStateOf
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
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import okhttp3.Request
import xyz.goldenlink.core.AccessCode
import xyz.goldenlink.core.ActionRefused
import xyz.goldenlink.core.AmbulancePhase
import xyz.goldenlink.core.AmbulanceSim
import xyz.goldenlink.core.ApprovalAction
import xyz.goldenlink.core.DispatcherNotice
import xyz.goldenlink.core.DispatcherPending
import xyz.goldenlink.core.BodyCare
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
import xyz.goldenlink.core.CallDecisionMessage
import xyz.goldenlink.core.CallError
import xyz.goldenlink.core.CallHangupMessage
import xyz.goldenlink.core.CallInviteMessage
import xyz.goldenlink.core.CallLabels
import xyz.goldenlink.core.CallSignalMessage
import xyz.goldenlink.core.CallState
import xyz.goldenlink.core.MediaReadyMessage
import xyz.goldenlink.core.RtcIceIn
import xyz.goldenlink.core.RtcIceMessage
import xyz.goldenlink.core.RtcSdpIn
import xyz.goldenlink.core.RtcSdpMessage
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
 * hub 출동 상태(ambulance_phase.caseId)를 그대로 쓴다. 통화는 [취소]와 [통화 종료]([전송])로 끝난다 — 눌러야만 음성을
 * 처리한다. 현장 첫 통화는 끝낸 뒤 [이송확정](통화 병원으로 출발, 요약은 그 병원에만)/[이송불가](요약을 존 전체에 동시 전달)를 고른다(2026-11-04).
 * 현장 첫 통화 뒤에도 환자 상태가 바뀌면 추가 통화를 할 수 있고, 새 요약은 환자 정보에 덧붙는다(바로 반영).
 */
class PhoneModel(app: Application) : AndroidViewModel(app) {
    val settings = Settings(app)

    // 연결
    var connection by mutableStateOf(HubSocket.State.CONNECTING)
    var apid by mutableStateOf<String?>(null)  // 접근 코드로 정한 소속 구급차
    /** 접근 코드를 아직 입력하지 않았다 — 앱은 코드 입력 화면만 보인다(아이폰과 같음) */
    var accessRequired by mutableStateOf(settings.apid.isBlank() && settings.hospitalId.isBlank())
    /** 병원 접근 코드(H-…)로 들어온 병원 모드 — 비어 있지 않으면 구급대 화면 대신 수신 전화 화면(HospitalModel)을 쓴다 */
    var hospitalId by mutableStateOf(settings.hospitalId)
    var accessChecking by mutableStateOf(false)
    var accessError by mutableStateOf<String?>(null)
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
    // caseId -> 관제 판단 대기의 원인 병원 이름(2026-11-04). 대기 중엔 이송 승인 대신 상황실이 병원을 지정한다
    var dispatcherPending by mutableStateOf<Map<String, String>>(emptyMap())
    var incidentAddress by mutableStateOf<String?>(null)   // 인계확인서 "출발지 주소" — hub가 좌표를 주소로 바꿔 준다
    /** 통화 화면 지도의 병원 핀 좌표 — hub map_overview(병원 목록)에서 hospitalId로 찾는다. 현장 후보 메시지엔 좌표가 없다 */
    val hospitalGps = mutableStateMapOf<String, GPS>()
    /** 통화 요약이 병원들에 전달되는 모습을 지도에서 보여 주는 중 — 끝나면(또는 눌러서 건너뛰면) 환자 정보 탭으로 넘어간다 */
    /** 전화를 걸었다가 받지 않아 취소한 병원(사건별) — 병원 리스트 맨 아래로 내린다. hub의 미응답 이력(callAttempts)이 늦게 와도 바로 반영되게 앱에서도 기억한다 */
    val skippedHospitals = mutableStateMapOf<String, Set<String>>()
    /** 통화가 취소·미응답으로 끝나면 현장 지도의 병원 리스트 시트를 펼친 채로 돌아온다(바로 전 화면) */
    var reopenList by mutableStateOf(false)
    class DeliveryShow(val caseId: String, val durationMs: Long, val reduceMotion: Boolean) {
        /** 지도가 준비돼 연출이 실제로 시작된 시각(0이면 아직) — 지도를 불러오는 동안 연출 시간이 흘러가 버리지 않게 화면이 채운다 */
        var readyAt by mutableLongStateOf(0L)
    }
    var deliveryShow by mutableStateOf<DeliveryShow?>(null)
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
        /** 현장 첫 통화를 끝낸 뒤 구급대원의 판단(2026-11-04): null = 아직 고르지 않음, "confirm" = 통화 병원으로 이송 확정, "reject" = 이송불가(존 전체 전달) */
        val decision: String? = null,
        val decidedAt: Long? = null,
        /** 실제 통화(WebRTC, 2026-11-04) — 병원 앱과 음성을 직접 주고받는다. 이 통화엔 STT·요약·이송 판단이 없다. callId는 hub 통화 식별자 */
        val webrtc: Boolean = false,
        val callId: String? = null,
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
    private var mapSocket: HubSocket? = null
    private var ambulance: HubSocket? = null
    private var noticeJob: Job? = null
    private var tickJob: Job? = null
    private var callRequestId: String? = null  // 지금 보낸 전화 연결 요청 — hub의 call_status가 내 요청에 대한 것인지 가린다

    // 실제 통화(WebRTC, 2026-11-04)의 연결·오디오 — init { start() }가 stop()을 부르므로 init보다 먼저 선언해야 한다(Kotlin은 선언 순서대로 초기화)
    private var rtc: RtcSession? = null
    private val callAudio = CallAudio(app)
    private var rtcNegotiation = 1

    init { start() }

    fun start() {
        stop()
        val id = settings.apid.trim().uppercase()
        if (id.isEmpty()) return  // 접근 코드를 입력하기 전엔 어디에도 연결하지 않는다
        follow(id)
        // 병원 좌표(map_overview)만 받는 읽기 전용 소켓 — 다른 메시지는 거른다(구급차 위치가 초당 전 차량분 오므로 해석하지 않는다)
        mapSocket = HubSocket(settings.wsUrl, "monitor", "phone-map", { t, d -> if (t == "map_overview") handle(t, d) }, { })
        // 15초마다: 기록 동기화 재시도 · 기기 간 수정 재전송 · (현장에서 아직 전화 전이면) hub 추천 갱신(다른 사건의 연락·이송 반영)
        tickJob = viewModelScope.launch {
            while (true) {
                delay(15_000)
                syncRecords()
                caseEdits.tick()
                if (onScene && call == null && !sent) requestFirstCall(quiet = true)
            }
        }
        // 모델이 없으면 조용히 서버 음성 인식으로 동작한다(아이폰과 같은 2026-10-05 요청)
        if (settings.onDevice) viewModelScope.launch { withContext(modelDispatcher) { models.load() } }
    }

    fun stop() {
        releaseRealCall()  // 실제 통화 중이던 마이크·연결을 먼저 정리한다
        tickJob?.cancel(); tickJob = null; recordRequest = null
        mapSocket?.close(); mapSocket = null
        ambulance?.close(); ambulance = null
        apid = null
        records.configure(null); recordsRev++
    }

    override fun onCleared() { stop() }

    /** 접근 코드를 hub `/identity`로 확인하고 맞으면 이 구급대에 연결한다 — 아이폰 AccessCodeEntry와 같은 규칙 */
    fun submitAccess(code: String, hub: String) {
        if (accessChecking) return
        // 구급대 코드(P-/A-)는 구급대 화면, 병원 코드(H-)는 수신 전화를 받는 병원 모드(2026-11-04)
        val hospitalCode = AccessCode.hospitalId(code)
        val id = hospitalCode ?: AccessCode.ambulanceId(code)
        val role = if (hospitalCode != null) "hospital" else "ambulance"
        if (id == null) { accessError = "P-SEL0111(구급대) 또는 H-A1100017(병원) 형식의 접근 코드를 입력하세요."; return }
        val base = hub.trim().trimEnd('/')
        if (!(base.startsWith("http://") || base.startsWith("https://")) || base.substringAfter("://").isBlank()) {
            accessError = "서버 주소를 확인하세요."; return
        }
        accessChecking = true; accessError = null
        viewModelScope.launch {
            val failure = withContext(Dispatchers.IO) {
                runCatching {
                    HubSocket.client.newCall(Request.Builder().url("$base/identity?role=$role&id=$id").build()).execute().use { r ->
                        val what = if (role == "hospital") "병원" else "구급대"
                        if (!r.isSuccessful) "서버에서 ${what}을 확인하지 못했습니다."
                        else {
                            val o = hubJson.parseToJsonElement(r.body!!.string()).jsonObject
                            val known = (o["known"] as? JsonPrimitive)?.booleanOrNull == true
                            if (known && (o["id"] as? JsonPrimitive)?.contentOrNull == id) null else "등록되지 않은 $what 코드입니다."
                        }
                    }
                }.getOrElse { "서버에 연결하지 못했습니다. 네트워크와 서버 주소를 확인한 뒤 다시 시도하세요." }
            }
            accessChecking = false
            accessError = failure
            if (failure == null) {
                settings.hubBase = base
                settings.realCall = true
                // 두 역할은 서로 배타적이다 — 구급대 코드를 넣으면 병원 모드가, 병원 코드를 넣으면 구급대 설정이 비워진다
                settings.apid = if (role == "ambulance") id else ""
                settings.hospitalId = if (role == "hospital") id else ""
                hospitalId = settings.hospitalId
                accessRequired = false
                start()  // 병원 모드면 소속 구급대가 없어 구급대 연결은 만들지 않는다(HospitalModel이 따로 접속한다)
            }
        }
    }

    /** 설정의 [접근 코드 변경] — 연결을 끊고 코드 입력 화면으로 돌아간다 */
    fun resetAccess() {
        stop()
        settings.apid = ""
        settings.hospitalId = ""
        hospitalId = ""
        accessError = null
        accessRequired = true
    }

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
        deliveryShow = null
        trackedSim = null; phaseTimes.clear(); incidentAddress = null; pendingConfirmId = null; resetBody()
        if (newApid == null) return
        ambulance = HubSocket(settings.wsUrl, "ambulance", newApid, { t, d -> handle(t, d) }, { s -> onConnectionState(s) })
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
    /** 받지 않은 병원인가 — hub의 미응답 이력 또는 방금 이 앱에서 취소한 병원 */
    fun isSkipped(h: SceneCandidate): Boolean =
        caseId?.let { c -> h.hospitalId in (skippedHospitals[c] ?: emptySet()) || h.hospitalId in (scenes[c]?.callAttempts ?: emptyList()) } == true
    /** 병원 리스트 — hub 추천 순서 그대로, 받지 않은 병원만 맨 아래로(순서는 유지) */
    val sceneHospitals: List<SceneCandidate>
        get() = (scene?.hospitals ?: emptyList()).let { all -> all.filterNot(::isSkipped) + all.filter(::isSkipped) }

    private fun markSkipped(caseId: String, hospitalId: String) {
        skippedHospitals[caseId] = (skippedHospitals[caseId] ?: emptySet()) + hospitalId
        reopenList = true
    }
    val status: CallStatus? get() = caseId?.let { callStatus[it] }
    val phase: AmbulancePhase get() = mySim?.phaseEnum ?: AmbulancePhase.idle
    val onScene: Boolean get() = simOn && phase == AmbulancePhase.on_scene && caseId != null
    /** 이송 중·재선택 대기 — 목적지(또는 다른) 병원과 추가 통화를 할 수 있는 단계 */
    val inTransport: Boolean get() = simOn && caseId != null && (phase == AmbulancePhase.transporting || phase == AmbulancePhase.rerouting)
    /** 운영자의 시연 일시정지(조작 잠금). 추가 통화로 이동만 멈춘 경우("call")는 통화·전송을 막지 않는다 */
    val paused: Boolean get() = mySim?.paused == true && mySim?.pauseReason != "call"
    /** 지금 사건이 관제 판단 대기면 원인 병원 이름(없으면 "1순위 병원"), 아니면 null */
    val waitingDispatcher: String? get() = (result?.caseId ?: caseId)?.let { dispatcherPending[it] }
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

    private fun handle(type: String, text: String) {
        runCatching {
            when (type) {
                "live_case_state", "live_case_error" -> caseEdits.accept(text)
                "records_changed" -> syncRecords()
                "record_sync_result", "record_import_result", "record_handover_result", "record_error" -> handleRecordReply(type, text)
                "map_overview" -> hubJson.decodeFromString(MapOverview.serializer(), text).hospitals.forEach { hospitalGps[it.hospitalId] = it.gps }
                "identity_info" -> {
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
                }
                // 실제 통화(WebRTC) — 지금 통화(callId)에 대한 메시지만 따른다
                "call_state" -> onRealCallState(hubJson.decodeFromString(CallState.serializer(), text))
                "rtc_answer" -> hubJson.decodeFromString(RtcSdpIn.serializer(), text).let { a ->
                    if (call?.webrtc == true && call?.callId == a.callId) rtc?.applyAnswer(a.sdp)
                }
                "rtc_ice" -> hubJson.decodeFromString(RtcIceIn.serializer(), text).let { ice ->
                    if (call?.webrtc == true && call?.callId == ice.callId) rtc?.addRemoteIce(ice.candidate)
                }
                "call_error" -> hubJson.decodeFromString(CallError.serializer(), text).let { e ->
                    if (call?.webrtc == true && call?.callId == e.callId) endRealCall("통화를 처리하지 못했습니다")
                }
                "call_connection_error" -> if (call?.phase == LocalCall.Phase.CONNECTING) { call = null; callRequestId = null; show("현재 단계에서는 전화할 수 없습니다") }
                "first_call_error" -> show("첫 통화 추천 요청을 처리하지 못했습니다. 현재 사건을 확인해 주세요.")
                "scene_candidates" -> hubJson.decodeFromString(SceneCandidates.serializer(), text).let {
                    scenes[it.caseId] = it
                    Log.i("GoldenLink", "scene_candidates case=${it.caseId} 내 사건=${it.caseId == caseId} 병원=${it.hospitals.size}")
                }
                "scene_input_mode" -> hubJson.decodeFromString(SceneInputMode.serializer(), text).let {
                    if (it.stage == "transport") transportInputMode[it.caseId] = it.mode else sceneInputMode[it.caseId] = it.mode
                }
                "call_status" -> hubJson.decodeFromString(CallStatus.serializer(), text).let { s ->
                    callStatus[s.caseId] = s
                    val c = call
                    // 내 전화 요청에 대한 상태만 따른다 — 관제가 받으면(calling) 그때 녹음을 시작한다
                    if (c != null && s.requestId != null && s.requestId == callRequestId && s.caseId == c.caseId && s.hospitalId == c.hospitalId) {
                        if (s.state == "calling") beginConnectedCall()
                        if (s.state == "no_answer" || s.state == "cancelled") {
                            markSkipped(c.caseId, c.hospitalId)
                            session?.cancel(); session = null; call = null; callRequestId = null
                            show(if (s.state == "no_answer") "전화 미응답 — 다음 추천 병원을 확인하세요" else "전화 요청이 취소됐습니다")
                        }
                    }
                }
                "call_transcript" -> {
                    val l = hubJson.decodeFromString(CallTranscriptLine.serializer(), text)
                    val c = l.caseId
                    if (c != null) hubTranscripts[c] = (hubTranscripts[c] ?: emptyList()) + l
                }
                "match_result" -> {
                    val m = hubJson.decodeFromString(MatchResult.serializer(), text)
                    if (apid != null && m.apid != null && m.apid != apid) return@runCatching  // 다른 구급차 사건
                    // 자동 전환: 이 사건의 매칭 결과가 처음 오면(=음성 요약 도착, 추가 통화 회차 제외) 환자 정보로,
                    // 이송 시작은 ambulance_phase에서 통화 지도로 전환한다. 연결 직후 따라잡기(지난 결과)는 전환하지 않는다
                    val firstForCase = results[m.caseId] == null
                    results[m.caseId] = m
                    val settled = System.currentTimeMillis() - liveSince > 3000
                    // 이 기기에서 건 통화의 요약은 아래 delivered 분기에서 연출한다(여기서 먼저 넘기지 않는다).
                    // 시연 콘솔 등 다른 곳에서 들어온 요약도 같은 전달 연출을 보여 준 뒤 환자 정보로 넘어간다
                    if (settled && firstForCase && (m.patientInfo?.callRound ?: 1) <= 1 && phase != AmbulancePhase.transporting && call?.caseId != m.caseId) startDeliveryShow(m.caseId)
                    val confirmedId = m.hospitals.firstOrNull { it.status == "confirmed" }?.hospitalId
                    if (pendingConfirmId != null && pendingConfirmId == confirmedId) pendingConfirmId = null
                    sentCount[m.caseId] = m.hospitals.size
                    matchVersion[m.caseId] = (matchVersion[m.caseId] ?: 0) + 1
                    destinations[m.caseId] = m.hospitals.firstOrNull { it.status == "confirmed" }
                    snapshotCase(m.caseId)
                    // 이번 통화의 새 요약이 반영되면 성공 확인 화면을 거치지 않고 환자 정보로.
                    // 병원 응답·주기 갱신만으로는 callRound가 늘지 않으므로 통화 처리를 닫지 않는다.
                    if (call?.caseId == m.caseId && delivered) {
                        // 이송확정이면 요약이 통화 병원 한 곳에만 갔고 구급차가 바로 출발한다 — 존 전체 전달 연출 없이 통화 지도(이송)로
                        val confirmed = call?.decision == "confirm"
                        dismissEnded()
                        if (confirmed) tab = Tab.CALL else startDeliveryShow(m.caseId)
                    }
                }
                "action_refused" -> {
                    val r = hubJson.decodeFromString(ActionRefused.serializer(), text)
                    pendingConfirmId = null
                    show(when (r.reason) {
                        "paused" -> "현재 시연 일시정지 중입니다."
                        "template_mode" -> "콘솔이 정해진 상황 선택 중이라 전화할 수 없습니다."
                        "already_arrived" -> "이미 병원에 도착해 이송 병원을 바꿀 수 없습니다. 현재 병원의 수용 불가 처리 후 다시 선택해 주세요."
                        "confirm_failed" -> "이송 확정을 처리하지 못해 존 안 병원 전체에 전달했습니다. 구급차 대시보드를 확인해 주세요."
                        "no_pending_decision" -> "이 통화는 이미 처리됐습니다."
                        "dispatcher_pending" -> DISPATCHER_WAIT_TEXT
                        else -> "지금은 통화를 시작할 수 없습니다."
                    })
                    if (call?.phase == LocalCall.Phase.CONNECTING && call?.webrtc != true) call = null  // 실제 통화는 call_state(ended)로 정리한다
                    if (r.reason == "no_pending_decision" && call?.phase == LocalCall.Phase.ENDED) { call = null; session = null }
                }
                "case_closed" -> forget(hubJson.decodeFromString(CaseClosed.serializer(), text).caseId)
                // 관제 판단 대기(2026-11-04) — 여러 환자가 한 병원에 몰려 상황실이 병원을 정한다. 그동안 이송 승인은 막힌다
                "dispatcher_pending" -> {
                    val p = hubJson.decodeFromString(DispatcherPending.serializer(), text)
                    dispatcherPending = if (p.pending) dispatcherPending + (p.caseId to (p.hospitalName ?: "1순위 병원"))
                        else dispatcherPending - p.caseId
                    if (p.pending) show("관제 판단 대기 — ${p.hospitalName ?: "1순위 병원"}에 여러 환자가 몰려 상황실이 병원을 지정합니다.")
                }
                "dispatcher_notice" -> {
                    val n = hubJson.decodeFromString(DispatcherNotice.serializer(), text)
                    dispatcherPending = dispatcherPending - n.caseId
                    if (n.kind == "transport_confirmed") show("상황실이 ${n.hospitalName ?: "병원"}(으)로 이송 병원을 지정했습니다.")
                }
                "case_sync" -> {
                    val ids = hubJson.decodeFromString(CaseSync.serializer(), text).caseIds.toSet()
                    for (id in (scenes.keys + sentCount.keys + results.keys) - ids) forget(id)
                }
                else -> Unit  // 모르는 type은 버린다
            }
        }.onFailure { Log.w("GoldenLink", "hub 메시지($type) 처리 실패", it) }
        syncLiveCase()
    }

    private fun forget(caseId: String) {
        closeRecord(caseId)
        results.remove(caseId)
        dispatcherPending = dispatcherPending - caseId
        scenes.remove(caseId); callStatus.remove(caseId); hubTranscripts.remove(caseId); sentCount.remove(caseId)
        matchVersion.remove(caseId); destinations.remove(caseId); sceneInputMode.remove(caseId)
        transportInputMode.remove(caseId)
        if (deliveryShow?.caseId == caseId) deliveryShow = null
        skippedHospitals.remove(caseId)
        if (call?.caseId == caseId && (session == null || call?.phase == LocalCall.Phase.ENDED)) { call = null; session = null }
    }

    /** 화면 위 안내를 잠깐(2.5초) 띄운다 */
    fun show(text: String) {
        notice = text
        noticeJob?.cancel()
        noticeJob = viewModelScope.launch { delay(2500); notice = null }
    }

    // ── 통화 ──

    /** 첫 통화 추천을 hub에 다시 요청한다 — 다른 구급차의 연락·이송을 반영한 후보를 추천순으로 다시 보낸다(scene_candidates) */
    fun requestFirstCall(quiet: Boolean = false) {
        val id = caseId ?: return
        Log.i("GoldenLink", "first_call_request case=$id 소켓연결=${ambulance?.isOpen}")
        if (!sendToHub(hubJson.encodeToJsonElement(FirstCallRequest.serializer(), FirstCallRequest(id))) && !quiet) {
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
        if (call?.webrtc == true) { hangupRealCall(); return }  // 실제 통화는 시연 연출의 "미응답 다음 병원" 규칙이 없다 — 발신을 취소한다
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
        if (settings.realCall) { startRealCall(caseId, hospitalId, name); return }
        call = LocalCall(caseId, hospitalId, name, sent, LocalCall.Phase.CONNECTING, System.currentTimeMillis())
        callRequestId = UUID.randomUUID().toString()
        if (!connectionAction("request")) {
            call = null; callRequestId = null
            error = "hub 연결이 끊겨 전화 요청을 보내지 못했습니다."
        }
    }

    // ── 실제 통화(WebRTC, 2026-11-04) ──
    // 설정의 [실제 통화]가 켜져 있으면 병원을 눌러 거는 전화가 시연 연출이 아니라 병원 앱(병원 모드)과의 실제 음성 통화가 된다.
    // 흐름: call_invite → (병원이 받으면) hub가 connecting → 이쪽이 offer를 만들어 보냄 → answer·ICE 교환 → 양쪽 media_ready → active.
    // 이 통화엔 STT·요약·이송 판단이 없다(다음 단계). 모든 hub 메시지는 지금 통화의 callId와 같을 때만 따른다.

    private fun startRealCall(caseId: String, hospitalId: String, name: String) {
        val callId = UUID.randomUUID().toString()
        call = LocalCall(caseId, hospitalId, name, sent, LocalCall.Phase.CONNECTING, System.currentTimeMillis(), webrtc = true, callId = callId)
        if (!sendToHub(hubJson.encodeToJsonElement(CallInviteMessage.serializer(),
                CallInviteMessage(callId, caseId, hospitalId, settings.deviceId)))) {
            call = null
            error = "hub 연결이 끊겨 전화를 걸지 못했습니다."
        }
    }

    private fun onRealCallState(s: CallState) {
        val c = call ?: return
        if (!c.webrtc || c.callId != s.callId) return
        when (s.state) {
            "connecting" -> {
                if (rtc != null) return  // 같은 상태가 다시 오면(재접속 동기화) 연결을 새로 만들지 않는다
                callAudio.start()
                val session = runCatching { RtcSession(getApplication(), s.iceServers ?: emptyList(), realCallListener(s.callId)) }.getOrElse {
                    Log.w("GoldenLink", "WebRTC 연결 준비 실패", it)
                    sendToHub(hubJson.encodeToJsonElement(CallHangupMessage.serializer(), CallHangupMessage(s.callId)))
                    endRealCall("통화 연결을 준비하지 못했습니다")
                    return
                }
                rtc = session
                session.createOffer { sdp ->
                    viewModelScope.launch {
                        if (call?.callId == s.callId) sendToHub(hubJson.encodeToJsonElement(RtcSdpMessage.serializer(),
                            RtcSdpMessage("rtc_offer", s.callId, sdp, rtcNegotiation)))
                    }
                }
            }
            "active" -> call = c.copy(phase = LocalCall.Phase.IN_CALL, startedAt = System.currentTimeMillis())
            "ended" -> endRealCall(CallLabels.endText(s.reason, s.detail))
        }
    }

    /** WebRTC 스레드의 콜백을 메인으로 옮기고, 지금 통화(callId)에 대한 것만 따른다 */
    private fun realCallListener(callId: String) = object : RtcSession.Listener {
        override fun onLocalIce(candidate: kotlinx.serialization.json.JsonObject) {
            viewModelScope.launch {
                if (call?.callId == callId) sendToHub(hubJson.encodeToJsonElement(RtcIceMessage.serializer(), RtcIceMessage(callId, candidate, rtcNegotiation)))
            }
        }

        override fun onMediaReady() {
            viewModelScope.launch {
                if (call?.callId == callId) sendToHub(hubJson.encodeToJsonElement(MediaReadyMessage.serializer(), MediaReadyMessage(callId)))
            }
        }

        override fun onFailed(reason: String) {
            viewModelScope.launch {
                if (call?.callId != callId) return@launch
                sendToHub(hubJson.encodeToJsonElement(CallHangupMessage.serializer(), CallHangupMessage(callId)))
                endRealCall("통화 연결에 실패했습니다")
            }
        }
    }

    /** [취소]/[통화 종료] — 마이크·연결을 바로 끄고 hub에 알린다. hub 응답이 늦어도 마이크는 이미 꺼져 있다 */
    fun hangupRealCall() {
        val c = call ?: return
        val id = c.callId ?: return
        if (!c.webrtc) return
        sendToHub(hubJson.encodeToJsonElement(CallHangupMessage.serializer(), CallHangupMessage(id)))
        endRealCall(if (c.phase == LocalCall.Phase.CONNECTING) "발신을 취소했습니다" else "통화를 종료했습니다")
    }

    /** 실제 통화의 자원을 정리하고 병원 목록으로 돌아간다. 여러 번 불러도 안전하다 */
    private fun endRealCall(message: String) {
        releaseRealCall()
        if (call?.webrtc == true) { call = null; reopenList = true }
        show(message)
    }

    private fun releaseRealCall() {
        rtc?.close(); rtc = null
        callAudio.stop()
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
            val notified = sendToHub(hubJson.encodeToJsonElement(CallSignalMessage.serializer(),
                CallSignalMessage("call_ended", apid, c.caseId, c.hospitalId, cancelled = true)))
            call = null; callRequestId = null
            error = "마이크를 시작하지 못했습니다: ${t.message}" + if (notified) "" else " (hub에 통화 취소를 전하지 못했습니다)"
            return
        }
        session = s
        call = call?.copy(phase = LocalCall.Phase.IN_CALL, startedAt = System.currentTimeMillis())
    }

    /** [취소] — 아무것도 전송하지 않는다. 녹음·인식을 버리고 hub에는 취소로 알려 "통화 중" 표시만 지운다 */
    fun cancelCall() {
        val c = call ?: return
        if (c.webrtc) { hangupRealCall(); return }  // 실제 통화: 받기 전엔 발신 취소, 통화 중엔 종료 — 같은 hangup이다
        val apid = apid
        if (c.phase == LocalCall.Phase.CONNECTING) {
            // 받지 않는 병원을 취소하는 것이라 미응답으로 알린다 — hub가 이 병원을 시도한 것으로 적고 다음 추천을 다시 보낸다
            if (!connectionAction("no_answer")) { show("hub 연결을 확인해 주세요"); return }
            markSkipped(c.caseId, c.hospitalId)
        }
        if (c.phase == LocalCall.Phase.IN_CALL && apid != null) {
            // 취소 신호가 못 가면 로컬 통화를 지우지 않는다 — 지우면 병원·관제 화면의 "통화 중"이 남는다
            if (!sendToHub(hubJson.encodeToJsonElement(CallSignalMessage.serializer(),
                    CallSignalMessage("call_ended", apid, c.caseId, c.hospitalId, cancelled = true)))) {
                show("hub 연결을 확인해 주세요. 통화 취소를 전하지 못했습니다."); return
            }
            session?.cancel()
        }
        if (c.phase != LocalCall.Phase.CONNECTING) reopenList = true
        call = null
        callRequestId = null
        session = null
        show("통화를 취소했습니다 — 전달하지 않았습니다")
    }

    /** [통화 종료](현장 첫 통화) / [전송](추가 통화) — 통화를 끝내고 이때만 음성을 처리(인식·구조화)한다.
     *  추가 통화는 바로 병원에 반영되고, 현장 첫 통화는 요약을 hub가 붙잡아 두었다가 구급대원이 [이송확정]/[이송불가]를 고르면 처리한다(2026-11-04) */
    fun sendCall() {
        val c = call ?: return
        if (c.webrtc) { hangupRealCall(); return }
        val apid = apid ?: return
        if (c.phase != LocalCall.Phase.IN_CALL) return
        if (paused) { show("현재 시연 일시정지 중입니다."); return }
        // 종료 신호가 hub에 못 가면 통화를 끝내지 않는다 — 그대로 두면 병원 화면엔 "통화 중"이 남고 요약만 따로 실패한다
        if (!sendToHub(hubJson.encodeToJsonElement(CallSignalMessage.serializer(),
                CallSignalMessage("call_ended", apid, c.caseId, c.hospitalId, awaitDecision = if (c.followup) null else true)))) {
            show("hub 연결을 확인해 주세요. 통화를 종료하지 못했습니다."); return
        }
        val before = results[c.caseId]
        call = c.copy(phase = LocalCall.Phase.ENDED, endedAt = System.currentTimeMillis(), matchVersionAtSend = matchVersion[c.caseId] ?: 0,
            callRoundAtSend = before?.patientInfo?.callRound ?: if (before == null) 0 else 1)
        wantsExtraCall = false
        val s = session
        viewModelScope.launch { s?.finish() }
    }

    /** 요약이 반영되면 환자 정보로 바로 넘기지 않고, 현장 지도에서 병원들로 전달되는 연출을 먼저 보여 준다.
     *  현장이 아니거나(이송 중 추가 통화) 지도에 찍을 병원 좌표가 없으면 연출 없이 바로 넘어간다 */
    private fun startDeliveryShow(caseId: String) {
        val anyTarget = results[caseId]?.hospitals?.any { hospitalGps[it.hospitalId] != null } == true
        if (!onScene || mySim?.gps == null || !anyTarget || BuildConfig.KAKAO_NATIVE_APP_KEY.isBlank()) { tab = Tab.PATIENT; return }
        // 기기의 "애니메이션 제거" 설정이면 움직임 없이 병원이 켜진 상태만 잠깐 보여 준다
        val reduce = android.provider.Settings.Global.getFloat(getApplication<Application>().contentResolver,
            android.provider.Settings.Global.ANIMATOR_DURATION_SCALE, 1f) == 0f
        val show = DeliveryShow(caseId, if (reduce) 1200L else 2600L, reduce)
        deliveryShow = show
        tab = Tab.CALL
        // 화면이 바뀌어 연출이 멈춰도 여기서 반드시 끝낸다
        // 연출은 화면이 지도 준비 뒤 시계를 흘려 끝내지만, 지도가 끝내 준비되지 않아도 막히지 않게 여유를 두고 끝낸다
        viewModelScope.launch { delay(show.durationMs + 5_000); if (deliveryShow === show) finishDelivery() }
    }

    /** 연출이 끝났거나 구급대원이 눌러 건너뛰었다 — 환자 정보 탭으로 */
    fun finishDelivery() {
        if (deliveryShow == null) return
        deliveryShow = null
        tab = Tab.PATIENT
    }

    /** 통화를 끝낸 구급대원의 판단(2026-11-04) — [이송확정]: 통화한 병원으로 바로 출발(요약은 그 병원에만),
     *  [이송불가]: 요약을 존 안 다른 후보 병원 전체에 동시에 전달. 요약 정리가 끝나기 전에 눌러도 hub가 순서를 맞춘다 */
    fun decideTransport(confirm: Boolean) {
        val c = call ?: return
        if (c.phase != LocalCall.Phase.ENDED || c.followup || c.decision != null) return
        if (paused) { show("현재 시연 일시정지 중입니다."); return }
        val decision = if (confirm) "confirm" else "reject"
        if (!sendToHub(hubJson.encodeToJsonElement(CallDecisionMessage.serializer(), CallDecisionMessage(c.caseId, decision)))) {
            show("hub 연결을 확인해 주세요. 선택을 전하지 못했습니다."); return
        }
        call = c.copy(decision = decision, decidedAt = System.currentTimeMillis())
        if (confirm) pendingConfirmId = c.hospitalId  // 이송 탭도 "확정 요청 중"으로 보인다 — hub가 확정을 돌려주면 풀린다
    }

    /** 종료 화면의 [확인] — 다음 화면(전달됨 · 추가 통화)으로. 판단 없이 닫는 첫 통화(인식된 말이 없는 경우)는 hub의 판단 대기도 닫는다 */
    fun dismissEnded() {
        val c = call
        if (c != null && c.phase == LocalCall.Phase.ENDED && !c.followup && c.decision == null) {
            sendToHub(hubJson.encodeToJsonElement(CallDecisionMessage.serializer(), CallDecisionMessage(c.caseId, "cancel")))
        }
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
        if (waitingDispatcher != null) { show(DISPATCHER_WAIT_TEXT); return }
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

    private fun resetBody() { bodyEdits = BodyEdits(); bodySentSignature = "" }

    /** 외상 도해에서 고친 것을 한 번에 병원으로 — 부위는 증상(injuryStatus) 칸, 처치는 추가 정보 한 줄(아이패드 BodyInjuryCard.send와 같다) */
    fun sendBodyEdits(): Boolean {
        val e = bodyEdits
        // 증상 칸 = 통화에서 온 것 중 빼지 않은 것 + 구급대원이 찍은 부위
        val kept = (patient?.injuryStatus ?: emptyList()).filter { text ->
            val marks = InjuryMapper.marks(text)
            marks.isEmpty() || !marks.all { it in e.removed }
        }
        if (!sendPatientOverride(null, kept + e.addedLines, null, null, null)) return false
        // 처치 전송이 실패하면 "보냄"으로 표시하지 않는다 — 다시 누르면 둘 다 다시 간다
        if (e.careLines.isNotEmpty() && !sendExtraNote("[처치] " + e.careLines.joinToString(" · "))) return false
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
        val value = SharedBodyValue(mark in bodyEdits.added, mark in bodyEdits.removed, bodyEdits.fittedCares[mark] ?: emptyList())
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
            // 부위에 맞지 않는 처치(예전 값·다른 기기 값)는 받지 않는다
            val kept = value.cares.filter { BodyCare.fits(mark, it) }
            if (kept.isNotEmpty()) cares = cares + (mark to kept)
        }
        bodyEdits = BodyEdits(added, removed, cares)
    }
}

/** 관제 판단 대기 중 이송 승인을 누르거나 hub가 거부했을 때의 안내(2026-11-04) */
const val DISPATCHER_WAIT_TEXT = "관제 판단 대기 중입니다. 상황실이 이송 병원을 지정합니다."
