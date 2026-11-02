package xyz.goldenlink.core

// 외상 부위 도해의 순수 로직 — 아이패드 BodyInjuryView.swift의 BodyRegion·BodyEdits·InjuryRisk·InjuryMapper와 BodyShape 확장(영역·탭 판정)을 옮겼다.
// 부위는 통화 요약의 글자에서 낱말 규칙으로 찾는다(AI 아님). 위험도 색도 규칙이며 전문의 검토 전 초안이다 — 순위·병원 선택에는 쓰지 않는다.
// 좌표는 모두 그림 칸 기준 0~1이다(가로 0~1, 세로 0~1). 그리는 쪽이 칸 크기를 곱한다.

enum class BodyRegion(val label: String) {
    HEAD("머리"), FACE("얼굴"), NECK("목"), CHEST("가슴"), ABDOMEN("배"),
    BACK("등·허리"), PELVIS("골반"), ARM("팔"), HAND("손"), LEG("다리"), FOOT("발");

    val isLimb: Boolean get() = this == ARM || this == LEG || this == HAND || this == FOOT
}

/** 환자 기준 좌·우(그림에서는 좌우를 바꿔 그린다 — 보는 사람의 왼쪽이 환자의 오른쪽) */
enum class BodySide(val label: String) { LEFT("좌"), RIGHT("우"), UNKNOWN("") }

data class BodyMark(val region: BodyRegion, val side: BodySide) {
    val label: String get() = (if (side == BodySide.UNKNOWN) "" else side.label + " ") + region.label
}

/**
 * 외상 도해를 눌러서 고친 것 — 통화 요약(AI)에 부위를 더하거나 빼고, 부위마다 처치를 적는다.
 *  · 부위 → hub `patient_override.injuryStatus`(병원 화면·재매칭에 반영, "구급대원 확인" 도장)
 *  · 처치 → 인계확인서의 처치 칸(기도·호흡·순환·약품·고정·기타) + 병원에는 추가 정보로
 */
data class BodyEdits(
    /** 통화에 없었는데 구급대원이 찍은 부위 */
    val added: Set<BodyMark> = emptySet(),
    /** 통화에서 뽑혔지만 "여긴 아니다"라고 한 부위 */
    val removed: Set<BodyMark> = emptySet(),
    /** 부위별 처치 */
    val cares: Map<BodyMark, List<String>> = emptyMap(),
) {
    /** 인계확인서 처치 칸으로 — "좌 다리 부목 고정" */
    val careLines: List<String> get() = fittedCares.flatMap { (mark, list) -> list.map { "${mark.label} $it" } }.sorted()

    /** 부위에 맞는 처치만 — 다른 기기에서 온 값이나 예전에 적은 값에 맞지 않는 처치(예: 팔에 산소투여)가 있어도 여기서 걸러진다 */
    val fittedCares: Map<BodyMark, List<String>>
        get() = cares.mapValues { (mark, list) -> list.filter { BodyCare.fits(mark, it) } }.filterValues { it.isNotEmpty() }

    /** hub로 보낼 증상 줄 — 구급대원이 찍은 부위 */
    val addedLines: List<String> get() = added.map { it.label + " 외상(구급대원 확인)" }.sorted()

    val isEmpty: Boolean get() = added.isEmpty() && removed.isEmpty() && careLines.isEmpty()

    /** 고친 부위 수(한 부위에 외상·처치를 같이 적어도 한 곳) */
    val markCount: Int get() = (added + removed + fittedCares.keys).size

    /** 지금 내용의 지문 — 보낸 뒤 또 바뀌었는지만 본다 */
    val signature: String
        get() = (added.map { "+" + it.label }.sorted() + removed.map { "-" + it.label }.sorted() + careLines).joinToString("|")

    /** 한 부위를 적용한 새 값 — `fromCall`은 그 부위가 통화 요약에서 온 것인가 */
    fun applied(mark: BodyMark, on: Boolean, careList: List<String>, fromCall: Boolean): BodyEdits =
        if (on) copy(
            removed = if (fromCall) removed - mark else removed,
            added = if (fromCall) added else added + mark,
            cares = careList.filter { BodyCare.fits(mark, it) }.let { fitted -> if (fitted.isEmpty()) cares - mark else cares + (mark to fitted) },
        ) else copy(
            removed = if (fromCall) removed + mark else removed,
            added = if (fromCall) added else added - mark,
            cares = cares - mark,
        )
}

