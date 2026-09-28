import SwiftUI

/// 앱 진입점.
/// 파일명과 타입명은 Xcode 프로젝트 이름(LiDAR_Space3D)이 자동 생성하는 것과 **일치**시켰다.
/// 이름이 다르면 Xcode가 만든 LiDAR_Space3DApp.swift와 이 파일에 @main이 둘 다 있게 되어
/// "'main' attribute can only apply to one type" 으로 빌드가 깨진다.
@main
struct LiDAR_Space3DApp: App {
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
}
