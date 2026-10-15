import SwiftUI

/// 병원 후보 카드들(2026-10-16) — 병원 리스트 화면(HospitalListScreen.swift)의 격자에 들어간다. 예전엔 구급차 화면 아래
/// 가로 스크롤 띠였다. 카드 폭은 격자 칸에 맞춘다.

/// 지금 이 환자를 실제로 보낼 수 있는 승인 병원인가 — "추천"·"더 나은 병원"이 같은 규칙을 쓴다(spider 초록 줄·웹과 같음, 2026-10-15)
enum HospitalRules {
    static func canTransportNow(_ h: HospitalMatch) -> Bool {
        guard h.status == "approved", h.unavailableReason == nil, h.excluded != true else { return false }
        if (h.demoteReasons ?? []).contains(where: { $0 == "beds_full" || $0 == "severe_blocked" }) { return false }
        if h.bedCountUnknown == true || h.bedDataStale == true { return true }
        return (h.availableBedCount ?? 1) > 0
    }
}


/// 매칭 결과 카드 — 이름 · 거리 · ETA · 상태 | 병상 · AI 유효 · 전문의 | 칩 | 정보 유효성 한 줄 | [이송 승인]
struct CandidateCard: View {
    @EnvironmentObject private var model: AppModel
    var h: HospitalMatch
    var recommended: Bool
    var confirmedId: String?
    var requesting: Bool
    /// 병원 리스트 화면처럼 넓을 때는 칩을 접지 않고 줄바꿈으로 다 보인다
    var allChips = false
    var onDetail: () -> Void

