import GoldenLinkCore
import SwiftUI
import UIKit
import CoreLocation

// 화면 디자인(2026-10-05) — 웹 대시보드 디자인 시안들(구급차·병원 대시보드, 시연 콘솔, 관제 지도)과 같은 색·카드 언어를 쓴다:
// 연회색 바탕 + 흰 카드(둥근 18) · 남색 글자 · 알약 칩 · 병상/AI 유효/전문의 세 칸 · AI(파랑)와 규칙(회색) 출처 구분.
// 화면 순서: 통화 중 > 통화 끝(전송 처리) > 다른 기기 통화 중 > 현장(병원 목록 / 전달됨 · 추가 통화) > 이송 중(목적지 병원과 통화) > 대기·출동

// MARK: - 디자인 색 (dashboard/src/components/ambulance/ambulance-design.ts와 같은 값)

enum AD {
    static let bg = Color(hex: 0xF4F6FA)
    static let line = Color(hex: 0xE3E7EE)
    static let control = Color(hex: 0xD3D9E3)
    static let ink = Color(hex: 0x1B2430)
    static let navy = Color(hex: 0x14213D)
    static let ink3 = Color(hex: 0x4A5565)
    static let sub = Color(hex: 0x5A6676)
    static let muted = Color(hex: 0x7A8594)
    static let chip = Color(hex: 0xF1F3F6)
    static let blue = Color(hex: 0x1F4E9C)
    static let blueSoft = Color(hex: 0xE8EEF8)
    static let green = Color(hex: 0x168A55)
    static let greenSoft = Color(hex: 0xE3F3EB)
    static let lime = Color(hex: 0x4E8B1F)
    static let limeSoft = Color(hex: 0xEEF5E6)
    static let orange = Color(hex: 0xC75B00)
    static let orangeSoft = Color(hex: 0xFFF1E0)
    static let red = Color(hex: 0xD93025)
    static let redSoft = Color(hex: 0xFDECEA)
    static let gray = Color(hex: 0x9AA3B0)
}

extension Color {
    init(hex: UInt32) {
        self.init(.sRGB,
                  red: Double((hex >> 16) & 0xFF) / 255,
                  green: Double((hex >> 8) & 0xFF) / 255,
                  blue: Double(hex & 0xFF) / 255,
                  opacity: 1)
    }
}

// MARK: - 공용 조각

struct Pill: View {
    let text: String
    var fg: Color = AD.ink3
    var bg: Color = AD.chip
    var bold = false

    var body: some View {
        Text(text)
            .font(.system(size: 11, weight: bold ? .bold : .medium))
            .foregroundStyle(fg)
            .padding(.horizontal, 9).padding(.vertical, 3)
            .background(bg, in: Capsule())
            .lineLimit(1)
    }
}

struct Card<Content: View>: View {
    var border: Color = AD.line
    var borderWidth: CGFloat = 1
    @ViewBuilder let content: Content

    var body: some View {
        content
            .padding(14)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(.white, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(border, lineWidth: borderWidth))
    }
}

/// 병상 · AI 유효 · 전문의 한 칸(대시보드 후보 카드와 같은 모양)
struct StatBox: View {
    let label: String
    let value: String
    let fg: Color
    let bg: Color
    var valueColor: Color?

    var body: some View {
        VStack(alignment: .leading, spacing: 1) {
            Text(label).font(.system(size: 11, weight: .medium)).foregroundStyle(fg)
            Text(value).font(.system(size: 19, weight: .black)).foregroundStyle(valueColor ?? fg)
                .lineLimit(1).minimumScaleFactor(0.7)
        }
        .padding(.horizontal, 10).padding(.vertical, 6)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(bg, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
    }
}

struct Dot: View {
    let color: Color
    var size: CGFloat = 8
    var body: some View { Circle().fill(color).frame(width: size, height: size) }
}

// MARK: - 루트

struct ContentView: View {
    @Environment(PhoneModel.self) private var m
    @State private var showSettings = false

    /// 헤더 아래 끝(화면 맨 위 기준) — 지도는 헤더 뒤(상태바 밑까지)로 이어지고, 다른 화면은 이 아래에서 시작한다
    @State private var headerBottom: CGFloat = 0
    @State private var headerHeight: CGFloat = 0

    /// 지도가 화면 맨 위까지 이어지는 화면인가 — 통화 탭의 지도 화면(안드로이드와 같은 전체 화면 레이아웃)
    private var showsMap: Bool {
        guard m.call == nil, m.tab == .call else { return false }
        if let s = m.status, s.state == "calling" { return false }
        if m.inTransport { return true }
        return m.apid != nil && !(m.identity != nil && !m.simOn) && m.mySim?.gps != nil
    }

