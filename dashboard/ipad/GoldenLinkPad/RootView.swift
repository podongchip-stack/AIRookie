import SwiftUI

/// 구급차 대시보드(웹 /ambulance 시안)와 같은 배치 — 상단바 → 두 화면.
/// 상단바의 **[환자 정보 | 이송]**(2026-10-27)으로 화면을 바꾼다:
///  · [환자 정보] = 왼쪽 통화 요약·구조화 + 추가 정보, 오른쪽 **외상 부위 그림**(BodyInjuryCard)
///  · [이송] = 왼쪽 병원 리스트(n×1), 병원을 누르면 오른쪽에 그 병원 배후역량표(TransportScreen)
/// 자동 전환: 음성 요약이 처음 도착하면 [환자 정보]로, 이송이 확정되면(hub 응답) [이송]으로(AppModel.requestScreen).
/// 상단바의 [정보 생존 모델]은 같은 화면 위에 전체 화면으로 덮는다.
enum Screen: String { case patient, transport }

struct RootView: View {
    @EnvironmentObject private var model: AppModel
    @AppStorage("screen") private var screenRaw = Screen.patient.rawValue
    @State private var showSettings = false
    @State private var showSurvival = false
    private var screen: Screen { Screen(rawValue: screenRaw) ?? .patient }

    var body: some View {
        ZStack(alignment: .top) {
            AD.bg.ignoresSafeArea()
            VStack(spacing: 8) {
                TopBar(showSurvival: $showSurvival, showSettings: $showSettings, screenRaw: $screenRaw)
                callBanner
                if !model.hasIncident {
                    // 출동도 사건도 전혀 없는 평상시(2026-10-29) — 탭을 골라도 보여줄 게 없으니 대기 화면 하나로 통일
                    IdleWaitingCard()
                } else if screen == .transport {
                    TransportScreen()
                } else if let hold = stageHold {
                    // 현장으로 가는 중·현장 확인 중엔 아직 채울 환자 정보가 없다(2026-10-28) —
                    // 빈 서식을 보여주지 않고 지금 뭘 하는 단계인지만 크게 띄운다
                    StageHoldCard(hold: hold)
                } else {
                    // [환자 정보] — 왼쪽은 예전과 같은 통화 요약·구조화(+추가 정보), 오른쪽은 외상 부위 그림
                    GeometryReader { g in
                        HStack(alignment: .top, spacing: 14) {
                            // 통화 요약 칸은 사건이 없어도 자리에 둔다(2026-10-27) — 통화가 시작되면 바로 채워진다.
                            // 인계확인서는 사건이 생긴 뒤에만(채울 값이 없으면 빈 서식만 남는다)
                            VStack(spacing: 8) {
                                CallSummaryCard(fill: !model.hasIncident,
                                                fitMax: model.hasIncident ? g.size.height * 0.45 : nil)
                                if model.hasIncident { HandoverCard() }
                            }
                            .frame(width: g.size.width >= 1000 ? 360 : 320, height: g.size.height)
                            BodyInjuryCard()
                        }
                    }
                }
            }
            .padding(.horizontal, 16).padding(.vertical, 10)

            if let n = model.notice {
                Text(n).font(.system(size: 14, weight: .bold)).foregroundStyle(.white)
                    .padding(.horizontal, 18).padding(.vertical, 10)
                    .background(AD.navy.opacity(0.92)).clipShape(Capsule())
                    .padding(.top, 70)
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.2), value: model.notice)
        .sheet(isPresented: $showSettings) { SettingsView().environmentObject(model) }
        .fullScreenCover(isPresented: $showSurvival) { SurvivalModelScreen(isPresented: $showSurvival).environmentObject(model) }
        // 앱을 켜면 [환자 정보]부터 — 이송이 확정되면 [이송]으로 자동으로 넘어간다
        .onAppear { screenRaw = Screen.patient.rawValue; model.start() }
        // 자동 전환: 음성 요약 첫 도착 → 환자 정보 → 이송 확정 → 이송. 언제든 상단바로 직접 바꿀 수 있다
        .onReceive(NotificationCenter.default.publisher(for: .switchScreen)) { n in
            guard let raw = n.userInfo?["screen"] as? String else { return }
            withAnimation(.easeInOut(duration: 0.25)) { screenRaw = raw }
        }
    }

