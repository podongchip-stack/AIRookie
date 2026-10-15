import SwiftUI

/// 병원 리스트 화면(2026-10-16) — 상단바 [구급차 | 병원 리스트 | 상황판]의 가운데. 지도 없이 왼쪽 현장 상태·통화 요약, 오른쪽 병원 후보.
/// 예전엔 구급차 화면 아래 가로 스크롤 띠였는데, 음성 요약 뒤 나오는 병원 리스트를 따로 크게 보려고 화면으로 뺐다.
/// 음성 요약이 처음 도착하면 이 화면으로 자동 전환되고, 이송이 확정되면(hub 응답) 구급차 지도로 돌아간다(AppModel.requestScreen).
struct HospitalListScreen: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            // 왼쪽 열은 화면 높이에 고정(2026-10-16) — 열 전체가 밀려 스크롤되던 것을, 병원 응답 현황(응답 기록)과 통화 요약이 남는 높이를
            // 나눠 갖고 각자 안에서 스크롤되게. 현장 상태·선택 비교는 내용 높이 그대로
            VStack(spacing: 8) {
                SceneStatusCard().fixedSize(horizontal: false, vertical: true)
                // 순서(2026-10-16): 현장 상태 → 통화 요약 → 선택 비교(수용 승인 2곳 이상) → 병원 응답 현황(남는 높이, 기록은 카드 안 스크롤)
                // 응답 현황·선택 비교는 이송 확정 전까지. 응답 현황이 있을 땐 통화 요약을 230pt로 묶는다(넘치면 카드 안 스크롤)
                let r = model.confirmed == nil ? model.result : nil
                if model.hasIncident { CallSummaryCard(fill: true).frame(minHeight: 90, maxHeight: r != nil ? 230 : .infinity) }
                if let r {
                    let approved = r.hospitals.filter { $0.status == "approved" && $0.excluded != true }
                    if approved.count >= 2 {
                        CompareCard(hospitals: approved, recommendedId: r.hospitals.first { HospitalRules.canTransportNow($0) }?.hospitalId)
                    }
                    ResponseStatusCard(r: r).frame(minHeight: 130)
                }
                if !model.hasIncident { Spacer(minLength: 0) }
            }
            .frame(width: 360)
            .frame(maxHeight: .infinity, alignment: .top)
            .clipped()   // 어떤 경우에도 화면 밖으로 넘치지 않게(넘치면 상단바까지 밀려 올라갔다)
            HospitalListPanel()
        }
    }
}

/// 오른쪽 — 요약 줄 · 필터 · 카드 격자. 통화 전엔 현장 후보(도착 시간순·첫 연락 추천), 음성 요약 뒤엔 hub 순위 그대로,
/// 이송 확정 뒤엔 확정 병원만(다른 후보는 펼쳐 재선택). 카드를 누르면 "왜 이 확률인가" 상세.
struct HospitalListPanel: View {
    @EnvironmentObject private var model: AppModel
    @State private var detail: HospitalMatch?
    @State private var showOthers = false
    @State private var filter: Filter = .all