/**
 * 외상 부위에서 고를 수 있는 처치. 어휘는 voice 처치판(2026-10-29)의 `treat_categories` 28범주이고, 한글 이름은 hub `voice_treatments.py`와
 * 글자까지 같다 — 통화에서 AI가 뽑은 처치와 대원이 도해에서 고른 처치가 같은 문자열이라 서식·병원 화면에서 겹치지 않는다(`BodyCareTest`가 hub와 대조).
 *
 * 부위마다 **그 부위에 실제로 하는 처치만** 보인다. 산소·CPR·약물·정맥로처럼 부위에 속하지 않는 전신 처치는 여기에 없다 —
 * 통화 요약의 처치로는 그대로 인계확인서에 들어간다. 부위별 목록은 전문의 검토 전 초안이다.
 */
object BodyCare {
    class Item(val key: String, val label: String)

    /** 28범주 전체(순서는 voice·hub와 같다) */
    val all: List<Item> = listOf(
        Item("oxygen", "산소투여"), Item("suction", "기도 흡인"), Item("foreign_body", "기도 이물 제거"), Item("airway_basic", "기본 기도확보"),
        Item("airway_advanced", "전문 기도확보"), Item("ventilation", "인공호흡"), Item("cpr", "CPR"), Item("defib", "AED"),
        Item("iv", "정맥로 확보"), Item("fluid", "수액공급"), Item("bleeding", "지혈"), Item("med_aspirin", "아스피린 투여"),
        Item("med_nitro", "니트로글리세린 투여"), Item("med_glucose", "포도당 투여"), Item("med_epinephrine", "에피네프린 투여"),
        Item("med_bronchodilator", "기관지확장제 투여"), Item("med_other", "기타 약물투여"), Item("spinal", "척추 고정"), Item("splint", "부목 고정"),
        Item("wound", "상처처치"), Item("burn", "화상 처치"), Item("irrigation", "세척"), Item("cold_pack", "냉찜질"), Item("cooling", "냉각"),
        Item("warming", "보온"), Item("position", "체위 조절"), Item("delivery", "분만 처치"), Item("other", "기타 처치"),
    )

    // 어느 부위에나 하는 처치
    private val common = listOf("지혈", "상처처치", "화상 처치", "세척", "냉찜질", "체위 조절")
    private const val SPLINT = "부목 고정"
    private const val SPINAL = "척추 고정"
    private val airway = listOf("기도 흡인", "기도 이물 제거")

    /** 그 부위에서 고를 수 있는 처치 — 가장 해당되는 것이 앞에 온다 */
    fun optionsFor(region: BodyRegion): List<String> = when (region) {
        BodyRegion.ARM, BodyRegion.HAND, BodyRegion.LEG, BodyRegion.FOOT -> listOf(SPLINT) + common
        BodyRegion.PELVIS -> listOf(SPLINT, SPINAL) + common
        BodyRegion.HEAD, BodyRegion.BACK -> listOf(SPINAL) + common
        BodyRegion.NECK -> listOf(SPINAL) + airway + common
        BodyRegion.FACE -> airway + common
        BodyRegion.CHEST, BodyRegion.ABDOMEN -> common
    }

    fun fits(mark: BodyMark, label: String): Boolean = label in optionsFor(mark.region)
}

/** 통화 요약의 항목 하나와 그 항목이 가리키는 부위 */
data class MappedInjury(val text: String, val marks: List<BodyMark>, val isMulti: Boolean = false)

