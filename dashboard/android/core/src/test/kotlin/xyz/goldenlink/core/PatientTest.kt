package xyz.goldenlink.core

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertNotNull
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** 환자 정보 탭 쪽 로직 — hub 메시지 디코딩, 인계확인서 자동 채움, 병상 신뢰도 감쇠. 아이패드 Swift 코드와 같은 규칙인지 본다 */
class PatientTest {
    private val matchJson = """
        {"caseId":"case-1","apid":"SEL0001","ambulanceName":"x","unknownField":1,
         "patientInfo":{"expectedDiagnosis":"경색 의심","injuryStatus":["흉통"],"ktasLevel":2,"patient":"62세 남성",
           "consciousness":"통증 반응(P)","treatment":["산소 투여","ECG"],"onset":"30분 전부터",
           "vitals":[{"sbp":150,"dbp":90,"hr":110,"spo2":96}],"callRound":1,
           "extraNotes":[{"text":"[처치] 좌 다리 부목","at":"2026-10-29T01:00:00Z"},{"text":"보호자 동승","at":"2026-10-29T01:01:00Z"}]},
         "hospitals":[{"hospitalId":"A1","name":"서울병원","status":"approved","distanceKm":3.2,"etaMin":7,
           "availableBedCount":4,"specialtyMatch":{"department":"순환기내과","basis":"exact","doctorCount":3},
           "bedReliability":{"authority":0.9,"rArrive":0.8,"horizonSec":420}}]}
    """.trimIndent()

    @Test
    fun matchResultDecodes() {
        val m = hubJson.decodeFromString(MatchResult.serializer(), matchJson)
        assertEquals("경색 의심", m.patientInfo?.expectedDiagnosis)
        assertEquals("BP 150/90 · HR 110 · SpO₂ 96%", m.patientInfo?.vitals?.last()?.text)
        assertEquals(7.0, m.hospitals[0].etaMin)
        assertEquals(0.8, m.hospitals[0].bedReliability?.rArrive)
    }

    @Test
    fun outgoingMessagesOmitUntouchedFields() {
        val o = hubJson.encodeToString(PatientOverrideMessage.serializer(), PatientOverrideMessage("c", "t", ktasLevel = 2))
        assertTrue(o.contains("\"type\":\"patient_override\"") && o.contains("\"ktasLevel\":2"))
        assertTrue(!o.contains("expectedDiagnosis") && !o.contains("injuryStatus"))
        val a = hubJson.encodeToString(ApprovalAction.serializer(), ApprovalAction("c", "A1", "t"))
        assertTrue(a.contains("\"action\":\"final_approval\"") && a.contains("\"actor\":\"paramedic\""))
    }

    @Test
    fun handoverAutoFillsFromSummary() {
        val m = hubJson.decodeFromString(MatchResult.serializer(), matchJson)
        val v = Handover.auto(m.patientInfo, m.hospitals[0].copy(status = "confirmed"), "역삼 구급 1", "SEL0001",
            mapOf("dispatchedAt" to 0L), GPS(37.5, 127.0), null, bodyCare = emptyList())
        assertEquals("서울병원", v["destination"])
        assertEquals("전문진료 가능", v["selectReason"])
        assertEquals("남", v["patientSex"])
        assertEquals("확인불가(62세)", v["patientBirth"])
        assertEquals("응급", v["severity"])
        assertEquals("P", v["avpu"])
        assertEquals("산소 투여", v["careBreathing"])
        assertEquals("ECG", v["careCirculation"])
        assertEquals("위도 37.50000, 경도 127.00000", v["originAddress"])
        // "[처치]"로 시작하는 추가 정보는 기타 소견에 또 적지 않는다
        assertEquals("증상: 흉통\n발생: 30분 전부터\n추가: 보호자 동승", v["notes"])
    }

    @Test
    fun treatmentsFillHandoverWithoutLosingStatus() {
        val p = PatientInfo(treatment = listOf("산소투여(비관)", "CPR", "AED", "정맥로 확보", "수액공급", "지혈", "아스피린 투여", "척추 고정", "부목 고정", "상처처치 거부"))
        val v = Handover.auto(p, null, null, null, emptyMap(), null, null)
        assertEquals("산소투여(비관)", v["careBreathing"])
        assertTrue(v["careCirculation"]!!.contains("CPR"))
        assertTrue(v["careCirculation"]!!.contains("지혈"))
        assertEquals("아스피린 투여", v["careDrug"])
        assertTrue(v["careFix"]!!.contains("부목 고정"))
        assertTrue(v["careEtc"]!!.contains("거부"))
    }

    @Test
    fun handoverMessageListsOnlyFilledFields() {
        val msg = Handover.message(mapOf("destination" to "서울병원", "notes" to "a\nb"))
        assertTrue(msg.startsWith("[인계확인서] 출동 및 처치 기록지"))
        assertTrue(msg.contains("도착기관 명칭: 서울병원"))
        assertTrue(msg.contains("a / b"))
        assertTrue(!msg.contains("환자 성명"))
    }

    @Test
    fun bedLiveFallsBackToScalarsAndDecays() {
        val still = BedLive.of(BedReliability(authority = 0.9, rArrive = 0.8), 0L)
        assertEquals(0.8, still.rArrive); assertEquals(false, still.live)
        val br = BedReliability(authority = 1.0, rArrive = 1.0, horizonSec = 600.0, predictedSurvivalSec = 1200.0,
            bornAt = "1970-01-01T00:00:00Z", sigma = 1.0)
        val atMedian = BedLive.of(br, 1_200_000L)   // 나이 = 예측 수명 -> S = 0.5
        assertEquals(0.5, atMedian.authority, 1e-3)
        assertTrue(atMedian.rArrive < atMedian.authority)  // 도착 시점이 더 낮다
        assertNotNull(atMedian.ageSec); assertNull(still.ageSec)
    }

    @Test
    fun avpuReadsParenthesis() {
        assertEquals("P", DisplayLabels.avpu("통증 반응(P)"))
        assertEquals("A", DisplayLabels.avpu("alert"))
        assertNull(DisplayLabels.avpu(""))
    }
}
