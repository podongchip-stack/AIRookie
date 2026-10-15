import SwiftUI

/// 상황판 — 전체 사건을 한 화면에(대량사고용). 구급차 화면과 같은 디자인이지만 병원 후보 리스트·현장 상태·통화 요약은 없다.
/// 왼쪽: 상황 요약 + 사건 목록(누르면 지도가 그 현장으로) / 오른쪽 전체: 거미줄 3D(모든 사건). 병원별 분산은 자료가 생기면
/// 지도 오른쪽 위에 떠 있는 카드로 올라온다(2026-10-15) — 그동안 지도는 그 카드 폭만큼 비켜서 맞춘다(spider setViewPadding).
struct SituationBoardView: View {
    @EnvironmentObject private var board: BoardModel
    @AppStorage("hubBase") private var hubBase = Settings.defaultHub
    @AppStorage("spiderBase") private var spiderBase = ""
    @State private var selected: String?
    @State private var showLoadInfo = false

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            VStack(spacing: 8) {
                summary
                caseList
            }
            .frame(width: 330)
            mapCard
        }
        .onAppear { board.start(); sendPadding(!board.hospitalLoads.isEmpty) }
        .onChange(of: board.hospitalLoads.isEmpty) { _, empty in sendPadding(!empty) }
    }

    /// 떠 있는 병원별 분산 카드 폭(카드 + 여백) — 지도가 [전체 보기]·자동 맞춤 때 이만큼 오른쪽을 비운다
    private static let floatWidth: CGFloat = 252
    private func sendPadding(_ shown: Bool) {
        NotificationCenter.default.post(name: .spiderEval, object: nil,
                                        userInfo: ["js": "setViewPadding(\(shown ? Int(Self.floatWidth + 28) : 0))", "key": "pad"])
    }

    // ── 상황 요약 ──
    private var summary: some View {
        let p = board.phaseCounts, k = board.ktasCounts, total = board.rows.count
        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .firstTextBaseline) {
                Text("상황 요약").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Spacer()
                Text("관제 · 보기 전용").font(.system(size: 11)).foregroundStyle(AD.muted)
            }
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text("\(total)").font(.system(size: 34, weight: .black)).foregroundStyle(AD.navy)
                Text("건 진행 중").font(.system(size: 13, weight: .medium)).foregroundStyle(AD.ink3)
                Spacer()
                Text("요청 병원 \(board.requestedHospitalCount)곳").font(.system(size: 12)).foregroundStyle(AD.sub)
            }
            HStack(spacing: 6) {
                stage("출동", p.dispatching, AD.ink3, AD.chip)
                stage("병원 선택", p.requesting, AD.orange, AD.orangeSoft)
                stage("이송 중", p.transporting, AD.blue, AD.blueSoft)
                stage("도착", p.arrived, AD.green, AD.greenSoft)
            }
            // KTAS 분포 — 한 줄 막대
            if total > 0 {
                VStack(alignment: .leading, spacing: 4) {
                    GeometryReader { g in
                        HStack(spacing: 2) {
                            ForEach(1...5, id: \.self) { kk in
                                let n = k[kk] ?? 0
                                if n > 0 { Rectangle().fill(Theme.ktas(kk)).frame(width: max(4, g.size.width * CGFloat(n) / CGFloat(total) - 2)) }
                            }
                        }
                    }
                    .frame(height: 8).clipShape(Capsule())
                    HStack(spacing: 10) {
                        ForEach(1...5, id: \.self) { kk in
                            HStack(spacing: 3) { Dot(color: Theme.ktas(kk), size: 7); Text("K\(kk) \(k[kk] ?? 0)").font(.system(size: 11)).foregroundStyle(AD.ink3) }
                        }
                    }
                }
            }
        }
        .card()
    }

    private func stage(_ label: String, _ n: Int, _ fg: Color, _ bg: Color) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(label).font(.system(size: 11, weight: .medium)).foregroundStyle(fg).lineLimit(1)
            Text("\(n)").font(.system(size: 20, weight: .black)).foregroundStyle(fg)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 8).padding(.vertical, 5)
        .background(bg).clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    // ── 사건 목록 ──
    private var caseList: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text("사건 목록").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Text("누르면 지도가 그 현장으로").font(.system(size: 11)).foregroundStyle(AD.muted)
                Spacer()
            }
            if board.ordered.isEmpty {
                Spacer()
                Text("진행 중인 사건이 없습니다").font(.system(size: 13)).foregroundStyle(AD.muted).frame(maxWidth: .infinity)
                Spacer()
            } else {
                ScrollView {
                    VStack(spacing: 6) {
                        ForEach(board.ordered) { r in
                            caseRow(r)
                                .onTapGesture {
                                    selected = r.caseId
                                    if let p = board.position(of: r) {
                                        NotificationCenter.default.post(name: .spiderFocus, object: nil, userInfo: ["lat": p.lat, "lng": p.lng])
                                    }
                                }
                        }
                    }
                }
                .scrollIndicators(.hidden)
            }
        }
        .frame(maxHeight: .infinity, alignment: .top)
        .card()
    }

    private func caseRow(_ r: BoardModel.Row) -> some View {
        let sim = board.sim(for: r)
        let phase: (String, Color) = {
            switch sim?.phase {
            case "dispatching": return ("출동 중", AD.ink3)
            case "transporting": return ("이송 중", AD.blue)
            case "at_hospital": return ("병원 도착", AD.green)
            case "rerouting": return ("재선택", AD.red)
            default: return r.confirmed != nil ? ("이송 확정", AD.green) : r.matched ? ("병원 선택", AD.orange) : ("현장", AD.red)
            }
        }()
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Pill(text: "K\(r.ktas)\(r.ktasEstimated ? "?" : "")", bg: Theme.ktasSoft(r.ktas), fg: Theme.ktas(r.ktas), bold: true)
                Text("#\(r.num.map(String.init) ?? "?")").font(.system(size: 13, weight: .bold)).foregroundStyle(AD.navy)
                Text(r.title).font(.system(size: 12.5, weight: .medium)).foregroundStyle(AD.ink).lineLimit(1)
                Spacer(minLength: 0)
                Text(phase.0).font(.system(size: 11, weight: .bold)).foregroundStyle(phase.1)
            }
            HStack(spacing: 6) {
                Text(r.ambulanceName ?? r.apid ?? "").font(.system(size: 11)).foregroundStyle(AD.sub).lineLimit(1)
                Spacer(minLength: 0)
                if let c = r.confirmed {
                    Text("→ \(c.name)").font(.system(size: 11, weight: .bold)).foregroundStyle(AD.green).lineLimit(1)
                } else if r.matched {
                    Text("대기 \(r.count("pending")) · 승인 \(r.count("approved")) · 불가 \(r.count("rejected"))").font(.system(size: 11)).foregroundStyle(AD.ink3)
                } else {
                    Text("병원 요청 전").font(.system(size: 11)).foregroundStyle(AD.muted)
                }
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 8)
        .background(selected == r.caseId ? AD.blueSoft : AD.bg)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 12, style: .continuous).stroke(selected == r.caseId ? AD.blue : AD.line, lineWidth: 1))
        .contentShape(Rectangle())
    }

    // ── 지도(모든 사건) ──
    private var mapCard: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text("거미줄 분배 · 전체 상황").font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy)
                Text("환자 → 최적 병원 · 이송 경로").font(.system(size: 11.5)).foregroundStyle(AD.sub)
                Spacer()
                Pill(text: "초록 = 요청 병원·최적", bg: AD.greenSoft, fg: AD.green)
                Button { NotificationCenter.default.post(name: .spiderEval, object: nil, userInfo: ["js": "fitAllNow()"]) } label: {
                    Label("전체 보기", systemImage: "arrow.up.left.and.arrow.down.right").font(.system(size: 12, weight: .bold)).foregroundStyle(.white)
                        .padding(.horizontal, 12).frame(minHeight: 30).background(AD.blue).clipShape(Capsule())
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            SpiderWebView(url: Settings.spiderURL(apid: nil, screen: "board"))
                .id("board|" + hubBase + "|" + spiderBase)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                .overlay(alignment: .topTrailing) {
                    // 병원별 분산 — 수용 승인·이송 확정된 병원이 생기면 지도 위에 떠 있는 카드로
                    GeometryReader { g in
                        let loads = board.hospitalLoads
                        if !loads.isEmpty {
                            HStack { Spacer(minLength: 0); floatingLoad(loads, maxHeight: g.size.height - 24) }
                                .padding(12)
                                .transition(.move(edge: .trailing).combined(with: .opacity))
                        }
                    }
                }
                .animation(.spring(response: 0.4, dampingFraction: 0.86), value: board.hospitalLoads.isEmpty)
                .padding([.horizontal, .bottom], 8)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AD.card).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.line, lineWidth: 1))
    }

    // ── 병원별 분산 현황(지도 위에 떠 있는 카드) — 글자를 줄였다(2026-10-16): 제목 한 줄 + 병원당 두 줄(이름·센터·병상 / 몰림 막대·
    // 확정·승인·대기 숫자·사건 번호). 설명 문장은 ⓘ를 누를 때만, 색 점의 뜻은 맨 아래 범례 한 줄. 글자는 11pt 아래로 내리지 않는다.
    private func floatingLoad(_ loads: [BoardModel.HospitalLoad], maxHeight: CGFloat) -> some View {
        let maxN = max(1, loads.map(\.load).max() ?? 1)
        let listHeight = min(CGFloat(loads.count) * 52, max(80, maxHeight - 70))   // 줄당 약 52pt, 넘치면 스크롤
        return VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 6) {
                Text("분산 \(loads.count)곳").font(.system(size: 14, weight: .bold)).foregroundStyle(AD.navy)
                Spacer()
                Button { showLoadInfo.toggle() } label: {
                    Image(systemName: showLoadInfo ? "info.circle.fill" : "info.circle").font(.system(size: 14)).foregroundStyle(AD.muted)
                }
                .buttonStyle(.plain)
            }
            if showLoadInfo {
                Text("확정·승인 병원. 한 병원으로 몰리면 hub가 다음 환자를 다른 병원으로 돌린다(규칙)")
                    .font(.system(size: 11)).foregroundStyle(AD.sub).fixedSize(horizontal: false, vertical: true)
            }
            ScrollView {
                VStack(spacing: 4) { ForEach(loads) { l in loadRow(l, maxN: maxN) } }
            }
            .scrollIndicators(.hidden)
            .frame(height: listHeight)
            HStack(spacing: 8) {
                legend(AD.green, "확정"); legend(AD.blue, "승인"); legend(AD.orange, "대기")
                Spacer(minLength: 0)
                Text("석 = 응급실 여유").font(.system(size: 11)).foregroundStyle(AD.muted)
            }
        }
        .padding(10)
        .frame(width: Self.floatWidth)
        .background(AD.card.opacity(0.96))
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(AD.line, lineWidth: 1))
        .shadow(color: .black.opacity(0.28), radius: 12, y: 5)
    }

    private func legend(_ c: Color, _ t: String) -> some View {
        HStack(spacing: 3) { Dot(color: c, size: 7); Text(t).font(.system(size: 11)).foregroundStyle(AD.ink3) }
    }

    private func loadRow(_ l: BoardModel.HospitalLoad, maxN: Int) -> some View {
        let n = l.load
        let level = l.level.flatMap { $0.hasPrefix("권역") ? "권역" : $0.hasPrefix("지역응급의료센터") ? "지역" : nil }
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 5) {
                Text(l.name).font(.system(size: 13, weight: .bold)).foregroundStyle(AD.navy).lineLimit(1)
                if let level { Pill(text: level, bg: AD.blueSoft, fg: AD.blue) }
                Spacer(minLength: 4)
                Text(l.bedUnknown ? "미상" : "\(l.available ?? 0)석").font(.system(size: 12, weight: .bold))
                    .foregroundStyle(l.bedUnknown ? AD.muted : (l.available ?? 0) <= 0 ? AD.red : AD.lime)
            }
            HStack(spacing: 6) {
                GeometryReader { g in
                    ZStack(alignment: .leading) {
                        Capsule().fill(AD.line)
                        Capsule().fill(n >= 3 ? AD.orange : AD.green).frame(width: max(n > 0 ? 5 : 0, g.size.width * CGFloat(n) / CGFloat(maxN)))
                    }
                }
                .frame(height: 5)
                count(l.confirmed.count, AD.green, always: true)
                count(l.approved, AD.blue)
                count(l.pending, AD.orange)
                if !l.confirmed.isEmpty {
                    Text("#" + l.confirmed.prefix(3).map { $0.num.map(String.init) ?? "?" }.joined(separator: "·"))
                        .font(.system(size: 11, design: .monospaced)).foregroundStyle(AD.ink3).lineLimit(1).fixedSize()
                }
            }
        }
        .padding(.horizontal, 9).padding(.vertical, 6)
        .background(AD.bg).clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    @ViewBuilder private func count(_ v: Int, _ c: Color, always: Bool = false) -> some View {
        if v > 0 || always {
            HStack(spacing: 2) { Dot(color: v > 0 ? c : AD.muted, size: 7); Text("\(v)").font(.system(size: 12, weight: .bold)).foregroundStyle(v > 0 ? c : AD.muted) }
                .fixedSize()
        }
    }
}
