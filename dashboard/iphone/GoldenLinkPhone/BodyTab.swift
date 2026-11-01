import GoldenLinkCore
import SwiftUI

// 외상 등록 페이지 — 아이패드 BodyInjuryCard를 폰 한 열로 옮겼다(안드로이드 BodyTab.kt와 같다). 사람 그림에서 부위를 탭으로만 고른다
// (드래그는 가로 페이지 넘김과 부딪친다). 부위는 통화 요약의 글자에서 낱말 규칙으로 찾고(AI 아님), 색은 위험도 규칙(전문의 검토 전 초안)이다.
// 순위·병원 선택에는 쓰지 않는다.

private func tierColor(_ t: InjuryTier) -> Color { switch t { case .high: AD.red; case .medium: AD.orange; case .low: AD.lime } }
private func tierSoft(_ t: InjuryTier) -> Color { switch t { case .high: AD.redSoft; case .medium: AD.orangeSoft; case .low: AD.limeSoft } }

/// 통화 요약 + 구급대원이 고친 것으로 그린 그림의 재료
private struct BodyView {
    let located: [MappedInjury]
    let unlocated: [MappedInjury]
    let callMarks: Set<BodyMark>
    let vital: InjuryRisk.VitalTier
    let tiers: [BodyMark: InjuryTier]
    let generalTier: InjuryTier
    let showsGeneral: Bool
    let numbered: [(Int, BodyMark)]

    init(_ p: PatientInfo, _ e: BodyEdits) {
        let injuries = InjuryMapper.parse(p)
        let specific = injuries.filter { !$0.marks.isEmpty && !$0.isMulti }
        located = specific.isEmpty ? injuries.filter { !$0.marks.isEmpty } : specific
        unlocated = injuries.filter { $0.marks.isEmpty || ($0.isMulti && !specific.isEmpty) }
        callMarks = Set(located.flatMap(\.marks))
        vital = InjuryRisk.vitalTier(p)

        var t: [BodyMark: InjuryTier] = [:]
        for injury in located { for mark in injury.marks where !e.removed.contains(mark) {
            t[mark] = max(t[mark] ?? .low, InjuryRisk.tier(injury.text, mark.region))
        } }
        for mark in e.added {
            let text = (["외상"] + (e.cares[mark] ?? [])).joined(separator: " ")
            t[mark] = max(t[mark] ?? .low, InjuryRisk.tier(text, mark.region))
        }
        tiers = t
        generalTier = max(unlocated.map { InjuryRisk.tier($0.text, nil) }.max() ?? .low, vital.tier)
        showsGeneral = !unlocated.isEmpty || vital.reason != nil
        numbered = tiers.keys.sorted { a, b in a.region.rawValue != b.region.rawValue ? a.region.rawValue < b.region.rawValue : a.side.label < b.side.label }
            .enumerated().map { ($0.offset + 1, $0.element) }
    }

    func text(_ mark: BodyMark, _ e: BodyEdits) -> String {
        var texts = located.filter { $0.marks.contains(mark) }.map(\.text)
        if texts.isEmpty { texts = ["외상(구급대원 확인)"] }
        texts += (e.cares[mark] ?? []).map { "처치 \($0)" }
        return texts.joined(separator: " · ")
    }
}

struct BodyPage: View {
    @Environment(PhoneModel.self) private var m
    let p: PatientInfo
    @State private var back = false
    @State private var tapped: BodyMark?

    var body: some View {
        let v = BodyView(p, m.bodyEdits)
        VStack(spacing: 10) {
            Card {
                VStack(alignment: .leading, spacing: 8) {
                    HStack(spacing: 6) {
                        Text("외상 부위").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                        Spacer()
                        if let k = p.ktasLevel { Pill(text: "KTAS \(k)", fg: ktasColor(k), bg: ktasSoft(k), bold: true) }
                        if !v.tiers.isEmpty { Pill(text: "\(v.tiers.count)곳", fg: AD.red, bg: AD.redSoft, bold: true) }
                        faceSwitch(v)
                    }
                    HStack(alignment: .top, spacing: 10) {
                        Figure(v: v, back: back) { tapped = $0 }.frame(width: 140)
                        VStack(alignment: .leading, spacing: 6) {
                            let shown = v.numbered.filter { BodyGeometry.visible($0.1.region, back: back) }
                            ForEach(Array(shown.enumerated()), id: \.offset) { _, item in
                                CalloutBox(n: item.0, mark: item.1, tier: v.tiers[item.1] ?? .low, text: v.text(item.1, m.bodyEdits))
                            }
                            if shown.isEmpty, v.unlocated.isEmpty {
                                Text(back ? "뒷모습에 표시된 부위가 없습니다" : "통화 요약에 외상 항목이 없습니다").font(.system(size: 12)).foregroundStyle(AD.muted)
                            }
                            if !back, v.showsGeneral { GeneralBox(v: v) }
                        }
                    }
                    HStack(spacing: 8) {
                        ForEach([InjuryTier.high, .medium, .low], id: \.rawValue) { t in
                            Circle().fill(tierColor(t)).frame(width: 7, height: 7)
                            Text(t.label).font(.system(size: 10.5, weight: .semibold)).foregroundStyle(AD.ink3)
                        }
                    }
                }
            }
            SendBar()
        }
        .sheet(item: $tapped) { mark in BodyEditSheet(mark: mark, v: v) }
    }

