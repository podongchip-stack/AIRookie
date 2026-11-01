package xyz.goldenlink.core

import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * 인계확인서 = **출동 및 처치 기록지**(응급의료에 관한 법률 시행규칙 [별지 제16호서식], 2019-09-27 개정)의 칸들.
 * 아이패드 Handover.swift를 그대로 옮겼다 — 칸을 구조체가 아니라 목록(`fields`)으로 두어 서식이 바뀌면 이 목록만 고친다.
 * 값은 두 겹이다: 통화 요약·출동 상태에서 자동으로 채운 값(`auto`)과 구급대원이 고친 값(`edits`, 기기에 사건별 저장).
 * 보여줄 때는 `edits[id] ?: auto[id]`. 서명·면허번호처럼 앱이 알 수 없는 칸은 빈칸이고 사람이 채운다.
 */
object Handover {
    sealed interface Kind {
        data object Text : Kind
        data object Multiline : Kind
        data class Choice(val options: List<String>) : Kind
    }

    data class Field(
        val id: String,
        val label: String,
        val section: Int,
        val kind: Kind = Kind.Text,
        /** 서식의 '*' 칸(반드시 적는 칸) */
        val required: Boolean = false,
        /** 요약 카드에 보여 줄 칸 */
        val summary: Boolean = false,
    )

    val sections = listOf("1. 요청 및 출동", "2. 인적사항", "3. 출발시 환자상태", "4. 이송 중 경과·처치", "5. 이송차량·이송자")

    private fun choice(vararg o: String) = Kind.Choice(o.toList())
    private val avpuChoice = choice("A", "V", "P", "U")

    val fields: List<Field> = listOf(
        // 1. 요청 및 출동에 관한 사항
        Field("requestedAt", "요청 일시", 1, required = true),
        Field("requester", "요청자(기관)", 1, required = true),
        Field("requesterPhone", "요청자 연락처", 1),
        Field("dispatchedAt", "출동 일시", 1, required = true),
        Field("transportKind", "이송의 종류", 1, choice("현장 이송", "의료기관간 이송", "기타"), required = true),
        Field("sceneArrivedAt", "현장도착 일시", 1, required = true),
        Field("originAddress", "출발지 주소", 1, required = true),
        Field("originName", "출발지 명칭", 1),
        Field("transportStartedAt", "이송개시 일시", 1, required = true),
        Field("transportEndedAt", "이송종료 일시", 1, required = true),
        Field("destination", "도착기관 명칭", 1, required = true, summary = true),
        Field("distanceKm", "이송거리(km)", 1, summary = true),
        Field("handoverDoctor", "환자인계의사(면허번호·성명)", 1),
        Field("receiveDoctor", "환자인수의사(면허번호·성명)", 1, required = true),
        Field("directorDoctor", "이송지도의사(소속·성명)", 1, required = true),
        Field("doctorComm", "의사통신방법", 1, choice("전화", "TRS", "기타"), required = true),
        Field("selector", "의료기관 선정자", 1, choice("구급대(이송자)", "환자/보호자", "의사", "기타"), required = true),
        Field("selectReason", "선정 이유", 1, choice("전문진료 가능", "근거리", "치료받던 병원", "환자/보호자 원함", "기타"), required = true),
        Field("selectMethod", "선정 방법", 1, choice("이송정보체계", "직접 연락", "구급상황관리센터", "자체 판단", "기타"), required = true),
        // 2. 인적사항
        Field("patientName", "환자 성명", 2, required = true, summary = true),
        Field("patientBirth", "생년월일", 2, required = true),
        Field("patientSex", "성별", 2, choice("남", "여", "확인불가"), required = true, summary = true),
        Field("patientAddress", "주소", 2, required = true),
        Field("patientPhone", "연락처", 2),
        Field("guardianName", "보호자 성명", 2),
        Field("guardianPhone", "보호자 연락처", 2),
        Field("guardianRelation", "보호자 관계", 2, choice("없음", "부모", "자녀", "친척", "친지", "기타")),
        // 3. 출발시 환자상태
        Field("severity", "중증도", 3, choice("응급", "비응급", "사망"), required = true, summary = true),
        Field("category", "분류", 3, choice("질병", "질병외"), required = true, summary = true),
        Field("suspected", "의심질환명", 3, required = true, summary = true),
        Field("avpu", "의식수준", 3, avpuChoice, required = true, summary = true),
        Field("vitals", "생체징후(혈압·맥박·호흡·체온)", 3, required = true, summary = true),
        Field("careAirway", "기도", 3),
        Field("careBreathing", "호흡", 3),
        Field("careCirculation", "순환", 3),
        Field("careDrug", "약품", 3),
        Field("careFix", "고정", 3),
        Field("careEtc", "기타 처치", 3),
        Field("notes", "기타 소견 및 처치", 3, Kind.Multiline, summary = true),
        // 4. 이송 중 경과 및 처치
        Field("avpu2", "의식수준(이송 중)", 4, avpuChoice, required = true),
        Field("vitals2", "생체징후(이송 중)", 4, required = true),
        Field("care2", "이송/도착시 처치상태", 4, Kind.Multiline, required = true),
        Field("notes2", "기타 소견 및 처치(이송 중)", 4, Kind.Multiline),
        // 5. 이송차량 및 이송자
        Field("agency", "소속기관명", 5, required = true),
        Field("vehicleKind", "이송차량", 5, choice("특수구급차", "일반구급차", "헬기", "기타"), required = true),
        Field("vehicleNo", "번호(등록·자격·면허)", 5, required = true),
        Field("crewName", "이송자 성명", 5, required = true),
        Field("crewGrade", "동승자 자격", 5, choice("1급 응급구조사", "2급 응급구조사", "간호사", "의사", "없음", "기타"), required = true),
        Field("driverName", "운전자 성명", 5, required = true),
    )

