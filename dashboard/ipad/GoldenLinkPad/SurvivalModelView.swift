import Charts
import SwiftUI

/// 정보 생존 모델 — 상단바 버튼으로 여는 전체 화면. "병원이 보낸 병상 숫자가 아직 유효한가"를 실제 E-Gen 다음 폴링으로 채점한
/// 라이브 보드(hub /verification/live)와, 지금 이 구급차 사건의 후보 병원들에 그 모델이 매긴 확률을 한 화면에.
struct SurvivalModelScreen: View {
    @EnvironmentObject private var model: AppModel
    @Binding var isPresented: Bool

    var body: some View {
        ZStack {
            AD.bg.ignoresSafeArea()
            VStack(spacing: 10) {
                HStack(spacing: 12) {
                    (Text("골든").foregroundStyle(AD.navy) + Text("링크").foregroundStyle(AD.blue)).font(.system(size: 20, weight: .black))
                    Text("정보 생존 모델").font(.system(size: 18, weight: .bold)).foregroundStyle(AD.navy)
                    Text("병원이 보낸 병상 숫자가 구급차가 도착할 때까지 유효할 확률").font(.system(size: 13)).foregroundStyle(AD.ink3)
                    Spacer()
                    if let b = model.liveBoard {
                        Text("\(b.modelTag ?? "") · θ=\(b.theta ?? 3)석 · 창 \(b.windowHours ?? 48)h · 폴링 \(b.polls ?? 0)회 · 생성 \(Labels.clock(b.generatedAt))")
                            .font(.system(size: 11)).foregroundStyle(AD.muted)
                    }
                    Button { model.fetchLiveBoard() } label: {
                        Image(systemName: "arrow.clockwise").font(.system(size: 15, weight: .semibold)).foregroundStyle(AD.ink3)
                            .frame(width: 36, height: 36).background(AD.chip).clipShape(Circle())
                    }
                    Button { isPresented = false } label: {
                        Text("대시보드로").font(.system(size: 13, weight: .bold)).foregroundStyle(.white)
                            .padding(.horizontal, 16).frame(minHeight: 36).background(AD.blue).clipShape(Capsule())
                    }
                }
                .padding(.horizontal, 18).frame(minHeight: 54)
                .background(AD.card).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.line, lineWidth: 1))
                ScrollView { SurvivalModelBody() }
            }
            .padding(.horizontal, 16).padding(.vertical, 10)
        }
    }
}