    /// 환자 정보를 보여줄 수 없는 단계 — (제목, 설명, 아이콘, 색)
    private var stageHold: (String, String, String, Color)? {
        guard let phase = model.sim?.phase, model.result == nil else { return nil }
        switch phase {
        case "dispatching":
            return ("현장으로 이송 중", "사고 현장으로 이동하고 있습니다. 현장에 도착하면 상황 판단으로 넘어갑니다.", "arrow.triangle.turn.up.right.diamond.fill", AD.blue)
        case "on_scene":
            let calling = model.callStatus?.state == "calling"
            return ("상황 판단 중",
                    calling ? "통화 내용을 받아 환자 정보를 구조화하고 있습니다." : "현장 확인 중입니다. 통화가 요약되면 환자 정보가 올라옵니다.",
                    "stethoscope", AD.orange)
        default: return nil
        }
    }

    @ViewBuilder private var callBanner: some View {
        if let call = model.callStatus, call.state == "calling" {
            Text("휴대폰으로 \(call.hospitalName ?? "병원")과 통화 중 — 통화가 끝나면 환자 정보가 후보 병원에 동시에 전달됩니다")
                .font(.system(size: 13, weight: .bold)).foregroundStyle(AD.green)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 16).padding(.vertical, 8)
                .background(AD.greenSoft).clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }
}

/// 사건·출동이 전혀 없는 평상시 대기 화면(2026-10-29) — StageHoldCard와 같은 모양
struct IdleWaitingCard: View {
    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: "cross.case.fill").font(.system(size: 54, weight: .semibold)).foregroundStyle(AD.muted)
            Text("출동 대기 중").font(.system(size: 30, weight: .black)).foregroundStyle(AD.navy)
            Text("새 사건이 들어오면 자동으로 환자 정보 화면으로 넘어갑니다.").font(.system(size: 15)).foregroundStyle(AD.sub)
                .multilineTextAlignment(.center)
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AD.card).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.line, lineWidth: 1))
    }
}

/// 환자 정보 자리에 들어가는 단계 안내 — 출동 중 / 상황 판단 중
struct StageHoldCard: View {
    let hold: (String, String, String, Color)

    var body: some View {
        VStack(spacing: 14) {
            Image(systemName: hold.2).font(.system(size: 54, weight: .semibold)).foregroundStyle(hold.3)
            Text(hold.0).font(.system(size: 30, weight: .black)).foregroundStyle(AD.navy)
            Text(hold.1).font(.system(size: 15)).foregroundStyle(AD.sub).multilineTextAlignment(.center)
        }
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AD.card).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.line, lineWidth: 1))
    }
}

/// 상단바 — 로고 · 버전 · 구급대 이름 | 정보 생존 모델 · 이송 상태 · 연결 · 경과 · 설정 (웹 AmbulanceTopBar)
struct TopBar: View {
    @EnvironmentObject private var model: AppModel
    @Binding var showSurvival: Bool
    @Binding var showSettings: Bool
    @Binding var screenRaw: String