    var body: some View {
        // 통화가 진행 중이거나 끝난 직후엔 탭과 상관없이 통화 화면(예전 그대로) — 통화 중에 화면이 바뀌면 안 된다
        let inCallFlow = m.call != nil
        ZStack(alignment: .top) {
            AD.bg.ignoresSafeArea()
            VStack(spacing: 10) {
                Group {
                    if inCallFlow || m.tab == .call { content }
                    else if m.tab == .patient { PatientTab() }
                    else if m.tab == .transport { TransportTab() }
                    else { RecordsTab() }
                }
                .padding(.horizontal, showsMap ? 0 : 16)
                .padding(.top, showsMap ? 0 : headerHeight + 10)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .ignoresSafeArea(.container, edges: showsMap ? .top : [])
                if !inCallFlow { TabBar().padding(.horizontal, 16) }
            }
            // 헤더 — 지도 위에 떠 있다
            VStack(spacing: 10) {
                header
                CaseEditStatusView(sync: m.caseEdits, onlyPending: true)
            }
            .padding(.horizontal, 16)
            .padding(.top, 6)
            .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { headerHeight = $0 }
            .onGeometryChange(for: CGFloat.self) { $0.frame(in: .global).maxY } action: { headerBottom = $0 }
        }
        .foregroundStyle(AD.ink)
        .overlay(alignment: .top) {
            // 일시정지 등 잠깐 뜨는 안내(2026-10-05)
            if let notice = m.notice {
                HStack(spacing: 8) {
                    Image(systemName: "pause.circle.fill").foregroundStyle(Color(hex: 0xFFB86B))
                    Text(notice).font(.system(size: 14, weight: .bold)).foregroundStyle(.white)
                }
                .padding(.horizontal, 18).padding(.vertical, 12)
                .background(AD.navy, in: Capsule())
                .shadow(color: AD.navy.opacity(0.3), radius: 12, y: 6)
                .padding(.top, 8)
                .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.easeOut(duration: 0.2), value: m.notice)
        // 통화 중엔 화면을 켜 둔다(시연 중 화면이 꺼져 흐름이 끊기지 않게 — 녹음 자체는 백그라운드 오디오로 이어진다, 안드로이드 FLAG_KEEP_SCREEN_ON과 동일)
        .onChange(of: m.call != nil) { _, inCall in UIApplication.shared.isIdleTimerDisabled = inCall }
        .overlay {
            if showSettings {
                ZStack {
                    Color.black.opacity(0.35).ignoresSafeArea().onTapGesture { showSettings = false }
                    SettingsView(onApply: { m.start() }, onClose: { showSettings = false })
                        .padding(.horizontal, 16)
                }
                .transition(.opacity)
            }
        }
        .animation(.easeOut(duration: 0.15), value: showSettings)
        .alert("알림", isPresented: .constant(m.error != nil)) { Button("확인") { m.error = nil } } message: { Text(m.error ?? "") }
    }

    // 상단: 로고 · 구급대 | 연결 · 설정
    private var header: some View {
        HStack(spacing: 8) {
            (Text("골든").foregroundStyle(AD.navy) + Text("링크").foregroundStyle(AD.blue))
                .font(.system(size: 19, weight: .black))
            Pill(text: m.identity?.name ?? m.apid ?? "구급대 미지정", fg: AD.ink3, bg: .white, bold: true)
            Spacer(minLength: 4)
            ConnectionDot(state: m.connection)
            Button { showSettings = true } label: {
                Image(systemName: "gearshape.fill").font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(AD.ink3)
                    .frame(width: 36, height: 36)
                    .background(AD.chip, in: Circle())
            }
            .disabled(m.call != nil && m.call?.phase != .ended)
            .accessibilityLabel("설정")
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(.white, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(AD.line))
        .shadow(color: .black.opacity(0.08), radius: 6, y: 2)
    }

    @ViewBuilder private var content: some View {
        if let call = m.call, call.phase != .ended {
            InCallView(call: call)
        } else if m.call?.phase == .ended {
            EndedView()
        } else if let s = m.status, s.state == "calling" {
            StatusPanel(icon: "phone.fill", tint: AD.green,
                        title: "\(s.device == "phone" ? "다른 휴대폰" : "구급차 대시보드")에서 통화 중",
                        detail: "\(s.hospitalName ?? "병원")과 통화하고 있습니다. 통화가 끝나면 다시 걸 수 있습니다.")
        } else if m.inTransport {
            CallMapScreen(topInset: headerBottom)
        } else {
            waiting
        }
    }

    @ViewBuilder private var waiting: some View {
        if m.apid == nil {
            StatusPanel(icon: "phone", tint: AD.blue, title: "출동 대기 중",
                        detail: "상황이 발생하면 출동하는 구급대의 전화 앱으로 자동 전환됩니다.")
        } else if m.identity != nil && !m.simOn {
            StatusPanel(icon: "car", tint: AD.gray, title: "출동 시뮬레이션이 꺼져 있습니다",
                        detail: "휴대폰 전화 앱은 출동 시뮬레이션에서만 씁니다.")
        } else if m.mySim?.gps == nil {
            StatusPanel(icon: "car", tint: AD.gray, title: m.phase.label, pulse: true, detail: "구급차 위치를 받는 중입니다.")
        } else {
            CallMapScreen(topInset: headerBottom)
        }
    }
}

/// 구급대 단계 색 — 관제 지도 구급차 마커 색과 같은 규칙(대기 회색 · 출동 주황 · 현장 빨강 · 이송 파랑 · 병원 초록)
func phaseColor(_ phase: AmbulancePhase) -> Color {
    switch phase {
    case .idle: AD.gray
    case .dispatching: AD.orange
    case .on_scene: AD.red
    case .transporting: AD.blue
    case .at_hospital, .rerouting: AD.green
    case .returning: AD.sub
    }
}

// MARK: - 지도 화면 (통화 탭 기본)

/// 지도가 배경. 출동 중엔 현장까지 선과 ETA, 현장에선 hub가 추천한 병원 목록 → 전화,
/// 병원 응답 중에는 관제 지도와 같은 보라색 활성 존과 확산 펄스를 지도에 표시한다. 지도는 카카오맵 iOS SDK.
struct CallMapScreen: View {
    /// 지도 위를 덮는 헤더의 아래 끝(화면 맨 위 기준) — 카메라 맞춤과 버튼 위치가 이 아래를 쓴다
    let topInset: CGFloat
    @Environment(PhoneModel.self) private var m
    @State private var tappedId: String?
    @State private var callCardHeight: CGFloat = 0

    var body: some View {
        @Bindable var m = m
        guard let sim = m.mySim, let ambulanceGps = sim.gps else { return AnyView(EmptyView()) }
        let phase = m.phase
        let sentMode = m.onScene && m.sent && !m.wantsExtraCall
        let scene = m.preKtas == nil ? [] : m.sceneHospitals
        // 현장 후보는 hub 도착 시간순 — 전달된 뒤에는 실제로 정보가 간 병원(매칭 결과)을 쓴다
        let ordered = scene.filter { $0.firstCallRecommended == true } + scene.filter { $0.firstCallRecommended != true }
        // 목록은 hub 첫 연락 규칙(이동·병상·전문의·도착 유효 확률 + 다른 구급차 점유) 그대로 — hub가 추천한 병원이 첫 연락 대상
        let nearest = scene.first { $0.firstCallRecommended == true }
        let target = scene.first { $0.hospitalId == tappedId } ?? nearest
        // 요약이 병원들에 전달되는 연출 — 지도 안 도형으로 그린다(CallMapView). 병원이 많으면 앞의 8곳만
        let show = m.deliveryShow.flatMap { $0.caseId == m.caseId && sentMode ? $0 : nil }
        let deliveryTargets: [DeliveryTarget] = show == nil ? [] : Array((m.result?.hospitals ?? []).compactMap { h in
            m.hospitalGps[h.hospitalId].map { DeliveryTarget(id: h.hospitalId, name: h.name, gps: $0) }
        }.prefix(DeliveryTimeline.maxTargets))
        let delivery: DeliveryInput? = show.flatMap { sh in
            deliveryTargets.isEmpty ? nil : DeliveryInput(caseId: sh.caseId, from: ambulanceGps, targets: deliveryTargets, durationMs: sh.durationMs, reduceMotion: sh.reduceMotion)
        }

        var hospitals: [(String, String)] = sentMode
            ? (m.result?.hospitals.map { ($0.hospitalId, $0.name) } ?? [])
            : (m.onScene ? ordered.map { ($0.hospitalId, $0.name) } : [])
        if m.inTransport || phase == .at_hospital, let dest = m.destination, !hospitals.contains(where: { $0.0 == dest.hospitalId }) {
            hospitals.append((dest.hospitalId, dest.name))
        }
        // 핀 정책은 안드로이드와 같다 — 병원에 도착하면 구급차는 병원 핀 위에 겹쳐 핀을 가리므로 그리지 않고(도착은 카드가 알린다),
        // 사건 현장은 출동·현장·이송 중에만, 센터는 출동·복귀 중에만 그린다. 병원 핀은 전화할 병원(선택)·목적지(확정)만 — 다른 후보는 그리지 않는다
        var pins: [MapPin] = []
        if phase != .at_hospital { pins.append(MapPin(id: "ambulance", name: m.identity?.name ?? sim.apid, pos: ambulanceGps, kind: .ambulance)) }
        if [.dispatching, .returning].contains(phase), let base = sim.base {
            pins.append(MapPin(id: "base", name: "센터", pos: base, kind: .base))
        }
        if [.dispatching, .on_scene, .transporting, .rerouting].contains(phase), let inc = sim.incident {
            // 사건 현장 글자는 출동 중에만 — 도착하면 뗀다
            pins.append(MapPin(id: "incident", name: phase == .dispatching ? "사건 현장" : "", pos: inc, kind: .incident))
        }
        for (id, name) in hospitals {
            guard let gps = m.hospitalGps[id] else { continue }
            guard id == m.destination?.hospitalId || (!sentMode && id == target?.hospitalId) else { continue }
            pins.append(MapPin(id: id, name: name, pos: gps, kind: .selected))
        }

        return AnyView(
            ZStack(alignment: .bottom) {
                CallMapView(pins: pins, routePath: m.routePaths[sim.apid] ?? [], showCandidates: sentMode, delivery: delivery, topOverlayHeight: topInset,
                            sceneFocusKey: m.onScene && !sentMode ? target.map { "\(m.caseId ?? "")-\($0.hospitalId)" } : nil,
                            bottomOverlayHeight: callCardHeight,
                            responseZone: m.onScene ? ResponseZone(bands: m.result?.zoneActive ?? [1]) : nil,
                            onPin: { id in if m.onScene, !sentMode, scene.contains(where: { $0.hospitalId == id }) { tappedId = id } })
                VStack(spacing: 10) {
                    if [.dispatching, .transporting, .returning].contains(phase), (m.routePaths[sim.apid]?.count ?? 0) <= 2 {
                        Text("도로 경로를 받지 못했습니다. hub의 경로 API 연결을 확인해 주세요.")
                            .font(.system(size: 11)).foregroundStyle(AD.orange)
                    }
                    if let show, delivery != nil {
                        DeliveryCardView(show: show, shown: deliveryTargets.count, total: m.caseId.flatMap { m.sentCount[$0] } ?? hospitals.count)
                    } else if sentMode {
                        let n = m.caseId.flatMap { m.sentCount[$0] } ?? hospitals.count
                        HStack(spacing: 10) {
                            Image(systemName: n > 0 ? "checkmark.circle.fill" : "exclamationmark.circle.fill").foregroundStyle(n > 0 ? AD.green : AD.orange).font(.system(size: 22))
                            Text(n > 0 ? "후보 병원 \(n)곳에 전달됐습니다" : "현재 범위에 전달할 병원이 없습니다").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                        }
                        BigButton(text: "추가 통화", color: AD.blue, icon: "phone.badge.plus") { m.wantsExtraCall = true }
                    } else if m.phase == .rerouting {
                        PhoneReselectList()
                    } else if m.inTransport {
                        Text(m.destination?.name ?? "목적지 병원").font(.headline)
                        BigButton(text: "목적지 병원과 통화", color: AD.blue, icon: "phone.fill", enabled: m.destination != nil && !m.transportCallBlocked && !m.paused) { Task { if let d = m.destination { await m.dial(hospitalId: d.hospitalId, name: d.name) } } }
                    } else if phase == .at_hospital {
                        HStack(spacing: 10) {
                            Image(systemName: "checkmark.circle.fill").foregroundStyle(AD.green).font(.system(size: 26))
                            VStack(alignment: .leading, spacing: 2) {
                                Text("\(m.destination?.name ?? "병원")에 도착했습니다").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                                Text("병원이 환자 수용을 확인하면 이어서 마무리됩니다").font(.system(size: 12.5)).foregroundStyle(AD.sub)
                            }
                        }
                    } else if m.onScene {
                        BigButton(text: "병원 리스트", color: AD.blue, icon: "list.bullet") {
                            tappedId = nil
                            m.requestFirstCall()
                            showCallHospitals = true
                        }
                    } else {
                        HStack(spacing: 8) {
                            Pill(text: phase.label, fg: phaseColor(phase), bg: phaseColor(phase).opacity(0.12), bold: true)
                            if phase == .dispatching, let eta = sim.etaSec.map({ max(1, Int(($0 / 60).rounded(.up))) }) {
                                Text("현장까지 약 \(eta)분").font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy)
                            } else if phase == .returning, let eta = sim.etaSec.map({ max(1, Int(($0 / 60).rounded(.up))) }) {
                                Text("기지까지 약 \(eta)분").font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy)
                            }
                        }
                    }
                }
                .padding(12)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.white.opacity(0.96), in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(AD.line))
                // 카드 안의 빈 곳을 눌러도 뒤쪽 최소화 영역으로 전달하지 않는다.
                .contentShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
                .onTapGesture { }
                .padding(10)
                .onGeometryChange(for: CGFloat.self) { $0.size.height } action: { callCardHeight = $0 }
            }
            // 연출 중에는 화면 아무 데나 누르면 건너뛴다
            .overlay {
                if show != nil { Color.clear.contentShape(Rectangle()).onTapGesture { m.finishDelivery() } }
            }
            // 지도는 위·옆이 화면 끝까지 이어지고 아래만 둥글다(안드로이드와 같다)
            .clipShape(UnevenRoundedRectangle(bottomLeadingRadius: 18, bottomTrailingRadius: 18, style: .continuous))
        )
        .sheet(isPresented: $showCallHospitals) {
            NavigationStack {
                VStack(spacing: 12) {
                    Text("병원 리스트").font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy)
                        .frame(maxWidth: .infinity, alignment: .center)
                    Text("hub 추천순 · 이동·병상·전문의·도착 유효 확률과 다른 사건의 연락·이송을 반영합니다")
                        .font(.caption).foregroundStyle(AD.sub)
                    if m.scene == nil {
                        ProgressView("추천 병원을 확인하고 있습니다")
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else {
                        List(m.scene?.hospitals ?? []) { h in
                            HStack(spacing: 12) {
                                VStack(alignment: .leading, spacing: 5) {
                                    Text((h.firstCallRecommended == true ? "추천 · " : "") + h.name).font(.headline)
                                    Text(distanceText(h)).font(.subheadline)
                                    Text(h.firstCallReason ?? "추천 후보").font(.caption).foregroundStyle(AD.sub)
                                    if m.scene?.callAttempts?.contains(h.hospitalId) == true {
                                        Text("전화 미응답 이력").font(.caption).foregroundStyle(AD.orange)
                                    }
                                }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                Button {
                                    showCallHospitals = false
                                    Task { await m.dial(h) }
                                } label: {
                                    Label("전화", systemImage: "phone.fill")
                                        .font(.system(size: 14, weight: .bold))
                                        .padding(.horizontal, 12).frame(minHeight: 44)
                                        .foregroundStyle(.white).background(AD.blue, in: RoundedRectangle(cornerRadius: 12))
                                }
                                .buttonStyle(.borderless)
                                .disabled(m.sceneCallBlocked || m.paused || m.call != nil)
                            }.padding(.vertical, 4)
                        }
                        .overlay {
                            if m.scene?.hospitals.isEmpty != false {
                                Text("현재 탐색 범위에 병원이 없습니다")
                                    .font(.subheadline).foregroundStyle(AD.sub).padding()
                            }
                        }
                    }
                }
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .principal) {
                        HStack {
                            Text("병원 리스트").font(.system(size: 17, weight: .semibold))
                            Spacer()
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    ToolbarItem(placement: .confirmationAction) { Button("닫기") { showCallHospitals = false } }
                }
            }
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        })
    }

    private func distanceText(_ h: SceneCandidate) -> String {
        let km = h.roadDistanceKm ?? h.distanceKm
        let dist = h.roadDistanceKm != nil ? String(format: "%.1fkm", km) : String(format: "직선 %.1fkm", km)
        if let eta = h.etaMin { return "\(dist) · ETA \(Int(eta.rounded()))분" }
        return dist
    }
}

