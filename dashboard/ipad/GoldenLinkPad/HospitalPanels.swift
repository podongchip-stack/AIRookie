import SwiftUI

/// 선택 비교(2026-10-16) — 수용 승인한 병원이 2곳 이상이면 [이송] 탭 응답 현황 아래에. 병상 · 도착 시 유효(AI) · 도착 시간 · 전문의를 한 표로,
/// 칸마다 가장 나은 값을 굵은 초록으로. hub 1순위(추천)에 표시. 지금 보낼 수 없는 승인 병원(병상 0 확인·제외·차단)은 흐리게
struct CompareCard: View {
    @EnvironmentObject private var model: AppModel
    let hospitals: [HospitalMatch]
    let recommendedId: String?

    private struct Row { let h: HospitalMatch; let beds: Int?; let valid: Double?; let eta: Double?; let docs: Int?; let ok: Bool }

    var body: some View {
        // 승인 병원이 많아도 **상위 3곳만**(2026-10-28, hub 순위 그대로) — 표가 길어지면 비교가 아니라 또 하나의 목록이 된다.
        // 전체 목록은 아래 병원 리스트가 보여 준다
        let rows = hospitals.prefix(3).map { h in
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
                Text(hospitals.count > 3 ? "수용 승인 \(hospitals.count)곳 중 상위 3곳" : "수용 승인 \(hospitals.count)곳")
                    .font(.system(size: 11.5)).foregroundStyle(AD.muted)
                Spacer()
            }
            cells(["", "병상", "유효", "도착", "전문의"], header: true)
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
            Text("유효 = 도착 때 병상 숫자가 맞을 확률(AI) · 초록 굵게 = 그 칸 최고 · 결정은 아래 병원 카드의 [이송 승인]")
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
