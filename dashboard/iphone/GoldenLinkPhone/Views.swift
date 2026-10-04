import GoldenLinkCore
import SwiftUI

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

    var body: some View {
        VStack(spacing: 10) {
            header
            content.frame(maxWidth: .infinity, maxHeight: .infinity)
            footer
        }
        .padding(.horizontal, 16)
        .padding(.top, 6)
        .background(AD.bg.ignoresSafeArea())
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
        .sheet(isPresented: $showSettings) { SettingsView { m.start() } }
        .alert("알림", isPresented: .constant(m.error != nil)) { Button("확인") { m.error = nil } } message: { Text(m.error ?? "") }
    }

    // 상단: 로고 · 버전 · 구급대 | 연결 · 설정
    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                (Text("골든").foregroundStyle(AD.navy) + Text("링크").foregroundStyle(AD.blue))
                    .font(.system(size: 19, weight: .black))
                Pill(text: "v2.0", fg: AD.blue, bg: AD.blueSoft, bold: true)
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
            HStack(spacing: 6) {
                Pill(text: m.identity?.name ?? m.apid ?? (m.autoFollow ? "자동 전환 대기" : "구급대 미지정"), fg: AD.ink3, bg: .white, bold: true)
                if let phase = m.mySim?.phase {
                    Pill(text: phase.label, fg: phaseColor(phase), bg: phaseColor(phase).opacity(0.12), bold: true)
                }
                Spacer(minLength: 0)
                Text("전화 앱").font(.system(size: 11, weight: .medium)).foregroundStyle(AD.muted)
            }
        }
        .padding(.horizontal, 14).padding(.vertical, 10)
        .background(.white, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).strokeBorder(AD.line))
    }

    // 하단: 출처 범례 + 모델 상태
    private var footer: some View {
        VStack(spacing: 4) {
            HStack(spacing: 12) {
                Label { Text("AI 처리") } icon: { Dot(color: AD.blue) }
                Label { Text("규칙 기반 · API") } icon: { Dot(color: AD.gray) }
                Label { Text("판단은 사람") } icon: { Dot(color: AD.orange) }
            }
            .font(.system(size: 10.5))
            .foregroundStyle(AD.ink3)
            if !m.modelStatus.isEmpty {
                Text(m.modelStatus).font(.system(size: 10.5)).foregroundStyle(AD.muted).lineLimit(1)
            }
        }
        .padding(.bottom, 4)
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
        } else if m.onScene {
            if m.sent && !m.wantsExtraCall {
                SentView()
            } else {
                HospitalListView()
            }
        } else if m.inTransport {
            TransportCallView()
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
        } else {
            let phase = m.mySim?.phase ?? .idle
            let eta = m.mySim?.etaSec.map { max(1, Int(($0 / 60).rounded(.up))) }
            StatusPanel(icon: phase == .dispatching ? "light.beacon.max.fill" : "car.fill", tint: phaseColor(phase),
                        title: phase.label, pulse: phase == .dispatching,
                        detail: (phase == .dispatching && eta != nil ? "현장까지 약 \(eta!)분 (실제 도로 기준)\n" : "")
                            + "현장에 도착하면 전화할 병원 목록이 여기에 뜹니다. 출동은 구급차 대시보드에서 합니다.")
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

// MARK: - 병원 목록 (현장 도착 뒤)

struct HospitalListView: View {
    @Environment(PhoneModel.self) private var m

    var body: some View {
        // 추천 병원을 맨 위로, 나머지는 hub가 보낸 도착 시간순 그대로
        let all = m.scene?.hospitals ?? []
        let ordered = all.filter { $0.firstCallRecommended == true } + all.filter { $0.firstCallRecommended != true }
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 10) {
                VStack(alignment: .leading, spacing: 2) {
                    HStack(alignment: .firstTextBaseline, spacing: 8) {
                        Text("전화할 병원").font(.system(size: 17, weight: .bold)).foregroundStyle(AD.navy)
                        Text("도착 시간순 · \(all.count)곳").font(.system(size: 12)).foregroundStyle(AD.ink3)
                        Spacer()
                        Pill(text: "규칙 기반", fg: AD.ink3, bg: AD.chip)
                    }
                    Text(m.wantsExtraCall
                         ? "추가 통화 — 바뀐 환자 상태를 말하면 기존 환자 정보에 덧붙여 후보 병원에 다시 전달됩니다."
                         : "한 곳과 통화하면 그 내용이 후보 병원 전체에 동시에 전달됩니다.")
                        .font(.system(size: 11.5)).foregroundStyle(AD.sub)
                    if m.wantsExtraCall {
                        Button("추가 통화 닫기") { m.wantsExtraCall = false }
                            .font(.system(size: 12, weight: .bold)).tint(AD.ink3).padding(.top, 2)
                    }
                }
                .padding(.horizontal, 4)

                if let symptom = m.scene?.reportedSymptom {
                    HStack(spacing: 8) {
                        Image(systemName: "phone.arrow.down.left").foregroundStyle(AD.orange)
                        Text("신고 내용: ").foregroundStyle(AD.ink3) + Text(symptom).bold().foregroundStyle(AD.navy)
                        Spacer(minLength: 0)
                        Text("현장과 다를 수 있음").font(.system(size: 10.5)).foregroundStyle(AD.muted)
                    }
                    .font(.system(size: 13))
                    .padding(.horizontal, 12).padding(.vertical, 9)
                    .background(AD.orangeSoft, in: RoundedRectangle(cornerRadius: 12, style: .continuous))
                }

                ForEach(ordered) { h in
                    HospitalCard(h: h) { Task { await m.dial(h) } }
                }
            }
            .padding(.bottom, 8)
        }
        .scrollIndicators(.hidden)
        .overlay {
            if all.isEmpty {
                VStack(spacing: 10) {
                    ProgressView().tint(AD.blue)
                    Text("병원 목록을 받는 중…").font(.system(size: 13)).foregroundStyle(AD.sub)
                }
            }
        }
    }
}