struct SurvivalModelBody: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            currentCase
            intro
            if let b = model.liveBoard {
                headline(b)
                HStack(alignment: .top, spacing: 12) {
                    holdChart(b).frame(maxWidth: .infinity)
                    calibrationChart(b).frame(width: 380)
                }
                HStack(alignment: .top, spacing: 12) {
                    regions(b).frame(maxWidth: .infinity)
                    feed(b).frame(width: 460)
                }
            } else if model.liveBoardLoading {
                HStack(spacing: 10) { ProgressView(); Text("라이브 채점 보드를 받는 중 — 첫 생성은 수십 초 걸립니다(48시간 × 416곳 재생)").foregroundStyle(AD.ink3) }.card()
            } else {
                VStack(alignment: .leading, spacing: 6) {
                    Text(model.liveBoardError ?? "보드 없음").foregroundStyle(AD.red)
                    Text("hub가 info 거절 로그 수신구(5003)의 /verification/live를 중계합니다 — start-all.sh로 info까지 띄워야 합니다.").font(.system(size: 12)).foregroundStyle(AD.muted)
                    Button("다시 받기") { model.fetchLiveBoard() }
                }.card()
            }
        }
    }

    private var intro: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionTitle(text: "이 모델은 무엇을 하나", sub: "AI · XGBoost AFT 생존모델 · 순위에는 쓰지 않는 설명용")
            Text("E-Gen이 주는 병상 값은 병원이 스스로 신고한 것이고, 타임스탬프는 값이 맞다는 뜻이 아닙니다(5분마다 자동 재송출). 그래서 값이 생긴 뒤 '3석 이상 바뀌기까지'를 생존시간으로 보고, 병원별 갱신 리듬·정보 나이·시간대·규모로 그 확률을 학습했습니다(로그정규, 재보정). 아래는 실제 다음 폴링으로 채점한 결과이고, 병원 카드의 'AI 유효 %'가 바로 이 모델의 출력입니다.")
                .font(.system(size: 13)).foregroundStyle(AD.ink3)
        }.card()
    }

    private func headline(_ b: LiveBoard) -> some View {
        let h = b.headline
        return HStack(spacing: 12) {
            stat("그냥 믿을 때 유지율", b.overallPct.map { String(format: "%.1f%%", $0) } ?? "—", "창 안 모든 병원×폴링에서 값이 다음 폴링까지 3석 이상 안 바뀐 비율", AD.ink3)
            stat("엔진이 '80% 이상'이라 한 값", b.selectedPct.map { String(format: "%.1f%%", $0) } ?? "—", "모델 선별 유지율 — 그냥 믿을 때보다 높아야 쓸모가 있다", AD.blue)
            stat("엔진이 경고한 값(<50%)", b.warnedPct.map { String(format: "%.0f%%", $0) } ?? "—", "경고 구간의 실제 유지율 — 낮을수록 경고가 맞았다는 뜻", AD.red)
            stat("3석 이상 어긋남", "\(h?.bigBreaks ?? 0)건", "값 변화 \(h?.valueChanges ?? 0)건 중 · 깨지기 전 경고 \(h?.warnedBreaks ?? 0)건 · 고신뢰 실패 \(h?.missedBreaks ?? 0)건", AD.orange)
            regimeBadge(b.regime)
        }
    }

    private func stat(_ title: String, _ value: String, _ sub: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(title).font(.system(size: 12)).foregroundStyle(AD.sub)
            Text(value).font(.system(size: 28, weight: .black)).foregroundStyle(color)
            Text(sub).font(.system(size: 11)).foregroundStyle(AD.ink3).lineLimit(2)
        }.frame(maxWidth: .infinity, alignment: .leading).card(12)
    }

    private func regimeBadge(_ r: LiveBoard.Regime?) -> some View {
        let level = r?.current?.level ?? 0
        let (text, color): (String, Color) = level >= 2 ? ("급증", AD.red) : level == 1 ? ("주의", AD.orange) : ("평시", AD.green)
        return VStack(alignment: .leading, spacing: 3) {
            Text("공통 충격 감지").font(.system(size: 12)).foregroundStyle(AD.sub)
            HStack(spacing: 6) { Dot(color: color, size: 10); Text(text).font(.system(size: 24, weight: .black)).foregroundStyle(color) }
            Text("최근 폴링 어긋남 \(r?.current?.breaks ?? 0)건 (창 중앙값 \(Int(r?.medianBreaks ?? 0))) · 아침 병상 정리 같은 동시 변화는 감지로 대응").font(.system(size: 11)).foregroundStyle(AD.ink3).lineLimit(3)
        }.frame(width: 240, alignment: .leading).card(12)
    }

    private func holdChart(_ b: LiveBoard) -> some View {
        let pts = (b.timeseries ?? []).compactMap { p -> (Date, Double, Double?, Int)? in
            guard let d = p.date else { return nil }
            return (d, p.allPct, p.hiPct, p.surge ?? 0)
        }
        return VStack(alignment: .leading, spacing: 6) {
            SectionTitle(text: "신뢰 등급별 유지율 — 시간 흐름", sub: "폴링마다 · 파랑 엔진 선별(80%↑) · 회색 전체")
            Chart {
                ForEach(Array(pts.enumerated()), id: \.offset) { _, p in
                    if p.3 >= 2 { RectangleMark(x: .value("t", p.0), width: 3).foregroundStyle(AD.red.opacity(0.15)) }
                    LineMark(x: .value("시각", p.0), y: .value("전체", p.1), series: .value("계열", "전체")).foregroundStyle(AD.gray).lineStyle(StrokeStyle(lineWidth: 1, dash: [3, 3]))
                    if let hi = p.2 { LineMark(x: .value("시각", p.0), y: .value("선별", hi), series: .value("계열", "선별")).foregroundStyle(AD.blue).lineStyle(StrokeStyle(lineWidth: 2)) }
                }
            }
            .chartYScale(domain: 80...100)
            .chartYAxis { AxisMarks(position: .leading) { v in AxisGridLine().foregroundStyle(AD.line); AxisValueLabel { if let d = v.as(Double.self) { Text("\(Int(d))%").foregroundStyle(AD.muted) } } } }
            .chartXAxis { AxisMarks(values: .stride(by: .hour, count: 6)) { _ in AxisGridLine().foregroundStyle(AD.line); AxisValueLabel(format: .dateTime.hour(), centered: false).foregroundStyle(AD.muted) } }
            .frame(height: 220)
            Text("붉은 띠 = 공통 충격(그 폴링의 어긋남이 창 중앙값의 3배 이상). 세로축은 80~100%만 보인다.").font(.system(size: 11)).foregroundStyle(AD.muted)
        }.card()
    }

    private func calibrationChart(_ b: LiveBoard) -> some View {
        let bins = (b.calibration?.bins ?? []).filter { ($0.total ?? 0) > 0 }
        return VStack(alignment: .leading, spacing: 6) {
            SectionTitle(text: "예측 vs 실제", sub: "확률 구간별 실제 유지율")
            Chart {
                ForEach(bins) { bin in
                    BarMark(x: .value("구간", bin.range), y: .value("예측", bin.predictedPct ?? 0)).foregroundStyle(AD.gray).position(by: .value("계열", "예측"))
                    BarMark(x: .value("구간", bin.range), y: .value("실제", bin.actualPct ?? 0)).foregroundStyle(AD.blue).position(by: .value("계열", "실제"))
                }
            }
            .chartYScale(domain: 0...100)
            .chartYAxis { AxisMarks(position: .leading) { v in AxisGridLine().foregroundStyle(AD.line); AxisValueLabel { if let d = v.as(Double.self) { Text("\(Int(d))%").foregroundStyle(AD.muted) } } } }
            .chartXAxis { AxisMarks { _ in AxisValueLabel().foregroundStyle(AD.ink3) } }
            .frame(height: 180)
            ForEach(bins) { bin in
                Text("\(bin.range): 예측 \(String(format: "%.0f", bin.predictedPct ?? 0))% → 실제 \(String(format: "%.1f", bin.actualPct ?? 0))% (\(bin.total ?? 0)건)").font(.system(size: 11)).foregroundStyle(AD.ink3)
            }
            Text("회색 예측 ≤ 파랑 실제면 모델이 보수적(과소확신). 구간 순서가 맞는 것이 핵심이다.").font(.system(size: 11)).foregroundStyle(AD.muted)
        }.card()
    }

    private func regions(_ b: LiveBoard) -> some View {
        let rs = (b.regions ?? []).sorted { ($0.allPct ?? 0) < ($1.allPct ?? 0) }
        return VStack(alignment: .leading, spacing: 6) {
            SectionTitle(text: "지역별 — 원값 유지율 → 엔진 선별", sub: "원값이 나쁜 지역일수록 선별 이득이 크다")
            LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 8), count: 3), spacing: 6) {
                ForEach(rs) { r in
                    HStack(spacing: 6) {
                        Text(r.label).font(.system(size: 12, weight: .bold)).foregroundStyle(AD.navy).frame(width: 36, alignment: .leading)
                        Text(String(format: "%.1f", r.allPct ?? 0)).font(.system(size: 12, design: .monospaced)).foregroundStyle(AD.muted)
                        Text("→").font(.system(size: 10)).foregroundStyle(AD.muted)
                        Text(String(format: "%.1f%%", r.hiPct ?? 0)).font(.system(size: 12, weight: .bold, design: .monospaced)).foregroundStyle(AD.blue)
                        Spacer()
                        Text("\(r.hospitals ?? 0)곳").font(.system(size: 10)).foregroundStyle(AD.muted)
                    }
                    .padding(.horizontal, 10).padding(.vertical, 6).background(AD.chip).clipShape(RoundedRectangle(cornerRadius: 10))
                }
            }
        }.card()
    }

    private func feed(_ b: LiveBoard) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionTitle(text: "판명 — 값이 바뀐 순간과 그때 모델 확률", sub: "최근 12건")
            ForEach((b.feed ?? []).prefix(12)) { f in
                HStack(spacing: 8) {
                    Text(Labels.clock(f.ts)).font(.system(size: 10, design: .monospaced)).foregroundStyle(AD.muted).frame(width: 56, alignment: .leading)
                    Text(f.name).font(.system(size: 11.5)).foregroundStyle(AD.ink).lineLimit(1)
                    Spacer()
                    Text("\(f.claimValue ?? 0) → \(f.newValue ?? 0)\(f.becameFull == true ? " 만실" : "")").font(.system(size: 11, design: .monospaced)).foregroundStyle(f.becameFull == true ? AD.red : AD.ink3)
                    Text("\(Labels.minutes((f.ageMin ?? 0) * 60)) 된 값 · 모델 \(Int(((f.pValid ?? 0) * 100).rounded()))%")
                        .font(.system(size: 11, weight: .medium)).foregroundStyle(Theme.validity(f.pValid ?? 0).fg)
                }
            }
            if let limits = b.limits, !limits.isEmpty {
                Divider().overlay(AD.line)
                ForEach(limits, id: \.self) { l in Text("· " + l).font(.system(size: 10.5)).foregroundStyle(AD.muted) }
            }
        }.card()
    }

    /// 지금 이 구급차 사건의 후보 병원들에 이 모델이 매긴 확률(초 단위 감쇠)과 한 줄 이유 — 모델이 사건에 어떻게 쓰이는지
    @ViewBuilder private var currentCase: some View {
        if let r = model.result, !r.hospitals.isEmpty {
            VStack(alignment: .leading, spacing: 8) {
                SectionTitle(text: "지금 이 환자의 후보 병원 — 병상 정보 유효 확률", sub: "지금 → 도착 시 · 초 단위 감쇠")
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 10), count: 3), spacing: 10) {
                    ForEach(r.hospitals.prefix(9)) { h in
                        VStack(alignment: .leading, spacing: 5) {
                            HStack {
                                Text(h.name).font(.system(size: 13, weight: .bold)).foregroundStyle(AD.navy).lineLimit(1)
                                Spacer()
                                let p = Theme.statusPill(h.status)
                                Pill(text: Labels.status(h.status), bg: p.bg, fg: p.fg, bold: true)
                            }
                            if let br = h.bedReliability {
                                let lv = BedReliability.live(br, now: model.now)
                                HStack(alignment: .firstTextBaseline, spacing: 6) {
                                    Text(BedReliability.pct(lv.authority)).font(.system(size: 24, weight: .black)).foregroundStyle(Theme.validity(lv.authority).fg)
                                    Text("→ 도착 시 \(BedReliability.pct(lv.rArrive))").font(.system(size: 13, weight: .bold)).foregroundStyle(Theme.validity(lv.rArrive).fg)
                                }
                                ProbBar(value: lv.rArrive)
                                Text("응급실 \(h.bedCountUnknown == true ? "미상" : "\(h.availableBedCount ?? 0)석")\(lv.ageSec.map { " · 정보 \(Labels.age($0))" } ?? "") · 이동 \(Labels.minutes(br.horizonSec))\(br.confirmedAgeSec != nil ? " · 병원 확인 ✓" : "")\(h.bedDataStale == true ? " · ⚠ 1일 넘은 값" : "")")
                                    .font(.system(size: 11)).foregroundStyle(AD.sub).lineLimit(2)
                            } else {
                                Text(h.bedCountUnknown == true ? "병상 미상 — 확률 없음" : "모델 값 없음").font(.system(size: 12)).foregroundStyle(AD.muted)
                            }
                        }
                        .padding(12).background(AD.bg).clipShape(RoundedRectangle(cornerRadius: 14))
                        .overlay(RoundedRectangle(cornerRadius: 14).stroke(h.status == "confirmed" ? AD.green : AD.line, lineWidth: h.status == "confirmed" ? 2 : 1))
                    }
                }
            }.card()
        }
    }
}