/** 외상 한 건의 위험도 — 규칙 기반, 전문의 검토 전 초안. 색만 나눌 뿐 순위·병원 선택에는 쓰지 않는다 */
enum class InjuryTier(val label: String) {
    LOW("낮음"), MEDIUM("중간"), HIGH("높음");
}

object InjuryRisk {
    /** 적색 깃발 — 하나라도 보이면 높음 */
    private val highWords = listOf(
        "관통", "자상", "총상", "절단", "압궤", "개방성", "개방 골절", "개방성 골절", "골반 골절", "척추 손상", "척수",
        "대량 출혈", "대량출혈", "다량 출혈", "출혈 지속", "동맥", "토혈", "객혈", "혈흉", "기흉", "혈복강", "복강 내 출혈",
        "2도 화상", "3도 화상", "흡입 화상", "기도 화상", "감전", "익수", "목맴", "교액", "질식", "기도 폐쇄",
        "의식 저하", "의식저하", "무반응", "반응 없음", "혼수", "지남력", "경련", "발작", "마비", "편마비",
        "호흡 곤란", "호흡곤란", "호흡 정지", "무호흡", "청색증", "심정지", "심폐", "쇼크", "저혈압", "저산소",
        "뇌출혈", "뇌졸중", "지주막하", "심근경색", "경색 의심", "대동맥", "아나필락시스", "패혈",
        "다발성", "중증",
    )

    /** 구조가 상한 것 — 중간 */
    private val mediumWords = listOf(
        "골절", "탈구", "열상", "자창", "화상", "출혈", "변형", "함몰", "타박상", "혈종", "압통", "복통", "흉통",
        "깊은", "찢어", "심한", "구토", "어지럼", "실신", "발열", "호흡 불편", "숨참",
    )

    /** 부정 표현 — "출혈 없음"처럼 없다고 말한 것은 깃발로 세지 않는다 */
    private val negations = listOf("없음", "없다", "없습니다", "아님", "아니", "음성", "정상", "소실", "해소", "부인")

    /** 중심부 — 낱말이 가벼워도 중간부터 본다(몸통·머리) */
    private val coreRegions = setOf(BodyRegion.HEAD, BodyRegion.NECK, BodyRegion.CHEST, BodyRegion.ABDOMEN, BodyRegion.PELVIS, BodyRegion.BACK)

    /** 한 건의 등급은 (낱말 등급, 부위 기본 등급) 중 높은 쪽이다 — "머리 타박"은 타박(낮음)이어도 머리라서 중간 */
    fun tier(text: String, region: BodyRegion?): InjuryTier {
        if (negations.any { text.contains(it) }) return InjuryTier.LOW
        if (highWords.any { text.contains(it) }) return InjuryTier.HIGH
        val byWord = if (mediumWords.any { text.contains(it) }) InjuryTier.MEDIUM else InjuryTier.LOW
        val byRegion = if (region != null && region in coreRegions) InjuryTier.MEDIUM else InjuryTier.LOW
        return maxOf(byWord, byRegion)
    }

    // 활력징후·의식 — 숫자라 추측이 없다. hub transport_triage.py와 같은 공개 표준 NEWS2(RCP 2017, Scale 1)
    private class Band(val lo: Double, val hi: Double?, val score: Int)

    private val news2Bands: Map<String, List<Band>> = mapOf(
        "rr" to listOf(Band(0.0, 8.0, 3), Band(9.0, 11.0, 1), Band(12.0, 20.0, 0), Band(21.0, 24.0, 2), Band(25.0, null, 3)),
        "spo2" to listOf(Band(0.0, 91.0, 3), Band(92.0, 93.0, 2), Band(94.0, 95.0, 1), Band(96.0, null, 0)),
        "sbp" to listOf(Band(0.0, 90.0, 3), Band(91.0, 100.0, 2), Band(101.0, 110.0, 1), Band(111.0, 219.0, 0), Band(220.0, null, 3)),
        "hr" to listOf(Band(0.0, 40.0, 3), Band(41.0, 50.0, 1), Band(51.0, 90.0, 0), Band(91.0, 110.0, 1), Band(111.0, 130.0, 2), Band(131.0, null, 3)),
        "bt" to listOf(Band(0.0, 35.0, 3), Band(35.1, 36.0, 1), Band(36.1, 38.0, 0), Band(38.1, 39.0, 1), Band(39.1, null, 2)),
    )

