import GoldenLinkCore
import SwiftUI

// [이송] 탭 — 아이패드 구급차 앱의 병원 리스트(CandidateCard)와 [이송 승인]을 폰 한 열로 옮겼다(안드로이드 TransportTab.kt와 같다).
// 순위는 hub가 정한 순서 그대로다(앱이 다시 정렬하지 않는다). 병원이 수용 승인한 병원에만 [이송 승인]이 열린다 — 최종 결정은 구급대원이다.

private let approveColor = Color(hex: 0xB45309)

private extension MatchResult {
    // 목록과 배지는 같은 승인 상태를 센다. 이송 확정 병원도 수용 승인한 병원에 포함한다.
    var acceptedHospitals: [Hospital] {
        hospitals.filter { $0.status == "approved" || $0.status == "confirmed" }
    }
}

/// 지금 이 환자를 실제로 보낼 수 있는 승인 병원인가 — 아이패드 HospitalRules.canTransportNow와 같은 규칙
func canTransportNow(_ h: MatchResult.Hospital) -> Bool {
    if h.status != "approved" || h.unavailableReason != nil || h.excluded == true { return false }
    if h.demoteReasons?.contains(where: { $0 == "beds_full" || $0 == "severe_blocked" }) == true { return false }
    if h.bedCountUnknown == true || h.bedDataStale == true { return true }
    return (h.availableBedCount ?? 1) > 0
}

struct TransportTab: View {
    @Environment(PhoneModel.self) private var m

    var body: some View {
        if let r = m.result {
            content(r)
        } else {
            StatusPanel(icon: "cross.case.fill", tint: AD.gray, title: "병원 응답을 기다리는 중",
                        detail: m.hasIncident ? "통화가 후보 병원에 전달되면 수용 승인·불가 응답이 여기에 모입니다." : "새 사건이 들어오면 후보 병원이 여기에 나타납니다.")
        }
    }

    @ViewBuilder private func content(_ r: MatchResult) -> some View {
        let confirmed = m.confirmed
        let candidates = r.acceptedHospitals
        if candidates.isEmpty {
            Text("수용 승인한 병원이 아직 없습니다. 병원 응답을 기다리고 있습니다.")
                .font(.subheadline).foregroundStyle(AD.sub).multilineTextAlignment(.center)
                .padding(.horizontal, 24)
                .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .center)
        } else {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("후보 병원").font(.system(size: 17, weight: .bold)).foregroundStyle(AD.navy)
                        Text(confirmed != nil ? "이송 확정 · \(confirmed!.name)" : "수용 승인 \(candidates.count)곳")
                            .font(.system(size: 12, weight: confirmed != nil ? .bold : .regular))
                            .foregroundStyle(confirmed != nil ? AD.green : AD.ink3)
                    }
                    Text(m.inTransport ? "이송 중에도 새로 승인한 병원이 있으면 다시 고를 수 있습니다."
                         : "병원이 수용을 승인하면 [이송 승인]이 열립니다. 순서는 hub가 정한 그대로입니다.")
                        .font(.system(size: 11.5)).foregroundStyle(AD.sub)
                }
                .padding(.horizontal, 4)

                if candidates.isEmpty { Text("수용 승인한 병원이 아직 없습니다. 병원 응답을 기다리고 있습니다.").font(.subheadline).foregroundStyle(AD.sub).padding() }
                ForEach(candidates, id: \.hospitalId) { h in
                    CandidateCard(h: h, recommended: confirmed == nil && h.hospitalId == r.hospitals.first(where: canTransportNow)?.hospitalId)
                }
            }
            .padding(.bottom, 8)
        }
        .scrollIndicators(.hidden)
        }
    }
}

private struct CandidateCard: View {
    @Environment(PhoneModel.self) private var m
    let h: MatchResult.Hospital
    let recommended: Bool

