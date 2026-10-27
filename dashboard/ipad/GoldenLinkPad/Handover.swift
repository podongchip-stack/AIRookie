import Foundation

/// 인계확인서 = **출동 및 처치 기록지**(응급의료에 관한 법률 시행규칙 [별지 제16호서식], 2019-09-27 개정)의 칸들.
///
/// 칸을 구조체 프로퍼티로 두지 않고 **목록(`fields`)** 으로 둔다 — 서식이 바뀌면 이 목록만 고치면 화면·요약·전송이 따라온다.
/// 값은 두 겹이다: 통화 요약·출동 상태에서 **자동으로 채운 값**(`auto`)과 구급대원이 **고친 값**(`edits`, 기기에 사건별 저장).
/// 보여줄 때는 `edits[id] ?? auto[id]` — 그래서 새 통화 회차가 와서 자동값이 바뀌어도 구급대원이 고친 칸은 그대로 남는다.
/// 서명·면허번호처럼 앱이 알 수 없는 칸은 빈칸이고, 그 칸은 사람이 채운다.
enum Handover {
    enum Kind: Equatable {
        case text
        case multiline
        case choice([String])
    }

    struct Field: Identifiable, Equatable {
        let id: String
        let label: String
        let section: Int
        var kind: Kind = .text
        /// 서식의 '*' 칸(반드시 적는 칸)
        var required = false
        /// 요약 카드에 보여 줄 칸
        var summary = false
    }

    static let sections = ["1. 요청 및 출동", "2. 인적사항", "3. 출발시 환자상태", "4. 이송 중 경과·처치", "5. 이송차량·이송자"]

    static let fields: [Field] = [
        // 1. 요청 및 출동에 관한 사항
        .init(id: "requestedAt", label: "요청 일시", section: 1, required: true),
        .init(id: "requester", label: "요청자(기관)", section: 1, required: true),
        .init(id: "requesterPhone", label: "요청자 연락처", section: 1),
        .init(id: "dispatchedAt", label: "출동 일시", section: 1, required: true),
        .init(id: "transportKind", label: "이송의 종류", section: 1, kind: .choice(["현장 이송", "의료기관간 이송", "기타"]), required: true),
        .init(id: "sceneArrivedAt", label: "현장도착 일시", section: 1, required: true),
        .init(id: "originAddress", label: "출발지 주소", section: 1, required: true),
        .init(id: "originName", label: "출발지 명칭", section: 1),
        .init(id: "transportStartedAt", label: "이송개시 일시", section: 1, required: true),
        .init(id: "transportEndedAt", label: "이송종료 일시", section: 1, required: true),
        .init(id: "destination", label: "도착기관 명칭", section: 1, required: true, summary: true),
        .init(id: "distanceKm", label: "이송거리(km)", section: 1, summary: true),
        .init(id: "handoverDoctor", label: "환자인계의사(면허번호·성명)", section: 1),
        .init(id: "receiveDoctor", label: "환자인수의사(면허번호·성명)", section: 1, required: true),
        .init(id: "directorDoctor", label: "이송지도의사(소속·성명)", section: 1, required: true),
        .init(id: "doctorComm", label: "의사통신방법", section: 1, kind: .choice(["전화", "TRS", "기타"]), required: true),
        .init(id: "selector", label: "의료기관 선정자", section: 1, kind: .choice(["구급대(이송자)", "환자/보호자", "의사", "기타"]), required: true),
        .init(id: "selectReason", label: "선정 이유", section: 1, kind: .choice(["전문진료 가능", "근거리", "치료받던 병원", "환자/보호자 원함", "기타"]), required: true),
        .init(id: "selectMethod", label: "선정 방법", section: 1, kind: .choice(["이송정보체계", "직접 연락", "구급상황관리센터", "자체 판단", "기타"]), required: true),
        // 2. 인적사항
        .init(id: "patientName", label: "환자 성명", section: 2, required: true, summary: true),
        .init(id: "patientBirth", label: "생년월일", section: 2, required: true),
        .init(id: "patientSex", label: "성별", section: 2, kind: .choice(["남", "여", "확인불가"]), required: true, summary: true),
        .init(id: "patientAddress", label: "주소", section: 2, required: true),
        .init(id: "patientPhone", label: "연락처", section: 2),
        .init(id: "guardianName", label: "보호자 성명", section: 2),
        .init(id: "guardianPhone", label: "보호자 연락처", section: 2),
        .init(id: "guardianRelation", label: "보호자 관계", section: 2, kind: .choice(["없음", "부모", "자녀", "친척", "친지", "기타"])),
        // 3. 출발시 환자상태
        .init(id: "severity", label: "중증도", section: 3, kind: .choice(["응급", "비응급", "사망"]), required: true, summary: true),
        .init(id: "category", label: "분류", section: 3, kind: .choice(["질병", "질병외"]), required: true, summary: true),
        .init(id: "suspected", label: "의심질환명", section: 3, required: true, summary: true),
        .init(id: "avpu", label: "의식수준", section: 3, kind: .choice(["A", "V", "P", "U"]), required: true, summary: true),
        .init(id: "vitals", label: "생체징후(혈압·맥박·호흡·체온)", section: 3, required: true, summary: true),
        .init(id: "careAirway", label: "기도", section: 3),
        .init(id: "careBreathing", label: "호흡", section: 3),
        .init(id: "careCirculation", label: "순환", section: 3),
        .init(id: "careDrug", label: "약품", section: 3),
        .init(id: "careFix", label: "고정", section: 3),
        .init(id: "careEtc", label: "기타 처치", section: 3),
        .init(id: "notes", label: "기타 소견 및 처치", section: 3, kind: .multiline, summary: true),
        // 4. 이송 중 경과 및 처치
        .init(id: "avpu2", label: "의식수준(이송 중)", section: 4, kind: .choice(["A", "V", "P", "U"]), required: true),
        .init(id: "vitals2", label: "생체징후(이송 중)", section: 4, required: true),
        .init(id: "care2", label: "이송/도착시 처치상태", section: 4, kind: .multiline, required: true),
        .init(id: "notes2", label: "기타 소견 및 처치(이송 중)", section: 4, kind: .multiline),
        // 5. 이송차량 및 이송자
        .init(id: "agency", label: "소속기관명", section: 5, required: true, summary: true),
        .init(id: "vehicleKind", label: "이송차량", section: 5, kind: .choice(["특수구급차", "일반구급차", "헬기", "기타"]), required: true),
        .init(id: "vehicleNo", label: "번호(등록·자격·면허)", section: 5, required: true),
        .init(id: "crewName", label: "이송자 성명", section: 5, required: true),
        .init(id: "crewGrade", label: "동승자 자격", section: 5, kind: .choice(["1급 응급구조사", "2급 응급구조사", "간호사", "의사", "없음", "기타"]), required: true),
        .init(id: "driverName", label: "운전자 성명", section: 5, required: true),
    ]

