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
}