private struct BigButton: View {
    let text: String
    let color: Color
    var icon: String?
    var enabled = true
    let action: () -> Void
    var body: some View {
        Button(action: action) {
            HStack(spacing: 8) {
                if let icon { Image(systemName: icon) }
                Text(text).fontWeight(.bold)
            }
            .font(.system(size: 15)).foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 46)
            .background(color, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
        .buttonStyle(.plain).disabled(!enabled)
    }
}

// MARK: - 통화 중

struct InCallView: View {
    @Environment(PhoneModel.self) private var m
    let call: PhoneModel.LocalCall

    var body: some View {
        let connecting = call.phase == .connecting
        VStack(spacing: 12) {
            Card {
                VStack(spacing: 10) {
                    HStack(spacing: 6) {
                        Dot(color: connecting ? AD.orange : AD.red)
                            .symbolEffect(.pulse, isActive: true)
                        Text(connecting ? "연결 중…" : call.followup ? "추가 통화 중" : "통화 중")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundStyle(connecting ? AD.orange : AD.red)
                    }
                    .padding(.horizontal, 10).padding(.vertical, 4)
                    .background((connecting ? AD.orangeSoft : AD.redSoft), in: Capsule())

                    Text(call.hospitalName).font(.system(size: 22, weight: .black)).foregroundStyle(AD.navy)
                        .multilineTextAlignment(.center)
                    if m.transportHeld {
                        // 이송 중 추가 통화 — 통화 내용을 듣고 정보가 반영될 때까지 이동이 잠시 멈춘다(2026-10-05)
                        Pill(text: "이송 잠시 멈춤 · 통화 내용 반영 뒤 다시 출발", fg: AD.blue, bg: AD.blueSoft, bold: true)
                    }
                    TimelineView(.periodic(from: .now, by: 1)) { ctx in
                        Text(connecting ? "전화 응답 대기" : mmss(ctx.date.timeIntervalSince(call.startedAt)))
                            .font(.system(size: 30, weight: .bold).monospacedDigit())
                            .foregroundStyle(connecting ? AD.muted : AD.ink)
                    }
                    let _ = m.tick  // CallSession(관찰 대상 아님)의 레벨·자막이 바뀌면 tick이 올라 다시 그린다
                    LevelMeter(level: CGFloat(min(1, max(0, m.session?.level ?? 0))), active: !connecting)
                }
                .frame(maxWidth: .infinity)
            }

            Card {
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("실시간 자막").font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy)
                        Spacer()
                        Pill(text: "AI · Qwen3-ASR", fg: AD.blue, bg: AD.blueSoft)
                    }
                    ScrollViewReader { proxy in
                        ScrollView {
                            VStack(alignment: .leading, spacing: 6) {
                                if m.transcriptLines.isEmpty {
                                    Text(connecting ? "병원 응답 대기 중입니다. 연결 후 녹음이 시작됩니다." : "말이 끊길 때마다 인식된 문장이 여기에 뜹니다.")
                                        .font(.system(size: 13)).foregroundStyle(AD.muted)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                }
                                ForEach(Array(m.transcriptLines.enumerated()), id: \.offset) { i, line in
                                    Text(line).font(.system(size: 14)).foregroundStyle(AD.ink)
                                        .padding(.horizontal, 10).padding(.vertical, 7)
                                        .frame(maxWidth: .infinity, alignment: .leading)
                                        .background(AD.bg, in: RoundedRectangle(cornerRadius: 10, style: .continuous))
                                        .id(i)
                                }
                            }
                        }
                        .onChange(of: m.transcriptLines.count) { _, n in withAnimation { proxy.scrollTo(n - 1, anchor: .bottom) } }
                    }
                }
            }
            .frame(maxHeight: .infinity)

