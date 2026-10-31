package xyz.goldenlink.core

import org.junit.jupiter.api.Assertions.assertEquals
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
    fun kstDate() {
        assertEquals("2026-11-02", RecordDates.of(java.time.Instant.parse("2026-11-01T15:30:00Z").toEpochMilli()))   // UTC 15:30 = KST 다음 날 00:30
        assertEquals("00:30", RecordDates.timeOf(java.time.Instant.parse("2026-11-01T15:30:00Z").toEpochMilli()))
    }
}
