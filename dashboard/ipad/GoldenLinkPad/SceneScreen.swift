import CoreLocation
import SwiftUI

// [현장] — 현장에 도착해 통화 요약이 오기 전(상황 판단 중)의 화면. 안드로이드·아이폰 현장 지도와 같은 흐름이다(2026-11-02):
// Pre-KTAS를 고르면(현장 도착 때 1이 미리 골라져 있다) hub가 첫 연락 추천 순서로 후보 병원을 다시 보내고, 통화 요약이 오면
// 구급차에서 후보 병원들로 요약이 동시에 전달되는 연출을 지도 위에 보여 준 뒤 환자 정보로 넘어간다.
// 지도는 카카오맵 SDK(KakaoMapView) — 아이폰·안드로이드와 같은 지도다.

/// 요약 전달 연출 — 지도 위에서 구급차 → 병원마다 곡선이 거의 동시에 그려지고 이름 칩이 뜬다. 병원이 많으면 앞의 8곳만 그리고 숫자는 전체를 센다
struct DeliveryShow {
    let caseId: String
    let durationMs: Double
    let reduceMotion: Bool
    let startedAt = Date()
}

enum DeliveryTimeline {
    static let maxTargets = 8
    private static let delay = 650.0     // 카메라가 구급차 주변으로 맞춰지는 동안
    private static let stagger = 90.0    // 병원마다 출발 간격 — 거의 동시로 보이게 짧게
    private static let flight = 800.0    // 선이 구급차에서 병원까지 그려지는 시간
    private static let pop = 350.0       // 도착한 병원의 이름 칩이 떠오르는 시간

    static func flightProgress(_ i: Int, _ t: Double, reduce: Bool) -> Double {
        reduce ? 1 : min(max((t - delay - stagger * Double(i)) / flight, 0), 1)
    }
    private static func arrivedAt(_ i: Int, reduce: Bool) -> Double { reduce ? 0 : delay + stagger * Double(i) + flight }
    /// 도착 뒤 0→1, 도착 전에는 -1
    static func popProgress(_ i: Int, _ t: Double, reduce: Bool) -> Double {
        t < arrivedAt(i, reduce: reduce) ? -1 : min((t - arrivedAt(i, reduce: reduce)) / pop, 1)
    }
    static func arrivedCount(_ n: Int, _ t: Double, reduce: Bool) -> Int { (0..<n).filter { t >= arrivedAt($0, reduce: reduce) }.count }
}

private func easeOutCubic(_ x: Double) -> Double { let d = 1 - x; return 1 - d * d * d }

/// 구급차→병원 곡선 위의 한 점 — 병원마다 휘는 방향을 번갈아 줘서 선이 겹치지 않게 한다
private func curvePoint(_ a: CGPoint, _ b: CGPoint, bend: Double, _ t: Double) -> CGPoint {
    let len = max(hypot(b.x - a.x, b.y - a.y), 1)
    let nx = -(b.y - a.y) / len, ny = (b.x - a.x) / len
    let c = CGPoint(x: (a.x + b.x) / 2 + nx * len * 0.18 * bend, y: (a.y + b.y) / 2 + ny * len * 0.18 * bend)
    let u = 1 - t
    return CGPoint(x: u * u * a.x + 2 * u * t * c.x + t * t * b.x, y: u * u * a.y + 2 * u * t * c.y + t * t * b.y)
}

private func curvePath(_ a: CGPoint, _ b: CGPoint, bend: Double, from: Double, to: Double) -> Path {
    var p = Path()
    guard to > from else { return p }
    let steps = 28
    for k in 0...steps {
        let pt = curvePoint(a, b, bend: bend, from + (to - from) * Double(k) / Double(steps))
        if k == 0 { p.move(to: pt) } else { p.addLine(to: pt) }
    }
    return p
}

struct DeliveryTarget: Identifiable {
    let id: String
    let name: String
    let coordinate: CLLocationCoordinate2D
}

