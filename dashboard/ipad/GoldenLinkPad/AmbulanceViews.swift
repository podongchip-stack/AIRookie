import SwiftUI

/// 왼쪽 열 — 통화 요약 · 구조화(웹 CallSummaryEditablePanel의 보기 전용판)
struct CallSummaryCard: View {
    @EnvironmentObject private var model: AppModel
    @State private var showTranscript = false
    @State private var showEdit = false

    /// true면 왼쪽 열의 남는 높이를 채운다(구급차 화면, 2026-10-16) — 내용은 위부터, 넘치면 카드 안에서 스크롤
    var fill = false
    /// 주면 내용 높이 그대로, 단 이 높이까지만 — 넘칠 때만 카드 안에서 스크롤(이송 확정 뒤 구급차 화면, 2026-10-16).
    /// 칸 높이 = 실제 내용 높이라 위아래 빈칸이 생기지 않는다(frame(maxHeight:)로 묶으면 칸이 최대치까지 커지고 카드가 가운데 떠서
    /// 큰 화면 패드에서 카드 사이가 벌어졌다)
    var fitMax: CGFloat? = nil
    @State private var contentH: CGFloat = 0

    var body: some View {
        Group {
            if let m = fitMax {
                ScrollView {
                    inner.onGeometryChange(for: CGFloat.self) { $0.size.height } action: { contentH = $0 }
                }
                .scrollIndicators(.hidden)
                .scrollBounceBehavior(.basedOnSize)
                .frame(height: max(0, min(contentH, m - 28)))
            } else if fill { ScrollView { inner }.scrollIndicators(.hidden) } else { inner }
        }
            .frame(maxWidth: .infinity, maxHeight: fill ? .infinity : nil, alignment: .topLeading)
            .card()
            .sheet(isPresented: $showEdit) {
                if let p = model.result?.patientInfo { CallSummaryEditSheet(p: p).environmentObject(model) }
            }
    }