    private var confirmed: Bool { h.hospitalId == confirmedId }
    private var unavailable: Bool { h.status == "pending" && h.unavailableReason != nil }
    private var statusKey: String { unavailable ? "rejected" : h.status }
    private var live: BedReliability.Live? { h.bedReliability.map { BedReliability.live($0, now: model.now) } }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Button(action: onDetail) {
                VStack(alignment: .leading, spacing: 5) {
                    head
                    stats
                    chips
                    validityLine
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            Spacer(minLength: 0)
            actionButton
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(AD.card)
        .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous)
            .stroke(confirmed ? AD.green : recommended ? AD.approve : AD.control, lineWidth: confirmed ? 3 : recommended ? 2 : 1))
        .opacity(statusKey == "rejected" && !confirmed ? 0.72 : 1)
    }

    private var head: some View {
        HStack(alignment: .top, spacing: 10) {
            VStack(alignment: .leading, spacing: 2) {
                Text(h.name).font(.system(size: 14, weight: .bold)).foregroundStyle(AD.navy).lineLimit(1)
                HStack(spacing: 0) {
                    Text(Labels.distance(km: h.distanceKm, road: h.roadDistanceKm)).foregroundStyle(AD.ink)
                    if let e = h.etaMin { Text(" · ETA ").foregroundStyle(AD.ink3); Text("\(e)분").foregroundStyle(AD.ink) }
                    else if let t = h.travelMin { Text(" · 약 \(Int(t.rounded()))분(직선 추정)").foregroundStyle(AD.ink3) }
                }.font(.system(size: 12))
            }
            Spacer(minLength: 0)
            HStack(spacing: 4) {
                if recommended { Pill(text: "추천", bg: AD.orangeSoft, fg: AD.approve, bold: true) }
                let p = Theme.statusPill(statusKey)
                Pill(text: statusText, bg: p.bg, fg: p.fg, bold: true)
            }
        }
    }

    private var statusText: String {
        if requesting && !confirmed { return "확정 요청 중" }
        if unavailable { return "수용 불가 · \(Labels.reject(h.unavailableReason))" }
        if h.status == "rejected", h.rejectReason != nil { return "수용 불가 · \(Labels.reject(h.rejectReason))" }
        return Labels.status(h.status)
    }

    private var stats: some View {
        HStack(spacing: 8) {
            bedBox
            if let lv = live {
                let t = Theme.validity(lv.rArrive)
                StatBox(label: "AI 유효", value: "\(BedReliability.pct(lv.rArrive))\(h.bedReliability?.confirmedAgeSec != nil ? " ✓" : "")", bg: t.bg, fg: t.fg)
            } else {
                StatBox(label: "AI 유효", value: "—", bg: AD.chip, fg: AD.ink3)
            }
            StatBox(label: "전문의", value: h.specialtyMatch?.doctorCount.map { "\($0)명" } ?? "—", bg: AD.chip, fg: AD.ink3, valueColor: AD.navy)
        }
    }

    @ViewBuilder private var bedBox: some View {
        let cap = h.erBedCapacity.map { "/\($0)" } ?? ""
        if h.bedCountUnknown == true {
            StatBox(label: "병상", value: "미상", bg: AD.chip, fg: AD.ink3)
        } else if (h.availableBedCount ?? 0) <= 0 {
            StatBox(label: h.erOccupancyPct.map { "병상 · \($0)%" } ?? "병상", value: h.erBedCapacity != nil ? "0\(cap)" : "없음", bg: AD.redSoft, fg: AD.red)
        } else {
            StatBox(label: [h.bedDataStale == true ? "병상 · 1일↑" : "병상", h.erOccupancyPct.map { "\($0)%" }].compactMap { $0 }.joined(separator: " · "),
                    value: h.erBedCapacity != nil ? "\(h.availableBedCount ?? 0)\(cap)" : "\(h.availableBedCount ?? 0)석", bg: AD.limeSoft, fg: AD.lime)
        }
    }

    /// 칩은 한 줄로 — 중요한 것부터 3개, 나머지는 "+N"(대량사고 때 칩이 여러 줄로 늘어 카드가 커지던 것, 2026-10-14). 전부는 상세에서.
    private var chips: AnyView {
        var items: [(String, Color, Color)] = []
        if h.demoteReasons?.contains("declared_no") == true { items.append(("수용 불가 신고", AD.redSoft, AD.red)) }
        if h.demoteReasons?.contains("severe_blocked") == true { items.append(("병원 차단 메시지", AD.redSoft, AD.red)) }
        if let sm = h.specialtyMatch {
            if sm.department == nil { items.append(("진료과 정보 미상", AD.chip, AD.ink3)) }
            else if sm.basis != "exact", (sm.score ?? 0) < 0.3 { items.append(("\(sm.department ?? "") · 적합도 낮음 \(Int(((sm.score ?? 0) * 100).rounded()))%", AD.chip, AD.ink3)) }
            else { items.append(("\(sm.department ?? "") · \(sm.basis == "exact" ? "필요 진료과 일치" : "적합도 \(Int(((sm.score ?? 0) * 100).rounded()))%")", AD.blueSoft, AD.blue)) }
        }
        if let n = h.inFlightCount, n > 0 { items.append(("이송 중 \(n)건\(h.loadPenaltyMin.map { $0 > 0 ? " · +\(fmt($0))분" : "" } ?? "")", AD.orangeSoft, AD.orange)) }
        if let lvl = h.emergencyLevel, lvl.hasSuffix("센터") { items.append((lvl, AD.chip, AD.ink3)) }
        if let r = h.reliability { items.append(("\(r.group) · \(Labels.confidence(r.confidence))", r.confidence == "high" ? AD.greenSoft : AD.chip, r.confidence == "high" ? AD.green : AD.ink3)) }
        if let sf = h.severeFreshness { items.append(("\(sf.value == "Y" ? "수용가능 신고" : "수용불가 신고") \(Labels.age(sf.ageSec, isMin: sf.ageIsMin ?? false))", AD.chip, AD.ink3)) }
        if allChips {
            return AnyView(FlowLayout(spacing: 5) { ForEach(Array(items.enumerated()), id: \.offset) { _, c in Pill(text: c.0, bg: c.1, fg: c.2).lineLimit(1) } }
                .frame(maxWidth: .infinity, alignment: .leading))
        }
        let shown = Array(items.prefix(3))
        return AnyView(HStack(spacing: 5) {
            ForEach(Array(shown.enumerated()), id: \.offset) { _, c in Pill(text: c.0, bg: c.1, fg: c.2) }
            if items.count > shown.count { Pill(text: "+\(items.count - shown.count)", bg: AD.chip, fg: AD.sub, bold: true) }
            Spacer(minLength: 0)
        }
        .lineLimit(1))
    }

    /// 정보 유효성(4-1) — 지금 / 도착 시 확률과 "왜"를 한 줄로: 정보 나이 · 도착까지 이동 · 병원 확인 · 1일 넘은 값
    @ViewBuilder private var validityLine: some View {
        if let lv = live, let br = h.bedReliability {
            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 4) {
                    Text("AI · 병상 정보 지금 유효").foregroundStyle(AD.sub)
                    Text(BedReliability.pct(lv.authority)).bold().foregroundStyle(Theme.validity(lv.authority).fg)
                    Text("→ 도착 시").foregroundStyle(AD.sub)
                    Text(BedReliability.pct(lv.rArrive)).bold().foregroundStyle(Theme.validity(lv.rArrive).fg)
                    Spacer(minLength: 0)
                    Image(systemName: "info.circle").foregroundStyle(AD.blue)
                }.font(.system(size: 11.5))
                ProbBar(value: lv.rArrive, height: 5)
                Text(reasonLine(lv, br)).font(.system(size: 11)).foregroundStyle(AD.muted).lineLimit(1)
            }
        } else {
            Text(h.bedCountUnknown == true ? "AI · 병상 미상 — 유효 확률을 내지 않습니다" : "AI · 병상 신뢰도 정보 없음")
                .font(.system(size: 11.5)).foregroundStyle(AD.sub)
        }
    }

    private func reasonLine(_ lv: BedReliability.Live, _ br: BedReliabilityMatch) -> String {
        var parts: [String] = []
        if let a = lv.ageSec { parts.append("정보 \(Labels.age(a))") }
        parts.append("도착까지 \(Labels.minutes(br.horizonSec))")
        if br.confirmedAgeSec != nil { parts.append("병원 확인 ✓") }
        if h.bedDataStale == true { parts.append("⚠ 1일 넘은 값") }
        if let byType = h.bedReliabilityByType, !byType.isEmpty {
            let s = byType.sorted { $0.key < $1.key }.prefix(2).map { "\(Labels.bedField[$0.key] ?? $0.key) \(BedReliability.pct(BedReliability.live($0.value, now: model.now).rArrive))" }
            parts.append(s.joined(separator: " "))
        }
        return parts.joined(separator: " · ")
    }

    @ViewBuilder private var actionButton: some View {
        let approvable = h.status == "approved" || h.status == "confirmed"
        if confirmed {
            bigButton("이송 확정됨", bg: AD.greenSoft, fg: AD.green, border: AD.green)
        } else if requesting {
            bigButton("확정 요청 중…", bg: AD.orangeSoft, fg: AD.approve, border: AD.approve)
        } else if approvable {
            Button { model.approve(h.hospitalId) } label: { bigButton("이송 승인", bg: model.paused ? AD.gray : AD.approve, fg: .white, border: nil) }
                .disabled(model.paused)
        } else {
            bigButton(h.excluded == true ? "이 사건에서 제외됨" : statusKey == "rejected" ? "수용 불가" : "병원 응답 대기", bg: AD.chip, fg: AD.muted, border: nil, small: true)
        }
    }

    private func bigButton(_ t: String, bg: Color, fg: Color, border: Color?, small: Bool = false) -> some View {
        Text(t).font(.system(size: small ? 13 : 14, weight: .bold)).foregroundStyle(fg)
            .frame(maxWidth: .infinity, minHeight: 38)
            .background(bg).clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(border ?? .clear, lineWidth: 2))
    }

    private func fmt(_ v: Double) -> String { v.rounded() == v ? String(Int(v)) : String(format: "%.1f", v) }
}