private extension GpsPoint { var coordinate: CLLocationCoordinate2D { .init(latitude: lat, longitude: lng) } }

/// 지도 위에 덮는 연출 — 화면을 누르면 건너뛴다
private struct DeliveryOverlay: View {
    let show: DeliveryShow
    let from: CLLocationCoordinate2D
    let targets: [DeliveryTarget]
    let project: (CLLocationCoordinate2D) -> CGPoint?
    let onSkip: () -> Void

    var body: some View {
        TimelineView(.animation) { ctx in
            let t = ctx.date.timeIntervalSince(show.startedAt) * 1000
            Canvas { gc, _ in
                guard let a = project(from) else { return }
                let glow = show.reduceMotion ? 0 : 1 - min(t / 900, 1)
                gc.fill(Path(ellipseIn: CGRect(x: a.x - (20 + 18 * (1 - glow)), y: a.y - (20 + 18 * (1 - glow)),
                                               width: 2 * (20 + 18 * (1 - glow)), height: 2 * (20 + 18 * (1 - glow)))),
                        with: .color(AD.blue.opacity(0.10 + 0.12 * glow)))
                for (i, target) in targets.enumerated() {
                    guard let b = project(target.coordinate) else { continue }
                    let bend = i % 2 == 0 ? 1.0 : -1.0
                    let f = DeliveryTimeline.flightProgress(i, t, reduce: show.reduceMotion)
                    let pop = DeliveryTimeline.popProgress(i, t, reduce: show.reduceMotion)
                    let arrived = pop >= 0
                    let e = easeOutCubic(f)
                    let settle = arrived ? 0.45 - 0.2 * pop : 0.45
                    gc.stroke(curvePath(a, b, bend: bend, from: 0, to: e), with: .color(AD.blue.opacity(settle)),
                              style: StrokeStyle(lineWidth: 2, lineCap: .round))
                    if f > 0, f < 1 {
                        let head = curvePath(a, b, bend: bend, from: max(e - 0.22, 0), to: e)
                        gc.stroke(head, with: .color(.white.opacity(0.9)), style: StrokeStyle(lineWidth: 3.5, lineCap: .round))
                        gc.stroke(head, with: .color(AD.blue.opacity(0.85)), style: StrokeStyle(lineWidth: 2.2, lineCap: .round))
                    }
                    if arrived {
                        let r1 = 7 + 14 * pop
                        gc.fill(Path(ellipseIn: CGRect(x: b.x - r1, y: b.y - r1, width: 2 * r1, height: 2 * r1)), with: .color(AD.green.opacity(0.25 * (1 - pop))))
                        gc.fill(Path(ellipseIn: CGRect(x: b.x - 6, y: b.y - 6, width: 12, height: 12)), with: .color(AD.green))
                        gc.stroke(Path(ellipseIn: CGRect(x: b.x - 6, y: b.y - 6, width: 12, height: 12)), with: .color(.white), lineWidth: 1.5)
                    } else {
                        gc.fill(Path(ellipseIn: CGRect(x: b.x - 4.5, y: b.y - 4.5, width: 9, height: 9)), with: .color(.white.opacity(0.85)))
                        gc.stroke(Path(ellipseIn: CGRect(x: b.x - 4.5, y: b.y - 4.5, width: 9, height: 9)), with: .color(AD.gray), lineWidth: 1.5)
                    }
                }
            }
            .overlay {
                // 이름 칩 — 도착하면 떠오른다. 이웃한 병원과 겹치지 않게 번갈아 위·아래에 둔다
                ZStack {
                    ForEach(Array(targets.enumerated()), id: \.element.id) { i, target in
                        let pop = DeliveryTimeline.popProgress(i, t, reduce: show.reduceMotion)
                        if pop >= 0, let b = project(target.coordinate) {
                            let grow = easeOutCubic(min(pop * 1.6, 1))
                            (Text("✓ ").foregroundColor(AD.green) + Text(target.name).foregroundColor(AD.navy))
                                .font(.system(size: 12, weight: .bold)).lineLimit(1).frame(maxWidth: 150)
                                .padding(.horizontal, 8).padding(.vertical, 4)
                                .background(Capsule().fill(.white.opacity(0.96)))
                                .overlay(Capsule().stroke(AD.green, lineWidth: 1.5))
                                .scaleEffect(0.7 + 0.3 * grow).opacity(grow)
                                .position(x: b.x, y: i % 2 == 0 ? b.y - 24 : b.y + 24)
                        }
                    }
                }
            }
            .overlay(alignment: .bottom) {
                let arrived = DeliveryTimeline.arrivedCount(targets.count, t, reduce: show.reduceMotion)
                let done = arrived >= targets.count
                VStack(spacing: 2) {
                    HStack(spacing: 8) {
                        Image(systemName: done ? "checkmark.circle.fill" : "paperplane.fill").foregroundStyle(done ? AD.green : AD.blue)
                        Text(done ? "후보 병원에 전달됐습니다" : "후보 병원 \(arrived)곳에 전달 중…")
                            .font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                    }
                    Text("화면을 누르면 건너뜁니다").font(.system(size: 11)).foregroundStyle(AD.muted)
                }
                .padding(.horizontal, 18).padding(.vertical, 10).background(.white.opacity(0.95), in: Capsule()).padding(.bottom, 18)
            }
            .onChange(of: t >= show.durationMs) { _, over in if over { onSkip() } }
        }
        .contentShape(Rectangle())
        .onTapGesture(perform: onSkip)
    }
}

