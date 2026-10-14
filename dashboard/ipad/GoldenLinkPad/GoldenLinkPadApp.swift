import SwiftUI

/// 골든링크 관제 — 아이패드(2026-10-14). hub WebSocket(role=monitor)으로 실제 사건을 받아 환자 위치·정보, 병원 수용 여부,
/// 병원 정보의 유효성(정보 생존 모델)을 네이티브로 보여 주고, 가운데에는 spider 거미줄 3D(서버 페이지)를 WebView로 띄운다.
/// 계산은 전부 서버(hub·spider)가 한다 — 이 앱은 받은 값을 그리고(정보 생존 확률의 초 단위 감쇠만 같은 식으로 로컬 계산)
/// hub에는 identify 외에 아무것도 보내지 않는다(보기 전용).
@main
struct GoldenLinkPadApp: App {
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(model)
                .preferredColorScheme(.dark)
        }
    }
}