    var body: some View {
        HStack(spacing: 14) {
            HStack(spacing: 10) {
                (Text("골든").foregroundStyle(AD.navy) + Text("링크").foregroundStyle(AD.blue))
                    .font(.system(size: 20, weight: .black)).fixedSize()
                Pill(text: ambulanceLabel, bg: AD.chip, fg: AD.ink3, bold: true)
            }
            // 환자 정보 · 이송 — 진행 순서대로
            screenSwitch
            Spacer(minLength: 8)
            connectionView
            if let at = model.receivedAt {
                (Text("수신 후 ") + Text(Labels.elapsed(model.now.timeIntervalSince(at))).bold().foregroundColor(AD.navy) + Text(" 경과"))
                    .font(.system(size: 12)).foregroundStyle(AD.sub)
            }
            statusView          // 이송 상태는 [정보 생존 모델] 바로 왼쪽(2026-10-27)
            Button { showSurvival = true } label: {
                Text("정보 생존 모델").font(.system(size: 13, weight: .bold)).foregroundStyle(.white)
                    .padding(.horizontal, 16).frame(minHeight: 36).background(AD.blue).clipShape(Capsule())
            }
            Button { NotificationCenter.default.post(name: .spiderReload, object: nil) } label: {
                Image(systemName: "arrow.clockwise").font(.system(size: 15, weight: .semibold)).foregroundStyle(AD.ink3)
                    .frame(width: 36, height: 36).background(AD.chip).clipShape(Circle())
            }
            Button { showSettings = true } label: {
                Image(systemName: "gearshape").font(.system(size: 15, weight: .semibold)).foregroundStyle(AD.ink3)
                    .frame(width: 36, height: 36).background(AD.chip).clipShape(Circle())
            }
        }
        .padding(.horizontal, 18).frame(minHeight: 54)
        .background(AD.card).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.line, lineWidth: 1))
    }

    /// 두 칸 전환 — [이송] 칸엔 병원 응답 배지(승인 수, 없으면 후보 수)를 붙여 환자 정보 화면에서도 응답이 온 걸 안다
    private var screenSwitch: some View {
        HStack(spacing: 2) {
            seg("환자 정보", .patient, badge: nil)
            seg("이송", .transport, badge: listBadge)
        }
        .padding(3).background(AD.chip).clipShape(Capsule())
        // 칸 어디를 눌러도 반대쪽 화면으로 넘어간다(2026-10-28) — 두 칸뿐이라 결과가 같고 과녁이 두 배다
        .contentShape(Capsule())
        .onTapGesture {
            withAnimation(.easeInOut(duration: 0.2)) {
                screenRaw = screenRaw == Screen.patient.rawValue ? Screen.transport.rawValue : Screen.patient.rawValue
            }
        }
    }
    private var listBadge: (String, Color)? {
        guard let r = model.result else { return model.scene.map { ("\($0.hospitals.count)", AD.gray) } }
        if model.confirmed != nil { return ("확정", AD.green) }
        let ok = r.hospitals.filter { HospitalRules.canTransportNow($0) }.count
        return ok > 0 ? ("승인 \(ok)", AD.green) : ("\(r.hospitals.count)", AD.orange)
    }
    private func seg(_ title: String, _ s: Screen, badge: (String, Color)?) -> some View {
        let on = screenRaw == s.rawValue
        return HStack(spacing: 5) {
                Text(title).font(.system(size: 13, weight: on ? .bold : .medium)).foregroundStyle(on ? AD.navy : AD.ink3)
                    .lineLimit(1).fixedSize()
                if let b = badge {
                    Text(b.0).font(.system(size: 10.5, weight: .bold)).foregroundStyle(.white).lineLimit(1).fixedSize()
                        .padding(.horizontal, 6).frame(minHeight: 17).background(b.1).clipShape(Capsule())
                }
            }
        .padding(.horizontal, 14).frame(minHeight: 32)
        .background(on ? AD.card : .clear).clipShape(Capsule())
        .shadow(color: on ? .black.opacity(0.08) : .clear, radius: 2, y: 1)
    }

    private var ambulanceLabel: String {
        if let n = model.ambulanceName { return n }
        if let a = model.apid { return "구급 \(a)" }
        return model.autoFollow ? "출동 구급대 자동" : "구급차 미지정"
    }

    private var statusView: some View {
        let (label, color): (String, Color) = {
            if let c = model.confirmed { return ("이송 확정 · \(c.name)", AD.green) }
            if model.hasIncident { return ("병원 선택 대기", AD.orange) }
            return ("출동 대기", AD.gray)
        }()
        // 상태 문구는 길어지면 말줄임(화면 전환 칸이 줄바꿈되지 않게). 폭을 고정하지 않는다(2026-10-28) —
        // 260pt 상자에 왼쪽 정렬로 넣었더니 [정보 생존 모델] 버튼과 한참 떨어져 보였다
        return HStack(spacing: 6) { Dot(color: color); Text(label).font(.system(size: 12, weight: .bold)).foregroundStyle(color).lineLimit(1).truncationMode(.tail) }
            .frame(maxWidth: 260, alignment: .trailing).fixedSize(horizontal: true, vertical: false)
    }

    private var connectionView: some View {
        let (label, color): (String, Color) = {
            switch model.connection {
            case .live: return ("", AD.green)
            case .connecting: return ("hub 연결 중…", AD.orange)
            case .reconnecting: return ("hub 재연결 중…", AD.red)
            case .closed: return ("hub 주소 없음", AD.red)
            }
        }()
        // 연결이 정상일 땐 아무것도 보이지 않는다 — 문제가 있을 때만 알린다
        return HStack(spacing: 6) { if !label.isEmpty { Dot(color: color); Text(label).font(.system(size: 12, weight: .medium)).foregroundStyle(color) } }
    }
}