/// 통화 전 현장 후보 카드(도착 시간순, 첫 연락 추천)
struct SceneCard: View {
    @EnvironmentObject private var model: AppModel
    var h: SceneCandidate

    var body: some View {
        let live = h.bedReliability.map { BedReliability.live($0, now: model.now) }
        let doctors = h.specialties?.reduce(0) { $0 + ($1.doctorCount ?? 0) } ?? 0
        VStack(alignment: .leading, spacing: 5) {
            HStack(alignment: .top) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(h.name).font(.system(size: 14, weight: .bold)).foregroundStyle(AD.navy).lineLimit(1)
                    Text(Labels.distance(km: h.distanceKm, road: h.roadDistanceKm) + (h.etaMin.map { " · ETA \($0)분" } ?? ""))
                        .font(.system(size: 12)).foregroundStyle(AD.ink3)
                }
                Spacer()
                if h.firstCallRecommended == true { Pill(text: "첫 연락 추천", bg: AD.greenSoft, fg: AD.green, bold: true) }
                else { Pill(text: "통화 전", bold: true) }
            }
            HStack(spacing: 8) {
                if h.bedCountUnknown == true { StatBox(label: "병상", value: "미상", bg: AD.chip, fg: AD.ink3) }
                else if (h.availableBedCount ?? 0) <= 0 { StatBox(label: "병상", value: "없음", bg: AD.redSoft, fg: AD.red) }
                else { StatBox(label: "병상", value: "\(h.availableBedCount ?? 0)석", bg: AD.limeSoft, fg: AD.lime) }
                if let lv = live { let t = Theme.validity(lv.rArrive); StatBox(label: "AI 유효", value: BedReliability.pct(lv.rArrive), bg: t.bg, fg: t.fg) }
                else { StatBox(label: "AI 유효", value: "—", bg: AD.chip, fg: AD.ink3) }
                StatBox(label: "전문의", value: doctors > 0 ? "\(doctors)명" : "—", bg: AD.chip, fg: AD.ink3, valueColor: AD.navy)
            }
            HStack(spacing: 5) {
                if let sp = h.specialties, !sp.isEmpty {
                    Pill(text: sp.prefix(3).map(\.department).joined(separator: "·") + (sp.count > 3 ? " 외 \(sp.count - 3)과" : ""), bg: AD.blueSoft, fg: AD.blue)
                }
                if let lvl = h.emergencyLevel, lvl.hasSuffix("센터") { Pill(text: lvl) }
                Spacer(minLength: 0)
            }.lineLimit(1)
            if let lv = live {
                VStack(alignment: .leading, spacing: 3) {
                    Text("AI · 지금 유효 \(BedReliability.pct(lv.authority)) → 도착 시 \(BedReliability.pct(lv.rArrive))\(lv.ageSec.map { " · 정보 \(Labels.age($0))" } ?? "")")
                        .font(.system(size: 11.5)).foregroundStyle(AD.sub)
                    ProbBar(value: lv.rArrive, height: 5)
                }
            }
            Spacer(minLength: 0)
            Text("통화 후 병원 응답을 받으면 승인").font(.system(size: 13, weight: .bold)).foregroundStyle(AD.muted)
                .frame(maxWidth: .infinity, minHeight: 38).background(AD.chip).clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .frame(maxWidth: .infinity, alignment: .topLeading)
        .frame(maxHeight: .infinity, alignment: .top)
        .background(AD.card).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(h.firstCallRecommended == true ? AD.green : AD.control, lineWidth: h.firstCallRecommended == true ? 2 : 1))
    }
}

