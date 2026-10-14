import SwiftUI

/// 오른쪽 단 — 2. 병원 수용 여부·병원 상태 + 4-1. 그 병원 정보가 얼마나 유효한가(정보 생존 모델)와 왜 그런가.
/// 순서는 hub가 보낸 순위 그대로(이송 확정 → 승인 → 점수순 → 내림 → 거절).
struct HospitalColumn: View {
    @EnvironmentObject private var model: AppModel
    @State private var detail: CaseHospital?

    var body: some View {
        VStack(spacing: 8) {
            if let c = model.selectedCase {
                let cnt = c.counts
                SectionTitle(text: "병원 수용 여부 · 정보 유효성",
                             sub: c.matched ? "대기 \(cnt.pending) · 승인 \(cnt.approved) · 불가 \(cnt.rejected)\(cnt.confirmed > 0 ? " · 확정" : "")" : "병원 요청 전")
                legend
                if c.hospitals.isEmpty {
                    Spacer()
                    Text(c.matched ? "후보 병원이 없습니다" : "현장 통화가 끝나면 존 안 병원에 동시 요청이 나갑니다").foregroundStyle(Theme.muted).font(.system(size: 12))
                    Spacer()
                } else {
                    ScrollView {
                        VStack(spacing: 6) {
                            ForEach(Array(c.hospitals.enumerated()), id: \.element.hospitalId) { i, h in
                                HospitalRow(rank: i + 1, h: h, now: model.now)
                                    .onTapGesture { detail = h }
                            }
                        }
                    }
                }
            } else {
                SectionTitle(text: "병원 수용 여부 · 정보 유효성")
                Spacer()
                Text("사건을 고르면 후보 병원이 여기에 뜹니다").foregroundStyle(Theme.muted).font(.system(size: 12))
                Spacer()
            }
        }
        .panel(10)
        .sheet(item: $detail) { h in
            ValidityDetailView(h: h, caseState: model.selectedCase).environmentObject(model)
        }
    }

    private var legend: some View {
        HStack(spacing: 10) {
            ForEach([("판단 대기", Theme.amber), ("수용 승인", Theme.ok), ("수용 불가", Theme.muted), ("이송 확정", Theme.ktas(2))], id: \.0) { item in
                HStack(spacing: 4) { Circle().fill(item.1).frame(width: 7, height: 7); Text(item.0) }
            }
            Spacer()
            Text("유효 % = 병상 숫자가 아직 맞을 확률(AI)").foregroundStyle(Theme.muted)
        }.font(.system(size: 10)).foregroundStyle(Theme.ink2)
    }
}

struct HospitalRow: View {
    var rank: Int
    var h: CaseHospital
    var now: Date