    enum Filter: String, CaseIterable { case all = "전체", approved = "수용 승인", pending = "판단 대기", rejected = "수용 불가" }
    private let columns = [GridItem(.adaptive(minimum: 320), spacing: 14, alignment: .top)]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header
            if let r = model.result {
                if model.confirmed == nil { filterBar(r) }
                grid {
                    ForEach(visible(r)) { h in
                        CandidateCard(h: h, recommended: h.hospitalId == recommendedId(r), confirmedId: model.confirmed?.hospitalId,
                                      requesting: model.pendingConfirmId == h.hospitalId, allChips: true, onDetail: { detail = h })
                            .id("m-\(r.caseId)-\(h.hospitalId)")
                    }
                }
                .id("match-\(r.caseId)")
            } else if let s = model.scene {
                grid { ForEach(sceneOrdered(s)) { h in SceneCard(h: h).id("s-\(s.caseId)-\(h.hospitalId)") } }
                    .id("scene-\(s.caseId)")
            } else {
                VStack(spacing: 8) {
                    Image(systemName: "list.bullet.rectangle").font(.system(size: 34)).foregroundStyle(AD.muted)
                    Text(model.hasIncident ? "현장 도착 후 주변 병원 후보가 나타납니다" : "사고가 발생하면 여기에 병원 후보가 나타납니다")
                        .font(.system(size: 14, weight: .medium)).foregroundStyle(AD.ink3)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .background(AD.card).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.line, lineWidth: 1))
        .sheet(item: $detail) { h in ValidityDetailView(h: h).environmentObject(model) }
        .onChange(of: model.caseId) { _, _ in filter = .all; showOthers = false }
    }

    private func grid<Content: View>(@ViewBuilder _ content: () -> Content) -> some View {
        ScrollView {
            LazyVGrid(columns: columns, alignment: .leading, spacing: 14) { content() }
                .padding(.bottom, 8)
        }
        .scrollIndicators(.visible)
    }

    // ── 요약 줄: 사건 · KTAS · 예상 병명 · 요청 존 · 병원 응답 집계 ──
    private var header: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                Text("병원 리스트").font(.system(size: 18, weight: .bold)).foregroundStyle(AD.navy)
                if let r = model.result {
                    let k = r.patientInfo?.ktasLevel
                    if let k { Pill(text: "KTAS \(k)", bg: Theme.ktasSoft(k), fg: Theme.ktas(k), bold: true) }
                    Text(r.patientInfo?.expectedDiagnosis ?? "").font(.system(size: 13, weight: .semibold)).foregroundStyle(AD.ink).lineLimit(1)
                    Spacer(minLength: 8)
                    let zoneMax = max(1, r.zoneActive?.max() ?? 1)
                    (Text(zoneMax > 1 ? "Zone 1~\(zoneMax)" : "Zone 1").bold().foregroundColor(AD.blue) + Text(" · 현장 반경 \(zoneMax * 5)km · \(r.hospitals.count)곳"))
                        .font(.system(size: 12)).foregroundStyle(AD.ink3)
                } else if let s = model.scene {
                    (Text("Zone \((s.zoneActive ?? [1]).map(String.init).joined(separator: ", "))").bold().foregroundColor(AD.blue) + Text(" · 통화 전 · 도착 시간순 \(s.hospitals.count)곳"))
                        .font(.system(size: 12)).foregroundStyle(AD.ink3)
                    Spacer()
                } else { Spacer() }
            }
            if let r = model.result {
                HStack(spacing: 10) {
                    if let c = model.confirmed {
                        HStack(spacing: 6) { Dot(color: AD.green); Text("이송 확정 · \(c.name)").font(.system(size: 12.5, weight: .bold)).foregroundStyle(AD.green) }
                        Spacer()
                        if r.hospitals.count > 1 {
                            Button { showOthers.toggle() } label: {
                                Text(showOthers ? "다른 후보 접기" : "다른 후보 \(r.hospitals.count - 1)곳 보기 (재선택할 때)")
                                    .font(.system(size: 12)).foregroundStyle(AD.ink3)
                                    .padding(.horizontal, 12).frame(minHeight: 30)
                                    .overlay(Capsule().stroke(AD.gray, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
                            }
                        }
                    } else {
                        Text("hub 순위 그대로 · 카드를 누르면 정보 유효성 근거").font(.system(size: 11.5)).foregroundStyle(AD.muted)
                        Spacer()
                    }
                }
            } else if let s = model.scene {
                Text(s.reportedSymptom.map { "1차 신고(\($0)) 기반 가추천 — 통화가 끝나면 확정 순위로 바뀝니다" } ?? "통화가 끝나면 hub 순위와 병원 응답으로 바뀝니다")
                    .font(.system(size: 11.5)).foregroundStyle(AD.sub).lineLimit(1)
            }
        }
    }

    // ── 필터: 전체 · 수용 승인 · 판단 대기 · 수용 불가 (개수) — 순서는 hub 순위 그대로, 거르기만 ──
    private func filterBar(_ r: HubMatchResult) -> some View {
        HStack(spacing: 8) {
            ForEach(Filter.allCases, id: \.self) { f in
                let n = r.hospitals.filter { matches($0, f) }.count
                Button { filter = f } label: {
                    Text("\(f.rawValue) \(n)").font(.system(size: 12.5, weight: .bold))
                        .foregroundStyle(filter == f ? .white : AD.ink3)
                        .padding(.horizontal, 14).frame(minHeight: 32)
                        .background(filter == f ? AD.navy : AD.chip).clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
            Spacer()
        }
    }

    private func statusKey(_ h: HospitalMatch) -> String { h.status == "pending" && h.unavailableReason != nil ? "rejected" : h.status }
    private func matches(_ h: HospitalMatch, _ f: Filter) -> Bool {
        switch f {
        case .all: return true
        case .approved: return ["approved", "confirmed"].contains(h.status)
        case .pending: return statusKey(h) == "pending"
        case .rejected: return statusKey(h) == "rejected"
        }
    }

    /// 이송이 확정되면 확정 병원만(웹과 같음) — 재선택을 위해 펼칠 수 있다. 확정 전엔 필터대로
    private func visible(_ r: HubMatchResult) -> [HospitalMatch] {
        if let c = model.confirmed, !showOthers { return r.hospitals.filter { $0.hospitalId == c.hospitalId } }
        return model.confirmed == nil ? r.hospitals.filter { matches($0, filter) } : r.hospitals
    }
    /// 병원 승인이 오면 지금 보낼 수 있는 승인 병원 중 최상위(hub 순위)를 "추천" — 자동 확정이 아니라 추천 + 탭 한 번
    private func recommendedId(_ r: HubMatchResult) -> String? {
        model.confirmed == nil ? r.hospitals.first { HospitalRules.canTransportNow($0) }?.hospitalId : nil
    }
    private func sceneOrdered(_ s: SceneCandidates) -> [SceneCandidate] {
        s.hospitals.filter { $0.firstCallRecommended == true } + s.hospitals.filter { $0.firstCallRecommended != true }
    }
}

/// 병원 응답 현황(2026-10-16) — 병원 리스트 화면 왼쪽. 응답 집계 막대, 다음 존 확장까지(hub zoneExpandAt), 최근 응답 순서.
/// 오른쪽 카드가 "누가 어떤 상태인가"라면 이 칸은 "지금 무슨 일이 일어나고 있나"를 시간 순서로 보여 준다.
struct ResponseStatusCard: View {
    @EnvironmentObject private var model: AppModel
    let r: HubMatchResult

    private func key(_ h: HospitalMatch) -> String { h.status == "pending" && h.unavailableReason != nil ? "rejected" : h.status }

    var body: some View {
        let approved = r.hospitals.filter { ["approved", "confirmed"].contains($0.status) }.count
        let rejected = r.hospitals.filter { key($0) == "rejected" }.count
        let pending = r.hospitals.count - approved - rejected
        let zone = max(1, r.zoneActive?.max() ?? 1)
        VStack(alignment: .leading, spacing: 9) {
            HStack(alignment: .firstTextBaseline) {
                Text("병원 응답 현황").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Spacer()
                Text("Zone \(zone == 1 ? "1" : "1~\(zone)") · \(r.hospitals.count)곳").font(.system(size: 12, weight: .semibold)).foregroundStyle(AD.blue)
            }
            GeometryReader { g in
                HStack(spacing: 2) {
                    seg(approved, AD.green, g.size.width); seg(pending, AD.orange, g.size.width); seg(rejected, AD.red, g.size.width)
                }
            }
            .frame(height: 8).clipShape(Capsule())
            HStack(spacing: 12) {
                legend("승인", approved, AD.green); legend("대기", pending, AD.orange); legend("불가", rejected, AD.red)
                Spacer(minLength: 0)
            }
            zoneLine
            Divider()
            if model.responseLog.isEmpty {
                Text("병원 응답을 기다리는 중 — 응답이 오면 여기에 순서대로 쌓입니다").font(.system(size: 12)).foregroundStyle(AD.muted)
                Spacer(minLength: 0)
            } else {
                // 응답 기록은 카드 안에서 스크롤(2026-10-16) — 최근 것이 위, 최대 20줄
                ScrollView {
                VStack(alignment: .leading, spacing: 6) {
                    ForEach(model.responseLog) { e in
                        HStack(alignment: .firstTextBaseline, spacing: 6) {
                            Dot(color: color(e.kind), size: 7)
                            Text(e.hospital).font(.system(size: 12.5, weight: .bold)).foregroundStyle(AD.navy).lineLimit(1)
                            Text(e.text).font(.system(size: 12)).foregroundStyle(color(e.kind)).lineLimit(1)
                            Spacer(minLength: 4)
                            Text(ago(e.at)).font(.system(size: 11)).foregroundStyle(AD.muted).fixedSize()
                        }
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                }
                .scrollIndicators(.visible)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .card()
    }

    @ViewBuilder private var zoneLine: some View {
        let next = max(1, r.zoneActive?.max() ?? 1) + 1
        if model.confirmed != nil {
            EmptyView()
        } else if let left = r.zonePausedLeftSec {
            Text("일시정지 — Zone \(next) 확장까지 \(left)초에서 멈춤").font(.system(size: 12)).foregroundStyle(AD.ink3)
        } else if let at = r.zoneExpandAt.flatMap(ISO.parse) {
            let s = max(0, Int(at.timeIntervalSince(model.now).rounded()))
            (Text("응답이 없으면 ") + Text("Zone \(next)").bold() + Text("로 확장 · ") + Text("\(s)초").bold().foregroundColor(AD.orange))
                .font(.system(size: 12)).foregroundStyle(AD.ink3)
        } else if r.hospitals.contains(where: { $0.status == "approved" }) {
            Text("수용 승인 병원이 있어 범위 확장 멈춤").font(.system(size: 12)).foregroundStyle(AD.ink3)
        }
    }

    private func seg(_ n: Int, _ c: Color, _ w: CGFloat) -> some View {
        Rectangle().fill(c).frame(width: n > 0 ? max(4, w * CGFloat(n) / CGFloat(max(1, r.hospitals.count)) - 2) : 0)
    }
    private func legend(_ t: String, _ n: Int, _ c: Color) -> some View {
        HStack(spacing: 4) { Dot(color: c, size: 7); Text("\(t) \(n)").font(.system(size: 12, weight: .semibold)).foregroundStyle(AD.ink3) }
    }
    private func color(_ kind: String) -> Color {
        switch kind { case "approved", "confirmed": return AD.green; case "zone": return AD.blue; default: return AD.red }
    }
    private func ago(_ d: Date) -> String {
        let s = Int(model.now.timeIntervalSince(d))
        return s < 60 ? "\(max(0, s))초 전" : "\(s / 60)분 전"
    }
}

/// 선택 비교(2026-10-16) — 수용 승인한 병원이 2곳 이상이면 응답 현황 아래에. 병상 · 도착 시 유효(AI) · 도착 시간 · 전문의를 한 표로,
/// 칸마다 가장 나은 값을 굵은 초록으로. hub 1순위(추천)에 표시. 지금 보낼 수 없는 승인 병원(병상 0 확인·제외·차단)은 흐리게
struct CompareCard: View {
    @EnvironmentObject private var model: AppModel
    let hospitals: [HospitalMatch]
    let recommendedId: String?

    private struct Row { let h: HospitalMatch; let beds: Int?; let valid: Double?; let eta: Double?; let docs: Int?; let ok: Bool }

    var body: some View {
        let rows = hospitals.map { h in
            Row(h: h, beds: h.bedCountUnknown == true ? nil : h.availableBedCount,
                valid: h.bedReliability.map { BedReliability.live($0, now: model.now).rArrive },
                eta: h.etaMin.map(Double.init) ?? h.travelMin, docs: h.specialtyMatch?.doctorCount, ok: HospitalRules.canTransportNow(h))
        }
        let ok = rows.filter(\.ok)
        let bestBeds = ok.compactMap(\.beds).max(), bestValid = ok.compactMap(\.valid).max()
        let bestEta = ok.compactMap(\.eta).min(), bestDocs = ok.compactMap(\.docs).max()
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text("선택 비교").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Text("수용 승인 \(hospitals.count)곳").font(.system(size: 11.5)).foregroundStyle(AD.muted)
                Spacer()
            }
            cells(["", "병상", "유효", "도착", "전문의"], header: true)
            // 승인 병원이 많으면 표 줄만 카드 안에서 스크롤(2026-10-16) — 높이는 줄 수만큼, 최대 약 5줄
            ScrollView {
            VStack(spacing: 4) {
            ForEach(rows, id: \.h.hospitalId) { r in
                HStack(spacing: 4) {
                    HStack(spacing: 4) {
                        Text(short(r.h.name)).font(.system(size: 12.5, weight: .bold)).foregroundStyle(AD.navy).lineLimit(1)
                        if r.h.hospitalId == recommendedId { Pill(text: "추천", bg: AD.orangeSoft, fg: AD.approve, bold: true) }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                    value(r.beds.map { "\($0)석" } ?? "미상", best: r.ok && r.beds != nil && r.beds == bestBeds)
                    value(r.valid.map(BedReliability.pct) ?? "—", best: r.ok && r.valid != nil && r.valid == bestValid,
                          color: r.valid.map { Theme.validity($0).fg })
                    value(r.eta.map { "\(Int($0.rounded()))분" } ?? "—", best: r.ok && r.eta != nil && r.eta == bestEta)
                    value(r.docs.map { "\($0)명" } ?? "—", best: r.ok && r.docs != nil && r.docs == bestDocs)
                }
                .padding(.vertical, 5).padding(.horizontal, 6)
                .background(r.h.hospitalId == recommendedId ? AD.orangeSoft.opacity(0.5) : AD.bg)
                .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
                .opacity(r.ok ? 1 : 0.5)
            }
            }
            }
            .scrollIndicators(.visible)
            .frame(height: min(CGFloat(rows.count) * 36, 150))
            Text("유효 = 도착 때 병상 숫자가 맞을 확률(AI) · 초록 굵게 = 그 칸 최고 · 결정은 오른쪽 카드의 [이송 승인]")
                .font(.system(size: 11)).foregroundStyle(AD.muted).fixedSize(horizontal: false, vertical: true)
        }
        .card()
    }

    private func cells(_ t: [String], header: Bool) -> some View {
        HStack(spacing: 4) {
            Text(t[0]).frame(maxWidth: .infinity, alignment: .leading)
            ForEach(1..<t.count, id: \.self) { i in Text(t[i]).frame(width: 46, alignment: .trailing) }
        }
        .font(.system(size: 11, weight: .semibold)).foregroundStyle(AD.muted).padding(.horizontal, 6)
    }
    private func value(_ t: String, best: Bool, color: Color? = nil) -> some View {
        Text(t).font(.system(size: 12.5, weight: best ? .heavy : .medium))
            .foregroundStyle(best ? AD.green : (color ?? AD.ink))
            .frame(width: 46, alignment: .trailing).lineLimit(1).minimumScaleFactor(0.8)
    }
    private func short(_ n: String) -> String {
        n.replacingOccurrences(of: "학교법인", with: "").replacingOccurrences(of: "의료법인", with: "")
            .replacingOccurrences(of: "의과대학부속", with: "").replacingOccurrences(of: "대학교", with: "대")
    }
}