    internal fun band(name: String, value: Double): Int =
        news2Bands[name]?.firstOrNull { value >= it.lo && (it.hi == null || value <= it.hi) }?.score ?: 0

    data class VitalTier(val tier: InjuryTier, val reason: String?)

    /** 최근 활력징후·의식 → (등급, 근거 한 줄). 값이 없으면 낮음·근거 없음 */
    fun vitalTier(patient: PatientInfo?): VitalTier {
        if (patient == null) return VitalTier(InjuryTier.LOW, null)
        var score = 0
        val reasons = mutableListOf<String>()
        patient.vitals?.lastOrNull()?.let { v ->
            val items = listOf(Triple("rr", v.rr, "RR"), Triple("spo2", v.spo2, "SpO₂"), Triple("sbp", v.sbp, "SBP"), Triple("hr", v.hr, "HR"), Triple("bt", v.bt, "BT"))
            for ((name, value, label) in items) {
                if (value == null) continue
                val s = band(name, value)
                score += s
                if (s >= 2) reasons += "$label ${if (value % 1.0 == 0.0) value.toInt().toString() else "%.1f".format(value)}"
            }
        }
        val avpu = DisplayLabels.avpu(patient.consciousness)
        if (avpu != null && avpu != "A") {
            score += 3
            reasons += "의식 $avpu"
        }
        val tier = if (score >= 7) InjuryTier.HIGH else if (score >= 5) InjuryTier.MEDIUM else InjuryTier.LOW
        return VitalTier(tier, if (reasons.isEmpty()) null else "NEWS2 $score · " + reasons.joinToString(" · "))
    }
}

object InjuryMapper {
    /** 부위 낱말 — 긴 낱말을 먼저 본다("발목"이 "목"보다 먼저여야 발목 부상이 목으로 가지 않는다) */
    private val keywords: List<Pair<BodyRegion, String>> = listOf(
        BodyRegion.HEAD to listOf("머리", "두부", "두개", "뇌", "이마", "전두", "후두", "측두", "두피"),
        BodyRegion.FACE to listOf("얼굴", "안면", "눈", "코피", "코", "입", "턱", "치아", "귀", "구강"),
        BodyRegion.NECK to listOf("목", "경부", "경추", "기도"),
        BodyRegion.CHEST to listOf("가슴", "흉부", "흉곽", "흉골", "흉통", "늑골", "갈비", "쇄골", "심장", "심와", "폐"),
        BodyRegion.ABDOMEN to listOf("복부", "복강", "상복부", "하복부", "명치", "옆구리", "배", "위장", "간", "비장", "신장"),
        BodyRegion.BACK to listOf("등허리", "허리", "요추", "흉추", "척추", "견갑", "등"),
        BodyRegion.PELVIS to listOf("골반", "둔부", "엉덩이", "치골", "사타구니", "고관절", "회음"),
        BodyRegion.ARM to listOf("팔꿈치", "주관절", "전완", "상완", "어깨", "견관절", "상지", "팔"),
        BodyRegion.HAND to listOf("손가락", "손목", "손등", "손바닥", "수부", "손"),
        BodyRegion.LEG to listOf("허벅지", "대퇴", "무릎", "슬관절", "정강", "종아리", "발목", "하지", "다리"),
        BodyRegion.FOOT to listOf("발가락", "발등", "발바닥", "족부", "발"),
    ).flatMap { (r, ws) -> ws.map { r to it } }.sortedByDescending { it.second.length }

