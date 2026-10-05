import CoreML
import Foundation
import GoldenLinkCore

/// MF_BERT 온디바이스(AI 처리, 생성형 아님). convert/mf_bert_split.py의 run_split()과 같은 순서:
///   조각마다 MFBertEncoder -> keep 행만 골라 이어 붙임 -> MFBertHeads -> decode(규칙 해석 포함)
/// fp32 그대로 돈다 — Neural Engine은 fp32를 못 돌려 CPU+GPU로 고정한다(.all이면 fp16으로 떨어져 결과가 바뀔 수 있다).
final class MFBertRunner {
    private let encoder: MLModel
    private let heads: MLModel
    let tokenizer: WordPieceTokenizer

    /// 앱 번들 Models/의 MFBertEncoder.mlpackage · MFBertHeads.mlpackage · tokenizer.json.
    /// Models/는 폴더 참조라 Xcode가 .mlpackage를 컴파일하지 않는다 — 첫 실행 때 기기에서 컴파일해 Application Support에 두고 재사용한다.
    init(bundle: Bundle = .main) throws {
        let config = MLModelConfiguration()
        config.computeUnits = .cpuAndGPU
        func url(_ name: String, _ ext: String) throws -> URL {
            guard let u = bundle.url(forResource: name, withExtension: ext, subdirectory: "Models") else {
                throw RunnerError.missing("Models/\(name).\(ext)")
            }
            return u
        }
        encoder = try MLModel(contentsOf: Self.compiled(url("MFBertEncoder", "mlpackage")), configuration: config)
        heads = try MLModel(contentsOf: Self.compiled(url("MFBertHeads", "mlpackage")), configuration: config)
        tokenizer = try WordPieceTokenizer(tokenizerJSON: url("tokenizer", "json"))
    }

    /// .mlpackage -> 컴파일된 .mlmodelc (앱 버전·파일 크기가 같으면 캐시 사용)
    private static func compiled(_ package: URL) throws -> URL {
        let fm = FileManager.default
        let cache = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0].appendingPathComponent("CompiledModels")
        try fm.createDirectory(at: cache, withIntermediateDirectories: true)
        let weights = package.appendingPathComponent("Data/com.apple.CoreML/weights/weight.bin")
        let size = (try? fm.attributesOfItem(atPath: weights.path)[.size] as? Int) ?? 0
        let version = Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "0"
        let target = cache.appendingPathComponent("\(package.deletingPathExtension().lastPathComponent)-\(version)-\(size).mlmodelc")
        if fm.fileExists(atPath: target.path) { return target }
        let tmp = try MLModel.compileModel(at: package)
        try? fm.removeItem(at: target)
        try fm.moveItem(at: tmp, to: target)
        return target
    }

    enum RunnerError: LocalizedError {
        case missing(String)
        var errorDescription: String? {
            switch self { case let .missing(f): "앱 번들에 \(f)가 없습니다 — README '2. 모델 변환' 참고" }
        }
    }

    /// 통화 텍스트 1건 -> v2 summary
    func extract(_ text: String) throws -> JSONValue {
        let c = chunkText(text, tokenizer: tokenizer)
        let total = c.keep.reduce(0) { $0 + $1.count }

        // 조각마다 인코더 -> (N, L, H)에서 keep 행만 (N, total, H)로 모은다
        var hidden: MLMultiArray?
        var n = 0, h = 0, t = 0
        for (chunk, keep) in zip(c.chunks, c.keep) {
            let ids = try MLMultiArray(shape: [1, NSNumber(value: chunk.count)], dataType: .int32)
            for (i, id) in chunk.enumerated() { ids[i] = NSNumber(value: Int32(id)) }
            let out = try encoder.prediction(from: MLDictionaryFeatureProvider(dictionary: ["input_ids": ids]))
            let layer = out.featureValue(for: "hidden")!.multiArrayValue!
            if hidden == nil {
                n = layer.shape[0].intValue
                h = layer.shape[2].intValue
                hidden = try MLMultiArray(shape: [NSNumber(value: n), NSNumber(value: total), NSNumber(value: h)], dataType: .float32)
            }
            copyRows(from: layer, rows: keep, into: hidden!, at: t, n: n, h: h)
            t += keep.count
        }

        let out = try heads.prediction(from: MLDictionaryFeatureProvider(dictionary: ["hidden": hidden!]))
        var logits: [String: [Float]] = [:]
        for name in Labels.shared.sentenceHeads {
            guard let a = out.featureValue(for: name)?.multiArrayValue else { throw RunnerError.missing("헤드 출력 \(name)") }
            logits[name] = floats(a)
        }
        // spans (1, T, 태그 수) -> 토큰별 argmax
        let spans = out.featureValue(for: "spans")!.multiArrayValue!
        let tagCount = spans.shape[2].intValue
        let flat = floats(spans)
        let tags = (0..<total).map { i in
            var best = 0
            for k in 1..<tagCount where flat[i * tagCount + k] > flat[i * tagCount + best] { best = k }
            return best
        }
        return decode(text: text, logits: MFBertLogits(heads: logits, spanTags: tags), offsets: c.offsets)
    }

    /// 출력 배열은 연속 메모리가 아닐 수 있어 strides로 읽는다
    private func floats(_ a: MLMultiArray) -> [Float] {
        let shape = a.shape.map(\.intValue), strides = a.strides.map(\.intValue)
        let count = shape.reduce(1, *)
        var out = [Float](repeating: 0, count: count)
        a.withUnsafeBufferPointer(ofType: Float.self) { p in
            for flat in 0..<count {
                var rem = flat, off = 0
                for d in stride(from: shape.count - 1, through: 0, by: -1) {
                    off += (rem % shape[d]) * strides[d]
                    rem /= shape[d]
                }
                out[flat] = p[off]
            }
        }
        return out
    }

    private func copyRows(from src: MLMultiArray, rows: [Int], into dst: MLMultiArray, at t0: Int, n: Int, h: Int) {
        let ss = src.strides.map(\.intValue), ds = dst.strides.map(\.intValue)
        src.withUnsafeBufferPointer(ofType: Float.self) { s in
            dst.withUnsafeMutableBufferPointer(ofType: Float.self) { d, _ in
                for layer in 0..<n {
                    for (j, row) in rows.enumerated() {
                        let so = layer * ss[0] + row * ss[1], dO = layer * ds[0] + (t0 + j) * ds[1]
                        for k in 0..<h { d[dO + k * ds[2]] = s[so + k * ss[2]] }
                    }
                }
            }
        }
    }
}
