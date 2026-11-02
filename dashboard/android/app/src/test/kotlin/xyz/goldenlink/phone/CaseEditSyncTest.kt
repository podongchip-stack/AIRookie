package xyz.goldenlink.phone

import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import java.util.UUID

/** 기기 간 수정 동기화 — 아이폰 shared/tests/CaseEditSyncChecks.swift와 같은 시나리오 */
class CaseEditSyncTest {
    private class MemoryStore : KeyValueStore {
        val values = HashMap<String, String>()
        override fun getString(key: String): String? = values[key]
        override fun putString(key: String, value: String): Boolean { values[key] = value; return true }
    }

    private val scope = "test-" + UUID.randomUUID()
    private val store = MemoryStore()
    private val sent = mutableListOf<JsonObject>()
    private val send: (JsonElement) -> Boolean = { sent.add(it.jsonObject); true }
    private val offline: (JsonElement) -> Boolean = { false }

    private fun state(sync: CaseEditSync, fields: Map<String, String>, version: Int, id: String? = null, conflicts: List<String> = emptyList(),
                      caseId: String = "case") {
        val value = buildJsonObject {
            put("type", JsonPrimitive("live_case_state")); put("caseId", JsonPrimitive(caseId)); put("apid", JsonPrimitive("A"))
            put("version", JsonPrimitive(version)); put("epoch", JsonPrimitive("epoch"))
            put("fields", buildJsonObject { fields.forEach { (k, v) -> put(k, JsonPrimitive(v)) } })
            put("ticket", JsonPrimitive("ticket"))
            put("conflicts", kotlinx.serialization.json.JsonArray(conflicts.map { JsonPrimitive(it) }))
            if (id != null) put("requestId", JsonPrimitive(id))
        }
        sync.accept(value.toString())
    }

    private fun lastRequestId() = sent.last()["requestId"]!!.jsonPrimitive.content

    @Test
    fun mergesResetsConflictsAndReplaysPendingEdits() {
        val sync = CaseEditSync(store)
        sync.activate("case", "A", scope, send = send)
        state(sync, emptyMap(), 1)
        assertTrue(sync.submit("case", mapOf("h:patientName" to "이름"), emptyMap()))
        val first = lastRequestId()
        state(sync, mapOf("h:destination" to "병원"), 2)
        assertEquals(mapOf("patientName" to "이름", "destination" to "병원"), sync.handover)   // 내 대기 수정 + 다른 기기 값이 합쳐 보인다
        state(sync, mapOf("h:patientName" to "이름", "h:destination" to "병원"), 3, first)
        assertFalse(sync.hasPending("case"))

        // 자동값으로 되돌리는 null은 JSON에 명시적으로 남는다
        val before = sync.fields
        sync.submit("case", mapOf("h:patientName" to null), before)
        assertEquals(JsonNull, sent.last()["changes"]!!.jsonObject["h:patientName"])
        val resetId = lastRequestId()
        state(sync, mapOf("h:patientName" to "다른 기기", "h:destination" to "병원"), 4, resetId, listOf("h:patientName"))
        assertTrue(sync.conflicts.isNotEmpty())
        sync.resolve(useMine = false)
        assertEquals("다른 기기", sync.handover["patientName"])

        // 사건이 끝난 뒤에도 대기 수정은 티켓으로 재전송되고 현재 화면에는 섞이지 않는다
        sync.submit("case", mapOf("h:notes" to "기록"), sync.fields)
        sync.activate(null, "A", scope, send = send)
        assertTrue(sync.fields.isEmpty())
        sync.reconnect()
        assertEquals("ticket", sent.last()["ticket"]!!.jsonPrimitive.contentOrNull)
        val oldId = lastRequestId()
        state(sync, mapOf("h:notes" to "기록"), 5, oldId)
        assertFalse(sync.hasPending("case"))
        assertTrue(sync.fields.isEmpty())
    }

    private fun error(sync: CaseEditSync, code: String, id: String?, caseId: String = "case") {
        val value = buildJsonObject {
            put("type", JsonPrimitive("live_case_error")); put("caseId", JsonPrimitive(caseId)); put("error", JsonPrimitive(code))
            if (id != null) put("requestId", JsonPrimitive(id))
        }
        sync.accept(value.toString())
    }