    /** 부위를 하나로 못 집는 말 — 몸통과 팔다리를 다 표시한다 */
    private val multiWords = listOf("다발성", "다발", "전신", "온몸", "여러 군데", "다수 부위")

    val multiMarks: List<BodyMark> = listOf(
        BodyMark(BodyRegion.HEAD, BodySide.UNKNOWN), BodyMark(BodyRegion.CHEST, BodySide.UNKNOWN), BodyMark(BodyRegion.ABDOMEN, BodySide.UNKNOWN),
        BodyMark(BodyRegion.ARM, BodySide.LEFT), BodyMark(BodyRegion.ARM, BodySide.RIGHT),
        BodyMark(BodyRegion.HAND, BodySide.LEFT), BodyMark(BodyRegion.HAND, BodySide.RIGHT),
        BodyMark(BodyRegion.LEG, BodySide.LEFT), BodyMark(BodyRegion.LEG, BodySide.RIGHT),
        BodyMark(BodyRegion.FOOT, BodySide.LEFT), BodyMark(BodyRegion.FOOT, BodySide.RIGHT),
    )

    /** 통화 요약에서 부위가 보이는 항목을 뽑는다. 예상 병명은 hub가 " · "로 이어 붙인 것이라 다시 쪼갠다 */
    fun parse(p: PatientInfo?): List<MappedInjury> {
        if (p == null) return emptyList()
        val items = mutableListOf<String>()
        items += (p.expectedDiagnosis ?: "").split('·', ',', '/')
        items += p.injuryStatus ?: emptyList()
        p.chiefComplaint?.let { items += it }
        items += (p.extraNotes ?: emptyList()).map { it.text }
        val seen = HashSet<String>()
        return items.map { it.trim() }
            .filter { it.isNotEmpty() && seen.add(it) && !isCategoryCode(it) }
            .map { MappedInjury(it, marks(it), isMulti(it)) }
    }

    fun isMulti(text: String): Boolean = multiWords.any { text.contains(it) }

    /** 한 항목의 부위. 같은 항목에 부위가 여럿이면 다 표시한다("머리와 다리 열상") */
    fun marks(text: String): List<BodyMark> {
        if (isMulti(text)) return multiMarks
        val found = mutableListOf<BodyMark>()
        var rest = text
        for ((region, word) in keywords) {
            if (!rest.contains(word)) continue
            // 쓴 낱말은 지워 더 짧은 낱말이 같은 글자를 다시 집지 않게("발목" → "목")
            rest = rest.replace(word, " ")
            if (found.any { it.region == region }) continue
            if (region.isLimb) found += sides(text).map { BodyMark(region, it) } else found += BodyMark(region, BodySide.UNKNOWN)
        }
        return found
    }

    /** MF_BERT 주 호소의 대분류 코드("T 외상"·"I 심혈관계")는 손상이 아니라 분류표라 그림에서 뺀다 */
    private fun isCategoryCode(text: String): Boolean = Regex("^[A-Z][ .]").containsMatchIn(text)

    /** 팔·다리의 좌우. 안 적혀 있으면 양쪽 다 표시한다. "좌"·"우" 한 글자는 낱말 앞에서만 본다("염좌"에 안 걸리게) */
    private fun sides(text: String): List<BodySide> {
        fun mark(one: String, word: String) = text.contains(word) || Regex("(^|[\\s(/·,])$one(측|쪽)?").containsMatchIn(text)
        val left = mark("좌", "왼")
        val right = mark("우", "오른")
        if (left && !right) return listOf(BodySide.LEFT)
        if (right && !left) return listOf(BodySide.RIGHT)
        return listOf(BodySide.LEFT, BodySide.RIGHT)
    }
}

/** 그림 위의 점 (0~1) */
data class Pt(val x: Double, val y: Double)