struct SkeletonCard: View {
    var index: Int
    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("후보 \(index)").font(.system(size: 14, weight: .bold)).foregroundStyle(AD.muted)
            RoundedRectangle(cornerRadius: 5).fill(AD.line).frame(width: 150, height: 10)
            HStack(spacing: 8) { ForEach(0..<3, id: \.self) { _ in RoundedRectangle(cornerRadius: 12).fill(Color(hex: 0xEEF0F4)).frame(height: 40) } }
            RoundedRectangle(cornerRadius: 5).fill(AD.line).frame(width: 220, height: 10)
            Spacer(minLength: 0)
            RoundedRectangle(cornerRadius: 14).fill(AD.line).frame(height: 38)
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .frame(maxWidth: .infinity).frame(maxHeight: .infinity, alignment: .top)
        .background(AD.skeleton).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.gray, style: StrokeStyle(lineWidth: 1, dash: [4, 3])))
    }
}

/// 상세 — 이 병원 정보가 얼마나 유효한가와 그 이유(정보 생존 모델·신고 신선도·심평원 대조·순위 근거·E-Gen 공지)
struct ValidityDetailView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    var h: HospitalMatch

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 12) {
                    header
                    survivalSection
                    declarationSection
                    rankSection
                    messagesSection
                }.padding(18)
            }
            .background(AD.bg)
            .navigationTitle(h.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("닫기") { dismiss() } } }
        }
        .presentationDetents([.large])
    }

    private var live: BedReliability.Live? { h.bedReliability.map { BedReliability.live($0, now: model.now) } }

    private var header: some View {
        HStack(spacing: 8) {
            if let g = h.emergencyLevel { Pill(text: g, bg: AD.blueSoft, fg: AD.blue, bold: true) }
            let p = Theme.statusPill(h.status)
            Pill(text: Labels.status(h.status), bg: p.bg, fg: p.fg, bold: true)
            if let r = h.rejectReason ?? h.unavailableReason { Pill(text: Labels.reject(r), bg: AD.redSoft, fg: AD.red) }
            if h.excluded == true { Pill(text: "이 사건에서 제외", bg: AD.redSoft, fg: AD.red) }
            Spacer()
            Text("\(Labels.distance(km: h.distanceKm, road: h.roadDistanceKm)) · 존 \(h.zone ?? 1)").font(.system(size: 12)).foregroundStyle(AD.ink3)
        }
    }

    private var survivalSection: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionTitle(text: "정보 생존 모델 — 응급실 병상 숫자가 아직 맞을 확률", sub: "AI · XGBoost AFT 생존모델")
            if let br = h.bedReliability, let lv = live {
                HStack(spacing: 28) {
                    bigStat("지금", lv.authority)
                    bigStat("도착 시 (\(Labels.minutes(br.horizonSec)) 뒤)", lv.rArrive)
                    VStack(alignment: .leading, spacing: 4) {
                        ProbBar(value: lv.rArrive, height: 10)
                        Text(lv.live ? "초 단위로 감쇠 중 — hub가 보낸 생존곡선을 앱이 같은 식으로 계산" : "매칭 시점 값(곡선 파라미터 없음)")
                            .font(.system(size: 11)).foregroundStyle(AD.muted)
                    }
                }
                Divider().overlay(AD.line)
                Text("왜 이 확률인가").font(.system(size: 13, weight: .bold)).foregroundStyle(AD.navy)
                if let a = lv.ageSec {
                    reason("정보 나이", "이 병상 값이 생긴 지 \(Labels.age(a)). 값은 환자가 드나들 때마다 바뀌고, 시간이 갈수록 그대로일 확률이 내려갑니다.")
                }
                if let m = br.predictedSurvivalSec {
                    reason("모델 예측 수명", "이 병원·이 시각·이 값이 \(Labels.minutes(m)) 안에 \(model.liveBoard?.theta ?? 3)석 이상 바뀔 확률이 반반(중앙값). 병원별 갱신 리듬·시간대·규모·정원 대비 비율로 학습했습니다.")
                }
                reason("도착까지", "이동 \(Labels.minutes(br.horizonSec)) — 순위에 쓴 이동시간(카카오 내비 ETA, 없으면 보정 추정)과 같은 값. 그만큼 더 지난 뒤의 확률이 '도착 시'입니다.")
                if br.confirmedAgeSec != nil {
                    reason("병원 확인 ✓", "병원이 '현재 정보가 맞습니다'를 눌렀습니다 — 확인 시점 기준 조건부 생존으로 되올린 값입니다.")
                }
                if h.bedDataStale == true {
                    reason("⚠ 1일 넘은 값", "마지막 갱신이 하루를 넘었거나 실시간 피드에 없는 병원 — 만실·확률 판단에 쓰지 않습니다.")
                }
                if let byType = h.bedReliabilityByType, !byType.isEmpty {
                    reason("배후진료", byType.sorted { $0.key < $1.key }.map { "\(Labels.bedField[$0.key] ?? $0.key) 도착 시 \(BedReliability.pct(BedReliability.live($0.value, now: model.now).rArrive))" }.joined(separator: " · "))
                }
                reason("모델", "\(br.modelTag ?? "infosurv") · 순위(finalScore)에는 쓰지 않는 설명용 확률")
            } else {
                Text(h.bedCountUnknown == true ? "병상 수가 미상이라 확률을 내지 않습니다 — 미상을 만실처럼 다루지 않는 원칙(뺑뺑이 방지)." : "이 병원에는 모델 값이 없습니다(구 데이터 또는 피드 없음).")
                    .font(.system(size: 13)).foregroundStyle(AD.ink3)
            }
        }.card(16)
    }

    private func bigStat(_ label: String, _ p: Double) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.system(size: 12)).foregroundStyle(AD.sub)
            Text(BedReliability.pct(p)).font(.system(size: 34, weight: .black)).foregroundStyle(Theme.validity(p).fg)
        }
    }

    private var declarationSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "병원 신고의 유효성", sub: "중증질환 수용 신고 · 심평원 대조")
            if let sf = h.severeFreshness {
                reason("\(sf.group) 신고", "\(sf.value == "Y" ? "수용 가능" : "수용 불가") — \(Labels.age(sf.ageSec, isMin: sf.ageIsMin ?? false)) 신고\(sf.ageIsMin == true ? "(수집 시작 전부터라 실제론 더 오래됨)" : "")\(sf.ruleRemainingSec.map { $0 > 0 ? " · 통상 9시간 만료 규칙까지 \(Labels.minutes($0))" : " · 9시간 규칙 만료 뒤에도 유지 중(병원이 갱신 지속)" } ?? "")")
            }
            if let r = h.reliability {
                reason("\(r.group) 심평원 대조", "\(Labels.confidence(r.confidence)) · 점수 \(String(format: "%.1f", r.score)) (불가능 0.2 < 근거 없는 미상 0.4 < 전문의 있는 미상 0.6 < 전문병원 지정 미상 0.8 < 가능 신고 1.0)")
                ForEach(r.basis ?? [], id: \.self) { b in
                    Text("· " + b).font(.system(size: 12)).foregroundStyle(AD.ink3).padding(.leading, 100)
                }
            }
            if h.severeFreshness == nil && h.reliability == nil {
                Text("이 환자의 질환군에 해당하는 신고가 없거나(일반 질환) 판정 데이터가 없습니다.").font(.system(size: 13)).foregroundStyle(AD.ink3)
            }
            Text("신선도는 '언제 적 신고인가'(규칙), 심평원 대조는 '그 신고를 믿을 만한가'(전문의·전문병원 지정 근거). 순위에는 수용 불가 신고만 순서로 반영합니다.")
                .font(.system(size: 11)).foregroundStyle(AD.muted)
        }.card(16)
    }

    private var rankSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "왜 이 순위인가", sub: "규칙 기반 · 0.6×진료과 + 0.4×이동시간")
            if let s = h.finalScore { reason("순위 점수", String(format: "%.3f", s)) }
            if let sm = h.specialtyMatch {
                reason("진료과", "\(sm.department ?? "—") · \(sm.basis == "exact" ? "필요 진료과 정확 일치 1.0" : sm.basis == "embedding" ? "임베딩 적합도 \(Int(((sm.score ?? 0) * 100).rounded()))%" : "진료과 정보 없음")\(sm.doctorCount.map { " · 전문의 \($0)명" } ?? "")")
            }
            if let t = h.travelMin { reason("이동시간", "\(String(format: "%.1f", t))분 (\(h.travelBasis == "eta" ? "카카오 내비 ETA" : "직선거리 보정 추정"))") }
            ForEach(h.bonusReasons ?? [], id: \.self) { b in reason("가산", b) }
            if let l = h.loadReason { reason("부하", l) }
            if let o = h.occupancyReason { reason("포화도", o) }
            ForEach(h.demoteReasons ?? [], id: \.self) { d in reason("뒤로 내림", Labels.demote(d)) }
        }.card(16)
    }

    @ViewBuilder private var messagesSection: some View {
        if let msgs = h.acceptanceMessages, !msgs.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                SectionTitle(text: "병원 공지(E-Gen 메시지)", sub: "병원이 직접 건 수용 제한")
                ForEach(Array(msgs.enumerated()), id: \.offset) { _, m in
                    HStack(alignment: .top, spacing: 6) {
                        Pill(text: m.kind == "severe" ? "중증" : "응급실", bg: m.matched == true ? AD.redSoft : AD.chip, fg: m.matched == true ? AD.red : AD.ink3)
                        Text(m.message ?? "").font(.system(size: 12)).foregroundStyle(m.matched == true ? AD.ink : AD.ink3)
                    }
                }
            }.card(16)
        }
    }

    private func reason(_ k: String, _ v: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(k).font(.system(size: 12)).foregroundStyle(AD.sub).frame(width: 92, alignment: .leading)
            Text(v).font(.system(size: 13)).foregroundStyle(AD.ink)
            Spacer(minLength: 0)
        }
    }
}
