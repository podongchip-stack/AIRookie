import SwiftUI

/// [환자 정보] 탭 왼쪽 아래 — **인계확인서**(출동 및 처치 기록지, 별지 제16호서식).
/// 서식 전체를 카드에 펼치지 않고 **중요한 칸만 간략히** 보여 주고, [인계확인서 수정]으로 전체를 고친다.
/// 통화 요약(AI)·출동 상태·확정 병원에서 채울 수 있는 칸은 미리 채워 두고, 고친 칸은 기기에 사건별로 남는다(`Handover`).
/// 전달은 수정 화면의 [저장 · 병원에 전달] 하나로 일어난다(2026-10-28) — 적힌 칸을 한 덩이 글로 만들어 기존 '추가 정보' 통로(hub `patient_override.extraNote`)로 보낸다 —
/// hub·병원 화면 계약을 바꾸지 않고 바로 쓰려는 선택이고, 서식 그대로의 전송·출력은 hub에 칸을 만들 때 붙인다.
struct HandoverCard: View {
    @EnvironmentObject private var model: AppModel
    @State private var edits: [String: String] = [:]
    @State private var showSheet = false

    private var patient: PatientInfo? { model.result?.patientInfo }
    private var auto: [String: String] {
        Handover.auto(patient: patient, confirmed: model.confirmed, ambulanceName: model.ambulanceName,
                      apid: model.apid, times: model.phaseTimes, incident: model.sim?.incident,
                      incidentAddress: model.incidentAddress, bodyCare: model.bodyEdits.careLines)
    }
    private var values: [String: String] {
        auto.merging(edits) { _, edited in edited }
    }
    private func value(_ id: String) -> String {
        (values[id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
    }
    /// 처치 여섯 칸을 모아 **한 줄에 하나씩** — 한 칸에 여러 건이면(", "로 이어 적힌다) 그것도 줄을 나눈다
    /// ("고정 좌 다리 부목 고정, 우 팔 부목" → "고정 좌 다리 부목 고정" / "고정 우 팔 부목")
    private var careText: String {
        Handover.careFieldIds.flatMap { id -> [String] in
            let v = value(id)
            guard !v.isEmpty, let label = Handover.field(id)?.label else { return [] }
            return v.components(separatedBy: ", ")
                .map { $0.trimmingCharacters(in: .whitespaces) }
                .filter { !$0.isEmpty }
                .map { label + " " + $0 }
        }.joined(separator: "\n")
    }
    private var sentCount: Int { (patient?.extraNotes ?? []).filter { $0.text.hasPrefix("[인계확인서]") }.count }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                VStack(alignment: .leading, spacing: 1) {
                    Text("인계확인서").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                    Text("출동 및 처치 기록지 · 별지 제16호서식").font(.system(size: 11)).foregroundStyle(AD.sub)
                }
                Spacer(minLength: 0)
                // [수정]은 머리에 둔다(2026-10-27) — 통화 요약 카드의 [수정]과 같은 자리
                if model.hasIncident {
                    Button { showSheet = true } label: {
                        Label("인계확인서 수정", systemImage: "square.and.pencil")
                            .font(.system(size: 13, weight: .bold)).foregroundStyle(AD.blue)
                            .padding(.horizontal, 12).frame(minHeight: 32)
                            .background(AD.blueSoft).clipShape(Capsule())
                    }
                }
            }
            if model.hasIncident {
                // summary의 각 줄이 fixedSize(vertical: true)라 안 눌린다 — 내용이 길면 카드가 끝없이 커져
                // 위 통화 요약 칸까지 밀어 올리고 상단바를 침범했다. ScrollView로 감싸 카드 자체 높이 안에서만 스크롤되게 한다
                ScrollView { summary }.scrollIndicators(.hidden)
                // 전달은 [인계확인서 수정] 안에서 저장과 함께 일어난다(2026-10-28) — 카드엔 전달 이력만 남긴다
                HStack(spacing: 8) {
                    if sentCount > 0 { Pill(text: "병원에 전달 \(sentCount)회", bg: AD.greenSoft, fg: AD.green, bold: true) }
                    else { Text("고친 내용은 [인계확인서 수정]에서 저장하면 병원에 함께 전달됩니다").font(.system(size: 11.5)).foregroundStyle(AD.muted) }
                    Spacer(minLength: 0)
                }
            } else {
                Spacer(minLength: 0)
                Text("사고가 발생하면 통화 요약으로 채워진 인계확인서가 여기에 나타납니다")
                    .font(.system(size: 13)).foregroundStyle(AD.muted).frame(maxWidth: .infinity)
                Spacer(minLength: 0)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .card()
        .onAppear { edits = Handover.loadEdits(model.caseId) }
        .onChange(of: model.caseId) { _, id in edits = Handover.loadEdits(id) }
        // 서식을 넓게 보려고 전체 화면으로 띄운다(기본 시트는 아이패드에서 좁은 세로 칸이라 종이 서식처럼 안 보인다)
        .fullScreenCover(isPresented: $showSheet) {
            HandoverSheet(auto: auto, edits: $edits, caseId: model.caseId).environmentObject(model)
        }
    }

    /// 간략히 보여 줄 칸(서식에서 `summary` 표시한 것) — 빈 칸은 "미입력"으로 드러낸다
    private var summary: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(Handover.fields.filter(\.summary)) { f in
                // 처치 줄은 "기타 소견" 바로 위, 즉 카드 **맨 아래 두 줄**이다(2026-10-28) — 둘이 떨어져 있으면 뭐가 뭔지 헷갈린다.
                // 서식에서 여섯 칸(기도·호흡·순환·약품·고정·기타)으로 나뉜 처치를 카드에서는 한 줄로 묶고,
                // 외상 도해에서 [적용]한 처치가 전달 전에도 바로 여기 보인다
                if f.id == "notes", !careText.isEmpty {
                    row("처치", careText, lines: 8, pill: ("자동", AD.blueSoft, AD.blue))
                }
                let v = value(f.id)
                row(cardLabel(f), v.isEmpty ? "미입력" : v, empty: v.isEmpty,
                    pill: edits[f.id] != nil ? ("수정", AD.orangeSoft, AD.orange)
                        : (v.isEmpty ? nil : ("자동", AD.blueSoft, AD.blue)))
            }
        }
    }

    /// 카드에서만 쓰는 짧은 이름 — 서식 자체의 칸 이름(법정 서식)은 그대로 둔다
    private func cardLabel(_ f: Handover.Field) -> String {
        f.id == "notes" ? "기타 소견(증상·발생)" : f.label
    }

    private func row(_ label: String, _ text: String, empty: Bool = false, lines: Int = 4,
                     pill: (String, Color, Color)? = nil) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label).font(.system(size: 11.5)).foregroundStyle(AD.sub)
                .frame(width: 92, alignment: .leading)
            Text(text)
                .font(.system(size: 13, weight: empty ? .regular : .semibold))
                .foregroundStyle(empty ? AD.muted : AD.ink)
                .lineLimit(lines).fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
            if let p = pill { Pill(text: p.0, bg: p.1, fg: p.2) }
        }
    }
}

