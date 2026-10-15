import SwiftUI

/// 병원 리스트 화면(2026-10-16) — 상단바 [구급차 | 병원 리스트 | 상황판]의 가운데. 지도 없이 왼쪽 현장 상태·통화 요약, 오른쪽 병원 후보.
/// 예전엔 구급차 화면 아래 가로 스크롤 띠였는데, 음성 요약 뒤 나오는 병원 리스트를 따로 크게 보려고 화면으로 뺐다.
/// 음성 요약이 처음 도착하면 이 화면으로 자동 전환되고, 이송이 확정되면(hub 응답) 구급차 지도로 돌아간다(AppModel.requestScreen).
struct HospitalListScreen: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            ScrollView {
                VStack(spacing: 8) {
                    SceneStatusCard()
                    if model.hasIncident { CallSummaryCard() }
                }
            }
            .scrollIndicators(.hidden)
            .frame(width: 360)
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