/** 사람 그림의 기하 — 부위 영역(다각형)·경계선·번호 자리·탭 판정. 아이패드 BodyShape 확장과 같은 값이다 */
object BodyGeometry {
    private const val HEAD_BOTTOM = 0.132   // 턱선
    private const val NECK_BOTTOM = 0.198   // 어깨가 시작하는 곳
    private const val CHEST_BOTTOM = 0.360
    private const val ABDOMEN_BOTTOM = 0.470
    private const val CROTCH = 0.565        // 가랑이
    private const val HAND_SPLIT = 0.48     // 손목 — 팔과 손의 경계
    private const val HAND_TIP = 0.58       // 손끝
    private const val FOOT_SPLIT = 0.90     // 발목 — 다리와 발의 경계

    /** 몸통 경계 한 줄 — (y, 왼쪽 x, 오른쪽 x) */
    private class Row(val y: Double, val l: Double, val r: Double)

    private val torso: List<Row> = BodyShapeData.torso.toList().chunked(3).map { Row(it[0], it[1], it[2]) }

    /** 실루엣 전체 */
    val outline: List<Pt> = BodyShapeData.outline.toList().chunked(2).map { Pt(it[0], it[1]) }

    /** 앞모습에서만 / 뒷모습에서만 보이는 부위. 머리·목·팔·다리는 양쪽에 다 있다 */
    fun visible(r: BodyRegion, back: Boolean): Boolean = when (r) {
        BodyRegion.FACE, BodyRegion.CHEST, BodyRegion.ABDOMEN -> !back
        BodyRegion.BACK -> back
        else -> true
    }

    private fun rect(y0: Double, y1: Double, x0: Double = 0.0, x1: Double = 1.0): List<Pt> =
        listOf(Pt(x0, y0), Pt(x1, y0), Pt(x1, y1), Pt(x0, y1))

    /** 한 부위를 오려 낼 영역 — 앞모습 좌표 그대로. 뒷모습은 같은 좌표에 그린 뒤 좌우를 뒤집어 보여 준다 */
    fun region(m: BodyMark, back: Boolean = false): List<Pt> {
        if (back) when (m.region) {
            BodyRegion.FACE, BodyRegion.CHEST, BodyRegion.ABDOMEN -> return emptyList()
            BodyRegion.BACK -> return band(NECK_BOTTOM, ABDOMEN_BOTTOM)
            else -> {}
        }
        return when (m.region) {
            BodyRegion.HEAD -> rect(0.0, HEAD_BOTTOM)
            BodyRegion.FACE -> rect(0.055, HEAD_BOTTOM - 0.004, 0.28, 0.72)
            BodyRegion.NECK -> rect(HEAD_BOTTOM, NECK_BOTTOM, 0.34, 0.66)   // 어깨까지 번지지 않게 가운데만
            BodyRegion.CHEST -> band(NECK_BOTTOM, CHEST_BOTTOM)
            BodyRegion.ABDOMEN -> band(CHEST_BOTTOM, ABDOMEN_BOTTOM)
            BodyRegion.PELVIS -> rect(ABDOMEN_BOTTOM, CROTCH, 0.17, 0.83)
            // 등·허리는 앞모습에 안 보인다 — 몸통 가운데 띠로 표시한다
            BodyRegion.BACK -> rect(0.215, 0.520, 0.41, 0.59)
            BodyRegion.ARM -> armSide(m.side)
            BodyRegion.HAND -> handSide(m.side)
            BodyRegion.LEG -> if (m.side == BodySide.RIGHT) rect(CROTCH, FOOT_SPLIT, 0.17, 0.5) else rect(CROTCH, FOOT_SPLIT, 0.5, 0.83)
            BodyRegion.FOOT -> if (m.side == BodySide.RIGHT) rect(FOOT_SPLIT, 1.0, 0.17, 0.5) else rect(FOOT_SPLIT, 1.0, 0.5, 0.83)
        }
    }

