import SwiftUI

/// 가로 3단: [사건·환자 정보 | 거미줄 3D(WebView) | 병원 수용 여부·정보 유효성]. 위 탭으로 [정보 생존 모델] 전체 화면.
struct RootView: View {
    enum Tab: String, CaseIterable, Identifiable {
        case control = "관제 · 거미줄 3D"
        case survival = "정보 생존 모델"
        var id: String { rawValue }
    }

    @EnvironmentObject private var model: AppModel
    @AppStorage("tab") private var tabRaw = Tab.control.rawValue   // 마지막 탭 기억
    @State private var showSettings = false
    private var tab: Binding<Tab> { Binding(get: { Tab(rawValue: tabRaw) ?? .control }, set: { tabRaw = $0.rawValue }) }
    @AppStorage("hubBase") private var hubBase = Settings.defaultHub
    @AppStorage("spiderBase") private var spiderBase = ""

    var body: some View {
        ZStack {
            Theme.bg.ignoresSafeArea()
            VStack(spacing: 10) {
                topBar
                switch tab.wrappedValue {
                case .control: ControlView()
                case .survival: SurvivalModelView()
                }
            }
            .padding(12)
        }
        .sheet(isPresented: $showSettings) { SettingsView().environmentObject(model) }
        .onAppear { model.start() }
    }

    private var topBar: some View {
        HStack(spacing: 14) {
            VStack(alignment: .leading, spacing: 2) {
                Text("골든링크 관제").font(.system(size: 18, weight: .bold)).foregroundStyle(Theme.ink)
                Text("거미줄 분배 모델 · 정보 생존 모델").font(.system(size: 11)).foregroundStyle(Theme.muted)
            }
            Picker("", selection: tab) {
                ForEach(Tab.allCases) { t in Text(t.rawValue).tag(t) }
            }
            .pickerStyle(.segmented)
            .frame(width: 320)
            Spacer()
            connectionBadge
            Text("사건 \(model.cases.count)건").font(.system(size: 12)).foregroundStyle(Theme.ink2)
            Button { NotificationCenter.default.post(name: .spiderReload, object: nil); model.fetchLiveBoard() } label: {
                Label("새로고침", systemImage: "arrow.clockwise")
            }
            Button { showSettings = true } label: { Label("설정", systemImage: "gearshape") }
        }
        .font(.system(size: 13))
        .tint(Theme.ink2)
    }

    private var connectionBadge: some View {
        let (text, color): (String, Color) = {
            switch model.connection {
            case .live: return ("hub 연결됨", Theme.ok)
            case .connecting: return ("hub 연결 중", Theme.amber)
            case .reconnecting: return ("hub 재연결 중", Theme.clash)
            case .closed: return ("hub 주소 없음", Theme.clash)
            }
        }()
        return HStack(spacing: 5) {
            Circle().fill(color).frame(width: 8, height: 8)
            Text(text).font(.system(size: 12)).foregroundStyle(Theme.ink2)
            Text(hostLabel).font(.system(size: 11)).foregroundStyle(Theme.muted)
        }
    }

    private var hostLabel: String { URL(string: hubBase)?.host ?? hubBase }
}

/// 관제 탭 — 3단 배치
struct ControlView: View {
    @EnvironmentObject private var model: AppModel
    @AppStorage("hubBase") private var hubBase = Settings.defaultHub
    @AppStorage("spiderBase") private var spiderBase = ""

    var body: some View {
        // iPadOS 26은 앱을 창으로 띄울 수 있어 폭이 줄어든다 — 1,000pt 넘으면 3단, 아니면 위 거미줄 · 아래 2단
        GeometryReader { g in
            if g.size.width >= 1000 {
                HStack(spacing: 10) {
                    CaseColumn().frame(width: 330)
                    web
                    HospitalColumn().frame(width: 380)
                }
            } else {
                VStack(spacing: 10) {
                    web.frame(height: max(g.size.height * 0.42, 260))
                    HStack(spacing: 10) {
                        CaseColumn()
                        HospitalColumn()
                    }
                }
            }
        }
        .id(hubBase + "|" + spiderBase)   // 주소가 바뀌면 WebView를 새로 만든다
    }

    private var web: some View {
        SpiderWebView(url: Settings.spiderURL)
            .clipShape(RoundedRectangle(cornerRadius: 6))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(Theme.line, lineWidth: 1))
            .overlay(alignment: .topTrailing) {
                Text("거미줄 3D · spider 서버").font(.system(size: 11)).foregroundStyle(Theme.ink2)
                    .padding(.horizontal, 8).padding(.vertical, 4).background(Theme.panel.opacity(0.85)).clipShape(RoundedRectangle(cornerRadius: 4)).padding(8)
            }
    }
}