    var body: some View {
        TimelineView(.periodic(from: .now, by: 1)) { ctx in
            let confirmedHere = m.confirmed?.hospitalId == h.hospitalId
            let requesting = m.pendingConfirmId == h.hospitalId && !confirmedHere
            let unavailable = h.status == "pending" && h.unavailableReason != nil
            let statusKey = unavailable ? "rejected" : h.status
            let live = h.bedReliability.map { BedLive.of($0, now: ctx.date.timeIntervalSince1970 * 1000) }

            Card(border: confirmedHere ? AD.green : (recommended ? approveColor : AD.control), borderWidth: confirmedHere ? 3 : (recommended ? 2 : 1)) {
                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .top, spacing: 8) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(h.name).font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy).lineLimit(2)
                            Text(distanceText(h)).font(.system(size: 12)).foregroundStyle(AD.ink3)
                        }
                        Spacer(minLength: 4)
                        VStack(alignment: .trailing, spacing: 4) {
                            if recommended { Pill(text: "추천", fg: approveColor, bg: AD.orangeSoft, bold: true) }
                            let (fg, bg) = statusColors(statusKey)
                            Pill(text: statusText(requesting: requesting, confirmed: confirmedHere, unavailable: unavailable), fg: fg, bg: bg, bold: true)
                        }
                    }
                    HStack(spacing: 8) {
                        bedBox
                        if let live {
                            let (fg, bg) = validityColors(live.rArrive)
                            StatBox(label: "AI 유효", value: BedLive.pct(live.rArrive) + (h.bedReliability?.confirmedAgeSec != nil ? " ✓" : ""), fg: fg, bg: bg)
                        } else {
                            StatBox(label: "AI 유효", value: "—", fg: AD.ink3, bg: AD.chip)
                        }
                        StatBox(label: "전문의", value: h.specialtyMatch?.doctorCount.map { "\($0)명" } ?? "—", fg: AD.ink3, bg: AD.chip, valueColor: AD.navy)
                    }
                    let chips = chipsOf(h)
                    if !chips.isEmpty {
                        ScrollView(.horizontal) {
                            HStack(spacing: 5) { ForEach(Array(chips.enumerated()), id: \.offset) { _, c in Pill(text: c.0, fg: c.1, bg: c.2) } }
                        }.scrollIndicators(.hidden)
                    }
                    validityLine(live)
                    actionButton(confirmedHere: confirmedHere, requesting: requesting, statusKey: statusKey)
                }
            }
        }
    }

    private func distanceText(_ h: MatchResult.Hospital) -> String {
        let dist = h.roadDistanceKm.map { String(format: "%.1fkm", $0) } ?? String(format: "직선 %.1fkm", h.distanceKm)
        if let eta = h.etaMin { return "\(dist) · ETA \(Int(eta.rounded()))분" }
        if let travel = h.travelMin { return "\(dist) · 약 \(Int(travel.rounded()))분(직선 추정)" }
        return dist
    }

    private func statusText(requesting: Bool, confirmed: Bool, unavailable: Bool) -> String {
        if requesting { return "확정 요청 중" }
        if unavailable { return "수용 불가 · " + DisplayLabels.reject(h.unavailableReason) }
        if h.status == "rejected", h.rejectReason != nil { return "수용 불가 · " + DisplayLabels.reject(h.rejectReason) }
        return DisplayLabels.status(h.status)
    }

    private func statusColors(_ s: String) -> (Color, Color) {
        switch s {
        case "approved": return (AD.blue, AD.blueSoft)
        case "rejected": return (AD.red, AD.redSoft)
        case "confirmed": return (AD.green, AD.greenSoft)
        default: return (AD.orange, AD.orangeSoft)
        }
    }

    private func validityColors(_ p: Double) -> (Color, Color) {
        if p >= 0.8 { return (AD.blue, AD.blueSoft) }
        if p >= 0.5 { return (AD.ink3, AD.chip) }
        return (AD.red, AD.redSoft)
    }

    @ViewBuilder private var bedBox: some View {
        let cap = h.erBedCapacity.map { "/\($0)" } ?? ""
        let avail = h.availableBedCount ?? 0
        if h.bedCountUnknown == true {
            StatBox(label: "병상", value: "미상", fg: AD.ink3, bg: AD.chip)
        } else if avail <= 0 {
            StatBox(label: h.erOccupancyPct.map { "병상 · \($0)%" } ?? "병상", value: h.erBedCapacity != nil ? "0\(cap)" : "없음", fg: AD.red, bg: AD.redSoft)
        } else {
            let label = [h.bedDataStale == true ? "병상 · 1일↑" : "병상", h.erOccupancyPct.map { "\($0)%" }].compactMap { $0 }.joined(separator: " · ")
            StatBox(label: label, value: h.erBedCapacity != nil ? "\(avail)\(cap)" : "\(avail)석", fg: AD.lime, bg: AD.limeSoft)
        }
    }

    private func chipsOf(_ h: MatchResult.Hospital) -> [(String, Color, Color)] {
        var out: [(String, Color, Color)] = []
        if h.demoteReasons?.contains("declared_no") == true { out.append(("수용 불가 신고", AD.red, AD.redSoft)) }
        if h.demoteReasons?.contains("severe_blocked") == true { out.append(("병원 차단 메시지", AD.red, AD.redSoft)) }
        if let sm = h.specialtyMatch {
            let pct = Int(((sm.score ?? 0) * 100).rounded())
            if sm.department == nil {
                out.append(("진료과 정보 미상", AD.ink3, AD.chip))
            } else if sm.basis != "exact", (sm.score ?? 0) < 0.3 {
                out.append(("\(sm.department!) · 적합도 낮음 \(pct)%", AD.ink3, AD.chip))
            } else {
                out.append(("\(sm.department!) · " + (sm.basis == "exact" ? "필요 진료과 일치" : "적합도 \(pct)%"), AD.blue, AD.blueSoft))
            }
        }
        if let n = h.inFlightCount, n > 0 {
            let min = h.loadPenaltyMin.flatMap { $0 > 0 ? " · +\($0.rounded() == $0 ? String(Int($0)) : String(format: "%.1f", $0))분" : nil } ?? ""
            out.append(("이송 중 \(n)건" + min, AD.orange, AD.orangeSoft))
        }
        if let level = h.emergencyLevel, level.hasSuffix("센터") { out.append((level, AD.ink3, AD.chip)) }
        return out
    }

    @ViewBuilder private func validityLine(_ live: BedLive.Live?) -> some View {
        if let live, let br = h.bedReliability {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 4) {
                    Text("AI · 병상 정보 지금 유효").font(.system(size: 11.5)).foregroundStyle(AD.sub)
                    Text(BedLive.pct(live.authority)).font(.system(size: 11.5, weight: .bold)).foregroundStyle(validityColors(live.authority).0)
                    Text("→ 도착 시").font(.system(size: 11.5)).foregroundStyle(AD.sub)
                    Text(BedLive.pct(live.rArrive)).font(.system(size: 11.5, weight: .bold)).foregroundStyle(validityColors(live.rArrive).0)
                }
                GeometryReader { geo in
                    ZStack(alignment: .leading) {
                        Capsule().fill(AD.line)
                        Capsule().fill(validityColors(live.rArrive).0).frame(width: geo.size.width * CGFloat(min(max(live.rArrive, 0), 1)))
                    }
                }.frame(height: 5)
                var parts: [String] {
                    var p: [String] = []
                    if let age = live.ageSec { p.append("정보 " + DisplayLabels.age(age)) }
                    p.append("도착까지 " + DisplayLabels.minutes(br.horizonSec ?? 0))
                    if br.confirmedAgeSec != nil { p.append("병원 확인 ✓") }
                    if h.bedDataStale == true { p.append("⚠ 1일 넘은 값") }
                    return p
                }
                Text(parts.joined(separator: " · ")).font(.system(size: 11)).foregroundStyle(AD.muted).lineLimit(1)
            }
        } else {
            Text(h.bedCountUnknown == true ? "AI · 병상 미상 — 유효 확률을 내지 않습니다" : "AI · 병상 신뢰도 정보 없음")
                .font(.system(size: 11.5)).foregroundStyle(AD.sub)
        }
    }

    @ViewBuilder private func actionButton(confirmedHere: Bool, requesting: Bool, statusKey: String) -> some View {
        let approvable = h.status == "approved" || h.status == "confirmed"
        Group {
            if confirmedHere {
                bigButtonLabel("이송 확정됨", bg: AD.greenSoft, fg: AD.green)
            } else if requesting {
                bigButtonLabel("확정 요청 중…", bg: AD.orangeSoft, fg: approveColor)
            } else if approvable {
                Button { m.approve(h.hospitalId) } label: { bigButtonLabel("이송 승인", bg: m.paused ? AD.gray : approveColor, fg: .white) }
                    .buttonStyle(.plain).disabled(m.paused)
            } else {
                bigButtonLabel(h.excluded == true ? "이 사건에서 제외됨" : (statusKey == "rejected" ? "수용 불가" : "병원 응답 대기"), bg: AD.chip, fg: AD.muted)
            }
        }
    }

    private func bigButtonLabel(_ text: String, bg: Color, fg: Color) -> some View {
        Text(text).font(.system(size: 14, weight: .bold)).foregroundStyle(fg)
            .frame(maxWidth: .infinity, minHeight: 44).background(bg, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }
}