/// 현장 지도 — 안드로이드 [통화] 탭(지도가 바탕)과 같은 흐름이다(2026-11-02). 출동 중엔 현장까지 도로 경로와 ETA, 현장에선 Pre-KTAS → 후보 병원,
/// 요약이 병원에 전달되면 응답 존·병원 응답, 이송 중엔 목적지까지 경로. 왼쪽 패널이 단계마다 바뀌고 오른쪽은 계속 같은 지도다.
/// 통화만 없다 — 통화는 휴대폰 앱이 한다.
struct SceneScreen: View {
    @EnvironmentObject private var model: AppModel
    @State private var centerRequest = 0
    @State private var focusId: String?
    @State private var projector: MapProjector?
    @State private var mapMessage: String? = "카카오맵을 불러오는 중…"

    private var phase: String { model.sim?.phase ?? "idle" }
    private var candidates: [SceneCandidate] { model.scene?.hospitals ?? [] }
    private var sent: Bool { model.result != nil }
    private var inTransport: Bool { ["transporting", "at_hospital", "rerouting"].contains(phase) }
    private var incident: CLLocationCoordinate2D? { model.sim?.incident?.coordinate }
    private var ambulance: CLLocationCoordinate2D? { model.sim?.gps?.coordinate }
    private var baseCoord: CLLocationCoordinate2D? { model.sim?.base?.coordinate }
    private var zoneKm: Double? { sent && phase == "on_scene" ? 5.0 * Double(model.result?.zoneActive?.max() ?? 1) : nil }

    /// hub가 준 도로 경로의 남은 구간. 경로가 없으면 임의의 직선을 만들지 않는다.
    private var route: [CLLocationCoordinate2D] {
        guard let sim = model.sim, let a = sim.gps else { return [] }
        if let path = sim.path {
            let rest = RoadRoute.remaining(path, latitude: a.lat, longitude: a.lng)
            if rest.count >= 2 { return rest.map { .init(latitude: $0[0], longitude: $0[1]) } }
        }
        return []
    }
    private var etaMin: Int? { model.sim?.etaSec.map { max(1, Int(ceil($0 / 60))) } }

