package xyz.goldenlink.core

import org.junit.jupiter.api.Assertions.assertEquals
import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertNull
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test

/** 외상 도해 로직 — 아이패드 BodyInjuryView.swift의 DEBUG 자체 검사(selfCheck)를 그대로 옮겼다 */
class BodyInjuryTest {
    private fun mk(r: BodyRegion, s: BodySide = BodySide.UNKNOWN) = BodyMark(r, s)
    private fun sides(r: BodyRegion) = listOf(mk(r, BodySide.LEFT), mk(r, BodySide.RIGHT))

    @Test
    fun tierRules() {
        assertEquals(InjuryTier.MEDIUM, InjuryRisk.tier("좌 다리 골절", BodyRegion.LEG))
        assertEquals(InjuryTier.MEDIUM, InjuryRisk.tier("머리 타박", BodyRegion.HEAD))
        assertEquals(InjuryTier.HIGH, InjuryRisk.tier("흉부 관통상", BodyRegion.CHEST))
        assertEquals(InjuryTier.LOW, InjuryRisk.tier("손목 찰과상", BodyRegion.ARM))
        assertEquals(InjuryTier.HIGH, InjuryRisk.tier("의식 저하", null))
        assertEquals(InjuryTier.LOW, InjuryRisk.tier("의식 저하 없음", null))
        assertEquals(InjuryTier.LOW, InjuryRisk.tier("활동성 출혈 없음", BodyRegion.ARM))
        assertEquals(InjuryTier.HIGH, InjuryRisk.tier("개방성 골절", BodyRegion.LEG))
        assertEquals(3, InjuryRisk.band("spo2", 88.0))
        assertEquals(3, InjuryRisk.band("sbp", 85.0))
    }

    @Test
    fun partsFromText() {
        assertEquals(listOf(mk(BodyRegion.LEG, BodySide.LEFT)), InjuryMapper.marks("좌 다리 골절"))
        assertEquals(listOf(mk(BodyRegion.LEG, BodySide.RIGHT)), InjuryMapper.marks("우측 발목 염좌"))   // 발목이 목보다 먼저
        assertEquals(sides(BodyRegion.HAND), InjuryMapper.marks("손목 자상"))
        assertEquals(sides(BodyRegion.LEG), InjuryMapper.marks("발목 염좌"))                              // "염좌"의 좌는 좌우가 아니다
        assertEquals(listOf(mk(BodyRegion.ARM, BodySide.LEFT)), InjuryMapper.marks("좌측 팔 골절"))
        assertEquals(listOf(mk(BodyRegion.HAND, BodySide.RIGHT)), InjuryMapper.marks("우측 손가락 열상"))
        assertEquals(sides(BodyRegion.FOOT), InjuryMapper.marks("발가락 동상"))
        assertEquals(BodyRegion.NECK, InjuryMapper.marks("경부 통증").first().region)
        assertEquals(BodyRegion.CHEST, InjuryMapper.marks("흉통(심장성)").first().region)
        assertEquals(InjuryMapper.multiMarks.size, InjuryMapper.marks("교통사고 다발성 외상").size)
        assertTrue(InjuryMapper.marks("호흡 곤란").isEmpty())
        assertEquals(setOf(BodyRegion.HEAD, BodyRegion.LEG), InjuryMapper.marks("머리 열상과 다리 골절").map { it.region }.toSet())
        assertTrue(InjuryMapper.isMulti("다발성 외상") && !InjuryMapper.isMulti("머리 열상"))
    }

    @Test
    fun categoryCodeIsNotAnInjury() {
        val p = PatientInfo(chiefComplaint = "T 외상", expectedDiagnosis = "좌 다리 골절 · 교통사고")
        assertEquals(listOf("좌 다리 골절", "교통사고"), InjuryMapper.parse(p).map { it.text })
    }

    @Test
    fun tapToPart() {
        fun at(x: Double, y: Double) = BodyGeometry.hit(Pt(x, y))
        assertEquals(BodyRegion.FACE, at(0.5, 0.11)?.region)
        assertEquals(BodyRegion.NECK, at(0.5, 0.17)?.region)
        assertEquals(BodyRegion.CHEST, at(0.5, 0.26)?.region)
        assertEquals(BodyRegion.ABDOMEN, at(0.5, 0.43)?.region)
        assertEquals(BodyRegion.PELVIS, at(0.5, 0.53)?.region)
        assertEquals(mk(BodyRegion.LEG, BodySide.RIGHT), at(0.32, 0.80))   // 그림 왼쪽 = 환자 오른쪽
        assertEquals(mk(BodyRegion.LEG, BodySide.LEFT), at(0.68, 0.80))
        assertEquals(mk(BodyRegion.FOOT, BodySide.RIGHT), at(0.32, 0.96))
        assertEquals(mk(BodyRegion.FOOT, BodySide.LEFT), at(0.68, 0.96))
        assertEquals(mk(BodyRegion.ARM, BodySide.RIGHT), at(0.05, 0.40))
        assertEquals(mk(BodyRegion.HAND, BodySide.RIGHT), at(0.05, 0.52))
        assertEquals(mk(BodyRegion.HAND, BodySide.LEFT), at(0.95, 0.52))
        assertNull(at(0.5, 1.4))

        fun atBack(x: Double, y: Double) = BodyGeometry.hit(Pt(x, y), back = true)
        assertEquals(mk(BodyRegion.LEG, BodySide.LEFT), atBack(0.32, 0.80))   // 뒷모습은 좌우가 뒤집혀 보인다
        assertEquals(mk(BodyRegion.LEG, BodySide.RIGHT), atBack(0.68, 0.80))
        assertEquals(BodyRegion.BACK, atBack(0.5, 0.26)?.region)
        assertEquals(BodyRegion.BACK, atBack(0.5, 0.43)?.region)
        assertEquals(BodyRegion.PELVIS, atBack(0.5, 0.53)?.region)
        assertEquals(BodyRegion.HEAD, atBack(0.5, 0.11)?.region)               // 뒤통수(얼굴 아님)
        assertTrue(BodyGeometry.visible(BodyRegion.BACK, true) && !BodyGeometry.visible(BodyRegion.BACK, false))
        assertTrue(BodyGeometry.visible(BodyRegion.CHEST, false) && !BodyGeometry.visible(BodyRegion.CHEST, true))
    }

