// swift-tools-version: 6.0
// 모델·화면과 무관한 순수 로직(토크나이저·조각 나누기·decode·parse·발화 자르기·hub 메시지).
// 맥에서 `swift test`로 Python 원본(voice/)과 같은 결과를 내는지 바로 확인할 수 있게 앱과 분리했다.
import PackageDescription

let package = Package(
    name: "GoldenLinkCore",
    platforms: [.iOS(.v18), .macOS(.v14)],
    products: [.library(name: "GoldenLinkCore", targets: ["GoldenLinkCore"])],
    targets: [
        .target(name: "GoldenLinkCore", resources: [.copy("Resources/labels.json")]),
        .testTarget(name: "GoldenLinkCoreTests", dependencies: ["GoldenLinkCore"], resources: [.copy("Fixtures")]),
    ],
    swiftLanguageModes: [.v5]
)