    /// 연출에 그릴 병원 — 통화 요약 결과의 후보 중 좌표를 아는 앞의 8곳
    private var deliveryTargets: [DeliveryTarget] {
        let known = Dictionary(candidates.compactMap { c in c.gps.map { (c.hospitalId, $0) } }, uniquingKeysWith: { a, _ in a })
        return (model.result?.hospitals ?? []).compactMap { h -> DeliveryTarget? in
            guard let g = h.gps ?? known[h.hospitalId] else { return nil }
            return DeliveryTarget(id: h.hospitalId, name: h.name, coordinate: g.coordinate)
        }.prefix(DeliveryTimeline.maxTargets).map { $0 }
    }

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            sidePanel.frame(width: 380).frame(maxHeight: .infinity, alignment: .top).card(14)
            mapCard
        }
    }

    /// 카메라를 다시 맞추는 때 — 구급차 위치가 1초마다 바뀔 때마다 맞추지 않고, 단계·사건·경로·후보·존·연출이 바뀔 때만
    private var fitKey: [String] {
        [phase, model.sim?.caseId ?? "", "\(model.sim?.path?.count ?? 0)", "\(candidates.count)", "\(model.result?.hospitals.count ?? 0)",
         "\(zoneKm ?? 0)", model.deliveryShow == nil ? "-" : "show", model.confirmed?.hospitalId ?? "", focusId ?? ""]
    }

    // ── 왼쪽: 단계마다 바뀌는 패널 ──
    @ViewBuilder private var sidePanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            stepper
            if inTransport { transportPanel }
            else if model.deliveryShow != nil { Text("요약을 후보 병원에 전달하고 있습니다").font(.system(size: 14, weight: .bold)).foregroundStyle(AD.navy) }
            else if sent { sentPanel }
            else if phase == "on_scene" { scenePanel }
            else { movingPanel }
            Spacer(minLength: 0)
        }
    }

    /// 출동 → 현장 도착 → 통화(요약) → 병원 전달, 지금 어디쯤인지
    private var stepper: some View {
        let steps = ["출동", "현장 도착", "요약", "병원 전달"]
        let current: Int = {
            if inTransport || sent { return 3 }
            switch phase {
            case "dispatching": return 0
            case "on_scene": return model.callStatus?.state == "calling" ? 2 : 1
            default: return 0
            }
        }()
        return HStack(spacing: 4) {
            ForEach(Array(steps.enumerated()), id: \.offset) { i, title in
                VStack(spacing: 4) {
                    Circle().fill(i <= current ? AD.blue : AD.control).frame(width: 10, height: 10)
                        .overlay(Circle().stroke(AD.blue.opacity(i == current ? 0.3 : 0), lineWidth: 5))
                    Text(title).font(.system(size: 11, weight: i == current ? .bold : .medium)).foregroundStyle(i <= current ? AD.navy : AD.muted)
                }.frame(maxWidth: .infinity)
            }
        }
    }

    /// 출동 중·복귀 중 — 구급차 단계와 ETA
    private var movingPanel: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Pill(text: Labels.phase(phase), bg: AD.blueSoft, fg: AD.blue, bold: true)
                if phase == "dispatching", let e = etaMin { Text("현장까지 약 \(e)분").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy) }
            }
            if let sym = model.scene?.reportedSymptom {
                Text("신고: \(sym)").font(.system(size: 13, weight: .semibold)).foregroundStyle(AD.ink)
            }
            if phase == "dispatching" || phase == "returning", (model.sim?.path?.count ?? 0) <= 2 {
                Text("도로 경로를 받지 못했습니다. hub의 경로 API 연결을 확인해 주세요.").font(.system(size: 11)).foregroundStyle(AD.orange)
            }
            Text("현장에 도착하면 Pre-KTAS를 고르고 후보 병원을 확인합니다.").font(.system(size: 12)).foregroundStyle(AD.sub)
        }
    }

    /// 현장(전달 전) — Pre-KTAS와 후보 병원
    private var scenePanel: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("환자 상태에 맞는 Pre-KTAS를 고르면 첫 연락 추천 순서가 바로 바뀝니다. 통화 요약이 오면 후보 병원 전체에 동시에 전달됩니다.")
                .font(.system(size: 12)).foregroundStyle(AD.sub).fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 6) {
                ForEach(1...5, id: \.self) { k in
                    let on = model.preKtas == k
                    Button { model.setPreKtas(k) } label: {
                        VStack(spacing: 1) {
                            Text("\(k)").font(.system(size: 20, weight: .black))
                            Text("Pre-KTAS").font(.system(size: 9, weight: .semibold))
                        }
                        .foregroundStyle(on ? .white : Theme.ktas(k))
                        .frame(maxWidth: .infinity, minHeight: 50)
                        .background(on ? Theme.ktas(k) : Theme.ktasSoft(k), in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                    }.buttonStyle(.plain)
                }
            }
            HStack {
                Text("후보 병원 \(candidates.count)곳").font(.system(size: 13, weight: .bold)).foregroundStyle(AD.navy)
                Spacer()
                if let s = model.scene, let z = s.zoneActive?.max() { Pill(text: "Zone \(z)", bg: AD.blueSoft, fg: AD.blue, bold: true) }
            }
            if model.scene?.preKtas != model.preKtas {
                HStack(spacing: 8) { ProgressView(); Text("KTAS 적합 병원을 확인하고 있습니다").font(.system(size: 13)).foregroundStyle(AD.sub) }
                    .frame(maxWidth: .infinity, minHeight: 80)
            } else if candidates.isEmpty {
                Text("현재 탐색 범위에 KTAS 적합 병원이 없습니다").font(.system(size: 13)).foregroundStyle(AD.sub).frame(maxWidth: .infinity, minHeight: 80)
            } else {
                ScrollView {
                    LazyVStack(spacing: 8) {
                        ForEach(candidates) { h in
                            SceneRow(h: h, on: h.hospitalId == focusId).onTapGesture { focusId = h.hospitalId }
                        }
                    }
                }
            }
        }
    }

    /// 요약이 병원에 전달된 뒤 — 몇 곳에 갔고 응답이 어떤지(상세는 [이송] 탭)
    private var sentPanel: some View {
        let hs = model.result?.hospitals ?? []
        let ok = hs.filter { $0.status == "approved" || $0.status == "confirmed" }.count
        let no = hs.filter { $0.status == "rejected" || $0.unavailableReason != nil }.count
        return VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                Image(systemName: "checkmark.circle.fill").font(.system(size: 26)).foregroundStyle(AD.green)
                Text("후보 병원 \(hs.count)곳에 전달됐습니다").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
            }
            HStack(spacing: 6) {
                Pill(text: "수용 승인 \(ok)", bg: AD.greenSoft, fg: AD.green, bold: true)
                Pill(text: "수용 불가 \(no)", bg: AD.redSoft, fg: AD.red, bold: true)
                Pill(text: "판단 대기 \(max(hs.count - ok - no, 0))", bg: AD.orangeSoft, fg: AD.orange, bold: true)
            }
            if let z = model.result?.zoneActive?.max() { Text("요청 범위 Zone \(z) · 구급차 중심 \(Int(5 * Double(z)))km").font(.system(size: 12)).foregroundStyle(AD.sub) }
            ScrollView {
                LazyVStack(spacing: 6) {
                    ForEach(hs) { h in
                        let c = Theme.statusPill(h.status)
                        HStack(spacing: 8) {
                            Text(h.name).font(.system(size: 13, weight: .semibold)).foregroundStyle(AD.navy).lineLimit(1)
                            Spacer(minLength: 4)
                            Pill(text: (h.unavailableReason != nil ? "수용 불가" : Labels.status(h.status)), bg: c.bg, fg: c.fg, bold: true)
                        }
                        .padding(.horizontal, 10).padding(.vertical, 8).background(AD.chip, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                    }
                }
            }
        }
    }

    /// 이송 중·도착·재선택 — 목적지와 ETA
    @ViewBuilder private var transportPanel: some View {
        if phase == "rerouting" { ReselectBanner() }
        else {
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 8) {
                    Pill(text: phase == "at_hospital" ? "병원 도착" : "병원 이송 중", bg: AD.blueSoft, fg: AD.blue, bold: true)
                    if phase == "transporting", let e = etaMin { Text("도착까지 약 \(e)분").font(.system(size: 12)).foregroundStyle(AD.sub) }
                }
                Text("목적지 병원").font(.system(size: 11.5)).foregroundStyle(AD.sub)
                Text(model.confirmed?.name ?? "확정 병원").font(.system(size: 20, weight: .black)).foregroundStyle(AD.navy)
                Text("이송 중 환자 상태가 바뀌면 휴대폰으로 목적지 병원과 통화하세요. 통화 내용은 환자 정보에 덧붙어 병원 화면에 바로 반영됩니다.")
                    .font(.system(size: 12.5)).foregroundStyle(AD.ink3).fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    // ── 오른쪽: 지도(카카오맵) ──
    private var pins: [MapPin] {
        var out: [MapPin] = []
        if let g = model.sim?.incident { out.append(MapPin(id: "incident", name: phase == "dispatching" ? "사건 현장" : "", pos: g, kind: .incident)) }
        if phase == "dispatching" || phase == "returning", let g = model.sim?.base { out.append(MapPin(id: "base", name: "센터", pos: g, kind: .base)) }
        if let g = model.sim?.gps { out.append(MapPin(id: "ambulance", name: model.ambulanceName ?? "구급차", pos: g, kind: .ambulance)) }
        if inTransport {
            if let d = model.confirmed, let g = d.gps ?? candidates.first(where: { $0.hospitalId == d.hospitalId })?.gps {
                out.append(MapPin(id: d.hospitalId, name: d.name, pos: g, kind: .selected))
            }
        } else if sent {
            for h in model.result?.hospitals ?? [] {
                guard let g = h.gps else { continue }
                let kind: MapPin.Kind = h.status == "rejected" || h.unavailableReason != nil ? .rejected : (h.status == "pending" ? .hospital : .approved)
                out.append(MapPin(id: h.hospitalId, name: h.name, pos: g, kind: kind))
            }
        } else if phase == "on_scene" {
            for h in candidates {
                guard let g = h.gps else { continue }
                let kind: MapPin.Kind = h.hospitalId == focusId ? .selected : (h.firstCallRecommended == true ? .recommended : .hospital)
                out.append(MapPin(id: h.hospitalId, name: h.name, pos: g, kind: kind))
            }
        }
        return out
    }

    /// 단계에 맞춰 카메라를 맞출 점 — 출동·이송·복귀는 구급차와 목적지·경로, 현장은 현장과 후보, 전달 뒤는 응답 병원과 존, 연출 중엔 전달 대상
    private var fitPoints: [GpsPoint] {
        var pts: [GpsPoint] = []
        if let a = model.sim?.gps { pts.append(a) }
        if model.deliveryShow != nil { pts += deliveryTargets.map { GpsPoint(lat: $0.coordinate.latitude, lng: $0.coordinate.longitude) } }
        else if let id = focusId, let g = candidates.first(where: { $0.hospitalId == id })?.gps, phase == "on_scene", !sent { pts.append(g) }
        else if inTransport {
            if let d = model.confirmed, let g = d.gps ?? candidates.first(where: { $0.hospitalId == d.hospitalId })?.gps { pts.append(g) }
            pts += route.striding(8).map { GpsPoint(lat: $0.latitude, lng: $0.longitude) }
        } else if sent {
            pts += (model.result?.hospitals ?? []).compactMap { $0.gps }
            if let km = zoneKm, let a = model.sim?.gps { pts += mapCircle(center: a, radiusKm: km) }
        } else if phase == "on_scene" {
            if let c = model.sim?.incident { pts.append(c) }
            pts += candidates.prefix(6).compactMap { $0.gps }
        } else {
            if let c = model.sim?.incident { pts.append(c) }
            if phase == "returning", let b = model.sim?.base { pts.append(b) }
            pts += route.striding(8).map { GpsPoint(lat: $0.latitude, lng: $0.longitude) }
        }
        return pts
    }

    private var roadPath: [[Double]] {
        guard let a = model.sim?.gps else { return [] }
        if let path = model.sim?.path { let rest = RoadRoute.remaining(path, latitude: a.lat, longitude: a.lng); if rest.count >= 2 { return rest } }
        return []
    }

    private var mapCard: some View {
        KakaoMapView(pins: pins, routePath: roadPath, zoneRadiusKm: zoneKm, fitKey: fitKey.joined(separator: "|"), fitPoints: fitPoints, centerRequest: centerRequest,
                     initialCenter: model.needsInitialMapCenter, onInitialCenter: { model.needsInitialMapCenter = false },
                     onPin: { id in if candidates.contains(where: { $0.hospitalId == id }) { focusId = id } },
                     onProjector: { projector = $0 }, onMessage: { mapMessage = $0 })
            .id(Settings.kakaoNativeAppKey)
            .overlay {
                if let mapMessage {
                    Text(mapMessage).font(.system(size: 13)).multilineTextAlignment(.center)
                        .padding(20).frame(maxWidth: .infinity, maxHeight: .infinity).background(AD.bg.opacity(0.95))
                }
            }
            .overlay {
                if let show = model.deliveryShow, let from = ambulance, let p = projector {
                    DeliveryOverlay(show: show, from: from, targets: deliveryTargets,
                                    project: { c in p.point(lat: c.latitude, lng: c.longitude) }, onSkip: { model.finishDelivery() })
                }
            }
            .overlay(alignment: .topTrailing) {
                Button { centerRequest += 1 } label: {
                    Label("내 위치", systemImage: "location.fill")
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundStyle(AD.blue)
                        .padding(.horizontal, 16).frame(minHeight: 44)
                        .background(.white, in: Capsule()).shadow(radius: 3)
                }
                .buttonStyle(.plain)
                .padding(12)
                .disabled(mapMessage != nil || !(model.sim?.gps.map {
                    $0.lat.isFinite && $0.lng.isFinite && (-90...90).contains($0.lat) && (-180...180).contains($0.lng)
                } ?? false))
                .accessibilityHint("현재 구급차 위치로 지도를 이동합니다")
            }
            .clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.line, lineWidth: 1))
            .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private extension Array {
    /// 길이가 긴 경로에서 몇 점만 골라 카메라 범위 계산에 쓴다(처음·끝 포함)
    func striding(_ n: Int) -> [Element] {
        guard count > n, n > 1 else { return self }
        return (0..<n).map { self[$0 * (count - 1) / (n - 1)] }
    }
}