    /** 몸통 띠 — 좌우를 몸통 경계로 잘라 팔까지 칠해지지 않게 한다 */
    private fun band(y0: Double, y1: Double): List<Pt> {
        val rows = torsoRows(y0, y1)
        if (rows.isEmpty()) return emptyList()
        return rows.map { Pt(it.l, it.y) } + rows.asReversed().map { Pt(it.r, it.y) }
    }

    /** 팔 — 어깨부터 손목까지, 몸통 경계 바깥쪽(환자의 오른팔이 보는 사람의 왼쪽) */
    private fun armSide(side: BodySide): List<Pt> {
        val rows = torsoRows(HEAD_BOTTOM, HAND_SPLIT)
        val first = rows.firstOrNull() ?: return emptyList()
        val last = rows.last()
        val viewerLeft = side == BodySide.RIGHT
        val outer = if (viewerLeft) 0.0 else 1.0
        return rows.map { Pt(if (viewerLeft) it.l else it.r, it.y) } + listOf(Pt(outer, last.y), Pt(outer, first.y))
    }

    /** 손 — 손목부터 손끝까지. 폭이 좁아졌다 넓어지므로 실측한 고정 가로 범위(0.17/0.83)를 쓴다 */
    private fun handSide(side: BodySide): List<Pt> {
        val viewerLeft = side == BodySide.RIGHT
        val inner = if (viewerLeft) 0.17 else 0.83
        val outer = if (viewerLeft) 0.0 else 1.0
        return rect(HAND_SPLIT, HAND_TIP, minOf(inner, outer), maxOf(inner, outer))
    }

    private fun torsoRows(y0: Double, y1: Double): List<Row> {
        val rows = torso.filter { it.y > y0 && it.y < y1 }.toMutableList()
        at(y0)?.let { rows.add(0, it) }
        at(y1)?.let { rows.add(it) }
        return rows
    }

    private fun at(y: Double): Row? {
        val first = torso.firstOrNull() ?: return null
        val last = torso.last()
        if (y <= first.y) return Row(y, first.l, first.r)
        if (y >= last.y) return Row(y, last.l, last.r)
        for ((a, b) in torso.zipWithNext()) if (y >= a.y && y <= b.y) {
            val t = (y - a.y) / maxOf(0.0001, b.y - a.y)
            return Row(y, a.l + (b.l - a.l) * t, a.r + (b.r - a.r) * t)
        }
        return null
    }

    /** 부위 경계선 — 누를 수 있는 칸이 보이게 실루엣 안에 옅은 선을 긋는다. 선분 목록(시작·끝) */
    fun dividers(back: Boolean = false): List<Pair<Pt, Pt>> {
        val out = mutableListOf<Pair<Pt, Pt>>()
        for (y in if (back) listOf(HEAD_BOTTOM, NECK_BOTTOM, ABDOMEN_BOTTOM, CROTCH) else listOf(HEAD_BOTTOM, NECK_BOTTOM, CHEST_BOTTOM, ABDOMEN_BOTTOM, CROTCH)) {
            out += Pt(0.0, y) to Pt(1.0, y)
        }
        out += Pt(0.5, CROTCH) to Pt(0.5, 1.0)       // 다리 가운데
        val rows = torsoRows(HEAD_BOTTOM, HAND_SPLIT)  // 팔/몸통 경계
        for (edge in 1..2) {
            val pts = rows.map { Pt(if (edge == 1) it.l else it.r, it.y) }
            out += pts.zipWithNext()
        }
        rows.lastOrNull()?.let {                       // 손목 경계 — 팔 칸 안에서만
            out += Pt(0.0, HAND_SPLIT) to Pt(it.l, HAND_SPLIT)
            out += Pt(it.r, HAND_SPLIT) to Pt(1.0, HAND_SPLIT)
        }
        out += Pt(0.17, FOOT_SPLIT) to Pt(0.83, FOOT_SPLIT)   // 발목 경계
        return out
    }

