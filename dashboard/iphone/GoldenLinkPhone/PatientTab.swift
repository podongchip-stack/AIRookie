import GoldenLinkCore
import SwiftUI
import UIKit

// [환자 정보] 탭 — 아이패드 구급차 앱의 같은 이름 화면(CallSummaryCard · 추가 정보 · HandoverCard)을 세로 한 열로 옮겼다(안드로이드 PatientTab.kt와 같다).
// 위부터: 통화 요약·구조화(+수정·확인) → 추가 정보 전송 → 인계확인서. 통화 요약은 AI, 병원에 가는 값은 구급대원이 확인한 값이다.

func ktasColor(_ k: Int) -> Color {
    switch k { case 1: Color(hex: 0xD93025); case 2: Color(hex: 0xE8590C); case 3: Color(hex: 0xC75B00); case 4: Color(hex: 0x4E8B1F); default: Color(hex: 0x168A55) }
}
func ktasSoft(_ k: Int) -> Color { k <= 2 ? AD.redSoft : (k == 3 ? AD.orangeSoft : AD.greenSoft) }

/// 중증도 알약 색·문구 — Theme.severity
private func severity(_ tag: String?) -> (Color, Color, String) {
    switch tag {
    case "high": (AD.redSoft, AD.red, "중증 의심")
    case "medium": (AD.orangeSoft, AD.orange, "중등도 의심")
    case "low": (AD.greenSoft, AD.green, "경증 의심")
    default: (AD.chip, AD.ink3, "중증도 미상")
    }
}

private let pages = ["외상", "통화 요약", "인계확인서"]

struct PatientTab: View {
    @Environment(PhoneModel.self) private var m
    @State private var page = 1  // 가운데(통화 요약)가 기본 — 왼쪽에 외상, 오른쪽에 인계확인서

    var body: some View {
        if let p = m.patient {
            VStack(spacing: 8) {
                pageBar
                TabView(selection: $page) {
                    BodyPage(p: p).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center).tag(0)
                    VStack(spacing: 10) { SummaryCard(p: p); ExtraNoteCard(p: p) }
                        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center).tag(1)
                    HandoverCard(p: p).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center).tag(2)
                }
                .tabViewStyle(.page(indexDisplayMode: .never))
            .background(KeyboardDismissArea())
            }
        } else {
            waiting
        }
    }

    @ViewBuilder private var waiting: some View {
        // 통화 요약이 오기 전 — 지금 뭘 하는 단계인지만 보여 준다(빈 서식을 보여주지 않는다)
        if !m.hasIncident {
            StatusPanel(icon: "car", tint: AD.gray, title: "출동 대기 중", detail: "새 사건이 들어오면 자동으로 환자 정보 화면으로 넘어갑니다.")
        } else if m.phase == .dispatching {
            StatusPanel(icon: "light.beacon.max.fill", tint: AD.blue, title: "현장으로 이송 중",
                        pulse: true, detail: "사고 현장으로 이동하고 있습니다. 현장에 도착하면 상황 판단으로 넘어갑니다.")
        } else {
            StatusPanel(icon: "stethoscope", tint: AD.orange, title: "상황 판단 중", pulse: m.status?.state == "calling",
                        detail: m.status?.state == "calling" ? "통화 내용을 받아 환자 정보를 구조화하고 있습니다." : "현장 확인 중입니다. 통화가 요약되면 환자 정보가 올라옵니다.")
        }
    }

    /// 가로로 밀어 넘기는 세 페이지의 표시줄 — 누르면 그 페이지로 간다
    private var pageBar: some View {
        HStack(spacing: 0) {
            ForEach(Array(pages.enumerated()), id: \.offset) { i, title in
                let on = i == page
                Button { withAnimation { page = i } } label: {
                    VStack(spacing: 0) {
                        Text(title).font(.system(size: 14, weight: on ? .bold : .medium)).foregroundStyle(on ? AD.blue : AD.muted)
                            .padding(.vertical, 8).frame(maxWidth: .infinity)
                        Rectangle().fill(on ? AD.blue : .clear).frame(height: 2.5)
                    }
                }
                .buttonStyle(.plain)
            }
        }
        .overlay(alignment: .bottom) { Rectangle().fill(AD.line).frame(height: 1) }
    }
}

