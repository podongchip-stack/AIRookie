package xyz.goldenlink.phone

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.serialization.Serializable
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.builtins.MapSerializer
import kotlinx.serialization.builtins.serializer
import kotlinx.serialization.json.JsonElement
import xyz.goldenlink.core.hubJson
import java.util.UUID

/**
 * 같은 구급대의 휴대폰·태블릿이 현재 사건의 수동 수정만 공유한다(아이폰·아이패드 shared/CaseEditSync.swift와 같은 규칙).
 * 통화 원문·서버 자동값은 별도 match_result로 받는다. 칸 id: 인계확인서 "h:<id>", 외상 도해 "b:<부위>:<좌우>".
 * 수정은 먼저 기기에 대기열로 보관하고 연결되면 hub로 보낸다. 같은 칸을 다른 기기가 먼저 고쳤으면 충돌로 멈추고 구급대원이 고른다.
 */
class CaseEditSync(private val store: KeyValueStore) {
    @Serializable
    data class Request(
        val caseId: String,
        var base: Map<String, String>,
        val changes: Map<String, String?>,
        var ticket: String? = null,
        var requestId: String = UUID.randomUUID().toString(),
        val type: String = "live_case_patch",
    )

    @Serializable
    private data class Get(val caseId: String, val ticket: String? = null, val type: String = "live_case_get")

    @Serializable
    data class State(
        val caseId: String,
        val apid: String? = null,
        val fields: Map<String, String>? = null,
        val version: Int? = null,
        val epoch: String? = null,
        val requestId: String? = null,
        val conflicts: List<String>? = null,
        val error: String? = null,
        val ticket: String? = null,
        val handoverRevision: Int? = null,
    )

    var fields by mutableStateOf<Map<String, String>>(emptyMap()); private set
    var status by mutableStateOf("기기 간 수정 동기화 대기"); private set
    var conflicts by mutableStateOf<List<String>>(emptyList()); private set
    var pendingCount by mutableIntStateOf(0); private set
    var onUpdate: (() -> Unit)? = null

    private var serverFields: Map<String, String> = emptyMap()
    private var queue = mutableListOf<Request>()
    private var active: String? = null
    private var unit: String? = null
    private var key = ""
    private var ready = false
    private var version = -1
    private var epoch = ""
    private var sent: String? = null
    private var lastAttempt = 0L
    private var sender: ((JsonElement) -> Boolean)? = null
    private var legacy: Map<String, String> = emptyMap()
    private var conflictState: State? = null

    private val mapSer = MapSerializer(String.serializer(), String.serializer())
    private val queueSer = ListSerializer(Request.serializer())

    val handover: Map<String, String> get() = fields.filterKeys { it.startsWith("h:") }.mapKeys { it.key.removePrefix("h:") }
    fun hasPending(caseId: String): Boolean = queue.any { it.caseId == caseId }
    fun ownsCase(caseId: String): Boolean = active == caseId

    private fun ticketOf(caseId: String) = store.getString("$key.ticket.$caseId")

    fun activate(caseId: String?, apid: String?, server: String, initialHandover: Map<String, String> = emptyMap(), send: (JsonElement) -> Boolean) {
        sender = send
        val scope = "goldenlink.live-edits.$server.${apid ?: ""}"
        if (key != scope) {
            key = scope
            queue = store.getString(key)?.let { runCatching { hubJson.decodeFromString(queueSer, it) }.getOrNull() }?.toMutableList() ?: mutableListOf()
        }
        if (active == caseId && unit == apid) return
        active = caseId; unit = apid; ready = false; version = -1; epoch = ""; sent = null
        legacy = initialHandover
        serverFields = caseId?.let { c -> store.getString("$key.cache.$c")?.let { runCatching { hubJson.decodeFromString(mapSer, it) }.getOrNull() } } ?: emptyMap()
        fields = serverFields; conflicts = emptyList(); project()
        refresh(); flush()
    }

    fun refresh() {
        val c = active ?: return
        lastAttempt = System.currentTimeMillis()
        if (sender?.invoke(hubJson.encodeToJsonElement(Get.serializer(), Get(c, ticketOf(c)))) != true) status = "연결되면 수정을 동기화합니다."
    }

    fun reconnect() { ready = false; sent = null; refresh(); flush() }

    fun tick() {
        if (System.currentTimeMillis() - lastAttempt <= 10_000) return
        sent = null
        if (conflicts.isEmpty()) flush()
        refresh()
    }

    /** 칸 수정을 대기열에 넣고 보낸다. 같은 칸을 되돌리는 null도 JSON에 명시적으로 남겨 자동값으로 초기화할 수 있다 */
    fun submit(caseId: String, changes: Map<String, String?>, base: Map<String, String>): Boolean {
        if (caseId != active || changes.isEmpty()) return changes.isEmpty()
        queue.add(Request(caseId, base, changes, ticketOf(caseId)))
        persist(); project(); flush()
        return true
    }

