import GoldenLinkCore
import SwiftUI

func navigationDistance(_ meters: Double) -> String {
    if meters < 100 { return "\(max(10, Int((meters / 10).rounded()) * 10))m" }
    if meters < 1000 { return "\(Int((meters / 50).rounded()) * 50)m" }
    return String(format: "%.1fkm", meters / 1000)
}

struct NavigationBanner: View {
    let turn: RoadRoute.Turn?
    let remainM: Double
    var body: some View {
        let angle = turn?.angleDeg ?? 0
        let side = angle > 0 ? "우" : "좌"
        let instruction = turn == nil ? "직진" : abs(angle) >= 135 ? side + "측 유턴" : abs(angle) >= 60 ? side + "회전" : side + "측 방향"
        HStack(spacing: 12) {
            Image(systemName: turn == nil ? "arrow.up" : abs(angle) >= 135 ? (angle > 0 ? "arrow.uturn.right" : "arrow.uturn.left") : (angle > 0 ? "arrow.turn.up.right" : "arrow.turn.up.left"))
                .font(.system(size: 30, weight: .bold))
            VStack(alignment: .leading, spacing: 3) {
                Text(turn.map { "\(navigationDistance($0.distanceM)) 앞 \(instruction)" } ?? "직진 · \(navigationDistance(remainM))")
                    .font(.system(size: 17, weight: .heavy)).lineLimit(1).minimumScaleFactor(0.7)
                if turn != nil { Text("목적지까지 \(navigationDistance(remainM))").font(.caption).opacity(0.7) }
            }
            Spacer(minLength: 0)
        }.foregroundStyle(.white).padding(14).background(AD.navy, in: RoundedRectangle(cornerRadius: 16))
    }
}

/// 접힌 상태에도 상태·목적지·통화 버튼을 전부 표시한다. 위로 밀면 안내/재선택 목록을 펼친다.
struct PhoneTransportSheet: View {
    @Environment(PhoneModel.self) private var m
    @Binding var expanded: Bool
    var body: some View {
        let rerouting = m.phase == .rerouting
        VStack(alignment: .leading, spacing: 10) {
            Button { withAnimation { expanded.toggle() } } label: {
                Capsule().fill(AD.control).frame(width: 36, height: 4)
                    .frame(maxWidth: .infinity, minHeight: 44)
            }.buttonStyle(.plain).accessibilityLabel(expanded ? "병원 안내 접기" : "병원 안내 펼치기")
                .gesture(DragGesture().onEnded { value in withAnimation { expanded = value.translation.height < 0 } })
            HStack {
                Pill(text: rerouting ? "재선택 대기" : "병원 이송 중", fg: rerouting ? AD.red : AD.blue, bg: rerouting ? AD.redSoft : AD.blueSoft, bold: true)
                if m.transportHeld { Text("통화 내용 반영 중 · 이송 잠시 멈춤").font(.caption).foregroundStyle(AD.blue) }
                else if !rerouting, let eta = m.mySim?.etaSec { Text("도착까지 약 \(max(1, Int(ceil(eta / 60))))분").font(.caption).foregroundStyle(AD.sub) }
            }
            if rerouting { Text("목적지 병원이 수용할 수 없게 됐습니다").font(.headline).foregroundStyle(AD.navy) }
            else {
                HStack(spacing: 12) {
                    VStack(alignment: .leading) {
                        Text("목적지 병원").font(.caption).foregroundStyle(AD.sub)
                        Text(m.destination?.name ?? "확정 병원").font(.system(size: 20, weight: .heavy)).foregroundStyle(AD.navy).lineLimit(1).minimumScaleFactor(0.7)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                    Button { Task { if let d = m.destination { await m.dial(hospitalId: d.hospitalId, name: d.name) } } } label: {
                        Label("통화", systemImage: "phone.fill").font(.headline).foregroundStyle(.white)
                            .padding(.horizontal, 16).frame(minHeight: 46).background(AD.green, in: RoundedRectangle(cornerRadius: 14))
                    }.disabled(m.destination == nil || m.transportCallBlocked || m.paused || m.call != nil)
                }
            }
            if expanded {
                if rerouting { PhoneReselectList() }
                else {
                    Text("이송 중 환자 상태가 바뀌면 목적지 병원과 통화하세요. 통화 내용은 환자 정보에 덧붙어 병원 화면에 바로 반영됩니다.").font(.subheadline).foregroundStyle(AD.ink3)
                    if m.transportCallBlocked {
                        Label("시연 콘솔에서 ‘음성으로 통화’를 선택하면 전화할 수 있습니다.", systemImage: "lock.fill")
                            .font(.subheadline).foregroundStyle(AD.orange).padding(10).background(AD.orangeSoft, in: RoundedRectangle(cornerRadius: 12))
                    }
                }
            }
        }
        .onAppear { if rerouting { expanded = true } }
        .onChange(of: rerouting) { _, value in if value { withAnimation { expanded = true } } }
    }
}