    @Test
    fun hubErrorsAreHandledByReasonAndUnsendableEditsAreDropped() {
        val sync = CaseEditSync(store)
        sync.activate("case", "A", scope, send = send)
        state(sync, emptyMap(), 1)
        // 일시정지·저장소 오류는 대기열을 그대로 두고 이유만 알린다
        sync.submit("case", mapOf("h:notes" to "기록"), emptyMap())
        error(sync, "paused", lastRequestId())
        assertTrue(sync.hasPending("case")); assertTrue(sync.status.contains("일시정지"))
        error(sync, "storage_unavailable", lastRequestId())
        assertTrue(sync.hasPending("case")); assertTrue(sync.status.contains("저장소"))
        // 지금 보는 사건이 not_owner면 hub가 아직 모르는 것일 수 있어 다시 시도한다(지우지 않는다)
        error(sync, "not_owner", lastRequestId())
        assertTrue(sync.hasPending("case")); assertTrue(sync.status.contains("알지 못합니다"))
        // 형식이 맞지 않는 수정은 다시 보내도 같아서 지운다
        error(sync, "invalid_patch", lastRequestId())
        assertFalse(sync.hasPending("case")); assertTrue(sync.status.contains("형식"))
    }

    @Test
    fun editsOfAClosedCaseAreDroppedWhenTheHubDoesNotOwnItAnymore() {
        val sync = CaseEditSync(store)
        sync.activate("case", "A", scope, send = send)
        state(sync, emptyMap(), 1)
        sync.submit("case", mapOf("h:notes" to "기록"), emptyMap())
        val id = lastRequestId()
        sync.activate("next", "A", scope, send = send)   // 사건이 바뀌었다 — 이전 사건의 수정은 티켓으로만 재전송된다
        error(sync, "not_owner", id)
        assertFalse(sync.hasPending("case"))
    }

    @Test
    fun persistedOfflineEditsReplayAndStayWithTheirCase() {
        val first = CaseEditSync(store)
        first.activate("offline", "A", scope, send = offline)
        val initial = buildJsonObject {
            put("caseId", JsonPrimitive("offline")); put("apid", JsonPrimitive("A")); put("fields", buildJsonObject {})
            put("version", JsonPrimitive(1)); put("epoch", JsonPrimitive("e")); put("ticket", JsonPrimitive("offline-ticket")); put("handoverRevision", JsonPrimitive(0))
        }
        first.accept(initial.toString())
        first.submit("offline", mapOf("h:notes" to "오프라인 수정"), emptyMap())

        // 앱을 다시 켠 것처럼 같은 저장소로 새로 만든다
        val reopened = CaseEditSync(store)
        reopened.activate("offline", "A", scope, send = send)
        assertTrue(reopened.hasPending("offline"))
        assertEquals("오프라인 수정", reopened.handover["notes"])
        assertEquals("offline-ticket", sent.last()["ticket"]!!.jsonPrimitive.contentOrNull)
        assertFalse(reopened.submit("wrong", mapOf("h:notes" to "혼입"), emptyMap()))   // 다른 사건 id는 받지 않는다
    }

    @Test
    fun legacyDeviceEditsMigrateOnceAndServerValuesWin() {
        val sync = CaseEditSync(store)
        sync.activate("legacy", "A", scope, initialHandover = mapOf("notes" to "기존 메모", "agency" to "기존 소속"), send = offline)
        sync.submit("legacy", mapOf("h:notes" to "오프라인 갱신"), emptyMap())
        assertEquals("기존 소속", sync.handover["agency"])
        val serverState = buildJsonObject {
            put("caseId", JsonPrimitive("legacy")); put("apid", JsonPrimitive("A")); put("fields", buildJsonObject {})
            put("version", JsonPrimitive(1)); put("epoch", JsonPrimitive("e")); put("ticket", JsonPrimitive("legacy-ticket")); put("handoverRevision", JsonPrimitive(0))
        }
        sync.accept(serverState.toString())
        assertEquals(mapOf("notes" to "오프라인 갱신", "agency" to "기존 소속"), sync.handover)
    }
}
