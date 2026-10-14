import SwiftUI

/// 왼쪽 열 맨 위 — 현장 상태(출동 시뮬레이션 단계 · 발생 위치 · 확정 병원). 웹 DispatchControlPanel의 보기 전용판.
/// 출동·현장 종료는 웹 구급차 대시보드·시연 콘솔에서 한다.
struct SceneStatusCard: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text("현장 상태").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Spacer()
                if model.sim?.paused == true { Pill(text: model.sim?.pauseReason == "call" ? "통화 중 정지" : "시연 정지", bg: AD.redSoft, fg: AD.red, bold: true) }
                Pill(text: model.simDispatch ? "시뮬레이션 위치" : "위치 정보", bg: AD.chip, fg: AD.ink3)
            }
            HStack(spacing: 10) {
                Image(systemName: icon).font(.system(size: 20, weight: .semibold)).foregroundStyle(phaseColor)
                    .frame(width: 40, height: 40).background(phaseColor.opacity(0.12)).clipShape(Circle())
                VStack(alignment: .leading, spacing: 2) {
                    Text(Labels.phase(model.sim?.phase ?? (model.hasIncident ? "on_scene" : "idle")))
                        .font(.system(size: 15, weight: .bold)).foregroundStyle(AD.ink)
                    Text(detail).font(.system(size: 12)).foregroundStyle(AD.sub).lineLimit(2)
                }
                Spacer(minLength: 0)
            }
            if model.hasIncident, let p = model.sim?.incident ?? model.result?.ambulanceGps {
                HStack(spacing: 6) {
                    Text("발생 위치").font(.system(size: 11.5)).foregroundStyle(AD.sub)
                    Text(String(format: "%.5f, %.5f", p.lat, p.lng)).font(.system(size: 12, weight: .medium, design: .monospaced)).foregroundStyle(AD.ink)
                }
            }
            if !model.hasIncident {
                Text(model.apid == nil && model.autoFollow
                     ? "출동 대기 중 — 상황이 발생하면 출동하는 구급대 화면으로 자동 전환됩니다. 병원 후보는 사고가 발생하면 아래에 나타납니다."
                     : "출동 대기 중 — 사고가 발생하면 환자 정보와 병원 후보가 나타납니다.")
                    .font(.system(size: 12)).foregroundStyle(AD.muted)
            }
        }
        .card()
    }

    private var phase: String { model.sim?.phase ?? (model.hasIncident ? "on_scene" : "idle") }
    private var icon: String {
        switch phase {
        case "dispatching": return "light.beacon.max"
        case "on_scene": return "cross.case"
        case "transporting": return "arrow.triangle.turn.up.right.diamond"
        case "at_hospital": return "building.2"
        case "rerouting": return "arrow.triangle.branch"
        case "returning": return "house"
        default: return "house"
        }
    }
    private var phaseColor: Color {
        switch phase {
        case "dispatching", "transporting": return AD.orange
        case "on_scene", "rerouting": return AD.red
        case "at_hospital": return AD.green
        default: return AD.gray
        }
    }
    private var detail: String {
        if let c = model.confirmed {
            let eta = model.sim?.etaSec.map { " · 도착까지 약 \(Labels.minutes($0))" } ?? ""
            return "이송 확정 \(c.name)\(eta)"
        }
        switch phase {
        case "dispatching": return model.sim?.etaSec.map { "현장까지 약 \(Labels.minutes($0))" } ?? "현장으로 이동 중"
        case "on_scene": return model.result == nil ? "대원 휴대폰 전화 앱으로 병원에 전화합니다" : "병원 응답을 받는 중 — 후보 등록 병원에 이송 승인"
        case "rerouting": return "도착 후 수용 불가 — 다른 후보로 재선택"
        case "returning": return "사건 종료"
        default: return model.ambulanceName ?? model.apid ?? "구급차 미지정"
        }
    }
}