private struct Field<Content: View>: View {
    let label: String
    @ViewBuilder let content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.system(size: 11.5)).foregroundStyle(AD.sub)
            content
        }
    }
}

// MARK: - 통화 요약 · 구조화

private struct SummaryCard: View {
    @Environment(PhoneModel.self) private var m
    let p: PatientInfo
    @State private var showEdit = false
    @State private var showTranscript = false

    var body: some View {
        Card {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top, spacing: 8) {
                    Text("통화 요약 · 구조화").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                    Spacer()

                }
                HStack(spacing: 6) {
                    Pill(text: "AI 처리", fg: AD.blue, bg: AD.blueSoft, bold: true)
                    if p.confirmedBy == "paramedic" { Pill(text: "구급대원 확인", fg: AD.green, bg: AD.greenSoft, bold: true) }
                    else { Pill(text: "확인 전", fg: AD.orange, bg: AD.orangeSoft, bold: true) }
                    if (p.callRound ?? 1) > 1 { Pill(text: "\(p.callRound!)차 통화로 갱신", fg: AD.orange, bg: AD.orangeSoft, bold: true) }
                }
                Field(label: "예상 병명") { Text(p.expectedDiagnosis ?? "—").font(.system(size: 14, weight: .semibold)).foregroundStyle(AD.navy) }
                Field(label: "증상") {
                    let s = p.injuryStatus ?? []
                    if s.isEmpty { Text("—").font(.system(size: 12)).foregroundStyle(AD.muted) }
                    else {
                        WrapChips(s)
                    }
                }
                let sv = severity(p.severityTag)
                HStack(spacing: 6) {
                    Pill(text: sv.2, fg: sv.1, bg: sv.0, bold: true)
                    if let k = p.ktasLevel { Pill(text: "KTAS \(k)", fg: ktasColor(k), bg: ktasSoft(k), bold: true) }
                    let line = [p.patient, p.chiefComplaint, p.consciousness.map { "의식 \($0)" }].compactMap { $0 }.joined(separator: " · ")
                    if !line.isEmpty { Text(line).font(.system(size: 12)).foregroundStyle(AD.ink3) }
                }
                let onset = [p.onset.map { "발생 \($0)" }, p.requiredDepartment.map { "필요 진료과 \($0)" }].compactMap { $0 }.joined(separator: " · ")
                if !onset.isEmpty { Text(onset).font(.system(size: 12)).foregroundStyle(AD.sub) }
                if let v = p.vitals?.last?.text, !v.isEmpty {
                    (Text("활력징후  ").font(.system(size: 12, weight: .bold)).foregroundStyle(AD.navy) + Text(v).font(.system(size: 12)).foregroundStyle(AD.ink3)
                     + ((p.vitals?.count ?? 0) > 1 ? Text("  (측정 \(p.vitals!.count)회 중 최근)").font(.system(size: 12)).foregroundStyle(AD.muted) : Text("")))
                }
                if let prev = p.previousCalls, !prev.isEmpty {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(prev) { u in
                            Text("\(u.callRound)차 통화 · \(severity(u.severityTag).2) · \(u.expectedDiagnosis ?? "")" + (u.ktasLevel.map { " · KTAS \($0)" } ?? ""))
                                .font(.system(size: 11.5)).foregroundStyle(AD.sub)
                        }
                    }
                    .padding(.horizontal, 10).padding(.vertical, 6)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(AD.chip, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                }
                if !m.transcriptLines.isEmpty {
                    Button(showTranscript ? "자막 접기" : "자막 \(m.transcriptLines.count)줄") { showTranscript.toggle() }
                        .font(.system(size: 11, weight: .medium)).foregroundStyle(AD.blue)
                        .padding(.horizontal, 10).padding(.vertical, 3).background(AD.blueSoft, in: Capsule())
                    if showTranscript {
                        VStack(alignment: .leading, spacing: 3) {
                                ForEach(Array(m.transcriptLines.suffix(30).enumerated()), id: \.offset) { _, l in
                                    Text(l).font(.system(size: 12)).foregroundStyle(AD.ink)
                                }
                        }
                        .padding(8)
                        .background(AD.chip, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                }
                HStack(spacing: 8) {
                    Button { showEdit = true } label: {
                        Text("수정").font(.system(size: 15, weight: .bold)).foregroundStyle(AD.blue)
                            .frame(maxWidth: .infinity, minHeight: 44).background(AD.blueSoft, in: RoundedRectangle(cornerRadius: 14))
                    }
                }.buttonStyle(.plain)
            }
        }
        .sheet(isPresented: $showEdit) { SummaryEditSheet(p: p) }
    }
}