/// 인계확인서 전체 — **종이 서식처럼** 넓게(전체 화면). 왼쪽 회색 칸이 항목 이름, 오른쪽 흰 칸이 적는 자리이고
/// 한 줄에 두 칸씩 들어간다(긴 칸은 한 줄 전체). 자동으로 채운 칸에는 "자동", 고친 칸에는 "수정" 표시가 붙는다.
struct HandoverSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var model: AppModel
    let auto: [String: String]
    @Binding var edits: [String: String]
    let caseId: String?
    @State private var draft: [String: String] = [:]
    /// 이 화면을 연 뒤 사람이 손댄 칸 — 서식을 열어 둔 채 새 통화·출동 소식이 와도 이 칸은 덮지 않는다
    @State private var touched: Set<String> = []

    private func binding(_ id: String) -> Binding<String> {
        Binding(get: { draft[id] ?? "" }, set: { draft[id] = $0; touched.insert(id) })
    }

    var body: some View {
        VStack(spacing: 0) {
            bar
            ScrollView {
                VStack(spacing: 18) {
                    Text("통화 요약(AI)·출동 상태에서 채울 수 있는 칸은 미리 채워 두었습니다. 사실과 다르면 고치세요 — 고친 칸은 그대로 남고, 새 통화가 와도 덮어쓰지 않습니다. 서명·면허번호처럼 앱이 알 수 없는 칸은 비어 있습니다. [저장 · 병원에 전달]을 누르면 적은 내용이 이 기기에 저장되고 같은 내용이 수용 병원에도 전달됩니다.")
                        .font(.system(size: 12.5)).foregroundStyle(AD.sub)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(12).background(AD.chip).clipShape(RoundedRectangle(cornerRadius: 10))
                    ForEach(1...5, id: \.self) { section in
                        VStack(alignment: .leading, spacing: 6) {
                            Text(Handover.sections[section - 1])
                                .font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy)
                            table(Handover.fields.filter { $0.section == section })
                        }
                    }
                    Text("'*' 표시는 반드시 적는 칸입니다(응급의료에 관한 법률 시행규칙 별지 제16호서식).")
                        .font(.system(size: 11.5)).foregroundStyle(AD.muted)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .padding(20)
                .frame(maxWidth: 1180)
                .frame(maxWidth: .infinity)
            }
            .background(AD.bg)
        }
        .onAppear { draft = auto.merging(edits) { _, edited in edited } }
        // 서식을 열어 둔 채 통화 요약·출동 상태가 갱신되면, 손대지 않은 칸만 새 자동값으로 따라 채운다
        .onChange(of: auto) { _, fresh in
            for (id, value) in fresh where !touched.contains(id) && edits[id] == nil {
                draft[id] = value
            }
        }
    }

    /// 위 띠 — 서식 이름과 버튼
    private var bar: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 1) {
                Text("출동 및 처치 기록지").font(.system(size: 18, weight: .black)).foregroundStyle(AD.navy)
                Text("응급의료에 관한 법률 시행규칙 [별지 제16호서식] · 인계확인서")
                    .font(.system(size: 11.5)).foregroundStyle(AD.sub)
            }
            Spacer(minLength: 8)
            Button { draft = auto; touched = [] } label: {
                Text("자동값으로 되돌리기").font(.system(size: 13, weight: .semibold)).foregroundStyle(AD.ink3)
                    .padding(.horizontal, 14).frame(minHeight: 36).background(AD.chip).clipShape(Capsule())
            }
            Button { dismiss() } label: {
                Text("취소").font(.system(size: 13, weight: .semibold)).foregroundStyle(AD.ink3)
                    .padding(.horizontal, 16).frame(minHeight: 36).background(AD.chip).clipShape(Capsule())
            }
            // 저장과 전달을 한 버튼으로(2026-10-28) — 적은 내용은 기기에 남고 같은 동작으로 병원에도 간다
            Button { save(); _ = model.sendExtraNote(Handover.message(draft)); dismiss() } label: {
                Label("저장 · 병원에 전달", systemImage: "paperplane.fill")
                    .font(.system(size: 14, weight: .bold)).foregroundStyle(.white)
                    .padding(.horizontal, 20).frame(minHeight: 36)
                .background(model.paused ? AD.gray : AD.blue).clipShape(Capsule())
            }
            .disabled(model.paused)
        }
        .padding(.horizontal, 20).padding(.vertical, 12)
        .background(AD.card)
        .overlay(alignment: .bottom) { Rectangle().fill(AD.line).frame(height: 1) }
    }

    /// 한 장(섹션)의 표 — 한 줄에 두 칸, 여러 줄짜리 칸은 한 줄 전체
    private func table(_ fields: [Handover.Field]) -> some View {
        VStack(spacing: 0) {
            ForEach(Array(rows(fields).enumerated()), id: \.offset) { i, row in
                // 줄 높이는 그 줄에서 가장 높은 칸이 정하고, 이름 칸 회색은 그 높이를 **끝까지** 채운다
                // (2026-10-28 — 칸마다 fixedSize를 걸었더니 줄보다 짧아져 흰 띠가 보였다)
                HStack(spacing: 0) {
                    ForEach(row) { cell($0) }
                    // 한 칸만 있는 줄의 빈 자리도 회색으로 — 흰 구멍이 남지 않게
                    if row.count == 1, row[0].kind != .multiline {
                        HStack(spacing: 0) {
                            Rectangle().fill(AD.line).frame(width: 1)
                            AD.chip.frame(maxWidth: .infinity)   // 칸이 없는 자리 — 흰 구멍 대신 회색
                        }
                    }
                }
                .fixedSize(horizontal: false, vertical: true)
                if i < rows(fields).count - 1 { Rectangle().fill(AD.line).frame(height: 1) }
            }
        }
        .background(AD.card)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(AD.line, lineWidth: 1))
    }

    /// 두 칸씩 묶는다. 여러 줄짜리 칸은 혼자 한 줄을 쓴다
    private func rows(_ fields: [Handover.Field]) -> [[Handover.Field]] {
        var out: [[Handover.Field]] = []
        var pair: [Handover.Field] = []
        for f in fields {
            if f.kind == .multiline {
                if !pair.isEmpty { out.append(pair); pair = [] }
                out.append([f])
            } else {
                pair.append(f)
                if pair.count == 2 { out.append(pair); pair = [] }
            }
        }
        if !pair.isEmpty { out.append(pair) }
        return out
    }

    /// 한 칸 — 왼쪽 회색 이름, 오른쪽 적는 자리
    private func cell(_ f: Handover.Field) -> some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 2) {
                Text(f.label + (f.required ? " *" : ""))
                    .font(.system(size: 12.5, weight: .semibold)).foregroundStyle(AD.ink3)
                    .fixedSize(horizontal: false, vertical: true)
                if edits[f.id] != nil { Pill(text: "수정", bg: AD.orangeSoft, fg: AD.orange) }
                else if !(auto[f.id] ?? "").isEmpty { Pill(text: "자동", bg: AD.blueSoft, fg: AD.blue) }
            }
            .frame(width: 170, alignment: .topLeading)
            .padding(.horizontal, 12).padding(.vertical, 10)
            .frame(maxHeight: .infinity, alignment: .top)
            .background(AD.chip)
            Rectangle().fill(AD.line).frame(width: 1)
            input(f)
                .padding(.horizontal, 12).padding(.vertical, 8)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        }
        .frame(maxWidth: .infinity)
    }

    @ViewBuilder private func input(_ f: Handover.Field) -> some View {
        switch f.kind {
        case .text:
            TextField("", text: binding(f.id)).font(.system(size: 15)).textFieldStyle(.plain)
        case .multiline:
            TextField("", text: binding(f.id), axis: .vertical).font(.system(size: 15)).lineLimit(2...6).textFieldStyle(.plain)
        case .choice(let options):
            Picker("", selection: binding(f.id)) {
                Text("—").tag("")
                ForEach(options, id: \.self) { Text($0).tag($0) }
            }
            .pickerStyle(.menu).labelsHidden()
        }
    }

    /// 자동값과 **다른 칸만** 저장한다 — 그래야 통화가 갱신될 때 안 고친 칸이 따라 바뀐다
    private func save() {
        var out: [String: String] = [:]
        for f in Handover.fields {
            let v = (draft[f.id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
            if v != (auto[f.id] ?? "").trimmingCharacters(in: .whitespacesAndNewlines) { out[f.id] = v }
        }
        edits = out
        Handover.saveEdits(caseId, out)
    }
}