    fun field(id: String): Field? = fields.firstOrNull { it.id == id }

    /** 처치 칸들(기도·호흡·순환·약품·고정·기타) — 카드에서 "처치" 한 줄로 묶어 보여 준다 */
    val careFieldIds = listOf("careAirway", "careBreathing", "careCirculation", "careDrug", "careFix", "careEtc")

    /**
     * 통화 요약(AI)·출동 상태·확정 병원에서 채울 수 있는 칸만 채운다. 나머지는 사람이 적는다.
     * `times`는 앱이 기억해 둔 단계별 시각(epoch ms), `bodyCare`는 외상 도해에서 부위를 눌러 적은 처치("좌 다리 부목")다.
     */
    fun auto(
        patient: PatientInfo?, confirmed: MatchHospital?, ambulanceName: String?, apid: String?,
        times: Map<String, Long>, incident: GPS?, incidentAddress: String?, bodyCare: List<String> = emptyList(),
    ): Map<String, String> {
        val v = LinkedHashMap<String, String>()
        v["transportKind"] = "현장 이송"
        v["selector"] = "구급대(이송자)"
        v["selectMethod"] = "이송정보체계"
        v["doctorComm"] = "전화"
        v["vehicleKind"] = "특수구급차"
        ambulanceName?.let { v["agency"] = it }
        apid?.let { v["vehicleNo"] = it }
        for ((key, t) in times) v[key] = stamp(t)
        // 주소를 못 구했을 때만 좌표를 적는다(hub가 카카오로 바꿔 준다)
        if (!incidentAddress.isNullOrEmpty()) v["originAddress"] = incidentAddress
        else if (incident != null) v["originAddress"] = "위도 %.5f, 경도 %.5f".format(incident.lat, incident.lng)

        if (confirmed != null) {
            v["destination"] = confirmed.name
            v["distanceKm"] = "%.1f".format(confirmed.roadDistanceKm ?: confirmed.distanceKm)
            v["selectReason"] = if (confirmed.specialtyMatch?.basis == "exact") "전문진료 가능" else "근거리"
        }
        if (patient == null) return v

        // 인적사항 — 이름·생년월일·주소는 통화에서 안 받는다(개인정보 최소 수집). 성별·나이만 적는다
        v["patientName"] = "확인불가"
        v["patientBirth"] = patient.patient?.let(::age)?.let { "확인불가($it)" } ?: "확인불가"
        patient.patient?.let { v["patientSex"] = if (it.contains("여")) "여" else if (it.contains("남")) "남" else "확인불가" }
        v["patientAddress"] = "확인불가"

        // 출발시 상태 — KTAS 1~3은 응급, 4~5는 비응급(서식의 3단계로 줄인다)
        val k = patient.ktasLevel
        if (k != null) v["severity"] = if (k <= 3) "응급" else "비응급"
        else patient.severityTag?.let { v["severity"] = if (it == "low") "비응급" else "응급" }
        v["category"] = if (isTrauma(patient)) "질병외" else "질병"
        v["suspected"] = listOfNotNull(patient.expectedDiagnosis, patient.chiefComplaint).firstOrNull() ?: ""
        DisplayLabels.avpu(patient.consciousness)?.let { v["avpu"] = it }
        patient.vitals?.lastOrNull()?.text?.takeIf { it.isNotEmpty() }?.let { v["vitals"] = it }
        val vitals = patient.vitals
        if (vitals != null && vitals.size > 1 && vitals.last().text.isNotEmpty()) {
            v["vitals2"] = vitals.last().text  // 측정이 2회 이상이면 마지막 것을 이송 중 칸에도 적어 둔다(고칠 수 있다)
            v["avpu2"] = v["avpu"] ?: ""
        }
        v.putAll(care((patient.treatment ?: emptyList()) + bodyCare))
        val symptoms = (patient.injuryStatus ?: emptyList()).joinToString(", ")
        // "[처치] …"는 외상 도해에서 보낸 것이라 이미 처치 칸에 들어가 있다 — 기타 소견에 또 적지 않는다
        val extra = (patient.extraNotes ?: emptyList()).map { it.text }.filter { !it.startsWith("[처치]") }.joinToString(" / ")
        v["notes"] = listOfNotNull(
            if (symptoms.isEmpty()) null else "증상: $symptoms",
            patient.onset?.let { "발생: $it" },
            if (extra.isEmpty()) null else "추가: $extra",
        ).joinToString("\n")
        return v
    }