    static func field(_ id: String) -> Field? { fields.first { $0.id == id } }

    // ── 자동 채움 ────────────────────────────────────────────────────────────
    /// 통화 요약(AI)·출동 상태·확정 병원에서 채울 수 있는 칸만 채운다. 나머지는 사람이 적는다.
    /// `times`는 앱이 기억해 둔 단계별 시각(출동·현장 도착·이송 시작·병원 도착)이다.
    static func auto(patient: PatientInfo?, confirmed: HospitalMatch?, ambulanceName: String?, apid: String?,
                     times: [String: Date], incident: GpsPoint?, incidentAddress: String?) -> [String: String] {
        var v: [String: String] = [:]
        v["transportKind"] = "현장 이송"
        v["selector"] = "구급대(이송자)"
        v["selectMethod"] = "이송정보체계"
        v["doctorComm"] = "전화"
        v["vehicleKind"] = "특수구급차"
        if let n = ambulanceName { v["agency"] = n }
        if let a = apid { v["vehicleNo"] = a }
        for (key, date) in times { v[key] = stamp(date) }
        // 주소를 못 구했을 때만 좌표를 적는다(hub가 카카오로 바꿔 준다)
        if let address = incidentAddress, !address.isEmpty { v["originAddress"] = address }
        else if let p = incident { v["originAddress"] = String(format: "위도 %.5f, 경도 %.5f", p.lat, p.lng) }

        if let c = confirmed {
            v["destination"] = c.name
            if let km = c.roadDistanceKm ?? Optional(c.distanceKm) { v["distanceKm"] = String(format: "%.1f", km) }
            v["selectReason"] = (c.specialtyMatch?.basis == "exact") ? "전문진료 가능" : "근거리"
        }
        guard let p = patient else { return v }

        // 인적사항 — 이름·생년월일·주소는 통화에서 안 받는다(개인정보 최소 수집). 성별·나이만 적는다
        v["patientName"] = "확인불가"
        v["patientBirth"] = p.patient.flatMap(age) .map { "확인불가(\($0))" } ?? "확인불가"
        if let s = p.patient { v["patientSex"] = s.contains("여") ? "여" : (s.contains("남") ? "남" : "확인불가") }
        v["patientAddress"] = "확인불가"

        // 출발시 상태 — KTAS 1~3은 응급, 4~5는 비응급(서식의 3단계로 줄인다)
        if let k = p.ktasLevel { v["severity"] = k <= 3 ? "응급" : "비응급" }
        else if let tag = p.severityTag { v["severity"] = tag == "low" ? "비응급" : "응급" }
        v["category"] = isTrauma(p) ? "질병외" : "질병"
        v["suspected"] = [p.expectedDiagnosis, p.chiefComplaint].compactMap { $0 }.first ?? ""
        if let c = Labels.avpu(p.consciousness) { v["avpu"] = c }
        if let last = p.vitals?.last, !last.text.isEmpty { v["vitals"] = last.text }
        if let two = p.vitals, two.count > 1, let m = two.last, !m.text.isEmpty {
            v["vitals2"] = m.text          // 측정이 2회 이상이면 마지막 것을 이송 중 칸에도 적어 둔다(고칠 수 있다)
            v["avpu2"] = v["avpu"] ?? ""
        }
        for (key, value) in care(p.treatment ?? []) { v[key] = value }
        let symptoms = (p.injuryStatus ?? []).joined(separator: ", ")
        let extra = (p.extraNotes ?? []).map(\.text).joined(separator: " / ")
        v["notes"] = [symptoms.isEmpty ? nil : "증상: " + symptoms,
                      p.onset.map { "발생: \($0)" },
                      extra.isEmpty ? nil : "추가: " + extra].compactMap { $0 }.joined(separator: "\n")
        return v
    }