    private var inner: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 1) {
                    Text("통화 요약 · 구조화").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                    Text("통화 음성 → 항목 추출").font(.system(size: 11.5)).foregroundStyle(AD.sub)
                }
                Spacer()
                // 구급대원 확인·수정(2026-10-27) — 누르면 칸을 고쳐 hub로 보낸다(보낸 칸만 바뀜)
                if model.result?.patientInfo != nil {
                    Button { showEdit = true } label: {
                        Label("수정", systemImage: "square.and.pencil")
                            .font(.system(size: 13, weight: .bold)).foregroundStyle(AD.blue)
                            .padding(.horizontal, 12).frame(minHeight: 32)
                            .background(AD.blueSoft).clipShape(Capsule())
                    }
                }
                VStack(alignment: .trailing, spacing: 4) {
                    if let p = model.result?.patientInfo {
                        if p.confirmedBy == "paramedic" { Pill(text: "구급대원 확인", bg: AD.greenSoft, fg: AD.green, bold: true) }
                        if (p.callRound ?? 1) > 1 { Pill(text: "\(p.callRound ?? 1)차 통화로 갱신", bg: AD.orangeSoft, fg: AD.orange, bold: true) }
                    }
                }
            }
            if let p = model.result?.patientInfo {
                field("예상 병명") { Text(p.expectedDiagnosis ?? "—").font(.system(size: 14, weight: .semibold)).foregroundStyle(AD.navy) }
                field("증상") {
                    FlowRow(items: p.injuryStatus ?? []) { Pill(text: $0, bg: AD.chip, fg: AD.ink3) }
                }
                HStack(spacing: 6) {
                    let sev = Theme.severity(p.severityTag)
                    Pill(text: sev.label, bg: sev.bg, fg: sev.fg, bold: true)
                    if let k = p.ktasLevel { Pill(text: "Pre-KTAS \(k)", bg: Theme.ktasSoft(k), fg: Theme.ktas(k), bold: true) }
                    Text([p.patient, p.chiefComplaint, p.consciousness.map { "의식 \($0)" }].compactMap { $0 }.joined(separator: " · "))
                        .font(.system(size: 12)).foregroundStyle(AD.ink3).lineLimit(2)
                }
                let onset = [p.onset.map { "발생 \($0)" }, p.requiredDepartment.map { "필요 진료과 \($0)" }].compactMap { $0 }.joined(separator: " · ")
                if !onset.isEmpty { Text(onset).font(.system(size: 12)).foregroundStyle(AD.sub) }
                if let v = p.vitals?.last, !v.text.isEmpty {
                    (Text("활력징후  ").bold().foregroundColor(AD.navy) + Text(v.text) + Text((p.vitals?.count ?? 0) > 1 ? "  (측정 \(p.vitals?.count ?? 0)회 중 최근)" : "").foregroundColor(AD.muted))
                        .font(.system(size: 12)).foregroundStyle(AD.ink3)
                }
                if let prev = p.previousCalls, !prev.isEmpty {
                    VStack(alignment: .leading, spacing: 2) {
                        ForEach(prev) { u in
                            Text("\(u.callRound)차 통화 · \(Theme.severity(u.severityTag).label) · \(u.expectedDiagnosis ?? "")\(u.ktasLevel.map { " · Pre-KTAS \($0)" } ?? "")")
                                .font(.system(size: 11.5)).foregroundStyle(AD.sub)
                        }
                    }
                    .padding(.horizontal, 10).padding(.vertical, 6).frame(maxWidth: .infinity, alignment: .leading)
                    .background(AD.chip).clipShape(RoundedRectangle(cornerRadius: 10))
                }
                if showTranscript { transcriptBox }
            } else if calling || !model.transcript.isEmpty {
                transcriptBox
            }
            if model.result?.patientInfo == nil, !calling, model.transcript.isEmpty {
                // 통화 전 — 칸만 두고 무엇이 채워질지 알려 준다
                Text(model.hasIncident ? "통화가 시작되면 인식한 말과 구조화된 항목이 여기에 채워집니다"
                                       : "사고가 발생해 통화가 연결되면 예상 병명·증상·중증도·활력징후가 여기에 채워집니다")
                    .font(.system(size: 13)).foregroundStyle(AD.muted)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.vertical, 6)
            }
            if model.result?.patientInfo != nil && !model.transcript.isEmpty {
                Divider().overlay(AD.line)
                HStack {
                    Spacer()
                    Button { showTranscript.toggle() } label: { Pill(text: showTranscript ? "자막 접기" : "자막 \(model.transcript.count)줄", bg: AD.blueSoft, fg: AD.blue) }
                }
            }
        }
    }

    private var calling: Bool { model.callStatus?.state == "calling" }

    private var transcriptBox: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 3) {
                ForEach(model.transcript.suffix(30)) { l in
                    Text(l.text).font(.system(size: 12)).foregroundStyle(AD.ink).frame(maxWidth: .infinity, alignment: .leading)
                }
            }
        }
        .frame(maxHeight: 140)
        .padding(8).background(AD.chip).clipShape(RoundedRectangle(cornerRadius: 10))
    }

    private func field<V: View>(_ label: String, @ViewBuilder _ content: () -> V) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.system(size: 11.5)).foregroundStyle(AD.sub)
            content()
        }
    }
}

/// 알약 줄바꿈 배치
struct FlowRow<Item: Hashable, V: View>: View {
    var items: [Item]
    @ViewBuilder var content: (Item) -> V
    var body: some View {
        if items.isEmpty {
            Text("—").font(.system(size: 12)).foregroundStyle(AD.muted)
        } else {
            FlowLayout(spacing: 6) { ForEach(items, id: \.self) { content($0) } }
        }
    }
}

struct FlowLayout: Layout {
    var spacing: CGFloat = 6
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let width = proposal.width ?? 300
        var x: CGFloat = 0, y: CGFloat = 0, rowH: CGFloat = 0
        for s in subviews {
            let sz = s.sizeThatFits(.unspecified)
            if x + sz.width > width, x > 0 { x = 0; y += rowH + spacing; rowH = 0 }
            x += sz.width + spacing; rowH = max(rowH, sz.height)
        }
        return CGSize(width: width, height: y + rowH)
    }
    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        var x = bounds.minX, y = bounds.minY, rowH: CGFloat = 0
        for s in subviews {
            let sz = s.sizeThatFits(.unspecified)
            if x + sz.width > bounds.maxX, x > bounds.minX { x = bounds.minX; y += rowH + spacing; rowH = 0 }
            s.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(sz))
            x += sz.width + spacing; rowH = max(rowH, sz.height)
        }
    }
}