private struct WrapChips: View {
    let items: [String]
    init(_ items: [String]) { self.items = items }
    var body: some View {
        FlowLayout(spacing: 6) { ForEach(items, id: \.self) { Pill(text: $0) } }
    }
}

/// 간단한 줄바꿈 칩 레이아웃(FlowRow 대응)
struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? .infinity
        var x: CGFloat = 0, y: CGFloat = 0, lineHeight: CGFloat = 0
        for v in subviews {
            let size = v.sizeThatFits(.unspecified)
            if x + size.width > width, x > 0 { x = 0; y += lineHeight + spacing; lineHeight = 0 }
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
        return CGSize(width: width.isFinite ? width : x, height: y + lineHeight)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x: CGFloat = bounds.minX, y: CGFloat = bounds.minY, lineHeight: CGFloat = 0
        for v in subviews {
            let size = v.sizeThatFits(.unspecified)
            if x + size.width > bounds.maxX, x > bounds.minX { x = bounds.minX; y += lineHeight + spacing; lineHeight = 0 }
            v.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
            x += size.width + spacing
            lineHeight = max(lineHeight, size.height)
        }
    }
}

/// 통화 요약 확인·수정 — 바뀐 칸만 hub `patient_override`로 보낸다. 아무 칸도 안 고치면 "수정 없이 확인". 순위 칸이 바뀌면 hub가 다시 매칭한다
private struct SummaryEditSheet: View {
    @Environment(PhoneModel.self) private var m
    @Environment(\.dismiss) private var dismiss
    let p: PatientInfo
    @State private var diagnosis = ""
    @State private var symptoms = ""
    @State private var ktas = 0
    @State private var department = ""
    @State private var complaint = ""

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Text("취소").foregroundStyle(AD.ink3).onTapGesture { dismiss() }
                Spacer()
                Text("통화 요약 확인·수정").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Spacer()
                Text("확인·전송").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.blue).onTapGesture { apply() }
            }
            ScrollView {
                VStack(alignment: .leading, spacing: 10) {
                    Card {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("예상 병명").font(.system(size: 12)).foregroundStyle(AD.sub)
                            TextField("예상 병명", text: $diagnosis)
                            if diagnosis.trimmingCharacters(in: .whitespaces).isEmpty {
                                Text("비울 수 없습니다 — 그대로 두려면 손대지 않아도 됩니다").font(.system(size: 11)).foregroundStyle(AD.muted)
                            }
                        }
                    }
                    Card {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("증상 (쉼표로 구분)").font(.system(size: 12)).foregroundStyle(AD.sub)
                            TextField("증상", text: $symptoms)
                        }
                    }
                    Card {
                        VStack(alignment: .leading, spacing: 8) {
                            Text("KTAS").font(.system(size: 12)).foregroundStyle(AD.sub)
                            HStack(spacing: 6) {
                                ForEach(0...5, id: \.self) { k in
                                    let on = ktas == k
                                    Text(k == 0 ? "—" : "\(k)").font(.system(size: 14, weight: .bold)).foregroundStyle(on ? .white : AD.ink3)
                                        .frame(maxWidth: .infinity).padding(.vertical, 10)
                                        .background(on ? AD.blue : AD.chip, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                                        .onTapGesture { ktas = k }
                                }
                            }
                        }
                    }
                    Card {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("필요 진료과").font(.system(size: 12)).foregroundStyle(AD.sub)
                            TextField("필요 진료과", text: $department)
                        }
                    }
                    Card {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("주 호소").font(.system(size: 12)).foregroundStyle(AD.sub)
                            TextField("주 호소", text: $complaint)
                        }
                    }
                }
            }
        }
        .scrollDisabled(true)
        .scrollBounceBehavior(.basedOnSize)
        .padding(16)
        .background(AD.bg.ignoresSafeArea())
        .onAppear {
            diagnosis = p.expectedDiagnosis ?? ""
            symptoms = (p.injuryStatus ?? []).joined(separator: ", ")
            ktas = p.ktasLevel ?? 0
            department = p.requiredDepartment ?? ""
            complaint = p.chiefComplaint ?? ""
        }
    }

    private func apply() {
        let symptomList = symptoms.split(whereSeparator: { ",;\n".contains($0) }).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
        let diagnosisChanged = !diagnosis.trimmingCharacters(in: .whitespaces).isEmpty && diagnosis.trimmingCharacters(in: .whitespaces) != (p.expectedDiagnosis ?? "")
        let symptomsChanged = symptomList != (p.injuryStatus ?? [])
        let ktasChanged = ktas != 0 && ktas != p.ktasLevel
        let deptChanged = department.trimmingCharacters(in: .whitespaces) != (p.requiredDepartment ?? "")
        let complaintChanged = complaint.trimmingCharacters(in: .whitespaces) != (p.chiefComplaint ?? "")
        let ok = m.sendPatientOverride(
            expectedDiagnosis: diagnosisChanged ? diagnosis.trimmingCharacters(in: .whitespaces) : nil,
            injuryStatus: symptomsChanged ? symptomList : nil,
            ktasLevel: ktasChanged ? ktas : nil,
            requiredDepartment: deptChanged ? department.trimmingCharacters(in: .whitespaces) : nil,
            chiefComplaint: complaintChanged ? complaint.trimmingCharacters(in: .whitespaces) : nil)
        if ok { dismiss() }
    }
}

