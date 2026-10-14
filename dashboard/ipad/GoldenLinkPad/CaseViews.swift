import MapKit
import SwiftUI

/// 왼쪽 단 — 1. 진행 중 사건 목록 → 선택 사건의 환자 정보(1-2)·발생 위치(1-1, 미니 지도)·진행 과정
struct CaseColumn: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 10) {
            caseList
            if let c = model.selectedCase {
                ScrollView {
                    VStack(spacing: 10) {
                        PatientCard(c: c)
                        MiniMap(c: c).frame(height: 230).clipShape(RoundedRectangle(cornerRadius: 6))
                            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.line, lineWidth: 1))
                        EventsCard(c: c)
                    }
                }
            } else {
                VStack(spacing: 8) {
                    Spacer()
                    Image(systemName: "cross.circle").font(.system(size: 28)).foregroundStyle(Theme.muted)
                    Text("진행 중인 사건이 없습니다").foregroundStyle(Theme.ink2)
                    Text("구급차 대시보드에서 [이동] → 현장 도착 → 휴대폰 전화 앱으로 통화하면 여기에 뜹니다.")
                        .font(.system(size: 12)).foregroundStyle(Theme.muted).multilineTextAlignment(.center)
                    Spacer()
                }.frame(maxWidth: .infinity).panel()
            }
        }
    }

    private var caseList: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionTitle(text: "진행 중 사건", sub: "\(model.cases.count)건 · hub 실시간")
            if model.orderedCases.isEmpty {
                Text("—").foregroundStyle(Theme.muted).font(.system(size: 12))
            } else {
                ScrollView {
                    VStack(spacing: 4) {
                        ForEach(model.orderedCases) { c in
                            CaseRow(c: c, selected: c.caseId == model.selectedCase?.caseId)
                                .onTapGesture { model.selectedCaseId = c.caseId }
                        }
                    }
                }.frame(maxHeight: 150)
            }
        }.panel(10)
    }
}

struct CaseRow: View {
    @EnvironmentObject private var model: AppModel
    var c: AppModel.CaseState
    var selected: Bool
    var body: some View {
        HStack(spacing: 8) {
            Chip(text: "K\(c.ktas)", color: Theme.ktas(c.ktas), filled: true)
            Text("#\(c.num.map(String.init) ?? "?")").font(.system(size: 13, weight: .semibold)).foregroundStyle(Theme.ink)
            Text(c.overview?.expectedDiagnosis ?? c.symptom ?? "증상 정보 없음").font(.system(size: 12)).foregroundStyle(Theme.ink2).lineLimit(1)
            Spacer()
            Text(Labels.phase(model.sim(for: c)?.phase) .isEmpty ? (c.matched ? "요청 중" : "매칭 전") : Labels.phase(model.sim(for: c)?.phase))
                .font(.system(size: 11)).foregroundStyle(Theme.muted)
        }
        .padding(.horizontal, 8).padding(.vertical, 6)
        .background(selected ? Theme.panel2 : Color.clear)
        .overlay(RoundedRectangle(cornerRadius: 4).stroke(selected ? Theme.ink2 : Theme.line, lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: 4))
        .contentShape(Rectangle())
    }
}

/// 1-2 발생 환자의 정보 — 휴대폰 통화에서 뽑힌 KTAS·예상 병명·주 호소·필요 진료과·나이/성별과 확인 여부. 통화 전문·활력징후는 안 온다.
struct PatientCard: View {
    @EnvironmentObject private var model: AppModel
    var c: AppModel.CaseState

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Text("K\(c.ktas)").font(.system(size: 26, weight: .bold)).foregroundStyle(Theme.ktas(c.ktas))
                VStack(alignment: .leading, spacing: 1) {
                    Text("사건 #\(c.num.map(String.init) ?? "?") · \(Labels.severity(c.severity))\(c.ktasEstimated ? " (KTAS 추정)" : "")")
                        .font(.system(size: 13, weight: .semibold)).foregroundStyle(Theme.ink)
                    Text("\(c.ambulanceName ?? c.apid ?? "") · \(phaseText)").font(.system(size: 11)).foregroundStyle(Theme.muted)
                }
                Spacer()
                if let by = c.overview?.confirmedBy {
                    Chip(text: by == "paramedic" ? "구급대원 확인" : "AI 요약 · 확인 전", color: by == "paramedic" ? Theme.ok : Theme.amber)
                }
                if c.overview?.paused == true { Chip(text: "정지", color: Theme.clash) }
            }
            Divider().overlay(Theme.line)
            if c.matched {
                row("예상 병명", c.overview?.expectedDiagnosis ?? "—", strong: true)
                row("주 호소", c.overview?.chiefComplaint ?? "—")
                row("필요 진료과", c.overview?.requiredDepartment ?? "—")
                row("환자", c.overview?.patient ?? "—")
            } else {
                row("신고 내용", c.symptom ?? "—", strong: true)
                Text("현장 통화 전 — 통화 요약이 오면 KTAS·예상 병명·진료과가 채워집니다.").font(.system(size: 11)).foregroundStyle(Theme.muted)
            }
            if let p = model.position(of: c) {
                row("발생 위치", String(format: "%.5f, %.5f", p.lat, p.lng) + (model.sim(for: c)?.incident != nil ? " (현장)" : " (구급차 위치)"))
            }
            if let z = c.overview?.zoneActive, !z.isEmpty {
                let cnt = c.counts
                row("요청 범위", "존 \(z.count) (\(z.count * 5) km) · 병원 \(c.hospitals.count)곳 — 대기 \(cnt.pending) · 승인 \(cnt.approved) · 불가 \(cnt.rejected)\(cnt.confirmed > 0 ? " · 확정 \(cnt.confirmed)" : "")")
            }
            if let t = c.startedAt { row("시작", Labels.clock(t)) }
            Text("출처: 휴대폰 통화 → 온디바이스/중앙 STT·MF_BERT(AI) → hub. 통화 전문·활력징후는 관제에 오지 않습니다.")
                .font(.system(size: 10)).foregroundStyle(Theme.muted)
        }.panel()
    }

    private var phaseText: String {
        let p = Labels.phase(model.sim(for: c)?.phase)
        return p.isEmpty ? (c.matched ? "병원 요청 중" : "매칭 전") : p
    }

    private func row(_ k: String, _ v: String, strong: Bool = false) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(k).font(.system(size: 11)).foregroundStyle(Theme.muted).frame(width: 64, alignment: .leading)
            Text(v).font(.system(size: strong ? 14 : 12, weight: strong ? .semibold : .regular)).foregroundStyle(Theme.ink)
            Spacer(minLength: 0)
        }
    }
}