/// 아래 탭 — 이송 목록에 표시되는 수용 승인 병원 수만 배지로 표시한다. 승인 전에는 숨긴다.
struct TabBar: View {
    @Environment(PhoneModel.self) private var m

    private var badge: (String, Color)? {
        if let r = m.result {
            let ok = r.acceptedHospitals.count
            return ok > 0 ? ("승인 \(ok)", AD.green) : nil
        }
        return nil
    }

    var body: some View {
        HStack(spacing: 2) {
            ForEach([(PhoneModel.Tab.call, "통화"), (.patient, "환자 정보"), (.transport, "이송"), (.records, "기록")], id: \.0) { tab, title in
                let on = m.tab == tab
                Button { m.tab = tab } label: {
                    HStack(spacing: 0) {
                        Text(title).font(.system(size: 13, weight: on ? .bold : .medium)).foregroundStyle(on ? AD.navy : AD.ink3).lineLimit(1)
                        if tab == .transport, let badge {
                            Text(badge.0).font(.system(size: 10.5, weight: .bold)).foregroundStyle(.white).lineLimit(1)
                                .padding(.horizontal, 6).padding(.vertical, 1)
                                .background(badge.1, in: Capsule()).padding(.leading, 5)
                        }
                    }
                    .frame(maxWidth: .infinity, minHeight: 38)
                    .background(on ? Color.white : Color.clear, in: Capsule())
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(AD.chip, in: Capsule())
    }
}