/// 후보 병원 한 줄 — 첫 연락 추천 · 도착 시간 · 병상
private struct SceneRow: View {
    let h: SceneCandidate
    let on: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Text(h.name).font(.system(size: 14, weight: .bold)).foregroundStyle(AD.navy).lineLimit(1)
                Spacer(minLength: 4)
                if h.firstCallRecommended == true { Pill(text: "첫 연락 추천", bg: AD.greenSoft, fg: AD.green, bold: true) }
            }
            HStack(spacing: 8) {
                Text(h.etaMin.map { "도착 \($0)분" } ?? "직선 \(String(format: "%.1f", h.distanceKm))km").font(.system(size: 12)).foregroundStyle(AD.ink3)
                Text(bedText).font(.system(size: 12, weight: .semibold)).foregroundStyle(bedColor)
                if let l = h.emergencyLevel { Text(l).font(.system(size: 11)).foregroundStyle(AD.sub).lineLimit(1) }
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(10)
        .background(on ? AD.blueSoft : AD.chip, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
        .contentShape(Rectangle())
    }

    private var bedText: String {
        if h.bedCountUnknown == true { return "병상 미상" }
        return (h.availableBedCount ?? 0) > 0 ? "빈 병상 \(h.availableBedCount ?? 0)" : "만실"
    }
    private var bedColor: Color {
        if h.bedCountUnknown == true { return AD.sub }
        return (h.availableBedCount ?? 0) > 0 ? AD.green : AD.red
    }
}
