import Foundation
import UIKit

/// 기기 기종을 사람이 읽을 수 있는 이름으로 알아낸다.
///
/// 왜 필요한가:
/// `UIDevice.current.model`은 **모든 아이폰에서 "iPhone"만** 돌려준다. 그래서 세션 폴더와
/// metadata.json만 봐서는 15 Pro로 찍은 건지 12 Pro로 찍은 건지 구분할 수 없었다.
/// 두 대로 동시에 찍고 병합하는 워크플로에서는 이게 바로 문제가 된다 — 어느 쪽 메시가
/// 성글었는지, 어느 기기가 더 멀리 측정했는지 추적할 수가 없다.
///
/// 실제 기종은 `uname()`의 `machine` 필드(예: "iPhone16,1")에 들어 있고, 이를 표에서 찾아
/// "iPhone 15 Pro"로 바꾼다.
///
/// 실패 시 확인할 것:
/// - 이름이 "iPhone16_1" 처럼 식별자 그대로 나옴 -> 표에 없는 신형이다. `modelNames`에 추가할 것.
///   (표에 없어도 세션은 정상 동작한다 — 식별자를 그대로 쓰기 때문에 구분은 계속 된다.)
/// - 시뮬레이터에서는 "Simulator"가 나온다. ARKit이 안 되므로 어차피 의미 있는 세션이 아니다.
enum DeviceInfo {

    /// 하드웨어 식별자. 예: "iPhone16,1"
    static let identifier: String = {
        // 시뮬레이터는 uname이 맥의 아키텍처를 주므로 환경변수로 먼저 걸러낸다.
        if let sim = ProcessInfo.processInfo.environment["SIMULATOR_MODEL_IDENTIFIER"] {
            return sim
        }
        var info = utsname()
        uname(&info)
        let raw = withUnsafeBytes(of: &info.machine) { buffer -> String in
            // machine은 고정 길이 C 배열이라 NUL 이전까지만 잘라야 한다.
            let bytes = buffer.prefix { $0 != 0 }
            return String(decoding: bytes, as: UTF8.self)
        }
        return raw.isEmpty ? "unknown" : raw
    }()

    /// 사람이 읽는 이름. 예: "iPhone 15 Pro"
    static var marketingName: String {
        modelNames[identifier] ?? identifier
    }

    /// 파일/폴더 이름에 쓸 수 있게 정리한 이름. 예: "iPhone15Pro"
    ///
    /// 서버의 `SESSION_ID_RE = ^[A-Za-z0-9_\-]+$` 를 반드시 통과해야 한다.
    /// 통과하지 못하면 업로드가 400으로 거부되므로, 영숫자가 아닌 문자는 전부 제거한다
    /// (공백, 쉼표, 괄호 등).
    static var slug: String {
        let cleaned = marketingName.unicodeScalars
            .filter { CharacterSet.alphanumerics.contains($0) }
            .map(String.init)
            .joined()
        return cleaned.isEmpty ? "unknown" : cleaned
    }

    /// LiDAR 스캐너 탑재 기종인가 (표 기준의 참고값).
    ///
    /// ⚠️ 실제 판단은 이 표가 아니라 `ARCaptureManager.isLiDARCaptureAvailable`
    ///    (= ARKit 런타임 질의)로 한다. 표는 새 기종이 나오면 낡기 때문이다.
    ///    이 값은 metadata에 "표 기준으로는 이랬다"는 참고 기록으로만 남긴다.
    static var hasLiDARByModelTable: Bool {
        lidarModels.contains(identifier)
    }

    /// 기종 표. LiDAR 탑재 기종을 우선 채웠고, 비탑재 기종도 혼동을 막기 위해 일부 포함한다.
    /// 표에 없으면 식별자를 그대로 쓰므로 빠져도 치명적이지 않다.
    private static let modelNames: [String: String] = [
        // --- LiDAR 탑재 (iPhone) ---
        "iPhone13,3": "iPhone 12 Pro",
        "iPhone13,4": "iPhone 12 Pro Max",
        "iPhone14,2": "iPhone 13 Pro",
        "iPhone14,3": "iPhone 13 Pro Max",
        "iPhone15,2": "iPhone 14 Pro",
        "iPhone15,3": "iPhone 14 Pro Max",
        "iPhone16,1": "iPhone 15 Pro",
        "iPhone16,2": "iPhone 15 Pro Max",
        "iPhone17,1": "iPhone 16 Pro",
        "iPhone17,2": "iPhone 16 Pro Max",
        "iPhone18,1": "iPhone 17 Pro",
        "iPhone18,2": "iPhone 17 Pro Max",

        // --- LiDAR 비탑재 (찍혀도 메시가 안 나오므로 이름으로 바로 알아보게) ---
        "iPhone13,1": "iPhone 12 mini",
        "iPhone13,2": "iPhone 12",
        "iPhone14,4": "iPhone 13 mini",
        "iPhone14,5": "iPhone 13",
        "iPhone14,7": "iPhone 14",
        "iPhone14,8": "iPhone 14 Plus",
        "iPhone15,4": "iPhone 15",
        "iPhone15,5": "iPhone 15 Plus",
        "iPhone17,3": "iPhone 16",
        "iPhone17,4": "iPhone 16 Plus",

        // --- iPad Pro (LiDAR 탑재) ---
        "iPad8,9": "iPad Pro 11 (2nd)",
        "iPad8,10": "iPad Pro 11 (2nd)",
        "iPad8,11": "iPad Pro 12.9 (4th)",
        "iPad8,12": "iPad Pro 12.9 (4th)",
        "iPad13,4": "iPad Pro 11 (3rd)",
        "iPad13,5": "iPad Pro 11 (3rd)",
        "iPad13,6": "iPad Pro 11 (3rd)",
        "iPad13,7": "iPad Pro 11 (3rd)",
        "iPad13,8": "iPad Pro 12.9 (5th)",
        "iPad13,9": "iPad Pro 12.9 (5th)",
        "iPad13,10": "iPad Pro 12.9 (5th)",
        "iPad13,11": "iPad Pro 12.9 (5th)",
    ]

    private static let lidarModels: Set<String> = [
        "iPhone13,3", "iPhone13,4", "iPhone14,2", "iPhone14,3",
        "iPhone15,2", "iPhone15,3", "iPhone16,1", "iPhone16,2",
        "iPhone17,1", "iPhone17,2", "iPhone18,1", "iPhone18,2",
        "iPad8,9", "iPad8,10", "iPad8,11", "iPad8,12",
        "iPad13,4", "iPad13,5", "iPad13,6", "iPad13,7",
        "iPad13,8", "iPad13,9", "iPad13,10", "iPad13,11",
    ]
}