    private var live: BedReliability.Live? { h.bedReliability.map { BedReliability.live($0, now: now) } }
    private var unavailable: Bool { h.status == "pending" && h.unavailableReason != nil }

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Text("\(rank)").font(.system(size: 11, design: .monospaced)).foregroundStyle(Theme.muted).frame(width: 18)
                Text(h.name).font(.system(size: 13, weight: .semibold)).foregroundStyle(h.excluded == true ? Theme.muted : Theme.ink).lineLimit(1)
                if let g = h.emergencyLevel { Chip(text: Labels.grade(g), color: Theme.grade(g)) }
                Spacer()
                statusChip
            }
            HStack(spacing: 8) {
                Text(bedsText).foregroundStyle(h.bedDataStale == true ? Theme.clash : Theme.ink2)
                if let t = h.travelMin { Text("이동 \(String(format: "%.0f", t))분\(h.travelBasis == "estimate" ? "(직선)" : "")") }
                if let s = h.finalScore { Text("순위 \(String(format: "%.2f", s))") }
                if let n = h.inFlightCount, n > 0 { Text("이송 중 \(n)건").foregroundStyle(Theme.amber) }
                Spacer()
            }.font(.system(size: 11)).foregroundStyle(Theme.ink2)
            // 4-1 정보 유효성 — 지금 / 도착 시
            if let lv = live {
                HStack(spacing: 8) {
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 6) {
                            Text("정보 유효").font(.system(size: 10)).foregroundStyle(Theme.muted)
                            Text("지금 \(BedReliability.pct(lv.authority))").font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.validity(lv.authority))
                            Text("· 도착 시 \(BedReliability.pct(lv.rArrive))").font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.validity(lv.rArrive))
                            if h.bedReliability?.confirmedAgeSec != nil { Text("✓ 병원 확인").font(.system(size: 10)).foregroundStyle(Theme.ok) }
                            if let a = lv.ageSec { Text("· 정보 \(Labels.age(a))").font(.system(size: 10)).foregroundStyle(Theme.muted) }
                        }
                        ProbBar(value: lv.rArrive)
                    }
                }
            } else {
                Text(h.bedCountUnknown == true ? "정보 유효: 병상 미상 — 확률 없음" : "정보 유효: 모델 값 없음").font(.system(size: 10)).foregroundStyle(Theme.muted)
            }
            HStack(spacing: 6) {
                if h.bedDataStale == true { Chip(text: "1일 넘은 값", color: Theme.clash) }
                if let sf = h.severeFreshness { Chip(text: "\(sf.value == "Y" ? "수용가능 신고" : "수용불가 신고") \(Labels.age(sf.ageSec, isMin: sf.ageIsMin ?? false))", color: sf.value == "Y" ? Theme.ok : Theme.clash) }
                if let r = h.reliability { Chip(text: "\(r.group) · 신뢰 \(Labels.confidence(r.confidence))", color: r.confidence == "high" ? Theme.ok : Theme.ink2) }
                ForEach(h.demoteReasons ?? [], id: \.self) { d in Chip(text: Labels.demote(d), color: Theme.clash) }
                Spacer()
                Image(systemName: "chevron.right").font(.system(size: 10)).foregroundStyle(Theme.muted)
            }
        }
        .padding(8)
        .background(h.status == "confirmed" ? Theme.panel2 : Theme.bg.opacity(0.5))
        .overlay(RoundedRectangle(cornerRadius: 5).stroke(h.status == "confirmed" ? Theme.ktas(2).opacity(0.7) : Theme.line, lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 5))
        .opacity(h.excluded == true ? 0.55 : 1)
        .contentShape(Rectangle())
    }

    private var statusChip: some View {
        Group {
            if unavailable {
                Chip(text: "수용 불가 · \(Labels.reject(h.unavailableReason))", color: Theme.muted, filled: true)
            } else if h.status == "rejected" {
                Chip(text: "수용 불가 · \(Labels.reject(h.rejectReason))", color: Theme.muted, filled: true)
            } else {
                Chip(text: Labels.status(h.status), color: Theme.status(h.status), filled: h.status != "pending")
            }
        }
    }

    private var bedsText: String {
        if h.bedCountUnknown == true { return "응급실 미상" }
        guard let n = h.availableBedCount else { return "응급실 —" }
        if let cap = h.erBedCapacity { return "응급실 \(n)/\(cap)\(h.erOccupancyPct.map { " · 포화 \($0)%" } ?? "")" }
        return "응급실 \(n)"
    }
}