/// 1-1 발생 환자의 위치 — 현장 점·후보 병원(응답 색)·구급차와 이송 경로. 3D는 가운데 거미줄이 맡고 여기는 평면 확인용.
struct MiniMap: View {
    @EnvironmentObject private var model: AppModel
    var c: AppModel.CaseState
    @State private var position: MapCameraPosition = .automatic

    var body: some View {
        Map(position: $position) {
            if let p = model.position(of: c) {
                Annotation("현장 #\(c.num.map(String.init) ?? "?")", coordinate: CLLocationCoordinate2D(latitude: p.lat, longitude: p.lng)) {
                    Circle().fill(Theme.ktas(c.ktas)).frame(width: 16, height: 16).overlay(Circle().stroke(.white, lineWidth: 2))
                }
            }
            ForEach(c.hospitals.prefix(14)) { h in
                if let g = h.gps ?? model.gps(of: h.hospitalId) {
                    Annotation(shortName(h.name), coordinate: CLLocationCoordinate2D(latitude: g.lat, longitude: g.lng), anchor: .center) {
                        Circle().fill(Theme.status(h.status)).frame(width: h.status == "confirmed" ? 14 : 10, height: h.status == "confirmed" ? 14 : 10)
                            .overlay(Circle().stroke(.white.opacity(0.8), lineWidth: 1))
                    }
                }
            }
            if let s = model.sim(for: c), let g = s.gps, s.phase != "idle" {
                if let path = s.path, path.count > 1 {
                    MapPolyline(coordinates: path.map { CLLocationCoordinate2D(latitude: $0[0], longitude: $0[1]) })
                        .stroke(Theme.ktas(c.ktas).opacity(0.8), lineWidth: 3)
                }
                Annotation("구급차 · \(Labels.phase(s.phase))", coordinate: CLLocationCoordinate2D(latitude: g.lat, longitude: g.lng)) {
                    Image(systemName: "cross.circle.fill").font(.system(size: 18)).foregroundStyle(.white, Theme.ktas(c.ktas))
                }
            }
        }
        .mapStyle(.standard(elevation: .flat, pointsOfInterest: .excludingAll))
        .onAppear { recentre() }
        .onChange(of: c.caseId) { _, _ in recentre() }
        .onChange(of: c.hospitals.count) { _, _ in recentre() }
    }

    private func recentre() {
        var pts: [GpsPoint] = []
        if let p = model.position(of: c) { pts.append(p) }
        for h in c.hospitals.prefix(8) { if let g = h.gps ?? model.gps(of: h.hospitalId) { pts.append(g) } }
        guard !pts.isEmpty else { return }
        let lats = pts.map(\.lat), lngs = pts.map(\.lng)
        let center = CLLocationCoordinate2D(latitude: (lats.min()! + lats.max()!) / 2, longitude: (lngs.min()! + lngs.max()!) / 2)
        let span = MKCoordinateSpan(latitudeDelta: max((lats.max()! - lats.min()!) * 1.5, 0.03), longitudeDelta: max((lngs.max()! - lngs.min()!) * 1.5, 0.04))
        position = .region(MKCoordinateRegion(center: center, span: span))
    }

    private func shortName(_ n: String) -> String {
        var s = n
        for pat in ["학교법인", "의료법인", "재단법인", "의과대학부속", "의과대학", "서울특별시"] { s = s.replacingOccurrences(of: pat, with: "") }
        s = s.replacingOccurrences(of: "대학교", with: "대")
        return String(s.prefix(9))
    }
}

/// 2. 진행 과정 — hub 사건 기록(규칙 기반): 출동·요청 시작·승인·불가·확장·확정·완료
struct EventsCard: View {
    var c: AppModel.CaseState
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            SectionTitle(text: "진행 과정", sub: "hub 기록")
            if c.events.isEmpty {
                Text("—").foregroundStyle(Theme.muted).font(.system(size: 12))
            }
            ForEach(c.events) { e in
                HStack(alignment: .top, spacing: 8) {
                    Rectangle().fill(kindColor(e.kind)).frame(width: 2)
                    Text(Labels.clock(e.t)).font(.system(size: 11, design: .monospaced)).foregroundStyle(Theme.muted).frame(width: 58, alignment: .leading)
                    Text(e.text ?? "").font(.system(size: 12)).foregroundStyle(Theme.ink)
                }
            }
        }.panel()
    }
    private func kindColor(_ k: String?) -> Color {
        switch k {
        case "a": return Theme.ok
        case "t": return Theme.ktas(2)
        case "r", "x": return Theme.clash
        case "d": return Theme.occ
        case "c": return Theme.muted
        default: return Theme.line
        }
    }
}