    /** 번호 동그라미 자리(0~1). 뒷모습은 그림이 뒤집혀 보이므로 x도 뒤집는다 */
    fun anchor(m: BodyMark, back: Boolean): Pt {
        val a = anchor(m)
        return if (back) Pt(1 - a.x, a.y) else a
    }

    private fun anchor(m: BodyMark): Pt {
        val right = m.side == BodySide.RIGHT
        return when (m.region) {
            BodyRegion.HEAD -> Pt(0.5, 0.055)
            BodyRegion.FACE -> Pt(0.5, 0.115)
            BodyRegion.NECK -> Pt(0.5, 0.176)
            BodyRegion.CHEST -> Pt(0.5, 0.265)
            BodyRegion.BACK -> Pt(0.5, 0.345)
            BodyRegion.ABDOMEN -> Pt(0.5, 0.432)
            BodyRegion.PELVIS -> Pt(0.5, 0.535)
            BodyRegion.ARM -> Pt(if (right) 0.075 else 0.925, 0.430)
            BodyRegion.HAND -> Pt(if (right) 0.085 else 0.915, (HAND_SPLIT + HAND_TIP) / 2)
            BodyRegion.LEG -> Pt(if (right) 0.315 else 0.685, 0.760)
            BodyRegion.FOOT -> Pt(if (right) 0.315 else 0.685, (FOOT_SPLIT + 1) / 2)
        }
    }

    private fun contains(poly: List<Pt>, p: Pt): Boolean {
        if (poly.size < 3) return false
        var inside = false
        var j = poly.lastIndex
        for (i in poly.indices) {
            val a = poly[i]; val b = poly[j]
            if ((a.y > p.y) != (b.y > p.y) && p.x < (b.x - a.x) * (p.y - a.y) / (b.y - a.y) + a.x) inside = !inside
            j = i
        }
        return inside
    }

    private fun m(r: BodyRegion, s: BodySide = BodySide.UNKNOWN) = BodyMark(r, s)

    private val hitFront = listOf(
        m(BodyRegion.FACE), m(BodyRegion.NECK), m(BodyRegion.HEAD),
        m(BodyRegion.HAND, BodySide.LEFT), m(BodyRegion.HAND, BodySide.RIGHT), m(BodyRegion.ARM, BodySide.LEFT), m(BodyRegion.ARM, BodySide.RIGHT),
        m(BodyRegion.FOOT, BodySide.LEFT), m(BodyRegion.FOOT, BodySide.RIGHT), m(BodyRegion.LEG, BodySide.LEFT), m(BodyRegion.LEG, BodySide.RIGHT),
        m(BodyRegion.CHEST), m(BodyRegion.ABDOMEN), m(BodyRegion.PELVIS),
    )
    private val hitBack = listOf(
        m(BodyRegion.NECK), m(BodyRegion.HEAD),
        m(BodyRegion.HAND, BodySide.LEFT), m(BodyRegion.HAND, BodySide.RIGHT), m(BodyRegion.ARM, BodySide.LEFT), m(BodyRegion.ARM, BodySide.RIGHT),
        m(BodyRegion.FOOT, BodySide.LEFT), m(BodyRegion.FOOT, BodySide.RIGHT), m(BodyRegion.LEG, BodySide.LEFT), m(BodyRegion.LEG, BodySide.RIGHT),
        m(BodyRegion.BACK), m(BodyRegion.PELVIS),
    )

    /** 누른 자리(0~1)가 어느 부위인가 — 겹치는 영역은 좁은 것부터 본다. 실루엣 밖은 null.
     *  뒷모습은 그림을 좌우로 뒤집어 보여 주므로 누른 자리도 되뒤집어 앞모습 좌표에서 찾는다 */
    fun hit(p: Pt, back: Boolean = false): BodyMark? {
        val q = if (back) Pt(1 - p.x, p.y) else p
        if (!contains(outline, q)) return null
        return (if (back) hitBack else hitFront).firstOrNull { contains(region(it, back), q) }
    }
}