    /// 통화 요약의 처치 목록 → 서식의 처치 줄(기도·호흡·순환·약품·고정·기타)
    private static func care(_ treatments: [String]) -> [String: String] {
        var out: [String: String] = [:]
        func add(_ key: String, _ text: String) { out[key] = out[key].map { $0 + ", " + text } ?? text }
        for t in treatments {
            switch true {
            case t.contains("기관내삽관"), t.contains("삽관"): add("careAirway", "기관내삽관")
            case t.contains("기도"): add("careAirway", t)
            case t.contains("산소"): add("careBreathing", "산소투여")
            case t.contains("BVM"), t.contains("인공호흡"): add("careBreathing", t)
            case t.contains("ECG"), t.contains("심전도"), t.contains("모니터"): add("careCirculation", "모니터링")
            case t.contains("정맥로"), t.contains("수액"), t.contains("IV"): add("careCirculation", t)
            case t.contains("투여"), t.contains("약"): add("careDrug", t)
            case t.contains("부목"), t.contains("고정"), t.contains("경추"), t.contains("척추"): add("careFix", t)
            default: add("careEtc", t)
            }
        }
        return out
    }

    /// 손상 기전이 보이면 '질병외'(서식 작성방법: 사고에 의한 경우는 질병외)
    private static func isTrauma(_ p: PatientInfo) -> Bool {
        let text = ([p.expectedDiagnosis, p.chiefComplaint].compactMap { $0 } + (p.injuryStatus ?? [])).joined(separator: " ")
        let words = ["사고", "교통", "추락", "낙상", "충돌", "자상", "열상", "골절", "화상", "중독", "익수", "폭행", "외상", "절단", "압궤"]
        return words.contains { text.contains($0) }
    }

    private static func age(_ patient: String) -> String? {
        let digits = patient.prefix { $0.isNumber }
        return digits.isEmpty ? nil : "\(digits)세"
    }

    static func stamp(_ d: Date) -> String {
        let f = DateFormatter()
        f.locale = Locale(identifier: "ko_KR")
        f.dateFormat = "yyyy-MM-dd HH:mm"
        return f.string(from: d)
    }

    // ── 저장(기기) ───────────────────────────────────────────────────────────
    /// 고친 칸만 사건별로 기기에 저장한다 — 자동값은 매번 다시 만든다(새 통화 회차가 와도 고친 칸은 유지)
    static func loadEdits(_ caseId: String?) -> [String: String] {
        guard let caseId, let data = UserDefaults.standard.data(forKey: key(caseId)),
              let v = try? JSONDecoder().decode([String: String].self, from: data) else { return [:] }
        return v
    }
    static func saveEdits(_ caseId: String?, _ edits: [String: String]) {
        guard let caseId else { return }
        UserDefaults.standard.set(try? JSONEncoder().encode(edits), forKey: key(caseId))
    }
    private static func key(_ caseId: String) -> String { "handover-" + caseId }

    // ── 병원 전달용 한 덩이 글 ────────────────────────────────────────────────
    /// 적힌 칸만 모아 한 줄씩. 병원은 이걸 '추가 정보'로 받는다(hub 계약을 바꾸지 않는다).
    static func message(_ values: [String: String]) -> String {
        var lines = ["[인계확인서] 출동 및 처치 기록지"]
        for section in 1...5 {
            let rows = fields.filter { $0.section == section }
                .compactMap { f -> String? in
                    let v = (values[f.id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                    return v.isEmpty ? nil : "\(f.label): \(v.replacingOccurrences(of: "\n", with: " / "))"
                }
            if !rows.isEmpty { lines.append("■ " + sections[section - 1] + " — " + rows.joined(separator: " · ")) }
        }
        return lines.joined(separator: "\n")
    }
}