            if m.call?.phase == .connecting {
                Button("미응답 · 다음 병원") { m.noAnswerNext() }
                    .font(.system(size: 16, weight: .bold)).foregroundStyle(AD.orange)
            }
            // [취소]는 아무것도 보내지 않고, [전송]을 눌러야만 음성을 처리해 병원에 보낸다(2026-10-05)
            HStack(spacing: 10) {
                Button { m.cancelCall() } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "xmark.circle.fill").font(.system(size: 26, weight: .bold))
                        Text("취소").font(.system(size: 19, weight: .bold))
                    }
                    .frame(maxWidth: .infinity, minHeight: 72)
                    .contentShape(Rectangle())
                    .foregroundStyle(AD.red)
                    .background(AD.redSoft, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(AD.red, lineWidth: 2))
                }
                .buttonStyle(.plain)
                Button { m.sendCall() } label: {
                    HStack(spacing: 10) {
                        Image(systemName: "paperplane.fill").font(.system(size: 24, weight: .bold))
                        Text("전송").font(.system(size: 19, weight: .bold))
                    }
                    .frame(maxWidth: .infinity, minHeight: 72)
                    .contentShape(Rectangle())
                    .foregroundStyle(.white)
                    .background(connecting ? AD.control : AD.blue, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
                }
                .buttonStyle(.plain)
                .disabled(connecting)
            }
            Text("취소하면 아무것도 전달되지 않습니다 · 전송을 눌러야 기기에서 음성을 인식·구조화해 병원에 보냅니다")
                .font(.system(size: 10.5)).foregroundStyle(AD.muted).multilineTextAlignment(.center)
        }
    }
}

