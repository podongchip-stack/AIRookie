import SwiftUI

/// 골든링크 구급차 대시보드 — 아이패드(2026-10-14). 구급차에 싣는 화면이다: 웹 구급차 대시보드(/ambulance)와 같은 디자인으로
/// 현장 상태·통화 요약(환자 정보)·병원 후보(수용 여부·정보 유효성)를 보여 주고, 지도 자리에는 spider 거미줄 3D를 띄운다.
/// 계산은 전부 서버(hub·spider)가 하고, 이 앱은 받은 값을 그린다(정보 생존 확률의 초 단위 감쇠만 같은 식으로 로컬 계산).
/// 조작은 [이송 승인] 하나(구급대원 판단).
@main
struct GoldenLinkPadApp: App {
    @StateObject private var model = AppModel()

    init() {
        #if DEBUG
        InjuryMapper.selfCheck()   // 외상 부위 규칙 — 틀리면 DEBUG 빌드에서 바로 멈춘다
        InjuryRisk.selfCheck()     // 외상 위험도 규칙(초안)
        BodyShape.selfCheck()      // 그림 탭 → 부위 · 탭으로 적은 것의 전달 줄
        #endif
    }

    var body: some Scene {
        WindowGroup {
            Group {
                if model.accessRequired {
                    PadAccessCodeEntry { model.accessRequired = false }
                } else {
                    RootView()
                }
            }
                .environmentObject(model)
                .preferredColorScheme(.light)
        }
    }
}
