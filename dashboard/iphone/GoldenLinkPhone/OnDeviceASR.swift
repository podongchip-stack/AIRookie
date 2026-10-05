import Foundation
import GoldenLinkCore
import Qwen3ASR

/// Qwen3-ASR-0.6B + LoRA(합친 것) 온디바이스 STT. speech-swift(MLX Swift)에 float 디코더 패치를 적용해 bf16 그대로 돈다.
/// voice/asr.py와 같은 규칙: 16kHz 모노, "language Korean<asr_text>" 프롬프트, 그리디, max_new_tokens=256, 5초 넘으면 조용한 곳에서 자름.
/// 모델 하나라 한 번에 하나만 돌린다(actor).
actor OnDeviceASR {
    static let folderName = "Qwen3ASR-119ko-bf16"  // convert/merge_qwen3_asr.py 출력 폴더(앱 번들에 폴더째 넣는다)
    private let model: Qwen3ASRModel

    private init(model: Qwen3ASRModel) { self.model = model }

    static func load() async throws -> OnDeviceASR {
        guard let dir = Bundle.main.url(forResource: folderName, withExtension: nil, subdirectory: "Models") else {
            throw NSError(domain: "ASR", code: 1, userInfo: [NSLocalizedDescriptionKey:
                "앱 번들에 \(folderName) 폴더가 없습니다 — README '2. 모델 변환' 참고"])
        }
        // modelId는 크기 판정(0.6B)에만 쓰인다. offlineMode라 내려받지 않고 폴더를 그대로 읽는다
        let model = try await Qwen3ASRModel.fromPretrained(modelId: "goldenlink/Qwen3-ASR-0.6B-119ko-bf16",
                                                           cacheDir: dir, offlineMode: true)
        return OnDeviceASR(model: model)
    }

    /// 발화 하나 -> 구간들(발화 시작 기준 초). 빈 구간은 버린다
    func transcribe(_ audio: [Float]) -> [RecognizedSegment] {
        splitChunks(audio).compactMap { r in
            let text = model.transcribe(audio: Array(audio[r]), sampleRate: GoldenLinkCore.sampleRate,
                                        language: "Korean", maxTokens: 256)
                .trimmingCharacters(in: .whitespacesAndNewlines)
            return text.isEmpty ? nil : RecognizedSegment(start: Double(r.lowerBound) / Double(GoldenLinkCore.sampleRate),
                                                          end: Double(r.upperBound) / Double(GoldenLinkCore.sampleRate), text: text)
        }
    }
}