/// 음성 레벨 막대(마이크 입력 크기 — 통화 시연 패널 파형과 같은 느낌)
struct LevelMeter: View {
    let level: CGFloat
    let active: Bool
    private let count = 24

    var body: some View {
        HStack(alignment: .center, spacing: 3) {
            ForEach(0..<count, id: \.self) { i in
                // 가운데가 높은 고정 모양 × 지금 음량
                let shape = 0.35 + 0.65 * sin(Double(i) / Double(count - 1) * .pi)
                Capsule()
                    .fill(active ? AD.red.opacity(0.75) : AD.control)
                    .frame(width: 4, height: max(4, 34 * CGFloat(shape) * (active ? max(0.12, level) : 0.12)))
            }
        }
        .frame(height: 36)
        .animation(.easeOut(duration: 0.12), value: level)
    }
}

// MARK: - 통화 종료 뒤

struct EndedView: View {
    @Environment(PhoneModel.self) private var m

    var body: some View {
        let _ = m.tick
        let stage = m.session?.stage
        let sent: Int? = m.delivered ? m.caseId.flatMap { m.sentCount[$0] } : nil
        let hospital = m.call?.hospitalName ?? "병원"
        let followup = m.call?.followup == true
        // 서버 음성 인식(모델 없음)은 결과가 hub 매칭으로만 온다 — 90초 넘게 안 오면 말이 인식되지 않은 것으로 본다
        let serverWaitOver = Settings.onDevice == false || m.session == nil || stage == .sent
        TimelineView(.periodic(from: .now, by: 1)) { ctx in
        let timedOut = sent == nil && serverWaitOver && (m.call?.endedAt.map { ctx.date.timeIntervalSince($0) > 90 } ?? false)
        let finished = sent != nil || timedOut || stage == .noSpeech || isFailed(stage)
        VStack(spacing: 12) {
            Spacer(minLength: 0)
            Card(border: sent == 0 ? AD.orange : sent != nil ? AD.green : AD.line, borderWidth: sent != nil ? 2 : 1) {
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 10) {
                        Image(systemName: sent == 0 ? "exclamationmark.circle.fill" : sent != nil ? "checkmark.circle.fill" : "waveform")
                            .font(.system(size: 26, weight: .semibold))
                            .foregroundStyle(sent == 0 ? AD.orange : sent != nil ? AD.green : AD.blue)
                            .symbolEffect(.pulse, isActive: sent == nil)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(sent.map { $0 == 0 ? "전달할 병원이 없습니다" : followup ? "환자 정보에 덧붙여 \($0)곳에 전달됐습니다" : "후보 병원 \($0)곳에 전달됐습니다" }
                                 ?? (timedOut ? "전달되지 않았습니다" : stageTitle(stage)))
                                .font(.system(size: 17, weight: .bold)).foregroundStyle(AD.navy)
                            Text("\(followup ? "추가 통화" : "통화"): \(hospital)").font(.system(size: 12)).foregroundStyle(AD.sub)
                        }
                    }
                    // 진행 단계 — 음성 인식(AI) → 구조화(AI) → 병원 전달(규칙)
                    VStack(alignment: .leading, spacing: 8) {
                        StepRow(title: "남은 음성 인식", source: "AI", state: stepState(0, stage: stage, sent: sent))
                        StepRow(title: "환자 정보 구조화 (MF_BERT)", source: "AI", state: stepState(1, stage: stage, sent: sent))
                        StepRow(title: "존 안 후보 병원에 동시 전달", source: "규칙", state: stepState(2, stage: stage, sent: sent))
                    }
                    if case let .failed(reason)? = stage {
                        Text(reason).font(.system(size: 12)).foregroundStyle(AD.red)
                    }
                    if timedOut {
                        Text("인식된 말이 없었거나 음성 인식 서버에 닿지 않았습니다. 다시 걸 수 있습니다.")
                            .font(.system(size: 12)).foregroundStyle(AD.red)
                    }
                    Divider().overlay(AD.line)
                    Text("병원 응답 확인·이송 승인은 구급차 대시보드에서 합니다.")
                        .font(.system(size: 12)).foregroundStyle(AD.sub)
                    if finished, sent == nil {
                        Button { m.dismissEnded(); m.tab = .call } label: {
                            Text("다시 통화하기")
                                .font(.system(size: 15, weight: .bold))
                                .frame(maxWidth: .infinity, minHeight: 46)
                                .foregroundStyle(.white)
                                .background(AD.blue, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            Spacer(minLength: 0)
        }
        }
    }

    private func isFailed(_ s: CallSession.Stage?) -> Bool {
        if case .failed? = s { return true }
        return false
    }

    private func stageTitle(_ s: CallSession.Stage?) -> String {
        switch s {
        case .finishing?: "남은 음성을 인식하는 중…"
        case .structuring?: "환자 정보를 구조화하는 중…"
        case .noSpeech?: "인식된 말이 없어 전달하지 않았습니다"
        case .failed?: "전달하지 못했습니다"
        default: "환자 정보를 정리하는 중…"
        }
    }

    /// 0 인식 · 1 구조화 · 2 전달. 서버 STT 모드(session 없음)는 hub의 매칭 결과(sent)만으로 판단한다.
    private func stepState(_ index: Int, stage: CallSession.Stage?, sent: Int?) -> StepRow.State {
        if sent == 0 { return index < 2 ? .done : .failed }
        if sent != nil { return .done }
        switch stage {
        case .failed?, .noSpeech?, .cancelled?: return index == 0 ? .done : .failed
        case .finishing?: return index == 0 ? .active : .pending
        case .structuring?: return index == 0 ? .done : index == 1 ? .active : .pending
        case .sent?: return index < 2 ? .done : .active
        default: return index == 0 ? .active : .pending
        }
    }
}

struct StepRow: View {
    enum State { case pending, active, done, failed }
    let title: String
    let source: String
    let state: State

    var body: some View {
        HStack(spacing: 10) {
            ZStack {
                switch state {
                case .done: Image(systemName: "checkmark.circle.fill").foregroundStyle(AD.green)
                case .active: ProgressView().controlSize(.small).tint(AD.blue)
                case .failed: Image(systemName: "xmark.circle.fill").foregroundStyle(AD.red)
                case .pending: Circle().strokeBorder(AD.control, lineWidth: 2)
                }
            }
            .frame(width: 20, height: 20)
            Text(title).font(.system(size: 13, weight: state == .active ? .bold : .regular))
                .foregroundStyle(state == .pending ? AD.muted : AD.ink)
            Spacer()
            Pill(text: source, fg: source == "AI" ? AD.blue : AD.ink3, bg: source == "AI" ? AD.blueSoft : AD.chip)
        }
    }
}

// MARK: - 이송 중: 목적지 병원과 통화

/// 이송 중 환자 상태가 바뀌면 목적지 병원과 다시 통화한다(2026-10-05). 새 요약은 환자 정보에 덧붙어 병원 화면에 반영되고,
/// 병원이 받을 수 없게 되면 병원 대시보드의 [이송 중 수용 철회]로 확정이 풀려 구급차는 다른 병원으로 재선택한다.
struct TransportCallView: View {
    @Environment(PhoneModel.self) private var m

    var body: some View {
        let rerouting = m.phase == .rerouting
        let dest = m.destination
        let eta = m.mySim?.etaSec.map { max(1, Int(($0 / 60).rounded(.up))) }
        VStack(spacing: 12) {
            Spacer(minLength: 0)
            Card(border: rerouting ? AD.red : AD.line, borderWidth: rerouting ? 2 : 1) {
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 8) {
                        Pill(text: rerouting ? "재선택 대기" : "병원 이송 중", fg: rerouting ? AD.red : AD.blue,
                             bg: rerouting ? AD.redSoft : AD.blueSoft, bold: true)
                        if m.transportHeld {
                            Text("통화 내용 반영 중 — 이송 잠시 멈춤").font(.system(size: 12, weight: .bold)).foregroundStyle(AD.blue)
                        } else if !rerouting, let eta {
                            Text("도착까지 약 \(eta)분").font(.system(size: 12)).foregroundStyle(AD.sub)
                        }
                    }
                    if rerouting {
                        Text("목적지 병원이 수용할 수 없게 됐습니다").font(.system(size: 18, weight: .bold)).foregroundStyle(AD.navy)
                        PhoneReselectList()
                    } else {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("목적지 병원").font(.system(size: 11.5)).foregroundStyle(AD.sub)
                            Text(dest?.name ?? "확정 병원").font(.system(size: 20, weight: .black)).foregroundStyle(AD.navy)
                        }
                        Text("이송 중 환자 상태가 바뀌면 목적지 병원과 통화하세요. 통화 내용은 환자 정보에 덧붙어 병원 화면에 바로 반영됩니다.")
                            .font(.system(size: 12.5)).foregroundStyle(AD.ink3).fixedSize(horizontal: false, vertical: true)
                        if m.transportCallBlocked {
                            HStack(alignment: .top, spacing: 8) {
                                Image(systemName: "lock.fill").foregroundStyle(AD.orange)
                                Text("시연 콘솔이 **정해진 상황 선택** 중이라 전화를 걸 수 없습니다. 콘솔에서 **음성으로 통화**를 고르면 전화할 수 있습니다.")
                                    .foregroundStyle(AD.navy)
                            }
                            .font(.system(size: 13))
                            .padding(.horizontal, 12).padding(.vertical, 9)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .background(AD.orangeSoft, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                        }
                        if let dest {
                            Button { Task { await m.dial(hospitalId: dest.hospitalId, name: dest.name) } } label: {
                                HStack(spacing: 8) {
                                    Image(systemName: "phone.fill")
                                    Text("목적지 병원과 통화").fontWeight(.bold)
                                }
                                .font(.system(size: 15))
                                .frame(maxWidth: .infinity, minHeight: 50)
                                .foregroundStyle(.white)
                                .background(m.paused ? AD.control : AD.green, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                            }
                            .buttonStyle(.plain)
                            .disabled(m.transportCallBlocked)
                            .opacity(m.transportCallBlocked ? 0.45 : 1)
                        }
                    }
                }
            }
            Spacer(minLength: 0)
        }
    }
}

// MARK: - 안내 카드

struct StatusPanel: View {
    let icon: String
    var tint: Color = AD.blue
    let title: String
    var pulse = false
    let detail: String

