import SwiftUI

/// 상황판 — 전체 사건을 한 화면에(대량사고용). 구급차 화면과 같은 디자인이지만 병원 후보 리스트·현장 상태·통화 요약은 없다.
/// 왼쪽: 상황 요약 + 사건 목록(누르면 지도가 그 현장으로) / 가운데: 거미줄 3D(모든 사건) / 오른쪽: 병원별 분산 현황.
struct SituationBoardView: View {
    @EnvironmentObject private var board: BoardModel
    @AppStorage("hubBase") private var hubBase = Settings.defaultHub
    @AppStorage("spiderBase") private var spiderBase = ""
    @State private var selected: String?

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            VStack(spacing: 8) {
                summary
                caseList
            }
            .frame(width: 330)
            mapCard
            hospitalLoad.frame(width: 330)
        }
        .onAppear { board.start() }
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
                Pill(text: "초록 = 승인 병원 중 최적", bg: AD.greenSoft, fg: AD.green)
                Button { NotificationCenter.default.post(name: .spiderEval, object: nil, userInfo: ["js": "fitAllNow()"]) } label: {
                    Label("전체 보기", systemImage: "arrow.up.left.and.arrow.down.right").font(.system(size: 12, weight: .bold)).foregroundStyle(.white)
                        .padding(.horizontal, 12).frame(minHeight: 30).background(AD.blue).clipShape(Capsule())
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            SpiderWebView(url: Settings.spiderURL(apid: nil, screen: "board"))
                .id("board|" + hubBase + "|" + spiderBase)
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                .padding([.horizontal, .bottom], 8)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AD.card).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.line, lineWidth: 1))
    }

    // ── 병원별 분산 현황 ──
    private var hospitalLoad: some View {
        let loads = board.hospitalLoads
        let maxN = max(1, loads.map(\.load).max() ?? 1)
        return VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline) {
                Text("병원별 분산").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Text("확정·승인 병원").font(.system(size: 11)).foregroundStyle(AD.muted)
                Spacer()
            }
            Text("한 병원으로 몰리는지 보는 칸 — 이송 중 부하가 쌓이면 hub가 다음 환자를 다른 병원으로 돌린다(규칙)")
                .font(.system(size: 11)).foregroundStyle(AD.sub)
            if loads.isEmpty {
                Spacer()
                Text("아직 수용 승인·이송 확정된 병원이 없습니다").font(.system(size: 13)).foregroundStyle(AD.muted).frame(maxWidth: .infinity)
                Spacer()
            } else {
                ScrollView {
                    VStack(spacing: 6) {
                        ForEach(loads) { l in loadRow(l, maxN: maxN) }
                    }
                }
                .scrollIndicators(.hidden)
            }
        }
        .frame(maxHeight: .infinity, alignment: .top)
        .card()
    }

    private func loadRow(_ l: BoardModel.HospitalLoad, maxN: Int) -> some View {
        let n = l.load
        return VStack(alignment: .leading, spacing: 5) {
            HStack(spacing: 6) {
                Text(l.name).font(.system(size: 13, weight: .bold)).foregroundStyle(AD.navy).lineLimit(1)
                if let lv = l.level, lv.hasSuffix("센터") { Pill(text: lv.replacingOccurrences(of: "응급의료센터", with: "센터"), bg: AD.blueSoft, fg: AD.blue) }
                Spacer(minLength: 0)
                Text(l.bedUnknown ? "응급실 미상" : "응급실 \(l.available ?? 0)석").font(.system(size: 11, weight: .medium))
                    .foregroundStyle(l.bedUnknown ? AD.muted : (l.available ?? 0) <= 0 ? AD.red : AD.lime)
            }
            GeometryReader { g in
                ZStack(alignment: .leading) {
                    Capsule().fill(AD.line)
                    Capsule().fill(n >= 3 ? AD.orange : AD.green).frame(width: max(n > 0 ? 6 : 0, g.size.width * CGFloat(n) / CGFloat(maxN)))
                }
            }.frame(height: 6)
            HStack(spacing: 6) {
                Text("이송 확정 \(l.confirmed.count)명").font(.system(size: 11.5, weight: .bold)).foregroundStyle(l.confirmed.isEmpty ? AD.muted : AD.green)
                if l.approved > 0 { Text("· 승인 \(l.approved)").font(.system(size: 11)).foregroundStyle(AD.blue) }
                if l.pending > 0 { Text("· 대기 \(l.pending)").font(.system(size: 11)).foregroundStyle(AD.orange) }
                Spacer(minLength: 0)
                Text(l.confirmed.prefix(4).map { "#\($0.num.map(String.init) ?? "?")" }.joined(separator: " ")).font(.system(size: 11, design: .monospaced)).foregroundStyle(AD.ink3)
            }
        }
        .padding(.horizontal, 10).padding(.vertical, 8)
        .background(AD.bg).clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}