// MARK: - 추가 정보

/// 통화 요약에 없는 것(보호자 동승·복용약·특이사항)을 구급대원이 적어 후보 병원들에 보낸다
private struct ExtraNoteCard: View {
    @Environment(PhoneModel.self) private var m
    let p: PatientInfo
    @FocusState private var editing: Bool

    var body: some View {
        // 인계확인서·외상 도해 처치는 각자 자리에서 따로 보이므로 여기서는 직접 적은 것만 센다
        let mine = (p.extraNotes ?? []).filter { !$0.text.hasPrefix("[인계확인서]") && !$0.text.hasPrefix("[처치]") }
        Card {
            VStack(alignment: .leading, spacing: 8) {
                Text("추가 정보").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                ForEach(mine.suffix(3)) { n in Text("· \(n.text)").font(.system(size: 12)).foregroundStyle(AD.ink3) }
                TextField("예: 보호자 동승, 와파린 복용 중", text: Bindable(m).extraNoteDraft, axis: .vertical).lineLimit(2...4).focused($editing)
                    .padding(8).background(AD.chip, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                Button { if m.sendExtraNote(m.extraNoteDraft) { m.extraNoteDraft = ""; editing = false } } label: {
                    HStack(spacing: 8) { Image(systemName: "paperplane.fill"); Text("병원에 전달").fontWeight(.bold) }
                        .font(.system(size: 15)).foregroundStyle(.white).frame(maxWidth: .infinity, minHeight: 44)
                        .background(m.extraNoteDraft.trimmingCharacters(in: .whitespaces).isEmpty || m.paused ? AD.control : AD.blue, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
                .buttonStyle(.plain).disabled(m.extraNoteDraft.trimmingCharacters(in: .whitespaces).isEmpty)
            }
        }
    }
}

// MARK: - 인계확인서

private struct HandoverCard: View {
    @Environment(PhoneModel.self) private var m
    let p: PatientInfo
    @State private var edits: [String: String] = [:]
    @State private var showSheet = false

    var body: some View {
        let auto = Handover.auto(patient: p, confirmed: m.confirmed, ambulanceName: m.identity?.name, apid: m.apid,
                                 times: m.phaseTimes, incident: m.mySim?.incident, incidentAddress: m.incidentAddress, bodyCare: m.bodyEdits.careLines)
        let values = auto.merging(edits) { _, new in new }
        let value: (String) -> String = { (values[$0] ?? "").trimmingCharacters(in: .whitespaces) }
        let careText = Handover.careFieldIds.flatMap { id -> [String] in
            let v = value(id)
            guard let label = Handover.field(id)?.label, !v.isEmpty else { return [] }
            return v.split(separator: ",").map { "\(label) \($0.trimmingCharacters(in: .whitespaces))" }
        }.joined(separator: "\n")
        let sentCount = (p.extraNotes ?? []).filter { $0.text.hasPrefix("[인계확인서]") }.count

        Card {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("인계확인서").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                    Spacer()
                    Button { showSheet = true } label: {
                        HStack(spacing: 4) { Image(systemName: "square.and.pencil"); Text("수정").fontWeight(.bold) }
                            .font(.system(size: 13)).foregroundStyle(AD.blue)
                            .padding(.horizontal, 12).padding(.vertical, 7).background(AD.blueSoft, in: Capsule())
                    }.buttonStyle(.plain)
                }
                VStack(alignment: .leading, spacing: 6) {
                    CaseEditStatusView(sync: m.caseEdits)
                    ForEach(Handover.fields.filter(\.summary)) { f in
                        if f.id == "notes", !careText.isEmpty { SummaryRow(label: "처치", text: careText, tag: "자동") }
                        let v = value(f.id)
                        SummaryRow(label: f.id == "notes" ? "기타 소견(증상·발생)" : f.label, text: v.isEmpty ? "미입력" : v, empty: v.isEmpty,
                                   tag: edits[f.id] != nil ? "수정" : (v.isEmpty ? nil : "자동"))
                    }
                }
                if sentCount > 0 { Pill(text: "병원에 전달 \(sentCount)회", fg: AD.green, bg: AD.greenSoft, bold: true) }
            }
        }
        .onAppear { edits = Handover.loadEdits(m.caseId) }
        .onChange(of: m.recordsRev) { _, _ in edits = Handover.loadEdits(m.caseId) }
        .sheet(isPresented: $showSheet) {
            HandoverSheet(auto: auto, edits: edits, caseId: m.caseId, onSaved: { edits = $0 })
        }
    }
}

private struct SummaryRow: View {
    let label: String
    let text: String
    var empty = false
    var tag: String?
    var body: some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label).font(.system(size: 11.5)).foregroundStyle(AD.sub).frame(width: 86, alignment: .leading)
            Text(text).font(.system(size: 13, weight: empty ? .regular : .semibold)).foregroundStyle(empty ? AD.muted : AD.ink).frame(maxWidth: .infinity, alignment: .leading)
            if let tag { Pill(text: tag, fg: tag == "수정" ? AD.orange : AD.blue, bg: tag == "수정" ? AD.orangeSoft : AD.blueSoft) }
        }
    }
}

