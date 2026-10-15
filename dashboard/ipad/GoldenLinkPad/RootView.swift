import SwiftUI

/// 구급차 대시보드(웹 /ambulance 시안)와 같은 배치 — 상단바 · 범례 → 왼쪽 열(현장 상태 · 통화 요약) + 오른쪽 거미줄 3D 지도.
/// 상단바의 [구급차 | 병원 리스트 | 상황판]으로 화면을 바꾼다(2026-10-16) — 병원 리스트는 지도 없이 현장 상태·통화 요약 + 병원 후보
/// (HospitalListScreen), 상황판은 이 구급차가 아니라 전체 사건(대량사고). 예전엔 병원 리스트가 구급차 화면 아래 띠였다.
/// 자동 전환: 음성 요약이 처음 도착하면 병원 리스트로, 이송이 확정되면(hub 응답) 구급차 지도로(AppModel.requestScreen).
/// 상단바의 [정보 생존 모델]은 같은 화면 위에 전체 화면으로 덮는다.
enum Screen: String { case ambulance, hospitals, board }

struct RootView: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var board: BoardModel
    @AppStorage("screen") private var screenRaw = Screen.ambulance.rawValue
    @State private var showSettings = false
    @State private var showSurvival = false
    private var screen: Screen { Screen(rawValue: screenRaw) ?? .ambulance }

    var body: some View {
        ZStack(alignment: .top) {
            AD.bg.ignoresSafeArea()
            VStack(spacing: 8) {
                TopBar(showSurvival: $showSurvival, showSettings: $showSettings, screenRaw: $screenRaw)
                Legend()
                if screen == .board {
                    SituationBoardView()
                } else if screen == .hospitals {
                    callBanner
                    HospitalListScreen()
                } else {
                callBanner
                // 병원 후보는 [병원 리스트] 화면으로 옮겼다(2026-10-16) — 지도가 아래까지
                GeometryReader { g in
                    HStack(alignment: .top, spacing: 14) {
                        ScrollView {
                            VStack(spacing: 8) {
                                SceneStatusCard()
                                if model.hasIncident { CallSummaryCard() }
                            }
                        }
                        .scrollIndicators(.hidden)
                        .frame(width: g.size.width >= 1000 ? 360 : 320)
                        .clipped()
                        MapCard()
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
        .sheet(isPresented: $showSettings) { SettingsView().environmentObject(model).environmentObject(board) }
        .fullScreenCover(isPresented: $showSurvival) { SurvivalModelScreen(isPresented: $showSurvival).environmentObject(model) }
        .onAppear { model.start(); if screen == .board { board.start() } }
        .onChange(of: screenRaw) { _, v in if v == Screen.board.rawValue { board.start() } }
        // 자동 전환(2026-10-16): 음성 요약 첫 도착 → 병원 리스트, 이송 확정 → 구급차 지도. 상황판을 보고 있으면 건드리지 않는다
        .onReceive(NotificationCenter.default.publisher(for: .switchScreen)) { n in
            guard let raw = n.userInfo?["screen"] as? String, screen != .board else { return }
            withAnimation(.easeInOut(duration: 0.25)) { screenRaw = raw }
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

/// 상단바 — 로고 · 버전 · 구급대 이름 | 정보 생존 모델 · 이송 상태 · 연결 · 경과 · 설정 (웹 AmbulanceTopBar)
struct TopBar: View {
    @EnvironmentObject private var model: AppModel
    @EnvironmentObject private var board: BoardModel
    @Binding var showSurvival: Bool
    @Binding var showSettings: Bool
    @Binding var screenRaw: String
    private var isBoard: Bool { screenRaw == Screen.board.rawValue }

    var body: some View {
        HStack(spacing: 14) {
            HStack(spacing: 10) {
                (Text("골든").foregroundStyle(AD.navy) + Text("링크").foregroundStyle(AD.blue))
                    .font(.system(size: 20, weight: .black))
                Pill(text: "v2.0", bg: AD.blueSoft, fg: AD.blue, bold: true)
                if isBoard { Pill(text: "상황판 · 전체 사건", bg: AD.navy, fg: .white, bold: true) }
                else { Pill(text: ambulanceLabel, bg: AD.chip, fg: AD.ink3, bold: true) }
            }
            // 구급차(지도) · 병원 리스트 · 상황판(전체 사건, 대량사고용)
            screenSwitch
            Spacer(minLength: 8)
            if isBoard {
                let n = board.rows.count
                HStack(spacing: 6) { Dot(color: n > 0 ? AD.orange : AD.gray); Text(n > 0 ? "진행 중 \(n)건" : "진행 중 사건 없음").font(.system(size: 12, weight: .bold)).foregroundStyle(n > 0 ? AD.orange : AD.gray) }
            } else {
                statusView
            }
            connectionView
            if !isBoard, let at = model.receivedAt {
                (Text("수신 후 ") + Text(Labels.elapsed(model.now.timeIntervalSince(at))).bold().foregroundColor(AD.navy) + Text(" 경과"))
                    .font(.system(size: 12)).foregroundStyle(AD.sub)
            }
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

    /// 세 칸 전환 — 병원 리스트 칸엔 병원 응답 배지(승인 수, 없으면 후보 수)를 붙여 구급차 화면에서도 응답이 온 걸 안다
    private var screenSwitch: some View {
        HStack(spacing: 2) {
            seg("구급차", .ambulance, badge: nil)
            seg("병원 리스트", .hospitals, badge: listBadge)
            seg("상황판", .board, badge: nil)
        }
        .padding(3).background(AD.chip).clipShape(Capsule())
    }
    private var listBadge: (String, Color)? {
        guard let r = model.result else { return model.scene.map { ("\($0.hospitals.count)", AD.gray) } }
        if model.confirmed != nil { return ("확정", AD.green) }
        let ok = r.hospitals.filter { HospitalRules.canTransportNow($0) }.count
        return ok > 0 ? ("승인 \(ok)", AD.green) : ("\(r.hospitals.count)", AD.orange)
    }
    private func seg(_ title: String, _ s: Screen, badge: (String, Color)?) -> some View {
        let on = screenRaw == s.rawValue
        return Button { withAnimation(.easeInOut(duration: 0.2)) { screenRaw = s.rawValue } } label: {
            HStack(spacing: 5) {
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
        .buttonStyle(.plain)
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
        // 상태 문구는 길어지면 말줄임 — 화면 전환 칸이 줄바꿈되지 않게(2026-10-16)
        return HStack(spacing: 6) { Dot(color: color); Text(label).font(.system(size: 12, weight: .bold)).foregroundStyle(color).lineLimit(1).truncationMode(.tail) }
            .frame(maxWidth: 260, alignment: .leading)
    }

    private var connectionView: some View {
        let (label, color): (String, Color) = {
            switch isBoard ? board.connection : model.connection {
            case .live: return ("실시간 연동", AD.green)
            case .connecting: return ("hub 연결 중…", AD.orange)
            case .reconnecting: return ("hub 재연결 중…", AD.red)
            case .closed: return ("hub 주소 없음", AD.red)
            }
        }()
        return HStack(spacing: 6) { Dot(color: color); Text(label).font(.system(size: 12, weight: .medium)).foregroundStyle(color) }
    }
}

/// 범례 + AI 안내 한 줄 — AI 처리 / 규칙 기반 / 의료진 판단 영역을 색으로 구분(웹 AmbulanceLegend, CLAUDE.md 출처 표시 원칙)
struct Legend: View {
    var body: some View {
        HStack(spacing: 18) {
            item(AD.blue, "AI 처리")
            item(AD.gray, "규칙 기반 · 센서 · API")
            item(AD.orange, "의료진 판단 영역")
            Spacer()
            Text("AI는 환자 정보 구조화와 기록 자동화만 수행합니다. 이송 최종 승인은 구급대원의 판단입니다.")
                .font(.system(size: 11.5)).foregroundStyle(AD.sub).lineLimit(1).minimumScaleFactor(0.8)
        }
        .padding(.horizontal, 6)
    }
    private func item(_ c: Color, _ t: String) -> some View {
        HStack(spacing: 6) { Dot(color: c, size: 9); Text(t).font(.system(size: 11.5)).foregroundStyle(AD.ink3) }
    }
}

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
                Text("내 구급차 기준 · 이송 경로").font(.system(size: 11.5)).foregroundStyle(AD.sub)
                Spacer()
                Pill(text: "초록 노드 = 요청 병원 · 초록 줄 = 승인 중 최적", bg: AD.greenSoft, fg: AD.green)
                Pill(text: "민트 = 거미줄 제안", bg: Color(hex: 0xE6FBF4), fg: Color(hex: 0x0F7B5F))
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
        .confirmationDialog(changeTo.map { "목적지를 \($0.match.name)(으)로 바꿀까요?" } ?? "", isPresented: Binding(get: { changeTo != nil }, set: { if !$0 { changeTo = nil } }),
                            titleVisibility: .visible, presenting: changeTo) { b in
            Button("\(b.match.name)(으)로 변경") { model.approve(b.match.hospitalId); changeTo = nil }
            Button("취소", role: .cancel) { changeTo = nil }
        } message: { b in
            Text(changeMessage(b))
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
                    HStack(spacing: 8) {
                        VStack(alignment: .leading, spacing: 1) {
                            Text(b.match.name).font(.system(size: 13, weight: .bold)).foregroundStyle(AD.navy).lineLimit(1)
                            HStack(spacing: 6) {
                                Text("유효 \(BedReliability.pct(b.rArrive))").font(.system(size: 12, weight: .bold)).foregroundStyle(Theme.validity(b.rArrive).fg)
                                Text(b.bedText).font(.system(size: 12, weight: .semibold)).foregroundStyle(AD.lime)
                            }
                        }
                        Spacer(minLength: 6)
                        Button { changeTo = b } label: {
                            Text("변경").font(.system(size: 12.5, weight: .bold)).foregroundStyle(.white)
                                .padding(.horizontal, 14).frame(minHeight: 32).background(AD.approve).clipShape(Capsule())
                        }
                        .buttonStyle(.plain)
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
        return "도착 시 병상 정보 유효 \(BedReliability.pct(b.rArrive)) · \(b.bedText)\(eta.isEmpty ? "" : " · \(eta)")\n병원이 수용 승인한 곳입니다. 지금 위치에서 새 병원으로 이동합니다."
    }

    private func jsSafe(_ s: String) -> String { s.replacingOccurrences(of: "\\", with: "").replacingOccurrences(of: "'", with: "’") }
}