struct HospitalCard: View {
    let h: SceneCandidate
    let onCall: () -> Void

    var body: some View {
        let recommended = h.firstCallRecommended == true
        Card(border: recommended ? AD.green : AD.control, borderWidth: recommended ? 2 : 1) {
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top, spacing: 8) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(h.name).font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy)
                            .lineLimit(2).fixedSize(horizontal: false, vertical: true)
                        Text(distanceText).font(.system(size: 12)).foregroundStyle(AD.ink3)
                    }
                    Spacer(minLength: 4)
                    if recommended {
                        Pill(text: "첫 연락 추천", fg: AD.green, bg: AD.greenSoft, bold: true)
                    } else {
                        Pill(text: "통화 전", fg: AD.ink3, bg: AD.chip, bold: true)
                    }
                }

                HStack(spacing: 8) {
                    bedBox
                    validBox
                    StatBox(label: "전문의", value: doctors > 0 ? "\(doctors)명" : "—", fg: AD.ink3, bg: AD.chip, valueColor: AD.navy)
                }

                if h.emergencyLevel != nil || !(h.specialties ?? []).isEmpty {
                    ScrollView(.horizontal) {
                        HStack(spacing: 6) {
                            if let level = h.emergencyLevel, level.hasSuffix("센터") {
                                Pill(text: level, fg: AD.ink3, bg: AD.chip)
                            }
                            ForEach(Array((h.specialties ?? []).prefix(4).enumerated()), id: \.offset) { _, s in
                                Pill(text: "\(s.department) \(s.doctorCount)", fg: AD.blue, bg: AD.blueSoft)
                            }
                        }
                    }
                    .scrollIndicators(.hidden)
                }

                Button(action: onCall) {
                    HStack(spacing: 8) {
                        Image(systemName: "phone.fill")
                        Text("전화 걸기").fontWeight(.bold)
                    }
                    .font(.system(size: 15))
                    .frame(maxWidth: .infinity, minHeight: 46)
                    .foregroundStyle(.white)
                    .background(recommended ? AD.green : AD.blue, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                }
                .buttonStyle(.plain)
            }
        }
    }

    private var distanceText: String {
        let km = h.roadDistanceKm ?? h.distanceKm
        let dist = h.roadDistanceKm != nil ? String(format: "%.1fkm", km) : String(format: "직선 %.1fkm", km)
        if let eta = h.etaMin { return "\(dist) · ETA \(Int(eta.rounded()))분" }
        return dist
    }

    private var doctors: Int { (h.specialties ?? []).reduce(0) { $0 + $1.doctorCount } }

    // 미상을 0이나 "없음"으로 보이면 안 된다(대시보드와 같은 원칙) — 미상은 회색, 확인된 만실만 빨강
    @ViewBuilder private var bedBox: some View {
        if h.bedCountUnknown {
            StatBox(label: "병상", value: "미상", fg: AD.ink3, bg: AD.chip)
        } else if h.availableBedCount <= 0 {
            StatBox(label: "병상", value: "없음", fg: AD.red, bg: AD.redSoft)
        } else {
            StatBox(label: "병상", value: "\(h.availableBedCount)석", fg: AD.lime, bg: AD.limeSoft)
        }
    }

    // 도착 시 유효 확률(AI) — ≥80% 파랑, 50~80% 회색, <50% 빨강
    @ViewBuilder private var validBox: some View {
        if let p = h.bedReliability?.rArrive {
            let pct = Int((p * 100).rounded())
            let (fg, bg): (Color, Color) = p >= 0.8 ? (AD.blue, AD.blueSoft) : p >= 0.5 ? (AD.ink3, AD.chip) : (AD.red, AD.redSoft)
            StatBox(label: "AI 유효", value: "\(pct)%", fg: fg, bg: bg)
        } else {
            StatBox(label: "AI 유효", value: "—", fg: AD.ink3, bg: AD.chip)
        }
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
                    TimelineView(.periodic(from: .now, by: 1)) { ctx in
                        Text(connecting ? "응급실 연결 중" : mmss(ctx.date.timeIntervalSince(call.startedAt)))
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
                                    Text(connecting ? "곧 연결됩니다." : "말이 끊길 때마다 인식된 문장이 여기에 뜹니다.")
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

            // [취소]는 아무것도 보내지 않고, [전송]을 눌러야만 음성을 처리해 병원에 보낸다(2026-10-05)
            HStack(spacing: 10) {
                Button { m.cancelCall() } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "xmark").font(.system(size: 17, weight: .bold))
                        Text("취소").font(.system(size: 16, weight: .bold))
                    }
                    .frame(maxWidth: .infinity, minHeight: 56)
                    .foregroundStyle(AD.red)
                    .background(.white, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(AD.red, lineWidth: 2))
                }
                .buttonStyle(.plain)
                Button { m.sendCall() } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "paperplane.fill").font(.system(size: 17, weight: .bold))
                        Text("전송").font(.system(size: 16, weight: .bold))
                    }
                    .frame(maxWidth: .infinity, minHeight: 56)
                    .foregroundStyle(.white)
                    .background(connecting ? AD.control : AD.blue, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                }
                .buttonStyle(.plain)
                .disabled(connecting)
                .layoutPriority(1)
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
            Card(border: sent != nil ? AD.green : AD.line, borderWidth: sent != nil ? 2 : 1) {
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 10) {
                        Image(systemName: sent != nil ? "checkmark.circle.fill" : "waveform")
                            .font(.system(size: 26, weight: .semibold))
                            .foregroundStyle(sent != nil ? AD.green : AD.blue)
                            .symbolEffect(.pulse, isActive: sent == nil)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(sent.map { followup ? "환자 정보에 덧붙여 \($0)곳에 전달됐습니다" : "후보 병원 \($0)곳에 전달됐습니다" }
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
                    if finished {
                        Button { m.dismissEnded() } label: {
                            Text(sent != nil ? "확인" : "확인 · 다시 걸기")
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

// MARK: - 현장: 전달됨 · 추가 통화

struct SentView: View {
    @Environment(PhoneModel.self) private var m

    var body: some View {
        let n = m.caseId.flatMap { m.sentCount[$0] } ?? 0
        VStack(spacing: 12) {
            Spacer(minLength: 0)
            Card(border: AD.green, borderWidth: 2) {
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 10) {
                        Image(systemName: "checkmark.circle.fill").font(.system(size: 26, weight: .semibold)).foregroundStyle(AD.green)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("후보 병원 \(n)곳에 전달됐습니다").font(.system(size: 17, weight: .bold)).foregroundStyle(AD.navy)
                            Text("병원 응답 확인·이송 승인은 구급차 대시보드에서 합니다").font(.system(size: 12)).foregroundStyle(AD.sub)
                        }
                    }
                    Divider().overlay(AD.line)
                    Text("환자 상태가 바뀌었으면 다시 통화하세요. 새 통화 내용은 기존 환자 정보에 덧붙여 전달됩니다.")
                        .font(.system(size: 12.5)).foregroundStyle(AD.ink3).fixedSize(horizontal: false, vertical: true)
                    Button { m.wantsExtraCall = true } label: {
                        HStack(spacing: 8) {
                            Image(systemName: "phone.badge.plus")
                            Text("추가 통화").fontWeight(.bold)
                        }
                        .font(.system(size: 15))
                        .frame(maxWidth: .infinity, minHeight: 46)
                        .foregroundStyle(AD.blue)
                        .background(AD.blueSoft, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    .buttonStyle(.plain)
                }
            }
            Spacer(minLength: 0)
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
                        if !rerouting, let eta { Text("도착까지 약 \(eta)분").font(.system(size: 12)).foregroundStyle(AD.sub) }
                    }
                    if rerouting {
                        Text("목적지 병원이 수용할 수 없게 됐습니다").font(.system(size: 18, weight: .bold)).foregroundStyle(AD.navy)
                        Text("구급차 대시보드에서 승인한 다른 병원을 이송 승인하세요. 승인 병원이 없으면 범위를 넓혀 다시 요청합니다.")
                            .font(.system(size: 12.5)).foregroundStyle(AD.ink3).fixedSize(horizontal: false, vertical: true)
                    } else {
                        VStack(alignment: .leading, spacing: 2) {
                            Text("목적지 병원").font(.system(size: 11.5)).foregroundStyle(AD.sub)
                            Text(dest?.name ?? "확정 병원").font(.system(size: 20, weight: .black)).foregroundStyle(AD.navy)
                        }
                        Text("이송 중 환자 상태가 바뀌면 목적지 병원과 통화하세요. 통화 내용은 환자 정보에 덧붙어 병원 화면에 바로 반영됩니다.")
                            .font(.system(size: 12.5)).foregroundStyle(AD.ink3).fixedSize(horizontal: false, vertical: true)
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

// MARK: - 설정

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    let onApply: () -> Void
    @State private var hub = Settings.hubBase
    @State private var apid = Settings.apid
    @State private var onDevice = Settings.onDevice
    @State private var rms = Double(Settings.silenceRMS)
    @State private var hold = Settings.holdSec

    var body: some View {
        NavigationStack {
            Form {
                Section("hub") {
                    TextField("https://app.rookie-goldenlink.xyz 또는 http://<맥 IP>:5001", text: $hub)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField("구급차 ID (SEL0001 또는 auto)", text: $apid).textInputAutocapitalization(.characters)
                }
                Section {
                    Toggle("기기 안에서 음성 인식·구조화", isOn: $onDevice).tint(AD.blue)
                } footer: {
                    Text("끄면 웹 전화 앱처럼 음성을 hub로 보내 중앙 voice가 처리합니다. 켜면 음성은 기기 밖으로 나가지 않고, [전송]을 누를 때 구조화된 요약만 hub로 보냅니다(공개 도메인 가능).")
                }
                Section("무음 감지") {
                    LabeledContent("무음 기준 RMS \(rms, specifier: "%.3f")") { Slider(value: $rms, in: 0.002...0.05).tint(AD.blue) }
                    LabeledContent("발화 끝 \(hold, specifier: "%.1f")초") { Slider(value: $hold, in: 0.2...1.5, step: 0.1).tint(AD.blue) }
                }
            }
            .scrollContentBackground(.hidden)
            .background(AD.bg)
            .navigationTitle("설정")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("적용") {
                        Settings.hubBase = hub
                        Settings.apid = apid.trimmingCharacters(in: .whitespaces).isEmpty ? "auto" : apid
                        Settings.onDevice = onDevice
                        Settings.silenceRMS = Float(rms)
                        Settings.holdSec = hold
                        onApply()
                        dismiss()
                    }
                    .fontWeight(.bold)
                    .tint(AD.blue)
                }
                ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() }.tint(AD.ink3) }
            }
        }
    }
}

func mmss(_ sec: TimeInterval) -> String {
    let t = max(0, Int(sec))
    return String(format: "%02d:%02d", t / 60, t % 60)
}