/// 인계확인서 전체 — 전체 화면. 칸마다 이름(필수는 *)과 입력. 자동으로 채운 칸에는 "자동", 고친 칸에는 "수정" 표시.
/// [저장 · 병원에 전달]을 누르면 자동값과 다른 칸만 기기에 저장하고 적힌 칸 전체를 한 덩이 글로 병원에도 보낸다
private struct HandoverSheet: View {
    @Environment(PhoneModel.self) private var m
    @Environment(\.dismiss) private var dismiss
    let auto: [String: String]
    let edits: [String: String]
    let caseId: String?
    let onSaved: ([String: String]) -> Void
    @State private var draft: [String: String] = [:]
    @State private var sharedBase: [String: String] = [:]
    @State private var touched: Set<String> = []  // 서식을 연 뒤 사람이 손댄 칸 — 열어 둔 채 새 통화·출동 소식이 와도 이 칸은 덮지 않는다

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Text("취소").foregroundStyle(AD.ink3).onTapGesture { dismiss() }
                Text("출동 및 처치 기록지").font(.system(size: 15, weight: .black)).foregroundStyle(AD.navy).frame(maxWidth: .infinity, alignment: .leading)
                Text("자동값").foregroundStyle(AD.ink3).font(.system(size: 13)).onTapGesture { draft = auto; touched = Set(edits.keys).union(m.caseEdits.handover.keys) }
                Text("저장·전달").foregroundStyle(m.paused ? AD.gray : AD.blue).fontWeight(.bold).onTapGesture { if !m.paused { save() } }
            }
            .padding(.horizontal, 24).padding(.top, 22).padding(.bottom, 14).background(.white)

            ScrollView {
                VStack(alignment: .leading, spacing: 14) {
                    ForEach(1...5, id: \.self) { section in
                        Text(Handover.sections[section - 1]).font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy)
                        VStack(alignment: .leading, spacing: 12) {
                            ForEach(Handover.fields.filter { $0.section == section }) { f in
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack(spacing: 6) {
                                        Text(f.label + (f.required ? " *" : "")).font(.system(size: 12, weight: .semibold)).foregroundStyle(AD.ink3)
                                        if edits[f.id] != nil { Pill(text: "수정", fg: AD.orange, bg: AD.orangeSoft) }
                                        else if !(auto[f.id] ?? "").isEmpty { Pill(text: "자동", fg: AD.blue, bg: AD.blueSoft) }
                                    }
                                    fieldInput(f)
                                }
                            }
                        }
                        .padding(12)
                        .background(.white, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).strokeBorder(AD.line))
                    }
                }
                .padding(14)
            }
        }
        .background(AD.bg.ignoresSafeArea())
        .onAppear {
            draft = auto.merging(edits) { _, n in n }
            sharedBase = m.caseEdits.fields
        }
        .onReceive(m.caseEdits.$fields) { fields in
            for f in Handover.fields where !touched.contains(f.id) {
                draft[f.id] = fields["h:" + f.id] ?? auto[f.id] ?? ""
                sharedBase["h:" + f.id] = fields["h:" + f.id]
            }
        }
        .onChange(of: auto) { _, fresh in
            for (id, value) in fresh where !touched.contains(id) {
                draft[id] = m.caseEdits.fields["h:" + id] ?? value
            }
        }
    }

    @ViewBuilder private func fieldInput(_ f: Handover.Field) -> some View {
        switch f.kind {
        case .choice(let options):
            FlowLayout(spacing: 6) {
                ForEach(options, id: \.self) { o in
                    let on = draft[f.id] == o
                    Text(o).font(.system(size: 13, weight: .medium)).foregroundStyle(on ? .white : AD.ink3)
                        .padding(.horizontal, 12).padding(.vertical, 7)
                        .background(on ? AD.blue : AD.chip, in: Capsule())
                        .onTapGesture { set(f.id, on ? "" : o) }
                }
            }
        case .multiline:
            TextField(f.label, text: Binding(get: { draft[f.id] ?? "" }, set: { set(f.id, $0) }), axis: .vertical).lineLimit(2...6)
        case .text:
            TextField(f.label, text: Binding(get: { draft[f.id] ?? "" }, set: { set(f.id, $0) }))
        }
    }

    private func set(_ id: String, _ v: String) { draft[id] = v; touched.insert(id) }

    private func save() {
        guard let caseId, caseId == m.caseId else { m.show("사건이 변경되어 저장하지 못했습니다."); return }
        m.shareHandover(caseId: caseId, draft: draft, auto: auto, touched: touched, base: sharedBase)
        m.snapshotCase(caseId)
        onSaved(m.caseEdits.handover)
        m.sendExtraNote(Handover.message(draft))
        dismiss()
    }
}