    @ViewBuilder private func faceSwitch(_ v: BodyView) -> some View {
        HStack(spacing: 2) {
            ForEach([false, true], id: \.self) { value in
                let on = back == value
                let hidden = v.tiers.keys.filter { BodyGeometry.visible($0.region, back: value) && !BodyGeometry.visible($0.region, back: !value) }.count
                HStack(spacing: 4) {
                    Text(value ? "뒤" : "앞").font(.system(size: 12, weight: on ? .bold : .medium)).foregroundStyle(on ? AD.navy : AD.ink3)
                    if !on, hidden > 0 {
                        Text("\(hidden)").font(.system(size: 10, weight: .bold)).foregroundStyle(.white)
                            .padding(.horizontal, 5).background(AD.red, in: Capsule())
                    }
                }
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(on ? Color.white : Color.clear, in: Capsule())
                .onTapGesture { back = value; tapped = nil }
            }
        }
        .padding(2)
        .background(AD.chip, in: Capsule())
    }
}

extension BodyMark: Identifiable { public var id: String { "\(region.rawValue)-\(side)" } }

/// 사람 모양 — 실루엣을 통째로 그리고 다친 부위만 그 영역으로 오려 위험도 색으로 덧칠한다. 부위는 탭으로 고른다
private struct Figure: View {
    let v: BodyView
    let back: Bool
    let onTap: (BodyMark) -> Void

    var body: some View {
        let height: CGFloat = 330
        let width = height * BodyShapeData.ratio
        Canvas { context, size in
            let w = size.width, h = size.height
            let body = path(BodyGeometry.outline, w: w, h: h)
            context.drawLayer { ctx in
                if back { ctx.transform = CGAffineTransform(scaleX: -1, y: 1).concatenating(CGAffineTransform(translationX: w, y: 0)) }
                ctx.fill(body, with: .color(AD.navy))
                for (_, mark) in v.numbered where BodyGeometry.visible(mark.region, back: back) {
                    var clipped = ctx
                    clipped.clip(to: path(BodyGeometry.region(mark, back: back), w: w, h: h))
                    clipped.fill(body, with: .color(tierColor(v.tiers[mark] ?? .low)))
                }
                var lineCtx = ctx
                lineCtx.clip(to: body)
                for (a, b) in BodyGeometry.dividers(back: back) {
                    var p = Path(); p.move(to: pt(a, w, h)); p.addLine(to: pt(b, w, h))
                    lineCtx.stroke(p, with: .color(.white.opacity(0.22)), style: StrokeStyle(lineWidth: 2, dash: [6, 6]))
                }
            }
            // 번호 동그라미는 뒤집지 않고 자리만 뒤집는다(글자가 거울상이 되지 않게)
            for (n, mark) in v.numbered where BodyGeometry.visible(mark.region, back: back) {
                let a = BodyGeometry.anchor(mark, back: back)
                let c = pt(a, w, h)
                let color = tierColor(v.tiers[mark] ?? .low)
                context.fill(Path(ellipseIn: CGRect(x: c.x - 9, y: c.y - 9, width: 18, height: 18)), with: .color(color))
                context.stroke(Path(ellipseIn: CGRect(x: c.x - 9, y: c.y - 9, width: 18, height: 18)), with: .color(.white), lineWidth: 1.5)
                context.draw(Text("\(n)").font(.system(size: 11, weight: .heavy)).foregroundStyle(.white), at: c)
            }
        }
        .frame(width: width, height: height)
        .contentShape(Rectangle())
        .onTapGesture { location in
            let p = Pt(location.x / width, location.y / height)
            if let mark = BodyGeometry.hit(p, back: back) { onTap(mark) }
        }
    }

    private func pt(_ p: Pt, _ w: CGFloat, _ h: CGFloat) -> CGPoint { CGPoint(x: p.x * w, y: p.y * h) }
    private func path(_ pts: [Pt], w: CGFloat, h: CGFloat) -> Path {
        var path = Path()
        for (i, q) in pts.enumerated() { let c = pt(q, w, h); if i == 0 { path.move(to: c) } else { path.addLine(to: c) } }
        if !pts.isEmpty { path.closeSubpath() }
        return path
    }
}

private struct CalloutBox: View {
    let n: Int; let mark: BodyMark; let tier: InjuryTier; let text: String
    var body: some View {
        HStack(alignment: .top, spacing: 6) {
            Text("\(n)").font(.system(size: 11, weight: .heavy)).foregroundStyle(.white)
                .frame(width: 20, height: 20).background(tierColor(tier), in: Circle())
            VStack(alignment: .leading, spacing: 1) {
                HStack(spacing: 5) {
                    Text(mark.label).font(.system(size: 12.5, weight: .bold)).foregroundStyle(tierColor(tier))
                    Pill(text: tier.label, fg: tierColor(tier), bg: tierSoft(tier))
                }
                Text(text).font(.system(size: 12)).foregroundStyle(AD.ink)
            }
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.white, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 10, style: .continuous).strokeBorder(tierSoft(tier), lineWidth: 1.5))
    }
}