/// 4-1 상세 — 이 병원 정보가 얼마나 유효한가와 그 이유(정보 생존 모델·신고 신선도·심평원 대조·순위 근거·E-Gen 메시지)
struct ValidityDetailView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.dismiss) private var dismiss
    var h: CaseHospital
    var caseState: AppModel.CaseState?

    var body: some View {
        NavigationStack {
            ZStack {
                Theme.bg.ignoresSafeArea()
                ScrollView {
                    VStack(alignment: .leading, spacing: 12) {
                        header
                        survivalSection
                        declarationSection
                        rankSection
                        messagesSection
                    }.padding(16)
                }
            }
            .navigationTitle(h.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("닫기") { dismiss() } } }
        }
        .presentationDetents([.large])
    }

    private var live: BedReliability.Live? { h.bedReliability.map { BedReliability.live($0, now: model.now) } }

    private var header: some View {
        HStack(spacing: 8) {
            if let g = h.emergencyLevel { Chip(text: g, color: Theme.grade(g)) }
            Chip(text: Labels.status(h.status), color: Theme.status(h.status), filled: true)
            if let r = h.rejectReason ?? h.unavailableReason { Chip(text: Labels.reject(r), color: Theme.muted) }
            if h.excluded == true { Chip(text: "이 사건에서 제외", color: Theme.clash) }
            Spacer()
            Text("직선 \(String(format: "%.1f", h.distanceKm)) km\(h.roadDistanceKm.map { " · 도로 \(String(format: "%.1f", $0)) km" } ?? "") · 존 \(h.zone)")
                .font(.system(size: 12)).foregroundStyle(Theme.ink2)
        }
    }

    /// 3·4-1 정보 생존 모델 — 병상 숫자가 아직 유효할 확률과 그 근거
    private var survivalSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "정보 생존 모델 — 응급실 병상 숫자가 아직 맞을 확률", sub: "AI · XGBoost AFT 생존모델")
            if let br = h.bedReliability, let lv = live {
                HStack(spacing: 24) {
                    bigStat("지금", lv.authority)
                    bigStat("도착 시 (\(Labels.minutes(br.horizonSec)) 뒤)", lv.rArrive)
                    VStack(alignment: .leading, spacing: 4) {
                        ProbBar(value: lv.rArrive, height: 10)
                        Text(lv.live ? "초 단위로 감쇠 중 — 같은 곡선을 앱이 로컬로 계산" : "매칭 시점 값(곡선 파라미터 없음)").font(.system(size: 10)).foregroundStyle(Theme.muted)
                    }
                }
                Divider().overlay(Theme.line)
                VStack(alignment: .leading, spacing: 5) {
                    Text("왜 이 확률인가").font(.system(size: 12, weight: .semibold)).foregroundStyle(Theme.ink)
                    if let a = lv.ageSec {
                        reason("정보 나이", "이 병상 값이 생긴 지 \(Labels.age(a)) (\(Labels.minutes(a))). 값은 환자가 드나들 때마다 바뀌고, 시간이 갈수록 그대로일 확률이 내려갑니다.")
                    }
                    if let m = br.predictedSurvivalSec {
                        reason("모델 예측 수명", "이 병원·이 시각·이 값이 \(Labels.minutes(m)) 안에 \(model.liveBoard?.theta ?? 3)석 이상 바뀔 확률이 반반(중앙값). 병원별 갱신 리듬·시간대·규모·정원 대비 비율로 학습한 값입니다.")
                    }
                    reason("도착까지", "이동 \(Labels.minutes(br.horizonSec)) — 순위에 쓴 이동시간(카카오 내비 ETA, 없으면 보정 추정)과 같은 값. 그만큼 더 지난 뒤의 확률이 '도착 시'입니다.")
                    if br.confirmedAgeSec != nil {
                        reason("병원 확인 ✓", "병원 대시보드가 '현재 정보가 맞습니다'를 눌렀습니다 — 확인 시점 기준 조건부 생존 S(a)/S(u)로 되올린 값입니다.")
                    }
                    if h.bedDataStale == true {
                        reason("⚠ 1일 넘은 값", "마지막 갱신이 하루를 넘었거나 실시간 피드에 없는 병원 — 만실·확률 판단에 쓰지 않습니다(미상과 같은 취급).")
                    }
                    reason("모델", "\(br.modelTag ?? "infosurv") · 전국 E-Gen 스냅샷으로 학습·재보정, 순위(finalScore)에는 쓰지 않는 설명용 확률")
                }
            } else {
                Text(h.bedCountUnknown == true ? "병상 수가 미상이라 확률을 내지 않습니다 — 미상을 만실처럼 다루지 않는 원칙(뺑뺑이 방지)." : "이 병원에는 모델 값이 없습니다(구 데이터 또는 피드 없음).")
                    .font(.system(size: 12)).foregroundStyle(Theme.ink2)
            }
        }.panel()
    }

    private func bigStat(_ label: String, _ p: Double) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label).font(.system(size: 11)).foregroundStyle(Theme.muted)
            Text(BedReliability.pct(p)).font(.system(size: 30, weight: .bold)).foregroundStyle(Theme.validity(p))
        }
    }

    /// 중증질환 신고 신선도(규칙) + 심평원 대조 신뢰도
    private var declarationSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "병원 신고의 유효성", sub: "중증질환 수용 신고 · 심평원 대조")
            if let sf = h.severeFreshness {
                reason("\(sf.group) 신고", "\(sf.value == "Y" ? "수용 가능" : "수용 불가") — \(Labels.age(sf.ageSec, isMin: sf.ageIsMin ?? false)) 신고\(sf.ageIsMin == true ? "(수집 시작 전부터라 실제론 더 오래됨)" : "")\(sf.ruleRemainingSec.map { $0 > 0 ? " · 통상 9시간 만료 규칙까지 \(Labels.minutes($0))" : " · 9시간 규칙 만료 뒤에도 유지 중(병원이 갱신 지속)" } ?? "")")
            }
            if let r = h.reliability {
                reason("\(r.group) 심평원 대조", "신뢰 \(Labels.confidence(r.confidence)) · 점수 \(String(format: "%.1f", r.score)) (불가능 0.2 < 근거 없는 미상 0.4 < 전문의 있는 미상 0.6 < 전문병원 지정 미상 0.8 < 가능 신고 1.0)")
                ForEach(r.basis ?? [], id: \.self) { b in
                    HStack(alignment: .top, spacing: 6) { Text("·").foregroundStyle(Theme.muted); Text(b).font(.system(size: 12)).foregroundStyle(Theme.ink2) }.padding(.leading, 8)
                }
            }
            if h.severeFreshness == nil && h.reliability == nil {
                Text("이 사건의 질환군에 해당하는 신고가 없거나(일반 질환) 판정 데이터가 없습니다.").font(.system(size: 12)).foregroundStyle(Theme.ink2)
            }
            Text("둘은 다른 축입니다 — 신선도는 '언제 적 신고인가'(규칙), 심평원 대조는 '그 신고를 믿을 만한가'(전문의·전문병원 지정 근거). 순위에는 수용 불가 신고만 순서로 반영합니다.")
                .font(.system(size: 10)).foregroundStyle(Theme.muted)
        }.panel()
    }

    private var rankSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionTitle(text: "왜 이 순위인가", sub: "규칙 기반 · 0.6×진료과 + 0.4×이동시간")
            if let s = h.finalScore { reason("순위 점수", String(format: "%.3f", s)) }
            if let sm = h.specialtyMatch {
                reason("진료과", "\(sm.department ?? "—") · \(sm.basis == "exact" ? "필요 진료과 정확 일치 1.0" : sm.basis == "embedding" ? "임베딩 적합도 \(Int(((sm.score ?? 0) * 100).rounded()))%" : "진료과 정보 없음")\(sm.doctorCount.map { " · 전문의 \($0)명" } ?? "")")
            }
            if let t = h.travelMin { reason("이동시간", "\(String(format: "%.1f", t))분 (\(h.travelBasis == "eta" ? "카카오 내비 ETA" : "직선거리 보정 추정"))\(h.etaMin.map { " · ETA \($0)분" } ?? "")") }
            ForEach(h.bonusReasons ?? [], id: \.self) { b in reason("가산", b) }
            if let l = h.loadReason { reason("부하", l) }
            if let o = h.occupancyReason { reason("포화도", o) }
            ForEach(h.demoteReasons ?? [], id: \.self) { d in reason("뒤로 내림", Labels.demote(d)) }
            if let at = h.respondedAt { reason("응답 시각", Labels.clock(at)) }
        }.panel()
    }

    private var messagesSection: some View {
        Group {
            if let msgs = h.acceptanceMessages, !msgs.isEmpty {
                VStack(alignment: .leading, spacing: 6) {
                    SectionTitle(text: "병원 공지(E-Gen 메시지)", sub: "병원이 직접 건 수용 제한")
                    ForEach(Array(msgs.enumerated()), id: \.offset) { _, m in
                        HStack(alignment: .top, spacing: 6) {
                            Chip(text: m.kind == "severe" ? "중증" : "응급실", color: m.matched == true ? Theme.clash : Theme.muted)
                            Text(m.message ?? "").font(.system(size: 12)).foregroundStyle(m.matched == true ? Theme.ink : Theme.ink2)
                        }
                    }
                }.panel()
            }
        }
    }

    private func reason(_ k: String, _ v: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(k).font(.system(size: 11)).foregroundStyle(Theme.muted).frame(width: 90, alignment: .leading)
            Text(v).font(.system(size: 12)).foregroundStyle(Theme.ink)
            Spacer(minLength: 0)
        }
    }
}