    @Test
    fun editsAndLines() {
        val leg = mk(BodyRegion.LEG, BodySide.LEFT)
        var e = BodyEdits().applied(leg, true, listOf("지혈", "부목 고정"), fromCall = false)
        assertEquals(listOf("좌 다리 외상(구급대원 확인)"), e.addedLines)
        assertEquals(listOf("좌 다리 부목 고정", "좌 다리 지혈"), e.careLines)
        assertFalse(e.isEmpty)
        assertTrue(BodyEdits().isEmpty)
        assertEquals(1, e.markCount)
        val before = e.signature
        e = e.applied(mk(BodyRegion.BACK, BodySide.UNKNOWN), true, emptyList(), fromCall = false)
        assertNotEquals(before, e.signature)
        assertEquals(2, e.markCount)
        // 통화에서 온 부위를 빼면 removed로, 다시 켜면 되돌린다
        val head = mk(BodyRegion.HEAD, BodySide.UNKNOWN)
        val off = BodyEdits().applied(head, false, emptyList(), fromCall = true)
        assertEquals(setOf(head), off.removed)
        assertTrue(off.applied(head, true, emptyList(), fromCall = true).removed.isEmpty())
    }

    @Test
    fun careOptionsFitTheRegion() {
        // 팔다리·골반은 부목, 머리·목·등·골반은 척추 고정, 얼굴·목은 기도 처치, 가슴·배는 공통만
        for (r in listOf(BodyRegion.ARM, BodyRegion.HAND, BodyRegion.LEG, BodyRegion.FOOT, BodyRegion.PELVIS)) assertTrue("부목 고정" in BodyCare.optionsFor(r))
        for (r in listOf(BodyRegion.HEAD, BodyRegion.NECK, BodyRegion.BACK, BodyRegion.PELVIS)) assertTrue("척추 고정" in BodyCare.optionsFor(r))
        for (r in listOf(BodyRegion.FACE, BodyRegion.NECK)) assertTrue("기도 흡인" in BodyCare.optionsFor(r) && "기도 이물 제거" in BodyCare.optionsFor(r))
        assertFalse("부목 고정" in BodyCare.optionsFor(BodyRegion.CHEST))
        assertFalse("척추 고정" in BodyCare.optionsFor(BodyRegion.ARM))
        // 전신 처치는 어느 부위에도 없다
        val systemic = listOf("산소투여", "정맥로 확보", "CPR", "AED", "수액공급", "인공호흡", "보온", "냉각", "분만 처치", "아스피린 투여", "기본 기도확보")
        for (r in BodyRegion.entries) for (t in systemic) assertFalse(t in BodyCare.optionsFor(r), "$r $t")
        // 모든 선택지는 28범주 어휘 안에 있다
        val all = BodyCare.all.map { it.label }.toSet()
        for (r in BodyRegion.entries) assertTrue(all.containsAll(BodyCare.optionsFor(r)))
        assertEquals(28, BodyCare.all.size)
    }

    @Test
    fun misfitCaresAreDropped() {
        val arm = mk(BodyRegion.ARM, BodySide.LEFT)
        // 팔에 산소투여·척추 고정은 맞지 않아 적용 때 걸러진다
        val e = BodyEdits().applied(arm, true, listOf("부목 고정", "산소투여", "척추 고정", "지혈"), fromCall = false)
        assertEquals(listOf("좌 팔 부목 고정", "좌 팔 지혈"), e.careLines)
        // 이미 들어와 있던 값(다른 기기·예전 값)도 읽을 때 걸러진다
        val stale = BodyEdits(added = setOf(arm), cares = mapOf(arm to listOf("산소 투여", "정맥로 확보", "부목 고정")))
        assertEquals(listOf("좌 팔 부목 고정"), stale.careLines)
        assertEquals(1, stale.markCount)
        val onlyMisfit = BodyEdits(cares = mapOf(arm to listOf("산소 투여")))
        assertTrue(onlyMisfit.isEmpty)
        assertEquals(0, onlyMisfit.markCount)
    }

    @Test
    fun vocabularyMatchesHub() {
        // hub/voice_treatments.py의 한글 이름과 글자까지 같아야 AI가 뽑은 처치와 겹치지 않는다. 저장소 밖에서 돌리면 건너뛴다
        val file = java.io.File("../../../hub/voice_treatments.py")
        org.junit.jupiter.api.Assumptions.assumeTrue(file.exists())
        val text = file.readText(Charsets.UTF_8)
        val start = text.indexOf("['산소투여'")
        val end = text.indexOf("'기타 처치']") + "'기타 처치']".length
        val hub = Regex("'([^']+)'").findAll(text.substring(start, end)).map { it.groupValues[1] }.toList()
        assertEquals(hub, BodyCare.all.map { it.label })
    }
}