/// (2026-10-26 구급차 화면에서 빼둠 — 지금 그 자리는 외상 부위 그림·인계확인서)
/// 오른쪽 지도 — spider 거미줄 3D(이 구급차의 사건만). 계산·데이터는 전부 서버 쪽이라 앱은 주소만 가리킨다.
struct MapCard: View {
    @EnvironmentObject private var model: AppModel
    @AppStorage("hubBase") private var hubBase = Settings.defaultHub
    @AppStorage("spiderBase") private var spiderBase = ""
    @State private var changeTo: BetterHospital?

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text("거미줄 분배 · 실시간").font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy)
                Spacer()
                // 지도를 손으로 옮기면 내 구급차 따라가기가 멈춘다 — 다시 켜는 버튼. auto에서 아직 따라갈 구급대가 없으면(출동 전·사건 종료 뒤)
                // 지도엔 '내 구급차'가 없으니 같은 자리에서 전체 보기로 동작한다(spider followMine이 알아서 바꾼다)
                Button { NotificationCenter.default.post(name: .spiderEval, object: nil, userInfo: ["js": "followMine()"]) } label: {
                    Label(model.apid == nil ? "전체 보기" : "내 구급차", systemImage: model.apid == nil ? "arrow.up.left.and.arrow.down.right" : "location.fill")
                        .font(.system(size: 12, weight: .bold)).foregroundStyle(.white)
                        .padding(.horizontal, 12).frame(minHeight: 30).background(AD.blue).clipShape(Capsule())
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 10)
            SpiderWebView(url: Settings.spiderURL(apid: model.apid, screen: "ambulance"))
                .id(hubBase + "|" + spiderBase + "|" + (model.apid ?? ""))   // 주소·구급차가 바뀌면 WebView를 새로 만든다
                .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
                .overlay(alignment: .topLeading) { betterPill.padding(10) }
                .padding([.horizontal, .bottom], 8)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AD.card).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.line, lineWidth: 1))
        // 지도 안(spider)에도 같은 병원을 작게 표시 — 바뀔 때만 보낸다(확률은 % 정수로 묶어 1초마다 보내지 않게)
        .onChange(of: betterSignature, initial: true) { _, _ in
            let items = model.betterHospitals.map { b in
                "{hpid:'\(b.id)',label:'\(jsSafe("▲ " + b.match.name + " · 유효 " + BedReliability.pct(b.rArrive) + " · " + b.bedText))'}"
            }
            NotificationCenter.default.post(name: .spiderEval, object: nil,
                                            userInfo: ["js": "window.setBetterHospitals&&setBetterHospitals([\(items.joined(separator: ","))])", "key": "better"])
        }
        // 목적지 변경 확인은 시스템 확인창 대신 알약 안에서(2026-10-16) — 확인창이 화면 엉뚱한 곳에 떠 흐름이 끊겼다.
        // 8초 동안 안 누르면 저절로 접는다(이동 중 펼쳐진 채로 남지 않게)
        .task(id: changeTo?.id) {
            guard changeTo != nil else { return }
            try? await Task.sleep(for: .seconds(8))
            if !Task.isCancelled { withAnimation(.easeOut(duration: 0.2)) { changeTo = nil } }
        }
    }

    private var betterSignature: String {
        model.betterHospitals.map { "\($0.id):\(Int(($0.rArrive * 100).rounded())):\($0.bedText)" }.joined(separator: "|")
    }

    /// 이송 중 "더 나은 병원" 알약 — 지금 목적지와 비교(병원 이름 · 도착 시 유효 % · 병상) + [변경]. 이송 중에만, 최대 2곳
    @ViewBuilder private var betterPill: some View {
        let better = model.betterHospitals
        if let c = model.confirmed, !better.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 6) {
                    Text("더 나은 병원").font(.system(size: 12, weight: .heavy)).foregroundStyle(AD.navy)
                    Pill(text: "AI · 도착 시 유효", bg: AD.blueSoft, fg: AD.blue)
                }
                Text("지금 \(c.name) · 유효 \(model.destinationRArrive.map(BedReliability.pct) ?? "—") · \(c.bedCountUnknown == true ? "병상 미상" : "병상 \(c.availableBedCount ?? 0)석")")
                    .font(.system(size: 11.5)).foregroundStyle(AD.ink3).lineLimit(1)
                ForEach(better) { b in
                    if changeTo?.id == b.id {
                        // [변경]을 누르면 그 자리에서 짧게 확인 — [취소] / [목적지 변경]
                        VStack(alignment: .leading, spacing: 6) {
                            Text("\(b.match.name)(으)로 바꿀까요?").font(.system(size: 13, weight: .bold)).foregroundStyle(AD.navy).lineLimit(1)
                            Text(changeMessage(b)).font(.system(size: 11.5)).foregroundStyle(AD.ink3).lineLimit(1)
                            HStack(spacing: 8) {
                                Spacer(minLength: 0)
                                Button { withAnimation(.easeOut(duration: 0.2)) { changeTo = nil } } label: {
                                    Text("취소").font(.system(size: 12.5, weight: .bold)).foregroundStyle(AD.ink3)
                                        .padding(.horizontal, 14).frame(minHeight: 32).background(AD.chip).clipShape(Capsule())
                                }
                                .buttonStyle(.plain)
                                Button { model.approve(b.match.hospitalId); changeTo = nil } label: {
                                    Text("목적지 변경").font(.system(size: 12.5, weight: .bold)).foregroundStyle(.white)
                                        .padding(.horizontal, 14).frame(minHeight: 32).background(AD.approve).clipShape(Capsule())
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(8)
                        .background(AD.orangeSoft).clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
                        .transition(.opacity)
                    } else {
                        HStack(spacing: 8) {
                            VStack(alignment: .leading, spacing: 1) {
                                Text(b.match.name).font(.system(size: 13, weight: .bold)).foregroundStyle(AD.navy).lineLimit(1)
                                HStack(spacing: 6) {
                                    Text("유효 \(BedReliability.pct(b.rArrive))").font(.system(size: 12, weight: .bold)).foregroundStyle(Theme.validity(b.rArrive).fg)
                                    Text(b.bedText).font(.system(size: 12, weight: .semibold)).foregroundStyle(AD.lime)
                                }
                            }
                            Spacer(minLength: 6)
                            Button { withAnimation(.easeOut(duration: 0.2)) { changeTo = b } } label: {
                                Text("변경").font(.system(size: 12.5, weight: .bold)).foregroundStyle(.white)
                                    .padding(.horizontal, 14).frame(minHeight: 32).background(AD.approve).clipShape(Capsule())
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }
            }
            .padding(12)
            .frame(width: 300, alignment: .leading)
            .background(AD.card.opacity(0.96))
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous).stroke(AD.approve.opacity(0.6), lineWidth: 1.5))
            .shadow(color: .black.opacity(0.25), radius: 10, y: 4)
            .transition(.opacity)
        }
    }

    private func changeMessage(_ b: BetterHospital) -> String {
        let eta = b.match.etaMin.map { "도착 약 \($0)분" } ?? b.match.travelMin.map { "도착 약 \(Int($0.rounded()))분(추정)" } ?? ""
        return "유효 \(BedReliability.pct(b.rArrive)) · \(b.bedText)\(eta.isEmpty ? "" : " · \(eta)") · 수용 승인 병원"
    }

    private func jsSafe(_ s: String) -> String { s.replacingOccurrences(of: "\\", with: "").replacingOccurrences(of: "'", with: "’") }
}
