import SwiftUI

/// 병원 코드는 지도 대신 이 수신 화면으로 들어온다. 두 앱 모두 화면을 켜 둔 통화부터 지원한다.
struct HospitalView: View {
    let model: HospitalModel
    let onChangeCode: () -> Void

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                Text("골든링크 · 병원").font(.headline).foregroundStyle(AD.navy)
                Text(model.hospitalName ?? Settings.hospitalID ?? "병원")
                    .font(.title.bold()).multilineTextAlignment(.center).foregroundStyle(AD.ink)
                Label(model.connection == .live ? "서버 연결됨" : "서버 연결 중…",
                      systemImage: model.connection == .live ? "checkmark.circle.fill" : "arrow.clockwise")
                    .foregroundStyle(model.connection == .live ? AD.green : AD.sub)
                Card {
                    VStack(spacing: 24) {
                        Image(systemName: model.call == nil ? "phone.fill" : "phone.connection.fill")
                            .font(.system(size: 44)).foregroundStyle(AD.blue).accessibilityHidden(true)
                        if let call = model.call {
                            Text(call.ambulanceName).font(.title2.bold()).multilineTextAlignment(.center)
                            switch call.phase {
                            case .incoming:
                                Text("전화가 왔습니다").font(.headline)
                                action(model.accepting ? "마이크 확인 중…" : "전화 받기", icon: "phone.fill", color: AD.green) { Task { await model.accept() } }
                                    .disabled(model.accepting || model.connection != .live)
                                action("거절", icon: "phone.down.fill", color: AD.red) { model.reject() }
                            case .connecting:
                                ProgressView("음성 연결 중…")
                                action("통화 종료", icon: "phone.down.fill", color: AD.red) { model.hangup() }
                            case .active:
                                Text("통화 중").font(.headline)
                                if let since = call.startedAt {
                                    Text(since, style: .timer).font(.title.monospacedDigit())
                                }
                                HStack(spacing: 16) {
                                    Button { model.toggleMute() } label: {
                                        Label(model.muted ? "음소거 해제" : "음소거", systemImage: model.muted ? "mic.slash.fill" : "mic.fill")
                                            .frame(maxWidth: .infinity, minHeight: 48)
                                    }.buttonStyle(.bordered).tint(AD.blue)
                                    Button { model.toggleSpeaker() } label: {
                                        Label(model.speaker ? "수화부" : "스피커", systemImage: "speaker.wave.2.fill")
                                            .frame(maxWidth: .infinity, minHeight: 48)
                                    }.buttonStyle(.bordered).tint(AD.blue)
                                }
                                action("통화 종료", icon: "phone.down.fill", color: AD.red) { model.hangup() }
                            }
                        } else {
                            Text("전화 수신 대기").font(.title2.bold())
                            Text("구급대가 전화하면 여기에서 받을 수 있습니다.")
                                .multilineTextAlignment(.center).foregroundStyle(AD.sub)
                        }
                    }.padding(8).frame(maxWidth: .infinity)
                }
                if let notice = model.notice { Text(notice).foregroundStyle(AD.ink).multilineTextAlignment(.center) }
                if model.call == nil {
                    Button("접근 코드 변경", action: onChangeCode).frame(minHeight: 48).foregroundStyle(AD.blue)
                }
            }.padding(24).frame(maxWidth: 520).frame(maxWidth: .infinity)
        }
        .background(AD.bg.ignoresSafeArea())
        .preferredColorScheme(.light)
        .onAppear { UIApplication.shared.isIdleTimerDisabled = true; model.start() }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false; model.stop() }
    }

    private func action(_ title: String, icon: String, color: Color, perform: @escaping () -> Void) -> some View {
        Button(action: perform) {
            Label(title, systemImage: icon).font(.headline).frame(maxWidth: .infinity, minHeight: 56)
        }.buttonStyle(.borderedProminent).tint(color)
    }
}
