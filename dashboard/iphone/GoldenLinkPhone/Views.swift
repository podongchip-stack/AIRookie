import GoldenLinkCore
import SwiftUI

/// PhoneCallView.tsx와 같은 화면 순서: 통화 중 > 종료 > 다른 기기 통화 중 > 이미 전달됨 > 대기/출동 > 병원 목록
struct ContentView: View {
    @Environment(PhoneModel.self) private var m
    @State private var showSettings = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                content.frame(maxWidth: .infinity, maxHeight: .infinity)
                Text(m.modelStatus).font(.caption2).foregroundStyle(.secondary).padding(.bottom, 4)
            }
            .navigationTitle(m.identity?.name ?? m.apid ?? "골든링크")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) { ConnectionDot(state: m.connection) }
                ToolbarItem(placement: .topBarTrailing) {
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                        .disabled(m.call != nil && m.call?.phase != .ended)
                }
            }
            .sheet(isPresented: $showSettings) { SettingsView { m.start() } }
            .alert("알림", isPresented: .constant(m.error != nil)) { Button("확인") { m.error = nil } } message: { Text(m.error ?? "") }
        }
    }

    @ViewBuilder private var content: some View {
        if let call = m.call, call.phase != .ended {
            InCallView(call: call)
        } else if m.call?.phase == .ended || m.status?.state == "ended" {
            EndedView()
        } else if let s = m.status, s.state == "calling" {
            StatusPanel(icon: "phone.fill", title: "\(s.device == "phone" ? "다른 휴대폰" : "구급차 대시보드")에서 통화 중",
                        detail: "\(s.hospitalName ?? "병원")과 통화하고 있습니다. 통화는 사건마다 한 번만 합니다.")
        } else if let c = m.caseId, m.status == nil, let n = m.sentCount[c] {
            StatusPanel(icon: "checkmark.circle.fill", title: "후보 병원 \(n)곳에 전달됐습니다",
                        detail: "이 사건은 통화 없이 환자 정보가 나갔습니다. 병원 응답 확인·이송 승인은 구급차 대시보드에서 하세요.")
        } else if !m.onScene {
            waiting
        } else {
            HospitalListView()
        }
    }

    @ViewBuilder private var waiting: some View {
        if m.apid == nil {
            StatusPanel(icon: "phone", title: "출동 대기 중", detail: "상황이 발생하면 출동하는 구급대의 전화 앱으로 자동 전환됩니다.")
        } else if m.identity != nil && !m.simOn {
            StatusPanel(icon: "car", title: "출동 시뮬레이션이 꺼져 있습니다", detail: "휴대폰 전화 앱은 출동 시뮬레이션에서만 씁니다.")
        } else {
            let phase = m.mySim?.phase ?? .idle
            StatusPanel(icon: "car.fill", title: phase.label, pulse: phase == .dispatching,
                        detail: "현장에 도착하면 전화할 병원 목록이 여기에 뜹니다. 출동은 구급차 대시보드에서 하세요.")
        }
    }
}

struct HospitalListView: View {
    @Environment(PhoneModel.self) private var m

    var body: some View {
        // 추천 병원을 맨 위로, 나머지는 hub가 보낸 도착 시간순 그대로
        let all = m.scene?.hospitals ?? []
        let ordered = all.filter { $0.firstCallRecommended == true } + all.filter { $0.firstCallRecommended != true }
        List {
            if let symptom = m.scene?.reportedSymptom {
                Label("신고: \(symptom)", systemImage: "phone.arrow.down.left").font(.subheadline)
            }
            Section {
                ForEach(ordered) { h in
                    Button { Task { await m.dial(h) } } label: { HospitalRow(h: h) }
                }
            } header: {
                Text("전화할 병원 · 도착 시간순").badge(Text("규칙 기반"))
            }
        }
        .overlay { if all.isEmpty { ProgressView("병원 목록을 받는 중…") } }
    }
}

struct HospitalRow: View {
    let h: SceneCandidate

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                if h.firstCallRecommended == true {
                    Text("첫 연락 추천").font(.caption2.bold()).padding(.horizontal, 6).padding(.vertical, 2)
                        .background(.green.opacity(0.2), in: Capsule())
                }
                Text(h.name).font(.headline).foregroundStyle(.primary)
                if let level = h.emergencyLevel { Text(level).font(.caption2).foregroundStyle(.secondary) }
            }
            HStack(spacing: 12) {
                Text(h.etaMin.map { "\(Int($0.rounded()))분" } ?? String(format: "%.1fkm(직선)", h.distanceKm))
                Text(h.bedCountUnknown ? "병상 미상" : "병상 \(h.availableBedCount)")  // 미상을 0으로 보이면 안 된다
                if let p = h.bedReliability?.rArrive {
                    Text("도착 시 유효 \(Int((p * 100).rounded()))% · AI").foregroundStyle(.blue)
                }
            }
            .font(.subheadline).foregroundStyle(.secondary)
            if let sp = h.specialties, !sp.isEmpty {
                Text(sp.prefix(4).map { "\($0.department) \($0.doctorCount)" }.joined(separator: " · "))
                    .font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
        }
        .padding(.vertical, 2)
    }
}

struct InCallView: View {
    @Environment(PhoneModel.self) private var m
    let call: PhoneModel.LocalCall