    var body: some View {
        VStack {
            Spacer(minLength: 0)
            Card {
                VStack(spacing: 12) {
                    Image(systemName: icon)
                        .font(.system(size: 30, weight: .semibold))
                        .foregroundStyle(tint)
                        .frame(width: 68, height: 68)
                        .background(tint.opacity(0.12), in: Circle())
                        .symbolEffect(.pulse, isActive: pulse)
                    Text(title).font(.system(size: 19, weight: .bold)).foregroundStyle(AD.navy)
                        .multilineTextAlignment(.center)
                    Text(detail).font(.system(size: 13)).foregroundStyle(AD.sub)
                        .multilineTextAlignment(.center).fixedSize(horizontal: false, vertical: true)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 10)
            }
            Spacer(minLength: 0)
        }
    }
}

struct ConnectionDot: View {
    let state: HubSocket.State
    var body: some View {
        let (color, text): (Color, String) = switch state {
        case .live: (AD.green, "실시간 연동")
        case .connecting: (AD.gray, "연결 중")
        case .reconnecting: (AD.red, "재연결 중")
        }
        HStack(spacing: 5) {
            Dot(color: color)
            Text(text).font(.system(size: 11.5, weight: .medium)).foregroundStyle(color)
        }
    }
}

// MARK: - 설정 (안드로이드 SettingsDialog와 같은 AD 카드 디자인 — 네이티브 Form/NavigationStack 대신 커스텀 모달)

struct SettingsView: View {
    @Environment(PhoneModel.self) private var m
    let onApply: () -> Void
    let onClose: () -> Void
    @State private var recordToken = RecordAccess.token(Settings.apid)
    @State private var kakaoKey = Settings.kakaoNativeAppKey
    @State private var hub = Settings.hubBase
    @State private var onDevice = Settings.onDevice
    @State private var rms = Double(Settings.silenceRMS)
    @State private var hold = Settings.holdSec

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Text("닫기").foregroundStyle(AD.ink3).onTapGesture(perform: onClose)
                Spacer()
                Text("설정").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.navy)
                Spacer()
                Text("적용").font(.system(size: 16, weight: .bold)).foregroundStyle(AD.blue).onTapGesture {
                    Settings.kakaoNativeAppKey = kakaoKey
                    Settings.hubBase = hub
                    guard RecordAccess.save(recordToken, apid: Settings.apid) else { return }
                    Settings.onDevice = onDevice
                    Settings.silenceRMS = Float(rms)
                    Settings.holdSec = hold
                    onApply()
                    onClose()
                }
            }

            Card {
                VStack(alignment: .leading, spacing: 6) {
                    Text("hub").font(.system(size: 12)).foregroundStyle(AD.sub)
                    TextField("https://app.rookie-goldenlink.xyz 또는 http://<맥 IP>:5001", text: $hub)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    Text("구급대 코드: " + Settings.accessCode).font(.system(size: 13, weight: .semibold))
                    SecureField("카카오맵 네이티브 앱 키", text: $kakaoKey)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    SecureField("기록 동기화 키 (운영자 발급)", text: $recordToken)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    Text("과거 기록은 같은 구급차 ID와 동기화 키가 있어야 내려받습니다.")
                        .font(.system(size: 11)).foregroundStyle(AD.sub)
                }
            }
            Card {
                VStack(alignment: .leading, spacing: 6) {
                    HStack {
                        Text("기기 안에서 음성 인식·구조화").foregroundStyle(AD.ink)
                        Spacer(minLength: 8)
                        Toggle("", isOn: $onDevice).labelsHidden().tint(AD.blue)
                    }
                    Text("끄면 웹 전화 앱처럼 음성을 hub로 보내 중앙 voice가 처리합니다. 켜면 음성은 기기 밖으로 나가지 않고, [전송]을 누를 때 구조화된 요약만 hub로 보냅니다(공개 도메인 가능).")
                        .font(.system(size: 11.5)).foregroundStyle(AD.sub)
                }
            }
            Button("접근 코드 변경") {
                m.stop()
                Settings.accessCode = ""
                m.accessRequired = true
                onClose()
            }
            .font(.system(size: 14, weight: .semibold)).foregroundStyle(AD.blue)
            Card {
                VStack(alignment: .leading, spacing: 6) {
                    Text("무음 감지").font(.system(size: 12)).foregroundStyle(AD.sub)
                    Text("무음 기준 RMS \(rms, specifier: "%.3f")").font(.system(size: 13)).foregroundStyle(AD.ink)
                    Slider(value: $rms, in: 0.002...0.05).tint(AD.blue)
                    Text("발화 끝 \(hold, specifier: "%.1f")초").font(.system(size: 13)).foregroundStyle(AD.ink)
                    Slider(value: $hold, in: 0.2...1.5, step: 0.1).tint(AD.blue)
                }
            }
        }
        .padding(16)
        .background(AD.bg, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
    }
}