/// 왼쪽 열 — 통화 요약 · 구조화(웹 CallSummaryEditablePanel의 보기 전용판) + 통화 현황
struct CallSummaryCard: View {
    @EnvironmentObject private var model: AppModel
    @State private var showTranscript = false

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 1) {
                    Text("통화 요약 · 구조화").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                    Text("통화 음성 → 항목 추출").font(.system(size: 11.5)).foregroundStyle(AD.sub)
                }
                Spacer()
                VStack(alignment: .trailing, spacing: 4) {
                    Pill(text: "Qwen3-ASR · MF_BERT", bg: AD.blueSoft, fg: AD.blue)
                    if let p = model.result?.patientInfo {
                        if p.confirmedBy == "paramedic" { Pill(text: "구급대원 확인", bg: AD.greenSoft, fg: AD.green, bold: true) }
                        else { Pill(text: "AI 요약 · 구급대원 확인 전", bg: AD.orangeSoft, fg: AD.orange, bold: true) }
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
                    if let k = p.ktasLevel { Pill(text: "KTAS \(k)", bg: Theme.ktasSoft(k), fg: Theme.ktas(k), bold: true) }
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
                            Text("\(u.callRound)차 통화 · \(Theme.severity(u.severityTag).label) · \(u.expectedDiagnosis ?? "")\(u.ktasLevel.map { " · KTAS \($0)" } ?? "")")
                                .font(.system(size: 11.5)).foregroundStyle(AD.sub)
                        }
                    }
                    .padding(.horizontal, 10).padding(.vertical, 6).frame(maxWidth: .infinity, alignment: .leading)
                    .background(AD.chip).clipShape(RoundedRectangle(cornerRadius: 10))
                }
                if showTranscript { transcriptBox }
            } else if calling || !model.transcript.isEmpty {
                Text("실시간 자막 (voice 음성 인식)").font(.system(size: 11.5)).foregroundStyle(AD.sub)
                transcriptBox
            } else {
                Text(model.sim?.phase == "dispatching"
                     ? "현장 도착 후 대원 휴대폰의 전화 앱으로 병원에 전화합니다."
                     : "수신 대기 중 — 대원 휴대폰의 전화 앱으로 병원에 전화하면 통화 내용이 여기 정리됩니다.")
                    .font(.system(size: 13)).foregroundStyle(AD.muted)
            }
            Divider().overlay(AD.line)
            HStack {
                VStack(alignment: .leading, spacing: 1) {
                    HStack(spacing: 6) {
                        Text("통화 현황").font(.system(size: 13, weight: .bold)).foregroundStyle(AD.navy)
                        if calling { Dot(color: AD.green) }
                    }
                    Text(callText).font(.system(size: 11.5, weight: calling ? .bold : .regular)).foregroundStyle(calling ? AD.green : AD.sub)
                }
                Spacer()
                if model.result?.patientInfo != nil && !model.transcript.isEmpty {
                    Button { showTranscript.toggle() } label: { Pill(text: showTranscript ? "자막 접기" : "자막 \(model.transcript.count)줄", bg: AD.blueSoft, fg: AD.blue) }
                } else {
                    Pill(text: "voice 음성 인식", bg: AD.blueSoft, fg: AD.blue)
                }
            }
        }
        .card()
    }

    private var calling: Bool { model.callStatus?.state == "calling" }
    private var callText: String {
        guard let c = model.callStatus else { return "휴대폰 전화 앱 P-\(model.apid ?? "AUTO")" }
        if c.state == "calling" {
            let since = c.startedAt.flatMap(ISO.parse).map { Labels.elapsed(model.now.timeIntervalSince($0)) } ?? ""
            return "\(c.hospitalName ?? "병원")과 통화 중\(c.followup == true ? "(추가 통화)" : "") · \(since)"
        }
        if c.cancelled == true { return "통화 취소 — 전달하지 않았습니다" }
        return "통화 종료 · \(model.result.map { "후보 병원 \($0.hospitals.count)곳에 전달" } ?? "요약 정리 중")"
    }

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
