package xyz.goldenlink.core

import kotlinx.serialization.json.int
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** [기록] 탭 — 병원 응답 분류와 기록 직렬화 */
class CaseRecordTest {
    @Test
    fun groupsByStatus() {
        assertEquals(ResponseGroup.CONFIRMED, ResponseGroup.of("confirmed"))
        assertEquals(ResponseGroup.APPROVED, ResponseGroup.of("approved"))
        assertEquals(ResponseGroup.REJECTED, ResponseGroup.of("rejected"))
        assertEquals(ResponseGroup.NO_REPLY, ResponseGroup.of("pending"))   // 응답 없음 = 무응답
    }

    @Test
    fun roundTripAndCounts() {
        val r = CaseRecord(
            caseId = "c1", apid = "SEL0001", date = "2026-11-01", startedAt = 1L, updatedAt = 2L, ktasLevel = 2,
            hospitals = listOf(RecordHospital("A", "가", "confirmed"), RecordHospital("B", "나", "rejected", "BEDS_FULL"), RecordHospital("C", "다")),
            handover = mapOf("destination" to "가"),
        )
        val back = hubJson.decodeFromString(CaseRecord.serializer(), hubJson.encodeToString(CaseRecord.serializer(), r))
        assertEquals(r, back)
        assertEquals(1, back.count(ResponseGroup.CONFIRMED))
        assertEquals(1, back.count(ResponseGroup.NO_REPLY))
    }

    @Test
    fun hubArchiveRecordWithFractionalEpoch() {
        // hub 보관소는 epoch ms를 소수가 붙은 실수로 줄 수 있고, 서버 변경 순번·이벤트를 함께 싣는다
        val json = """{"caseId":"c1","apid":"SEL0001","date":"2026-11-01","startedAt":1793500000123.5,"updatedAt":1793500005000.0,
            "hospitals":[],"archiveVersion":7,"archiveEpoch":"e1","handoverRevision":2,"handoverEdits":{"destination":"가"},
            "events":[{"id":"1","hospitalId":"A","action":"hospital_reject","actor":"hospital","timestamp":"t","reason":"BEDS_FULL"}]}"""
        val r = hubJson.decodeFromString(CaseRecord.serializer(), json)
        assertEquals(1793500000123L, r.startedAt)
        assertEquals(7, r.archiveVersion)
        assertEquals("수용 거절", r.events!!.single().label)
    }

    private val legacy = """{"caseId":"case-old","apid":"SEL0001","date":"2026-11-01","startedAt":1793491200000,"updatedAt":1793491200000,"hospitals":[],"handover":{},"closed":true}"""

    @Test
    fun oldDeviceRecordsStillDecodeForMigration() {
        val record = hubJson.decodeFromString(CaseRecord.serializer(), legacy)
        assertNull(record.archiveVersion)
        assertNull(record.events)
        assertTrue(record.closed)
    }

    @Test
    fun serverPageKeepsHistorySeparateFromLatestStatus() {
        val json = """{"requestId":"download","apid":"SEL0001","epoch":"server-epoch","cursor":103,"hasMore":false,"records":[{"caseId":"case-old","apid":"SEL0001","date":"2026-11-01","startedAt":1793491200000,"updatedAt":1793491300000,"hospitals":[{"hospitalId":"H","name":"병원","status":"rejected"}],"handover":{"careFix":"부목 고정"},"handoverEdits":{},"handoverRevision":0,"closed":true,"archiveVersion":103,"archiveEpoch":"server-epoch","events":[{"id":"event-1","hospitalId":"H","action":"hospital_approve","actor":"hospital","timestamp":"2026-11-01T00:00:00Z"},{"id":"event-2","hospitalId":"H","action":"hospital_reject","actor":"hospital","timestamp":"2026-11-01T00:01:00Z","reason":"BEDS_FULL"}]}]}"""
        val page = hubJson.decodeFromString(RecordSyncReply.serializer(), json)
        val record = page.records!!.first()
        assertEquals(listOf("hospital_approve", "hospital_reject"), record.events!!.map { it.action })
        assertEquals("rejected", record.hospitals.first().status)
        assertEquals("부목 고정", record.handover["careFix"])
        assertEquals(page.epoch, record.archiveEpoch)
        assertEquals(page.cursor, record.archiveVersion)
    }

    @Test
    fun pendingSaveKeepsIdAcrossOfflineRestart() {
        val pending = PendingHandover("case-old", 2, mapOf("notes" to "수정 내용"))
        val restored = hubJson.decodeFromString(PendingHandover.serializer(), hubJson.encodeToString(PendingHandover.serializer(), pending))
        val request = RecordHandoverRequest(restored, "test-token")
        val body = hubJson.parseToJsonElement(hubJson.encodeToString(RecordHandoverRequest.serializer(), request)).jsonObject
        assertEquals(pending.requestId, body["requestId"]!!.jsonPrimitive.content)
        assertEquals(2, body["revision"]!!.jsonPrimitive.int)
    }

    @Test
    fun kstDate() {
        assertEquals("2026-11-02", RecordDates.of(java.time.Instant.parse("2026-11-01T15:30:00Z").toEpochMilli()))   // UTC 15:30 = KST 다음 날 00:30
        assertEquals("00:30", RecordDates.timeOf(java.time.Instant.parse("2026-11-01T15:30:00Z").toEpochMilli()))
    }
}