/// 통화 요약 확인·수정 시트(2026-10-27) — 웹 대시보드 CallSummaryEditablePanel의 [수정] → [확인·전송]과 같은 규칙.
/// **바뀐 칸만** hub `patient_override`로 보내고(안 보낸 칸은 그대로), 아무 칸도 안 고치면 "수정 없이 확인"이다.
/// 예상 병명·KTAS·필요 진료과는 순위 칸이라 hub가 다시 매칭한다 — 넓힌 존·병원 승인은 유지된다.
struct CallSummaryEditSheet: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    let p: PatientInfo

    @State private var diagnosis = ""
    @State private var symptoms = ""
    @State private var ktas = 0          // 0 = 그대로
    @State private var department = ""
    @State private var complaint = ""

    private var symptomList: [String] {
        symptoms.split(whereSeparator: { ",;\n".contains($0) })
            .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }
    /// 예상 병명은 hub가 빈 값을 받지 않는다 — 지웠으면 보내지 않는다
    private var diagnosisChanged: Bool {
        let v = diagnosis.trimmingCharacters(in: .whitespaces)
        return !v.isEmpty && v != (p.expectedDiagnosis ?? "")
    }
    private var changedCount: Int {
        [diagnosisChanged, symptomList != (p.injuryStatus ?? []), ktas != (p.ktasLevel ?? 0),
         department.trimmingCharacters(in: .whitespaces) != (p.requiredDepartment ?? ""),
         complaint.trimmingCharacters(in: .whitespaces) != (p.chiefComplaint ?? "")].filter { $0 }.count
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("예상 병명") {
                    TextField("예: 경색 의심", text: $diagnosis)
                    if diagnosis.trimmingCharacters(in: .whitespaces).isEmpty {
                        Text("비울 수 없습니다 — 그대로 두려면 손대지 않아도 됩니다")
                            .font(.system(size: 12)).foregroundStyle(AD.orange)
                    }
                }
                Section("증상 (쉼표로 구분)") { TextField("예: 흉통, 호흡 곤란", text: $symptoms) }
                Section("Pre-KTAS") {
                    Picker("Pre-KTAS", selection: $ktas) {
                        Text("—").tag(0)
                        ForEach(1...5, id: \.self) { Text("\($0)").tag($0) }
                    }
                    .pickerStyle(.segmented)
                    Text("바꾸면 중증도도 1·2 중증 / 3 중등증 / 4·5 경증으로 따라 바뀝니다")
                        .font(.system(size: 12)).foregroundStyle(AD.sub)
                }
                Section("필요 진료과") { TextField("예: 순환기내과", text: $department) }
                Section("주 호소") { TextField("예: 심와부 통증", text: $complaint) }
                Section {
                    Text(changedCount == 0
                         ? "고친 칸이 없습니다 — [확인·전송]을 누르면 '수정 없이 확인'으로 전달됩니다"
                         : "고친 칸 \(changedCount)곳이 후보 병원들에 다시 전달됩니다")
                        .font(.system(size: 12.5)).foregroundStyle(AD.sub)
                }
            }
            .navigationTitle("통화 요약 확인·수정")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("취소") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("확인·전송") { if send() { dismiss() } }.bold()
                }
            }
            .onAppear {
                diagnosis = p.expectedDiagnosis ?? ""
                symptoms = (p.injuryStatus ?? []).joined(separator: ", ")
                ktas = p.ktasLevel ?? 0
                department = p.requiredDepartment ?? ""
                complaint = p.chiefComplaint ?? ""
            }
        }
    }

    private func send() -> Bool {
        func changed(_ v: String, _ was: String?) -> String? {
            let t = v.trimmingCharacters(in: .whitespaces)
            return t == (was ?? "") ? nil : t
        }
        return model.sendPatientOverride(
            expectedDiagnosis: diagnosisChanged ? diagnosis.trimmingCharacters(in: .whitespaces) : nil,
            injuryStatus: symptomList == (p.injuryStatus ?? []) ? nil : symptomList,
            ktasLevel: (ktas != 0 && ktas != p.ktasLevel) ? ktas : nil,
            requiredDepartment: changed(department, p.requiredDepartment),
            chiefComplaint: changed(complaint, p.chiefComplaint))
    }
}
