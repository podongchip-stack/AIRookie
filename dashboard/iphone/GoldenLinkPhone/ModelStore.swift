import Foundation
import GoldenLinkCore

/// 두 모델을 한 번 올려 두고 계속 쓴다(서버 voice와 같은 방식). 합계 약 3GB — 8GB 기기라
/// Increased Memory Limit 권한이 필요하다. 메모리가 모자라면 MF_BERT를 통화 종료 뒤에 올리도록 바꾼다(README 참고).
actor ModelStore {
    private var asr: OnDeviceASR?
    private var mfBert: MFBertRunner?

    /// 앱 시작 때 미리 부른다. 실패하면 이유를 돌려준다(화면에 표시 → 서버 STT 모드로 쓸 수 있음)
    func load() async -> String? {
        do {
            if mfBert == nil { mfBert = try MFBertRunner() }
            if asr == nil { asr = try await OnDeviceASR.load() }
            return nil
        } catch {
            return error.localizedDescription
        }
    }

    var ready: Bool { asr != nil && mfBert != nil }

    func transcribe(_ audio: [Float]) async -> [RecognizedSegment] {
        await asr?.transcribe(audio) ?? []
    }

    func extract(_ text: String) throws -> JSONValue {
        guard let mfBert else { throw NSError(domain: "MFBert", code: 1, userInfo: [NSLocalizedDescriptionKey: "MF_BERT 미탑재"]) }
        return try mfBert.extract(text)
    }
}