func mmss(_ sec: TimeInterval) -> String {
    let t = max(0, Int(sec))
    return String(format: "%02d:%02d", t / 60, t % 60)
}


/// 기기를 한 구급대에 연결한다. 웹 아이패드의 A-코드와 같은 hub identity를 확인한다.
struct AccessCodeEntry: View {
    let onEnter: () -> Void
    @State private var code = ""
    @State private var hub = Settings.hubBase
    @State private var checking = false
    @State private var error: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("골든링크").font(.system(size: 28, weight: .black)).foregroundStyle(AD.navy)
                Text("구급대 접근 코드").font(.title3.bold())
                Text("소속 구급대 코드를 입력하면 해당 구급대의 사건과 이송 정보를 확인합니다.")
                    .font(.subheadline).foregroundStyle(AD.sub)
                TextField("예: P-SEL0111", text: $code)
                    .textInputAutocapitalization(.characters).autocorrectionDisabled()
                    .textFieldStyle(.roundedBorder).accessibilityLabel("접근 코드")
                    .onSubmit { Task { await enter() } }
                if let error { Text(error).font(.footnote).foregroundStyle(AD.red) }
                Button { Task { await enter() } } label: {
                    Text(checking ? "구급대 확인 중…" : "입장")
                        .font(.headline).frame(maxWidth: .infinity, minHeight: 48)
                        .foregroundStyle(.white).background(AD.blue, in: RoundedRectangle(cornerRadius: 12))
                }.disabled(checking || code.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Text("시연: 역삼119안전센터 구급 1\n아이폰 P-SEL0111 · 아이패드 A-SEL0111")
                    .font(.footnote).foregroundStyle(AD.sub)
                DisclosureGroup("서버 연결 설정") {
                    TextField("hub 주소", text: $hub)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                        .textFieldStyle(.roundedBorder).padding(.top, 8)
                }.font(.subheadline)
            }.padding(24).frame(maxWidth: 480).frame(maxWidth: .infinity).padding(.top, 64)
        }.background(AD.bg.ignoresSafeArea())
    }

    @MainActor private func enter() async {
        guard !checking else { return }
        guard let id = Settings.ambulanceID(from: code) else {
            error = "P-SEL0111 형식의 구급대 접근 코드를 입력하세요."
            return
        }
        guard let base = URL(string: hub.trimmingCharacters(in: .whitespacesAndNewlines)),
              ["http", "https"].contains(base.scheme?.lowercased() ?? ""), base.host != nil,
              var url = URLComponents(url: base, resolvingAgainstBaseURL: false) else {
            error = "서버 주소를 확인하세요."; return
        }
        url.path = "/identity"
        url.queryItems = [URLQueryItem(name: "role", value: "ambulance"), URLQueryItem(name: "id", value: id)]
        guard let endpoint = url.url else { return }
        checking = true; error = nil
        defer { checking = false }
        do {
            var request = URLRequest(url: endpoint); request.timeoutInterval = 10
            let (data, response) = try await URLSession.shared.data(for: request)
            guard (response as? HTTPURLResponse)?.statusCode == 200 else { error = "서버에서 구급대를 확인하지 못했습니다."; return }
            struct IdentityCheck: Decodable { let known: Bool; let id: String }
            let identity = try JSONDecoder().decode(IdentityCheck.self, from: data)
            guard identity.known, identity.id == id else { error = "등록되지 않은 구급대 코드입니다."; return }
            Settings.hubBase = hub.trimmingCharacters(in: .whitespacesAndNewlines)
            Settings.apid = id; Settings.accessCode = "P-" + id
            onEnter()
        } catch { self.error = "서버에 연결하지 못했습니다. 네트워크와 서버 주소를 확인한 뒤 다시 시도하세요." }
    }
}