    fun accept(text: String) {
        val state = runCatching { hubJson.decodeFromString(State.serializer(), text) }.getOrNull() ?: return
        if (state.apid != null && state.apid != unit) return
        if (state.caseId != active && queue.none { it.requestId == state.requestId }) return
        if (state.error != null) {
            sent = null
            handleError(state)
            return
        }
        val values = state.fields ?: return
        state.ticket?.let { store.putString("$key.ticket.${state.caseId}", it) }
        // 종료 직전에 저장한 대기열의 영수증은 현재 사건 화면에 섞지 않는다.
        if (state.caseId != active) {
            val i = queue.indexOfFirst { it.requestId == state.requestId }
            if (state.requestId != null && i >= 0) {
                sent = null
                if (!state.conflicts.isNullOrEmpty()) {
                    conflicts = state.conflicts; conflictState = state
                    status = "이전 사건 수정이 다른 기기와 겹칩니다. 저장할 값을 선택하세요."
                } else { queue.removeAt(i); persist(); project(); flush() }
            }
            return
        }
        if (state.epoch != epoch || (state.version ?: -1) >= version) {
            serverFields = values; version = state.version ?: 0; epoch = state.epoch ?: ""
            store.putString("$key.cache.${state.caseId}", hubJson.encodeToString(mapSer, values))
        }
        ready = true
        val migrationKey = "$key.migrated.${state.caseId}"
        if (store.getString(migrationKey) != "1") {
            // 기존 기기의 수동 수정은 최초 한 번만 이관한다. 새 서버값이 있으면 그것이 우선이다.
            val queuedKeys = queue.filter { it.caseId == state.caseId }.flatMap { it.changes.keys }.toSet()
            val imported = legacy.filter { (state.handoverRevision ?: 0) == 0 && serverFields["h:" + it.key] == null && ("h:" + it.key) !in queuedKeys }
            if (imported.isNotEmpty()) {
                queue.add(Request(state.caseId, serverFields, imported.mapKeys { "h:" + it.key })); persist()
            }
            store.putString(migrationKey, "1")
        }
        val index = queue.indexOfFirst { it.requestId == state.requestId }
        if (state.requestId != null && index >= 0) {
            sent = null
            if (!state.conflicts.isNullOrEmpty()) {
                conflicts = state.conflicts; conflictState = state; status = "다른 기기에서 같은 칸을 수정했습니다. 저장할 값을 선택하세요."
            } else {
                val completed = queue.removeAt(index)
                // 같은 기기에서 연속 저장한 다음 수정의 기준만 전진한다.
                for (q in queue) if (q.caseId == state.caseId) {
                    val base = q.base.toMutableMap()
                    for ((k, v) in completed.changes) if (q.base[k] == completed.base[k]) { if (v == null) base.remove(k) else base[k] = v }
                    q.base = base
                }
                conflicts = emptyList(); persist()
            }
        }
        project()
        if (conflicts.isEmpty()) flush()
    }

    /** hub가 거절한 이유별로 다르게 다룬다 — 영영 안 들어갈 수정은 대기열에서 치워야 "동기화 실패" 안내가 계속 남지 않는다 */
    private fun handleError(state: State) {
        when (state.error) {
            "paused" -> status = "일시정지 해제 후 수정이 동기화됩니다."
            // 이 구급대 사건이 아니거나 끝난 사건(보관 증표도 없음) — 다시 보내도 같은 답이라 그 사건의 대기 수정을 지운다.
            // 지금 보는 사건이면 hub가 아직 사건을 모르는 것일 수 있어(재시작 직후 등) 지우지 않고 다시 시도한다
            "not_owner" -> if (state.caseId != active) {
                queue.removeAll { it.caseId == state.caseId }; persist(); project()
                status = "끝난 사건의 수정은 동기화할 수 없어 지웠습니다."
            } else status = "hub가 이 사건을 알지 못합니다 · 재연결하면 다시 시도합니다."
            // 형식이 맞지 않거나 너무 큰 수정 — 다시 보내도 같다
            "invalid_patch" -> {
                queue.removeAll { it.requestId == state.requestId }; persist(); project()
                status = "수정 내용이 형식에 맞지 않아 보내지 못했습니다(그 수정은 지웠습니다)."
            }
            "storage_unavailable" -> status = "hub 저장소 오류 · 잠시 뒤 다시 시도합니다."
            else -> status = "수정 동기화 실패(${state.error}) · 재연결 시 재시도합니다."
        }
    }

    fun resolve(useMine: Boolean) {
        val state = conflictState ?: return
        val i = queue.indexOfFirst { it.requestId == state.requestId }
        if (i < 0 || conflicts.isEmpty()) return
        if (useMine) { queue[i].base = state.fields ?: emptyMap(); queue[i].requestId = UUID.randomUUID().toString() }
        else queue.removeAt(i)
        sent = null; conflicts = emptyList(); conflictState = null; persist(); project(); flush()
    }

    private fun project() {
        pendingCount = queue.size
        val projected = (if (ready) serverFields else legacy.mapKeys { "h:" + it.key } + serverFields).toMutableMap()
        for (r in queue) if (r.caseId == active) for ((k, v) in r.changes) { if (v == null) projected.remove(k) else projected[k] = v }
        fields = projected
        if (conflicts.isEmpty()) status = when {
            queue.isNotEmpty() -> "수정 ${queue.size}건 저장됨 · 다른 기기에 전달 대기"
            ready -> "휴대폰·태블릿 수정 동기화됨"
            else -> "기기 간 수정 동기화 대기"
        }
        if (ready || hasPending(active ?: "")) onUpdate?.invoke()
    }

    private fun persist() { store.putString(key, hubJson.encodeToString(queueSer, queue)) }

    private fun flush() {
        if (conflicts.isNotEmpty() || sent != null) return
        val i = queue.indexOfFirst { (it.caseId == active && ready) || it.ticket != null }
        if (i < 0) return
        if (queue[i].ticket == null) { queue[i].ticket = ticketOf(queue[i].caseId); persist() }
        val request = queue[i]
        lastAttempt = System.currentTimeMillis()
        if (sender?.invoke(hubJson.encodeToJsonElement(Request.serializer(), request)) == true) sent = request.requestId
        else status = "수정 저장됨 · 연결되면 다시 전송합니다."
    }
}

/** 외상 도해 한 부위의 공유 값 — 칸 "b:<부위>:<좌|우|빈칸>"의 JSON 문자열 */
@Serializable
data class SharedBodyValue(val added: Boolean, val removed: Boolean, val cares: List<String>)
