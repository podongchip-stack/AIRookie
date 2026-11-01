import SwiftUI

/// [이송] 탭(2026-10-27) — 왼쪽에 병원 후보를 한 줄에 하나씩(n×1) 세로로 쌓고, 병원을 누르면 오른쪽에 그 병원의
/// **배후역량표**가 뜬다. 예전 [구급차] 탭의 자리다(지도는 [환자 정보] 탭의 외상 그림으로 바뀌었다).
/// 순서는 hub 순위 그대로이고(앱은 정렬하지 않는다), 조작은 카드 안의 [이송 승인] 하나다.
struct TransportScreen: View {
    @EnvironmentObject private var model: AppModel
    @State private var selectedId: String?
    @State private var detail: HospitalMatch?

    private var hospitals: [HospitalMatch] { model.result?.hospitals ?? [] }
    /// 통화 전 현장 후보(도착 시간순, 첫 연락 추천이 맨 위)
    private var sceneOrdered: [SceneCandidate] {
        guard let s = model.scene else { return [] }
        return s.hospitals.filter { $0.firstCallRecommended == true } + s.hospitals.filter { $0.firstCallRecommended != true }
    }
    /// 오른쪽에 펼쳐 볼 병원 — 고른 게 없으면 **추천 병원이 바로 열린다**(확정 병원 → 지금 보낼 수 있는 첫 병원 → hub 1순위).
    /// 통화 전이면 현장 후보의 첫 연락 추천(없으면 가장 가까운 곳)
    private var selected: HospitalMatch? {
        hospitals.first { $0.hospitalId == selectedId } ?? model.confirmed
            ?? hospitals.first { HospitalRules.canTransportNow($0) } ?? hospitals.first
    }
    private var selectedScene: SceneCandidate? {
        guard model.result == nil else { return nil }
        return sceneOrdered.first { $0.hospitalId == selectedId } ?? sceneOrdered.first
    }
    private var recommendedId: String? {
        model.confirmed == nil ? hospitals.first { HospitalRules.canTransportNow($0) }?.hospitalId : nil
    }

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            // 병원 응답 현황 카드는 없앴다(2026-10-27) — 집계는 아래 리스트 머리에 숫자로 들어가고, 그만큼 리스트가 길어진다
            VStack(spacing: 8) {
                if model.sim?.phase == "rerouting" { ReselectBanner() }
                if let r = model.result, model.confirmed == nil {
                    let approved = r.hospitals.filter { $0.status == "approved" && $0.excluded != true }
                    if approved.count >= 2 { CompareCard(hospitals: approved, recommendedId: recommendedId) }
                }
                list
            }
            .frame(width: 400)
            .frame(maxHeight: .infinity, alignment: .top)
            right
        }
        .sheet(item: $detail) { h in ValidityDetailView(h: h).environmentObject(model) }
        .onChange(of: model.caseId) { _, _ in selectedId = nil }
    }

    // ── 왼쪽: 병원 리스트 n×1 ──
    private var list: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("병원 리스트").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Spacer(minLength: 0)
                if let c = model.confirmed {
                    Pill(text: "이송 확정 · \(c.name)", bg: AD.greenSoft, fg: AD.green, bold: true)
                } else if let r = model.result {
                    Text("\(r.hospitals.count)곳 요청").font(.system(size: 12, weight: .semibold)).foregroundStyle(AD.ink3)
                } else if let s = model.scene {
                    Pill(text: "통화 전 · \(s.hospitals.count)곳", bg: AD.chip, fg: AD.ink3)
                }
            }
            // 제목 줄과 분리된 자기 줄(2026-10-28) — 400pt 고정 폭에서 제목·요청 수와 같은 줄에 두면 넘쳐서 줄바꿈됐다
            if let r = model.result { responseCounts(r) }
            if let r = model.result {
                HStack(spacing: 6) {
                    Text("병원을 누르면 오른쪽에 배후역량표").font(.system(size: 11.5)).foregroundStyle(AD.muted)
                    zoneLine(r)
                    Spacer(minLength: 0)
                }
                ScrollView {
                    LazyVStack(spacing: 10) {
                        ForEach(r.hospitals) { h in
                            Button { selectedId = h.hospitalId } label: {
                                CandidateCard(h: h, recommended: h.hospitalId == recommendedId, confirmedId: model.confirmed?.hospitalId,
                                              requesting: model.pendingConfirmId == h.hospitalId, allChips: true,
                                              onDetail: { selectedId = h.hospitalId })
                                    .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous)
                                        .stroke(AD.blue, lineWidth: h.hospitalId == selected?.hospitalId ? 2.5 : 0))
                            }
                            .buttonStyle(.plain)
                            .id("t-\(r.caseId)-\(h.hospitalId)")
                        }
                    }
                    .padding(.bottom, 8)
                }
                .scrollIndicators(.visible)
            } else if let s = model.scene {
                Text("통화 전 — 도착 시간순(규칙) · 병원을 누르면 오른쪽에 배후역량표").font(.system(size: 11.5)).foregroundStyle(AD.muted)
                ScrollView {
                    LazyVStack(spacing: 10) {
                        ForEach(sceneOrdered) { h in
                            Button { selectedId = h.hospitalId } label: {
                                SceneCard(h: h)
                                    .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous)
                                        .stroke(AD.blue, lineWidth: h.hospitalId == selectedScene?.hospitalId ? 2.5 : 0))
                            }
                            .buttonStyle(.plain)
                            .id("ts-\(s.caseId)-\(h.hospitalId)")
                        }
                    }
                    .padding(.bottom, 8)
                }
                .scrollIndicators(.visible)
            } else {
                Spacer(minLength: 0)
                VStack(spacing: 8) {
                    Image(systemName: "list.bullet.rectangle").font(.system(size: 30)).foregroundStyle(AD.muted)
                    Text(model.hasIncident ? "현장 도착 후 주변 병원 후보가 나타납니다" : "사고가 발생하면 여기에 병원 후보가 나타납니다")
                        .font(.system(size: 13, weight: .medium)).foregroundStyle(AD.ink3).multilineTextAlignment(.center)
                }
                .frame(maxWidth: .infinity)
                Spacer(minLength: 0)
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        .background(AD.card).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.line, lineWidth: 1))
    }

    /// 승인 · 대기 · 불가 숫자 — 예전 '병원 응답 현황' 카드의 집계를 리스트 머리로 옮긴 것
    private func responseCounts(_ r: HubMatchResult) -> some View {
        func key(_ h: HospitalMatch) -> String { h.status == "pending" && h.unavailableReason != nil ? "rejected" : h.status }
        let approved = r.hospitals.filter { ["approved", "confirmed"].contains($0.status) }.count
        let rejected = r.hospitals.filter { key($0) == "rejected" }.count
        let pending = r.hospitals.count - approved - rejected
        return HStack(spacing: 6) {
            count("승인", approved, AD.green, AD.greenSoft)
            count("대기", pending, AD.orange, AD.orangeSoft)
            count("불가", rejected, AD.red, AD.redSoft)
        }
    }
    private func count(_ label: String, _ n: Int, _ fg: Color, _ bg: Color) -> some View {
        HStack(spacing: 4) {
            Text(label).font(.system(size: 11.5, weight: .semibold)).foregroundStyle(n > 0 ? fg : AD.muted)
            Text("\(n)").font(.system(size: 13, weight: .heavy)).foregroundStyle(n > 0 ? fg : AD.muted)
        }
        .padding(.horizontal, 9).frame(minHeight: 24)
        .background(n > 0 ? bg : AD.chip).clipShape(Capsule())
    }

    /// 다음 존 확장까지(hub zoneExpandAt) — 예전 응답 현황 카드에 있던 한 줄
    @ViewBuilder private func zoneLine(_ r: HubMatchResult) -> some View {
        if model.confirmed == nil {
            if let left = r.zonePausedLeftSec {
                Text("· 일시정지 — 범위 확장까지 \(left)초에서 멈춤").font(.system(size: 11.5)).foregroundStyle(AD.ink3)
            } else if let at = r.zoneExpandAt.flatMap(ISO.parse) {
                let sec = max(0, Int(at.timeIntervalSince(model.now).rounded()))
                let next = max(1, r.zoneActive?.max() ?? 1) + 1
                (Text("· 응답 없으면 Zone \(next)로 확장 ") + Text("\(sec)초").bold().foregroundColor(AD.orange))
                    .font(.system(size: 11.5)).foregroundStyle(AD.ink3)
            } else if r.hospitals.contains(where: { $0.status == "approved" }) {
                Text("· 수용 승인 병원이 있어 범위 확장 멈춤").font(.system(size: 11.5)).foregroundStyle(AD.ink3)
            }
        }
    }

    // ── 오른쪽: 고른 병원의 배후역량(확정 병원이면 목적지 카드까지) ──
    @ViewBuilder private var right: some View {
        if let h = selected {
            VStack(spacing: 8) {
                if let c = model.confirmed, c.hospitalId == h.hospitalId {
                    DestinationCard(h: c)
                } else {
                    selectedHead(h)
                }
                BackupDetailCard(hospitalId: h.hospitalId, name: h.name)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        } else if let h = selectedScene {
            // 통화 전(현장 확인) — 후보가 뜨면 추천 병원 배후역량을 바로 보여 준다
            VStack(spacing: 8) {
                sceneHead(h)
                BackupDetailCard(hospitalId: h.hospitalId, name: h.name)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        } else {
            VStack(spacing: 8) {
                Image(systemName: "building.2").font(.system(size: 34)).foregroundStyle(AD.muted)
                Text("병원을 누르면 그 병원의 배후역량(병상·장비·전문의·공지)을 보여줍니다")
                    .font(.system(size: 14, weight: .medium)).foregroundStyle(AD.ink3).multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .card()
        }
    }

    /// 통화 전 현장 후보 — 이름·도착·병상·AI 유효(매칭 카드와 같은 값)
    private func sceneHead(_ h: SceneCandidate) -> some View {
        let live = h.bedReliability.map { BedReliability.live($0, now: model.now) }
        let doctors = h.specialties?.reduce(0) { $0 + ($1.doctorCount ?? 0) } ?? 0
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Text(h.name).font(.system(size: 16, weight: .heavy)).foregroundStyle(AD.navy).lineLimit(1)
                if let lv = h.emergencyLevel, lv.hasSuffix("센터") { Pill(text: lv.hasPrefix("권역") ? "권역센터" : "지역센터", bg: AD.blueSoft, fg: AD.blue) }
                Spacer(minLength: 0)
                if h.firstCallRecommended == true { Pill(text: "첫 연락 추천", bg: AD.greenSoft, fg: AD.green, bold: true) }
                else { Pill(text: "통화 전", bold: true) }
            }
            HStack(spacing: 8) {
                StatBox(label: "도착", value: h.etaMin.map { "\($0)분" } ?? "—", bg: AD.chip, fg: AD.ink3, valueColor: AD.navy)
                if h.bedCountUnknown == true { StatBox(label: "응급실 병상", value: "미상", bg: AD.chip, fg: AD.ink3) }
                else if (h.availableBedCount ?? 0) <= 0 { StatBox(label: "응급실 병상", value: "없음", bg: AD.redSoft, fg: AD.red) }
                else { StatBox(label: "응급실 병상", value: "\(h.availableBedCount ?? 0)석", bg: AD.limeSoft, fg: AD.lime) }
                if let lv = live { let t = Theme.validity(lv.rArrive); StatBox(label: "AI 도착 시 유효", value: BedReliability.pct(lv.rArrive), bg: t.bg, fg: t.fg) }
                else { StatBox(label: "AI 도착 시 유효", value: "—", bg: AD.chip, fg: AD.ink3) }
                StatBox(label: "전문의", value: doctors > 0 ? "\(doctors)명" : "—", bg: AD.chip, fg: AD.ink3, valueColor: AD.navy)
            }
            Text("통화가 끝나면 hub 순위·병원 응답으로 바뀝니다").font(.system(size: 11.5)).foregroundStyle(AD.muted)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }

    /// 확정 전에 고른 병원 — 이름·도착·병상·유효 한 줄 요약과 [왜 이 확률인가]
    private func selectedHead(_ h: HospitalMatch) -> some View {
        let live = h.bedReliability.map { BedReliability.live($0, now: model.now) }
        return VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Text(h.name).font(.system(size: 16, weight: .heavy)).foregroundStyle(AD.navy).lineLimit(1)
                if let lv = h.emergencyLevel, lv.hasSuffix("센터") { Pill(text: lv.hasPrefix("권역") ? "권역센터" : "지역센터", bg: AD.blueSoft, fg: AD.blue) }
                Spacer(minLength: 0)
                let p = Theme.statusPill(h.status == "pending" && h.unavailableReason != nil ? "rejected" : h.status)
                Pill(text: Labels.status(h.status), bg: p.bg, fg: p.fg, bold: true)
            }
            HStack(spacing: 8) {
                StatBox(label: "도착", value: h.etaMin.map { "\($0)분" } ?? h.travelMin.map { "\(Int($0.rounded()))분" } ?? "—",
                        bg: AD.chip, fg: AD.ink3, valueColor: AD.navy)
                if h.bedCountUnknown == true { StatBox(label: "응급실 병상", value: "미상", bg: AD.chip, fg: AD.ink3) }
                else if (h.availableBedCount ?? 0) <= 0 { StatBox(label: "응급실 병상", value: "없음", bg: AD.redSoft, fg: AD.red) }
                else { StatBox(label: "응급실 병상", value: "\(h.availableBedCount ?? 0)석", bg: AD.limeSoft, fg: AD.lime) }
                if let lv = live { let t = Theme.validity(lv.rArrive); StatBox(label: "AI 도착 시 유효", value: BedReliability.pct(lv.rArrive), bg: t.bg, fg: t.fg) }
                else { StatBox(label: "AI 도착 시 유효", value: "—", bg: AD.chip, fg: AD.ink3) }
                Button { detail = h } label: {
                    Text("왜 이 확률인가").font(.system(size: 12.5, weight: .bold)).foregroundStyle(AD.blue)
                        .padding(.horizontal, 12).frame(minHeight: 36).background(AD.blueSoft).clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .card()
    }
}


/// 재선택(2026-11-02, 안드로이드 재선택 화면과 같다) — 목적지 병원이 수용할 수 없게 됐을 때. 승인한(지금 보낼 수 있는) 병원이 있으면 바로 이송 승인하게 하고,
/// 없으면 수용 불가·제외 병원을 뺀 후보의 응답을 기다린다. 이송 승인을 보낸 뒤 hub가 확정할 때까지는 "확정하고 있습니다"로 붙잡는다.
struct ReselectBanner: View {
    @EnvironmentObject private var model: AppModel

    private var hospitals: [HospitalMatch] { model.result?.hospitals ?? [] }
    private var ready: [HospitalMatch] { hospitals.filter { HospitalRules.canTransportNow($0) } }
    private var deciding: HospitalMatch? { model.confirmed ?? hospitals.first { $0.hospitalId == model.pendingConfirmId } }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Pill(text: "재선택 대기", bg: AD.redSoft, fg: AD.red, bold: true)
                Text("목적지 병원이 수용할 수 없게 됐습니다").font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy)
            }
            if let d = deciding {
                HStack(spacing: 8) {
                    ProgressView()
                    Text("\(d.name)(으)로 이송을 확정하고 있습니다").font(.system(size: 14, weight: .bold)).foregroundStyle(AD.navy)
                }
            } else if !ready.isEmpty {
                Text("승인한 병원이 있습니다 — 바로 이송 승인하세요").font(.system(size: 12.5)).foregroundStyle(AD.ink3)
                ForEach(ready.prefix(4)) { h in
                    HStack(spacing: 8) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(h.name).font(.system(size: 14, weight: .semibold)).foregroundStyle(AD.navy).lineLimit(1)
                            Text(h.etaMin.map { "도착 \($0)분" } ?? "\(String(format: "%.1f", h.roadDistanceKm ?? h.distanceKm))km")
                                .font(.system(size: 12)).foregroundStyle(AD.ink3)
                        }
                        Spacer()
                        Button { model.approve(h.hospitalId) } label: {
                            Text("이송 승인").font(.system(size: 13, weight: .bold)).foregroundStyle(.white)
                                .padding(.horizontal, 14).frame(minHeight: 34).background(AD.green).clipShape(Capsule())
                        }.buttonStyle(.plain)
                    }
                    .padding(.horizontal, 12).padding(.vertical, 8)
                    .background(AD.greenSoft, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }
            } else {
                Text("승인한 병원이 없습니다. 수용 불가 병원은 빼고 후보 병원의 응답을 기다리는 중입니다 — 범위가 필요하면 자동으로 넓혀 다시 요청합니다.")
                    .font(.system(size: 12.5)).foregroundStyle(AD.orange).fixedSize(horizontal: false, vertical: true)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(14)
        .background(AD.card)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.red, lineWidth: 2))
    }
}