final class DeliveryShow {
    let caseId: String
    let durationMs: Double
    let reduceMotion: Bool
    var startedAt: Date?
    init(caseId: String, durationMs: Double, reduceMotion: Bool) {
        self.caseId = caseId; self.durationMs = durationMs; self.reduceMotion = reduceMotion
    }
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



/// 지도 위에 덮는 연출 — 화면을 누르면 건너뛴다
struct DeliveryOverlay: View {
    let show: DeliveryShow
    let from: CLLocationCoordinate2D
    let targets: [DeliveryTarget]
    let project: (CLLocationCoordinate2D) -> CGPoint?
    let onSkip: () -> Void

    var body: some View {
        TimelineView(.animation) { ctx in
            let t = ctx.date.timeIntervalSince(show.startedAt ?? ctx.date) * 1000
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
        .onAppear { if show.startedAt == nil { show.startedAt = Date() } }
        .contentShape(Rectangle())
        .onTapGesture(perform: onSkip)
    }
}


struct PhoneReselectList: View {
    @Environment(PhoneModel.self) private var m
    var body: some View {
        let hospitals = m.result?.hospitals ?? []
        let ready = hospitals.filter(canTransportNow)
        let skipped = m.caseId.flatMap { m.skippedHospitals[$0] } ?? []
        let all = hospitals.filter { $0.status != "rejected" && $0.excluded != true && $0.unavailableReason == nil }
        let callable = all.filter { !skipped.contains($0.hospitalId) } + all.filter { skipped.contains($0.hospitalId) }
        let deciding = m.confirmed ?? hospitals.first { $0.hospitalId == m.pendingConfirmId }
        VStack(alignment: .leading, spacing: 8) {
            if let deciding {
                HStack { ProgressView(); Text("\(deciding.name)(으)로 이송을 확정하고 있습니다") }
            } else {
                Text(ready.isEmpty ? "승인한 병원이 없습니다. 수용 불가 병원을 뺀 후보에게 다시 전화하세요" : "승인한 병원이 있습니다 — 바로 이송 승인하세요")
                    .font(.caption).foregroundStyle(AD.sub)
                ScrollView {
                    VStack(spacing: 8) {
                        ForEach(ready.isEmpty ? callable : ready, id: \.hospitalId) { h in
                            HStack {
                                VStack(alignment: .leading) {
                                    Text(h.name).font(.headline)
                                    Text(String(format: "%.1fkm", h.roadDistanceKm ?? h.distanceKm)).font(.caption)
                                    if skipped.contains(h.hospitalId) { Text("전화 미응답 이력").font(.caption).foregroundStyle(AD.orange) }
                                }
                                Spacer()
                                Button(ready.isEmpty ? "전화" : "이송 승인") {
                                    if ready.isEmpty { Task { await m.dial(hospitalId: h.hospitalId, name: h.name) } }
                                    else { m.approve(h.hospitalId) }
                                }.buttonStyle(.borderedProminent)
                                    .disabled(m.paused || m.call != nil || m.pendingConfirmId != nil)
                            }.padding(8)
                        }
                        if ready.isEmpty && callable.isEmpty { Text("전화할 수 있는 후보가 없습니다. 범위를 넓혀 다시 요청 중입니다.").font(.caption) }
                    }
                }.frame(maxHeight: 240)
            }
        }
    }
}