private struct GeneralBox: View {
    let v: BodyView
    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 5) {
                Text("부위 미상 · 전신 증상").font(.system(size: 11.5, weight: .semibold)).foregroundStyle(AD.muted)
                if v.generalTier > .low { Pill(text: v.generalTier.label, fg: tierColor(v.generalTier), bg: tierSoft(v.generalTier)) }
            }
            if !v.unlocated.isEmpty { Text(v.unlocated.map(\.text).joined(separator: " · ")).font(.system(size: 12)).foregroundStyle(AD.ink3) }
            if let reason = v.vital.reason { Text(reason).font(.system(size: 11.5, weight: .semibold)).foregroundStyle(tierColor(v.vital.tier)) }
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(AD.chip, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
    }
}

/// 적은 것을 한 번에 보내는 줄 — 고친 게 없으면 아예 안 보인다
private struct SendBar: View {
    @Environment(PhoneModel.self) private var m
    var body: some View {
        let e = m.bodyEdits
        if !(e.isEmpty && e.signature == m.bodySentSignature) {
            let sent = e.signature == m.bodySentSignature
            HStack(spacing: 8) {
                Pill(text: sent ? "병원에 전달함" : "전달 전", fg: sent ? AD.green : AD.orange, bg: sent ? AD.greenSoft : AD.orangeSoft, bold: true)
                Text("부위 \(e.markCount)곳 · 처치 \(e.careLines.count)건").font(.system(size: 11.5)).foregroundStyle(sent ? AD.muted : AD.ink3)
                Spacer()
                if !sent {
                    Button { m.sendBodyEdits() } label: {
                        HStack(spacing: 6) { Image(systemName: "paperplane.fill"); Text("병원에 전달") }
                            .font(.system(size: 13, weight: .bold)).foregroundStyle(.white)
                            .padding(.horizontal, 14).frame(minHeight: 32)
                            .background(m.paused ? AD.gray : AD.blue, in: Capsule())
                    }.buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 10).padding(.vertical, 6)
            .background(AD.chip, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        }
    }
}

/// 부위 하나를 고치는 칸 — 외상 있음/없음과 그 부위에 한 처치. 여기서는 보내지 않고 [적용]으로 도해에만 반영한다
private struct BodyEditSheet: View {
    @Environment(PhoneModel.self) private var m
    @Environment(\.dismiss) private var dismiss
    let mark: BodyMark
    let v: BodyView
    @State private var on = false
    @State private var cares: [String] = []
    @State private var sharedBase: [String: String] = [:]

    var body: some View {
        let fromCall = v.callMarks.contains(mark)
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 8) {
                Text(mark.label).font(.system(size: 16, weight: .heavy)).foregroundStyle(AD.navy)
                if fromCall { Pill(text: "통화 요약", fg: AD.blue, bg: AD.blueSoft) }
                Spacer()
                Text("닫기").foregroundStyle(AD.ink3).font(.system(size: 13)).onTapGesture { dismiss() }
            }
            HStack(spacing: 6) {
                ForEach([true, false], id: \.self) { value in
                    let sel = on == value
                    Text(value ? "외상 있음" : "외상 없음").font(.system(size: 13, weight: .bold)).foregroundStyle(sel ? .white : AD.ink3)
                        .padding(.horizontal, 14).padding(.vertical, 8)
                        .background(sel ? (value ? AD.red : AD.gray) : AD.chip, in: Capsule())
                        .onTapGesture { on = value; if !value { cares = [] } }
                }
            }
            if on {
                FlowLayout(spacing: 6) {
                    ForEach(BodyEdits.careOptions, id: \.self) { o in
                        let sel = cares.contains(o)
                        Text(o).font(.system(size: 12.5, weight: sel ? .bold : .medium)).foregroundStyle(sel ? .white : AD.ink3)
                            .padding(.horizontal, 12).padding(.vertical, 7)
                            .background(sel ? AD.blue : AD.chip, in: Capsule())
                            .onTapGesture { if sel { cares.removeAll { $0 == o } } else { cares.append(o) } }
                    }
                }
            }
            Button {
                m.bodyEdits = m.bodyEdits.applied(mark, on: on, careList: cares, fromCall: fromCall)
                m.shareBody(mark, base: sharedBase)
                dismiss()
            } label: {
                Text("적용").font(.system(size: 15, weight: .bold)).foregroundStyle(.white)
                    .frame(maxWidth: .infinity, minHeight: 44).background(AD.blue, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            }.buttonStyle(.plain)
        }
        .padding(16)
        .onAppear {
            on = v.tiers[mark] != nil
            cares = m.bodyEdits.cares[mark] ?? []
            sharedBase = m.caseEdits.fields
        }
    }
}