    var body: some View {
        let connecting = call.phase == .connecting
        VStack(spacing: 16) {
            Text(connecting ? "연결 중…" : "통화 중 · 음성 인식").font(.caption.bold())
                .foregroundStyle(connecting ? .orange : .red)
            Text(call.hospitalName).font(.title2.bold())
            TimelineView(.periodic(from: .now, by: 1)) { ctx in
                Text(connecting ? "응급실 연결 중" : mmss(ctx.date.timeIntervalSince(call.startedAt)))
                    .font(.title3.monospacedDigit()).foregroundStyle(.secondary)
            }
            let _ = m.tick  // CallSession(관찰 대상 아님)의 레벨·자막이 바뀌면 tick이 올라 다시 그린다
            let level = CGFloat(m.session?.level ?? 0)
            Capsule().fill(.red.opacity(0.6)).frame(width: 40 + 200 * level, height: 6).animation(.easeOut(duration: 0.1), value: level)
            ScrollViewReader { proxy in
                ScrollView {
                    VStack(alignment: .leading, spacing: 8) {
                        if m.transcriptLines.isEmpty {
                            Text(connecting ? "곧 연결됩니다." : "말이 끊길 때마다\n인식된 문장이 여기에 뜹니다.")
                                .foregroundStyle(.secondary).frame(maxWidth: .infinity)
                        }
                        ForEach(Array(m.transcriptLines.enumerated()), id: \.offset) { i, line in Text(line).id(i) }
                    }
                    .padding()
                }
                .onChange(of: m.transcriptLines.count) { _, n in proxy.scrollTo(n - 1) }
            }
            .background(.gray.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
            Text("실시간 자막 · AI(Qwen3-ASR)").font(.caption2).foregroundStyle(.secondary)
            Button(role: .destructive) { m.hangUp() } label: {
                Image(systemName: "phone.down.fill").font(.title).frame(width: 72, height: 72)
                    .background(.red, in: Circle()).foregroundStyle(.white)
            }
        }
        .padding()
    }
}

struct EndedView: View {
    @Environment(PhoneModel.self) private var m

    var body: some View {
        let _ = m.tick
        let sent = m.caseId.flatMap { m.sentCount[$0] }
        let stage = m.session?.stage
        VStack(spacing: 12) {
            StatusPanel(icon: "checkmark.circle.fill", title: sent.map { "후보 병원 \($0)곳에 전달됐습니다" } ?? stageTitle(stage),
                        pulse: sent == nil,
                        detail: "통화: \(m.call?.hospitalName ?? m.status?.hospitalName ?? "병원")\n병원 응답 확인·이송 승인은 구급차 대시보드에서")
            if case let .failed(reason)? = stage { Text(reason).font(.footnote).foregroundStyle(.red).padding(.horizontal) }
        }
    }

    private func stageTitle(_ s: CallSession.Stage?) -> String {
        switch s {
        case .finishing?: "남은 음성을 인식하는 중…"
        case .structuring?: "환자 정보를 구조화하는 중…(MF_BERT)"
        case .noSpeech?: "인식된 말이 없어 전달하지 않았습니다"
        case .failed?: "전달하지 못했습니다"
        default: "환자 정보를 정리하는 중…"
        }
    }
}

struct StatusPanel: View {
    let icon: String
    let title: String
    var pulse = false
    let detail: String

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: icon).font(.system(size: 40)).symbolEffect(.pulse, isActive: pulse)
            Text(title).font(.title3.bold()).multilineTextAlignment(.center)
            Text(detail).font(.subheadline).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .padding(24)
    }
}

struct ConnectionDot: View {
    let state: HubSocket.State
    var body: some View {
        let (color, text): (Color, String) = switch state {
        case .live: (.green, "연결됨")
        case .connecting: (.gray, "연결 중")
        case .reconnecting: (.red, "재연결 중")
        }
        Label { Text(text).font(.caption) } icon: { Circle().fill(color).frame(width: 8, height: 8) }
    }
}

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
                    TextField("http://<맥 IP>:5001", text: $hub).textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField("구급차 ID (SEL0001 또는 auto)", text: $apid).textInputAutocapitalization(.characters)
                }
                Section {
                    Toggle("기기 안에서 음성 인식·구조화", isOn: $onDevice)
                } footer: {
                    Text("끄면 웹 전화 앱처럼 음성을 hub로 보내 중앙 voice가 처리합니다. 켜면 음성은 기기 밖으로 나가지 않고 /voice/utterance·/voice/summary만 보냅니다(공개 도메인에선 404 — 로컬 모드 필요).")
                }
                Section("무음 감지") {
                    LabeledContent("무음 기준 RMS \(rms, specifier: "%.3f")") { Slider(value: $rms, in: 0.002...0.05) }
                    LabeledContent("발화 끝 \(hold, specifier: "%.1f")초") { Slider(value: $hold, in: 0.2...1.5, step: 0.1) }
                }
            }
            .navigationTitle("설정")
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
                }
                ToolbarItem(placement: .cancellationAction) { Button("닫기") { dismiss() } }
            }
        }
    }
}

func mmss(_ sec: TimeInterval) -> String {
    let t = max(0, Int(sec))
    return String(format: "%02d:%02d", t / 60, t % 60)
}
