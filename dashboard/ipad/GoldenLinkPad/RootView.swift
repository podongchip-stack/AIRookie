import SwiftUI

/// 구급차 대시보드(웹 /ambulance 시안)와 같은 배치 — 상단바 · 범례 → 위: 왼쪽 열(현장 상태 · 통화 요약) + 오른쪽 거미줄 3D 지도
/// → 아래: 병원 후보 리스트(가로 스크롤 카드). 병원 리스트는 사고가 발생했을 때만 아래에서 올라온다.
/// 상단바의 [정보 생존 모델]은 같은 화면 위에 전체 화면으로 덮는다.
/// 상단바의 [구급차 | 상황판]으로 화면을 바꾼다 — 상황판은 이 구급차가 아니라 전체 사건(대량사고)을 본다(SituationBoardView).
enum Screen: String { case ambulance, board }

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
                } else {
                if let call = model.callStatus, call.state == "calling" {
                    Text("휴대폰으로 \(call.hospitalName ?? "병원")과 통화 중 — 통화가 끝나면 환자 정보가 후보 병원에 동시에 전달됩니다")
                        .font(.system(size: 13, weight: .bold)).foregroundStyle(AD.green)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.horizontal, 16).padding(.vertical, 8)
                        .background(AD.greenSoft).clipShape(RoundedRectangle(cornerRadius: 12))
                }
                GeometryReader { g in
                    let wide = g.size.width >= 1000
                    VStack(spacing: 10) {
                        HStack(alignment: .top, spacing: 14) {
                            ScrollView {
                                VStack(spacing: 8) {
                                    SceneStatusCard()
                                    if model.hasIncident { CallSummaryCard() }
                                }
                            }
                            .scrollIndicators(.hidden)
                            .frame(width: wide ? 360 : 320)
                            .clipped()   // 넘치는 통화 요약이 아래 병원 리스트 제목 위로 비치지 않게
                            MapCard()
                        }
                        .frame(maxHeight: .infinity)
                        // 사고가 없으면 병원 리스트 자리 없이 지도가 아래까지 — 사고가 생기면 아래에서 올라온다
                        if model.hasIncident {
                            // 카드(병상·AI 유효·전문의 세 칸 + 칩 한 줄 + 정보 유효성 + 이송 승인)가 약 225pt — 지도를 가리지 않게 낮게(2026-10-14)
                            HospitalSection()
                                .frame(height: min(max(g.size.height * 0.36, 252), 268))
                                .clipped()
                                .transition(.move(edge: .bottom).combined(with: .opacity))
                        }
                    }
                    .animation(.spring(response: 0.45, dampingFraction: 0.86), value: model.hasIncident)
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
            // 구급차 화면 ↔ 상황판(전체 사건, 대량사고용)
            Picker("", selection: $screenRaw) {
                Text("구급차").tag(Screen.ambulance.rawValue)
                Text("상황판").tag(Screen.board.rawValue)
            }
            .pickerStyle(.segmented)
            .frame(width: 170)
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
        return HStack(spacing: 6) { Dot(color: color); Text(label).font(.system(size: 12, weight: .bold)).foregroundStyle(color).lineLimit(1) }
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

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Text("거미줄 분배 · 실시간").font(.system(size: 15, weight: .bold)).foregroundStyle(AD.navy)
                Text("내 구급차 기준 · 이송 경로").font(.system(size: 11.5)).foregroundStyle(AD.sub)
                Spacer()
                Pill(text: "초록 = 승인 병원 중 최적", bg: AD.greenSoft, fg: AD.green)
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
                .padding([.horizontal, .bottom], 8)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .background(AD.card).clipShape(RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous).stroke(AD.line, lineWidth: 1))
    }
}