    /** 통화 요약의 처치 목록 → 서식의 처치 줄(기도·호흡·순환·약품·고정·기타) */
    private fun care(treatments: List<String>): Map<String, String> {
        val out = LinkedHashMap<String, String>()
        fun add(key: String, text: String) { out[key] = out[key]?.let { "$it, $text" } ?: text }
        for (t in treatments) {
            when {
                t.contains("CPR") || t.contains("AED") || t.contains("지혈") || t.contains("순환보조") -> add("careCirculation", t)
                t.contains("기관내삽관") || t.contains("삽관") -> add("careAirway", t)
                t.contains("기도") -> add("careAirway", t)
                t.contains("산소") -> add("careBreathing", t)
                t.contains("BVM") || t.contains("인공호흡") -> add("careBreathing", t)
                t.contains("ECG") || t.contains("심전도") || t.contains("모니터") -> add("careCirculation", t)
                t.contains("정맥로") || t.contains("수액") || t.contains("IV") -> add("careCirculation", t)
                t.contains("투여") || t.contains("약") -> add("careDrug", t)
                t.contains("부목") || t.contains("고정") || t.contains("경추") || t.contains("척추") -> add("careFix", t)
                else -> add("careEtc", t)
            }
        }
        return out
    }

    /** 손상 기전이 보이면 '질병외'(서식 작성방법: 사고에 의한 경우는 질병외) */
    private fun isTrauma(p: PatientInfo): Boolean {
        val text = (listOfNotNull(p.expectedDiagnosis, p.chiefComplaint) + (p.injuryStatus ?: emptyList())).joinToString(" ")
        return listOf("사고", "교통", "추락", "낙상", "충돌", "자상", "열상", "골절", "화상", "중독", "익수", "폭행", "외상", "절단", "압궤").any { text.contains(it) }
    }

    private fun age(patient: String): String? = patient.takeWhile { it.isDigit() }.takeIf { it.isNotEmpty() }?.let { "${it}세" }

    fun stamp(millis: Long): String = SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.KOREA).format(Date(millis))

    /** 적힌 칸만 모아 한 줄씩. 병원은 이걸 '추가 정보'로 받는다(hub 계약을 바꾸지 않는다) */
    fun message(values: Map<String, String>): String {
        val lines = mutableListOf("[인계확인서] 출동 및 처치 기록지")
        for (section in 1..5) {
            val rows = fields.filter { it.section == section }.mapNotNull { f ->
                val v = (values[f.id] ?: "").trim()
                if (v.isEmpty()) null else "${f.label}: ${v.replace("\n", " / ")}"
            }
            if (rows.isNotEmpty()) lines += "■ " + sections[section - 1] + " — " + rows.joinToString(" · ")
        }
        return lines.joinToString("\n")
    }
}
