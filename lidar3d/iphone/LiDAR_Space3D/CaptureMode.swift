import Foundation

/// 촬영 모드. 하나의 앱에서 3D 스캔과 4D 고정 녹화를 골라 쓴다.
///
/// - 3D 스캔(`scan3D`): 기존 방식 그대로. 폰을 들고 현장을 한 바퀴 돌며 정적 공간을 기록한다.
///   ARKit 메시(scene_mesh.ply)를 함께 만들어 뷰어가 바로 그린다.
/// - 4D 고정 녹화(`fixed4D`): 폰을 거치대에 **고정**하고 처치 과정처럼 시간에 따라 바뀌는 장면을
///   기록한다(live4d). 시간대별 3D는 Mac이 원본 뎁스로 만들므로 ARKit 메시는 만들지 않는다.
///
/// 파일 형식(영상·뎁스·포즈·intrinsics)은 두 모드가 **완전히 같다** — Mac 파이프라인이 그대로 읽는다.
/// 달라지는 것은 무엇을 켜고 끄는지, 얼마나 자주 저장하는지뿐이다.
enum CaptureMode: String, CaseIterable, Identifiable {
    case scan3D = "scan3d"
    case fixed4D = "fixed4d"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .scan3D:  return "3D 스캔"
        case .fixed4D: return "4D 고정 녹화"
        }
    }

    var guide: String {
        switch self {
        case .scan3D:
            return "폰을 들고 천천히 한 바퀴 — 현장 공간(정적 3D)을 기록합니다."
        case .fixed4D:
            return "폰을 거치대에 고정한 뒤 START — 시간에 따라 바뀌는 장면을 기록합니다. "
                + "녹화 중에는 폰을 건드리지 마세요. 최대 \(Int((maxDuration ?? 0) / 60))분."
        }
    }

    /// ARKit 씬 재구성(메시). 4D는 끈다 — 원본 뎁스로 Mac이 재구성하고, 끄면 발열이 줄어든다.
    var meshEnabled: Bool { self == .scan3D }

    /// 뎁스 저장 주기(Hz). 4D는 영상(15Hz)과 맞춰 영상 프레임마다 뎁스가 있게 한다.
    var depthSaveHz: Double { self == .scan3D ? 10.0 : 15.0 }

    /// 영상 저장 주기(Hz). 두 모드 같다.
    var videoSaveHz: Double { 15.0 }

    /// 뎁스 저장·업로드를 토글과 무관하게 강제하는가. 4D는 뎁스가 결과물의 본체다.
    var requiresDepth: Bool { self == .fixed4D }

    /// 최대 녹화 시간(초). 4D 15Hz 뎁스+신뢰도는 약 3.7MB/s라, 서버의 depth.zip 해제 상한(2GB)
    /// 안에 들어오도록 8분에서 자동 종료한다(8분 ≈ 1.8GB). 3D 스캔은 제한하지 않는다.
    var maxDuration: TimeInterval? { self == .fixed4D ? 8 * 60 : nil }

    /// metadata.json의 capture_mode 값. Mac 파이프라인이 모드를 구분하는 근거.
    var metadataTag: String { self == .scan3D ? "lidar_arkit" : "lidar_arkit_fixed4d" }

    /// 세션 폴더 이름 끝에 붙는 표시. 서버 목록에서 바로 구분되게 한다.
    var sessionSuffix: String { self == .scan3D ? "" : "_4D" }

    /// 뎁스(Float32) + 신뢰도(UInt8) 한 프레임의 바이트 — 예상 용량 표시용.
    static let depthBytesPerFrame = 256 * 192 * 4 + 256 * 192
}
